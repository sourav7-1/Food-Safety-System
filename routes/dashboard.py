from datetime import date, timedelta

from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required
from sqlalchemy import func

from extensions import db
from models import Complaint, Inspection, Stall, Vendor
from routes import role_required


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _render_dashboard(role, title, description):
    return render_template(
        "dashboard.html",
        dashboard_role=role,
        dashboard_title=title,
        dashboard_description=description,
    )


@dashboard_bp.route("/admin")
@login_required
@role_required("admin")
def admin():
    ranked_inspections = (
        db.session.query(
            Inspection.inspection_id,
            Inspection.stall_id,
            Inspection.overall_score,
            Inspection.risk_level,
            func.row_number()
            .over(
                partition_by=Inspection.stall_id,
                order_by=(
                    Inspection.inspection_date.desc(),
                    Inspection.inspection_id.desc(),
                ),
            )
            .label("row_num"),
        )
        .filter(Inspection.status.in_(("submitted", "approved")))
        .subquery()
    )
    latest_inspections = (
        db.session.query(ranked_inspections)
        .filter(ranked_inspections.c.row_num == 1)
        .subquery()
    )

    total_vendors = Vendor.query.count()
    total_stalls = Stall.query.count()
    todays_inspections = Inspection.query.filter(
        func.date(Inspection.inspection_date) == date.today()
    ).count()
    high_risk_stalls = db.session.query(
        func.count(latest_inspections.c.inspection_id)
    ).filter(
        latest_inspections.c.risk_level.in_(("high", "critical"))
    ).scalar() or 0
    pending_complaints = Complaint.query.filter(
        Complaint.status.in_(("open", "under_review"))
    ).count()
    average_hygiene_score = db.session.query(
        func.avg(latest_inspections.c.overall_score)
    ).scalar()

    risk_rows = (
        db.session.query(
            latest_inspections.c.risk_level,
            func.count(latest_inspections.c.inspection_id),
        )
        .filter(latest_inspections.c.risk_level.is_not(None))
        .group_by(latest_inspections.c.risk_level)
        .all()
    )
    risk_counts = {
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
    }
    risk_counts.update({str(level): count for level, count in risk_rows})

    start_date = date.today() - timedelta(days=6)
    trend_rows = (
        db.session.query(
            func.date(Inspection.inspection_date).label("day"),
            func.count(Inspection.inspection_id),
        )
        .filter(func.date(Inspection.inspection_date) >= start_date)
        .group_by(func.date(Inspection.inspection_date))
        .all()
    )
    trend_counts = {day: count for day, count in trend_rows}
    trend_dates = [
        start_date + timedelta(days=offset) for offset in range(7)
    ]

    recent_inspections = (
        Inspection.query.join(Inspection.stall)
        .order_by(Inspection.inspection_date.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        page_title="Dashboard",
        total_vendors=total_vendors,
        total_stalls=total_stalls,
        todays_inspections=todays_inspections,
        high_risk_stalls=high_risk_stalls,
        pending_complaints=pending_complaints,
        average_hygiene_score=(
            round(float(average_hygiene_score), 1)
            if average_hygiene_score is not None
            else 0
        ),
        risk_counts=risk_counts,
        trend_labels=[day.strftime("%a") for day in trend_dates],
        trend_values=[trend_counts.get(day, 0) for day in trend_dates],
        recent_inspections=recent_inspections,
    )


@dashboard_bp.route("/inspector")
@login_required
@role_required("inspector")
def inspector():
    return redirect(url_for("inspection_workflow.inspections"))


@dashboard_bp.route("/vendor")
@login_required
@role_required("vendor")
def vendor():
    return redirect(url_for("vendor_portal.dashboard"))


@dashboard_bp.route("/customer")
@login_required
@role_required("customer", "consumer")
def customer():
    return redirect(url_for("customer_portal.search_stalls"))
