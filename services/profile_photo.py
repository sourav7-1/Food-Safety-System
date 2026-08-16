import os
import shutil
import uuid
from io import BytesIO
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from services.evidence import _looks_like_jpeg, _looks_like_png, _looks_like_webp


class ProfilePhotoValidationError(Exception):
    """Raised when an uploaded profile photo fails validation. The message
    is safe to show directly to the user."""


# Reuses the same magic-byte signature checks as complaint/corrective
# evidence (services/evidence.py) instead of duplicating them.
_SIGNATURE_CHECKS = {
    "jpg": _looks_like_jpeg,
    "jpeg": _looks_like_jpeg,
    "png": _looks_like_png,
    "webp": _looks_like_webp,
}


def _storage_root():
    return Path(current_app.config["PROFILE_PHOTO_STORAGE_PATH"])


def _split_extension(filename):
    original_name = secure_filename(filename or "")
    if not original_name or "." not in original_name:
        raise ProfilePhotoValidationError(
            "The file must have a valid name and extension."
        )
    return original_name.rsplit(".", 1)[1].lower()


def save_profile_photo(file_storage):
    """Validate an uploaded profile photo and save a resized, compressed
    JPEG copy under static/uploads/profile_photos/. Returns the
    root-relative URL to store on User.profile_photo_url (e.g.
    "/static/uploads/profile_photos/<name>.jpg"). Raises
    ProfilePhotoValidationError -- with nothing written to disk -- if any
    check fails.
    """
    if file_storage is None or not file_storage.filename:
        raise ProfilePhotoValidationError("No photo was provided.")

    extension = _split_extension(file_storage.filename)
    signature_check = _SIGNATURE_CHECKS.get(extension)
    if signature_check is None:
        raise ProfilePhotoValidationError(
            "Profile photos must be JPG, JPEG, PNG, or WEBP."
        )

    file_storage.stream.seek(0)
    data = file_storage.stream.read()
    file_storage.stream.seek(0)

    if not data:
        raise ProfilePhotoValidationError("The uploaded photo is empty.")

    max_mb = current_app.config.get("PROFILE_PHOTO_MAX_MB", 5)
    if len(data) > max_mb * 1024 * 1024:
        raise ProfilePhotoValidationError(
            f"Photo is too large ({len(data) / (1024 * 1024):.1f} MB). "
            f"Maximum is {max_mb} MB."
        )

    if not signature_check(data[:64]):
        raise ProfilePhotoValidationError(
            f"This file does not look like a valid .{extension} image."
        )

    # A real decode (not just a magic-byte peek) catches truncated or
    # otherwise-crafted files that pass the signature check but aren't a
    # genuinely loadable image.
    try:
        probe = Image.open(BytesIO(data))
        probe.verify()
        image = Image.open(BytesIO(data))  # verify() invalidates `probe`
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ProfilePhotoValidationError(
            "This file is not a valid, readable image."
        ) from error

    if image.mode != "RGB":
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            background.paste(image.convert("RGBA"), mask=image.convert("RGBA").split()[-1])
        else:
            background.paste(image.convert("RGB"))
        image = background

    max_dimension = current_app.config.get("PROFILE_PHOTO_MAX_DIMENSION", 512)
    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True)
    buffer.seek(0)

    stored_name = f"{uuid.uuid4().hex}.jpg"
    destination = _storage_root() / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(destination.name + ".part")
    try:
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(buffer, out)
        os.replace(tmp_path, destination)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return f"/static/uploads/profile_photos/{stored_name}"


def delete_profile_photo(photo_url):
    """Best-effort cleanup. photo_url is the root-relative URL stored on
    User.profile_photo_url."""
    if not photo_url:
        return
    filename = os.path.basename(photo_url)
    path = _storage_root() / filename
    try:
        path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning(
            "Could not remove old profile photo file: %s", filename
        )
