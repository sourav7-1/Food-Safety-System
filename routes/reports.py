from datetime import date, timedelta

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    Inspection,
    Stall,
)
from routes import permission_required


reports_bp = Blueprint("reports", __name__, url_prefix="/admin/reports")


def _latest_inspections():
    ranked = (
        db.session.query(
            Inspection.inspection_id,
            Inspection.stall_id,
            Inspection.inspection_date,
            Inspection.overall_score,
            Inspection.risk_level,
            Inspection.reinspection_date,
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
    return (
        db.session.query(ranked)
        .filter(ranked.c.row_num == 1)
        .subquery()
    )


@reports_bp.route("/")
@login_required
@permission_required("reports.view")
def dashboard():
    today = date.today()
    latest = _latest_inspections()

    trend_start = today - timedelta(days=29)
    trend_rows = (
        db.session.query(
            func.date(Inspection.inspection_date).label("day"),
            func.count(Inspection.inspection_id).label("total"),
        )
        .filter(func.date(Inspection.inspection_date) >= trend_start)
        .group_by(func.date(Inspection.inspection_date))
        .all()
    )
    trend_map = {row.day: row.total for row in trend_rows}
    trend_dates = [
        trend_start + timedelta(days=offset) for offset in range(30)
    ]

    risk_rows = (
        db.session.query(
            latest.c.risk_level,
            func.count(latest.c.inspection_id),
        )
        .filter(latest.c.risk_level.is_not(None))
        .group_by(latest.c.risk_level)
        .all()
    )
    risk_map = {
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
    }
    risk_map.update({str(level): count for level, count in risk_rows})

    area_rows = (
        db.session.query(
            Area.area_name,
            func.round(func.avg(latest.c.overall_score), 2),
        )
        .join(Stall, Stall.area_id == Area.area_id)
        .join(latest, latest.c.stall_id == Stall.stall_id)
        .group_by(Area.area_id, Area.area_name)
        .order_by(Area.area_name)
        .all()
    )

    complaint_rows = (
        db.session.query(
            ComplaintType.type_name,
            func.count(Complaint.complaint_id),
        )
        .outerjoin(
            Complaint,
            Complaint.complaint_type_id
            == ComplaintType.complaint_type_id,
        )
        .group_by(
            ComplaintType.complaint_type_id,
            ComplaintType.type_name,
        )
        .order_by(func.count(Complaint.complaint_id).desc())
        .all()
    )

    top_stalls = (
        db.session.query(
            Stall.stall_id,
            Stall.stall_name,
            Area.area_name,
            latest.c.overall_score,
            latest.c.risk_level,
        )
        .join(latest, latest.c.stall_id == Stall.stall_id)
        .join(Area, Area.area_id == Stall.area_id)
        .filter(latest.c.overall_score.is_not(None))
        .order_by(
            latest.c.overall_score.desc(),
            Stall.stall_name,
        )
        .limit(10)
        .all()
    )

    high_risk_stalls = (
        db.session.query(
            Stall.stall_id,
            Stall.stall_name,
            Area.area_name,
            latest.c.overall_score,
            latest.c.risk_level,
            latest.c.reinspection_date,
        )
        .join(latest, latest.c.stall_id == Stall.stall_id)
        .join(Area, Area.area_id == Stall.area_id)
        .filter(
            latest.c.risk_level.in_(("high", "critical")),
            latest.c.overall_score.is_not(None),
        )
        .order_by(
            latest.c.risk_level.desc(),
            latest.c.overall_score,
        )
        .all()
    )

    reinspection_rows = (
        db.session.query(
            Stall.stall_name,
            Area.area_name,
            latest.c.risk_level,
            latest.c.reinspection_date,
        )
        .join(latest, latest.c.stall_id == Stall.stall_id)
        .join(Area, Area.area_id == Stall.area_id)
        .filter(
            latest.c.reinspection_date.is_not(None),
            latest.c.reinspection_date <= today + timedelta(days=30),
            Stall.status == "active",
        )
        .order_by(latest.c.reinspection_date)
        .all()
    )
    due_counts = {"overdue": 0, "due_7_days": 0, "due_30_days": 0}
    for row in reinspection_rows:
        if row.reinspection_date < today:
            due_counts["overdue"] += 1
        elif row.reinspection_date <= today + timedelta(days=7):
            due_counts["due_7_days"] += 1
        else:
            due_counts["due_30_days"] += 1

    return render_template(
        "admin/reports.html",
        page_title="Reports & Analytics",
        trend_labels=[day.strftime("%d %b") for day in trend_dates],
        trend_values=[trend_map.get(day, 0) for day in trend_dates],
        risk_map=risk_map,
        area_labels=[row[0] for row in area_rows],
        area_values=[float(row[1]) for row in area_rows],
        complaint_labels=[row[0] for row in complaint_rows],
        complaint_values=[row[1] for row in complaint_rows],
        top_stalls=top_stalls,
        top_stall_labels=[row.stall_name for row in top_stalls],
        top_stall_values=[
            float(row.overall_score) for row in top_stalls
        ],
        high_risk_stalls=high_risk_stalls,
        high_risk_labels=[row.stall_name for row in high_risk_stalls],
        high_risk_values=[
            float(row.overall_score) for row in high_risk_stalls
        ],
        high_risk_colors=[
            "#ef4444" if row.risk_level == "critical" else "#f97316"
            for row in high_risk_stalls
        ],
        reinspection_rows=reinspection_rows,
        due_counts=due_counts,
        generated_at=today,
    )
