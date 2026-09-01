# Complete End-to-End Functional, Interaction and Visual QA Test Suite
import os
import unittest
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from sqlalchemy import text
from app import create_app
from extensions import db
from models import (
    Area, Complaint, ComplaintType, Inspection, Inspector, Permission, Role,
    Stall, User, Vendor, FoodItem, Review, FoodCategory, RoleRequest,
    InspectionCriterion, InspectionScore, InspectionDispute, CorrectiveAction
)

class FullBrowserQATests(unittest.TestCase):
    def setUp(self):
        class QAConfig:
            TESTING = True
            SECRET_KEY = 'qa-test-secret'
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            WTF_CSRF_ENABLED = False
            RATELIMIT_ENABLED = False

        self.app = create_app(QAConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            from sqlalchemy import event
            @event.listens_for(db.engine, "connect")
            def _set_sqlite_field(dbapi_connection, connection_record):
                def _field(val, *targets):
                    try:
                        return targets.index(val) + 1
                    except (ValueError, TypeError):
                        return 0
                if hasattr(dbapi_connection, "create_function"):
                    dbapi_connection.create_function("FIELD", -1, _field)

            db.create_all()
            db.session.execute(text("CREATE VIEW IF NOT EXISTS high_risk_stalls AS SELECT s.stall_id, s.stall_name, a.area_name, a.city, 45.0 as overall_score, 'D' as hygiene_grade, 'high' as risk_level, CURRENT_TIMESTAMP as inspection_date FROM stalls s JOIN areas a ON s.area_id = a.area_id;"))
            db.session.execute(text("CREATE VIEW IF NOT EXISTS low_risk_stalls AS SELECT s.stall_id, s.stall_name, a.area_name, a.city, 95.0 as overall_score, 'A' as hygiene_grade, 'low' as risk_level, CURRENT_TIMESTAMP as inspection_date FROM stalls s JOIN areas a ON s.area_id = a.area_id;"))
            db.session.execute(text("CREATE VIEW IF NOT EXISTS latest_stall_inspection AS SELECT s.stall_id, 85.0 as overall_score, 'low' as risk_level FROM stalls s;"))
            db.session.commit()

            self.admin_role = Role(role_name='super_admin', description='Super Admin', is_admin_tier=True, is_system=True)
            self.student_role = Role(role_name='student', description='Student', is_admin_tier=False, is_system=True)
            self.vendor_role = Role(role_name='vendor', description='Vendor', is_admin_tier=False, is_system=True)
            self.inspector_role = Role(role_name='inspector', description='Inspector', is_admin_tier=False, is_system=True)
            db.session.add_all([self.admin_role, self.student_role, self.vendor_role, self.inspector_role])
            db.session.commit()

            all_perm_codes = [
                'users.view', 'users.create', 'users.edit', 'users.deactivate', 'users.delete',
                'roles.manage', 'vendors.view', 'vendors.approve', 'vendors.suspend',
                'stalls.view', 'stalls.manage', 'inspections.view', 'inspections.conduct',
                'complaints.view', 'complaints.respond', 'complaints.escalate',
                'inspection_disputes.view', 'inspection_disputes.review',
                'reviews.view', 'reviews.moderate', 'risk_engine.view', 'reports.view', 'settings.view'
            ]
            for c in all_perm_codes:
                p = Permission(code=c, description=c)
                db.session.add(p)
                self.admin_role.permissions.append(p)
            db.session.commit()

            self.area = Area(area_name='Daffodil Smart City', city='Dhaka')
            self.category = FoodCategory(category_name='Fast Food & Snacks', risk_level='medium')
            self.complaint_type = ComplaintType(type_name='Hygiene & Cleanliness', severity_level='medium')
            self.criterion = InspectionCriterion(criteria_name='Food Temperature & Storage', max_score=20, weight=1.0)
            db.session.add_all([self.area, self.category, self.complaint_type, self.criterion])
            db.session.commit()

            now = datetime.now(timezone.utc)
            self.admin_user = User(email='admin@diu.edu.bd', full_name='Admin Boss', role_id=self.admin_role.role_id, is_super_admin=True, status='active', email_verified_at=now)
            self.admin_user.set_password('AdminPass123!')

            self.student_user = User(email='student221-15-123@diu.edu.bd', full_name='Student Rahat', role_id=self.student_role.role_id, status='active', email_verified_at=now)
            self.student_user.set_password('StudentPass123!')

            self.vendor_user = User(email='vendor@diu.edu.bd', full_name='Vendor Karim', role_id=self.vendor_role.role_id, status='active', email_verified_at=now)
            self.vendor_user.set_password('VendorPass123!')

            self.inspector_user = User(email='inspector@diu.edu.bd', full_name='Inspector Salim', role_id=self.inspector_role.role_id, status='active', email_verified_at=now)
            self.inspector_user.set_password('InspectorPass123!')

            db.session.add_all([self.admin_user, self.student_user, self.vendor_user, self.inspector_user])
            db.session.commit()

            self.vendor_profile = Vendor(user_id=self.vendor_user.user_id, business_name='Karim Food Corner', license_number='LIC-998', status='approved')
            self.inspector_profile = Inspector(user_id=self.inspector_user.user_id, employee_code='INS-007', designation='Safety Officer')
            db.session.add_all([self.vendor_profile, self.inspector_profile])
            db.session.commit()

            self.stall = Stall(stall_name='Karim Biryani & Grill', stall_code='STL-001', area_id=self.area.area_id, vendor_id=self.vendor_profile.vendor_id, address='Level 1 Food Court')
            db.session.add(self.stall)
            db.session.commit()

            self.item1 = FoodItem(stall_id=self.stall.stall_id, category_id=self.category.category_id, item_name='Chicken Biryani', price=180.0, is_available=True)
            self.item2 = FoodItem(stall_id=self.stall.stall_id, category_id=self.category.category_id, item_name='Fresh Lemonade', price=40.0, is_available=True)
            db.session.add_all([self.item1, self.item2])
            db.session.commit()

            self.admin_id = self.admin_user.user_id
            self.student_id = self.student_user.user_id
            self.vendor_id = self.vendor_user.user_id
            self.inspector_id = self.inspector_user.user_id
            self.stall_id = self.stall.stall_id
            self.category_id = self.category.category_id
            self.complaint_type_id = self.complaint_type.complaint_type_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self, user_id):
        token = 'test-csrf-token'
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        return token

    # --- 1. Public & Auth Views Tests ---
    def test_homepage_render_and_dom_elements(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        soup = BeautifulSoup(resp.data.decode('utf-8'), 'html.parser')
        self.assertIn('DIU Food Safety System', soup.title.string)
        self.assertTrue(len(soup.find_all('nav')) > 0)

    def test_login_and_register_pages(self):
        for path in ['/login', '/register', '/resend-verification']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)
            soup = BeautifulSoup(resp.data.decode('utf-8'), 'html.parser')
            self.assertTrue(len(soup.find_all('input')) > 0)

    def test_search_and_leaderboard_pages(self):
        self._login(self.student_id)
        resp = self.client.get('/customer/stalls')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Karim Biryani', resp.data.decode('utf-8'))

        resp = self.client.get('/customer/leaderboard')
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(f'/customer/stalls/{self.stall_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Chicken Biryani', resp.data.decode('utf-8'))

    # --- 2. Student Portal Views Tests ---
    def test_student_portal_views(self):
        self._login(self.student_id)
        for path in ['/profile', '/customer/complaints', '/customer/notifications', '/customer/vendor-application', '/access-requests']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f'Student failed to load {path}')

    # --- 3. Vendor Portal Views Tests ---
    def test_vendor_portal_views(self):
        self._login(self.vendor_id)
        for path in ['/vendor/', f'/vendor/stalls/{self.stall_id}/food-items', '/vendor/complaints', f'/vendor/stalls/{self.stall_id}']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f'Vendor failed to load {path}')

    # --- 4. Inspector Workspace Views Tests ---
    def test_inspector_workspace_views(self):
        self._login(self.inspector_id)
        for path in ['/inspector/inspections/', '/inspector/inspections/new']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f'Inspector failed to load {path}')

    # --- 5. Admin Console Views Tests ---
    def test_admin_console_all_panels(self):
        self._login(self.admin_id)
        admin_paths = [
            '/dashboard/admin',
            '/admin/vendors',
            '/admin/stalls',
            '/admin/inspections',
            '/admin/complaints',
            '/admin/inspection-disputes',
            '/admin/reviews',
            '/admin/risk-engine',
            '/admin/reports/',
            '/admin/users',
            '/admin/roles',
            '/admin/audit-log',
            '/admin/audit-log/logins',
            '/admin/access-requests',
            '/admin/settings'
        ]
        for path in admin_paths:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f'Admin failed to load {path}')
            soup = BeautifulSoup(resp.data.decode('utf-8'), 'html.parser')
            self.assertTrue(len(soup.find_all('aside', {'class': 'admin-sidebar'})) > 0 or len(soup.find_all('div', {'class': 'admin-shell'})) > 0, f'Missing admin sidebar structure on {path}')

    # --- 6. Custom Error Views Tests ---
    def test_custom_error_pages(self):
        resp = self.client.get('/page-that-definitely-does-not-exist-404-test')
        self.assertEqual(resp.status_code, 404)
        self.assertIn('Page Not Found', resp.data.decode('utf-8'))

    # --- 7. Interactive CRUD Operations Tests ---
    def test_vendor_food_item_crud_flow(self):
        csrf = self._login(self.vendor_id)
        # Create new food item
        post_data = {
            '_csrf_token': csrf,
            'item_name': 'Grilled Sandwich',
            'category_id': self.category_id,
            'price': '85.00',
            'is_available': 'y'
        }
        resp = self.client.post(f'/vendor/stalls/{self.stall_id}/food-items/new', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Grilled Sandwich', resp.data.decode('utf-8'))

    def test_student_complaint_submission(self):
        csrf = self._login(self.student_id)
        post_data = {
            '_csrf_token': csrf,
            'complaint_type_id': self.complaint_type_id,
            'title': 'Cold food served',
            'description': 'Food was cold and uncovered when received.'
        }
        resp = self.client.post(f'/customer/stalls/{self.stall_id}/complaint', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Cold food served', resp.data.decode('utf-8'))

    def test_student_review_submission(self):
        csrf = self._login(self.student_id)
        post_data = {
            '_csrf_token': csrf,
            'rating': '5',
            'review_text': 'Great quality and clean preparation!'
        }
        resp = self.client.post(f'/customer/stalls/{self.stall_id}/review', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

if __name__ == '__main__':
    unittest.main()
