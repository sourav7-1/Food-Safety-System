import os
import unittest
from datetime import datetime

from app import create_app
from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    Inspection,
    Inspector,
    Permission,
    Role,
    Stall,
    User,
    Vendor,
)
from services.database_setup import _split_mysql_script


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RbacTestConfig:
    TESTING = True
    SECRET_KEY = "rbac-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


class RbacTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(RbacTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

            permissions = {
                code: Permission(code=code, description=code)
                for code in (
                    "vendors.view", "vendors.create", "vendors.edit", "vendors.delete",
                    "stalls.view", "stalls.create", "stalls.edit", "stalls.delete",
                    "users.view", "users.create", "users.edit", "users.status",
                    "users.inspectors",
                    "complaints.view", "complaints.respond", "complaints.evidence",
                    "inspections.view", "inspections.approve", "inspections.reject",
                    "reviews.view", "reviews.moderate",
                    "risk_engine.view",
                    "reports.view",
                    "settings.view",
                    "roles.manage",
                )
            }
            db.session.add_all(permissions.values())

            # "admin" here is deliberately given only the user-management
            # permissions (not vendors/stalls/etc.), so tests can prove
            # permission scoping actually narrows access rather than
            # every admin-role user getting everything.
            admin_role = Role(
                role_name="admin",
                is_system=True,
                is_admin_tier=True,
                permissions=[
                    permissions["users.view"],
                    permissions["users.create"],
                    permissions["users.edit"],
                    permissions["users.status"],
                    permissions["users.inspectors"],
                ],
            )
            customer_role = Role(role_name="customer", is_system=True)
            inspector_role = Role(role_name="inspector", is_system=True)
            vendor_role = Role(role_name="vendor", is_system=True)
            support_role = Role(
                role_name="support",
                is_system=False,
                is_admin_tier=True,
                permissions=[
                    permissions["complaints.view"],
                    permissions["complaints.respond"],
                ],
            )
            db.session.add_all(
                [admin_role, customer_role, inspector_role, vendor_role, support_role]
            )
            db.session.commit()

            self.super_admin = User(
                role_id=admin_role.role_id,
                full_name="Super Admin",
                email="super@example.test",
                status="active",
                is_super_admin=True,
            )
            self.super_admin.set_password("SecurePass123")

            self.limited_admin = User(
                role_id=admin_role.role_id,
                full_name="Limited Admin",
                email="limited@example.test",
                status="active",
                is_super_admin=False,
            )
            self.limited_admin.set_password("SecurePass123")

            self.support_user = User(
                role_id=support_role.role_id,
                full_name="Support Staffer",
                email="support@example.test",
                status="active",
            )
            self.support_user.set_password("SecurePass123")

            self.customer = User(
                role_id=customer_role.role_id,
                full_name="Plain Customer",
                email="customer@example.test",
                status="active",
            )
            self.customer.set_password("SecurePass123")

            db.session.add_all(
                [self.super_admin, self.limited_admin, self.support_user, self.customer]
            )
            db.session.commit()

            area = Area(area_name="Test Area", city="Test City", zone="")
            db.session.add(area)
            db.session.flush()

            inspector_user = User(
                role_id=inspector_role.role_id,
                full_name="Field Inspector",
                email="inspector@example.test",
                status="active",
            )
            inspector_user.set_password("SecurePass123")
            db.session.add(inspector_user)
            db.session.flush()
            self.inspector = Inspector(
                user_id=inspector_user.user_id,
                employee_code="EMP-1",
                assigned_area_id=area.area_id,
            )
            db.session.add(self.inspector)

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

            stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area.area_id,
                stall_name="Test Stall",
                stall_code="TS-1",
                address="123 Test Street",
                status="active",
            )
            db.session.add(stall)
            complaint_type = ComplaintType(
                type_name="Poor hygiene", severity_level="medium"
            )
            db.session.add(complaint_type)
            db.session.commit()

            complaint = Complaint(
                stall_id=stall.stall_id,
                complaint_type_id=complaint_type.complaint_type_id,
                submitted_by_user_id=self.customer.user_id,
                title="Unsafe handling",
                description="Food left uncovered.",
                status="submitted",
            )
            db.session.add(complaint)
            db.session.commit()

            self.stall_id = stall.stall_id
            self.complaint_id = complaint.complaint_id
            self.area_id = area.area_id
            self.admin_role_id = admin_role.role_id
            self.customer_role_id = customer_role.role_id
            self.inspector_role_id = inspector_role.role_id
            self.support_role_id = support_role.role_id
            self.super_admin_id = self.super_admin.user_id
            self.limited_admin_id = self.limited_admin.user_id
            self.support_user_id = self.support_user.user_id
            self.customer_id = self.customer.user_id
            self.inspector_user_id = inspector_user.user_id
            self.inspector_id = self.inspector.inspector_id

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

    def _user_count(self):
        with self.app.app_context():
            return User.query.count()

    # -- admin-tier gate ---------------------------------------------------

    def test_non_admin_tier_role_blocked_from_admin_routes(self):
        self._login(self.customer_id)
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 403)

    def test_custom_admin_tier_role_reaches_dashboard(self):
        self._login(self.support_user_id)
        response = self.client.get("/dashboard/admin")
        self.assertEqual(response.status_code, 200)

    # -- permission scoping --------------------------------------------

    def test_super_admin_bypasses_permission_checks(self):
        self._login(self.super_admin_id)
        response = self.client.get("/admin/vendors")
        self.assertEqual(response.status_code, 200)

    def test_permission_required_blocks_without_matching_code(self):
        # limited_admin's role only has users.manage, not vendors.manage.
        self._login(self.limited_admin_id)
        response = self.client.get("/admin/vendors")
        self.assertEqual(response.status_code, 403)

    def test_permission_required_allows_with_matching_code(self):
        self._login(self.limited_admin_id)
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 200)

    def test_custom_role_only_reaches_its_granted_permission(self):
        self._login(self.support_user_id)
        allowed = self.client.get("/admin/complaints")
        blocked = self.client.get("/admin/vendors")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(blocked.status_code, 403)

    # -- super-admin-only routes ------------------------------------------

    def test_super_admin_required_blocks_admin_tier_non_super_admin(self):
        self._login(self.limited_admin_id)
        response = self.client.get("/admin/roles")
        self.assertEqual(response.status_code, 403)

    def test_super_admin_required_allows_super_admin(self):
        self._login(self.super_admin_id)
        response = self.client.get("/admin/roles")
        self.assertEqual(response.status_code, 200)

    # -- privilege escalation guard -----------------------------------

    def test_limited_admin_cannot_create_admin_tier_user(self):
        token = self._login(self.limited_admin_id)
        before = self._user_count()
        response = self.client.post(
            "/admin/users",
            data={
                "_csrf_token": token,
                "full_name": "Sneaky New Admin",
                "email": "sneaky@example.test",
                "role_id": str(self.admin_role_id),
                "status": "active",
                "password": "SecurePass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user_count(), before)

    def test_limited_admin_cannot_promote_user_to_admin_role(self):
        token = self._login(self.limited_admin_id)
        response = self.client.post(
            f"/admin/users/{self.customer_id}",
            data={
                "_csrf_token": token,
                "full_name": "Plain Customer",
                "email": "customer@example.test",
                "role_id": str(self.admin_role_id),
                "status": "active",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.customer_id)
            self.assertEqual(user.role_id, self.customer_role_id)

    def test_limited_admin_can_create_customer_user(self):
        token = self._login(self.limited_admin_id)
        before = self._user_count()
        response = self.client.post(
            "/admin/users",
            data={
                "_csrf_token": token,
                "full_name": "New Customer",
                "email": "newcustomer@example.test",
                "role_id": str(self.customer_role_id),
                "status": "active",
                "password": "SecurePass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user_count(), before + 1)

    # -- self-protection --------------------------------------------------

    def test_super_admin_cannot_remove_own_super_admin_flag(self):
        token = self._login(self.super_admin_id)
        self.client.post(
            f"/admin/users/{self.super_admin_id}",
            data={
                "_csrf_token": token,
                "full_name": "Super Admin",
                "email": "super@example.test",
                "role_id": str(self.admin_role_id),
                "status": "active",
                # is_super_admin checkbox intentionally omitted (unchecked)
            },
        )
        with self.app.app_context():
            user = db.session.get(User, self.super_admin_id)
            self.assertTrue(user.is_super_admin)

    def test_admin_cannot_change_own_role_away_from_admin_tier(self):
        token = self._login(self.limited_admin_id)
        self.client.post(
            f"/admin/users/{self.limited_admin_id}",
            data={
                "_csrf_token": token,
                "full_name": "Limited Admin",
                "email": "limited@example.test",
                "role_id": str(self.customer_role_id),
                "status": "active",
            },
        )
        with self.app.app_context():
            user = db.session.get(User, self.limited_admin_id)
            self.assertEqual(user.role_id, self.admin_role_id)

    def test_admin_cannot_self_deactivate_via_edit(self):
        token = self._login(self.limited_admin_id)
        self.client.post(
            f"/admin/users/{self.limited_admin_id}",
            data={
                "_csrf_token": token,
                "full_name": "Limited Admin",
                "email": "limited@example.test",
                "role_id": str(self.admin_role_id),
                "status": "inactive",
            },
        )
        with self.app.app_context():
            user = db.session.get(User, self.limited_admin_id)
            self.assertEqual(user.status, "active")

    # -- inspector role transitions ----------------------------------------

    def test_creating_inspector_user_creates_inspector_row(self):
        token = self._login(self.limited_admin_id)
        response = self.client.post(
            "/admin/users",
            data={
                "_csrf_token": token,
                "full_name": "New Inspector",
                "email": "newinspector@example.test",
                "role_id": str(self.inspector_role_id),
                "status": "active",
                "password": "SecurePass123",
                "employee_code": "EMP-99",
                "assigned_area_id": str(self.area_id),
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(email="newinspector@example.test").one()
            self.assertIsNotNone(user.inspector_profile)
            self.assertEqual(user.inspector_profile.employee_code, "EMP-99")

    def test_creating_inspector_without_employee_code_rejected(self):
        token = self._login(self.limited_admin_id)
        before = self._user_count()
        response = self.client.post(
            "/admin/users",
            data={
                "_csrf_token": token,
                "full_name": "Bad Inspector",
                "email": "badinspector@example.test",
                "role_id": str(self.inspector_role_id),
                "status": "active",
                "password": "SecurePass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user_count(), before)

    def test_removing_inspector_role_deletes_inspector_row_when_no_inspections(self):
        token = self._login(self.limited_admin_id)
        response = self.client.post(
            f"/admin/users/{self.inspector_user_id}",
            data={
                "_csrf_token": token,
                "full_name": "Field Inspector",
                "email": "inspector@example.test",
                "role_id": str(self.customer_role_id),
                "status": "active",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Inspector, self.inspector_id))
            user = db.session.get(User, self.inspector_user_id)
            self.assertEqual(user.role_id, self.customer_role_id)

    def test_removing_inspector_role_blocked_while_inspections_exist(self):
        with self.app.app_context():
            db.session.add(
                Inspection(
                    stall_id=self.stall_id,
                    inspector_id=self.inspector_id,
                    inspection_date=datetime.now(),
                    status="submitted",
                )
            )
            db.session.commit()

        token = self._login(self.limited_admin_id)
        response = self.client.post(
            f"/admin/users/{self.inspector_user_id}",
            data={
                "_csrf_token": token,
                "full_name": "Field Inspector",
                "email": "inspector@example.test",
                "role_id": str(self.customer_role_id),
                "status": "active",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Inspector, self.inspector_id))
            user = db.session.get(User, self.inspector_user_id)
            self.assertEqual(user.role_id, self.inspector_role_id)

    # -- role management (super admin only) --------------------------------

    def test_role_create_requires_super_admin(self):
        token = self._login(self.limited_admin_id)
        response = self.client.post(
            "/admin/roles",
            data={"_csrf_token": token, "role_name": "moderator", "description": ""},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertIsNone(Role.query.filter_by(role_name="moderator").first())

    def test_role_create_and_permission_assignment(self):
        token = self._login(self.super_admin_id)
        self.client.post(
            "/admin/roles",
            data={
                "_csrf_token": token,
                "role_name": "moderator",
                "description": "Reviews and complaints only",
            },
        )
        with self.app.app_context():
            new_role = Role.query.filter_by(role_name="moderator").one()
            self.assertFalse(new_role.is_system)
            self.assertFalse(new_role.is_admin_tier)
            role_id = new_role.role_id

        self.client.post(
            f"/admin/roles/{role_id}",
            data={
                "_csrf_token": token,
                "role_name": "moderator",
                "description": "Reviews and complaints only",
                "is_admin_tier": "on",
                "permissions": ["reviews.view", "reviews.moderate", "complaints.view"],
            },
        )
        with self.app.app_context():
            role = db.session.get(Role, role_id)
            self.assertTrue(role.is_admin_tier)
            codes = {p.code for p in role.permissions}
            self.assertEqual(
                codes, {"reviews.view", "reviews.moderate", "complaints.view"}
            )

    def test_role_edit_is_system_blocks_rename(self):
        token = self._login(self.super_admin_id)
        self.client.post(
            f"/admin/roles/{self.admin_role_id}",
            data={
                "_csrf_token": token,
                "role_name": "renamed-admin",
                "description": "",
                "is_admin_tier": "on",
                "permissions": ["users.view"],
            },
        )
        with self.app.app_context():
            role = db.session.get(Role, self.admin_role_id)
            self.assertEqual(role.role_name, "admin")

    def test_role_delete_blocked_for_system_role(self):
        token = self._login(self.super_admin_id)
        response = self.client.post(
            f"/admin/roles/{self.customer_role_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Role, self.customer_role_id))

    def test_role_delete_blocked_when_users_assigned(self):
        token = self._login(self.super_admin_id)
        self.client.post(
            "/admin/roles",
            data={"_csrf_token": token, "role_name": "moderator", "description": ""},
        )
        with self.app.app_context():
            role = Role.query.filter_by(role_name="moderator").one()
            role_id = role.role_id
            user = db.session.get(User, self.customer_id)
            user.role_id = role_id
            db.session.commit()

        self.client.post(
            f"/admin/roles/{role_id}/delete", data={"_csrf_token": token}
        )
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Role, role_id))

    def test_role_delete_succeeds_for_unused_custom_role(self):
        token = self._login(self.super_admin_id)
        self.client.post(
            "/admin/roles",
            data={"_csrf_token": token, "role_name": "moderator", "description": ""},
        )
        with self.app.app_context():
            role_id = Role.query.filter_by(role_name="moderator").one().role_id

        self.client.post(
            f"/admin/roles/{role_id}/delete", data={"_csrf_token": token}
        )
        with self.app.app_context():
            self.assertIsNone(db.session.get(Role, role_id))

    def test_super_admin_cannot_remove_admin_tier_from_own_role(self):
        token = self._login(self.super_admin_id)
        self.client.post(
            f"/admin/roles/{self.admin_role_id}",
            data={
                "_csrf_token": token,
                "role_name": "admin",
                "description": "",
                "permissions": ["users.view"],
                # is_admin_tier intentionally omitted (unchecked)
            },
        )
        with self.app.app_context():
            role = db.session.get(Role, self.admin_role_id)
            self.assertTrue(role.is_admin_tier)

    # -- fine-grained permission splits (view vs write, per action) --------

    def _make_role_user(self, role_name, codes):
        with self.app.app_context():
            role = Role(role_name=role_name, is_admin_tier=True)
            role.permissions = Permission.query.filter(
                Permission.code.in_(codes)
            ).all()
            user = User(
                full_name=role_name.title(),
                email=f"{role_name}@example.test",
                status="active",
            )
            user.set_password("SecurePass123")
            user.role = role
            db.session.add_all([role, user])
            db.session.commit()
            return user.user_id

    def test_complaints_view_only_cannot_respond(self):
        user_id = self._make_role_user("viewer", ["complaints.view"])
        token = self._login(user_id)

        allowed = self.client.get(f"/admin/complaints/{self.complaint_id}")
        self.assertEqual(allowed.status_code, 200)

        blocked = self.client.post(
            f"/admin/complaints/{self.complaint_id}",
            data={
                "_csrf_token": token,
                "status": "under_review",
                "admin_response": "Trying to respond without permission.",
            },
        )
        self.assertEqual(blocked.status_code, 403)
        with self.app.app_context():
            complaint = db.session.get(Complaint, self.complaint_id)
            self.assertEqual(complaint.status, "submitted")

    def test_respond_permission_does_not_grant_evidence_review(self):
        user_id = self._make_role_user(
            "responder", ["complaints.view", "complaints.respond"]
        )
        self._login(user_id)
        # No evidence exists in this fixture, but the permission gate is
        # checked before the row is even looked up, so a 403 here proves
        # complaints.respond alone does not imply complaints.evidence.
        response = self.client.post(
            "/admin/evidence/999999/status",
            data={"_csrf_token": "test-csrf-token", "verification_status": "verified"},
        )
        self.assertEqual(response.status_code, 403)

    def test_users_create_without_inspectors_permission_blocked_from_inspector_role(
        self,
    ):
        user_id = self._make_role_user("recruiter", ["users.create"])
        token = self._login(user_id)

        # Allowed: creating a plain customer account.
        ok_response = self.client.post(
            "/admin/users",
            data={
                "_csrf_token": token,
                "full_name": "New Customer",
                "email": "recruit-customer@example.test",
                "role_id": str(self.customer_role_id),
                "status": "active",
                "password": "SecurePass123",
            },
        )
        self.assertEqual(ok_response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(
                User.query.filter_by(email="recruit-customer@example.test").first()
            )

        # Blocked: creating an inspector account requires users.inspectors.
        blocked_response = self.client.post(
            "/admin/users",
            data={
                "_csrf_token": token,
                "full_name": "New Inspector",
                "email": "recruit-inspector@example.test",
                "role_id": str(self.inspector_role_id),
                "status": "active",
                "password": "SecurePass123",
                "employee_code": "EMP-77",
            },
        )
        self.assertEqual(blocked_response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(
                User.query.filter_by(email="recruit-inspector@example.test").first()
            )


class RbacMigrationSyntaxTests(unittest.TestCase):
    def test_migration_sql_parses_cleanly(self):
        path = os.path.join(
            PROJECT_ROOT, "database", "migrations", "008_add_rbac.sql"
        )
        with open(path, encoding="utf-8") as handle:
            script = handle.read()
        statements = list(_split_mysql_script(script))
        self.assertGreater(len(statements), 0)
        joined = "\n".join(statements).lower()
        for expected in (
            "is_system",
            "is_admin_tier",
            "is_super_admin",
            "permissions",
            "role_permissions",
            "roles.manage",
        ):
            self.assertIn(expected, joined)

    def test_migration_009_sql_parses_cleanly(self):
        path = os.path.join(
            PROJECT_ROOT,
            "database",
            "migrations",
            "009_expand_permission_granularity.sql",
        )
        with open(path, encoding="utf-8") as handle:
            script = handle.read()
        statements = list(_split_mysql_script(script))
        self.assertGreater(len(statements), 0)
        joined = "\n".join(statements).lower()
        for expected in (
            "vendors.view",
            "users.inspectors",
            "complaints.evidence",
            "delete from permissions",
        ):
            self.assertIn(expected, joined)


if __name__ == "__main__":
    unittest.main()
