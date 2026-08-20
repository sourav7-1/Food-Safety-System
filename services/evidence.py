import hashlib
import os
import shutil
import uuid
from pathlib import Path

from flask import abort, current_app, request, send_file
from werkzeug.utils import secure_filename

from extensions import db
from models import EvidenceAuditLog


class EvidenceValidationError(Exception):
    """Raised when an uploaded file fails extension, size, or signature
    checks. The message is safe to show directly to the user."""


# Extensions this app will never accept, checked defensively even though
# the allowlists below already exclude everything not explicitly listed.
_EXPLICITLY_DENIED_EXTENSIONS = {
    "exe", "bat", "cmd", "sh", "php", "py", "js", "html", "htm", "svg",
}

_MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "pdf": "application/pdf",
}


def _looks_like_jpeg(header):
    return header[:3] == b"\xff\xd8\xff"


def _looks_like_png(header):
    return header[:8] == b"\x89PNG\r\n\x1a\n"


def _looks_like_webp(header):
    return header[:4] == b"RIFF" and header[8:12] == b"WEBP"


def _looks_like_isobmff(header):
    # Shared "ftyp" box signature for the whole ISO base-media family:
    # mp4, mov, and m4a all start this way regardless of their specific
    # brand, so this is deliberately loose -- the extension picks the
    # category, this just confirms it's a real ISO-BMFF container.
    return header[4:8] == b"ftyp"


def _looks_like_webm(header):
    # EBML header, shared by WebM/Matroska -- covers both video and
    # audio-only .webm since both use the same container family.
    return header[:4] == b"\x1a\x45\xdf\xa3"


def _looks_like_mp3(header):
    if header[:3] == b"ID3":
        return True
    return len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0


def _looks_like_wav(header):
    return header[:4] == b"RIFF" and header[8:12] == b"WAVE"


def _looks_like_pdf(header):
    return header[:5] == b"%PDF-"


# extension -> (category, size-limit config key, magic-byte signature check)
EVIDENCE_RULES = {
    "jpg": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_jpeg),
    "jpeg": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_jpeg),
    "png": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_png),
    "webp": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_webp),
    "mp4": ("video", "EVIDENCE_MAX_VIDEO_MB", _looks_like_isobmff),
    "mov": ("video", "EVIDENCE_MAX_VIDEO_MB", _looks_like_isobmff),
    "webm": ("video", "EVIDENCE_MAX_VIDEO_MB", _looks_like_webm),
    "mp3": ("audio", "EVIDENCE_MAX_AUDIO_MB", _looks_like_mp3),
    "wav": ("audio", "EVIDENCE_MAX_AUDIO_MB", _looks_like_wav),
    "m4a": ("audio", "EVIDENCE_MAX_AUDIO_MB", _looks_like_isobmff),
    "pdf": ("document", "EVIDENCE_MAX_DOCUMENT_MB", _looks_like_pdf),
}

CORRECTIVE_EVIDENCE_RULES = {
    "png": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_png),
    "jpg": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_jpeg),
    "jpeg": ("image", "EVIDENCE_MAX_IMAGE_MB", _looks_like_jpeg),
    "pdf": ("document", "EVIDENCE_MAX_DOCUMENT_MB", _looks_like_pdf),
}


def _hash_and_sniff(stream, chunk_size=1024 * 1024, header_size=64):
    """Stream-hash the file (SHA-256) and capture its first bytes for
    signature sniffing, without loading the whole file into memory."""
    stream.seek(0)
    sha256 = hashlib.sha256()
    header = b""
    total = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if len(header) < header_size:
            header += chunk[: header_size - len(header)]
        sha256.update(chunk)
        total += len(chunk)
    stream.seek(0)
    return sha256.hexdigest(), header, total


def _save_stream(stream, destination):
    """Write to a temp file in the same directory, then atomically move it
    into place, so nothing ever reads a partially-written file."""
    stream.seek(0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(destination.name + ".part")
    try:
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(stream, out)
        os.replace(tmp_path, destination)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _storage_root():
    return Path(current_app.config["EVIDENCE_STORAGE_PATH"])


def _split_extension(filename):
    original_name = secure_filename(filename or "")
    if not original_name or "." not in original_name:
        raise EvidenceValidationError(
            "The file must have a valid name and extension."
        )
    return original_name, original_name.rsplit(".", 1)[1].lower()


def _validate_size(original_name, size, size_config_key):
    if size == 0:
        raise EvidenceValidationError(f"{original_name} is empty.")
    max_mb = current_app.config.get(size_config_key, 10)
    max_bytes = max_mb * 1024 * 1024
    if size > max_bytes:
        raise EvidenceValidationError(
            f"{original_name} is too large "
            f"({size / (1024 * 1024):.1f} MB). Maximum for this file type "
            f"is {max_mb} MB."
        )


def validate_and_store_complaint_evidence(file_storage, complaint_id):
    """Validate one uploaded complaint-evidence file and save it to private
    storage. Returns a dict of ComplaintEvidence column values. Raises
    EvidenceValidationError (nothing written to disk) if any check fails."""
    if file_storage is None or not file_storage.filename:
        raise EvidenceValidationError("No file was provided.")

    original_name, extension = _split_extension(file_storage.filename)
    if extension in _EXPLICITLY_DENIED_EXTENSIONS or extension not in EVIDENCE_RULES:
        raise EvidenceValidationError(
            f"'{original_name}' is not an allowed evidence type. Allowed: "
            "JPG, JPEG, PNG, WEBP, MP4, WEBM, MOV, MP3, WAV, M4A, PDF."
        )
    category, size_config_key, signature_check = EVIDENCE_RULES[extension]

    file_hash, header, size = _hash_and_sniff(file_storage.stream)
    _validate_size(original_name, size, size_config_key)

    if not signature_check(header):
        raise EvidenceValidationError(
            f"'{original_name}' does not look like a valid .{extension} "
            "file."
        )

    stored_name = f"{uuid.uuid4().hex}.{extension}"
    relative_path = str(Path("complaints") / str(complaint_id) / stored_name)
    _save_stream(file_storage.stream, _storage_root() / relative_path)

    return {
        "file_name": original_name,
        "stored_file_name": stored_name,
        "file_type": category,
        "mime_type": _MIME_TYPES[extension],
        "file_size": size,
        "storage_path": relative_path,
        "file_hash": file_hash,
    }


def validate_and_store_corrective_evidence(file_storage):
    """Same validation approach as complaint evidence, scoped to the
    smaller set of types corrective-action proof already accepted (PNG,
    JPG, JPEG, PDF). Returns the stored filename to save on
    CorrectiveAction.evidence_path."""
    if file_storage is None or not file_storage.filename:
        raise EvidenceValidationError("Evidence file is required.")

    original_name, extension = _split_extension(file_storage.filename)
    if extension not in CORRECTIVE_EVIDENCE_RULES:
        raise EvidenceValidationError("Evidence must be PNG, JPG, JPEG, or PDF.")
    _category, size_config_key, signature_check = CORRECTIVE_EVIDENCE_RULES[extension]

    file_hash, header, size = _hash_and_sniff(file_storage.stream)
    _validate_size(original_name, size, size_config_key)

    if not signature_check(header):
        raise EvidenceValidationError(
            f"'{original_name}' does not look like a valid .{extension} "
            "file."
        )

    stored_name = f"{uuid.uuid4().hex}.{extension}"
    _save_stream(file_storage.stream, _storage_root() / "corrective_actions" / stored_name)
    return stored_name


def validate_and_store_dispute_evidence(file_storage, dispute_id):
    """Same validation approach as complaint evidence (image/video/audio/
    document), scoped to inspection-dispute proof files. Returns a dict of
    InspectionDisputeEvidence column values. Raises EvidenceValidationError
    (nothing written to disk) if any check fails."""
    if file_storage is None or not file_storage.filename:
        raise EvidenceValidationError("No file was provided.")

    original_name, extension = _split_extension(file_storage.filename)
    if extension in _EXPLICITLY_DENIED_EXTENSIONS or extension not in EVIDENCE_RULES:
        raise EvidenceValidationError(
            f"'{original_name}' is not an allowed evidence type. Allowed: "
            "JPG, JPEG, PNG, WEBP, MP4, WEBM, MOV, MP3, WAV, M4A, PDF."
        )
    category, size_config_key, signature_check = EVIDENCE_RULES[extension]

    file_hash, header, size = _hash_and_sniff(file_storage.stream)
    _validate_size(original_name, size, size_config_key)

    if not signature_check(header):
        raise EvidenceValidationError(
            f"'{original_name}' does not look like a valid .{extension} "
            "file."
        )

    stored_name = f"{uuid.uuid4().hex}.{extension}"
    relative_path = str(
        Path("inspection_disputes") / str(dispute_id) / stored_name
    )
    _save_stream(file_storage.stream, _storage_root() / relative_path)

    return {
        "file_name": original_name,
        "stored_file_name": stored_name,
        "file_type": category,
        "mime_type": _MIME_TYPES[extension],
        "file_size": size,
        "storage_path": relative_path,
        "file_hash": file_hash,
    }


def delete_stored_complaint_files(relative_paths):
    """Best-effort cleanup used when a complaint submission fails partway
    through -- never leave orphan files behind for rows that never made it
    into the database."""
    for relative_path in relative_paths:
        path = _storage_root() / relative_path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning(
                "Could not remove orphaned evidence file: %s", relative_path
            )


def delete_corrective_evidence_file(stored_file_name):
    path = _storage_root() / "corrective_actions" / stored_file_name
    try:
        path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning(
            "Could not remove orphaned corrective-action evidence file: %s",
            stored_file_name,
        )


def serve_complaint_evidence(evidence, as_attachment=False):
    path = _storage_root() / evidence.storage_path
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype=evidence.mime_type,
        as_attachment=as_attachment,
        download_name=evidence.file_name,
        conditional=True,
    )


def serve_dispute_evidence(evidence, as_attachment=False):
    path = _storage_root() / evidence.storage_path
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype=evidence.mime_type,
        as_attachment=as_attachment,
        download_name=evidence.file_name,
        conditional=True,
    )


def serve_corrective_evidence(stored_file_name):
    path = _storage_root() / "corrective_actions" / stored_file_name
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, conditional=True)


def record_audit(evidence, user, action, details=None):
    db.session.add(
        EvidenceAuditLog(
            evidence_id=evidence.evidence_id,
            user_id=getattr(user, "user_id", None),
            action=action,
            ip_address=request.remote_addr,
            user_agent=(request.headers.get("User-Agent") or "")[:255],
            details=details,
        )
    )
    db.session.commit()
