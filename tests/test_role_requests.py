import unittest

from app import create_app
from extensions import db
from models import AuthAuditLog, Inspector, Role, RoleAuditLog, RoleRequest, User
from services.role_requests import (
    RoleRequestError,
    approve_role_request,
    create_role_request,
    reject_role_request,
)


class RoleRequestTestConfig:
    TESTING = True
    SECRET_KEY = "role-request-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


class RoleRequestTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(RoleRequestTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

            admin_role = Role(role_name="admin", is_system=True, is_admin_tier=True)
            customer_role = Role(role_name="customer", is_system=True)
            inspector_role = Role(role_name="inspector", is_system=True)
            db.session.add_all([admin_role, customer_role, inspector_role])
            db.session.commit()

            self.super_admin = User(
                role_id=admin_role.role_id, full_name="Super Admin",
                email="super@example.test", status="active", is_super_admin=True,
            )
            self.super_admin.set_password("SecurePass123")

            self.plain_admin = User(
                role_id=admin_role.role_id, full_name="Plain Admin",
                email="plainadmin@example.test", status="active", is_super_admin=False,
            )
            self.plain_admin.set_password("SecurePass123")

            self.customer = User(
                role_id=customer_role.role_id, full_name="Plain Customer",
                email="customer@example.test", status="active",
            )
            self.customer.set_password("SecurePass123")

            self.inspector_user = User(
                role_id=inspector_role.role_id, full_name="Existing Inspector",
                email="inspector@example.test", status="active",
            )
            self.inspector_user.set_password("SecurePass123")

            db.session.add_all(
                [self.super_admin, self.plain_admin, self.customer, self.inspector_user]
            )
            db.session.commit()
            db.session.add(
                Inspector(user_id=self.inspector_user.user_id, employee_code="EMP-1")
            )
            db.session.commit()

            self.admin_role_id = admin_role.role_id
            self.customer_role_id = customer_role.role_id
            self.inspector_role_id = inspector_role.role_id
            self.super_admin_id = self.super_admin.user_id
            self.plain_admin_id = self.plain_admin.user_id
            self.customer_id = self.customer.user_id
            self.inspector_user_id = self.inspector_user.user_id

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

    # -- self-service submission -----------------------------------------

    def test_customer_can_submit_inspector_request(self):
        token = self._login(self.customer_id)
        response = self.client.post(
            "/access-requests",
            data={
                "_csrf_token": token, "requested_role": "inspector",
                "reason": "I want to help inspect stalls.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            req = RoleRequest.query.filter_by(user_id=self.customer_id).first()
            self.assertIsNotNone(req)
            self.assertEqual(req.status, "pending")
            self.assertEqual(req.requested_role, "inspector")

    def test_duplicate_pending_request_blocked(self):
        token = self._login(self.customer_id)
        self.client.post(
            "/access-requests",
            data={"_csrf_token": token, "requested_role": "admin", "reason": "x"},
        )
        self.client.post(
            "/access-requests",
            data={"_csrf_token": token, "requested_role": "admin", "reason": "y"},
        )
        with self.app.app_context():
            count = RoleRequest.query.filter_by(
                user_id=self.customer_id, requested_role="admin"
            ).count()
            self.assertEqual(count, 1)

    def test_requesting_role_already_held_is_rejected(self):
        with self.app.app_context():
            with self.assertRaises(RoleRequestError):
                create_role_request(
                    db.session.get(User, self.inspector_user_id), "inspector", ""
                )

    def test_access_requests_page_requires_login(self):
        response = self.client.get("/access-requests")
        self.assertIn(response.status_code, (302, 401))

    # -- authorization on the pending request ------------------------------

    def test_pending_inspector_role_request_grants_no_access(self):
        token = self._login(self.customer_id)
        self.client.post(
            "/access-requests",
            data={"_csrf_token": token, "requested_role": "inspector", "reason": ""},
        )
        response = self.client.get("/dashboard/inspector")
        self.assertEqual(response.status_code, 403)

    def test_non_super_admin_cannot_view_access_requests_dashboard(self):
        self._login(self.plain_admin_id)
        response = self.client.get("/admin/access-requests")
        self.assertEqual(response.status_code, 403)

    def test_non_super_admin_cannot_approve(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="admin", status="pending"
            )
            db.session.add(req)
            db.session.commit()
            request_id = req.request_id

        token = self._login(self.plain_admin_id)
        response = self.client.post(
            f"/admin/access-requests/{request_id}/approve",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            req = db.session.get(RoleRequest, request_id)
            self.assertEqual(req.status, "pending")
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.role_id, self.customer_role_id)

    def test_public_super_admin_registration_route_does_not_exist(self):
        response = self.client.get("/register-super-admin")
        self.assertEqual(response.status_code, 404)

    # -- approval transaction ----------------------------------------------

    def test_super_admin_approves_admin_request(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="admin", status="pending"
            )
            db.session.add(req)
            db.session.commit()
            request_id = req.request_id

        token = self._login(self.super_admin_id)
        response = self.client.post(
            f"/admin/access-requests/{request_id}/approve",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            req = db.session.get(RoleRequest, request_id)
            self.assertEqual(req.status, "approved")
            self.assertEqual(req.reviewed_by, self.super_admin_id)
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.role_id, self.admin_role_id)
            self.assertTrue(RoleAuditLog.query.filter_by(target_user_id=self.customer_id).count() >= 1)
            self.assertTrue(
                AuthAuditLog.query.filter_by(
                    user_id=self.customer_id, event="role_approved"
                ).count() == 1
            )

    def test_super_admin_approves_inspector_request_with_employee_code(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="inspector", status="pending"
            )
            db.session.add(req)
            db.session.commit()
            request_id = req.request_id

        token = self._login(self.super_admin_id)
        response = self.client.post(
            f"/admin/access-requests/{request_id}/approve",
            data={"_csrf_token": token, "employee_code": "EMP-99"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.role_id, self.inspector_role_id)
            self.assertIsNotNone(user.inspector_profile)
            self.assertEqual(user.inspector_profile.employee_code, "EMP-99")

    def test_approving_inspector_request_without_employee_code_fails_cleanly(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="inspector", status="pending"
            )
            db.session.add(req)
            db.session.commit()
            request_id = req.request_id

        token = self._login(self.super_admin_id)
        response = self.client.post(
            f"/admin/access-requests/{request_id}/approve",
            data={"_csrf_token": token},
        )
        # The route catches the validation error, flashes it, and
        # redirects -- it must not leave the request half-approved.
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            req = db.session.get(RoleRequest, request_id)
            self.assertEqual(req.status, "pending")
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.role_id, self.customer_role_id)
            self.assertIsNone(user.inspector_profile)

    def test_approving_already_reviewed_request_raises(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="admin", status="approved"
            )
            db.session.add(req)
            db.session.commit()
            with self.assertRaises(RoleRequestError):
                approve_role_request(req, db.session.get(User, self.super_admin_id))

    def test_reject_stores_reason_and_reviewer_and_does_not_change_role(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="admin", status="pending"
            )
            db.session.add(req)
            db.session.commit()
            request_id = req.request_id

        token = self._login(self.super_admin_id)
        response = self.client.post(
            f"/admin/access-requests/{request_id}/reject",
            data={"_csrf_token": token, "rejection_reason": "Not enough info."},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            req = db.session.get(RoleRequest, request_id)
            self.assertEqual(req.status, "rejected")
            self.assertEqual(req.rejection_reason, "Not enough info.")
            self.assertEqual(req.reviewed_by, self.super_admin_id)
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.role_id, self.customer_role_id)

    def test_rejecting_already_reviewed_request_raises(self):
        with self.app.app_context():
            req = RoleRequest(
                user_id=self.customer_id, requested_role="admin", status="rejected"
            )
            db.session.add(req)
            db.session.commit()
            with self.assertRaises(RoleRequestError):
                reject_role_request(
                    req, db.session.get(User, self.super_admin_id), "again"
                )


if __name__ == "__main__":
    unittest.main()
