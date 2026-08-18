import re
import unittest
from unittest.mock import patch

from app import create_app
from extensions import db
from models import Role, User
from services.account_classification import is_allowed_signup_email


class DomainRestrictionTestConfig:
    TESTING = True
    SECRET_KEY = "domain-restriction-test-secret"
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


class DomainRestrictionUnitTests(unittest.TestCase):
    def test_valid_student_email_allowed(self):
        self.assertTrue(is_allowed_signup_email("222-35-456@diu.edu.bd"))

    def test_gmail_blocked(self):
        self.assertFalse(is_allowed_signup_email("someone@gmail.com"))

    def test_official_diu_staff_domain_blocked(self):
        self.assertFalse(is_allowed_signup_email("registrar@daffodilvariversity.edu.bd"))

    def test_malformed_diu_domain_email_blocked(self):
        self.assertFalse(is_allowed_signup_email("student@diu.edu.bd"))


class DomainRestrictionRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(DomainRestrictionTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="student", is_system=True),
                    Role(role_name="customer", is_system=True),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _csrf_token(self):
        response = self.client.get("/register")
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"', response.get_data(as_text=True)
        )
        return match.group(1)

    def _register(self, email):
        token = self._csrf_token()
        return self.client.post(
            "/register",
            data={
                "_csrf_token": token,
                "full_name": "Test User",
                "email": email,
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            },
        )

    # -- local register() -------------------------------------------------

    def test_register_rejects_gmail(self):
        response = self._register("someone@gmail.com")
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertIsNone(
                User.query.filter_by(email="someone@gmail.com").first()
            )

    def test_register_rejects_official_diu_staff_domain(self):
        response = self._register("registrar@daffodilvariversity.edu.bd")
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertIsNone(
                User.query.filter_by(
                    email="registrar@daffodilvariversity.edu.bd"
                ).first()
            )

    def test_register_rejects_malformed_diu_domain_email(self):
        response = self._register("student@diu.edu.bd")
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertIsNone(
                User.query.filter_by(email="student@diu.edu.bd").first()
            )

    def test_register_accepts_valid_diu_student_email(self):
        response = self._register("222-35-456@diu.edu.bd")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(email="222-35-456@diu.edu.bd").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role_name, "student")

    # -- google_callback() new-account branch ------------------------------

    def _google_signup(self, email):
        with patch("routes.auth.oauth") as mock_oauth:
            mock_oauth.google.authorize_access_token.return_value = {}
            mock_oauth.google.userinfo.return_value = {
                "sub": f"google-sub-{email}",
                "email": email,
                "email_verified": True,
                "name": "Test User",
            }
            return self.client.get("/auth/google/callback")

    def test_google_signup_rejects_gmail(self):
        response = self._google_signup("newperson@gmail.com")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(
                User.query.filter_by(email="newperson@gmail.com").first()
            )

    def test_google_signup_accepts_valid_diu_student_email(self):
        response = self._google_signup("222-99-111@diu.edu.bd")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(email="222-99-111@diu.edu.bd").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role_name, "student")

    def test_google_login_still_works_for_preexisting_non_diu_account(self):
        # The restriction only gates NEW account creation -- an existing
        # account (e.g. a Gmail customer account created before this
        # restriction existed) must still be able to log in.
        with self.app.app_context():
            customer_role = Role.query.filter_by(role_name="customer").first()
            existing = User(
                role_id=customer_role.role_id,
                full_name="Existing Customer",
                email="existing@gmail.com",
                status="active",
                auth_provider="local",
            )
            existing.set_password("SecurePass123")
            db.session.add(existing)
            db.session.commit()

        response = self._google_signup("existing@gmail.com")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(email="existing@gmail.com").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.google_id, "google-sub-existing@gmail.com")


if __name__ == "__main__":
    unittest.main()
