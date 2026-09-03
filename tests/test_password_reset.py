import re
import unittest
from datetime import datetime, timezone

from app import create_app
from extensions import db
from models import Role, User
from services.password_reset import (
    ResetTokenExpired,
    ResetTokenInvalid,
    decode_reset_token,
    generate_reset_token,
    reset_token_matches_user,
)


class PasswordResetTestConfig:
    TESTING = True
    SECRET_KEY = "password-reset-test-secret"
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
    PASSWORD_RESET_MAX_AGE_SECONDS = 3600


class PasswordResetServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(PasswordResetTestConfig)
        with self.app.app_context():
            db.create_all()
            role = Role(role_name="student", is_system=True)
            db.session.add(role)
            db.session.flush()
            self.user = User(
                role_id=role.role_id,
                full_name="Jane Student",
                email="jane222-11-222@diu.edu.bd",
                status="active",
                auth_provider="local",
            )
            self.user.set_password("OriginalPass123")
            db.session.add(self.user)
            db.session.commit()
            self.user_id = self.user.user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_freshly_issued_token_matches_user(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            token = generate_reset_token(user)
            uid, fingerprint = decode_reset_token(token)
            self.assertEqual(uid, self.user_id)
            self.assertTrue(reset_token_matches_user(fingerprint, user))

    def test_token_stops_matching_after_password_changes(self):
        # This is the single-use mechanism: no server-side token storage,
        # just a fingerprint of password_hash baked into the signed token.
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            token = generate_reset_token(user)
            user.set_password("BrandNewPass456")
            db.session.commit()

            uid, fingerprint = decode_reset_token(token)
            user = db.session.get(User, uid)
            self.assertFalse(reset_token_matches_user(fingerprint, user))

    def test_tampered_token_raises_invalid(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            token = generate_reset_token(user)
            tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
            with self.assertRaises(ResetTokenInvalid):
                decode_reset_token(tampered)

    def test_expired_token_raises_expired(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            token = generate_reset_token(user)
            self.app.config["PASSWORD_RESET_MAX_AGE_SECONDS"] = -1
            with self.assertRaises(ResetTokenExpired):
                decode_reset_token(token)


class PasswordResetRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(PasswordResetTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            role = Role(role_name="student", is_system=True)
            db.session.add(role)
            db.session.flush()
            user = User(
                role_id=role.role_id,
                full_name="Jane Student",
                email="jane222-11-222@diu.edu.bd",
                status="active",
                auth_provider="local",
                email_verified_at=datetime.now(timezone.utc),
            )
            user.set_password("OriginalPass123")
            db.session.add(user)

            google_user = User(
                role_id=role.role_id,
                full_name="Google Student",
                email="google222-33-444@diu.edu.bd",
                status="active",
                auth_provider="google",
                google_id="google-sub-1",
            )
            db.session.add(google_user)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _csrf_token(self, path="/login"):
        response = self.client.get(path)
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"', response.get_data(as_text=True)
        )
        return match.group(1)

    def _login(self, email, password):
        token = self._csrf_token()
        return self.client.post(
            "/login",
            data={"_csrf_token": token, "email": email, "password": password},
        )

    def test_forgot_password_shows_generic_message_for_unknown_email(self):
        token = self._csrf_token("/forgot-password")
        response = self.client.post(
            "/forgot-password",
            data={"_csrf_token": token, "email": "nobody@diu.edu.bd"},
        )
        self.assertEqual(response.status_code, 302)

    def test_forgot_password_shows_generic_message_for_google_only_account(self):
        # No password to reset -- must not error, must not reveal via a
        # different response shape that the account exists.
        token = self._csrf_token("/forgot-password")
        response = self.client.post(
            "/forgot-password",
            data={
                "_csrf_token": token,
                "email": "google222-33-444@diu.edu.bd",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_full_reset_flow_changes_password_and_allows_login(self):
        with self.app.app_context():
            user = User.query.filter_by(email="jane222-11-222@diu.edu.bd").first()
            from services.password_reset import generate_reset_token

            token = generate_reset_token(user)

        # Old password still works before the reset.
        response = self._login("jane222-11-222@diu.edu.bd", "OriginalPass123")
        self.assertEqual(response.status_code, 302)
        self.client.get("/logout")

        csrf = self._csrf_token(f"/reset-password/{token}")
        response = self.client.post(
            f"/reset-password/{token}",
            data={
                "_csrf_token": csrf,
                "password": "BrandNewPass456",
                "confirm_password": "BrandNewPass456",
            },
        )
        self.assertEqual(response.status_code, 302)

        # Old password no longer works.
        response = self._login("jane222-11-222@diu.edu.bd", "OriginalPass123")
        self.assertEqual(response.status_code, 401)
        # New password works.
        response = self._login("jane222-11-222@diu.edu.bd", "BrandNewPass456")
        self.assertEqual(response.status_code, 302)

    def test_reset_token_cannot_be_replayed(self):
        with self.app.app_context():
            user = User.query.filter_by(email="jane222-11-222@diu.edu.bd").first()
            from services.password_reset import generate_reset_token

            token = generate_reset_token(user)

        csrf = self._csrf_token(f"/reset-password/{token}")
        self.client.post(
            f"/reset-password/{token}",
            data={
                "_csrf_token": csrf,
                "password": "BrandNewPass456",
                "confirm_password": "BrandNewPass456",
            },
        )

        # Reusing the same link a second time must be rejected, not
        # allow setting the password again.
        response = self.client.get(f"/reset-password/{token}")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forgot-password", response.headers.get("Location", ""))

    def test_reset_rejects_mismatched_confirmation(self):
        with self.app.app_context():
            user = User.query.filter_by(email="jane222-11-222@diu.edu.bd").first()
            from services.password_reset import generate_reset_token

            token = generate_reset_token(user)

        csrf = self._csrf_token(f"/reset-password/{token}")
        response = self.client.post(
            f"/reset-password/{token}",
            data={
                "_csrf_token": csrf,
                "password": "BrandNewPass456",
                "confirm_password": "SomethingElse789",
            },
        )
        self.assertEqual(response.status_code, 400)

        # Original password must still work -- the mismatched submission
        # must not have changed anything.
        response = self._login("jane222-11-222@diu.edu.bd", "OriginalPass123")
        self.assertEqual(response.status_code, 302)

    def test_reset_rejects_unknown_token(self):
        response = self.client.get("/reset-password/not-a-real-token")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/forgot-password", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
