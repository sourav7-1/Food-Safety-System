import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from extensions import db
from models import (
    Complaint,
    CorrectiveAction,
    FoodCategory,
    FoodItem,
    Inspection,
    Stall,
    Vendor,
)
from routes import role_required


vendor_bp = Blueprint("vendor_portal", __name__, url_prefix="/vendor")
ALLOWED_EVIDENCE_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}


def _vendor():
    profile = Vendor.query.filter_by(user_id=current_user.user_id).first()
    if profile is None:
        abort(403)
    return profile


def _owned_stall(vendor, stall_id):
    return Stall.query.filter_by(
        stall_id=stall_id,
        vendor_id=vendor.vendor_id,
    ).first_or_404()


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


def _stall_snapshot(stall):
    latest = _latest_inspection(stall.stall_id)
    return {
        "stall": stall,
        "inspection": latest,
        "grade": _grade(latest.overall_score) if latest else None,
    }


@vendor_bp.route("/")
@login_required
@role_required("vendor")
def dashboard():
    vendor = _vendor()
    snapshots = [_stall_snapshot(stall) for stall in vendor.stalls]
    pending_actions = CorrectiveAction.query.filter(
        CorrectiveAction.assigned_to_vendor_id == vendor.vendor_id,
        CorrectiveAction.status.in_(("pending", "in_progress", "overdue")),
    ).count()
    open_complaints = (
        Complaint.query.join(Stall)
        .filter(
            Stall.vendor_id == vendor.vendor_id,
            Complaint.status.in_(("open", "under_review")),
        )
        .count()
    )
    return render_template(
        "vendor/dashboard.html",
        vendor=vendor,
        snapshots=snapshots,
        pending_actions=pending_actions,
        open_complaints=open_complaints,
    )


@vendor_bp.route("/stalls/<int:stall_id>")
@login_required
@role_required("vendor")
def stall_profile(stall_id):
    vendor = _vendor()
    stall = _owned_stall(vendor, stall_id)
    latest = _latest_inspection(stall.stall_id)
    history = (
        Inspection.query.filter_by(stall_id=stall.stall_id)
        .order_by(Inspection.inspection_date.desc())
        .all()
    )
    risk_reasons = []
    if latest:
        for item in latest.scores:
            ratio = float(item.score / item.criterion.max_score)
            if ratio < 0.70 or item.comments:
                risk_reasons.append(
                    {
                        "criterion": item.criterion.criteria_name,
                        "score": item.score,
                        "maximum": item.criterion.max_score,
                        "comments": item.comments,
                    }
                )
        if latest.remarks:
            risk_reasons.append(
                {
                    "criterion": "Inspector remarks",
                    "score": None,
                    "maximum": None,
                    "comments": latest.remarks,
                }
            )
    for complaint in stall.complaints:
        if (
            complaint.status in {"open", "under_review"}
            and complaint.complaint_type.severity_level
            in {"high", "critical"}
        ):
            risk_reasons.append(
                {
                    "criterion": (
                        f"{complaint.complaint_type.severity_level.title()} "
                        "unresolved complaint"
                    ),
                    "score": None,
                    "maximum": None,
                    "comments": complaint.title,
                }
            )
    actions = (
        CorrectiveAction.query.filter_by(
            assigned_to_vendor_id=vendor.vendor_id
        )
        .filter(
            (CorrectiveAction.inspection_id.in_(
                [record.inspection_id for record in history]
            ))
            | (CorrectiveAction.complaint_id.in_(
                [
                    complaint.complaint_id
                    for complaint in stall.complaints
                ]
            ))
        )
        .order_by(CorrectiveAction.due_date)
        .all()
        if history or stall.complaints
        else []
    )
    return render_template(
        "vendor/stall_profile.html",
        vendor=vendor,
        stall=stall,
        latest=latest,
        grade=_grade(latest.overall_score) if latest else None,
        risk_reasons=risk_reasons,
        history=history,
        actions=actions,
    )


@vendor_bp.route("/stalls/<int:stall_id>/food-items")
@login_required
@role_required("vendor")
def food_items(stall_id):
    vendor = _vendor()
    stall = _owned_stall(vendor, stall_id)
    return render_template(
        "vendor/food_items.html",
        vendor=vendor,
        stall=stall,
        categories=FoodCategory.query.order_by(
            FoodCategory.category_name
        ).all(),
    )


@vendor_bp.route(
    "/stalls/<int:stall_id>/food-items/new", methods=["POST"]
)
@login_required
@role_required("vendor")
def food_item_create(stall_id):
    vendor = _vendor()
    stall = _owned_stall(vendor, stall_id)
    try:
        raw_price = request.form.get("price", "").strip()
        price = Decimal(raw_price) if raw_price else None
        if price is not None and price < 0:
            raise ValueError("Price cannot be negative.")
        item = FoodItem(
            stall_id=stall.stall_id,
            category_id=int(request.form["category_id"]),
            item_name=request.form.get("item_name", "").strip(),
            price=price,
            is_available=request.form.get("is_available") == "on",
        )
        db.session.add(item)
        db.session.commit()
        flash("Food item added successfully.", "success")
    except (ValueError, InvalidOperation, IntegrityError):
        db.session.rollback()
        flash(
            "Food item could not be added. Check the values and duplicates.",
            "danger",
        )
    return redirect(
        url_for("vendor_portal.food_items", stall_id=stall.stall_id)
    )


@vendor_bp.route(
    "/stalls/<int:stall_id>/food-items/<int:item_id>/edit",
    methods=["POST"],
)
@login_required
@role_required("vendor")
def food_item_edit(stall_id, item_id):
    vendor = _vendor()
    stall = _owned_stall(vendor, stall_id)
    item = FoodItem.query.filter_by(
        food_item_id=item_id,
        stall_id=stall.stall_id,
    ).first_or_404()
    try:
        raw_price = request.form.get("price", "").strip()
        item.price = Decimal(raw_price) if raw_price else None
        if item.price is not None and item.price < 0:
            raise ValueError
        item.category_id = int(request.form["category_id"])
        item.item_name = request.form.get("item_name", "").strip()
        item.is_available = request.form.get("is_available") == "on"
        db.session.commit()
        flash("Food item updated.", "success")
    except (ValueError, InvalidOperation, IntegrityError):
        db.session.rollback()
        flash("Food item could not be updated.", "danger")
    return redirect(
        url_for("vendor_portal.food_items", stall_id=stall.stall_id)
    )


@vendor_bp.route(
    "/stalls/<int:stall_id>/food-items/<int:item_id>/delete",
    methods=["POST"],
)
@login_required
@role_required("vendor")
def food_item_delete(stall_id, item_id):
    vendor = _vendor()
    stall = _owned_stall(vendor, stall_id)
    item = FoodItem.query.filter_by(
        food_item_id=item_id,
        stall_id=stall.stall_id,
    ).first_or_404()
    db.session.delete(item)
    try:
        db.session.commit()
        flash("Food item deleted.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Food item could not be deleted.", "danger")
    return redirect(
        url_for("vendor_portal.food_items", stall_id=stall.stall_id)
    )


@vendor_bp.route("/complaints")
@login_required
@role_required("vendor")
def complaints():
    vendor = _vendor()
    records = (
        Complaint.query.join(Stall)
        .filter(Stall.vendor_id == vendor.vendor_id)
        .order_by(Complaint.submitted_at.desc())
        .all()
    )
    return render_template(
        "vendor/complaints.html",
        vendor=vendor,
        complaints=records,
    )


@vendor_bp.route(
    "/corrective-actions/<int:action_id>/submit",
    methods=["POST"],
)
@login_required
@role_required("vendor")
def submit_corrective_action(action_id):
    vendor = _vendor()
    action = CorrectiveAction.query.filter_by(
        action_id=action_id,
        assigned_to_vendor_id=vendor.vendor_id,
    ).first_or_404()
    notes = request.form.get("completion_notes", "").strip()
    evidence = request.files.get("evidence")
    if not notes:
        flash("Completion notes are required.", "danger")
        return redirect(request.referrer or url_for("vendor_portal.dashboard"))
    if not evidence or not evidence.filename:
        flash("Evidence file is required.", "danger")
        return redirect(request.referrer or url_for("vendor_portal.dashboard"))

    original_name = secure_filename(evidence.filename)
    extension = (
        original_name.rsplit(".", 1)[1].lower()
        if "." in original_name
        else ""
    )
    if extension not in ALLOWED_EVIDENCE_EXTENSIONS:
        flash("Evidence must be PNG, JPG, JPEG, or PDF.", "danger")
        return redirect(request.referrer or url_for("vendor_portal.dashboard"))

    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    destination = os.path.join(upload_folder, stored_name)
    try:
        evidence.save(destination)
        action.completion_notes = notes
        action.evidence_path = stored_name
        action.status = "completed"
        action.completed_at = datetime.now()
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.exists(destination):
            os.remove(destination)
        current_app.logger.exception("Corrective evidence submission failed")
        flash("Corrective action submission failed.", "danger")
        return redirect(request.referrer or url_for("vendor_portal.dashboard"))

    flash("Corrective action and evidence submitted.", "success")
    return redirect(request.referrer or url_for("vendor_portal.dashboard"))


@vendor_bp.route("/corrective-actions/<int:action_id>/evidence")
@login_required
@role_required("vendor", "admin")
def corrective_evidence(action_id):
    action = db.get_or_404(CorrectiveAction, action_id)
    if current_user.role_name == "vendor":
        vendor = _vendor()
        if action.assigned_to_vendor_id != vendor.vendor_id:
            abort(403)
    if not action.evidence_path:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        action.evidence_path,
        as_attachment=True,
    )
