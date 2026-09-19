import re
import unittest
from datetime import datetime

from app import create_app
from extensions import db
from models import Area, Role, User, Vendor
from unittest.mock import patch

from flask import redirect

from services.account_classification import (
    is_vendor_applicant_account,
    refreshed_classification,
    violates_student_email_rule,
)


class VendorSignupTestConfig:
    TESTING = True
    SECRET_KEY = "vendor-signup-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    GOOGLE_CLIENT_ID = "test-client-id"
    GOOGLE_CLIENT_SECRET = "test-client-secret"


class StudentEmailRuleUnitTests(unittest.TestCase):
    def test_google_refresh_never_moves_a_student_into_the_applicant_exemption(self):
        # legacy student-role account with a Gmail address, not yet stamped
        self.assertEqual(
            refreshed_classification("student", "unclassified", "x@gmail.com"),
            "unclassified",
        )

    def test_google_refresh_keeps_an_existing_applicant_stamp_and_updates_others(self):
        self.assertEqual(
            refreshed_classification("student", "external", "x@gmail.com"), "external"
        )
        self.assertEqual(
            refreshed_classification("vendor", "unclassified", "x@gmail.com"), "external"
        )
        self.assertEqual(
            refreshed_classification("student", "student", "john222-35-456@diu.edu.bd"),
            "student",
        )

    def test_real_student_cannot_leave_the_diu_id_format(self):
        self.assertTrue(violates_student_email_rule("student", "x@gmail.com", "student"))

    def test_valid_diu_id_is_fine(self):
        self.assertFalse(
            violates_student_email_rule("student", "john222-35-456@diu.edu.bd", "student")
        )

    def test_legacy_unclassified_student_with_gmail_is_still_blocked(self):
        self.assertTrue(violates_student_email_rule("student", "x@gmail.com", "unclassified"))

    def test_vendor_applicant_classifications_are_exempt(self):
        self.assertFalse(violates_student_email_rule("student", "x@gmail.com", "external"))
        self.assertFalse(
            violates_student_email_rule("student", "x@daffodilvariversity.edu.bd", "official_diu")
        )

    def test_rule_only_applies_to_the_student_role(self):
        self.assertFalse(violates_student_email_rule("vendor", "x@gmail.com", "external"))
        self.assertFalse(violates_student_email_rule("inspector", "x@gmail.com", "unclassified"))

    def test_is_vendor_applicant_account(self):
        self.assertTrue(is_vendor_applicant_account("student", "external"))
        self.assertFalse(is_vendor_applicant_account("student", "student"))
        self.assertFalse(is_vendor_applicant_account("vendor", "external"))


class VendorSignupRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(VendorSignupTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="student", is_system=True),
                    Role(role_name="vendor", is_system=True),
                ]
            )
            db.session.add(Area(area_name="Birulia", city="Savar", zone=""))
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _token(self, path="/register"):
        response = self.client.get(path)
        return re.search(
            r'name="_csrf_token" value="([^"]+)"', response.get_data(as_text=True)
        ).group(1)

    def _register(self, email, *, query="?role=vendor", form_role=None):
        data = {
            "_csrf_token": self._token("/register" + query),
            "full_name": "Stall Owner",
            "email": email,
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
        }
        if form_role:
            data["role"] = form_role
        return self.client.post("/register" + query, data=data)

    def _user(self, email):
        with self.app.app_context():
            user = User.query.filter_by(email=email).first()
            if user is None:
                return None
            return (user.role_name, user.email_classification, user.user_id)

    def _verify_and_login(self, email):
        with self.app.app_context():
            user = User.query.filter_by(email=email).one()
            user.email_verified_at = datetime.now()
            db.session.commit()
        return self.client.post(
            "/login",
            data={
                "_csrf_token": self._token("/login"),
                "email": email,
                "password": "SecurePass123",
            },
        )

    # -- registration --------------------------------------------------------

    def test_vendor_signup_accepts_a_gmail_address(self):
        response = self._register("owner@gmail.com")
        self.assertEqual(response.status_code, 302)
        role, classification, _ = self._user("owner@gmail.com")
        # Never the vendor role -- only an admin approval grants that.
        self.assertEqual(role, "student")
        self.assertEqual(classification, "external")

    def test_vendor_signup_accepts_the_staff_domain(self):
        response = self._register("boss@daffodilvariversity.edu.bd")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user("boss@daffodilvariversity.edu.bd")[1], "official_diu")

    def test_vendor_signup_role_can_come_from_the_form_field_alone(self):
        response = self._register("owner2@gmail.com", query="", form_role="vendor")
        self.assertEqual(response.status_code, 302)

    def test_vendor_signup_still_accepts_a_real_student_email(self):
        response = self._register("john222-35-456@diu.edu.bd")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user("john222-35-456@diu.edu.bd")[1], "student")

    def test_vendor_signup_still_rejects_a_malformed_student_domain_email(self):
        response = self._register("student@diu.edu.bd")
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self._user("student@diu.edu.bd"))

    def test_plain_signup_still_rejects_gmail(self):
        response = self._register("owner@gmail.com", query="")
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self._user("owner@gmail.com"))

    def test_vendor_signup_page_says_any_email_works_and_keeps_google_with_vendor_intent(self):
        body = self.client.get("/register?role=vendor").get_data(as_text=True)
        self.assertIn("Any email address works", body)
        self.assertIn('name="role" value="vendor"', body)
        self.assertIn("Continue with Google", body)
        self.assertIn("/auth/google/login?role=vendor", body)

    def test_student_signup_page_is_unchanged(self):
        body = self.client.get("/register").get_data(as_text=True)
        self.assertIn("Only official DIU student emails are accepted", body)
        self.assertNotIn('name="role" value="vendor"', body)
        self.assertIn("Continue with Google", body)
        self.assertNotIn("/auth/google/login?role=vendor", body)

    # -- after registration --------------------------------------------------

    def test_vendor_applicant_can_log_in(self):
        self._register("owner@gmail.com")
        response = self._verify_and_login("owner@gmail.com")
        self.assertEqual(response.status_code, 302)

    def test_vendor_applicant_is_kept_on_the_vendor_application(self):
        self._register("owner@gmail.com")
        self._verify_and_login("owner@gmail.com")

        blocked = self.client.get("/customer/stalls")
        self.assertEqual(blocked.status_code, 302)
        self.assertTrue(blocked.headers["Location"].endswith("/customer/vendor-application"))

        page = self.client.get("/customer/vendor-application")
        self.assertEqual(page.status_code, 200)

    def test_vendor_applicant_can_submit_an_application_but_stays_a_student(self):
        self._register("owner@gmail.com")
        self._verify_and_login("owner@gmail.com")
        with self.app.app_context():
            area_id = Area.query.one().area_id
        response = self.client.post(
            "/customer/vendor-application",
            data={
                "_csrf_token": self._token("/customer/vendor-application"),
                "business_name": "Owner Foods",
                "license_number": "LIC-OWN-1",
                "requested_stall_name": "Owner Corner",
                "requested_address": "Near the gate",
                "requested_area_id": area_id,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            vendor = Vendor.query.one()
            self.assertEqual(vendor.status, "pending")
            self.assertEqual(vendor.user.role_name, "student")

    def test_real_student_is_not_redirected_away_from_student_pages(self):
        self._register("john222-35-456@diu.edu.bd", query="")
        self._verify_and_login("john222-35-456@diu.edu.bd")
        response = self.client.get("/customer/stalls")
        self.assertEqual(response.status_code, 200)


class GoogleVendorSignupTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(VendorSignupTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="student", is_system=True),
                    Role(role_name="vendor", is_system=True),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _start_google(self, path="/auth/google/login?role=vendor"):
        with patch("routes.auth.oauth") as mock_oauth:
            mock_oauth.google.authorize_redirect.return_value = redirect("/google-consent")
            return self.client.get(path)

    def _callback(self, email):
        with patch("routes.auth.oauth") as mock_oauth:
            mock_oauth.google.authorize_access_token.return_value = {}
            mock_oauth.google.userinfo.return_value = {
                "sub": f"google-sub-{email}",
                "email": email,
                "email_verified": True,
                "name": "Google Owner",
            }
            return self.client.get("/auth/google/callback")

    def _user(self, email):
        with self.app.app_context():
            user = User.query.filter_by(email=email).first()
            return None if user is None else (user.role_name, user.email_classification)

    def test_vendor_intent_lets_google_create_a_non_diu_account(self):
        self._start_google()
        response = self._callback("owner@gmail.com")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user("owner@gmail.com"), ("student", "external"))
        # Signed in, and confined to the vendor application.
        self.assertEqual(self.client.get("/customer/vendor-application").status_code, 200)
        blocked = self.client.get("/customer/stalls")
        self.assertTrue(blocked.headers["Location"].endswith("/customer/vendor-application"))

    def test_without_vendor_intent_google_still_rejects_a_non_diu_account(self):
        self._start_google("/auth/google/login")
        self._callback("owner@gmail.com")
        self.assertIsNone(self._user("owner@gmail.com"))

    def test_vendor_intent_still_rejects_a_malformed_student_domain_account(self):
        self._start_google()
        self._callback("student@diu.edu.bd")
        self.assertIsNone(self._user("student@diu.edu.bd"))

    def test_vendor_intent_is_one_shot(self):
        self._start_google()
        self._callback("owner@gmail.com")
        self.client.get("/logout")  # (POST-only route; the session is cleared below anyway)
        with self.client.session_transaction() as session:
            session.clear()
        self._callback("second@gmail.com")
        self.assertIsNone(self._user("second@gmail.com"))

    def test_a_later_normal_google_login_clears_a_stale_vendor_intent(self):
        self._start_google()
        self._start_google("/auth/google/login")
        self._callback("owner@gmail.com")
        self.assertIsNone(self._user("owner@gmail.com"))

    def test_google_login_cannot_exempt_a_legacy_student_role_gmail_account(self):
        with self.app.app_context():
            role = Role.query.filter_by(role_name="student").one()
            legacy = User(
                role_id=role.role_id,
                full_name="Legacy",
                email="legacy@gmail.com",
                status="active",
                auth_provider="local",
            )
            legacy.set_password("SecurePass123")
            db.session.add(legacy)
            db.session.commit()

        self._callback("legacy@gmail.com")

        # Not signed in: the student-email rule still blocks this account,
        # and Google re-authenticating did not stamp it as an applicant.
        self.assertEqual(self._user("legacy@gmail.com"), ("student", "unclassified"))
        self.assertTrue(
            self.client.get("/customer/vendor-application").headers["Location"].startswith(
                "/login"
            )
        )


if __name__ == "__main__":
    unittest.main()
