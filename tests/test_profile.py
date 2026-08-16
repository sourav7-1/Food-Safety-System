import io
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO

from PIL import Image

from app import create_app
from extensions import db
from models import Area, Complaint, ComplaintType, Review, Role, Stall, User, Vendor
from services.database_setup import _split_mysql_script


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _real_image_bytes(fmt="JPEG", size=(20, 20), color=(200, 30, 30)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


class ProfileTestConfig:
    TESTING = True
    SECRET_KEY = "profile-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    PROFILE_PHOTO_STORAGE_PATH = None  # set per-test to a temp dir
    PROFILE_PHOTO_MAX_MB = 1
    PROFILE_PHOTO_MAX_DIMENSION = 512


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp(prefix="profile-photo-test-")
        config = type(
            "Cfg",
            (ProfileTestConfig,),
            {"PROFILE_PHOTO_STORAGE_PATH": self.storage_dir},
        )
        self.app = create_app(config)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="admin"),
                    Role(role_name="customer"),
                    Role(role_name="vendor"),
                ]
            )
            db.session.commit()

            customer_role = Role.query.filter_by(role_name="customer").one()
            vendor_role = Role.query.filter_by(role_name="vendor").one()

            self.area = Area(area_name="Gulshan", city="Dhaka", zone="North")
            self.other_area = Area(area_name="Banani", city="Dhaka", zone="North")
            db.session.add_all([self.area, self.other_area])
            db.session.flush()

            self.customer = User(
                role_id=customer_role.role_id,
                full_name="Primary Customer",
                email="primary@example.test",
                phone="01700000001",
                status="active",
                email_verified_at=datetime.utcnow(),
            )
            self.customer.set_password("SecurePass123")

            self.other_customer = User(
                role_id=customer_role.role_id,
                full_name="Other Customer",
                email="other@example.test",
                phone="01700000002",
                status="active",
                email_verified_at=datetime.utcnow(),
            )
            self.other_customer.set_password("SecurePass123")

            self.google_user = User(
                role_id=customer_role.role_id,
                full_name="Google Customer",
                email="googleuser@example.test",
                google_id="google-sub-123",
                auth_provider="google",
                status="active",
                email_verified_at=datetime.utcnow(),
            )

            db.session.add_all([self.customer, self.other_customer, self.google_user])
            db.session.flush()

            vendor_owner = User(
                role_id=vendor_role.role_id,
                full_name="Vendor Owner",
                email="vendor@example.test",
                status="active",
                email_verified_at=datetime.utcnow(),
            )
            vendor_owner.set_password("SecurePass123")
            db.session.add(vendor_owner)
            db.session.flush()
            vendor = Vendor(
                user_id=vendor_owner.user_id,
                business_name="Test Vendor",
                license_number="LIC-1",
            )
            db.session.add(vendor)
            db.session.flush()

            self.stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=self.area.area_id,
                stall_name="Test Stall",
                stall_code="TS-1",
                address="123 Test Street",
                status="active",
            )
            complaint_type = ComplaintType(
                type_name="Poor hygiene", severity_level="medium"
            )
            db.session.add_all([self.stall, complaint_type])
            db.session.commit()

            # Activity belonging to the primary customer.
            db.session.add(
                Review(
                    stall_id=self.stall.stall_id,
                    user_id=self.customer.user_id,
                    rating=4,
                    review_text="Pretty good.",
                    status="visible",
                )
            )
            db.session.add(
                Complaint(
                    stall_id=self.stall.stall_id,
                    complaint_type_id=complaint_type.complaint_type_id,
                    submitted_by_user_id=self.customer.user_id,
                    title="My own complaint",
                    description="Something was off.",
                    status="submitted",
                )
            )
            # Activity belonging to a different customer -- must never
            # appear on the primary customer's profile.
            db.session.add(
                Complaint(
                    stall_id=self.stall.stall_id,
                    complaint_type_id=complaint_type.complaint_type_id,
                    submitted_by_user_id=self.other_customer.user_id,
                    title="Someone else's complaint",
                    description="Not related to the primary customer.",
                    status="submitted",
                )
            )
            db.session.commit()

            self.area_id = self.area.area_id
            self.customer_id = self.customer.user_id
            self.other_customer_id = self.other_customer.user_id
            self.google_user_id = self.google_user.user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        import shutil

        shutil.rmtree(self.storage_dir, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _login(self, user_id):
        token = "test-csrf-token"
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return token

    def _edit(self, **overrides):
        token = self._login(self.customer_id)
        data = {
            "_csrf_token": token,
            "full_name": "Primary Customer",
            "email": "primary@example.test",
            "phone": "01700000001",
            "bio": "",
            "address": "",
            "date_of_birth": "",
            "preferred_area_id": "",
            "current_password": "",
        }
        data.update(overrides)
        return self.client.post("/profile/edit", data=data)

    def _stored_files(self):
        files = []
        for root, _dirs, filenames in os.walk(self.storage_dir):
            files.extend(filenames)
        return files

    # -- login-required / scoping -----------------------------------------

    def test_profile_requires_login(self):
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_profile_view_shows_only_own_activity(self):
        self._login(self.customer_id)
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("My own complaint", body)
        self.assertNotIn("Someone else's complaint", body)

    def test_edit_only_changes_current_user_not_other_users(self):
        self._edit(full_name="Renamed Customer")
        with self.app.app_context():
            mine = db.session.get(User, self.customer_id)
            other = db.session.get(User, self.other_customer_id)
            self.assertEqual(mine.full_name, "Renamed Customer")
            self.assertEqual(other.full_name, "Other Customer")

    # -- basic field edits -------------------------------------------------

    def test_edit_updates_basic_fields_without_password(self):
        response = self._edit(
            bio="I like street food.",
            address="12 Road, Dhaka",
            date_of_birth="1995-06-15",
            preferred_area_id=str(self.area_id),
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.bio, "I like street food.")
            self.assertEqual(user.address, "12 Road, Dhaka")
            self.assertEqual(user.date_of_birth, date(1995, 6, 15))
            self.assertEqual(user.preferred_area_id, self.area_id)

    def test_future_date_of_birth_rejected(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        self._edit(date_of_birth=future)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertIsNone(user.date_of_birth)

    # -- email/phone change requires current password -----------------------

    def test_email_change_without_password_rejected(self):
        self._edit(email="new-address@example.test")
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.email, "primary@example.test")

    def test_email_change_with_wrong_password_rejected(self):
        self._edit(email="new-address@example.test", current_password="WrongPass1")
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.email, "primary@example.test")

    def test_email_change_with_correct_password_succeeds_and_needs_reverification(self):
        self._edit(
            email="new-address@example.test", current_password="SecurePass123"
        )
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.email, "new-address@example.test")
            self.assertIsNone(user.email_verified_at)

    def test_email_change_to_existing_address_rejected(self):
        self._edit(email="other@example.test", current_password="SecurePass123")
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            other = db.session.get(User, self.other_customer_id)
            self.assertEqual(user.email, "primary@example.test")
            self.assertEqual(other.email, "other@example.test")

    def test_phone_change_without_password_rejected(self):
        self._edit(phone="01711111111")
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.phone, "01700000001")

    def test_phone_change_with_correct_password_succeeds(self):
        self._edit(phone="01711111111", current_password="SecurePass123")
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.phone, "01711111111")

    # -- photo upload --------------------------------------------------

    def test_photo_upload_rejects_non_image_disguised_as_image(self):
        token = self._login(self.customer_id)
        response = self.client.post(
            "/profile/photo",
            data={
                "_csrf_token": token,
                "photo": (io.BytesIO(b"not really an image, just text"), "malware.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertIsNone(user.profile_photo_url)
        self.assertEqual(self._stored_files(), [])

    def test_photo_upload_rejects_disallowed_extension(self):
        token = self._login(self.customer_id)
        response = self.client.post(
            "/profile/photo",
            data={
                "_csrf_token": token,
                "photo": (io.BytesIO(_real_image_bytes()), "photo.exe"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertIsNone(user.profile_photo_url)

    def test_photo_upload_oversized_rejected(self):
        token = self._login(self.customer_id)
        oversized = _real_image_bytes() + b"0" * (2 * 1024 * 1024)  # > 1 MB test limit
        response = self.client.post(
            "/profile/photo",
            data={
                "_csrf_token": token,
                "photo": (io.BytesIO(oversized), "big.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertIsNone(user.profile_photo_url)
        self.assertEqual(self._stored_files(), [])

    def test_valid_photo_upload_replaces_old_file(self):
        token = self._login(self.customer_id)
        response = self.client.post(
            "/profile/photo",
            data={
                "_csrf_token": token,
                "photo": (io.BytesIO(_real_image_bytes(fmt="JPEG")), "first.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            first_url = db.session.get(User, self.customer_id).profile_photo_url
        self.assertIsNotNone(first_url)
        self.assertEqual(len(self._stored_files()), 1)

        response = self.client.post(
            "/profile/photo",
            data={
                "_csrf_token": token,
                "photo": (io.BytesIO(_real_image_bytes(fmt="PNG")), "second.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            second_url = db.session.get(User, self.customer_id).profile_photo_url
        self.assertIsNotNone(second_url)
        self.assertNotEqual(first_url, second_url)
        # The old file must be deleted once the new one is committed --
        # exactly one file should remain in storage.
        self.assertEqual(len(self._stored_files()), 1)

    def test_photo_remove(self):
        token = self._login(self.customer_id)
        self.client.post(
            "/profile/photo",
            data={
                "_csrf_token": token,
                "photo": (io.BytesIO(_real_image_bytes()), "photo.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(len(self._stored_files()), 1)

        response = self.client.post(
            "/profile/photo/remove", data={"_csrf_token": token}
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertIsNone(user.profile_photo_url)
        self.assertEqual(self._stored_files(), [])

    # -- password change --------------------------------------------------

    def test_password_change_requires_correct_current_password(self):
        token = self._login(self.customer_id)
        response = self.client.post(
            "/profile/password",
            data={
                "_csrf_token": token,
                "current_password": "WrongPass1",
                "new_password": "BrandNewPass1",
                "confirm_password": "BrandNewPass1",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertTrue(user.check_password("SecurePass123"))

    def test_password_change_success(self):
        token = self._login(self.customer_id)
        response = self.client.post(
            "/profile/password",
            data={
                "_csrf_token": token,
                "current_password": "SecurePass123",
                "new_password": "BrandNewPass1",
                "confirm_password": "BrandNewPass1",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertTrue(user.check_password("BrandNewPass1"))

    def test_password_change_rejected_for_google_only_account(self):
        token = self._login(self.google_user_id)
        response = self.client.post(
            "/profile/password",
            data={
                "_csrf_token": token,
                "current_password": "anything",
                "new_password": "BrandNewPass1",
                "confirm_password": "BrandNewPass1",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.google_user_id)
            self.assertIsNone(user.password_hash)


class ProfileMigrationSyntaxTests(unittest.TestCase):
    def test_migration_sql_parses_cleanly(self):
        path = os.path.join(
            PROJECT_ROOT,
            "database",
            "migrations",
            "006_add_user_profile_fields.sql",
        )
        with open(path, encoding="utf-8") as handle:
            script = handle.read()
        statements = list(_split_mysql_script(script))
        self.assertGreater(len(statements), 0)
        joined = "\n".join(statements).lower()
        for expected in (
            "profile_photo_url",
            "bio",
            "address",
            "date_of_birth",
            "preferred_area_id",
            "fk_users_preferred_area_id",
        ):
            self.assertIn(expected, joined)


if __name__ == "__main__":
    unittest.main()
