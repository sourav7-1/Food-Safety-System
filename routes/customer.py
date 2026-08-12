from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db, limiter
from models import (
    Area,
    Complaint,
    ComplaintEvidence,
    ComplaintType,
    FoodCategory,
    FoodItem,
    Inspection,
    Review,
    Stall,
)
from routes import role_required
from services.evidence import (
    EvidenceValidationError,
    delete_stored_complaint_files,
    record_audit,
    serve_complaint_evidence,
    validate_and_store_complaint_evidence,
)


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
@limiter.limit("10 per hour")
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

    evidence_files = [
        item for item in request.files.getlist("evidence") if item and item.filename
    ]
    max_files = current_app.config.get("EVIDENCE_MAX_FILES_PER_COMPLAINT", 5)
    if len(evidence_files) > max_files:
        flash(
            f"You can attach at most {max_files} evidence files per "
            "complaint.",
            "danger",
        )
        return redirect(
            url_for("customer_portal.stall_detail", stall_id=stall_id)
        )

    complaint = Complaint(
        stall_id=stall_id,
        complaint_type_id=complaint_type.complaint_type_id,
        submitted_by_user_id=current_user.user_id,
        title=title,
        description=description,
        status="submitted",
    )
    db.session.add(complaint)

    # Evidence is optional supporting information, not proof: every file
    # is stored PENDING and only an admin can move it to verified/rejected
    # (see routes/admin.py:evidence_status). This never touches
    # complaint.status.
    saved_relative_paths = []
    try:
        db.session.flush()  # assigns complaint.complaint_id for storage_path
        for uploaded_file in evidence_files:
            metadata = validate_and_store_complaint_evidence(
                uploaded_file, complaint.complaint_id
            )
            saved_relative_paths.append(metadata["storage_path"])
            db.session.add(
                ComplaintEvidence(
                    complaint_id=complaint.complaint_id,
                    uploaded_by=current_user.user_id,
                    verification_status="pending",
                    **metadata,
                )
            )
        db.session.commit()
    except EvidenceValidationError as error:
        db.session.rollback()
        delete_stored_complaint_files(saved_relative_paths)
        flash(str(error), "danger")
        return redirect(
            url_for("customer_portal.stall_detail", stall_id=stall_id)
        )
    except SQLAlchemyError:
        db.session.rollback()
        delete_stored_complaint_files(saved_relative_paths)
        current_app.logger.exception("Complaint submission failed")
        flash("Complaint could not be submitted. Please try again.", "danger")
        return redirect(
            url_for("customer_portal.stall_detail", stall_id=stall_id)
        )

    try:
        for evidence in complaint.evidence:
            record_audit(evidence, current_user, "uploaded")
    except SQLAlchemyError:
        # The complaint and its evidence already committed successfully;
        # a failure logging that fact shouldn't turn into a 500 for the
        # user, so this is swallowed after being logged.
        current_app.logger.exception(
            "Failed to write upload audit log for complaint %s",
            complaint.complaint_id,
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


@customer_bp.route("/complaints/<int:complaint_id>")
@login_required
@role_required("customer", "consumer")
def complaint_detail(complaint_id):
    complaint = Complaint.query.filter_by(
        complaint_id=complaint_id,
        submitted_by_user_id=current_user.user_id,
    ).first_or_404()
    return render_template(
        "customer/complaint_detail.html",
        complaint=complaint,
    )


@customer_bp.route("/evidence/<int:evidence_id>")
@login_required
@role_required("customer", "consumer")
def evidence_download(evidence_id):
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    if evidence.complaint.submitted_by_user_id != current_user.user_id:
        abort(403)
    record_audit(evidence, current_user, "viewed")
    return serve_complaint_evidence(evidence)
