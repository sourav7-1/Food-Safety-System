import unittest
from datetime import date, datetime, timedelta

from app import create_app
from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    FoodCategory,
    FoodItem,
    Inspection,
    Inspector,
    Notification,
    Review,
    Role,
    Stall,
    User,
    Vendor,
)
from services.student_dashboard import (
    get_student_calendar_data,
    get_student_dashboard_data,
)


class StudentDashboardTestConfig:
    TESTING = True
    SECRET_KEY = "dashboard-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False


class StudentDashboardTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(StudentDashboardTestConfig)
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

        db.create_all()

        # Seed roles
        self.student_role = Role(role_name="student", description="Student")
        self.admin_role = Role(role_name="admin", description="Admin", is_admin_tier=True)
        self.vendor_role = Role(role_name="vendor", description="Vendor")
        self.inspector_role = Role(role_name="inspector", description="Inspector")
        db.session.add_all([self.student_role, self.admin_role, self.vendor_role, self.inspector_role])
        db.session.commit()

        # Create test student users
        self.student_user = User(
            role_id=self.student_role.role_id,
            full_name="Alice Student",
            email="alice221-15-1234@diu.edu.bd",
            email_classification="student",
            status="active",
            email_verified_at=datetime.now(),
        )
        self.student_user.set_password("password123")

        self.other_student = User(
            role_id=self.student_role.role_id,
            full_name="Bob Student",
            email="bob221-15-5678@diu.edu.bd",
            email_classification="student",
            status="active",
            email_verified_at=datetime.now(),
        )
        self.other_student.set_password("password123")

        # Create Vendor user & profile
        self.vendor_user = User(
            role_id=self.vendor_role.role_id,
            full_name="Vendor Owner",
            email="owner@gmail.com",
            email_classification="external",
            status="active",
            email_verified_at=datetime.now(),
        )
        self.vendor_user.set_password("password123")

        # Create Inspector user & profile
        self.inspector_user = User(
            role_id=self.inspector_role.role_id,
            full_name="Inspector Dave",
            email="dave@daffodilvariversity.edu.bd",
            email_classification="official_diu",
            status="active",
            email_verified_at=datetime.now(),
        )
        self.inspector_user.set_password("password123")

        # Create Area
        self.area = Area(area_name="Main Campus Cafeteria", city="Dhaka")
        db.session.add_all([self.student_user, self.other_student, self.vendor_user, self.inspector_user, self.area])
        db.session.commit()

        self.vendor = Vendor(
            user_id=self.vendor_user.user_id,
            business_name="Green Food Ltd",
            license_number="LIC-12345",
            status="approved",
        )
        self.inspector = Inspector(
            user_id=self.inspector_user.user_id,
            employee_code="INS-001",
            assigned_area_id=self.area.area_id,
        )
        db.session.add_all([self.vendor, self.inspector])
        db.session.commit()

        self.stall = Stall(
            vendor_id=self.vendor.vendor_id,
            stall_name="Green Bites",
            stall_code="ST-001",
            area_id=self.area.area_id,
            status="active",
            address="Level 1, Student Center",
        )
        self.stall2 = Stall(
            vendor_id=self.vendor.vendor_id,
            stall_name="Campus Canteen",
            stall_code="ST-002",
            area_id=self.area.area_id,
            status="active",
            address="Level 2, Student Center",
        )
        db.session.add_all([self.stall, self.stall2])
        db.session.commit()

        # Create Complaint Type
        self.ctype = ComplaintType(type_name="Food Hygiene", description="Cleanliness and food safety")
        db.session.add(self.ctype)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test-csrf-token"
            sess["_user_id"] = str(user.user_id)
            sess["_fresh"] = True

    def test_new_user_dashboard_empty_activity(self):
        """A new user with zero reviews and complaints gets 0 points and 'New Member' status."""
        data = get_student_dashboard_data(self.student_user)

        self.assertEqual(data["first_name"], "Alice")
        self.assertEqual(data["user_points"], 0)
        self.assertEqual(data["user_rank"], "New Member")
        self.assertEqual(data["reviews_count"], 0)
        self.assertEqual(data["open_complaints_count"], 0)
        self.assertEqual(data["resolved_complaints_count"], 0)
        self.assertEqual(data["my_complaints"], [])
        self.assertEqual(data["alerts_feed"], [])

        # Stalls are active but uninspected -> fallback with 'Awaiting audit'
        self.assertEqual(len(data["top_safe_stalls"]), 2)
        self.assertFalse(data["top_safe_stalls"][0]["is_rated"])
        self.assertEqual(data["top_safe_stalls"][0]["days_ago"], "Awaiting audit")

    def test_points_calculation_and_leaderboard_rank(self):
        """User points: 15 per review + 10 per complaint; leaderboard ranks active students."""
        # Alice submits 2 reviews and 1 complaint -> 2*15 + 1*10 = 40 pts
        rev1 = Review(stall_id=self.stall.stall_id, user_id=self.student_user.user_id, rating=5, review_text="Great food!")
        rev2 = Review(stall_id=self.stall2.stall_id, user_id=self.student_user.user_id, rating=4, review_text="Clean stall.")
        comp1 = Complaint(
            stall_id=self.stall.stall_id,
            complaint_type_id=self.ctype.complaint_type_id,
            submitted_by_user_id=self.student_user.user_id,
            title="Cold soup",
            description="Soup was served cold.",
            status="submitted",
        )
        db.session.add_all([rev1, rev2, comp1])

        # Bob submits 1 review -> 15 pts
        rev_bob = Review(stall_id=self.stall.stall_id, user_id=self.other_student.user_id, rating=4, review_text="Nice!")
        db.session.add(rev_bob)
        db.session.commit()

        alice_data = get_student_dashboard_data(self.student_user)
        self.assertEqual(alice_data["user_points"], 40)
        self.assertEqual(alice_data["user_rank"], "#1")
        self.assertEqual(alice_data["reviews_count"], 2)
        self.assertEqual(alice_data["open_complaints_count"], 1)

        bob_data = get_student_dashboard_data(self.other_student)
        self.assertEqual(bob_data["user_points"], 15)
        self.assertEqual(bob_data["user_rank"], "#2")

        # Top 5 leaderboard should contain both
        self.assertEqual(len(alice_data["top_5_leaderboard"]), 2)
        self.assertEqual(alice_data["top_5_leaderboard"][0]["name"], "Alice Student")
        self.assertTrue(alice_data["top_5_leaderboard"][0]["is_current_user"])
        self.assertEqual(alice_data["top_5_leaderboard"][1]["name"], "Bob Student")
        self.assertFalse(alice_data["top_5_leaderboard"][1]["is_current_user"])

    def test_complaint_stepper_status_mapping(self):
        """Check mapping of raw complaint status to 3-step stepper."""
        # 1. Submitted status
        c1 = Complaint(
            stall_id=self.stall.stall_id,
            complaint_type_id=self.ctype.complaint_type_id,
            submitted_by_user_id=self.student_user.user_id,
            title="Complaint 1",
            description="Description 1",
            status="submitted",
        )
        # 2. In progress status
        c2 = Complaint(
            stall_id=self.stall.stall_id,
            complaint_type_id=self.ctype.complaint_type_id,
            submitted_by_user_id=self.student_user.user_id,
            title="Complaint 2",
            description="Description 2",
            status="under_review",
        )
        # 3. Resolved status
        c3 = Complaint(
            stall_id=self.stall.stall_id,
            complaint_type_id=self.ctype.complaint_type_id,
            submitted_by_user_id=self.student_user.user_id,
            title="Complaint 3",
            description="Description 3",
            status="resolved",
        )
        db.session.add_all([c1, c2, c3])
        db.session.commit()

        data = get_student_dashboard_data(self.student_user)
        self.assertEqual(len(data["my_complaints"]), 3)

        complaints_by_title = {c["title"]: c for c in data["my_complaints"]}

        self.assertEqual(complaints_by_title["Complaint 1"]["step_index"], 1)
        self.assertEqual(complaints_by_title["Complaint 1"]["step_state"], "submitted")

        self.assertEqual(complaints_by_title["Complaint 2"]["step_index"], 2)
        self.assertEqual(complaints_by_title["Complaint 2"]["step_state"], "in_progress")

        self.assertEqual(complaints_by_title["Complaint 3"]["step_index"], 3)
        self.assertEqual(complaints_by_title["Complaint 3"]["step_state"], "resolved")

    def test_top_safe_stalls_hygiene_score_and_pastel_themes(self):
        """Rated stalls receive hygiene scores, grades, and pastel theme objects."""
        inspection = Inspection(
            stall_id=self.stall.stall_id,
            inspector_id=self.inspector.inspector_id,
            inspection_date=datetime.now() - timedelta(days=2),
            overall_score=94.5,
            risk_level="low",
            status="approved",
        )
        db.session.add(inspection)
        db.session.commit()

        data = get_student_dashboard_data(self.student_user)
        stalls = data["top_safe_stalls"]
        self.assertGreaterEqual(len(stalls), 1)
        self.assertTrue(stalls[0]["is_rated"])
        self.assertEqual(stalls[0]["score"], 94.5)
        self.assertEqual(stalls[0]["grade"], "A")
        self.assertEqual(stalls[0]["days_ago"], "Inspected 2 days ago")
        self.assertIn("theme", stalls[0])
        self.assertEqual(stalls[0]["theme"]["color"], "peach")

    def test_calendar_api_data_aggregation(self):
        """Calendar API aggregates inspections by date and provides highest risk level."""
        today = date.today()
        d_str = today.strftime("%Y-%m-%d")
        m_str = today.strftime("%Y-%m")

        inspection = Inspection(
            stall_id=self.stall.stall_id,
            inspector_id=self.inspector.inspector_id,
            inspection_date=datetime.now(),
            overall_score=85.0,
            risk_level="medium",
            status="approved",
        )
        db.session.add(inspection)
        db.session.commit()

        cal_data = get_student_calendar_data(m_str)
        self.assertTrue(cal_data["success"])
        self.assertIn(d_str, cal_data["days"])
        day_entry = cal_data["days"][d_str]
        self.assertEqual(day_entry["highest_risk"], "medium")
        self.assertEqual(day_entry["count"], 1)
        self.assertEqual(day_entry["inspections"][0]["grade"], "B")
        self.assertEqual(day_entry["inspections"][0]["score"], 85.0)

    def test_customer_dashboard_unauthenticated(self):
        """Unauthenticated request to /customer/dashboard redirects to login."""
        res = self.client.get("/customer/dashboard")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers["Location"])

    def test_customer_dashboard_authenticated(self):
        """Authenticated student accesses /customer/dashboard with 200 OK."""
        self._login(self.student_user)
        res = self.client.get("/customer/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Welcome back, Alice", res.data)
        self.assertIn(b"Top Safe Stalls", res.data)
        self.assertIn(b"My Complaints", res.data)
        self.assertIn(b"Safety Calendar", res.data)
        self.assertIn(b"Top Student Champions", res.data)

    def test_calendar_api_endpoint(self):
        """Route /api/customer/calendar returns JSON for authenticated student."""
        self._login(self.student_user)
        res = self.client.get("/api/customer/calendar")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.is_json)
        json_body = res.get_json()
        self.assertTrue(json_body["success"])
        self.assertIn("days", json_body)


if __name__ == "__main__":
    unittest.main()
