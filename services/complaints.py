"""Complaint status/evidence constants and side-effects shared by every
portal that can act on a complaint (currently routes/admin.py and
routes/inspector.py) -- kept in one place so both stay in lockstep on
what transitions are legal and what happens when one fires."""

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Inspection, Notification


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


def notify_complaint_update(complaint, status_changed, response_text):
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


def refresh_stall_risk(stall_id):
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
