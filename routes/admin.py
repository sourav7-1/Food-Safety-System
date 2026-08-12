from datetime import datetime
from decimal import Decimal, InvalidOperation

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
    ComplaintEvidence,
    ComplaintType,
    CorrectiveAction,
    FoodCategory,
    Inspection,
    InspectionCriterion,
    Inspector,
    Review,
    Role,
    Stall,
    User,
    Vendor,
)
from routes import role_required
from services.evidence import record_audit, serve_complaint_evidence
from services.registration_import import cache_photo


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


@admin_bp.route("/vendors")
@login_required
@role_required("admin")
def vendors():
    search = request.args.get("q", "").strip()
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
    return render_template(
        "admin/vendors/list.html",
        page_title="Vendors",
        vendors=records,
        search=search,
    )


@admin_bp.route("/vendors/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def vendor_create():
    if request.method == "POST":
        vendor_role = _role("vendor")
        if vendor_role is None:
            flash("The vendor role is missing from the roles table.", "danger")
            return render_template(
                "admin/vendors/form.html",
                page_title="Add Vendor",
                vendor=None,
            ), 409

        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return render_template(
                "admin/vendors/form.html",
                page_title="Add Vendor",
                vendor=None,
            ), 400

        status = request.form.get("status", "active").strip() or "active"
        if status not in USER_STATUSES:
            flash("Select a valid account status.", "danger")
            return render_template(
                "admin/vendors/form.html",
                page_title="Add Vendor",
                vendor=None,
            ), 400

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
                business_name=request.form.get(
                    "business_name", ""
                ).strip(),
                license_number=request.form.get(
                    "license_number", ""
                ).strip(),
                license_expiry_date=_parse_date(
                    request.form.get("license_expiry_date")
                ),
                national_id=request.form.get(
                    "national_id", ""
                ).strip()
                or None,
            )
            db.session.add(vendor)
        except ValueError as error:
            flash(str(error), "danger")
            return render_template(
                "admin/vendors/form.html",
                page_title="Add Vendor",
                vendor=None,
            ), 400

        if _commit(
            "Vendor created successfully.",
            "Could not create vendor. Email, phone, licence, or national ID may already exist.",
        ):
            return redirect(url_for("admin.vendors"))

    return render_template(
        "admin/vendors/form.html",
        page_title="Add Vendor",
        vendor=None,
    )


@admin_bp.route("/vendors/<int:vendor_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def vendor_edit(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    if request.method == "POST":
        vendor.user.full_name = request.form.get("full_name", "").strip()
        vendor.user.email = request.form.get("email", "").strip().lower()
        vendor.user.phone = request.form.get("phone", "").strip() or None
        status = request.form.get("status", "active").strip() or "active"
        if status not in USER_STATUSES:
            flash("Select a valid account status.", "danger")
            return render_template(
                "admin/vendors/form.html",
                page_title="Edit Vendor",
                vendor=vendor,
            ), 400
        vendor.user.status = status
        password = request.form.get("password", "")
        if password:
            if len(password) < 8:
                flash(
                    "Password must contain at least 8 characters.", "danger"
                )
                return render_template(
                    "admin/vendors/form.html",
                    page_title="Edit Vendor",
                    vendor=vendor,
                ), 400
            vendor.user.set_password(password)
        vendor.business_name = request.form.get(
            "business_name", ""
        ).strip()
        vendor.license_number = request.form.get(
            "license_number", ""
        ).strip()
        try:
            vendor.license_expiry_date = _parse_date(
                request.form.get("license_expiry_date")
            )
        except ValueError:
            db.session.rollback()
            flash("Enter a valid licence expiry date.", "danger")
            return render_template(
                "admin/vendors/form.html",
                page_title="Edit Vendor",
                vendor=vendor,
            ), 400
        vendor.national_id = (
            request.form.get("national_id", "").strip() or None
        )

        if _commit(
            "Vendor updated successfully.",
            "Could not update vendor. A unique field may already be in use.",
        ):
            return redirect(url_for("admin.vendors"))

    return render_template(
        "admin/vendors/form.html",
        page_title="Edit Vendor",
        vendor=vendor,
    )


@admin_bp.route("/vendors/<int:vendor_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
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


@admin_bp.route("/stalls")
@login_required
@role_required("admin")
def stalls():
    search = request.args.get("q", "").strip()
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
    return render_template(
        "admin/stalls/list.html",
        page_title="Stalls",
        stalls=records,
        search=search,
    )


@admin_bp.route("/stalls/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def stall_create():
    vendors = Vendor.query.order_by(Vendor.business_name).all()
    areas = Area.query.order_by(Area.area_name).all()
    if request.method == "POST":
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
                latitude=_parse_decimal(
                    request.form.get("latitude"), "Latitude"
                ),
                longitude=_parse_decimal(
                    request.form.get("longitude"), "Longitude"
                ),
                status=status,
            )
            db.session.add(stall)
        except (KeyError, ValueError) as error:
            flash(str(error), "danger")
            return render_template(
                "admin/stalls/form.html",
                page_title="Add Stall",
                stall=None,
                vendors=vendors,
                areas=areas,
            ), 400

        if _commit(
            "Stall created successfully.",
            "Could not create stall. The stall code may already exist.",
        ):
            return redirect(url_for("admin.stalls"))

    return render_template(
        "admin/stalls/form.html",
        page_title="Add Stall",
        stall=None,
        vendors=vendors,
        areas=areas,
    )


@admin_bp.route("/stalls/<int:stall_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def stall_edit(stall_id):
    stall = db.get_or_404(Stall, stall_id)
    vendors = Vendor.query.order_by(Vendor.business_name).all()
    areas = Area.query.order_by(Area.area_name).all()
    if request.method == "POST":
        try:
            stall.vendor_id = int(request.form["vendor_id"])
            stall.area_id = int(request.form["area_id"])
            stall.stall_name = request.form.get(
                "stall_name", ""
            ).strip()
            stall.stall_code = request.form.get(
                "stall_code", ""
            ).strip()
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
            flash(str(error), "danger")
            return render_template(
                "admin/stalls/form.html",
                page_title="Edit Stall",
                stall=stall,
                vendors=vendors,
                areas=areas,
            ), 400

        if _commit(
            "Stall updated successfully.",
            "Could not update stall. The stall code may already exist.",
        ):
            return redirect(url_for("admin.stalls"))

    return render_template(
        "admin/stalls/form.html",
        page_title="Edit Stall",
        stall=stall,
        vendors=vendors,
        areas=areas,
    )


@admin_bp.route("/stalls/<int:stall_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def stall_delete(stall_id):
    stall = db.get_or_404(Stall, stall_id)
    db.session.delete(stall)
    _commit(
        "Stall deleted successfully.",
        "Stall cannot be deleted while related inspections, complaints, or records exist.",
    )
    return redirect(url_for("admin.stalls"))


@admin_bp.route("/inspectors")
@login_required
@role_required("admin")
def inspectors():
    search = request.args.get("q", "").strip()
    query = Inspector.query.join(Inspector.user).outerjoin(
        Inspector.assigned_area
    )
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Inspector.employee_code.ilike(term),
                User.full_name.ilike(term),
                User.email.ilike(term),
                Area.area_name.ilike(term),
            )
        )
    records = query.order_by(Inspector.created_at.desc()).all()
    return render_template(
        "admin/inspectors/list.html",
        page_title="Inspectors",
        inspectors=records,
        search=search,
    )


@admin_bp.route("/inspectors/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def inspector_create():
    areas = Area.query.order_by(Area.area_name).all()
    if request.method == "POST":
        inspector_role = _role("inspector")
        if inspector_role is None:
            flash(
                "The inspector role is missing from the roles table.",
                "danger",
            )
            return render_template(
                "admin/inspectors/form.html",
                page_title="Add Inspector",
                inspector=None,
                areas=areas,
            ), 409

        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return render_template(
                "admin/inspectors/form.html",
                page_title="Add Inspector",
                inspector=None,
                areas=areas,
            ), 400

        status = request.form.get("status", "active").strip() or "active"
        if status not in USER_STATUSES:
            flash("Select a valid account status.", "danger")
            return render_template(
                "admin/inspectors/form.html",
                page_title="Add Inspector",
                inspector=None,
                areas=areas,
            ), 400

        user = User(
            role_id=inspector_role.role_id,
            full_name=request.form.get("full_name", "").strip(),
            email=request.form.get("email", "").strip().lower(),
            phone=request.form.get("phone", "").strip() or None,
            status=status,
        )
        user.set_password(password)
        try:
            assigned_area_id = (
                int(request.form["assigned_area_id"])
                if request.form.get("assigned_area_id")
                else None
            )
        except ValueError:
            flash("Select a valid assigned area.", "danger")
            return render_template(
                "admin/inspectors/form.html",
                page_title="Add Inspector",
                inspector=None,
                areas=areas,
            ), 400
        inspector = Inspector(
            user=user,
            employee_code=request.form.get(
                "employee_code", ""
            ).strip(),
            designation=request.form.get("designation", "").strip()
            or None,
            assigned_area_id=assigned_area_id,
        )
        db.session.add(inspector)
        if _commit(
            "Inspector created successfully.",
            "Could not create inspector. Email, phone, or employee code may already exist.",
        ):
            return redirect(url_for("admin.inspectors"))

    return render_template(
        "admin/inspectors/form.html",
        page_title="Add Inspector",
        inspector=None,
        areas=areas,
    )


@admin_bp.route(
    "/inspectors/<int:inspector_id>/edit", methods=["GET", "POST"]
)
@login_required
@role_required("admin")
def inspector_edit(inspector_id):
    inspector = db.get_or_404(Inspector, inspector_id)
    areas = Area.query.order_by(Area.area_name).all()
    if request.method == "POST":
        inspector.user.full_name = request.form.get(
            "full_name", ""
        ).strip()
        inspector.user.email = request.form.get(
            "email", ""
        ).strip().lower()
        inspector.user.phone = (
            request.form.get("phone", "").strip() or None
        )
        status = request.form.get("status", "active").strip() or "active"
        if status not in USER_STATUSES:
            flash("Select a valid account status.", "danger")
            return render_template(
                "admin/inspectors/form.html",
                page_title="Edit Inspector",
                inspector=inspector,
                areas=areas,
            ), 400
        inspector.user.status = status
        password = request.form.get("password", "")
        if password:
            if len(password) < 8:
                flash(
                    "Password must contain at least 8 characters.", "danger"
                )
                return render_template(
                    "admin/inspectors/form.html",
                    page_title="Edit Inspector",
                    inspector=inspector,
                    areas=areas,
                ), 400
            inspector.user.set_password(password)
        inspector.employee_code = request.form.get(
            "employee_code", ""
        ).strip()
        inspector.designation = (
            request.form.get("designation", "").strip() or None
        )
        try:
            inspector.assigned_area_id = (
                int(request.form["assigned_area_id"])
                if request.form.get("assigned_area_id")
                else None
            )
        except ValueError:
            db.session.rollback()
            flash("Select a valid assigned area.", "danger")
            return render_template(
                "admin/inspectors/form.html",
                page_title="Edit Inspector",
                inspector=inspector,
                areas=areas,
            ), 400
        if _commit(
            "Inspector updated successfully.",
            "Could not update inspector. A unique field may already be in use.",
        ):
            return redirect(url_for("admin.inspectors"))

    return render_template(
        "admin/inspectors/form.html",
        page_title="Edit Inspector",
        inspector=inspector,
        areas=areas,
    )


@admin_bp.route(
    "/inspectors/<int:inspector_id>/delete", methods=["POST"]
)
@login_required
@role_required("admin")
def inspector_delete(inspector_id):
    inspector = db.get_or_404(Inspector, inspector_id)
    user = inspector.user
    db.session.delete(inspector)
    db.session.delete(user)
    _commit(
        "Inspector deleted successfully.",
        "Inspector cannot be deleted while related inspections exist.",
    )
    return redirect(url_for("admin.inspectors"))


@admin_bp.route("/complaints")
@login_required
@role_required("admin")
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


@admin_bp.route("/complaints/<int:complaint_id>", methods=["GET", "POST"])
@login_required
@role_required("admin")
def complaint_manage(complaint_id):
    complaint = db.get_or_404(Complaint, complaint_id)
    if request.method == "POST":
        status = request.form.get("status", "")
        if status not in COMPLAINT_STATUSES:
            flash("Select a valid complaint status.", "danger")
            return redirect(
                url_for(
                    "admin.complaint_manage",
                    complaint_id=complaint.complaint_id,
                )
            )
        current_status = complaint.status
        if status not in COMPLAINT_TRANSITIONS.get(current_status, set()):
            flash(
                f"Complaint cannot move from '{current_status}' to "
                f"'{status}' directly.",
                "danger",
            )
            return redirect(
                url_for(
                    "admin.complaint_manage",
                    complaint_id=complaint.complaint_id,
                )
            )
        complaint.status = status
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
                return render_template(
                    "admin/complaints/detail.html",
                    page_title="Manage Complaint",
                    complaint=complaint,
                ), 400
            try:
                action_due_date = _parse_date(due_date)
            except ValueError:
                db.session.rollback()
                flash("Enter a valid corrective-action due date.", "danger")
                return render_template(
                    "admin/complaints/detail.html",
                    page_title="Manage Complaint",
                    complaint=complaint,
                ), 400
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
            if status != current_status:
                _refresh_stall_risk(complaint.stall_id)
            return redirect(
                url_for(
                    "admin.complaint_manage",
                    complaint_id=complaint.complaint_id,
                )
            )

    return render_template(
        "admin/complaints/detail.html",
        page_title="Manage Complaint",
        complaint=complaint,
    )


@admin_bp.route("/evidence/<int:evidence_id>")
@login_required
@role_required("admin")
def evidence_download(evidence_id):
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    record_audit(evidence, current_user, "viewed")
    return serve_complaint_evidence(evidence)


@admin_bp.route("/evidence/<int:evidence_id>/status", methods=["POST"])
@login_required
@role_required("admin")
def evidence_status(evidence_id):
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    status = request.form.get("verification_status", "")
    if status not in EVIDENCE_VERIFICATION_STATUSES:
        flash("Select a valid evidence verification status.", "danger")
        return redirect(
            url_for(
                "admin.complaint_manage",
                complaint_id=evidence.complaint_id,
            )
        )

    rejection_reason = request.form.get("rejection_reason", "").strip()
    if status == "rejected" and not rejection_reason:
        flash("A rejection reason is required to reject evidence.", "danger")
        return redirect(
            url_for(
                "admin.complaint_manage",
                complaint_id=evidence.complaint_id,
            )
        )

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

    return redirect(
        url_for("admin.complaint_manage", complaint_id=evidence.complaint_id)
    )


@admin_bp.route("/inspections")
@login_required
@role_required("admin")
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
@role_required("admin")
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
@role_required("admin")
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
@role_required("admin")
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
@role_required("admin")
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
@role_required("admin")
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


@admin_bp.route("/users")
@login_required
@role_required("admin")
def users():
    role_name = request.args.get("role", "").strip()
    status = request.args.get("status", "").strip()
    query = User.query.join(User.role)
    if role_name in {"admin", "vendor", "inspector", "customer"}:
        query = query.filter(Role.role_name == role_name)
    if status in {"active", "inactive", "suspended"}:
        query = query.filter(User.status == status)
    records = query.order_by(User.created_at.desc()).all()
    return render_template(
        "admin/users/list.html",
        page_title="Users",
        users=records,
        selected_role=role_name,
        selected_status=status,
    )


@admin_bp.route("/users/<int:user_id>/status", methods=["POST"])
@login_required
@role_required("admin")
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


@admin_bp.route("/settings")
@login_required
@role_required("admin")
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
