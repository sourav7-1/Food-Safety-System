import unittest
from datetime import datetime

from app import create_app
from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    Inspection,
    InspectionDispute,
    Inspector,
    Notification,
    Role,
    Stall,
    User,
    Vendor,
)
from services.inspector_notifications import (
    notify_inspector_of_dispute,
    notify_inspectors_of_new_complaint,
)


class InspectorNotificationTestConfig:
    TESTING = True
    SECRET_KEY = "inspector-notification-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = False


class InspectorNotificationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(InspectorNotificationTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(role_name="inspector"),
                    Role(role_name="student"),
                    Role(role_name="vendor"),
                ]
            )
            db.session.commit()
            roles = {r.role_name: r.role_id for r in Role.query.all()}

            area_a = Area(area_name="Area A", city="Test City", zone="")
            area_b = Area(area_name="Area B", city="Test City", zone="")
            db.session.add_all([area_a, area_b])
            db.session.flush()

            def make_user(name, email, role):
                user = User(
                    role_id=roles[role],
                    full_name=name,
                    email=email,
                    status="active",
                )
                user.set_password("SecurePass123")
                db.session.add(user)
                return user

            in_area = make_user("Inspector A", "ins-a@example.test", "inspector")
            out_area = make_user("Inspector B", "ins-b@example.test", "inspector")
            all_areas = make_user("Inspector All", "ins-all@example.test", "inspector")
            student = make_user("Student", "notif-student@example.test", "student")
            vendor_user = make_user("Vendor", "notif-vendor@example.test", "vendor")
            db.session.flush()

            db.session.add_all(
                [
                    Inspector(user_id=in_area.user_id, employee_code="A-1", assigned_area_id=area_a.area_id),
                    Inspector(user_id=out_area.user_id, employee_code="B-1", assigned_area_id=area_b.area_id),
                    Inspector(user_id=all_areas.user_id, employee_code="ALL-1"),
                ]
            )
            vendor = Vendor(
                user_id=vendor_user.user_id,
                business_name="Karim Foods",
                license_number="LIC-N",
            )
            db.session.add(vendor)
            db.session.flush()

            stall = Stall(
                vendor_id=vendor.vendor_id,
                area_id=area_a.area_id,
                stall_name="Karim Biryani",
                stall_code="KB-1",
                address="Main gate",
                status="active",
            )
            ctype = ComplaintType(type_name="Poor hygiene", severity_level="medium")
            db.session.add_all([stall, ctype])
            db.session.commit()

            self.in_area_id = in_area.user_id
            self.out_area_id = out_area.user_id
            self.all_areas_id = all_areas.user_id
            self.student_id = student.user_id
            self.vendor_id = vendor.vendor_id
            self.stall_id = stall.stall_id
            self.ctype_id = ctype.complaint_type_id
            self.in_area_inspector_id = Inspector.query.filter_by(user_id=in_area.user_id).one().inspector_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
            session["_csrf_token"] = "test-csrf-token"
        return "test-csrf-token"

    def _notifications_for(self, user_id):
        with self.app.app_context():
            return [
                (n.message, n.complaint_id, n.is_read)
                for n in Notification.query.filter_by(user_id=user_id).all()
            ]

    def _add_notification(self, user_id, message="Test alert", complaint_id=None, is_read=False):
        with self.app.app_context():
            n = Notification(user_id=user_id, message=message, complaint_id=complaint_id, is_read=is_read)
            db.session.add(n)
            db.session.commit()
            return n.notification_id

    def _add_complaint(self):
        with self.app.app_context():
            complaint = Complaint(
                stall_id=self.stall_id,
                complaint_type_id=self.ctype_id,
                submitted_by_user_id=self.student_id,
                title="Flies on food",
                description="Lots of flies.",
                status="submitted",
            )
            db.session.add(complaint)
            db.session.commit()
            return complaint.complaint_id

    # -- who gets notified ---------------------------------------------------

    def test_new_complaint_notifies_area_and_all_area_inspectors_only(self):
        token = self._login(self.student_id)
        response = self.client.post(
            f"/customer/stalls/{self.stall_id}/complaint",
            data={
                "_csrf_token": token,
                "complaint_type_id": self.ctype_id,
                "title": "Flies on food",
                "description": "Lots of flies.",
            },
        )
        self.assertEqual(response.status_code, 302)

        in_area = self._notifications_for(self.in_area_id)
        all_areas = self._notifications_for(self.all_areas_id)
        self.assertEqual(len(in_area), 1)
        self.assertEqual(len(all_areas), 1)
        self.assertIn("Flies on food", in_area[0][0])
        self.assertIn("Karim Biryani", in_area[0][0])
        self.assertIsNotNone(in_area[0][1])  # linked to the complaint
        self.assertEqual(self._notifications_for(self.out_area_id), [])

    def test_dispute_notifies_the_inspector_who_did_the_inspection(self):
        with self.app.app_context():
            inspection = Inspection(
                stall_id=self.stall_id,
                inspector_id=self.in_area_inspector_id,
                inspection_date=datetime(2026, 8, 28, 19, 18),
                overall_score=80,
                risk_level="low",
                status="submitted",
            )
            db.session.add(inspection)
            db.session.flush()
            dispute = InspectionDispute(
                inspection_id=inspection.inspection_id,
                vendor_id=self.vendor_id,
                reason="The score does not match what happened.",
            )
            db.session.add(dispute)
            db.session.commit()
            notify_inspector_of_dispute(dispute)

        notes = self._notifications_for(self.in_area_id)
        self.assertEqual(len(notes), 1)
        self.assertIn("Karim Foods disputed", notes[0][0])
        self.assertIsNone(notes[0][1])  # not tied to a complaint
        self.assertEqual(self._notifications_for(self.out_area_id), [])

    def test_service_is_safe_when_no_inspector_covers_the_area(self):
        with self.app.app_context():
            Inspector.query.delete()
            db.session.commit()
            complaint = Complaint(
                stall_id=self.stall_id,
                complaint_type_id=self.ctype_id,
                title="x",
                description="y",
                status="submitted",
            )
            db.session.add(complaint)
            db.session.commit()
            notify_inspectors_of_new_complaint(complaint)
            self.assertEqual(Notification.query.count(), 0)

    # -- list page -----------------------------------------------------------

    def test_list_shows_only_own_notifications_and_counts(self):
        self._add_notification(self.in_area_id, "For inspector A")
        self._add_notification(self.in_area_id, "Already seen", is_read=True)
        self._add_notification(self.out_area_id, "For inspector B")
        self._login(self.in_area_id)
        response = self.client.get("/inspector/notifications/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("For inspector A", body)
        self.assertIn("Already seen", body)
        self.assertNotIn("For inspector B", body)
        self.assertIn("Mark all as read", body)
        self.assertIn("insNotifView", body)

    def test_empty_state(self):
        self._login(self.in_area_id)
        body = self.client.get("/inspector/notifications/").get_data(as_text=True)
        self.assertIn("all caught up", body)

    def test_sidebar_shows_link_and_unread_badge_on_other_inspector_pages(self):
        self._add_notification(self.in_area_id)
        self._add_notification(self.in_area_id)
        self._login(self.in_area_id)
        body = self.client.get("/inspector/inspections/").get_data(as_text=True)
        self.assertIn("/inspector/notifications/", body)
        self.assertIn('data-ins-unread-count>2<', body)
        self.assertIn("data-ins-bell-dot", body)

    def test_student_is_blocked(self):
        self._login(self.student_id)
        self.assertEqual(self.client.get("/inspector/notifications/").status_code, 403)

    # -- mark read -----------------------------------------------------------

    def test_mark_read_json_returns_remaining_unread(self):
        first = self._add_notification(self.in_area_id, "one")
        self._add_notification(self.in_area_id, "two")
        token = self._login(self.in_area_id)
        response = self.client.post(
            f"/inspector/notifications/{first}/read",
            data={"_csrf_token": token},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "notification_id": first, "unread_count": 1})

    def test_open_complaint_form_marks_read_and_goes_to_the_complaint(self):
        complaint_id = self._add_complaint()
        nid = self._add_notification(self.in_area_id, "alert", complaint_id=complaint_id)
        token = self._login(self.in_area_id)
        response = self.client.post(
            f"/inspector/notifications/{nid}/read", data={"_csrf_token": token}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/inspector/complaints/{complaint_id}"))
        self.assertTrue(self._notifications_for(self.in_area_id)[0][2])

    def test_mark_read_with_stay_returns_to_the_list(self):
        complaint_id = self._add_complaint()
        nid = self._add_notification(self.in_area_id, "alert", complaint_id=complaint_id)
        token = self._login(self.in_area_id)
        response = self.client.post(
            f"/inspector/notifications/{nid}/read",
            data={"_csrf_token": token, "stay": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/inspector/notifications/"))

    def test_cannot_mark_someone_elses_notification(self):
        nid = self._add_notification(self.out_area_id, "not yours")
        token = self._login(self.in_area_id)
        response = self.client.post(
            f"/inspector/notifications/{nid}/read", data={"_csrf_token": token}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self._notifications_for(self.out_area_id)[0][2])

    def test_mark_all_read_only_touches_own_notifications(self):
        self._add_notification(self.in_area_id, "a")
        self._add_notification(self.in_area_id, "b")
        self._add_notification(self.out_area_id, "c")
        token = self._login(self.in_area_id)
        response = self.client.post(
            "/inspector/notifications/read-all",
            data={"_csrf_token": token},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.get_json(), {"success": True, "unread_count": 0})
        self.assertTrue(all(read for _, _, read in self._notifications_for(self.in_area_id)))
        self.assertFalse(self._notifications_for(self.out_area_id)[0][2])


if __name__ == "__main__":
    unittest.main()
