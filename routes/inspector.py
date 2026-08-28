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
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import (
    Complaint,
    ComplaintEvidence,
    Inspection,
    InspectionCriterion,
    InspectionScore,
    Inspector,
    Stall,
)
from routes import role_required
from services.complaints import (
    COMPLAINT_STATUSES,
    COMPLAINT_TRANSITIONS,
    EVIDENCE_ACTION_BY_STATUS,
    EVIDENCE_VERIFICATION_STATUSES,
    notify_complaint_update,
    refresh_stall_risk,
)
from services.evidence import (
    EvidenceValidationError,
    delete_stored_complaint_files,
    record_audit,
    serve_complaint_evidence,
    validate_and_store_complaint_evidence,
)


inspector_bp = Blueprint(
    "inspection_workflow",
    __name__,
    url_prefix="/inspector/inspections",
)

inspector_complaints_bp = Blueprint(
    "inspector_complaints",
    __name__,
    url_prefix="/inspector/complaints",
)


def _current_inspector():
    inspector = Inspector.query.filter_by(
        user_id=current_user.user_id
    ).first()
    if inspector is None:
        abort(403)
    return inspector


def _available_stalls(inspector):
    query = Stall.query.filter_by(status="active")
    if inspector.assigned_area_id is not None:
        query = query.filter_by(area_id=inspector.assigned_area_id)
    return query.order_by(Stall.stall_name).all()


def _parse_inspection_date(value):
    if not value:
        return datetime.now()
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


@inspector_bp.route("/")
@login_required
@role_required("inspector")
def inspections():
    inspector = _current_inspector()
    records = (
        Inspection.query.filter_by(inspector_id=inspector.inspector_id)
        .join(Inspection.stall)
        .order_by(Inspection.inspection_date.desc())
        .all()
    )
    return render_template(
        "inspector/list.html",
        inspections=records,
        inspector=inspector,
    )


@inspector_bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required("inspector")
def create():
    inspector = _current_inspector()
    criteria = (
        InspectionCriterion.query.filter_by(is_active=True)
        .order_by(InspectionCriterion.criteria_id)
        .all()
    )
    stalls = _available_stalls(inspector)

    if request.method == "POST":
        try:
            stall_id = int(request.form.get("stall_id", ""))
            stall = db.session.get(Stall, stall_id)
            if stall is None or stall.status != "active":
                raise ValueError("Select an active stall.")
            if (
                inspector.assigned_area_id is not None
                and stall.area_id != inspector.assigned_area_id
            ):
                raise ValueError(
                    "That stall is outside your assigned inspection area."
                )
            if not criteria:
                raise ValueError(
                    "No active inspection criteria are configured."
                )

            inspection_date = _parse_inspection_date(
                request.form.get("inspection_date")
            )
            latest_existing = (
                Inspection.query.filter(
                    Inspection.stall_id == stall.stall_id,
                    Inspection.status.in_(("submitted", "approved")),
                )
                .order_by(Inspection.inspection_date.desc())
                .first()
            )
            if (
                latest_existing is not None
                and inspection_date < latest_existing.inspection_date
            ):
                raise ValueError(
                    "Inspection date cannot be earlier than this stall's "
                    "most recent inspection ("
                    + latest_existing.inspection_date.strftime(
                        "%Y-%m-%d %H:%M"
                    )
                    + ")."
                )

            submitted_scores = []
            for criterion in criteria:
                raw_score = request.form.get(
                    f"score_{criterion.criteria_id}", ""
                ).strip()
                if raw_score == "":
                    raise ValueError(
                        f"Score is required for {criterion.criteria_name}."
                    )
                try:
                    score = Decimal(raw_score)
                except InvalidOperation as error:
                    raise ValueError(
                        f"Enter a valid score for {criterion.criteria_name}."
                    ) from error
                if score < 0 or score > criterion.max_score:
                    raise ValueError(
                        f"{criterion.criteria_name} must be between 0 and "
                        f"{criterion.max_score}."
                    )
                submitted_scores.append(
                    (
                        criterion,
                        score,
                        request.form.get(
                            f"comments_{criterion.criteria_id}", ""
                        ).strip()
                        or None,
                    )
                )

            inspection = Inspection(
                stall_id=stall.stall_id,
                inspector_id=inspector.inspector_id,
                inspection_date=inspection_date,
                status="submitted",
                remarks=request.form.get("remarks", "").strip() or None,
            )
            db.session.add(inspection)
            db.session.flush()

            for criterion, score, comments in submitted_scores:
                db.session.add(
                    InspectionScore(
                        inspection_id=inspection.inspection_id,
                        criteria_id=criterion.criteria_id,
                        score=score,
                        comments=comments,
                    )
                )

            # Flush every score insert so MySQL validation and total-score
            # triggers run before risk calculation.
            db.session.flush()
            db.session.refresh(inspection)

            procedure_result = db.session.execute(
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
                {"stall_id": stall.stall_id},
            )
            procedure_result.close()
            risk_result = db.session.execute(
                text(
                    """
                    SELECT
                      @calculated_risk_level AS risk_level,
                      @calculated_risk_score AS risk_score,
                      @calculated_reinspection_date AS reinspection_date
                    """
                )
            ).mappings().one()

            if risk_result["risk_level"] is None:
                raise RuntimeError(
                    "MySQL risk procedure returned no risk result."
                )

            inspection.risk_level = risk_result["risk_level"]
            inspection.reinspection_date = risk_result[
                "reinspection_date"
            ]
            db.session.commit()

            flash(
                "Inspection submitted and risk calculated successfully.",
                "success",
            )
            return redirect(
                url_for(
                    "inspection_workflow.detail",
                    inspection_id=inspection.inspection_id,
                )
            )
        except (ValueError, SQLAlchemyError, RuntimeError) as error:
            db.session.rollback()
            flash(
                f"Inspection was not submitted. {error}",
                "danger",
            )

    return render_template(
        "inspector/form.html",
        inspector=inspector,
        criteria=criteria,
        stalls=stalls,
        default_inspection_date=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@inspector_bp.route("/<int:inspection_id>")
@login_required
@role_required("inspector")
def detail(inspection_id):
    inspector = _current_inspector()
    inspection = Inspection.query.filter_by(
        inspection_id=inspection_id,
        inspector_id=inspector.inspector_id,
    ).first_or_404()
    grade = db.session.execute(
        text("SELECT get_hygiene_grade(:score)"),
        {"score": inspection.overall_score},
    ).scalar_one()
    return render_template(
        "inspector/detail.html",
        inspection=inspection,
        grade=grade,
    )


# -- complaint review (student-filed complaints against a stall) -----------
#
# Admin keeps its own, separate complaint-handling routes in routes/admin.py
# (permission-gated, sees every complaint) -- this is a second, independent
# way to reach the same Complaint rows, scoped to an inspector's own
# assigned area, so field inspectors can resolve reports themselves instead
# of everything routing through admin.


def _in_inspector_scope(inspector, stall):
    """An inspector with no assigned area (assigned_area_id is None) sees
    everything -- same convention _available_stalls() above already uses
    for inspection creation."""
    return inspector.assigned_area_id is None or stall.area_id == inspector.assigned_area_id


def _complaints_query_for_inspector(inspector):
    query = Complaint.query.join(Complaint.stall)
    if inspector.assigned_area_id is not None:
        query = query.filter(Stall.area_id == inspector.assigned_area_id)
    return query


def _get_complaint_in_scope(inspector, complaint_id):
    complaint = db.get_or_404(Complaint, complaint_id)
    if not _in_inspector_scope(inspector, complaint.stall):
        abort(403)
    return complaint


@inspector_complaints_bp.route("/")
@login_required
@role_required("inspector")
def complaints():
    inspector = _current_inspector()
    status = request.args.get("status", "").strip()
    query = _complaints_query_for_inspector(inspector)
    if status in COMPLAINT_STATUSES:
        query = query.filter(Complaint.status == status)
    records = query.order_by(Complaint.submitted_at.desc()).all()
    return render_template(
        "inspector/complaints/list.html",
        inspector=inspector,
        complaints=records,
        selected_status=status,
    )


@inspector_complaints_bp.route("/<int:complaint_id>", methods=["GET", "POST"])
@login_required
@role_required("inspector")
def complaint_manage(complaint_id):
    inspector = _current_inspector()
    complaint = _get_complaint_in_scope(inspector, complaint_id)

    if request.method == "POST":
        status = request.form.get("status", "")
        if status not in COMPLAINT_STATUSES:
            flash("Select a valid complaint status.", "danger")
            return redirect(
                url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
            )
        current_status = complaint.status
        if status not in COMPLAINT_TRANSITIONS.get(current_status, set()):
            flash(
                f"Complaint cannot move from '{current_status}' to "
                f"'{status}' directly.",
                "danger",
            )
            return redirect(
                url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
            )

        if status == "resolved" and not any(
            item.uploader and item.uploader.role_name == "inspector"
            for item in complaint.evidence
        ):
            flash(
                "Attach your own inspection evidence before marking this "
                "complaint resolved.",
                "danger",
            )
            return redirect(
                url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
            )

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

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Complaint could not be updated.", "danger")
            return redirect(
                url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
            )

        flash("Complaint updated successfully.", "success")
        if status_changed:
            refresh_stall_risk(complaint.stall_id)
        if status_changed or response_changed:
            notify_complaint_update(complaint, status_changed, response_text)
        return redirect(
            url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
        )

    return render_template(
        "inspector/complaints/detail.html",
        inspector=inspector,
        complaint=complaint,
    )


@inspector_complaints_bp.route("/<int:complaint_id>/evidence", methods=["POST"])
@login_required
@role_required("inspector")
def complaint_evidence_upload(complaint_id):
    inspector = _current_inspector()
    complaint = _get_complaint_in_scope(inspector, complaint_id)

    evidence_files = [
        item for item in request.files.getlist("evidence") if item and item.filename
    ]
    if not evidence_files:
        flash("Select at least one evidence file to upload.", "danger")
        return redirect(
            url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
        )
    max_files = current_app.config.get("EVIDENCE_MAX_FILES_PER_COMPLAINT", 5)
    if len(evidence_files) > max_files:
        flash(
            f"You can attach at most {max_files} evidence files per "
            "complaint.",
            "danger",
        )
        return redirect(
            url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
        )

    # Unlike a student's submission (always PENDING until an admin/
    # inspector reviews it), evidence an inspector attaches here is their
    # own first-party proof of an on-site follow-up -- it's recorded as
    # already verified by them, not queued for someone else's review.
    saved_relative_paths = []
    now = datetime.now()
    try:
        for uploaded_file in evidence_files:
            metadata = validate_and_store_complaint_evidence(
                uploaded_file, complaint.complaint_id
            )
            saved_relative_paths.append(metadata["storage_path"])
            db.session.add(
                ComplaintEvidence(
                    complaint_id=complaint.complaint_id,
                    uploaded_by=current_user.user_id,
                    verification_status="verified",
                    verified_by=current_user.user_id,
                    verified_at=now,
                    **metadata,
                )
            )
        db.session.commit()
    except EvidenceValidationError as error:
        db.session.rollback()
        delete_stored_complaint_files(saved_relative_paths)
        flash(str(error), "danger")
        return redirect(
            url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
        )
    except SQLAlchemyError:
        db.session.rollback()
        delete_stored_complaint_files(saved_relative_paths)
        current_app.logger.exception(
            "Inspector evidence upload failed for complaint %s", complaint_id
        )
        flash("Evidence could not be uploaded. Please try again.", "danger")
        return redirect(
            url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
        )

    try:
        for evidence in complaint.evidence:
            if evidence.storage_path in saved_relative_paths:
                record_audit(evidence, current_user, "uploaded")
    except SQLAlchemyError:
        current_app.logger.exception(
            "Failed to write upload audit log for complaint %s", complaint_id
        )

    flash("Evidence uploaded.", "success")
    return redirect(
        url_for("inspector_complaints.complaint_manage", complaint_id=complaint_id)
    )


@inspector_complaints_bp.route("/evidence/<int:evidence_id>/status", methods=["POST"])
@login_required
@role_required("inspector")
def evidence_status(evidence_id):
    inspector = _current_inspector()
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    if not _in_inspector_scope(inspector, evidence.complaint.stall):
        abort(403)

    status = request.form.get("verification_status", "")
    if status not in EVIDENCE_VERIFICATION_STATUSES:
        flash("Select a valid evidence verification status.", "danger")
        return redirect(
            url_for(
                "inspector_complaints.complaint_manage",
                complaint_id=evidence.complaint_id,
            )
        )

    rejection_reason = request.form.get("rejection_reason", "").strip()
    if status == "rejected" and not rejection_reason:
        flash("A rejection reason is required to reject evidence.", "danger")
        return redirect(
            url_for(
                "inspector_complaints.complaint_manage",
                complaint_id=evidence.complaint_id,
            )
        )

    evidence.verification_status = status
    evidence.rejection_reason = rejection_reason if status == "rejected" else None
    if status in {"verified", "rejected"}:
        evidence.verified_by = current_user.user_id
        evidence.verified_at = datetime.now()
    else:
        evidence.verified_by = None
        evidence.verified_at = None

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Evidence status could not be updated.", "danger")
        return redirect(
            url_for(
                "inspector_complaints.complaint_manage",
                complaint_id=evidence.complaint_id,
            )
        )

    record_audit(
        evidence,
        current_user,
        EVIDENCE_ACTION_BY_STATUS[status],
        details=rejection_reason if status == "rejected" else None,
    )
    flash("Evidence status updated.", "success")
    return redirect(
        url_for("inspector_complaints.complaint_manage", complaint_id=evidence.complaint_id)
    )


@inspector_complaints_bp.route("/evidence/<int:evidence_id>")
@login_required
@role_required("inspector")
def evidence_download(evidence_id):
    inspector = _current_inspector()
    evidence = db.get_or_404(ComplaintEvidence, evidence_id)
    if not _in_inspector_scope(inspector, evidence.complaint.stall):
        abort(403)
    record_audit(evidence, current_user, "viewed")
    return serve_complaint_evidence(evidence)
