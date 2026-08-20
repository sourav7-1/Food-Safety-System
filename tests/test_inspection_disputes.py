import io
import shutil
import tempfile
import unittest
from datetime import datetime

from app import create_app
from extensions import db
from models import (
    Area,
    Inspection,
    InspectionDispute,
    InspectionDisputeEvidence,
    Inspector,
    Role,
    Stall,
    User,
    Vendor,
)


JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32
EXE_BYTES = b"MZ" + b"\x00" * 32


class DisputeTestConfig:
    TESTING = True
    SECRET_KEY = "dispute-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    EVIDENCE_STORAGE_PATH = None
    EVIDENCE_MAX_FILES_PER_COMPLAINT = 5
    EVIDENCE_MAX_IMAGE_MB = 1
    EVIDENCE_MAX_AUDIO_MB = 1
    EVIDENCE_MAX_VIDEO_MB = 1
    EVIDENCE_MAX_DOCUMENT_MB = 1


class InspectionDisputeTests(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp(prefix="dispute-test-")
        config = type(
            "Cfg", (DisputeTestConfig,), {"EVIDENCE_STORAGE_PATH": self.storage_dir}
        )
        self.app = create_app(config)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="admin", is_admin_tier=True),
                    Role(role_name="vendor"),
                    Role(role_name="inspector"),
                    Role(role_name="customer"),
                ]
            )
            db.session.commit()

            admin_role = Role.query.filter_by(role_name="admin").one()
            vendor_role = Role.query.filter_by(role_name="vendor").one()
            inspector_role = Role.query.filter_by(role_name="inspector").one()

            self.admin = User(
                role_id=admin_role.role_id,
                full_name="Admin",
                email="admin@example.test",
                status="active",
                is_super_admin=True,
            )
            self.admin.set_password("SecurePass123")

            vendor_user = User(
                role_id=vendor_role.role_id,
                full_name="Vendor Owner",
                email="vendor@example.test",
                status="active",
            )
            vendor_user.set_password("SecurePass123")

            other_vendor_user = User(
                role_id=vendor_role.role_id,
                full_name="Other Vendor",
                email="other-vendor@example.test",
                status="active",
            )
            other_vendor_user.set_password("SecurePass123")

            inspector_user = User(
                role_id=inspector_role.role_id,
                full_name="Inspector One",
                email="inspector@example.test",
                status="active",
            )
            inspector_user.set_password("SecurePass123")

            db.session.add_all(
                [self.admin, vendor_user, other_vendor_user, inspector_user]
            )
            db.session.flush()

            area = Area(area_name="Test Area", city="Test City", zone="")
            db.session.add(area)
            db.session.flush()

            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Test Vendor",
                license_number="LIC-1",
            )
            other_vendor = Vendor(
                user_id=other_vendor_user.user_id,
                business_name="Other Vendor Co",
                license_number="LIC-2",
            )
            db.session.add_all([vendor, other_vendor])
            db.session.flush()

            stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area.area_id,
                stall_name="Test Stall",
                stall_code="TS-1",
                address="123 Test Street",
                status="active",
            )
            db.session.add(stall)
            db.session.flush()

            inspector = Inspector(
                user_id=inspector_user.user_id, employee_code="INS-1"
            )
            db.session.add(inspector)
            db.session.flush()

            inspection = Inspection(
                stall_id=stall.stall_id,
                inspector_id=inspector.inspector_id,
                inspection_date=datetime(2026, 1, 10),
                overall_score=90,
                risk_level="low",
                status="approved",
            )
            db.session.add(inspection)
            db.session.commit()

            self.stall_id = stall.stall_id
            self.inspection_id = inspection.inspection_id
            self.vendor_id = vendor.vendor_id
            self.other_vendor_id = other_vendor.vendor_id
            self.vendor_user_id = vendor_user.user_id
            self.other_vendor_user_id = other_vendor_user.user_id
            self.admin_id = self.admin.user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(self.storage_dir, ignore_errors=True)

    def _csrf_session(self, user_id):
        token = "test-csrf-token"
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return token

    def _submit_dispute(self, user_id, files=None, **overrides):
        token = self._csrf_session(user_id)
        data = {
            "_csrf_token": token,
            "reason": "The reported score does not match what I was told on-site.",
        }
        data.update(overrides)
        if files:
            data["evidence"] = files
        return self.client.post(
            f"/vendor/stalls/{self.stall_id}/inspections/{self.inspection_id}/dispute",
            data=data,
            content_type="multipart/form-data",
        )

    def test_vendor_can_file_dispute_with_evidence(self):
        response = self._submit_dispute(
            self.vendor_user_id,
            files=[(io.BytesIO(JPEG_BYTES), "proof.jpg")],
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            dispute = InspectionDispute.query.one()
            self.assertEqual(dispute.status, "submitted")
            self.assertEqual(dispute.vendor_id, self.vendor_id)
            self.assertEqual(len(dispute.evidence), 1)
            evidence = InspectionDisputeEvidence.query.one()
            self.assertEqual(evidence.file_type, "image")

    def test_dispute_requires_reason(self):
        response = self._submit_dispute(self.vendor_user_id, reason="")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(InspectionDispute.query.count(), 0)

    def test_disallowed_extension_rejected(self):
        response = self._submit_dispute(
            self.vendor_user_id,
            files=[(io.BytesIO(EXE_BYTES), "virus.exe")],
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(InspectionDispute.query.count(), 0)

    def test_vendor_cannot_dispute_another_vendors_inspection(self):
        response = self._submit_dispute(self.other_vendor_user_id)
        self.assertEqual(response.status_code, 404)

    def test_admin_can_view_and_resolve_dispute(self):
        self._submit_dispute(self.vendor_user_id)
        with self.app.app_context():
            dispute = InspectionDispute.query.one()
            dispute_id = dispute.dispute_id

        token = self._csrf_session(self.admin_id)
        list_response = self.client.get("/admin/inspection-disputes")
        self.assertEqual(list_response.status_code, 200)

        resolve_response = self.client.post(
            f"/admin/inspection-disputes/{dispute_id}",
            data={
                "_csrf_token": token,
                "status": "resolved",
                "admin_response": "Score confirmed correct after review.",
            },
        )
        self.assertEqual(resolve_response.status_code, 302)
        with self.app.app_context():
            dispute = db.session.get(InspectionDispute, dispute_id)
            self.assertEqual(dispute.status, "resolved")
            self.assertIsNotNone(dispute.resolved_at)
            self.assertEqual(
                dispute.admin_response, "Score confirmed correct after review."
            )

    def test_vendor_cannot_access_admin_dispute_list(self):
        self._csrf_session(self.vendor_user_id)
        response = self.client.get("/admin/inspection-disputes")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
