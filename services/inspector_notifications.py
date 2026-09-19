"""In-app notifications for inspectors -- who hears about what.

Same best-effort contract as services/complaints.py:notify_complaint_update:
these run *after* the triggering action (a complaint or dispute) has already
committed, so a notification write failure is logged, never surfaced to the
student/vendor who caused it.

Uses the existing `notifications` table as-is (user_id, complaint_id,
message, is_read) -- no new columns. A notification with a complaint_id is a
complaint alert; one without is a general inspection update (currently: a
vendor disputing one of the inspector's inspections).
"""

from flask import current_app
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Inspector, Notification


def _inspectors_covering_area(area_id):
    """Inspectors assigned to `area_id`, plus inspectors with no assigned area
    (they see every area -- same convention routes/inspector.py uses for
    inspection creation and the complaints list)."""
    return Inspector.query.filter(
        or_(
            Inspector.assigned_area_id.is_(None),
            Inspector.assigned_area_id == area_id,
        )
    ).all()


def _add_and_commit(notifications, log_context):
    if not notifications:
        return
    try:
        db.session.add_all(notifications)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to create inspector notification(s) for %s", log_context
        )


def notify_inspectors_of_new_complaint(complaint):
    """A student filed a complaint -- tell every inspector who covers that
    stall's area."""
    stall = complaint.stall
    inspectors = _inspectors_covering_area(stall.area_id)
    message = (
        f'New complaint "{complaint.title}" reported against '
        f"{stall.stall_name} ({stall.stall_code})."
    )
    _add_and_commit(
        [
            Notification(
                user_id=inspector.user_id,
                complaint_id=complaint.complaint_id,
                message=message[:255],
            )
            for inspector in inspectors
        ],
        f"complaint {complaint.complaint_id}",
    )


def notify_inspector_of_dispute(dispute):
    """A vendor disputed an inspection -- tell the inspector who carried it
    out."""
    inspection = dispute.inspection
    inspector = inspection.inspector
    if inspector is None:
        return
    stall = inspection.stall
    business = dispute.vendor.business_name if dispute.vendor else "The vendor"
    message = (
        f"{business} disputed your "
        f"{inspection.inspection_date.strftime('%d %b %Y')} inspection of "
        f'{stall.stall_name}: "{dispute.reason[:120]}"'
    )
    _add_and_commit(
        [Notification(user_id=inspector.user_id, message=message[:255])],
        f"dispute {dispute.dispute_id}",
    )
