import re
import unittest

from app import create_app
from extensions import db
from models import Area, Permission, Role, User, Vendor
from routes.customer import _nearby_marker_color


class NearbyStallsTestConfig:
    TESTING = True
    SECRET_KEY = "nearby-stalls-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


# -- Unit: grade/color mapping (routes/customer.py:_nearby_marker_color) ----


class MarkerColorTests(unittest.TestCase):
    def test_grade_a_is_green(self):
        self.assertEqual(_nearby_marker_color("A", False), "green")

    def test_grade_b_is_green(self):
        self.assertEqual(_nearby_marker_color("B", False), "green")

    def test_grade_c_is_amber(self):
        self.assertEqual(_nearby_marker_color("C", False), "amber")

    def test_grade_d_is_red(self):
        self.assertEqual(_nearby_marker_color("D", False), "red")

    def test_null_grade_is_gray(self):
        self.assertEqual(_nearby_marker_color(None, False), "gray")

    def test_high_risk_forces_red_even_with_good_grade(self):
        # risk_level also weighs unresolved complaints, not just the raw
        # score, so it can call a stall risky even when its grade alone
        # would say "amber" (or better).
        self.assertEqual(_nearby_marker_color("A", True), "red")
        self.assertEqual(_nearby_marker_color("C", True), "red")

    def test_high_risk_with_null_grade_is_still_red(self):
        self.assertEqual(_nearby_marker_color(None, True), "red")


# -- Unit: /customer/api/stalls/nearby input validation ----------------------


class NearbyApiValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(NearbyStallsTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            role = Role(role_name="student", is_system=True)
            db.session.add(role)
            db.session.flush()
            user = User(
                role_id=role.role_id,
                full_name="Nearby Test Student",
                email="nearby999-99-999@diu.edu.bd",
                status="active",
                auth_provider="local",
            )
            user.set_password("TestPass123")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.user_id)
            session["_fresh"] = True

    def test_missing_lat_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_missing_lng_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=23.8")
        self.assertEqual(response.status_code, 400)

    def test_both_missing_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby")
        self.assertEqual(response.status_code, 400)

    def test_non_numeric_lat_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=abc&lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_non_numeric_lng_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=23.8&lng=abc")
        self.assertEqual(response.status_code, 400)

    def test_lat_above_range_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=91&lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_lat_below_range_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=-91&lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_lng_above_range_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=23.8&lng=181")
        self.assertEqual(response.status_code, 400)

    def test_lng_below_range_is_400(self):
        self._login()
        response = self.client.get("/customer/api/stalls/nearby?lat=23.8&lng=-181")
        self.assertEqual(response.status_code, 400)

    def test_radius_zero_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/stalls/nearby?lat=23.8&lng=90.4&radius_km=0"
        )
        self.assertEqual(response.status_code, 400)

    def test_radius_negative_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/stalls/nearby?lat=23.8&lng=90.4&radius_km=-5"
        )
        self.assertEqual(response.status_code, 400)

    def test_radius_non_numeric_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/stalls/nearby?lat=23.8&lng=90.4&radius_km=abc"
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_category_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/stalls/nearby?lat=23.8&lng=90.4&category=food_truck"
        )
        self.assertEqual(response.status_code, 400)

    # A request with a known category (and no matching stalls table --
    # this test class uses sqlite:///:memory:, which lacks the MySQL
    # latest_stall_inspection view the query joins against) would need to
    # actually execute the Haversine query, so the "known category
    # succeeds" case lives in tests/live_nearby_smoke.py against real
    # MySQL alongside the other query-execution cases.

    def test_requires_login(self):
        # No _login() call -- @login_required should redirect, not 200.
        response = self.client.get("/customer/api/stalls/nearby?lat=23.8&lng=90.4")
        self.assertEqual(response.status_code, 302)

    # radius_km > server cap (clamp-and-succeed) and radius_km omitted
    # (default-and-succeed) both require executing the real Haversine
    # query against latest_stall_inspection, a MySQL view that doesn't
    # exist under the sqlite:///:memory: database this test class uses --
    # see tests/live_nearby_smoke.py for those two cases against real
    # MySQL, alongside the distance-correctness checks.


# -- Integration: admin stall create/edit location validation ----------------


class AdminStallLocationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(NearbyStallsTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add(Permission(code="stalls.view", description="x"))
            db.session.add(Permission(code="stalls.create", description="x"))
            db.session.add(Permission(code="stalls.edit", description="x"))
            admin_role = Role(role_name="admin", is_system=True, is_admin_tier=True)
            vendor_role = Role(role_name="vendor", is_system=True)
            db.session.add_all([admin_role, vendor_role])
            db.session.flush()

            admin_user = User(
                role_id=admin_role.role_id,
                full_name="Admin",
                email="admin@example.test",
                status="active",
                auth_provider="local",
                is_super_admin=True,
            )
            admin_user.set_password("AdminPass123")
            vendor_user = User(
                role_id=vendor_role.role_id,
                full_name="Vendor Owner",
                email="vendor@example.test",
                status="active",
                auth_provider="local",
            )
            vendor_user.set_password("VendorPass123")
            db.session.add_all([admin_user, vendor_user])
            db.session.flush()

            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Test Vendor Co",
                license_number="LIC-001",
                status="approved",
            )
            area = Area(area_name="Test Area", city="Dhaka", zone="North")
            db.session.add_all([vendor, area])
            db.session.commit()

            self.admin_user_id = admin_user.user_id
            self.vendor_id = vendor.vendor_id
            self.area_id = area.area_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login_admin(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.admin_user_id)
            session["_fresh"] = True

    def _csrf_token(self):
        response = self.client.get("/admin/stalls")
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"', response.get_data(as_text=True)
        )
        return match.group(1)

    def _base_form(self, **overrides):
        form = {
            "vendor_id": str(self.vendor_id),
            "area_id": str(self.area_id),
            "stall_name": "Test Stall",
            "stall_code": "TS-001",
            "address": "123 Test Street",
            "photo_url": "",
            "latitude": "",
            "longitude": "",
            "category": "street_stall",
            "status": "active",
        }
        form.update(overrides)
        return form

    def test_create_with_only_latitude_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(latitude="23.81")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

        from models import Stall
        with self.app.app_context():
            self.assertIsNone(Stall.query.filter_by(stall_code="TS-001").first())

    def test_create_with_only_longitude_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(longitude="90.41")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

    def test_create_with_both_empty_saves_null_location(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form()
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 302)

        from models import Stall
        with self.app.app_context():
            stall = Stall.query.filter_by(stall_code="TS-001").first()
            self.assertIsNotNone(stall)
            self.assertIsNone(stall.latitude)
            self.assertIsNone(stall.longitude)
            self.assertFalse(stall.has_location)

    def test_create_with_out_of_range_latitude_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(latitude="91", longitude="90.41")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

    def test_create_with_out_of_range_longitude_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(latitude="23.81", longitude="181")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

    def test_create_with_non_numeric_coordinates_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(latitude="abc", longitude="def")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

    def test_create_with_valid_coordinates_saves_and_has_location(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(latitude="23.81030000", longitude="90.41250000")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 302)

        from models import Stall
        with self.app.app_context():
            stall = Stall.query.filter_by(stall_code="TS-001").first()
            self.assertIsNotNone(stall)
            self.assertTrue(stall.has_location)
            self.assertAlmostEqual(float(stall.latitude), 23.8103, places=4)
            self.assertAlmostEqual(float(stall.longitude), 90.4125, places=4)

    def test_edit_updates_location(self):
        self._login_admin()
        token = self._csrf_token()
        create_form = self._base_form(latitude="23.81", longitude="90.41")
        create_form["_csrf_token"] = token
        self.client.post("/admin/stalls", data=create_form)

        from models import Stall
        with self.app.app_context():
            stall_id = Stall.query.filter_by(stall_code="TS-001").first().stall_id

        token = self._csrf_token()
        edit_form = self._base_form(latitude="24.00", longitude="91.00")
        edit_form["_csrf_token"] = token
        response = self.client.post(f"/admin/stalls/{stall_id}/edit", data=edit_form)
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            stall = db.session.get(Stall, stall_id)
            self.assertAlmostEqual(float(stall.latitude), 24.00, places=2)
            self.assertAlmostEqual(float(stall.longitude), 91.00, places=2)

    def test_create_with_missing_category_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form()
        del form["category"]
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

        from models import Stall
        with self.app.app_context():
            self.assertIsNone(Stall.query.filter_by(stall_code="TS-001").first())

    def test_create_with_invalid_category_rejected(self):
        self._login_admin()
        token = self._csrf_token()
        form = self._base_form(category="food_truck")
        form["_csrf_token"] = token
        response = self.client.post("/admin/stalls", data=form)
        self.assertEqual(response.status_code, 400)

    def test_create_with_each_valid_category_saves(self):
        for category in ("street_stall", "food_court", "hall_canteen"):
            with self.subTest(category=category):
                self._login_admin()
                token = self._csrf_token()
                form = self._base_form(
                    stall_code=f"TS-{category}", category=category
                )
                form["_csrf_token"] = token
                response = self.client.post("/admin/stalls", data=form)
                self.assertEqual(response.status_code, 302)

                from models import Stall
                with self.app.app_context():
                    stall = Stall.query.filter_by(
                        stall_code=f"TS-{category}"
                    ).first()
                    self.assertIsNotNone(stall)
                    self.assertEqual(stall.category, category)

    def test_edit_updates_category(self):
        self._login_admin()
        token = self._csrf_token()
        create_form = self._base_form(category="street_stall")
        create_form["_csrf_token"] = token
        self.client.post("/admin/stalls", data=create_form)

        from models import Stall
        with self.app.app_context():
            stall_id = Stall.query.filter_by(stall_code="TS-001").first().stall_id

        token = self._csrf_token()
        edit_form = self._base_form(category="hall_canteen")
        edit_form["_csrf_token"] = token
        response = self.client.post(f"/admin/stalls/{stall_id}/edit", data=edit_form)
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            stall = db.session.get(Stall, stall_id)
            self.assertEqual(stall.category, "hall_canteen")

    def test_edit_without_touching_location_preserves_it(self):
        self._login_admin()
        token = self._csrf_token()
        create_form = self._base_form(latitude="23.81", longitude="90.41")
        create_form["_csrf_token"] = token
        self.client.post("/admin/stalls", data=create_form)

        from models import Stall
        with self.app.app_context():
            stall_id = Stall.query.filter_by(stall_code="TS-001").first().stall_id

        # Edit form always submits both hidden lat/lng inputs (see
        # templates/admin/stalls/list.html), so "not touching" location
        # in the UI means the JS-populated inputs still carry the
        # existing values -- simulate that here rather than omitting the
        # fields, which would incorrectly simulate clearing them instead.
        token = self._csrf_token()
        edit_form = self._base_form(
            stall_name="Renamed Stall", latitude="23.81", longitude="90.41"
        )
        edit_form["_csrf_token"] = token
        response = self.client.post(f"/admin/stalls/{stall_id}/edit", data=edit_form)
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            stall = db.session.get(Stall, stall_id)
            self.assertEqual(stall.stall_name, "Renamed Stall")
            self.assertAlmostEqual(float(stall.latitude), 23.81, places=2)
            self.assertAlmostEqual(float(stall.longitude), 90.41, places=2)


if __name__ == "__main__":
    unittest.main()
