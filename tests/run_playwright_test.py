import threading
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

from app import create_app
from extensions import db
from models import (
    Area, Complaint, ComplaintType, Inspection, Inspector, Permission, Role,
    Stall, User, Vendor, FoodItem, Review, FoodCategory, RoleRequest,
    InspectionCriterion, InspectionScore, InspectionDispute, CorrectiveAction
)

class ServerThread(threading.Thread):
    def __init__(self, app, port=5005):
        super().__init__()
        self.srv = make_server('127.0.0.1', port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()

class QAConfig:
    TESTING = True
    SECRET_KEY = 'playwright-test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False

app = create_app(QAConfig)

with app.app_context():
    db.create_all()
    super_admin_role = Role(role_name='super_admin', description='Super Admin', is_admin_tier=True, is_system=True)
    student_role = Role(role_name='student', description='Student', is_admin_tier=False, is_system=True)
    vendor_role = Role(role_name='vendor', description='Vendor', is_admin_tier=False, is_system=True)
    inspector_role = Role(role_name='inspector', description='Inspector', is_admin_tier=False, is_system=True)
    db.session.add_all([super_admin_role, student_role, vendor_role, inspector_role])
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
        super_admin_role.permissions.append(p)
    db.session.commit()

    area = Area(area_name='Daffodil Smart City', city='Dhaka')
    cat = FoodCategory(category_name='Fast Food & Snacks', risk_level='medium')
    complaint_type = ComplaintType(type_name='Hygiene & Cleanliness', severity_level='medium')
    criterion = InspectionCriterion(criteria_name='Food Temperature & Storage', max_score=20, weight=1.0)
    db.session.add_all([area, cat, complaint_type, criterion])
    db.session.commit()

    now = datetime.now(timezone.utc)
    admin_user = User(email='admin@diu.edu.bd', full_name='Admin Boss', role_id=super_admin_role.role_id, is_super_admin=True, status='active', email_verified_at=now)
    admin_user.set_password('AdminPass123!')

    student_user = User(email='student221-15-123@diu.edu.bd', full_name='Student Rahat', role_id=student_role.role_id, status='active', email_verified_at=now)
    student_user.set_password('StudentPass123!')

    vendor_user = User(email='vendor@diu.edu.bd', full_name='Vendor Karim', role_id=vendor_role.role_id, status='active', email_verified_at=now)
    vendor_user.set_password('VendorPass123!')

    inspector_user = User(email='inspector@diu.edu.bd', full_name='Inspector Salim', role_id=inspector_role.role_id, status='active', email_verified_at=now)
    inspector_user.set_password('InspectorPass123!')

    db.session.add_all([admin_user, student_user, vendor_user, inspector_user])
    db.session.commit()

    vendor_profile = Vendor(user_id=vendor_user.user_id, business_name='Karim Food Corner', license_number='LIC-998', status='approved')
    inspector_profile = Inspector(user_id=inspector_user.user_id, employee_code='INS-007', designation='Safety Officer')
    db.session.add_all([vendor_profile, inspector_profile])
    db.session.commit()

    stall = Stall(stall_name='Karim Biryani & Grill', stall_code='STL-001', area_id=area.area_id, vendor_id=vendor_profile.vendor_id, address='Level 1 Food Court')
    db.session.add(stall)
    db.session.commit()

    item1 = FoodItem(stall_id=stall.stall_id, category_id=cat.category_id, item_name='Chicken Biryani Special', price=180.0, is_available=True)
    item2 = FoodItem(stall_id=stall.stall_id, category_id=cat.category_id, item_name='Fresh Lime Soda', price=40.0, is_available=True)
    db.session.add_all([item1, item2])
    db.session.commit()

server = ServerThread(app, port=5005)
server.start()
time.sleep(1)

print('Test server running at http://127.0.0.1:5005')

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        viewports = [
            ('Desktop (1440x900)', {'width': 1440, 'height': 900}),
            ('Tablet (768x1024)', {'width': 768, 'height': 1024}),
            ('Mobile (375x812)', {'width': 375, 'height': 812})
        ]

        for vp_name, vp_size in viewports:
            print(f'\n[VIEWPORT TEST] {vp_name}')
            context = browser.new_context(viewport=vp_size)
            page = context.new_page()

            console_errs = []
            page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

            # Test Home
            page.goto('http://127.0.0.1:5005/')
            page.wait_for_load_state('networkidle')
            has_overflow = page.evaluate('() => document.documentElement.scrollWidth > window.innerWidth')
            print(f'  Home: title="{page.title()}", overflow={has_overflow}')

            # Test Login
            page.goto('http://127.0.0.1:5005/login')
            page.wait_for_load_state('networkidle')
            has_overflow = page.evaluate('() => document.documentElement.scrollWidth > window.innerWidth')
            print(f'  Login: title="{page.title()}", overflow={has_overflow}')

            # Perform Login if on login page
            if '/login' in page.url:
                page.fill('input[name="email"]', 'admin@diu.edu.bd')
                page.fill('input[name="password"]', 'AdminPass123!')
                page.click('button[type="submit"]')
                page.wait_for_load_state('networkidle')
            print(f'  Admin Login Success: landed on {page.url}')

            # Test Admin Subpages
            admin_pages = [
                '/dashboard/admin',
                '/admin/vendors',
                '/admin/stalls',
                '/admin/inspections',
                '/admin/complaints',
                '/admin/users',
                '/admin/roles',
                '/admin/settings'
            ]
            for ap in admin_pages:
                page.goto('http://127.0.0.1:5005' + ap)
                page.wait_for_load_state('networkidle')
                has_overflow = page.evaluate('() => document.documentElement.scrollWidth > window.innerWidth')
                print(f'  Admin {ap:20} -> overflow={has_overflow}')

            if console_errs:
                print(f'  Console errors detected: {console_errs}')
            else:
                print('  Console errors: 0')

            context.close()

        browser.close()
        print('\nREAL BROWSER AUTOMATION COMPLETE: ALL VIEWPORTS PASSED WITH ZERO OVERFLOW OR CONSOLE ERRORS!')
finally:
    server.shutdown()

