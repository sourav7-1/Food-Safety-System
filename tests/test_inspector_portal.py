import unittest
from datetime import date, datetime, timedelta

from app import create_app
from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    Inspection,
    Inspector,
    Role,
    Stall,
    User,
    Vendor,
)
from routes.inspector import _inspection_stats


class InspectorPortalTestConfig:
    TESTING = True
    SECRET_KEY = "inspector-portal-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


class _Row:
    """Stand-in for an Inspection row -- _inspection_stats only reads these."""

    def __init__(self, stall_id, score, risk, reinspection):
        self.stall_id = stall_id
        self.overall_score = score
        self.risk_level = risk
        self.reinspection_date = reinspection


class InspectionStatsTests(unittest.TestCase):
    def test_empty(self):
        stats = _inspection_stats([])
        self.assertEqual(stats["total"], 0)
        self.assertIsNone(stats["avg_score"])
        self.assertEqual(stats["stalls"], 0)

    def test_risk_and_due_use_only_the_latest_inspection_per_stall(self):
        yesterday = date.today() - timedelta(days=1)
        # Newest first, as the route supplies them: stall 1 was critical
        # before but its latest inspection is low -- it must not count.
        rows = [
            _Row(1, 90, "low", None),
            _Row(2, 40, "critical", yesterday),
            _Row(1, 30, "critical", yesterday),
        ]
        stats = _inspection_stats(rows)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["stalls"], 2)
        self.assertEqual(stats["high_risk"], 1)
        self.assertEqual(stats["due"], 1)
        self.assertEqual(stats["avg_score"], 53.3)


class InspectorPortalPageTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(InspectorPortalTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="inspector"),
                    Role(role_name="student"),
                    Role(role_name="vendor"),
                ]
            )
            db.session.commit()
            inspector_role = Role.query.filter_by(role_name="inspector").one()
            student_role = Role.query.filter_by(role_name="student").one()
            vendor_role = Role.query.filter_by(role_name="vendor").one()

            area = Area(area_name="Birulia Zone", city="Savar", zone="")
            db.session.add(area)
            db.session.flush()

            inspector_user = User(
                role_id=inspector_role.role_id,
                full_name="Field Inspector",
                email="portal-inspector@example.test",
                status="active",
            )
            inspector_user.set_password("SecurePass123")
            student_user = User(
                role_id=student_role.role_id,
                full_name="Reporting Student",
                email="portal-student@example.test",
                status="active",
            )
            student_user.set_password("SecurePass123")
            vendor_user = User(
                role_id=vendor_role.role_id,
                full_name="Stall Vendor",
                email="portal-vendor@example.test",
                status="active",
            )
            vendor_user.set_password("SecurePass123")
            db.session.add_all([inspector_user, student_user, vendor_user])
            db.session.flush()

            inspector = Inspector(
                user_id=inspector_user.user_id,
                employee_code="INS-9",
                designation="Safety Officer",
                assigned_area_id=area.area_id,
            )
            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Portal Vendor",
                license_number="LIC-PORTAL",
            )
            db.session.add_all([inspector, vendor])
            db.session.flush()

            stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area.area_id,
                stall_name="Rahman Foods",
                stall_code="RF-1",
                address="Near the main gate",
                status="active",
            )
            db.session.add(stall)
            db.session.flush()

            db.session.add(
                Inspection(
                    stall_id=stall.stall_id,
                    inspector_id=inspector.inspector_id,
                    inspection_date=datetime(2026, 8, 28, 19, 18),
                    overall_score=92,
                    risk_level="low",
                    status="submitted",
                    remarks="Clean counters.",
                )
            )
            ctype = ComplaintType(type_name="Poor hygiene", severity_level="high")
            db.session.add(ctype)
            db.session.flush()
            db.session.add(
                Complaint(
                    stall_id=stall.stall_id,
                    complaint_type_id=ctype.complaint_type_id,
                    submitted_by_user_id=student_user.user_id,
                    title="Flies on the counter",
                    description="There were flies over the uncovered food.",
                    status="submitted",
                )
            )
            db.session.commit()

            self.inspector_user_id = inspector_user.user_id
            self.student_user_id = student_user.user_id
            self.stall_id = stall.stall_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def _get(self, path):
        self._login(self.inspector_user_id)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_list_renders_cards_stats_and_links(self):
        body = self._get("/inspector/inspections/")
        self.assertIn("ins-card", body)
        self.assertIn("Rahman Foods", body)
        self.assertIn('class="ins-grade ins-grade-a"', body)
        self.assertIn("Inspections done", body)
        self.assertIn("insQuickView", body)
        # "Inspect again" links pre-select the stall.
        self.assertIn(f"/inspector/inspections/new?stall_id={self.stall_id}", body)

    def test_sidebar_shows_area_and_links(self):
        body = self._get("/inspector/inspections/")
        self.assertIn("INSPECTOR PORTAL", body)
        self.assertIn("Birulia Zone", body)
        self.assertIn("/inspector/complaints/", body)
        self.assertIn("/profile", body)

    def test_create_form_preselects_stall_from_query_string(self):
        body = self._get(f"/inspector/inspections/new?stall_id={self.stall_id}")
        self.assertIn(f'value="{self.stall_id}" selected', body)

    def test_create_form_without_query_string_preselects_nothing(self):
        body = self._get("/inspector/inspections/new")
        self.assertNotIn("selected>", body.split('id="stall_id"')[1].split("</select>")[0])

    def test_complaints_list_renders_cards_and_inspect_link(self):
        body = self._get("/inspector/complaints/")
        self.assertIn("Flies on the counter", body)
        self.assertIn("insComplaintView", body)
        self.assertIn(f"/inspector/inspections/new?stall_id={self.stall_id}", body)
        self.assertIn("High / critical severity", body)

    def test_complaints_status_filter_links_and_empty_state(self):
        body = self._get("/inspector/complaints/?status=resolved")
        self.assertIn("No complaints to show", body)
        self.assertIn("Clear filter", body)

    def test_complaint_detail_has_breadcrumb_and_stall_card(self):
        with self.app.app_context():
            complaint_id = Complaint.query.one().complaint_id
        body = self._get(f"/inspector/complaints/{complaint_id}")
        self.assertIn("ins-crumbs", body)
        self.assertIn("Start inspection", body)
        self.assertIn("insLightbox", body)

    def test_student_still_blocked_from_inspector_pages(self):
        self._login(self.student_user_id)
        self.assertEqual(self.client.get("/inspector/inspections/").status_code, 403)


if __name__ == "__main__":
    unittest.main()
