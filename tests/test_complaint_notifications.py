import unittest

from app import create_app
from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    Notification,
    Role,
    Stall,
    User,
    Vendor,
)


class NotificationTestConfig:
    TESTING = True
    SECRET_KEY = "notification-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


class ComplaintNotificationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(NotificationTestConfig)
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
            admin_role = Role.query.filter_by(role_name="admin").one()
            vendor_role = Role.query.filter_by(role_name="vendor").one()

            self.customer = User(
                role_id=customer_role.role_id,
                full_name="Reporting Customer",
                email="reporter@example.test",
                status="active",
            )
            self.customer.set_password("SecurePass123")
            self.other_customer = User(
                role_id=customer_role.role_id,
                full_name="Other Customer",
                email="other@example.test",
                status="active",
            )
            self.other_customer.set_password("SecurePass123")
            self.admin = User(
                role_id=admin_role.role_id,
                full_name="Admin",
                email="admin@example.test",
                status="active",
            )
            self.admin.set_password("SecurePass123")
            db.session.add_all([self.customer, self.other_customer, self.admin])

            area = Area(area_name="Test Area", city="Test City", zone="")
            db.session.add(area)
            db.session.flush()

            vendor_user = User(
                role_id=vendor_role.role_id,
                full_name="Vendor Owner",
                email="vendor@example.test",
                status="active",
            )
            vendor_user.set_password("SecurePass123")
            db.session.add(vendor_user)
            db.session.flush()
            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Test Vendor",
                license_number="LIC-1",
            )
            db.session.add(vendor)
            db.session.flush()

            self.stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area.area_id,
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

            self.complaint = Complaint(
                stall_id=self.stall.stall_id,
                complaint_type_id=complaint_type.complaint_type_id,
                submitted_by_user_id=self.customer.user_id,
                title="Unsafe handling",
                description="Food left uncovered.",
                status="submitted",
            )
            db.session.add(self.complaint)
            db.session.commit()

            self.complaint_id = self.complaint.complaint_id
            self.customer_id = self.customer.user_id
            self.other_customer_id = self.other_customer.user_id
            self.admin_id = self.admin.user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    # -- helpers ---------------------------------------------------------

    def _login(self, user_id):
        token = "test-csrf-token"
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return token

    def _admin_update(self, **overrides):
        token = self._login(self.admin_id)
        data = {"_csrf_token": token, "status": "under_review", "admin_response": ""}
        data.update(overrides)
        return self.client.post(f"/admin/complaints/{self.complaint_id}", data=data)

    # -- admin response + notification on status change --------------------

    def test_status_change_creates_notification_for_submitter(self):
        self._admin_update(status="under_review")
        with self.app.app_context():
            notifications = Notification.query.filter_by(
                user_id=self.customer_id
            ).all()
            self.assertEqual(len(notifications), 1)
            self.assertIn("Under Review", notifications[0].message)
            self.assertFalse(notifications[0].is_read)
            self.assertEqual(notifications[0].complaint_id, self.complaint_id)

    def test_admin_response_saved_and_shown_to_customer(self):
        self._admin_update(
            status="under_review",
            admin_response="We are looking into this.",
        )
        with self.app.app_context():
            complaint = db.session.get(Complaint, self.complaint_id)
            self.assertEqual(
                complaint.admin_response, "We are looking into this."
            )

        self._login(self.customer_id)
        response = self.client.get(f"/customer/complaints/{self.complaint_id}")
        body = response.get_data(as_text=True)
        self.assertIn("We are looking into this.", body)

    def test_response_only_change_without_status_change_still_notifies(self):
        # First call sets status to under_review with no response.
        self._admin_update(status="under_review")
        with self.app.app_context():
            self.assertEqual(
                Notification.query.filter_by(user_id=self.customer_id).count(), 1
            )
        # Second call: same status, but a new response message.
        self._admin_update(
            status="under_review", admin_response="Following up with the vendor."
        )
        with self.app.app_context():
            notifications = Notification.query.filter_by(
                user_id=self.customer_id
            ).order_by(Notification.notification_id).all()
            self.assertEqual(len(notifications), 2)
            self.assertIn("Following up with the vendor.", notifications[1].message)

    def test_no_notification_when_nothing_changes(self):
        self._admin_update(status="submitted")  # same as current status, no response
        with self.app.app_context():
            self.assertEqual(
                Notification.query.filter_by(user_id=self.customer_id).count(), 0
            )

    # -- customer notification inbox ----------------------------------------

    def test_notifications_require_login(self):
        response = self.client.get("/customer/notifications")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_customer_only_sees_own_notifications(self):
        self._admin_update(status="under_review")
        self._login(self.other_customer_id)
        response = self.client.get("/customer/notifications")
        body = response.get_data(as_text=True)
        self.assertNotIn("Unsafe handling", body)

    def test_unread_count_and_mark_all_read(self):
        self._admin_update(status="under_review")
        self._admin_update(
            status="under_review", admin_response="Second update."
        )
        token = self._login(self.customer_id)
        response = self.client.get("/customer/notifications")
        self.assertIn(
            '<span class="notification-badge">2</span>',
            response.get_data(as_text=True),
        )

        self.client.post(
            "/customer/notifications/read-all", data={"_csrf_token": token}
        )
        with self.app.app_context():
            unread = Notification.query.filter_by(
                user_id=self.customer_id, is_read=False
            ).count()
            self.assertEqual(unread, 0)

    def test_clicking_notification_marks_it_read_and_redirects_to_complaint(self):
        self._admin_update(status="under_review")
        token = self._login(self.customer_id)
        with self.app.app_context():
            notification_id = Notification.query.filter_by(
                user_id=self.customer_id
            ).one().notification_id

        response = self.client.post(
            f"/customer/notifications/{notification_id}/read",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f"/customer/complaints/{self.complaint_id}",
            response.headers["Location"],
        )
        with self.app.app_context():
            notification = db.session.get(Notification, notification_id)
            self.assertTrue(notification.is_read)

    def test_cannot_mark_another_users_notification_read(self):
        self._admin_update(status="under_review")
        token = self._login(self.other_customer_id)
        with self.app.app_context():
            notification_id = Notification.query.filter_by(
                user_id=self.customer_id
            ).one().notification_id

        response = self.client.post(
            f"/customer/notifications/{notification_id}/read",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            notification = db.session.get(Notification, notification_id)
            self.assertFalse(notification.is_read)


if __name__ == "__main__":
    unittest.main()
