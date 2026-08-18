import unittest

from app import create_app
from extensions import db
from models import Role, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "sample-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    MAX_CONTENT_LENGTH = 150 * 1024 * 1024
    EVIDENCE_STORAGE_PATH = "test-evidence"


class AuthenticationSamples(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="admin"),
                    Role(role_name="customer"),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def csrf_session(self):
        token = "sample-csrf-token"
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
        return token

    def test_customer_registration_hashes_password(self):
        # Registration is restricted to @diu.edu.bd student emails -- see
        # tests/test_domain_restriction.py for the restriction itself.
        # This sample only checks password hashing, so it uses a valid
        # DIU student email and the resulting "student" role.
        with self.app.app_context():
            db.session.add(Role(role_name="student"))
            db.session.commit()

        token = self.csrf_session()
        response = self.client.post(
            "/register",
            data={
                "_csrf_token": token,
                "full_name": "Sample Customer",
                "email": "222-35-456@diu.edu.bd",
                "phone": "01700000000",
                "password": "SecurePass123",
                "confirm_password": "SecurePass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(
                email="222-35-456@diu.edu.bd"
            ).one()
            self.assertNotEqual(user.password_hash, "SecurePass123")
            self.assertTrue(user.check_password("SecurePass123"))
            self.assertEqual(user.role_name, "student")

    def test_disabled_user_cannot_login(self):
        with self.app.app_context():
            role = Role.query.filter_by(role_name="customer").one()
            user = User(
                role=role,
                full_name="Disabled Customer",
                email="disabled@example.test",
                status="suspended",
            )
            user.set_password("SecurePass123")
            db.session.add(user)
            db.session.commit()

        token = self.csrf_session()
        response = self.client.post(
            "/login",
            data={
                "_csrf_token": token,
                "email": "disabled@example.test",
                "password": "SecurePass123",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_customer_cannot_access_admin(self):
        with self.app.app_context():
            role = Role.query.filter_by(role_name="customer").one()
            user = User(
                role=role,
                full_name="Customer",
                email="rolecheck@example.test",
                status="active",
            )
            user.set_password("SecurePass123")
            db.session.add(user)
            db.session.commit()
            user_id = user.user_id

        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        response = self.client.get("/admin/vendors")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
