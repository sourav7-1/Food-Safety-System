"""Manual live-MySQL smoke check.

Run with:
    python tests/live_mysql_smoke.py

The script creates only QA-prefixed records and removes them in ``finally``.
"""

import sys
from datetime import timedelta
from pathlib import Path

from flask import g
from sqlalchemy import text


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from extensions import db
from models import (
    Inspection,
    InspectionCriterion,
    InspectionScore,
    Inspector,
    Role,
    Stall,
    User,
)


QA_EMAIL = "qa-inspector@localhost.test"


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["_csrf_token"] = "qa-csrf-token"


def _assert_gets(client, paths):
    for path in paths:
        g.pop("_login_user", None)
        response = client.get(path)
        assert response.status_code == 200, (
            f"{path} returned {response.status_code}"
        )
        assert b"ProgrammingError" not in response.data
        assert b"Internal Server Error" not in response.data


def run():
    inspection_id = None
    inspector_id = None
    user_id = None
    with app.app_context():
        try:
            role = Role.query.filter_by(role_name="inspector").one()
            stall = Stall.query.order_by(Stall.stall_id).first()
            criteria = InspectionCriterion.query.filter_by(
                is_active=True
            ).order_by(InspectionCriterion.criteria_id).all()
            assert stall is not None, "At least one imported stall is required."
            assert criteria, "Active inspection criteria are required."

            user = User.query.filter_by(email=QA_EMAIL).first()
            if user is None:
                user = User(
                    role_id=role.role_id,
                    full_name="QA Inspector",
                    email=QA_EMAIL,
                    status="active",
                )
                user.set_password("QaTest-8472!")
                db.session.add(user)
                db.session.flush()
            user_id = user.user_id

            inspector = Inspector.query.filter_by(user_id=user.user_id).first()
            if inspector is None:
                inspector = Inspector(
                    user_id=user.user_id,
                    employee_code="QA-INSPECTOR",
                    designation="Automated QA",
                    assigned_area_id=stall.area_id,
                )
                db.session.add(inspector)
                db.session.commit()
            inspector_id = inspector.inspector_id

            client = app.test_client()
            _login(client, user.user_id)
            response = client.get("/inspector/inspections/new")
            assert response.status_code == 200, response.status_code

            form = {
                "_csrf_token": "qa-csrf-token",
                "stall_id": str(stall.stall_id),
                "inspection_date": "2026-07-30T12:00",
                "remarks": "Temporary automated database workflow check.",
            }
            for criterion in criteria:
                form[f"score_{criterion.criteria_id}"] = str(
                    criterion.max_score
                )
                form[f"comments_{criterion.criteria_id}"] = ""

            response = client.post(
                "/inspector/inspections/new",
                data=form,
                follow_redirects=False,
            )
            assert response.status_code == 302, response.status_code

            inspection = Inspection.query.filter_by(
                inspector_id=inspector.inspector_id,
                remarks="Temporary automated database workflow check.",
            ).order_by(Inspection.inspection_id.desc()).first()
            assert inspection is not None
            inspection_id = inspection.inspection_id
            assert float(inspection.overall_score) == 100.0
            assert inspection.risk_level == "low"
            assert inspection.reinspection_date == (
                inspection.inspection_date.date() + timedelta(days=180)
            )
            assert len(inspection.scores) == len(criteria)

            grade = db.session.execute(
                text("SELECT get_hygiene_grade(:score)"),
                {"score": inspection.overall_score},
            ).scalar_one()
            assert grade == "A"

            _assert_gets(
                client,
                (
                    "/inspector/inspections/",
                    f"/inspector/inspections/{inspection.inspection_id}",
                ),
            )

            admin = (
                User.query.join(User.role)
                .filter(Role.role_name == "admin", User.status == "active")
                .first()
            )
            if admin is not None:
                admin_client = app.test_client()
                _login(admin_client, admin.user_id)
                _assert_gets(
                    admin_client,
                    (
                        "/dashboard/admin",
                        "/admin/vendors",
                        "/admin/stalls",
                        "/admin/inspectors",
                        "/admin/inspections",
                        "/admin/complaints",
                        "/admin/reviews",
                        "/admin/risk-engine",
                        "/admin/reports/",
                        "/admin/users",
                        "/admin/settings",
                    ),
                )

            customer = (
                User.query.join(User.role)
                .filter(Role.role_name == "customer", User.status == "active")
                .first()
            )
            if customer is not None:
                customer_client = app.test_client()
                _login(customer_client, customer.user_id)
                _assert_gets(
                    customer_client,
                    (
                        "/customer/stalls",
                        f"/customer/stalls/{stall.stall_id}",
                        "/customer/complaints",
                    ),
                )

            vendor_user = stall.vendor.user
            original_vendor_status = vendor_user.status
            vendor_user.status = "active"
            db.session.commit()
            try:
                vendor_client = app.test_client()
                _login(vendor_client, vendor_user.user_id)
                _assert_gets(
                    vendor_client,
                    (
                        "/vendor/",
                        f"/vendor/stalls/{stall.stall_id}",
                        f"/vendor/stalls/{stall.stall_id}/food-items",
                        "/vendor/complaints",
                    ),
                )
            finally:
                vendor_user.status = original_vendor_status
                db.session.commit()

            print(
                "MYSQL_WORKFLOW_AND_ROUTES_OK",
                inspection.overall_score,
                grade,
                inspection.risk_level,
                inspection.reinspection_date,
            )
        finally:
            db.session.rollback()
            if inspection_id is not None:
                InspectionScore.query.filter_by(
                    inspection_id=inspection_id
                ).delete(synchronize_session=False)
                db.session.flush()
                Inspection.query.filter_by(
                    inspection_id=inspection_id
                ).delete(synchronize_session=False)
            if inspector_id is not None:
                Inspector.query.filter_by(
                    inspector_id=inspector_id
                ).delete(synchronize_session=False)
            if user_id is not None:
                User.query.filter_by(user_id=user_id).delete(
                    synchronize_session=False
                )
            db.session.commit()


if __name__ == "__main__":
    run()
