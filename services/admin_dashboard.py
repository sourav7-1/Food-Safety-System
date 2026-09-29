from datetime import date, datetime, timedelta
import calendar
from sqlalchemy import func

from extensions import db
from models import Area, Complaint, ComplaintType, Inspection, Inspector, Stall, User, Vendor


def get_admin_dashboard_data(current_user):
    """Aggregates all live database metrics and card data for the redesigned
    Admin Dashboard workspace."""
    today = date.today()

    # 1. KPI Statistics & Ranked Inspections
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
        func.date(Inspection.inspection_date) == today
    ).count()
    high_risk_stalls = (
        db.session.query(func.count(latest_inspections.c.inspection_id))
        .filter(latest_inspections.c.risk_level.in_(("high", "critical")))
        .scalar()
        or 0
    )
    pending_complaints = Complaint.query.filter(
        Complaint.status.in_(
            ("submitted", "under_review", "investigation", "action_required")
        )
    ).count()
    average_hygiene_score = db.session.query(
        func.avg(latest_inspections.c.overall_score)
    ).scalar()

    # Risk counts distribution
    risk_rows = (
        db.session.query(
            latest_inspections.c.risk_level,
            func.count(latest_inspections.c.inspection_id),
        )
        .filter(latest_inspections.c.risk_level.is_not(None))
        .group_by(latest_inspections.c.risk_level)
        .all()
    )
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    risk_counts.update({str(level): count for level, count in risk_rows})

    # Trend records (7 days)
    start_date = today - timedelta(days=6)
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
    trend_dates = [start_date + timedelta(days=offset) for offset in range(7)]

    # 2. Ongoing & Recent Active Inspections (Pastel Cards)
    # Prefer ongoing/submitted/draft records, fallback to recent inspections
    active_inspections_query = (
        Inspection.query.join(Inspection.stall)
        .outerjoin(Stall.vendor)
        .outerjoin(Inspection.inspector)
        .outerjoin(Inspector.user)
        .order_by(Inspection.inspection_date.desc())
        .limit(6)
        .all()
    )

    ongoing_cards = []
    pastel_themes = [
        {"color": "peach", "bg": "#fdebd3", "border": "#fcd39d", "text": "#9a3412", "accent": "#f59e0b"},
        {"color": "blue", "bg": "#dbeafe", "border": "#bfdbfe", "text": "#1e40af", "accent": "#3b82f6"},
        {"color": "pink", "bg": "#fcdde4", "border": "#fbcfe8", "text": "#9f1239", "accent": "#ec4899"},
    ]

    for idx, ins in enumerate(active_inspections_query[:3]):
        theme = pastel_themes[idx % len(pastel_themes)]
        vendor_name = ins.stall.vendor.business_name if ins.stall and ins.stall.vendor else "Campus Partner"
        inspector_name = ins.inspector.user.full_name if ins.inspector and ins.inspector.user else "Staff Auditor"
        score_val = float(ins.overall_score) if ins.overall_score is not None else 75.0
        
        # Calculate days left / timing
        if ins.reinspection_date:
            days_diff = (ins.reinspection_date - today).days
            if days_diff > 0:
                days_left_text = f"{days_diff} days left"
            elif days_diff == 0:
                days_left_text = "Due Today"
            else:
                days_left_text = f"{abs(days_diff)}d Overdue"
        else:
            days_left_text = "Standard Audit"

        ongoing_cards.append({
            "id": ins.inspection_id,
            "date": ins.inspection_date.strftime("%d %b %Y"),
            "stall_name": ins.stall.stall_name if ins.stall else "Campus Stall",
            "vendor_name": vendor_name,
            "stage": ins.status.replace("_", " ").title() if ins.status else "Draft",
            "risk_level": ins.risk_level or "low",
            "score": round(score_val, 1),
            "progress_percent": min(100, max(10, int(score_val))),
            "inspector_name": inspector_name,
            "inspector_initial": inspector_name[:1].upper() if inspector_name else "I",
            "days_left": days_left_text,
            "theme": theme,
        })

    # 3. User Detailed Information
    assigned_area_name = "DIU Main Campus HQ"
    if getattr(current_user, "preferred_area", None):
        assigned_area_name = current_user.preferred_area.area_name
    elif getattr(current_user, "inspector_profile", None) and current_user.inspector_profile.assigned_area:
        assigned_area_name = current_user.inspector_profile.assigned_area.area_name

    user_info = {
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone or "+880 1700-000000",
        "role_title": "Super Administrator" if getattr(current_user, "is_super_admin", False) else (
            current_user.role.role_name.title() if getattr(current_user, "role", None) else "Administrator"
        ),
        "assigned_area": assigned_area_name,
        "is_online": True,
    }

    # 4. Inbox Card: Latest 6 Complaints / Risk Alerts
    latest_complaints = (
        Complaint.query.join(Complaint.stall)
        .outerjoin(Complaint.complaint_type)
        .order_by(Complaint.submitted_at.desc())
        .limit(6)
        .all()
    )
    inbox_items = []
    for c in latest_complaints:
        is_unresolved = c.status in ("submitted", "under_review", "investigation", "action_required")
        inbox_items.append({
            "id": c.complaint_id,
            "title": c.title,
            "stall_name": c.stall.stall_name if c.stall else "General",
            "category": c.complaint_type.type_name if c.complaint_type else "Hygiene Issue",
            "date": c.submitted_at.strftime("%d %b, %I:%M %p"),
            "status": c.status.replace("_", " ").title(),
            "is_unresolved": is_unresolved,
        })

    recent_inspections = (
        Inspection.query.join(Inspection.stall)
        .order_by(Inspection.inspection_date.desc())
        .limit(5)
        .all()
    )

    return {
        "total_vendors": total_vendors,
        "total_stalls": total_stalls,
        "todays_inspections": todays_inspections,
        "high_risk_stalls": high_risk_stalls,
        "pending_complaints": pending_complaints,
        "average_hygiene_score": (
            round(float(average_hygiene_score), 1)
            if average_hygiene_score is not None
            else 0
        ),
        "risk_counts": risk_counts,
        "trend_labels": [day.strftime("%a") for day in trend_dates],
        "trend_values": [trend_counts.get(day, 0) for day in trend_dates],
        "recent_inspections": recent_inspections,
        "ongoing_cards": ongoing_cards,
        "user_info": user_info,
        "inbox_items": inbox_items,
        "today_str": today.strftime("%A, %d %B %Y"),
        "time_slot": f"{today.strftime('%d %b %Y')} · Shift A (08:00 - 18:00)",
    }


def get_calendar_inspections_data(month_str=None):
    """Fetches and aggregates monthly inspection events grouped by calendar day
    for the interactive dashboard calendar widget."""
    today = date.today()
    if month_str:
        try:
            parsed_dt = datetime.strptime(month_str, "%Y-%m")
            year = parsed_dt.year
            month = parsed_dt.month
        except ValueError:
            year = today.year
            month = today.month
    else:
        year = today.year
        month = today.month

    # Determine start and end of month
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    inspections = (
        Inspection.query.join(Inspection.stall)
        .outerjoin(Inspection.inspector)
        .outerjoin(Inspector.user)
        .filter(
            func.date(Inspection.inspection_date) >= start_date,
            func.date(Inspection.inspection_date) <= end_date,
        )
        .order_by(Inspection.inspection_date.asc())
        .all()
    )

    days_map = {}
    for ins in inspections:
        d_key = ins.inspection_date.strftime("%Y-%m-%d")
        if d_key not in days_map:
            days_map[d_key] = {
                "date": d_key,
                "day": ins.inspection_date.day,
                "highest_risk": "low",
                "count": 0,
                "inspections": [],
            }

        # Calculate risk priority
        current_risk = (ins.risk_level or "low").lower()
        if current_risk in ("high", "critical"):
            days_map[d_key]["highest_risk"] = "high"
        elif current_risk == "medium" and days_map[d_key]["highest_risk"] != "high":
            days_map[d_key]["highest_risk"] = "medium"

        days_map[d_key]["count"] += 1
        inspector_name = ins.inspector.user.full_name if ins.inspector and ins.inspector.user else "Inspector"
        days_map[d_key]["inspections"].append({
            "id": ins.inspection_id,
            "stall_name": ins.stall.stall_name if ins.stall else "Stall",
            "stall_code": ins.stall.stall_code if ins.stall else "",
            "score": round(float(ins.overall_score), 1) if ins.overall_score is not None else None,
            "risk_level": ins.risk_level or "unrated",
            "status": ins.status or "draft",
            "inspector": inspector_name,
            "time": ins.inspection_date.strftime("%I:%M %p"),
        })

    month_name = calendar.month_name[month]
    return {
        "success": True,
        "year": year,
        "month": f"{year:04d}-{month:02d}",
        "month_num": month,
        "month_name": f"{month_name} {year}",
        "today": today.strftime("%Y-%m-%d"),
        "days": days_map,
    }
