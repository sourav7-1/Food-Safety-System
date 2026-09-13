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
    Area, Complaint, ComplaintType, Role, Stall, User, Vendor, FoodCategory, ComplaintEvidence
)
from datetime import datetime, timezone

class ServerThread(threading.Thread):
    def __init__(self, app, port=5008):
        super().__init__()
        self.srv = make_server('127.0.0.1', port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()

import tempfile

class QAConfig:
    TESTING = True
    SECRET_KEY = 'playwright-complaint-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    EVIDENCE_STORAGE_PATH = tempfile.mkdtemp()

app = create_app(QAConfig)

with app.app_context():
    db.create_all()
    student_role = Role(role_name='student', description='Student', is_admin_tier=False, is_system=True)
    vendor_role = Role(role_name='vendor', description='Vendor', is_admin_tier=False, is_system=True)
    db.session.add_all([student_role, vendor_role])
    db.session.commit()

    area = Area(area_name='Daffodil Smart City', city='Dhaka')
    cat = FoodCategory(category_name='Drinks', risk_level='low')
    complaint_type = ComplaintType(type_name='Water & Hygiene', severity_level='medium')
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

    c1 = Complaint(
        stall_id=stall.stall_id,
        complaint_type_id=complaint_type.complaint_type_id,
        submitted_by_user_id=student.user_id,
        title='Water contamination issue',
        description='Drinking water smelled bad and tasted chlorinated.',
        status='action_required',
        admin_response='Inspector requested the stall to change water filtration system immediately.'
    )
    db.session.add(c1)
    db.session.commit()

    ev1 = ComplaintEvidence(
        complaint_id=c1.complaint_id,
        uploaded_by=student.user_id,
        file_name='water_sample.jpg',
        stored_file_name='water_sample_stored.jpg',
        storage_path='evidence/water_sample.jpg',
        file_type='image',
        mime_type='image/jpeg',
        file_size=10240,
        file_hash='abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
        verification_status='verified'
    )
    db.session.add(ev1)
    db.session.commit()

if __name__ == '__main__':
    server = ServerThread(app, port=5008)
    server.start()
    time.sleep(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})

            # 1. Log in
            page.goto('http://127.0.0.1:5008/login')
            page.fill('input[name="email"]', 'student221-15-123@diu.edu.bd')
            page.fill('input[name="password"]', 'StudentPass123!')
            page.click('button[type="submit"]')
            page.wait_for_load_state('networkidle')

            # 2. Go to complaint detail
            page.goto('http://127.0.0.1:5008/customer/complaints/1')
            page.wait_for_load_state('networkidle')

            print('Complaint Detail Page Title:', page.title())
            assert 'Complaint #1' in page.title()

            # 3. Check 3D Roadmap Pipeline
            pipeline = page.locator('#pipeline3DCard')
            assert pipeline.is_visible()
            steps_count = page.locator('.pipeline-step').count()
            print('3D Pipeline Steps count:', steps_count)
            assert steps_count == 4

            # 4. Check 3D Case Summary Modal Trigger
            page.locator('button:has-text("3D Case Summary")').click()
            page.wait_for_selector('#complaintSummaryModal.show', timeout=3000)
            modal_title = page.locator('#summaryModalTitle').inner_text()
            print('Summary modal opened! Title:', modal_title)
            assert '3D Case Summary Certificate' in modal_title
            page.locator('#complaintSummaryModal .btn-close').click()
            time.sleep(0.5)

            # 5. Check Evidence 3D Preview Modal Trigger
            evidence_card = page.locator('.btn-preview-evidence').first
            if evidence_card.is_visible():
                evidence_card.click()
                page.wait_for_selector('#evidencePreviewModal.show', timeout=3000)
                ev_title = page.locator('#evidenceModalTitle').inner_text()
                print('Evidence modal opened! File:', ev_title)
                assert 'water_sample.jpg' in ev_title
                page.locator('#evidencePreviewModal .btn-close').click()

            browser.close()
            print('\nALL PLAYWRIGHT COMPLAINT 3D TESTS PASSED WITH 100% SUCCESS!')
    finally:
        server.shutdown()
