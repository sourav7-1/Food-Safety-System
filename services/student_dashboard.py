from datetime import date, datetime, timedelta
import calendar
from sqlalchemy import case, func, text

from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    FoodCategory,
    FoodItem,
    Inspection,
    Notification,
    Review,
    Role,
    Stall,
    User,
    Vendor,
)


def get_student_dashboard_data(current_user):
    """Aggregates all real-time metrics, stall ratings, complaints, rankings,
    and alert feeds for the Student Portal Dashboard."""
    today = date.today()

    # 1. User Engagement Metrics & Leaderboard Rank Calculation
    user_id = current_user.user_id
    reviews_count = Review.query.filter_by(user_id=user_id).count()
    
    open_complaints_count = Complaint.query.filter(
        Complaint.submitted_by_user_id == user_id,
        Complaint.status.in_(("submitted", "under_review", "investigation", "action_required"))
    ).count()

    resolved_complaints_count = Complaint.query.filter(
        Complaint.submitted_by_user_id == user_id,
        Complaint.status.in_(("resolved", "closed"))
    ).count()

    total_complaints_count = Complaint.query.filter_by(submitted_by_user_id=user_id).count()

    # Points: 15 per review, 10 per complaint submitted
    user_points = (reviews_count * 15) + (total_complaints_count * 10)

    # Leaderboard Calculation across all students
    # Calculate points for every user who has reviews or complaints
    student_role = Role.query.filter(func.lower(Role.role_name) == "student").first()
    student_role_id = student_role.role_id if student_role else None

    # Group reviews and complaints by user
    review_subquery = (
        db.session.query(Review.user_id.label("uid"), func.count(Review.review_id).label("rcnt"))
        .group_by(Review.user_id)
        .subquery()
    )
    complaint_subquery = (
        db.session.query(Complaint.submitted_by_user_id.label("uid"), func.count(Complaint.complaint_id).label("ccnt"))
        .filter(Complaint.submitted_by_user_id.is_not(None))
        .group_by(Complaint.submitted_by_user_id)
        .subquery()
    )

    leaderboard_query = (
        db.session.query(
            User.user_id,
            User.full_name,
            User.profile_photo_url,
            func.coalesce(review_subquery.c.rcnt, 0).label("reviews_cnt"),
            func.coalesce(complaint_subquery.c.ccnt, 0).label("complaints_cnt"),
            (func.coalesce(review_subquery.c.rcnt, 0) * 15 + func.coalesce(complaint_subquery.c.ccnt, 0) * 10).label("total_pts")
        )
        .outerjoin(review_subquery, User.user_id == review_subquery.c.uid)
        .outerjoin(complaint_subquery, User.user_id == complaint_subquery.c.uid)
        .filter(User.status == "active")
    )
    if student_role_id:
        leaderboard_query = leaderboard_query.filter(User.role_id == student_role_id)

    all_students_ranked = (
        leaderboard_query
        .filter((func.coalesce(review_subquery.c.rcnt, 0) + func.coalesce(complaint_subquery.c.ccnt, 0)) > 0)
        .order_by(text("total_pts DESC"), User.user_id.asc())
        .all()
    )

    user_rank = "—"
    top_5_leaderboard = []
    user_in_top_5 = False

    for idx, row in enumerate(all_students_ranked, start=1):
        is_me = (row.user_id == user_id)
        if is_me:
            user_rank = f"#{idx}"
            user_in_top_5 = (idx <= 5)
        
        if idx <= 5:
            top_5_leaderboard.append({
                "rank": idx,
                "user_id": row.user_id,
                "name": row.full_name,
                "avatar": row.profile_photo_url,
                "initial": row.full_name[:1].upper() if row.full_name else "S",
                "points": row.total_pts,
                "reviews": row.reviews_cnt,
                "complaints": row.complaints_cnt,
                "is_current_user": is_me,
            })

    if user_rank == "—" and user_points == 0:
        user_rank = "New Member"

    # 2. Risk Distribution & High Risk Alert Banner
    # Ranked inspections view
    ranked_inspections = (
        db.session.query(
            Inspection.inspection_id,
            Inspection.stall_id,
            Inspection.overall_score,
            Inspection.risk_level,
            func.row_number()
            .over(
                partition_by=Inspection.stall_id,
                order_by=(Inspection.inspection_date.desc(), Inspection.inspection_id.desc()),
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

    # Active stalls with their latest inspection
    stalls_with_inspections = (
        db.session.query(
            Stall.stall_id,
            latest_inspections.c.risk_level,
            latest_inspections.c.overall_score
        )
        .outerjoin(latest_inspections, Stall.stall_id == latest_inspections.c.stall_id)
        .filter(Stall.status == "active")
        .all()
    )

    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0, "unrated": 0}
    for _, r_level, _ in stalls_with_inspections:
        r_str = (r_level or "").lower()
        if r_str in risk_counts:
            risk_counts[r_str] += 1
        else:
            risk_counts["unrated"] += 1

    high_risk_flagged_count = risk_counts["high"] + risk_counts["critical"]

    # 3. Top Safe Stalls (Row 2 Pastel Cards)
    # Ordered by latest inspection overall_score desc
    rated_stalls_query = (
        db.session.query(
            Stall,
            Area.area_name,
            latest_inspections.c.overall_score,
            latest_inspections.c.risk_level,
            Inspection.inspection_date
        )
        .join(Area, Stall.area_id == Area.area_id)
        .join(latest_inspections, Stall.stall_id == latest_inspections.c.stall_id)
        .join(Inspection, latest_inspections.c.inspection_id == Inspection.inspection_id)
        .filter(Stall.status == "active", latest_inspections.c.overall_score.is_not(None))
        .order_by(latest_inspections.c.overall_score.desc(), Stall.stall_name.asc())
        .limit(3)
        .all()
    )

    pastel_themes = [
        {"color": "peach", "bg": "#fdebd3", "border": "#fcd39d", "text": "#9a3412", "accent": "#f59e0b"},
        {"color": "blue", "bg": "#dbeafe", "border": "#bfdbfe", "text": "#1e40af", "accent": "#3b82f6"},
        {"color": "pink", "bg": "#fcdde4", "border": "#fbcfe8", "text": "#9f1239", "accent": "#ec4899"},
    ]

    top_safe_stalls = []
    seen_stall_ids = set()

    for idx, (stall, area_name, score, risk_level, insp_date) in enumerate(rated_stalls_query):
        theme = pastel_themes[idx % len(pastel_themes)]
        seen_stall_ids.add(stall.stall_id)

        # Grade calculation
        score_val = float(score) if score is not None else None
        if score_val is not None:
            if score_val >= 90:
                grade = "A"
            elif score_val >= 80:
                grade = "B"
            elif score_val >= 70:
                grade = "C"
            elif score_val >= 60:
                grade = "D"
            else:
                grade = "F"
        else:
            grade = "—"

        # Days ago calculation
        if insp_date:
            days_ago = (today - insp_date.date()).days if hasattr(insp_date, "date") else (today - insp_date).days
            if days_ago == 0:
                days_ago_text = "Inspected today"
            elif days_ago == 1:
                days_ago_text = "Inspected 1 day ago"
            else:
                days_ago_text = f"Inspected {days_ago} days ago"
        else:
            days_ago_text = "Recently inspected"

        top_safe_stalls.append({
            "stall_id": stall.stall_id,
            "stall_name": stall.stall_name,
            "stall_code": stall.stall_code,
            "area_name": area_name,
            "photo_url": stall.photo_url,
            "score": round(score_val, 1) if score_val is not None else None,
            "progress_percent": min(100, max(0, int(score_val))) if score_val is not None else 0,
            "grade": grade,
            "risk_level": risk_level or "low",
            "days_ago": days_ago_text,
            "is_rated": True,
            "theme": theme,
        })

    # If fewer than 3 rated stalls, fill with recently added active stalls
    if len(top_safe_stalls) < 3:
        needed = 3 - len(top_safe_stalls)
        fallback_stalls = (
            Stall.query.join(Area, Stall.area_id == Area.area_id)
            .filter(Stall.status == "active", ~Stall.stall_id.in_(seen_stall_ids) if seen_stall_ids else True)
            .order_by(Stall.created_at.desc())
            .limit(needed)
            .all()
        )
        for idx, stall in enumerate(fallback_stalls, start=len(top_safe_stalls)):
            theme = pastel_themes[idx % len(pastel_themes)]
            top_safe_stalls.append({
                "stall_id": stall.stall_id,
                "stall_name": stall.stall_name,
                "stall_code": stall.stall_code,
                "area_name": stall.area.area_name if stall.area else "Campus",
                "photo_url": stall.photo_url,
                "score": None,
                "progress_percent": 0,
                "grade": None,
                "risk_level": "unrated",
                "days_ago": "Awaiting audit",
                "is_rated": False,
                "theme": theme,
            })

    # 4. My Complaints Tracker (Latest 3) with 3-Step Stepper
    user_complaints = (
        Complaint.query.filter_by(submitted_by_user_id=user_id)
        .join(Stall, Complaint.stall_id == Stall.stall_id)
        .outerjoin(ComplaintType, Complaint.complaint_type_id == ComplaintType.complaint_type_id)
        .order_by(Complaint.submitted_at.desc())
        .limit(3)
        .all()
    )

    my_complaints_list = []
    for c in user_complaints:
        raw_status = (c.status or "submitted").lower()
        
        # Stepper Step Index:
        # Step 1: Submitted (0 = submitted)
        # Step 2: Under Review (1 = under_review, investigation, action_required)
        # Step 3: Resolved (2 = resolved, closed, rejected)
        if raw_status in ("resolved", "closed"):
            step_index = 3
            step_state = "resolved"
        elif raw_status == "rejected":
            step_index = 3
            step_state = "rejected"
        elif raw_status in ("under_review", "investigation", "action_required"):
            step_index = 2
            step_state = "in_progress"
        else:
            step_index = 1
            step_state = "submitted"

        my_complaints_list.append({
            "complaint_id": c.complaint_id,
            "title": c.title,
            "stall_name": c.stall.stall_name if c.stall else "Campus Stall",
            "category": c.complaint_type.type_name if c.complaint_type else "General Hygiene",
            "date": c.submitted_at.strftime("%d %b %Y, %I:%M %p"),
            "status_label": raw_status.replace("_", " ").title(),
            "step_index": step_index,
            "step_state": step_state,
        })

    # 5. Alerts Feed (Latest 6 Notifications)
    user_notifications = (
        Notification.query.filter_by(user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(6)
        .all()
    )
    alerts_feed = []
    for n in user_notifications:
        alerts_feed.append({
            "id": n.notification_id,
            "message": n.message,
            "is_read": n.is_read,
            "complaint_id": n.complaint_id,
            "date": n.created_at.strftime("%d %b, %I:%M %p"),
            "relative_time": _format_relative_time(n.created_at),
        })

    first_name = current_user.full_name.split()[0] if current_user.full_name else "Student"

    return {
        "first_name": first_name,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "profile_photo_url": current_user.profile_photo_url,
        "today_str": today.strftime("%A, %d %B %Y"),
        "user_points": user_points,
        "user_rank": user_rank,
        "reviews_count": reviews_count,
        "open_complaints_count": open_complaints_count,
        "resolved_complaints_count": resolved_complaints_count,
        "high_risk_flagged_count": high_risk_flagged_count,
        "risk_counts": risk_counts,
        "top_safe_stalls": top_safe_stalls,
        "my_complaints": my_complaints_list,
        "alerts_feed": alerts_feed,
        "top_5_leaderboard": top_5_leaderboard,
    }


def get_student_calendar_data(month_str=None):
    """Fetches and aggregates safety audits across campus for the student
    safety calendar."""
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

    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    inspections = (
        Inspection.query.join(Inspection.stall)
        .filter(
            Inspection.status.in_(("submitted", "approved")),
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

        current_risk = (ins.risk_level or "low").lower()
        if current_risk in ("high", "critical"):
            days_map[d_key]["highest_risk"] = "high"
        elif current_risk == "medium" and days_map[d_key]["highest_risk"] != "high":
            days_map[d_key]["highest_risk"] = "medium"

        score_val = float(ins.overall_score) if ins.overall_score is not None else None
        grade = "—"
        if score_val is not None:
            if score_val >= 90:
                grade = "A"
            elif score_val >= 80:
                grade = "B"
            elif score_val >= 70:
                grade = "C"
            elif score_val >= 60:
                grade = "D"
            else:
                grade = "F"

        days_map[d_key]["count"] += 1
        days_map[d_key]["inspections"].append({
            "stall_name": ins.stall.stall_name if ins.stall else "Campus Stall",
            "stall_code": ins.stall.stall_code if ins.stall else "",
            "score": round(score_val, 1) if score_val is not None else None,
            "grade": grade,
            "risk_level": current_risk,
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


def _format_relative_time(dt):
    if not dt:
        return ""
    now = datetime.now()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    return dt.strftime("%d %b")
