from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintType,
    FoodCategory,
    FoodItem,
    Inspection,
    Review,
    Stall,
)
from routes import role_required


customer_bp = Blueprint(
    "customer_portal",
    __name__,
    url_prefix="/customer",
)


def _latest_inspection(stall_id):
    return (
        Inspection.query.filter(
            Inspection.stall_id == stall_id,
            Inspection.status.in_(("submitted", "approved")),
        )
        .order_by(
            Inspection.inspection_date.desc(),
            Inspection.inspection_id.desc(),
        )
        .first()
    )


def _grade(score):
    if score is None:
        return None
    return db.session.execute(
        text("SELECT get_hygiene_grade(:score)"),
        {"score": score},
    ).scalar_one()


@customer_bp.route("/stalls")
@login_required
@role_required("customer", "consumer")
def search_stalls():
    search = request.args.get("q", "").strip()
    area_id = request.args.get("area_id", type=int)
    category_id = request.args.get("category_id", type=int)
    risk_level = request.args.get("risk_level", "").strip()

    ranked = (
        db.session.query(
            Inspection.stall_id,
            Inspection.risk_level,
            Inspection.overall_score,
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
    latest = (
        db.session.query(ranked)
        .filter(ranked.c.row_num == 1)
        .subquery()
    )
    query = (
        db.session.query(
            Stall,
            latest.c.risk_level,
            latest.c.overall_score,
        )
        .outerjoin(latest, latest.c.stall_id == Stall.stall_id)
        .filter(Stall.status == "active")
    )
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Stall.stall_name.ilike(term),
                Stall.address.ilike(term),
                Stall.stall_code.ilike(term),
            )
        )
    if area_id:
        query = query.filter(Stall.area_id == area_id)
    if category_id:
        query = query.filter(
            Stall.food_items.any(FoodItem.category_id == category_id)
        )
    if risk_level in {"low", "medium", "high", "critical"}:
        query = query.filter(latest.c.risk_level == risk_level)

    results = []
    for stall, current_risk, current_score in query.order_by(
        Stall.stall_name
    ).all():
        results.append(
            {
                "stall": stall,
                "risk": current_risk,
                "score": current_score,
                "grade": _grade(current_score),
            }
        )
    return render_template(
        "customer/search.html",
        results=results,
        areas=Area.query.order_by(Area.area_name).all(),
        categories=FoodCategory.query.order_by(
            FoodCategory.category_name
        ).all(),
        filters={
            "q": search,
            "area_id": area_id,
            "category_id": category_id,
            "risk_level": risk_level,
        },
    )


@customer_bp.route("/stalls/<int:stall_id>")
@login_required
@role_required("customer", "consumer")
def stall_detail(stall_id):
    stall = Stall.query.filter_by(
        stall_id=stall_id,
        status="active",
    ).first_or_404()
    latest = _latest_inspection(stall.stall_id)
    existing_review = Review.query.filter_by(
        stall_id=stall.stall_id,
        user_id=current_user.user_id,
    ).first()
    visible_reviews = Review.query.filter_by(
        stall_id=stall.stall_id,
        status="visible",
    ).order_by(Review.created_at.desc()).all()
    average_rating = db.session.query(func.avg(Review.rating)).filter_by(
        stall_id=stall.stall_id,
        status="visible",
    ).scalar()
    return render_template(
        "customer/stall_detail.html",
        stall=stall,
        latest=latest,
        grade=_grade(latest.overall_score) if latest else None,
        existing_review=existing_review,
        visible_reviews=visible_reviews,
        average_rating=(
            round(float(average_rating), 1)
            if average_rating is not None
            else None
        ),
        complaint_types=ComplaintType.query.order_by(
            ComplaintType.type_name
        ).all(),
    )


@customer_bp.route("/stalls/<int:stall_id>/review", methods=["POST"])
@login_required
@role_required("customer", "consumer")
def submit_review(stall_id):
    Stall.query.filter_by(stall_id=stall_id, status="active").first_or_404()
    if Review.query.filter_by(
        stall_id=stall_id,
        user_id=current_user.user_id,
    ).first():
        flash("You have already reviewed this stall.", "warning")
        return redirect(
            url_for("customer_portal.stall_detail", stall_id=stall_id)
        )
    try:
        rating = int(request.form.get("rating", ""))
        if rating not in range(1, 6):
            raise ValueError
        review = Review(
            stall_id=stall_id,
            user_id=current_user.user_id,
            rating=rating,
            review_text=request.form.get("review_text", "").strip()
            or None,
            status="visible",
        )
        db.session.add(review)
        db.session.commit()
        flash("Thank you for your review.", "success")
    except (ValueError, IntegrityError):
        db.session.rollback()
        flash("Your review could not be submitted.", "danger")
    return redirect(
        url_for("customer_portal.stall_detail", stall_id=stall_id)
    )


@customer_bp.route("/stalls/<int:stall_id>/complaint", methods=["POST"])
@login_required
@role_required("customer", "consumer")
def submit_complaint(stall_id):
    Stall.query.filter_by(stall_id=stall_id, status="active").first_or_404()
    complaint_type = db.session.get(
        ComplaintType,
        request.form.get("complaint_type_id", type=int),
    )
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if complaint_type is None or not title or not description:
        flash("Complaint type, title, and description are required.", "danger")
        return redirect(
            url_for("customer_portal.stall_detail", stall_id=stall_id)
        )
    complaint = Complaint(
        stall_id=stall_id,
        complaint_type_id=complaint_type.complaint_type_id,
        submitted_by_user_id=current_user.user_id,
        title=title,
        description=description,
        status="open",
    )
    db.session.add(complaint)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Complaint could not be submitted. Please try again.", "danger")
        return redirect(
            url_for("customer_portal.stall_detail", stall_id=stall_id)
        )
    flash("Complaint submitted. You can track it from your account.", "success")
    return redirect(url_for("customer_portal.my_complaints"))


@customer_bp.route("/complaints")
@login_required
@role_required("customer", "consumer")
def my_complaints():
    records = Complaint.query.filter_by(
        submitted_by_user_id=current_user.user_id
    ).order_by(Complaint.submitted_at.desc()).all()
    return render_template(
        "customer/complaints.html",
        complaints=records,
    )
