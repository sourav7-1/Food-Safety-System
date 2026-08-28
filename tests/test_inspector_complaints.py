import io
import shutil
import tempfile
import unittest

from app import create_app
from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintEvidence,
    ComplaintType,
    Inspector,
    Notification,
    Role,
    Stall,
    User,
    Vendor,
)


JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32


class InspectorComplaintTestConfig:
    TESTING = True
    SECRET_KEY = "inspector-complaint-test-secret"
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


class InspectorComplaintTests(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp(prefix="inspector-complaint-test-")
        config = type(
            "Cfg",
            (InspectorComplaintTestConfig,),
            {"EVIDENCE_STORAGE_PATH": self.storage_dir},
        )
        self.app = create_app(config)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="admin", is_admin_tier=True),
                    Role(role_name="inspector"),
                    Role(role_name="student"),
                    Role(role_name="vendor"),
                ]
            )
            db.session.commit()

            inspector_role = Role.query.filter_by(role_name="inspector").one()
            student_role = Role.query.filter_by(role_name="student").one()
            vendor_role = Role.query.filter_by(role_name="vendor").one()

            area_a = Area(area_name="Area A", city="Test City", zone="")
            area_b = Area(area_name="Area B", city="Test City", zone="")
            db.session.add_all([area_a, area_b])
            db.session.flush()

            inspector_user = User(
                role_id=inspector_role.role_id,
                full_name="Field Inspector",
                email="inspector@example.test",
                status="active",
            )
            inspector_user.set_password("SecurePass123")

            student_user = User(
                role_id=student_role.role_id,
                full_name="Reporting Student",
                email="student@example.test",
                status="active",
            )
            student_user.set_password("SecurePass123")

            vendor_user = User(
                role_id=vendor_role.role_id,
                full_name="Stall Vendor",
                email="vendor@example.test",
                status="active",
            )
            vendor_user.set_password("SecurePass123")

            db.session.add_all([inspector_user, student_user, vendor_user])
            db.session.flush()

            inspector = Inspector(
                user_id=inspector_user.user_id,
                employee_code="INS-1",
                assigned_area_id=area_a.area_id,
            )
            db.session.add(inspector)

            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Test Vendor",
                license_number="LIC-1",
            )
            db.session.add(vendor)
            db.session.flush()

            stall_in_area = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area_a.area_id,
                stall_name="In-Area Stall",
                stall_code="TS-1",
                address="123 Test Street",
                status="active",
            )
            stall_out_of_area = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area_b.area_id,
                stall_name="Out-of-Area Stall",
                stall_code="TS-2",
                address="456 Test Street",
                status="active",
            )
            db.session.add_all([stall_in_area, stall_out_of_area])
            db.session.flush()

            complaint_type = ComplaintType(
                type_name="Poor hygiene", severity_level="medium"
            )
            db.session.add(complaint_type)
            db.session.flush()

            complaint_in_area = Complaint(
                stall_id=stall_in_area.stall_id,
                complaint_type_id=complaint_type.complaint_type_id,
                submitted_by_user_id=student_user.user_id,
                title="Uncovered food",
                description="Food was left uncovered on the counter.",
                status="submitted",
            )
            complaint_out_of_area = Complaint(
                stall_id=stall_out_of_area.stall_id,
                complaint_type_id=complaint_type.complaint_type_id,
                submitted_by_user_id=student_user.user_id,
                title="Dirty utensils",
                description="Utensils looked unwashed.",
                status="submitted",
            )
            db.session.add_all([complaint_in_area, complaint_out_of_area])
            db.session.commit()

            self.inspector_user_id = inspector_user.user_id
            self.student_user_id = student_user.user_id
            self.complaint_in_area_id = complaint_in_area.complaint_id
            self.complaint_out_of_area_id = complaint_out_of_area.complaint_id

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

    # -- visibility / scoping ---------------------------------------------

    def test_inspector_list_only_shows_own_area(self):
        self._csrf_session(self.inspector_user_id)
        response = self.client.get("/inspector/complaints/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Uncovered food", body)
        self.assertNotIn("Dirty utensils", body)

    def test_inspector_can_view_complaint_in_own_area(self):
        self._csrf_session(self.inspector_user_id)
        response = self.client.get(
            f"/inspector/complaints/{self.complaint_in_area_id}"
        )
        self.assertEqual(response.status_code, 200)

    def test_inspector_blocked_from_complaint_outside_area(self):
        self._csrf_session(self.inspector_user_id)
        response = self.client.get(
            f"/inspector/complaints/{self.complaint_out_of_area_id}"
        )
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_access_inspector_complaint_routes(self):
        self._csrf_session(self.student_user_id)
        response = self.client.get("/inspector/complaints/")
        self.assertEqual(response.status_code, 403)

    # -- status transitions -------------------------------------------------

    def test_inspector_can_move_submitted_to_under_review(self):
        token = self._csrf_session(self.inspector_user_id)
        response = self.client.post(
            f"/inspector/complaints/{self.complaint_in_area_id}",
            data={
                "_csrf_token": token,
                "status": "under_review",
                "admin_response": "Looking into this.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            complaint = db.session.get(Complaint, self.complaint_in_area_id)
            self.assertEqual(complaint.status, "under_review")
            self.assertEqual(complaint.admin_response, "Looking into this.")
            self.assertEqual(
                Notification.query.filter_by(
                    user_id=self.student_user_id
                ).count(),
                1,
            )

    def test_resolving_without_inspector_evidence_is_rejected(self):
        token = self._csrf_session(self.inspector_user_id)
        # under_review -> resolved requires an inspector-uploaded evidence
        # file; move there first since submitted -> resolved isn't even a
        # legal transition.
        self.client.post(
            f"/inspector/complaints/{self.complaint_in_area_id}",
            data={"_csrf_token": token, "status": "under_review"},
        )
        response = self.client.post(
            f"/inspector/complaints/{self.complaint_in_area_id}",
            data={"_csrf_token": token, "status": "resolved"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            complaint = db.session.get(Complaint, self.complaint_in_area_id)
            self.assertEqual(complaint.status, "under_review")

    def test_resolving_with_inspector_evidence_succeeds(self):
        token = self._csrf_session(self.inspector_user_id)
        self.client.post(
            f"/inspector/complaints/{self.complaint_in_area_id}",
            data={"_csrf_token": token, "status": "under_review"},
        )
        upload_response = self.client.post(
            f"/inspector/complaints/{self.complaint_in_area_id}/evidence",
            data={
                "_csrf_token": token,
                "evidence": [(io.BytesIO(JPEG_BYTES), "followup.jpg")],
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload_response.status_code, 302)
        with self.app.app_context():
            evidence = ComplaintEvidence.query.filter_by(
                complaint_id=self.complaint_in_area_id
            ).one()
            self.assertEqual(evidence.verification_status, "verified")
            self.assertEqual(evidence.uploaded_by, self.inspector_user_id)

        resolve_response = self.client.post(
            f"/inspector/complaints/{self.complaint_in_area_id}",
            data={
                "_csrf_token": token,
                "status": "resolved",
                "admin_response": "Fixed on-site, verified with photo.",
            },
        )
        self.assertEqual(resolve_response.status_code, 302)
        with self.app.app_context():
            complaint = db.session.get(Complaint, self.complaint_in_area_id)
            self.assertEqual(complaint.status, "resolved")
            self.assertIsNotNone(complaint.resolved_at)

    def test_inspector_cannot_upload_evidence_outside_area(self):
        token = self._csrf_session(self.inspector_user_id)
        response = self.client.post(
            f"/inspector/complaints/{self.complaint_out_of_area_id}/evidence",
            data={
                "_csrf_token": token,
                "evidence": [(io.BytesIO(JPEG_BYTES), "followup.jpg")],
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)

    # -- evidence verification of the student's own upload -----------------

    def test_inspector_can_verify_student_evidence(self):
        with self.app.app_context():
            complaint = db.session.get(Complaint, self.complaint_in_area_id)
            evidence = ComplaintEvidence(
                complaint_id=complaint.complaint_id,
                uploaded_by=self.student_user_id,
                verification_status="pending",
                file_name="proof.jpg",
                stored_file_name="stored.jpg",
                file_type="image",
                mime_type="image/jpeg",
                file_size=100,
                storage_path="complaints/x/stored.jpg",
                file_hash="hash",
            )
            db.session.add(evidence)
            db.session.commit()
            evidence_id = evidence.evidence_id

        token = self._csrf_session(self.inspector_user_id)
        response = self.client.post(
            f"/inspector/complaints/evidence/{evidence_id}/status",
            data={"_csrf_token": token, "verification_status": "verified"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            evidence = db.session.get(ComplaintEvidence, evidence_id)
            self.assertEqual(evidence.verification_status, "verified")
            self.assertEqual(evidence.verified_by, self.inspector_user_id)


if __name__ == "__main__":
    unittest.main()
