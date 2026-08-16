import io
import shutil
import tempfile
import unittest

from app import create_app
from extensions import db
from models import Area, Complaint, ComplaintEvidence, ComplaintType, Role, Stall, User, Vendor


# Minimal, real magic-byte headers for each accepted type -- enough to pass
# signature sniffing without needing full, valid media files.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 32
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
MP3_BYTES = b"ID3" + b"\x00" * 32
WAV_BYTES = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 32


class EvidenceTestConfig:
    TESTING = True
    SECRET_KEY = "evidence-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    EVIDENCE_STORAGE_PATH = None  # set per-test to a temp dir
    EVIDENCE_MAX_FILES_PER_COMPLAINT = 5
    EVIDENCE_MAX_IMAGE_MB = 1
    EVIDENCE_MAX_AUDIO_MB = 1
    EVIDENCE_MAX_VIDEO_MB = 1
    EVIDENCE_MAX_DOCUMENT_MB = 1


class ComplaintEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp(prefix="evidence-test-")
        config = type(
            "Cfg", (EvidenceTestConfig,), {"EVIDENCE_STORAGE_PATH": self.storage_dir}
        )
        self.app = create_app(config)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="admin", is_admin_tier=True),
                    Role(role_name="customer"),
                ]
            )
            db.session.commit()

            customer_role = Role.query.filter_by(role_name="customer").one()
            admin_role = Role.query.filter_by(role_name="admin").one()

            self.customer = User(
                role_id=customer_role.role_id,
                full_name="Reporting Customer",
                email="reporter@example.test",
                status="active",
            )
            self.customer.set_password("SecurePass123")
            self.other_customer = User(
                role_id=customer_role.role_id,
                full_name="Other Customer",
                email="other@example.test",
                status="active",
            )
            self.other_customer.set_password("SecurePass123")
            self.admin = User(
                role_id=admin_role.role_id,
                full_name="Admin",
                email="admin@example.test",
                status="active",
                is_super_admin=True,
            )
            self.admin.set_password("SecurePass123")
            db.session.add_all([self.customer, self.other_customer, self.admin])

            area = Area(area_name="Test Area", city="Test City", zone="")
            db.session.add(area)
            db.session.flush()

            vendor_user = User(
                role_id=customer_role.role_id,
                full_name="Vendor Owner",
                email="vendor@example.test",
                status="active",
            )
            vendor_user.set_password("SecurePass123")
            db.session.add(vendor_user)
            db.session.flush()
            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Test Vendor",
                license_number="LIC-1",
            )
            db.session.add(vendor)
            db.session.flush()

            self.stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area.area_id,
                stall_name="Test Stall",
                stall_code="TS-1",
                address="123 Test Street",
                status="active",
            )
            complaint_type = ComplaintType(
                type_name="Unsafe food handling", severity_level="high"
            )
            db.session.add_all([self.stall, complaint_type])
            db.session.commit()

            self.stall_id = self.stall.stall_id
            self.complaint_type_id = complaint_type.complaint_type_id
            self.customer_id = self.customer.user_id
            self.other_customer_id = self.other_customer.user_id
            self.admin_id = self.admin.user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(self.storage_dir, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _csrf_session(self, user_id):
        token = "test-csrf-token"
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return token

    def _submit_complaint(self, files=None, **overrides):
        token = self._csrf_session(self.customer_id)
        data = {
            "_csrf_token": token,
            "complaint_type_id": str(self.complaint_type_id),
            "title": "Unsafe handling",
            "description": "Food was left uncovered near the road.",
        }
        data.update(overrides)
        if files:
            data["evidence"] = files
        return self.client.post(
            f"/customer/stalls/{self.stall_id}/complaint",
            data=data,
            content_type="multipart/form-data",
        )

    def _first_complaint(self):
        with self.app.app_context():
            return Complaint.query.order_by(Complaint.complaint_id.desc()).first()

    # -- optional evidence / valid uploads --------------------------------

    def test_complaint_submission_without_evidence_still_works(self):
        response = self._submit_complaint()
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            complaint = Complaint.query.one()
            self.assertEqual(complaint.status, "submitted")
            self.assertEqual(len(complaint.evidence), 0)

    def test_valid_uploads_per_type_are_stored_pending(self):
        files = [
            (io.BytesIO(JPEG_BYTES), "photo.jpg"),
            (io.BytesIO(PNG_BYTES), "photo.png"),
            (io.BytesIO(MP4_BYTES), "clip.mp4"),
            (io.BytesIO(MP3_BYTES), "note.mp3"),
            (io.BytesIO(PDF_BYTES), "report.pdf"),
        ]
        response = self._submit_complaint(files=files)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            complaint = Complaint.query.one()
            self.assertEqual(len(complaint.evidence), 5)
            for evidence in complaint.evidence:
                self.assertEqual(evidence.verification_status, "pending")
                self.assertIsNone(evidence.verified_by)
                self.assertEqual(len(evidence.file_hash), 64)

    def test_evidence_never_auto_verified(self):
        self._submit_complaint(files=[(io.BytesIO(JPEG_BYTES), "photo.jpg")])
        with self.app.app_context():
            evidence = ComplaintEvidence.query.one()
            self.assertEqual(evidence.verification_status, "pending")

    # -- rejected uploads --------------------------------------------------

    def test_disallowed_extensions_rejected(self):
        for filename in ("virus.exe", "script.php", "code.js", "image.svg"):
            with self.subTest(filename=filename):
                response = self._submit_complaint(
                    files=[(io.BytesIO(b"whatever content"), filename)]
                )
                self.assertEqual(response.status_code, 302)
                with self.app.app_context():
                    self.assertEqual(Complaint.query.count(), 0)
                    self.assertEqual(ComplaintEvidence.query.count(), 0)

    def test_magic_byte_mismatch_rejected(self):
        # .jpg extension, but the content is plainly not a JPEG.
        response = self._submit_complaint(
            files=[(io.BytesIO(b"not a real jpeg" + b"\x00" * 20), "fake.jpg")]
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Complaint.query.count(), 0)

    def test_oversized_file_rejected_with_no_orphan_row_or_file(self):
        oversized = JPEG_BYTES + b"0" * (2 * 1024 * 1024)  # > 1 MB test limit
        response = self._submit_complaint(
            files=[(io.BytesIO(oversized), "big.jpg")]
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Complaint.query.count(), 0)
            self.assertEqual(ComplaintEvidence.query.count(), 0)
        # No file should have been left behind in storage.
        import os

        complaints_dir = os.path.join(self.storage_dir, "complaints")
        leftover = []
        if os.path.isdir(complaints_dir):
            for root, _dirs, filenames in os.walk(complaints_dir):
                leftover.extend(filenames)
        self.assertEqual(leftover, [])

    def test_too_many_files_rejected(self):
        files = [(io.BytesIO(JPEG_BYTES), f"photo{i}.jpg") for i in range(6)]
        response = self._submit_complaint(files=files)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Complaint.query.count(), 0)

    # -- authorization -------------------------------------------------

    def test_owner_can_download_own_evidence(self):
        self._submit_complaint(files=[(io.BytesIO(JPEG_BYTES), "photo.jpg")])
        with self.app.app_context():
            evidence_id = ComplaintEvidence.query.one().evidence_id
        self._csrf_session(self.customer_id)
        response = self.client.get(f"/customer/evidence/{evidence_id}")
        self.assertEqual(response.status_code, 200)

    def test_other_customer_cannot_download_evidence(self):
        self._submit_complaint(files=[(io.BytesIO(JPEG_BYTES), "photo.jpg")])
        with self.app.app_context():
            evidence_id = ComplaintEvidence.query.one().evidence_id
        self._csrf_session(self.other_customer_id)
        response = self.client.get(f"/customer/evidence/{evidence_id}")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_download_any_evidence(self):
        self._submit_complaint(files=[(io.BytesIO(JPEG_BYTES), "photo.jpg")])
        with self.app.app_context():
            evidence_id = ComplaintEvidence.query.one().evidence_id
        self._csrf_session(self.admin_id)
        response = self.client.get(f"/admin/evidence/{evidence_id}")
        self.assertEqual(response.status_code, 200)

    def test_non_admin_cannot_verify_evidence(self):
        self._submit_complaint(files=[(io.BytesIO(JPEG_BYTES), "photo.jpg")])
        with self.app.app_context():
            evidence_id = ComplaintEvidence.query.one().evidence_id
        token = self._csrf_session(self.customer_id)
        response = self.client.post(
            f"/admin/evidence/{evidence_id}/status",
            data={"_csrf_token": token, "verification_status": "verified"},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            evidence = db.session.get(ComplaintEvidence, evidence_id)
            self.assertEqual(evidence.verification_status, "pending")

    # -- verification workflow -----------------------------------------

    def test_admin_verify_and_reject_are_independent_of_complaint_status(self):
        self._submit_complaint(
            files=[(io.BytesIO(JPEG_BYTES), "a.jpg"), (io.BytesIO(PDF_BYTES), "b.pdf")]
        )
        with self.app.app_context():
            complaint = Complaint.query.one()
            complaint_id = complaint.complaint_id
            original_status = complaint.status
            evidence_ids = [item.evidence_id for item in complaint.evidence]

        token = self._csrf_session(self.admin_id)
        self.client.post(
            f"/admin/evidence/{evidence_ids[0]}/status",
            data={"_csrf_token": token, "verification_status": "verified"},
        )
        response = self.client.post(
            f"/admin/evidence/{evidence_ids[1]}/status",
            data={"_csrf_token": token, "verification_status": "rejected"},
        )
        # No rejection_reason supplied -- must be rejected by the route.
        with self.app.app_context():
            second = db.session.get(ComplaintEvidence, evidence_ids[1])
            self.assertEqual(second.verification_status, "pending")

        self.client.post(
            f"/admin/evidence/{evidence_ids[1]}/status",
            data={
                "_csrf_token": token,
                "verification_status": "rejected",
                "rejection_reason": "Unrelated to the reported stall.",
            },
        )

        with self.app.app_context():
            first = db.session.get(ComplaintEvidence, evidence_ids[0])
            second = db.session.get(ComplaintEvidence, evidence_ids[1])
            complaint = db.session.get(Complaint, complaint_id)

            self.assertEqual(first.verification_status, "verified")
            self.assertIsNotNone(first.verified_by)
            self.assertIsNotNone(first.verified_at)

            self.assertEqual(second.verification_status, "rejected")
            self.assertEqual(
                second.rejection_reason, "Unrelated to the reported stall."
            )

            # The core business rule: evidence decisions never touch the
            # complaint's own status.
            self.assertEqual(complaint.status, original_status)


if __name__ == "__main__":
    unittest.main()
