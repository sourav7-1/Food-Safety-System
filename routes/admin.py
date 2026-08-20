from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import aliased

from extensions import db
from models import (
    Area,
    Complaint,
    ComplaintEvidence,
    ComplaintType,
    CorrectiveAction,
    FoodCategory,
    Inspection,
    InspectionCriterion,
    InspectionDispute,
    InspectionDisputeEvidence,
    Inspector,
    Notification,
    Permission,
    Review,
    Role,
    RoleAuditLog,
    RoleRequest,
    Stall,
    User,
    Vendor,
)
from routes import permission_required, super_admin_required
from services.auth_audit import record_auth_event
from services.evidence import record_audit, serve_complaint_evidence, serve_dispute_evidence
from services.registration_import import cache_photo
from services.role_audit import record_role_change
from services.role_requests import (
    RoleRequestError,
    approve_role_request,
    reject_role_request,
)


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

USER_STATUSES = {"active", "inactive", "suspended"}
STALL_STATUSES = {"active", "closed", "suspended"}
COMPLAINT_STATUSES = {
    "submitted",
    "under_review",
    "investigation",
    "action_required",
    "resolved",
    "rejected",
    "closed",
}
COMPLAINT_TRANSITIONS = {
    "submitted": {"submitted", "under_review", "rejected"},
    "under_review": {
        "under_review", "investigation", "action_required", "resolved", "rejected",
    },
    "investigation": {
        "investigation", "action_required", "resolved", "rejected", "under_review",
    },
    "action_required": {
        "action_required", "resolved", "rejected", "under_review",
    },
    "resolved": {"resolved", "closed", "under_review"},
    "rejected": {"rejected", "closed", "under_review"},
    "closed": {"closed", "under_review"},
}
DISPUTE_STATUSES = {"submitted", "under_review", "resolved", "rejected"}
DISPUTE_TRANSITIONS = {
    "submitted": {"submitted", "under_review", "resolved", "rejected"},
    "under_review": {"under_review", "resolved", "rejected"},
    "resolved": {"resolved", "under_review"},
    "rejected": {"rejected", "under_review"},
}
EVIDENCE_VERIFICATION_STATUSES = {"under_review", "verified", "rejected"}
EVIDENCE_ACTION_BY_STATUS = {
    "under_review": "marked_under_review",
    "verified": "verified",
    "rejected": "rejected",
}


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_decimal(value, field_name):
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field_name} must be a valid number.") from error


def _role(role_name):
    return Role.query.filter_by(role_name=role_name).first()


def _commit(success_message, failure_message):
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash(failure_message, "danger")
        return False
    flash(success_message, "success")
    return True


def _reopen_payload(mode, action, form):
    """Built when a create/edit modal submission fails validation, so the
    list page can hand it straight back to the client-side script and
    reopen the same modal pre-filled with what the user already typed --
    instead of the old behavior of silently discarding it on redirect.
    The password field is deliberately never echoed back."""
    values = {
        key: value
        for key, value in form.items()
        if key not in {"_csrf_token", "password"}
    }
    return {"mode": mode, "action": action, "values": values}


def _notify_complaint_update(complaint, status_changed, response_text):
    """Best-effort in-app notification for the customer who submitted this
    complaint. Never fails the request that just successfully updated the
    complaint -- a notification write failure is logged, not surfaced."""
    if not complaint.submitted_by_user_id:
        return  # nothing to notify (no logged-in submitter on record)

    status_label = complaint.status.replace("_", " ").title()
    if status_changed and response_text:
        message = (
            f'Your complaint "{complaint.title}" is now {status_label}. '
            f"Admin note: {response_text[:180]}"
        )
    elif status_changed:
        message = f'Your complaint "{complaint.title}" is now {status_label}.'
    else:
        message = f'New update on your complaint "{complaint.title}": {response_text[:180]}'

    try:
        db.session.add(
            Notification(
                user_id=complaint.submitted_by_user_id,
                complaint_id=complaint.complaint_id,
                message=message[:255],
            )
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to create notification for complaint %s",
            complaint.complaint_id,
        )


def _refresh_stall_risk(stall_id):
    """Re-run calculate_stall_risk against a stall's latest inspection.

    Complaint status changes shift the procedure's complaint-severity
    penalty, so the latest inspection's risk_level/reinspection_date must
    be recalculated whenever a complaint against that stall opens,
    resolves, or is rejected -- otherwise it silently goes stale.
    """
    latest = (
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
    if latest is None:
        return
    db.session.execute(
        text(
            """
            CALL calculate_stall_risk(
              :stall_id,
              @calculated_risk_level,
              @calculated_risk_score,
              @calculated_reinspection_date
            )
            """
        ),
        {"stall_id": stall_id},
    )
    result = db.session.execute(
        text(
            """
            SELECT
              @calculated_risk_level AS risk_level,
              @calculated_reinspection_date AS reinspection_date
            """
        )
    ).mappings().one()
    if result["risk_level"] is not None:
        latest.risk_level = result["risk_level"]
        latest.reinspection_date = result["reinspection_date"]
        db.session.commit()


def _render_vendors_list(search="", reopen_modal=None, status_code=200):
    query = Vendor.query.join(Vendor.user)
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Vendor.business_name.ilike(term),
                Vendor.license_number.ilike(term),
                User.full_name.ilike(term),
                User.email.ilike(term),
            )
        )
    records = query.order_by(Vendor.created_at.desc()).all()
    return (
        render_template(
            "admin/vendors/list.html",
            page_title="Vendors",
            vendors=records,
            search=search,
            reopen_modal=reopen_modal,
        ),
        status_code,
    )


@admin_bp.route("/api/dashboard-details/<category>")
@login_required
def api_dashboard_details(category):
    category = category.lower().strip()
    if category in ("total_vendors", "vendors"):
        records = Vendor.query.join(Vendor.user).order_by(Vendor.created_at.desc()).limit(30).all()
        return jsonify({
            "title": "Registered Vendors",
            "category_badge": "VENDORS",
            "badge_class": "bg-primary-subtle text-primary",
            "type": "vendors",
            "items": [
                {
                    "id": v.vendor_id,
                    "entity_type": "vendor",
                    "name": v.user.full_name,
                    "email": v.user.email,
                    "business": v.business_name or "—",
                    "license": v.license_number,
                    "status": v.status,
                    "account_status": v.user.status,
                }
                for v in records
            ]
        })
    elif category in ("total_stalls", "stalls"):
        records = Stall.query.join(Stall.area).order_by(Stall.created_at.desc()).limit(30).all()
        return jsonify({
            "title": "Tracked Food Stalls",
            "category_badge": "ALL STALLS",
            "badge_class": "bg-info-subtle text-info",
            "type": "stalls",
            "items": [
                {
                    "id": s.stall_id,
                    "entity_type": "stall",
                    "stall_name": s.stall_name,
                    "code": s.stall_code,
                    "area": s.area.area_name if s.area else "—",
                    "status": s.status,
                    "score": float(s.overall_score) if s.overall_score is not None else None,
                    "risk": s.risk_level or "unrated",
                }
                for s in records
            ]
        })
    elif category in ("todays_inspections", "inspections"):
        records = Inspection.query.join(Inspection.stall).order_by(Inspection.inspection_date.desc()).limit(30).all()
        return jsonify({
            "title": "Recent Inspections",
            "category_badge": "INSPECTIONS",
            "badge_class": "bg-success-subtle text-success",
            "type": "inspections",
            "items": [
                {
                    "id": i.inspection_id,
                    "entity_type": "inspection",
                    "stall_name": i.stall.stall_name,
                    "date": i.inspection_date.strftime('%d %b %Y, %I:%M %p') if i.inspection_date else "—",
                    "score": float(i.overall_score) if i.overall_score is not None else None,
                    "risk": i.risk_level or "unknown",
                    "status": i.status,
                }
                for i in records
            ]
        })
    elif category in ("high_risk_stalls", "high", "critical", "risk_high", "risk_critical"):
        records = Stall.query.join(Stall.area).filter(or_(Stall.risk_level == "high", Stall.risk_level == "critical")).order_by(Stall.created_at.desc()).limit(30).all()
        return jsonify({
            "title": "High & Critical Risk Stalls",
            "category_badge": "HIGH RISK",
            "badge_class": "bg-danger-subtle text-danger",
            "type": "stalls",
            "items": [
                {
                    "id": s.stall_id,
                    "entity_type": "stall",
                    "stall_name": s.stall_name,
                    "code": s.stall_code,
                    "area": s.area.area_name if s.area else "—",
                    "status": s.status,
                    "score": float(s.overall_score) if s.overall_score is not None else None,
                    "risk": s.risk_level or "high",
                }
                for s in records
            ]
        })
    elif category in ("risk_low", "low"):
        records = Stall.query.join(Stall.area).filter(Stall.risk_level == "low").order_by(Stall.created_at.desc()).limit(30).all()
        return jsonify({
            "title": "Low Risk (Safest) Stalls",
            "category_badge": "LOW RISK",
            "badge_class": "bg-success-subtle text-success",
            "type": "stalls",
            "items": [
                {
                    "id": s.stall_id,
                    "entity_type": "stall",
                    "stall_name": s.stall_name,
                    "code": s.stall_code,
                    "area": s.area.area_name if s.area else "—",
                    "status": s.status,
                    "score": float(s.overall_score) if s.overall_score is not None else None,
                    "risk": s.risk_level or "low",
                }
                for s in records
            ]
        })
    elif category in ("risk_medium", "medium"):
        records = Stall.query.join(Stall.area).filter(Stall.risk_level == "medium").order_by(Stall.created_at.desc()).limit(30).all()
        return jsonify({
            "title": "Medium Risk Stalls",
            "category_badge": "MEDIUM RISK",
            "badge_class": "bg-warning-subtle text-warning",
            "type": "stalls",
            "items": [
                {
                    "id": s.stall_id,
                    "entity_type": "stall",
                    "stall_name": s.stall_name,
                    "code": s.stall_code,
                    "area": s.area.area_name if s.area else "—",
                    "status": s.status,
                    "score": float(s.overall_score) if s.overall_score is not None else None,
                    "risk": s.risk_level or "medium",
                }
                for s in records
            ]
        })
    elif category in ("pending_complaints", "complaints"):
        records = Complaint.query.join(Complaint.stall).filter(Complaint.status.in_(["submitted", "under_review", "investigation", "action_required"])).order_by(Complaint.submitted_at.desc()).limit(30).all()
        return jsonify({
            "title": "Pending Complaints",
            "category_badge": "COMPLAINTS",
            "badge_class": "bg-warning-subtle text-warning",
            "type": "complaints",
            "items": [
                {
                    "id": c.complaint_id,
                    "entity_type": "complaint",
                    "title": c.title,
                    "stall_name": c.stall.stall_name,
                    "status": c.status,
                    "date": c.submitted_at.strftime('%d %b %Y') if c.submitted_at else "—",
                }
                for c in records
            ]
        })
    elif category == "average_hygiene_score":
        records = Stall.query.join(Stall.area).filter(Stall.overall_score.isnot(None)).order_by(Stall.overall_score.desc()).limit(30).all()
        return jsonify({
            "title": "Stall Hygiene Scores",
            "category_badge": "HYGIENE SCORES",
            "badge_class": "bg-info-subtle text-info",
            "type": "stalls",
            "items": [
                {
                    "id": s.stall_id,
                    "entity_type": "stall",
                    "stall_name": s.stall_name,
                    "code": s.stall_code,
                    "area": s.area.area_name if s.area else "—",
                    "status": s.status,
                    "score": float(s.overall_score) if s.overall_score is not None else None,
                    "risk": s.risk_level or "unrated",
                }
                for s in records
            ]
        })
    else:
        return jsonify({"title": "Details", "category_badge": "INFO", "badge_class": "bg-secondary-subtle text-secondary", "type": "empty", "items": []})


@admin_bp.route("/api/entity-detail/<entity_type>/<int:entity_id>")
@login_required
def api_entity_detail(entity_type, entity_id):
    entity_type = entity_type.lower().strip()
    if entity_type == "vendor":
        vendor = db.get_or_404(Vendor, entity_id)
        stalls_count = Stall.query.filter_by(vendor_id=vendor.vendor_id).count()
        return jsonify({
            "type": "vendor",
            "title": vendor.business_name or vendor.user.full_name,
            "name": vendor.user.full_name,
            "email": vendor.user.email,
            "phone": vendor.user.phone or "Not provided",
            "business": vendor.business_name or "—",
            "license": vendor.license_number,
            "license_expiry": vendor.license_expiry_date.strftime('%d %b %Y') if vendor.license_expiry_date else "—",
            "status": vendor.status.title(),
            "account_status": vendor.user.status.title(),
            "national_id": vendor.national_id or "—",
            "stalls_count": stalls_count,
            "created_at": vendor.created_at.strftime('%d %b %Y') if vendor.created_at else "—"
        })
    elif entity_type == "stall":
        stall = db.get_or_404(Stall, entity_id)
        inspections_count = Inspection.query.filter_by(stall_id=stall.stall_id).count()
        complaints_count = Complaint.query.filter_by(stall_id=stall.stall_id).count()
        latest_insp = Inspection.query.filter_by(stall_id=stall.stall_id).order_by(Inspection.inspection_date.desc()).first()
        risk_level = (latest_insp.risk_level if (latest_insp and latest_insp.risk_level) else "Unrated").title()
        score = float(latest_insp.overall_score) if (latest_insp and latest_insp.overall_score is not None) else None
        return jsonify({
            "type": "stall",
            "title": stall.stall_name,
            "code": stall.stall_code,
            "area": stall.area.area_name if stall.area else "—",
            "address": stall.address or "Campus Area",
            "status": stall.status.title(),
            "risk": risk_level,
            "score": score,
            "vendor_name": stall.vendor.user.full_name if stall.vendor and stall.vendor.user else "—",
            "vendor_business": stall.vendor.business_name if stall.vendor else "—",
            "inspections_count": inspections_count,
            "complaints_count": complaints_count,
            "photo_url": stall.photo_url or None
        })
    elif entity_type == "inspection":
        inspection = db.get_or_404(Inspection, entity_id)
        return jsonify({
            "type": "inspection",
            "title": f"Inspection #{inspection.inspection_id}",
            "stall_name": inspection.stall.stall_name if inspection.stall else "—",
            "inspector_name": inspection.inspector.user.full_name if inspection.inspector and inspection.inspector.user else "Inspector",
            "date": inspection.inspection_date.strftime('%d %b %Y, %I:%M %p') if inspection.inspection_date else "—",
            "score": float(inspection.overall_score) if inspection.overall_score is not None else None,
            "risk": (inspection.risk_level or "Unknown").title(),
            "status": inspection.status.title(),
            "notes": inspection.notes or "No additional notes provided for this inspection."
        })
    elif entity_type == "complaint":
        complaint = db.get_or_404(Complaint, entity_id)
        return jsonify({
            "type": "complaint",
            "title": complaint.title,
            "stall_name": complaint.stall.stall_name if complaint.stall else "—",
            "status": complaint.status.replace("_", " ").title(),
            "date": complaint.submitted_at.strftime('%d %b %Y') if complaint.submitted_at else "—",
            "description": complaint.description or "No detailed description.",
            "response": complaint.admin_response or "No admin response recorded yet."
        })
    else:
        return jsonify({"error": "Unknown entity type"}), 400


@admin_bp.route("/vendors")
@login_required
@permission_required("vendors.view")
def vendors():
    return _render_vendors_list(request.args.get("q", "").strip())


@admin_bp.route("/vendors", methods=["POST"])
@login_required
@permission_required("vendors.create")
def vendor_create():
    reopen = _reopen_payload("create", url_for("admin.vendor_create"), request.form)

    vendor_role = _role("vendor")
    if vendor_role is None:
        flash("The vendor role is missing from the roles table.", "danger")
        return _render_vendors_list(reopen_modal=reopen, status_code=409)

    password = request.form.get("password", "")
    if len(password) < 8:
        flash("Password must contain at least 8 characters.", "danger")
        return _render_vendors_list(reopen_modal=reopen, status_code=400)

    status = request.form.get("status", "active").strip() or "active"
    if status not in USER_STATUSES:
        flash("Select a valid account status.", "danger")
        return _render_vendors_list(reopen_modal=reopen, status_code=400)

    try:
        user = User(
            role_id=vendor_role.role_id,
            full_name=request.form.get("full_name", "").strip(),
            email=request.form.get("email", "").strip().lower(),
            phone=request.form.get("phone", "").strip() or None,
            status=status,
        )
        user.set_password(password)
        vendor = Vendor(
            user=user,
            business_name=request.form.get("business_name", "").strip(),
            license_number=request.form.get("license_number", "").strip(),
            license_expiry_date=_parse_date(
                request.form.get("license_expiry_date")
            ),
            national_id=request.form.get("national_id", "").strip() or None,
            # An admin creating a vendor directly here has already vetted
            # it -- unlike the self-service application flow
            # (routes/customer.py:vendor_application), which always
            # starts 'pending'.
            status="approved",
            reviewed_by_user_id=current_user.user_id,
            reviewed_at=datetime.now(),
        )
        db.session.add(vendor)
    except ValueError as error:
        flash(str(error), "danger")
        return _render_vendors_list(reopen_modal=reopen, status_code=400)

    if not _commit(
        "Vendor created successfully.",
        "Could not create vendor. Email, phone, licence, or national ID may already exist.",
    ):
        return _render_vendors_list(reopen_modal=reopen, status_code=409)
    return redirect(url_for("admin.vendors"))


@admin_bp.route("/vendors/<int:vendor_id>/edit", methods=["POST"])
@login_required
@permission_required("vendors.edit")
def vendor_edit(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    reopen = _reopen_payload(
        "edit", url_for("admin.vendor_edit", vendor_id=vendor_id), request.form
    )

    vendor.user.full_name = request.form.get("full_name", "").strip()
    vendor.user.email = request.form.get("email", "").strip().lower()
    vendor.user.phone = request.form.get("phone", "").strip() or None
    status = request.form.get("status", "active").strip() or "active"
    if status not in USER_STATUSES:
        db.session.rollback()
        flash("Select a valid account status.", "danger")
        return _render_vendors_list(reopen_modal=reopen, status_code=400)
    vendor.user.status = status
    password = request.form.get("password", "")
    if password:
        if len(password) < 8:
            db.session.rollback()
            flash("Password must contain at least 8 characters.", "danger")
            return _render_vendors_list(reopen_modal=reopen, status_code=400)
        vendor.user.set_password(password)
    vendor.business_name = request.form.get("business_name", "").strip()
    vendor.license_number = request.form.get("license_number", "").strip()
    try:
        vendor.license_expiry_date = _parse_date(
            request.form.get("license_expiry_date")
        )
    except ValueError:
        db.session.rollback()
        flash("Enter a valid licence expiry date.", "danger")
        return _render_vendors_list(reopen_modal=reopen, status_code=400)
    vendor.national_id = request.form.get("national_id", "").strip() or None

    if not _commit(
        "Vendor updated successfully.",
        "Could not update vendor. A unique field may already be in use.",
    ):
        return _render_vendors_list(reopen_modal=reopen, status_code=409)
    return redirect(url_for("admin.vendors"))


@admin_bp.route("/vendors/<int:vendor_id>/approve", methods=["POST"])
@login_required
@permission_required("vendors.edit")
def vendor_approve(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    if vendor.status == "approved":
        flash("This application has already been approved.", "warning")
        return redirect(url_for("admin.vendors"))

    vendor_role = _role("vendor")
    if vendor_role is None:
        flash("The vendor role is missing from the roles table.", "danger")
        return redirect(url_for("admin.vendors"))

    user = vendor.user
    old_role_id = user.role_id
    # This is the one and only place a user's role_id ever becomes the
    # vendor role -- self-service application (routes/customer.py:
    # vendor_application) only ever creates a 'pending' Vendor row and
    # never touches role_id.
    user.role_id = vendor_role.role_id
    record_role_change(
        current_user, user, old_role_id, vendor_role.role_id,
        f"Vendor application #{vendor.vendor_id} approved",
    )

    vendor.status = "approved"
    vendor.reviewed_by_user_id = current_user.user_id
    vendor.reviewed_at = datetime.now()
    vendor.rejection_reason = None

    _commit(
        "Vendor application approved. The applicant now has vendor access.",
        "Could not approve this application.",
    )
    return redirect(url_for("admin.vendors"))


@admin_bp.route("/vendors/<int:vendor_id>/reject", methods=["POST"])
@login_required
@permission_required("vendors.edit")
def vendor_reject(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    if vendor.status == "approved":
        flash(
            "This vendor is already approved; suspend or edit the "
            "account instead of rejecting it.",
            "danger",
        )
        return redirect(url_for("admin.vendors"))

    reason = request.form.get("rejection_reason", "").strip() or None
    vendor.status = "rejected"
    vendor.rejection_reason = reason
    vendor.reviewed_by_user_id = current_user.user_id
    vendor.reviewed_at = datetime.now()
    # role_id is never touched -- the applicant was never anything but
    # their existing role (customer/student) and stays that way.

    _commit(
        "Vendor application rejected.",
        "Could not reject this application.",
    )
    return redirect(url_for("admin.vendors"))


@admin_bp.route("/vendors/<int:vendor_id>/delete", methods=["POST"])
@login_required
@permission_required("vendors.delete")
def vendor_delete(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    user = vendor.user
    db.session.delete(vendor)
    db.session.delete(user)
    if not _commit(
        "Vendor deleted successfully.",
        "Vendor cannot be deleted while related stalls or records exist.",
    ):
        return redirect(url_for("admin.vendors"))
    return redirect(url_for("admin.vendors"))


def _render_stalls_list(search="", reopen_modal=None, status_code=200):
    query = Stall.query.join(Stall.vendor).join(Stall.area)
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Stall.stall_name.ilike(term),
                Stall.stall_code.ilike(term),
                Vendor.business_name.ilike(term),
                Area.area_name.ilike(term),
            )
        )
    records = query.order_by(Stall.created_at.desc()).all()
    return (
        render_template(
            "admin/stalls/list.html",
            page_title="Stalls",
            stalls=records,
            vendors=Vendor.query.order_by(Vendor.business_name).all(),
            areas=Area.query.order_by(Area.area_name).all(),
            search=search,
            reopen_modal=reopen_modal,
        ),
        status_code,
    )


@admin_bp.route("/stalls")
@login_required
@permission_required("stalls.view")
def stalls():
    return _render_stalls_list(request.args.get("q", "").strip())


@admin_bp.route("/stalls", methods=["POST"])
@login_required
@permission_required("stalls.create")
def stall_create():
    reopen = _reopen_payload("create", url_for("admin.stall_create"), request.form)
    try:
        status = request.form.get("status", "active").strip() or "active"
        if status not in STALL_STATUSES:
            raise ValueError("Select a valid stall status.")
        stall_code = request.form.get("stall_code", "").strip()
        stall = Stall(
            vendor_id=int(request.form["vendor_id"]),
            area_id=int(request.form["area_id"]),
            stall_name=request.form.get("stall_name", "").strip(),
            stall_code=stall_code,
            address=request.form.get("address", "").strip(),
            photo_url=cache_photo(
                request.form.get("photo_url", ""), stall_code
            ),
            latitude=_parse_decimal(request.form.get("latitude"), "Latitude"),
            longitude=_parse_decimal(
                request.form.get("longitude"), "Longitude"
            ),
            status=status,
        )
        db.session.add(stall)
    except (KeyError, ValueError) as error:
        flash(str(error), "danger")
        return _render_stalls_list(reopen_modal=reopen, status_code=400)

    if not _commit(
        "Stall created successfully.",
        "Could not create stall. The stall code may already exist.",
    ):
        return _render_stalls_list(reopen_modal=reopen, status_code=409)
    return redirect(url_for("admin.stalls"))


@admin_bp.route("/stalls/<int:stall_id>/edit", methods=["POST"])
@login_required
@permission_required("stalls.edit")
def stall_edit(stall_id):
    stall = db.get_or_404(Stall, stall_id)
    reopen = _reopen_payload(
        "edit", url_for("admin.stall_edit", stall_id=stall_id), request.form
    )
    try:
        stall.vendor_id = int(request.form["vendor_id"])
        stall.area_id = int(request.form["area_id"])
        stall.stall_name = request.form.get("stall_name", "").strip()
        stall.stall_code = request.form.get("stall_code", "").strip()
        stall.address = request.form.get("address", "").strip()
        stall.photo_url = cache_photo(
            request.form.get("photo_url", ""), stall.stall_code
        )
        stall.latitude = _parse_decimal(
            request.form.get("latitude"), "Latitude"
        )
        stall.longitude = _parse_decimal(
            request.form.get("longitude"), "Longitude"
        )
        status = request.form.get("status", "active").strip() or "active"
        if status not in STALL_STATUSES:
            raise ValueError("Select a valid stall status.")
        stall.status = status
    except (KeyError, ValueError) as error:
        db.session.rollback()
        flash(str(error), "danger")
        return _render_stalls_list(reopen_modal=reopen, status_code=400)

    if not _commit(
        "Stall updated successfully.",
        "Could not update stall. The stall code may already exist.",
    ):
        return _render_stalls_list(reopen_modal=reopen, status_code=409)
    return redirect(url_for("admin.stalls"))


@admin_bp.route("/stalls/<int:stall_id>/delete", methods=["POST"])
@login_required
@permission_required("stalls.delete")
def stall_delete(stall_id):
    stall = db.get_or_404(Stall, stall_id)
    db.session.delete(stall)
    _commit(
        "Stall deleted successfully.",
        "Stall cannot be deleted while related inspections, complaints, or records exist.",
    )
    return redirect(url_for("admin.stalls"))


@admin_bp.route("/complaints")
@login_required
@permission_required("complaints.view")
def complaints():
    status = request.args.get("status", "").strip()
    query = Complaint.query.join(Complaint.stall)
    if status in COMPLAINT_STATUSES:
        query = query.filter(Complaint.status == status)
    records = query.order_by(Complaint.submitted_at.desc()).all()
    return render_template(
        "admin/complaints/list.html",
        page_title="Complaints",
        complaints=records,
        selected_status=status,
    )


def _wants_partial():
    """True only when the request came from the complaint list's own
    modal loader (templates/admin/complaints/list.html), which sends this
    dedicated marker and expects back just the reusable inner panel.

    This is deliberately NOT the generic `X-Requested-With: XMLHttpRequest`
    header -- the shared admin-wide AJAX layer in templates/admin/base.html
    sends that on every POST form site-wide (including the standalone
    complaint detail page's own forms), and that layer expects a *full*
    page back so it can swap `.admin-content` in place. Keying off the
    generic header here would make it hand those callers a bare partial
    with no `.admin-content` to find, so `swapContent()` would fall back
    to a full page reload on every save -- exactly the behavior this was
    built to avoid.
    """
    return request.headers.get("X-Panel-Request") == "1"


def _render_complaint(complaint, status_code=200):
    if _wants_partial():
        return (
            render_template(
                "admin/complaints/_panel.html",
                complaint=complaint,
                standalone=True,
            ),
            status_code,
        )
    return (
        render_template(
            "admin/complaints/detail.html",
            page_title="Manage Complaint",
            complaint=complaint,
        ),
        status_code,
    )


@admin_bp.route("/complaints/<int:complaint_id>", methods=["GET", "POST"])
@login_required
@permission_required("complaints.view")
def complaint_manage(complaint_id):
    complaint = db.get_or_404(Complaint, complaint_id)
    if request.method == "POST":
        # Viewing a complaint and deciding its outcome are separate
        # capabilities -- complaints.view gets you the page, changing
        # anything on it requires complaints.respond.
        if not current_user.has_permission("complaints.respond"):
            abort(403)
        status = request.form.get("status", "")
        if status not in COMPLAINT_STATUSES:
            flash("Select a valid complaint status.", "danger")
            return _render_complaint(complaint, 400)
        current_status = complaint.status
        if status not in COMPLAINT_TRANSITIONS.get(current_status, set()):
            flash(
                f"Complaint cannot move from '{current_status}' to "
                f"'{status}' directly.",
                "danger",
            )
            return _render_complaint(complaint, 400)
        status_changed = status != current_status
        response_text = request.form.get("admin_response", "").strip()
        response_changed = response_text != (complaint.admin_response or "")

        complaint.status = status
        complaint.admin_response = response_text or None
        complaint.resolved_at = (
            datetime.now()
            if status in {"resolved", "rejected", "closed"}
            else None
        )

        action_description = request.form.get(
            "action_description", ""
        ).strip()
        due_date = request.form.get("due_date", "")
        if action_description:
            if not due_date:
                db.session.rollback()
                flash(
                    "A due date is required for a corrective action.",
                    "danger",
                )
                return _render_complaint(complaint, 400)
            try:
                action_due_date = _parse_date(due_date)
            except ValueError:
                db.session.rollback()
                flash("Enter a valid corrective-action due date.", "danger")
                return _render_complaint(complaint, 400)
            existing_open_action = next(
                (
                    action
                    for action in complaint.corrective_actions
                    if action.status in {"pending", "in_progress"}
                ),
                None,
            )
            if existing_open_action is not None:
                flash(
                    "An open corrective action already exists for this "
                    "complaint; resolve or cancel it before adding another.",
                    "warning",
                )
            else:
                db.session.add(
                    CorrectiveAction(
                        complaint_id=complaint.complaint_id,
                        assigned_to_vendor_id=complaint.stall.vendor_id,
                        action_description=action_description,
                        due_date=action_due_date,
                        status="pending",
                    )
                )
                if status == "submitted":
                    complaint.status = "under_review"

        if _commit(
            "Complaint updated successfully.",
            "Complaint could not be updated.",
        ):
            if status_changed:
                _refresh_stall_risk(complaint.stall_id)
            if status_changed or response_changed:
                _notify_complaint_update(complaint, status_changed, response_text)
        if not _wants_partial():
            return redirect(
                url_for(
                    "admin.complaint_manage",
                    complaint_id=complaint.complaint_id,
                )
            )

    return _render_complaint(complaint)


@admin_bp.route("/evidence/<int:evidence_id>")
@login_required
@permission_required("complaints.view", "complaints.evidence")
def evidence_download(evidence_id):
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    record_audit(evidence, current_user, "viewed")
    return serve_complaint_evidence(evidence)


@admin_bp.route("/inspection-disputes")
@login_required
@permission_required("inspection_disputes.view")
def inspection_disputes():
    status = request.args.get("status", "").strip()
    query = InspectionDispute.query.join(InspectionDispute.vendor)
    if status in DISPUTE_STATUSES:
        query = query.filter(InspectionDispute.status == status)
    records = query.order_by(InspectionDispute.submitted_at.desc()).all()
    return render_template(
        "admin/inspection_disputes/list.html",
        page_title="Inspection Disputes",
        disputes=records,
        selected_status=status,
    )


def _render_dispute(dispute, status_code=200):
    if _wants_partial():
        return (
            render_template(
                "admin/inspection_disputes/_panel.html",
                dispute=dispute,
                standalone=True,
            ),
            status_code,
        )
    return (
        render_template(
            "admin/inspection_disputes/detail.html",
            page_title="Manage Inspection Dispute",
            dispute=dispute,
        ),
        status_code,
    )


@admin_bp.route("/inspection-disputes/<int:dispute_id>", methods=["GET", "POST"])
@login_required
@permission_required("inspection_disputes.view")
def inspection_dispute_manage(dispute_id):
    dispute = db.get_or_404(InspectionDispute, dispute_id)
    if request.method == "POST":
        if not current_user.has_permission("inspection_disputes.respond"):
            abort(403)
        status = request.form.get("status", "")
        if status not in DISPUTE_STATUSES:
            flash("Select a valid dispute status.", "danger")
            return _render_dispute(dispute, 400)
        current_status = dispute.status
        if status not in DISPUTE_TRANSITIONS.get(current_status, set()):
            flash(
                f"Dispute cannot move from '{current_status}' to "
                f"'{status}' directly.",
                "danger",
            )
            return _render_dispute(dispute, 400)

        dispute.status = status
        dispute.admin_response = request.form.get("admin_response", "").strip() or None
        dispute.resolved_at = (
            datetime.now() if status in {"resolved", "rejected"} else None
        )

        _commit(
            "Inspection dispute updated successfully.",
            "Inspection dispute could not be updated.",
        )
        if not _wants_partial():
            return redirect(
                url_for(
                    "admin.inspection_dispute_manage",
                    dispute_id=dispute.dispute_id,
                )
            )

    return _render_dispute(dispute)


@admin_bp.route("/inspection-disputes/evidence/<int:evidence_id>")
@login_required
@permission_required("inspection_disputes.view")
def inspection_dispute_evidence_download(evidence_id):
    evidence = db.get_or_404(InspectionDisputeEvidence, evidence_id)
    return serve_dispute_evidence(evidence)


@admin_bp.route("/evidence/<int:evidence_id>/status", methods=["POST"])
@login_required
@permission_required("complaints.evidence")
def evidence_status(evidence_id):
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    status = request.form.get("verification_status", "")
    if status not in EVIDENCE_VERIFICATION_STATUSES:
        flash("Select a valid evidence verification status.", "danger")
        if not _wants_partial():
            return redirect(
                url_for(
                    "admin.complaint_manage",
                    complaint_id=evidence.complaint_id,
                )
            )
        return _render_complaint(evidence.complaint, 400)

    rejection_reason = request.form.get("rejection_reason", "").strip()
    if status == "rejected" and not rejection_reason:
        flash("A rejection reason is required to reject evidence.", "danger")
        if not _wants_partial():
            return redirect(
                url_for(
                    "admin.complaint_manage",
                    complaint_id=evidence.complaint_id,
                )
            )
        return _render_complaint(evidence.complaint, 400)

    # Evidence verification is a decision about the FILE, not about the
    # complaint -- complaint.status is never touched here. See
    # complaint_manage() for the separate, independent complaint decision.
    evidence.verification_status = status
    evidence.rejection_reason = rejection_reason if status == "rejected" else None
    if status in {"verified", "rejected"}:
        evidence.verified_by = current_user.user_id
        evidence.verified_at = datetime.now()
    else:
        evidence.verified_by = None
        evidence.verified_at = None

    if _commit(
        "Evidence status updated.",
        "Evidence status could not be updated.",
    ):
        record_audit(
            evidence,
            current_user,
            EVIDENCE_ACTION_BY_STATUS[status],
            details=rejection_reason if status == "rejected" else None,
        )

    if not _wants_partial():
        return redirect(
            url_for("admin.complaint_manage", complaint_id=evidence.complaint_id)
        )
    return _render_complaint(evidence.complaint)


@admin_bp.route("/inspections")
@login_required
@permission_required("inspections.view")
def inspections():
    status = request.args.get("status", "").strip()
    risk = request.args.get("risk", "").strip()
    query = Inspection.query.join(Inspection.stall).join(
        Inspection.inspector
    )
    if status in {"draft", "submitted", "approved", "rejected"}:
        query = query.filter(Inspection.status == status)
    if risk in {"low", "medium", "high", "critical"}:
        query = query.filter(Inspection.risk_level == risk)
    records = query.order_by(
        Inspection.inspection_date.desc(),
        Inspection.inspection_id.desc(),
    ).all()
    return render_template(
        "admin/inspections/list.html",
        page_title="Inspections",
        inspections=records,
        selected_status=status,
        selected_risk=risk,
    )


@admin_bp.route("/inspections/<int:inspection_id>/approve", methods=["POST"])
@login_required
@permission_required("inspections.approve")
def inspection_approve(inspection_id):
    inspection = db.get_or_404(Inspection, inspection_id)
    if inspection.status != "submitted":
        flash("Only a submitted inspection can be approved.", "danger")
        return redirect(url_for("admin.inspections"))
    inspection.status = "approved"
    _commit(
        "Inspection approved.",
        "Inspection could not be approved.",
    )
    return redirect(url_for("admin.inspections"))


@admin_bp.route("/inspections/<int:inspection_id>/reject", methods=["POST"])
@login_required
@permission_required("inspections.reject")
def inspection_reject(inspection_id):
    inspection = db.get_or_404(Inspection, inspection_id)
    if inspection.status != "submitted":
        flash("Only a submitted inspection can be rejected.", "danger")
        return redirect(url_for("admin.inspections"))
    inspection.status = "rejected"
    _commit(
        "Inspection rejected.",
        "Inspection could not be rejected.",
    )
    return redirect(url_for("admin.inspections"))


@admin_bp.route("/reviews")
@login_required
@permission_required("reviews.view")
def reviews():
    status = request.args.get("status", "").strip()
    query = Review.query.join(Review.stall).join(Review.user)
    if status in {"visible", "hidden", "flagged"}:
        query = query.filter(Review.status == status)
    records = query.order_by(Review.created_at.desc()).all()
    return render_template(
        "admin/reviews/list.html",
        page_title="Reviews",
        reviews=records,
        selected_status=status,
    )


@admin_bp.route("/reviews/<int:review_id>/status", methods=["POST"])
@login_required
@permission_required("reviews.moderate")
def review_status(review_id):
    review = db.get_or_404(Review, review_id)
    status = request.form.get("status", "")
    if status not in {"visible", "hidden", "flagged"}:
        flash("Select a valid review status.", "danger")
        return redirect(url_for("admin.reviews"))
    review.status = status
    _commit("Review status updated.", "Review status could not be updated.")
    return redirect(url_for("admin.reviews"))


@admin_bp.route("/risk-engine")
@login_required
@permission_required("risk_engine.view")
def risk_engine():
    ranked = (
        db.session.query(
            Inspection.stall_id,
            Inspection.inspection_id,
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
    latest = (
        db.session.query(ranked)
        .filter(ranked.c.row_num == 1)
        .subquery()
    )
    records = (
        db.session.query(
            Stall,
            latest.c.inspection_id,
            latest.c.inspection_date,
            latest.c.overall_score,
            latest.c.risk_level,
            latest.c.reinspection_date,
        )
        .outerjoin(latest, latest.c.stall_id == Stall.stall_id)
        .filter(Stall.status == "active")
        .order_by(
            latest.c.overall_score.is_(None).desc(),
            latest.c.overall_score,
            Stall.stall_name,
        )
        .all()
    )
    return render_template(
        "admin/risk_engine.html",
        page_title="Risk Engine",
        records=records,
    )


def _assignable_roles():
    """Roles selectable from the Users page. Vendor is excluded -- vendor
    accounts require business_name/license_number and already have a
    dedicated admin/vendors/new flow. A non-super-admin only sees
    non-admin-tier roles, closing the privilege-escalation path where a
    limited admin could otherwise create/promote their way to full
    access. A user without users.inspectors doesn't see Inspector as an
    option either, matching what user_create/user_edit would actually
    let them do."""
    query = Role.query.filter(Role.role_name != "vendor")
    if not current_user.is_super_admin:
        query = query.filter(Role.is_admin_tier.is_(False))
    if not current_user.has_permission("users.inspectors"):
        query = query.filter(Role.role_name != "inspector")
    return query.order_by(Role.role_name).all()


def _render_users_list(
    role_name="", status="", reopen_modal=None, status_code=200
):
    query = User.query.join(User.role)
    if role_name:
        query = query.filter(Role.role_name == role_name)
    if status in {"active", "inactive", "suspended"}:
        query = query.filter(User.status == status)
    records = query.order_by(User.created_at.desc()).all()
    return (
        render_template(
            "admin/users/list.html",
            page_title="Users",
            users=records,
            all_roles=Role.query.order_by(Role.role_name).all(),
            assignable_roles=_assignable_roles(),
            areas=Area.query.order_by(Area.area_name).all(),
            selected_role=role_name,
            selected_status=status,
            reopen_modal=reopen_modal,
        ),
        status_code,
    )


@admin_bp.route("/users")
@login_required
@permission_required("users.view")
def users():
    return _render_users_list(
        request.args.get("role", "").strip(),
        request.args.get("status", "").strip(),
    )


@admin_bp.route("/users/<int:user_id>/status", methods=["POST"])
@login_required
@permission_required("users.status")
def user_status(user_id):
    user = db.get_or_404(User, user_id)
    status = request.form.get("status", "")
    if status not in {"active", "inactive", "suspended"}:
        flash("Select a valid user status.", "danger")
        return redirect(url_for("admin.users"))
    if user.user_id == current_user.user_id and status != "active":
        flash("You cannot disable your own signed-in account.", "danger")
        return redirect(url_for("admin.users"))
    user.status = status
    _commit("User status updated.", "User status could not be updated.")
    return redirect(url_for("admin.users"))


def _apply_inspector_transition(user, role, form):
    """Create, update, or remove the linked Inspector row to match the
    user's (possibly new) role. Returns an error message, or None on
    success. Mirrors the validation the old dedicated inspector routes
    used to do."""
    was_inspector = user.inspector_profile is not None
    becomes_inspector = role.role_name == "inspector"

    if (was_inspector or becomes_inspector) and not current_user.has_permission(
        "users.inspectors"
    ):
        return "You do not have permission to manage inspector accounts."

    if was_inspector and not becomes_inspector:
        if user.inspector_profile.inspections:
            return (
                "Cannot change this user's role while they have existing "
                "inspections on record."
            )
        db.session.delete(user.inspector_profile)
        return None

    if not becomes_inspector:
        return None

    employee_code = form.get("employee_code", "").strip()
    if not employee_code:
        return "Employee code is required for an inspector account."
    try:
        assigned_area_id = (
            int(form["assigned_area_id"])
            if form.get("assigned_area_id")
            else None
        )
    except ValueError:
        return "Select a valid assigned area."
    designation = form.get("designation", "").strip() or None

    if was_inspector:
        user.inspector_profile.employee_code = employee_code
        user.inspector_profile.designation = designation
        user.inspector_profile.assigned_area_id = assigned_area_id
    else:
        db.session.add(
            Inspector(
                user=user,
                employee_code=employee_code,
                designation=designation,
                assigned_area_id=assigned_area_id,
            )
        )
    return None


@admin_bp.route("/users", methods=["POST"])
@login_required
@permission_required("users.create")
def user_create():
    reopen = _reopen_payload("create", url_for("admin.user_create"), request.form)

    role = db.session.get(Role, request.form.get("role_id", type=int))
    if role is None or role.role_name == "vendor":
        flash("Select a valid role.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)
    if role.is_admin_tier and not current_user.is_super_admin:
        flash(
            "Only a super admin can create an admin-tier account.", "danger"
        )
        return _render_users_list(reopen_modal=reopen, status_code=403)

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip() or None
    status = request.form.get("status", "active").strip() or "active"
    password = request.form.get("password", "")

    if not full_name or not email:
        flash("Full name and email are required.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)
    if status not in USER_STATUSES:
        flash("Select a valid account status.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)
    if len(password) < 8:
        flash("Password must contain at least 8 characters.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)

    user = User(
        role_id=role.role_id,
        full_name=full_name,
        email=email,
        phone=phone,
        status=status,
    )
    user.set_password(password)
    if role.is_admin_tier:
        user.is_super_admin = request.form.get("is_super_admin") == "on"

    if role.role_name == "inspector":
        error = _apply_inspector_transition(user, role, request.form)
        if error:
            flash(error, "danger")
            return _render_users_list(reopen_modal=reopen, status_code=400)
    else:
        db.session.add(user)

    if role.is_admin_tier:
        # Admin-tier account creation is the security-sensitive case rule
        # 4 cares about; ordinary customer/vendor/inspector creation
        # isn't logged here to keep this trail focused on escalations.
        db.session.flush()
        record_role_change(
            current_user, user, None, role.role_id,
            "Admin-tier account created via admin Users management",
        )

    if not _commit(
        "User created successfully.",
        "Could not create user. Email, phone, or employee code may "
        "already exist.",
    ):
        return _render_users_list(reopen_modal=reopen, status_code=409)
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>", methods=["POST"])
@login_required
@permission_required("users.edit")
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    target_was_admin_tier = bool(user.role and user.role.is_admin_tier)
    reopen = _reopen_payload(
        "edit", url_for("admin.user_edit", user_id=user_id), request.form
    )

    role = db.session.get(Role, request.form.get("role_id", type=int))
    if role is None or role.role_name == "vendor":
        flash("Select a valid role.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)
    if (
        (target_was_admin_tier or role.is_admin_tier)
        and not current_user.is_super_admin
    ):
        flash(
            "Only a super admin can manage admin-tier accounts.", "danger"
        )
        return _render_users_list(reopen_modal=reopen, status_code=403)

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip() or None
    status = request.form.get("status", "active").strip() or "active"
    is_super_admin_field = request.form.get("is_super_admin") == "on"

    if not full_name or not email:
        flash("Full name and email are required.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)
    if status not in USER_STATUSES:
        flash("Select a valid account status.", "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)

    if user.user_id == current_user.user_id:
        if status != "active":
            flash("You cannot disable your own signed-in account.", "danger")
            return _render_users_list(reopen_modal=reopen, status_code=400)
        if not role.is_admin_tier:
            flash(
                "You cannot change your own role away from an admin-tier "
                "role.",
                "danger",
            )
            return _render_users_list(reopen_modal=reopen, status_code=400)
        if current_user.is_super_admin and not is_super_admin_field:
            flash("You cannot remove your own super admin access.", "danger")
            return _render_users_list(reopen_modal=reopen, status_code=400)

    password = request.form.get("password", "")
    if password:
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return _render_users_list(reopen_modal=reopen, status_code=400)
        user.set_password(password)

    error = _apply_inspector_transition(user, role, request.form)
    if error:
        flash(error, "danger")
        return _render_users_list(reopen_modal=reopen, status_code=400)

    old_role_id = user.role_id
    old_status = user.status
    user.full_name = full_name
    user.email = email
    user.phone = phone
    user.status = status
    user.role_id = role.role_id
    user.is_super_admin = role.is_admin_tier and is_super_admin_field
    record_role_change(
        current_user, user, old_role_id, role.role_id,
        "Changed via admin Users management",
    )
    if old_status != "suspended" and status == "suspended":
        record_auth_event(
            "account_suspended", user=user,
            details=f"Suspended by {current_user.email}",
        )
    elif old_status == "suspended" and status == "active":
        record_auth_event(
            "account_reactivated", user=user,
            details=f"Reactivated by {current_user.email}",
        )

    if not _commit(
        "User updated successfully.",
        "Could not update user. A unique field may already be in use.",
    ):
        return _render_users_list(reopen_modal=reopen, status_code=409)
    return redirect(url_for("admin.users"))


PERMISSION_GROUP_LABELS = (
    ("vendors", "Vendors"),
    ("stalls", "Stalls"),
    ("users", "Users"),
    ("complaints", "Complaints"),
    ("inspections", "Inspections"),
    ("reviews", "Reviews"),
    ("risk_engine", "Risk Engine"),
    ("reports", "Reports"),
    ("settings", "Settings"),
    ("roles", "Roles & Permissions"),
)


def _grouped_permissions():
    all_permissions = Permission.query.order_by(Permission.code).all()
    groups = []
    for prefix, label in PERMISSION_GROUP_LABELS:
        items = [p for p in all_permissions if p.code.startswith(prefix + ".")]
        if items:
            groups.append({"label": label, "permissions": items})
    return groups


@admin_bp.route("/roles")
@login_required
@super_admin_required
def roles():
    return render_template(
        "admin/roles/list.html",
        page_title="Roles & Permissions",
        roles=Role.query.order_by(Role.role_name).all(),
        permission_groups=_grouped_permissions(),
    )


@admin_bp.route("/roles", methods=["POST"])
@login_required
@super_admin_required
def role_create():
    role_name = request.form.get("role_name", "").strip().lower()
    description = request.form.get("description", "").strip() or None
    if not role_name:
        flash("Role name is required.", "danger")
        return redirect(url_for("admin.roles"))
    db.session.add(
        Role(
            role_name=role_name,
            description=description,
            is_system=False,
            is_admin_tier=False,
        )
    )
    _commit(
        "Role created successfully.",
        "Could not create role. That name may already be in use.",
    )
    return redirect(url_for("admin.roles"))


@admin_bp.route("/roles/<int:role_id>", methods=["POST"])
@login_required
@super_admin_required
def role_edit(role_id):
    role = db.get_or_404(Role, role_id)
    new_is_admin_tier = request.form.get("is_admin_tier") == "on"
    if role.role_id == current_user.role_id and not new_is_admin_tier:
        flash(
            "You cannot remove admin-panel access from your own role.",
            "danger",
        )
        return redirect(url_for("admin.roles"))

    if not role.is_system:
        new_name = request.form.get("role_name", "").strip().lower()
        if not new_name:
            flash("Role name is required.", "danger")
            return redirect(url_for("admin.roles"))
        role.role_name = new_name

    role.description = request.form.get("description", "").strip() or None
    role.is_admin_tier = new_is_admin_tier

    selected_codes = set(request.form.getlist("permissions"))
    role.permissions = (
        Permission.query.filter(Permission.code.in_(selected_codes)).all()
        if selected_codes
        else []
    )

    _commit(
        "Role updated successfully.",
        "Could not update role. That name may already be in use.",
    )
    return redirect(url_for("admin.roles"))


@admin_bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@super_admin_required
def role_delete(role_id):
    role = db.get_or_404(Role, role_id)
    if role.is_system:
        flash("Built-in roles cannot be deleted.", "danger")
        return redirect(url_for("admin.roles"))
    if role.users.count() > 0:
        flash(
            "Cannot delete a role while users are assigned to it.", "danger"
        )
        return redirect(url_for("admin.roles"))
    db.session.delete(role)
    _commit("Role deleted successfully.", "Role could not be deleted.")
    return redirect(url_for("admin.roles"))


@admin_bp.route("/audit-log")
@login_required
@super_admin_required
def audit_log():
    search = request.args.get("q", "").strip()
    TargetUser = aliased(User)
    ActorUser = aliased(User)
    OldRole = aliased(Role)
    NewRole = aliased(Role)

    query = (
        db.session.query(RoleAuditLog, TargetUser, ActorUser, OldRole, NewRole)
        .join(TargetUser, RoleAuditLog.target_user_id == TargetUser.user_id)
        .outerjoin(ActorUser, RoleAuditLog.actor_user_id == ActorUser.user_id)
        .outerjoin(OldRole, RoleAuditLog.old_role_id == OldRole.role_id)
        .join(NewRole, RoleAuditLog.new_role_id == NewRole.role_id)
    )
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                TargetUser.full_name.ilike(term),
                TargetUser.email.ilike(term),
                ActorUser.full_name.ilike(term),
                ActorUser.email.ilike(term),
                NewRole.role_name.ilike(term),
                OldRole.role_name.ilike(term),
                RoleAuditLog.reason.ilike(term),
            )
        )

    # An append-only audit trail has no natural upper bound, so this is
    # capped to the most recent 300 entries rather than paginated --
    # simplest thing that keeps the page fast; revisit with real
    # pagination if this table grows large enough for that to matter.
    rows = query.order_by(RoleAuditLog.created_at.desc()).limit(300).all()
    entries = [
        {
            "audit": audit,
            "target_user": target_user,
            "actor_user": actor_user,
            "old_role": old_role,
            "new_role": new_role,
        }
        for audit, target_user, actor_user, old_role, new_role in rows
    ]
    return render_template(
        "admin/audit_log/list.html",
        page_title="Role Audit Log",
        entries=entries,
        search=search,
    )


@admin_bp.route("/audit-log/logins")
@login_required
@super_admin_required
def login_audit_log():
    from models import AuthAuditLog

    search = request.args.get("q", "").strip()
    query = db.session.query(AuthAuditLog).outerjoin(
        User, AuthAuditLog.user_id == User.user_id
    )
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                User.full_name.ilike(term),
                User.email.ilike(term),
                AuthAuditLog.email_attempted.ilike(term),
                AuthAuditLog.ip_address.ilike(term),
                AuthAuditLog.details.ilike(term),
            )
        )

    # Same append-only, most-recent-300 approach as the role audit log
    # above -- simplest thing that stays fast without real pagination.
    entries = query.order_by(AuthAuditLog.audit_id.desc()).limit(300).all()
    return render_template(
        "admin/audit_log/login_list.html",
        page_title="Login Activity",
        entries=entries,
        search=search,
    )


@admin_bp.route("/access-requests")
@login_required
@super_admin_required
def access_requests():
    # Unified view of every pending self-service escalation: Inspector
    # and Admin requests live in role_requests, but Vendor keeps using
    # its own existing pending-application workflow (vendors.status) --
    # see services/role_requests.py's module docstring for why these
    # aren't merged into one table. Both are shown together here so a
    # Super Admin has one place to review all three.
    status_filter = request.args.get("status", "pending").strip().lower()

    role_query = RoleRequest.query
    if status_filter in ("pending", "approved", "rejected", "cancelled"):
        role_query = role_query.filter_by(status=status_filter)
    role_entries = role_query.order_by(RoleRequest.request_id.desc()).limit(300).all()

    vendor_entries = []
    if status_filter in ("pending", "approved", "rejected"):
        vendor_status = {"approved": "approved", "rejected": "rejected"}.get(
            status_filter, "pending"
        )
        vendor_entries = (
            Vendor.query.filter_by(status=vendor_status)
            .order_by(Vendor.created_at.desc())
            .limit(300)
            .all()
        )

    return render_template(
        "admin/access_requests/list.html",
        page_title="Access Requests",
        role_entries=role_entries,
        vendor_entries=vendor_entries,
        status_filter=status_filter,
        areas=Area.query.order_by(Area.area_name).all(),
    )


@admin_bp.route("/access-requests/<int:request_id>/approve", methods=["POST"])
@login_required
@super_admin_required
def access_request_approve(request_id):
    role_request = db.get_or_404(RoleRequest, request_id)
    try:
        approve_role_request(role_request, current_user, inspector_form=request.form)
    except RoleRequestError as error:
        flash(str(error), "danger")
        return redirect(url_for("admin.access_requests"))
    flash(
        f"{role_request.requested_role.title()} access approved for "
        f"{role_request.user.full_name}.",
        "success",
    )
    return redirect(url_for("admin.access_requests"))


@admin_bp.route("/access-requests/<int:request_id>/reject", methods=["POST"])
@login_required
@super_admin_required
def access_request_reject(request_id):
    role_request = db.get_or_404(RoleRequest, request_id)
    try:
        reject_role_request(
            role_request, current_user, request.form.get("rejection_reason", "")
        )
    except RoleRequestError as error:
        flash(str(error), "danger")
        return redirect(url_for("admin.access_requests"))
    flash("Request rejected.", "info")
    return redirect(url_for("admin.access_requests"))


@admin_bp.route("/settings")
@login_required
@permission_required("settings.view")
def settings():
    return render_template(
        "admin/settings.html",
        page_title="Settings",
        roles=Role.query.order_by(Role.role_name).all(),
        areas=Area.query.order_by(Area.area_name).all(),
        criteria=InspectionCriterion.query.order_by(
            InspectionCriterion.criteria_id
        ).all(),
        categories=FoodCategory.query.order_by(
            FoodCategory.category_name
        ).all(),
        complaint_types=ComplaintType.query.order_by(
            ComplaintType.type_name
        ).all(),
    )
