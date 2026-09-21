import re
import unittest
from datetime import datetime

from app import create_app
from extensions import db
from models import Area, Notification, Permission, Role, User, Vendor
from services.vendor_requests import INQUIRY_MAX_LENGTH, MESSAGE_PREFIX


class AdminVendorRequestsTestConfig:
    TESTING = True
    SECRET_KEY = "admin-vendor-requests-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = create_app(AdminVendorRequestsTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            view = Permission(code="vendors.view", description="x")
            edit = Permission(code="vendors.edit", description="x")
            db.session.add_all([view, edit])
            admin_role = Role(role_name="admin", is_system=True, is_admin_tier=True)
            viewer_role = Role(role_name="vendor_viewer", is_admin_tier=True)
            viewer_role.permissions.append(view)  # can look, can't decide
            student_role = Role(role_name="student", is_system=True)
            inspector_role = Role(role_name="inspector", is_system=True)
            vendor_role = Role(role_name="vendor", is_system=True)
            db.session.add_all(
                [admin_role, viewer_role, student_role, inspector_role, vendor_role]
            )
            db.session.add(Area(area_name="Birulia", city="Savar", zone=""))
            db.session.flush()

            def user(name, email, role, classification="unclassified", verified=True):
                u = User(
                    role_id=role.role_id,
                    full_name=name,
                    email=email,
                    status="active",
                    email_classification=classification,
                    email_verified_at=datetime.now() if verified else None,
                )
                u.set_password("SecurePass123")
                db.session.add(u)
                return u

            admin = user("Admin", "vr-admin@example.test", admin_role)
            admin.is_super_admin = True
            viewer = user("Viewer", "vr-viewer@example.test", viewer_role)
            # Vendor sign-ups that never submitted the business application:
            rahim = user("Rahim Signup", "rahim@gmail.com", student_role, "external")
            unverified = user("Unverified Signup", "unverified@gmail.com", student_role, "external", verified=False)
            # Must NOT be treated as vendor requests:
            real_student = user("Real Student", "john222-35-456@diu.edu.bd", student_role, "student")
            legacy = user("Legacy Student", "legacy@gmail.com", student_role, "unclassified")
            ext_inspector = user("Ext Inspector", "extinsp@gmail.com", inspector_role, "external")
            # One that DID apply (pending), one already approved:
            applicant = user("Karim Applicant", "karim@gmail.com", student_role, "external")
            approved_user = user("Approved Vendor", "approved@example.test", vendor_role)
            db.session.flush()
            db.session.add(
                Vendor(
                    user_id=applicant.user_id,
                    business_name="Karim Foods",
                    license_number="LIC-K",
                    status="pending",
                    requested_stall_name="Karim Corner",
                )
            )
            db.session.add(
                Vendor(
                    user_id=approved_user.user_id,
                    business_name="Old Vendor Co",
                    license_number="LIC-OLD",
                    status="approved",
                )
            )
            db.session.commit()
            self.ids = {
                "admin": admin.user_id,
                "viewer": viewer.user_id,
                "rahim": rahim.user_id,
                "unverified": unverified.user_id,
                "real_student": real_student.user_id,
                "legacy": legacy.user_id,
                "ext_inspector": ext_inspector.user_id,
                "applicant": applicant.user_id,
            }
            self.applicant_vendor_id = applicant.vendor_profile.vendor_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, who):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.ids[who])
            session["_fresh"] = True
            session["_csrf_token"] = "tok"

    def _get(self, path="/admin/vendors", who="admin"):
        self._login(who)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _post(self, path, data=None, who="admin"):
        self._login(who)
        return self.client.post(path, data={"_csrf_token": "tok", **(data or {})})

    def _panel(self, body):
        return body.split('id="vendorRequests"')[1].split("Application</th>")[0]

    def _user_state(self, who):
        with self.app.app_context():
            user = db.session.get(User, self.ids[who])
            vendor = user.vendor_profile
            return (
                user.role_name,
                None if vendor is None else (vendor.status, vendor.business_name, vendor.rejection_reason),
            )

    def _notifications(self, who):
        with self.app.app_context():
            return [n.message for n in Notification.query.filter_by(user_id=self.ids[who]).all()]


class RequestsPanelTests(_Base):
    def test_one_panel_lists_signups_and_pending_applications_together(self):
        panel = self._panel(self._get())
        self.assertIn("Vendor requests", panel)
        self.assertIn("rahim@gmail.com", panel)
        self.assertIn("unverified@gmail.com", panel)
        self.assertIn("karim@gmail.com", panel)
        self.assertIn("Sign-up only", panel)
        self.assertIn("Application", panel)
        self.assertIn("can't log in yet", panel)

    def test_only_real_vendor_requests_are_listed(self):
        panel = self._panel(self._get())
        for email in ("john222-35-456@diu.edu.bd", "legacy@gmail.com", "extinsp@gmail.com", "approved@example.test"):
            self.assertNotIn(email, panel)

    def test_every_request_has_approve_decline_and_inquiry(self):
        panel = self._panel(self._get())
        self.assertEqual(panel.count("Approve</button>"), 3)
        self.assertEqual(panel.count("Decline</button>"), 3)
        self.assertEqual(panel.count("Inquiry</button>"), 3)

    def test_decided_vendors_stay_in_the_main_table_and_pending_ones_leave_it(self):
        body = self._get()
        main_table = body.split("Application</th>")[1]
        self.assertIn("Old Vendor Co", main_table)
        self.assertNotIn("Karim Foods", main_table)

    def test_sidebar_badge_counts_signups_and_applications(self):
        body = self._get()
        match = re.search(r'class="sidebar-count"[^>]*>(\d+)<', body)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "3")  # 2 sign-ups + 1 application
        self.assertIn('class="sidebar-count"', self._get("/admin/stalls"))

    def test_search_filters_the_panel(self):
        panel = self._panel(self._get("/admin/vendors?q=unverified"))
        self.assertIn("unverified@gmail.com", panel)
        self.assertNotIn("rahim@gmail.com", panel)
        self.assertNotIn("karim@gmail.com", panel)

    def test_empty_state_when_nothing_is_waiting(self):
        with self.app.app_context():
            Vendor.query.filter_by(status="pending").update({"status": "approved"})
            User.query.filter(User.email.in_(["rahim@gmail.com", "unverified@gmail.com"])).delete(
                synchronize_session=False
            )
            db.session.commit()
        body = self._get()
        self.assertIn("No vendor requests waiting", body)
        self.assertNotIn('class="sidebar-count"', body)

    def test_a_viewer_without_edit_permission_sees_no_decision_buttons(self):
        panel = self._panel(self._get(who="viewer"))
        self.assertIn("rahim@gmail.com", panel)
        self.assertNotIn("Approve</button>", panel)
        self.assertNotIn("Decline</button>", panel)


class DecisionTests(_Base):
    # -- approve a sign-up ---------------------------------------------------

    def test_approving_a_signup_makes_them_a_vendor(self):
        response = self._post(
            f"/admin/vendor-signups/{self.ids['rahim']}/approve",
            {"business_name": "Rahim Tea", "license_number": "LIC-RAHIM"},
        )
        self.assertEqual(response.status_code, 302)
        role, vendor = self._user_state("rahim")
        self.assertEqual(role, "vendor")
        self.assertEqual(vendor[:2], ("approved", "Rahim Tea"))

    def test_approving_a_signup_needs_business_name_and_licence(self):
        self._post(
            f"/admin/vendor-signups/{self.ids['rahim']}/approve",
            {"business_name": "Rahim Tea", "license_number": "  "},
        )
        self.assertEqual(self._user_state("rahim"), ("student", None))

    def test_approving_with_a_duplicate_licence_changes_nothing(self):
        self._post(
            f"/admin/vendor-signups/{self.ids['rahim']}/approve",
            {"business_name": "Rahim Tea", "license_number": "LIC-K"},
        )
        self.assertEqual(self._user_state("rahim"), ("student", None))

    def test_signup_actions_reject_someone_who_is_not_a_vendor_signup(self):
        for who in ("real_student", "legacy", "ext_inspector"):
            for action in ("approve", "decline"):
                self._post(
                    f"/admin/vendor-signups/{self.ids[who]}/{action}",
                    {"business_name": "X", "license_number": "L-" + who},
                )
        for who in ("real_student", "legacy"):
            self.assertEqual(self._user_state(who), ("student", None))
        self.assertEqual(self._user_state("ext_inspector"), ("inspector", None))

    def test_a_signup_that_has_since_applied_cannot_be_approved_this_way(self):
        self._post(
            f"/admin/vendor-signups/{self.ids['applicant']}/approve",
            {"business_name": "Hijack", "license_number": "LIC-HIJACK"},
        )
        role, vendor = self._user_state("applicant")
        self.assertEqual(role, "student")
        self.assertEqual(vendor[:2], ("pending", "Karim Foods"))

    # -- decline -------------------------------------------------------------

    def test_declining_a_signup_records_a_rejection_the_applicant_can_read(self):
        self._post(
            f"/admin/vendor-signups/{self.ids['rahim']}/decline",
            {"rejection_reason": "We couldn't verify you."},
        )
        role, vendor = self._user_state("rahim")
        self.assertEqual(role, "student")
        self.assertEqual((vendor[0], vendor[2]), ("rejected", "We couldn't verify you."))

        self._login("rahim")
        page = self.client.get("/customer/vendor-application").get_data(as_text=True)
        self.assertIn("We couldn&#39;t verify you.", page)
        # ... and they can't just apply again.
        self.assertEqual(self._user_state("rahim")[1][0], "rejected")
        self.client.post(
            "/customer/vendor-application",
            data={"_csrf_token": "tok", "business_name": "Again", "license_number": "L2",
                  "requested_stall_name": "S", "requested_address": "A", "requested_area_id": "1"},
        )
        self.assertEqual(self._user_state("rahim")[1][1], "(no application submitted)")

    def test_declined_signups_leave_the_requests_panel_and_appear_in_history(self):
        self._post(f"/admin/vendor-signups/{self.ids['rahim']}/decline")
        body = self._get()
        self.assertNotIn("rahim@gmail.com", self._panel(body))
        self.assertIn("rahim@gmail.com", body.split("Application</th>")[1])

    def test_declining_a_submitted_application_still_works(self):
        self._post(
            f"/admin/vendors/{self.applicant_vendor_id}/reject",
            {"rejection_reason": "Licence expired"},
        )
        self.assertEqual(self._user_state("applicant")[1][0], "rejected")

    def test_approving_a_submitted_application_still_works(self):
        self._post(f"/admin/vendors/{self.applicant_vendor_id}/approve")
        role, vendor = self._user_state("applicant")
        self.assertEqual((role, vendor[0]), ("vendor", "approved"))

    # -- permissions ---------------------------------------------------------

    def test_a_viewer_cannot_decide(self):
        for path in (
            f"/admin/vendor-signups/{self.ids['rahim']}/approve",
            f"/admin/vendor-signups/{self.ids['rahim']}/decline",
            f"/admin/vendor-requests/{self.ids['rahim']}/inquiry",
        ):
            self.assertEqual(
                self._post(path, {"business_name": "x", "license_number": "y", "message": "hi"}, who="viewer").status_code,
                403,
            )
        self.assertEqual(self._user_state("rahim"), ("student", None))


class InquiryTests(_Base):
    def test_inquiry_to_a_signup_reaches_their_portal(self):
        response = self._post(
            f"/admin/vendor-requests/{self.ids['rahim']}/inquiry",
            {"message": "Please add your licence number."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self._notifications("rahim"), [MESSAGE_PREFIX + "Please add your licence number."]
        )

    def test_inquiry_to_a_pending_application_works(self):
        self._post(
            f"/admin/vendor-requests/{self.ids['applicant']}/inquiry",
            {"message": "Which gate is the stall at?"},
        )
        self.assertEqual(len(self._notifications("applicant")), 1)

    def test_inquiry_is_refused_for_anyone_who_is_not_an_open_request(self):
        for who in ("real_student", "legacy", "ext_inspector"):
            self._post(f"/admin/vendor-requests/{self.ids[who]}/inquiry", {"message": "hello"})
            self.assertEqual(self._notifications(who), [])

    def test_empty_or_overlong_inquiries_are_refused(self):
        self._post(f"/admin/vendor-requests/{self.ids['rahim']}/inquiry", {"message": "   "})
        self._post(
            f"/admin/vendor-requests/{self.ids['rahim']}/inquiry",
            {"message": "x" * (INQUIRY_MAX_LENGTH + 1)},
        )
        self.assertEqual(self._notifications("rahim"), [])

    def test_the_applicant_sees_the_inquiry_once_as_new(self):
        self._post(
            f"/admin/vendor-requests/{self.ids['rahim']}/inquiry",
            {"message": "Please add your licence number."},
        )
        self._login("rahim")
        first = self.client.get("/customer/vendor-application").get_data(as_text=True)
        self.assertIn("Messages from the review team", first)
        self.assertIn("Please add your licence number.", first)
        self.assertIn(">NEW<", first)

        second = self.client.get("/customer/vendor-application").get_data(as_text=True)
        self.assertIn("Please add your licence number.", second)
        self.assertNotIn(">NEW<", second)

    def test_a_pending_applicant_can_answer_by_updating_the_application(self):
        self._login("applicant")
        response = self.client.post(
            "/customer/vendor-application",
            data={
                "_csrf_token": "tok",
                "business_name": "Karim Foods Ltd",
                "license_number": "LIC-K2",
                "requested_stall_name": "Karim Corner 2",
                "requested_address": "Gate 3",
                "requested_area_id": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        vendor = self._user_state("applicant")[1]
        self.assertEqual(vendor[:2], ("pending", "Karim Foods Ltd"))

    def test_the_update_form_is_prefilled_and_only_shown_while_pending(self):
        self._login("applicant")
        page = self.client.get("/customer/vendor-application").get_data(as_text=True)
        self.assertIn('value="Karim Foods"', page)
        self.assertIn("Save changes", page)

        # a decided application can no longer be edited
        with self.app.app_context():
            Vendor.query.filter_by(status="pending").update({"status": "rejected"})
            db.session.commit()
        page = self.client.get("/customer/vendor-application").get_data(as_text=True)
        self.assertNotIn("Save changes", page)
        self.client.post(
            "/customer/vendor-application",
            data={"_csrf_token": "tok", "business_name": "Changed", "license_number": "L9",
                  "requested_stall_name": "S", "requested_address": "A", "requested_area_id": "1"},
        )
        self.assertEqual(self._user_state("applicant")[1][1], "Karim Foods")


if __name__ == "__main__":
    unittest.main()
