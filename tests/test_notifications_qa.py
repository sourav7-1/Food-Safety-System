# Comprehensive QA Test Suite for Customer Notifications & Modal System
import unittest
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from sqlalchemy import text

from app import create_app
from extensions import db
from models import (
    Area, Complaint, ComplaintType, Notification, Role, Stall, User, Vendor, FoodCategory
)

class NotificationsQATests(unittest.TestCase):
    def setUp(self):
        class QAConfig:
            TESTING = True
            SECRET_KEY = 'qa-notifications-secret'
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            WTF_CSRF_ENABLED = False
            RATELIMIT_ENABLED = False

        self.app = create_app(QAConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.student_role = Role(role_name='student', description='Student', is_admin_tier=False, is_system=True)
            self.vendor_role = Role(role_name='vendor', description='Vendor', is_admin_tier=False, is_system=True)
            db.session.add_all([self.student_role, self.vendor_role])
            db.session.commit()

            area = Area(area_name='Daffodil Smart City', city='Dhaka')
            cat = FoodCategory(category_name='Drinks & Beverages', risk_level='low')
            complaint_type = ComplaintType(type_name='Hygiene & Cleanliness', severity_level='medium')
            db.session.add_all([area, cat, complaint_type])
            db.session.commit()

            now = datetime.now(timezone.utc)
            self.student = User(
                email='student221-15-777@diu.edu.bd',
                full_name='Student Tester',
                role_id=self.student_role.role_id,
                status='active',
                email_verified_at=now
            )
            self.student.set_password('StudentPass123!')

            self.vendor_user = User(
                email='vendor777@diu.edu.bd',
                full_name='Vendor Tester',
                role_id=self.vendor_role.role_id,
                status='active',
                email_verified_at=now
            )
            self.vendor_user.set_password('VendorPass123!')
            db.session.add_all([self.student, self.vendor_user])
            db.session.commit()

            vendor_prof = Vendor(user_id=self.vendor_user.user_id, business_name='Tasty Treat', license_number='LIC-777', status='approved')
            db.session.add(vendor_prof)
            db.session.commit()

            stall = Stall(stall_name='Tasty Treat Food Court', stall_code='STL-777', area_id=area.area_id, vendor_id=vendor_prof.vendor_id, address='Food Court 2')
            db.session.add(stall)
            db.session.commit()

            # Create complaints and notifications
            self.complaint1 = Complaint(
                stall_id=stall.stall_id,
                complaint_type_id=complaint_type.complaint_type_id,
                submitted_by_user_id=self.student.user_id,
                title='Water filter issue',
                description='The drinking water tasted strange today.',
                status='action_required',
                admin_response='Inspector requested stall owner to change water filter immediately.'
            )
            self.complaint2 = Complaint(
                stall_id=stall.stall_id,
                complaint_type_id=complaint_type.complaint_type_id,
                submitted_by_user_id=self.student.user_id,
                title='Cold food served',
                description='The chicken sandwich was served cold.',
                status='resolved',
                admin_response='Vendor adjusted food warmer temperatures.'
            )
            db.session.add_all([self.complaint1, self.complaint2])
            db.session.commit()

            self.notif1 = Notification(
                user_id=self.student.user_id,
                complaint_id=self.complaint1.complaint_id,
                message='Your complaint "Water filter issue" is now Action Required. Admin note: Inspector requested filter change.',
                is_read=False
            )
            self.notif2 = Notification(
                user_id=self.student.user_id,
                complaint_id=self.complaint2.complaint_id,
                message='Your complaint "Cold food served" is now Resolved.',
                is_read=False
            )
            self.notif3 = Notification(
                user_id=self.student.user_id,
                complaint_id=None,
                message='Welcome to the DIU Food Safety System notifications hub.',
                is_read=True
            )
            db.session.add_all([self.notif1, self.notif2, self.notif3])
            db.session.commit()

            self.student_id = self.student.user_id
            self.notif1_id = self.notif1.notification_id
            self.notif2_id = self.notif2.notification_id
            self.notif3_id = self.notif3.notification_id

    def _login(self, user_id):
        token = 'test-csrf-token'
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        return token

    def test_notifications_page_rendering_and_stats(self):
        """Test GET /customer/notifications renders stat cards, filter tabs, cards, and modal."""
        self._login(self.student_id)
        resp = self.client.get('/customer/notifications')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')

        # Check title and header
        self.assertIn("Notification Center", html)
        self.assertIn("Your Complaint & Safety Updates", html)

        # Check summary metrics
        self.assertIn('Total Alerts', html)
        self.assertIn('Action Required', html)
        self.assertIn('Resolved / Closed', html)

        # Check Filter tabs
        filter_tabs = soup.find_all(class_='notif-tab-btn')
        self.assertTrue(len(filter_tabs) >= 4)

        # Check Notification Cards
        cards = soup.find_all(class_='notif-card')
        self.assertEqual(len(cards), 3)

        # Verify modal exists in DOM
        modal = soup.find(id='notificationDetailModal')
        self.assertIsNotNone(modal)
        self.assertIn('Notification Details', modal.get_text())

    def test_notification_modal_data_attributes(self):
        """Test that notification cards contain all structured data attributes for modal population."""
        self._login(self.student_id)
        resp = self.client.get('/customer/notifications')
        soup = BeautifulSoup(resp.data.decode('utf-8'), 'html.parser')

        card1 = soup.find(id=f'notifCard-{self.notif1_id}')
        self.assertIsNotNone(card1)
        self.assertEqual(card1.get('data-status'), 'action_required')
        self.assertEqual(card1.get('data-is-read'), '0')
        self.assertEqual(card1.get('data-complaint-title'), 'Water filter issue')
        self.assertIn('Inspector requested', card1.get('data-admin-response'))
        self.assertIn('Tasty Treat Food Court', card1.get('data-stall-name'))

    def test_mark_single_notification_read_ajax(self):
        """Test POST /customer/notifications/<id>/read via AJAX returns JSON and updates is_read."""
        token = self._login(self.student_id)
        resp = self.client.post(
            f'/customer/notifications/{self.notif1_id}/read',
            headers={'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': token}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['notification_id'], self.notif1_id)
        self.assertEqual(data['unread_count'], 1)  # notif2 is still unread

        with self.app.app_context():
            n1 = db.session.get(Notification, self.notif1_id)
            self.assertTrue(n1.is_read)

    def test_mark_all_notifications_read_ajax(self):
        """Test POST /customer/notifications/read-all via AJAX marks all as read."""
        token = self._login(self.student_id)
        resp = self.client.post(
            '/customer/notifications/read-all',
            headers={'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': token}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['unread_count'], 0)

        with self.app.app_context():
            unread = Notification.query.filter_by(user_id=self.student_id, is_read=False).count()
            self.assertEqual(unread, 0)

if __name__ == '__main__':
    unittest.main()
