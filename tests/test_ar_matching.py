import unittest

from app import create_app
from extensions import db
from models import Role, User
from services.ar_matching import (
    bearing_degrees,
    confidence_band,
    confidence_score,
    gps_score,
    heading_score,
    ocr_score,
)


class ArMatchingTestConfig:
    TESTING = True
    SECRET_KEY = "ar-matching-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


# -- Unit: bearing_degrees ----------------------------------------------------


class BearingTests(unittest.TestCase):
    def test_due_north_is_zero(self):
        bearing = bearing_degrees(0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(bearing, 0.0, places=3)

    def test_due_east_is_90(self):
        bearing = bearing_degrees(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(bearing, 90.0, places=3)

    def test_due_south_is_180(self):
        bearing = bearing_degrees(1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(bearing, 180.0, places=3)

    def test_due_west_is_270(self):
        bearing = bearing_degrees(0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(bearing, 270.0, places=3)

    def test_result_is_always_in_0_360_range(self):
        bearing = bearing_degrees(23.87, 90.32, 23.869, 90.319)
        self.assertGreaterEqual(bearing, 0.0)
        self.assertLess(bearing, 360.0)


# -- Unit: gps_score -----------------------------------------------------------


class GpsScoreTests(unittest.TestCase):
    def test_zero_distance_is_full_score(self):
        self.assertAlmostEqual(gps_score(0), 40.0)

    def test_half_max_distance_is_half_score(self):
        self.assertAlmostEqual(gps_score(25), 20.0)

    def test_at_max_distance_is_zero(self):
        self.assertAlmostEqual(gps_score(50), 0.0)

    def test_beyond_max_distance_is_zero_not_negative(self):
        self.assertAlmostEqual(gps_score(60), 0.0)

    def test_none_distance_is_zero(self):
        self.assertAlmostEqual(gps_score(None), 0.0)


# -- Unit: ocr_score -------------------------------------------------------


class OcrScoreTests(unittest.TestCase):
    def test_exact_match_is_full_score(self):
        self.assertAlmostEqual(ocr_score("Rahman Foods", "Rahman Foods"), 30.0)

    def test_case_insensitive_exact_match_is_full_score(self):
        self.assertAlmostEqual(ocr_score("RAHMAN FOODS", "rahman foods"), 30.0)

    def test_empty_ocr_text_is_zero(self):
        self.assertAlmostEqual(ocr_score("", "Rahman Foods"), 0.0)

    def test_whitespace_only_ocr_text_is_zero(self):
        self.assertAlmostEqual(ocr_score("   ", "Rahman Foods"), 0.0)

    def test_completely_unrelated_text_scores_low(self):
        score = ocr_score("xyz123", "Rahman Foods")
        self.assertLess(score, 10.0)

    def test_partial_match_scores_between_zero_and_full(self):
        score = ocr_score("RAHMAN FOOD CORNER", "Rahman Foods")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 30.0)


# -- Unit: heading_score ---------------------------------------------------


class HeadingScoreTests(unittest.TestCase):
    def test_aligned_heading_is_full_score(self):
        self.assertAlmostEqual(heading_score(90, 90), 30.0)

    def test_30_degrees_off_is_half_score(self):
        self.assertAlmostEqual(heading_score(90, 120), 15.0)

    def test_60_degrees_off_is_zero(self):
        self.assertAlmostEqual(heading_score(90, 150), 0.0)

    def test_90_degrees_off_is_zero_not_negative(self):
        self.assertAlmostEqual(heading_score(90, 180), 0.0)

    def test_wraparound_near_0_360_boundary(self):
        # 350 degrees and 10 degrees are only 20 degrees apart, not 340.
        score = heading_score(350, 10)
        self.assertAlmostEqual(score, 20.0)

    def test_missing_user_heading_is_zero(self):
        self.assertAlmostEqual(heading_score(None, 90), 0.0)

    def test_missing_bearing_is_zero(self):
        self.assertAlmostEqual(heading_score(90, None), 0.0)


# -- Unit: confidence_score + confidence_band -------------------------------


class ConfidenceScoreTests(unittest.TestCase):
    def test_perfect_match_lands_in_high_band(self):
        score = confidence_score(
            distance_m=0,
            ocr_text="Rahman Foods",
            stall_name="Rahman Foods",
            user_heading_deg=90,
            bearing_deg=90,
        )
        self.assertEqual(score["total"], 100.0)
        self.assertEqual(confidence_band(score["total"]), "high")

    def test_good_gps_and_ocr_no_heading_lands_in_ambiguous_band(self):
        # 40 (gps) + 30 (ocr) + 0 (no heading) = 70 -- deliberately just
        # under the confirm-band floor to pin the exact boundary.
        score = confidence_score(
            distance_m=0,
            ocr_text="Rahman Foods",
            stall_name="Rahman Foods",
            user_heading_deg=None,
            bearing_deg=90,
        )
        self.assertEqual(score["total"], 70.0)
        self.assertEqual(confidence_band(score["total"]), "ambiguous")

    def test_gps_only_lands_in_low_band(self):
        # 40 (gps) + 0 (no ocr) + 0 (no heading) = 40, below the
        # ambiguous-band floor of 50 -- never shows a specific shop here.
        score = confidence_score(
            distance_m=0,
            ocr_text="",
            stall_name="Rahman Foods",
            user_heading_deg=None,
            bearing_deg=None,
        )
        self.assertEqual(score["total"], 40.0)
        self.assertEqual(confidence_band(score["total"]), "low")

    def test_far_away_with_ocr_and_heading_lands_in_ambiguous_band(self):
        # 0 (gps, 60m > 50m cap) + 30 (ocr) + 30 (heading) = 60.
        score = confidence_score(
            distance_m=60,
            ocr_text="Rahman Foods",
            stall_name="Rahman Foods",
            user_heading_deg=90,
            bearing_deg=90,
        )
        self.assertEqual(score["total"], 60.0)
        self.assertEqual(confidence_band(score["total"]), "ambiguous")

    def test_band_boundaries_are_inclusive_at_the_floor(self):
        self.assertEqual(confidence_band(90), "high")
        self.assertEqual(confidence_band(89.9), "confirm")
        self.assertEqual(confidence_band(75), "confirm")
        self.assertEqual(confidence_band(74.9), "ambiguous")
        self.assertEqual(confidence_band(50), "ambiguous")
        self.assertEqual(confidence_band(49.9), "low")


# -- Integration: /customer/api/ar/match input validation --------------------


class ArMatchApiValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ArMatchingTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            role = Role(role_name="student", is_system=True)
            db.session.add(role)
            db.session.flush()
            user = User(
                role_id=role.role_id,
                full_name="AR Test Student",
                email="artest999-99-999@diu.edu.bd",
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
        response = self.client.get("/customer/api/ar/match?lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_missing_lng_is_400(self):
        self._login()
        response = self.client.get("/customer/api/ar/match?lat=23.8")
        self.assertEqual(response.status_code, 400)

    def test_non_numeric_lat_is_400(self):
        self._login()
        response = self.client.get("/customer/api/ar/match?lat=abc&lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_lat_above_range_is_400(self):
        self._login()
        response = self.client.get("/customer/api/ar/match?lat=91&lng=90.4")
        self.assertEqual(response.status_code, 400)

    def test_lng_below_range_is_400(self):
        self._login()
        response = self.client.get("/customer/api/ar/match?lat=23.8&lng=-181")
        self.assertEqual(response.status_code, 400)

    def test_heading_above_range_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/ar/match?lat=23.8&lng=90.4&heading=360"
        )
        self.assertEqual(response.status_code, 400)

    def test_heading_negative_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/ar/match?lat=23.8&lng=90.4&heading=-1"
        )
        self.assertEqual(response.status_code, 400)

    def test_heading_non_numeric_is_400(self):
        self._login()
        response = self.client.get(
            "/customer/api/ar/match?lat=23.8&lng=90.4&heading=abc"
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_login(self):
        response = self.client.get("/customer/api/ar/match?lat=23.8&lng=90.4")
        self.assertEqual(response.status_code, 302)

    # A request with valid lat/lng/heading would need to actually execute
    # the Haversine query, which needs the MySQL latest_stall_inspection
    # view this sqlite:///:memory: test database doesn't have -- see
    # tests/live_nearby_smoke.py's pattern for /api/stalls/nearby; an
    # equivalent live smoke case for /api/ar/match can be added there
    # against real MySQL.


class ArScanPageTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ArMatchingTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            role = Role(role_name="student", is_system=True)
            db.session.add(role)
            db.session.flush()
            user = User(
                role_id=role.role_id,
                full_name="AR Page Test Student",
                email="arpage999-99-999@diu.edu.bd",
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

    def test_page_requires_login(self):
        response = self.client.get("/customer/ar-scan")
        self.assertEqual(response.status_code, 302)

    def test_page_loads_for_student(self):
        self._login()
        response = self.client.get("/customer/ar-scan")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
