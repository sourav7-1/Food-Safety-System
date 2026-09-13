import threading
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

from app import create_app
from extensions import db
from models import (
    Area, Complaint, ComplaintType, Role, Stall, User, Vendor, FoodCategory, Notification
)
from datetime import datetime, timezone

class ServerThread(threading.Thread):
    def __init__(self, app, port=5007):
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
    SECRET_KEY = 'playwright-notif-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False

app = create_app(QAConfig)

with app.app_context():
    db.create_all()
    student_role = Role(role_name='student', description='Student', is_admin_tier=False, is_system=True)
    vendor_role = Role(role_name='vendor', description='Vendor', is_admin_tier=False, is_system=True)
    db.session.add_all([student_role, vendor_role])
    db.session.commit()

    area = Area(area_name='Daffodil Smart City', city='Dhaka')
    cat = FoodCategory(category_name='Fast Food', risk_level='medium')
    complaint_type = ComplaintType(type_name='Hygiene & Cleanliness', severity_level='medium')
    db.session.add_all([area, cat, complaint_type])
    db.session.commit()

    now = datetime.now(timezone.utc)
    student = User(email='student221-15-123@diu.edu.bd', full_name='Sourav Test', role_id=student_role.role_id, status='active', email_verified_at=now)
    student.set_password('StudentPass123!')
    vendor_user = User(email='vendor@diu.edu.bd', full_name='Karim Vendor', role_id=vendor_role.role_id, status='active', email_verified_at=now)
    vendor_user.set_password('VendorPass123!')
    db.session.add_all([student, vendor_user])
    db.session.commit()

    v_prof = Vendor(user_id=vendor_user.user_id, business_name='Karim Food Corner', license_number='LIC-123', status='approved')
    db.session.add(v_prof)
    db.session.commit()

    stall = Stall(stall_name='Karim Biryani & Grill', stall_code='STL-001', area_id=area.area_id, vendor_id=v_prof.vendor_id, address='Food Court 1')
    db.session.add(stall)
    db.session.commit()

    c1 = Complaint(stall_id=stall.stall_id, complaint_type_id=complaint_type.complaint_type_id, submitted_by_user_id=student.user_id, title='Water contamination issue', description='Drinking water smelled bad.', status='action_required', admin_response='Vendor must replace water filter today.')
    c2 = Complaint(stall_id=stall.stall_id, complaint_type_id=complaint_type.complaint_type_id, submitted_by_user_id=student.user_id, title='Cold food served', description='Chicken was cold.', status='under_review')
    db.session.add_all([c1, c2])
    db.session.commit()

    n1 = Notification(user_id=student.user_id, complaint_id=c1.complaint_id, message='Your complaint "Water contamination issue" is now Action Required. Admin note: Vendor must replace water filter today.', is_read=False)
    n2 = Notification(user_id=student.user_id, complaint_id=c2.complaint_id, message='Your complaint "Cold food served" is now Under Review.', is_read=False)
    db.session.add_all([n1, n2])
    db.session.commit()

if __name__ == '__main__':
    server = ServerThread(app, port=5007)
    server.start()
    time.sleep(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})

            # 1. Log in
            page.goto('http://127.0.0.1:5007/login')
            page.fill('input[name="email"]', 'student221-15-123@diu.edu.bd')
            page.fill('input[name="password"]', 'StudentPass123!')
            page.click('button[type="submit"]')
            page.wait_for_load_state('networkidle')

            # 2. Go to notifications
            page.goto('http://127.0.0.1:5007/customer/notifications')
            page.wait_for_load_state('networkidle')

            print('Page Title:', page.title())
            cards_count = page.locator('.notif-card').count()
            print('Rendered notification cards count:', cards_count)
            assert cards_count == 2, f'Expected 2 cards, got {cards_count}'

            # 3. Test Detail Modal trigger
            page.locator('.btn-open-modal').first.click()
            page.wait_for_selector('#notificationDetailModal.show', timeout=4000)
            modal_title = page.locator('#modalComplaintTitle').inner_text()
            print('Detail Modal opened successfully! Title in modal:', modal_title)
            assert 'Water contamination issue' in modal_title

            # 4. Close Detail Modal
            page.locator('#notificationDetailModal .btn-close').click()
            time.sleep(0.5)

            # 5. Test Clickable Stat Card -> Category Modal
            print('Testing clickable stat card: Action Required...')
            page.locator('.notif-stat-card[data-stat-category="action_required"]').click()
            page.wait_for_selector('#statCategoryModal.show', timeout=4000)
            cat_title = page.locator('#statCategoryModalTitle').inner_text()
            print('Category Modal Title:', cat_title)
            assert 'Action Required' in cat_title

            # Verify category items inside modal
            cat_item_count = page.locator('#modalCategoryItemsContainer .category-item-card').count()
            print('Category modal item count:', cat_item_count)
            assert cat_item_count >= 1

            # Check direct hyperlinks in category card
            track_link = page.locator('#modalCategoryItemsContainer .category-item-card a[href*="/customer/complaints/"]').first
            assert track_link.count() > 0, "Expected Track 3D Progress hyperlink"
            print('Track hyperlink found:', track_link.get_attribute('href'))

            # Close Category Modal
            page.locator('#statCategoryModal .btn-close').click()
            time.sleep(0.5)

            # 6. Test Unread Stat Card -> Category Modal
            print('Testing clickable stat card: Unread...')
            page.locator('.notif-stat-card[data-stat-category="unread"]').click()
            page.wait_for_selector('#statCategoryModal.show', timeout=4000)
            cat_unread_title = page.locator('#statCategoryModalTitle').inner_text()
            assert 'Unread' in cat_unread_title
            
            # Test inside-modal sorting
            page.select_option('#modalCategorySortSelect', 'oldest')
            time.sleep(0.3)
            page.locator('#statCategoryModal .btn-close').click()
            time.sleep(0.5)

            # 7. Test Main Page Filter Tabs
            page.locator('.notif-tab-btn[data-filter="action_required"]').click()
            visible_cards = page.locator('.notif-card:visible').count()
            print('Filter "Action Required" visible count:', visible_cards)
            assert visible_cards == 1

            # 8. Test Main Page Sort Selector
            page.locator('.notif-tab-btn[data-filter="all"]').click()
            page.select_option('#notifSortSelect', 'stall')
            time.sleep(0.3)
            visible_all = page.locator('.notif-card:visible').count()
            assert visible_all == 2

            # 9. Test search input
            search_input = page.locator('#notifSearchInput')
            search_input.fill('Cold')
            visible_search = page.locator('.notif-card:visible').count()
            print('Search "Cold" visible count:', visible_search)
            assert visible_search == 1

            browser.close()
            print('\nALL PLAYWRIGHT NOTIFICATIONS & CATEGORY MODAL TESTS PASSED WITH 100% SUCCESS!')
    finally:
        server.shutdown()

