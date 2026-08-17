from datetime import datetime, timezone

from extensions import db
from models import Role, RoleRequest
from services.auth_audit import record_auth_event
from services.role_audit import record_role_change


class RoleRequestError(Exception):
    """Raised for a request that fails validation before any write --
    the caller is expected to flash str(error) and re-render, same as
    every other form-handling route in this project."""


def create_role_request(user, requested_role, reason):
    if requested_role not in ("inspector", "admin"):
        raise RoleRequestError("Select a valid role to request.")
    if user.role_name == requested_role:
        raise RoleRequestError(f"Your account already has the {requested_role} role.")
    if (
        RoleRequest.query.filter_by(
            user_id=user.user_id, requested_role=requested_role, status="pending"
        ).first()
        is not None
    ):
        raise RoleRequestError(
            f"You already have a pending {requested_role} request."
        )

    role_request = RoleRequest(
        user_id=user.user_id,
        requested_role=requested_role,
        reason=(reason or "").strip()[:500] or None,
    )
    db.session.add(role_request)
    db.session.flush()
    record_auth_event(
        "role_requested", user=user, details=f"Requested {requested_role} access"
    )
    db.session.commit()
    return role_request


def approve_role_request(role_request, actor, inspector_form=None):
    """Grants the requested role in a single transaction: the
    role_requests row, the user's role_id, the linked Inspector profile
    (if applicable), and both audit trails are all written together and
    committed once -- if anything fails, nothing about this approval is
    left half-applied.

    Raises RoleRequestError for validation failures (e.g. missing
    Inspector employee code); the caller flashes str(error) and
    re-renders, same as the rest of the admin panel.
    """
    if role_request.status != "pending":
        raise RoleRequestError("This request has already been reviewed.")

    role = Role.query.filter_by(role_name=role_request.requested_role).first()
    if role is None:
        raise RoleRequestError(
            f"The {role_request.requested_role} role does not exist in this "
            "database."
        )

    user = role_request.user
    old_role_id = user.role_id

    if role_request.requested_role == "inspector":
        # Reuses the exact same validation/creation logic the admin
        # Users panel already uses for inspector transitions, so an
        # inspector approved here is indistinguishable from one created
        # directly by an admin.
        from routes.admin import _apply_inspector_transition

        error = _apply_inspector_transition(user, role, inspector_form or {})
        if error:
            raise RoleRequestError(error)

    user.role_id = role.role_id
    record_role_change(
        actor, user, old_role_id, role.role_id,
        f"Approved via role request #{role_request.request_id}",
    )

    role_request.status = "approved"
    role_request.reviewed_by = actor.user_id
    role_request.reviewed_at = datetime.now(timezone.utc)

    record_auth_event(
        "role_approved", user=user,
        details=f"{role_request.requested_role} approved by {actor.email}",
    )

    db.session.commit()
    return role_request


def reject_role_request(role_request, actor, rejection_reason):
    if role_request.status != "pending":
        raise RoleRequestError("This request has already been reviewed.")

    role_request.status = "rejected"
    role_request.reviewed_by = actor.user_id
    role_request.reviewed_at = datetime.now(timezone.utc)
    role_request.rejection_reason = (rejection_reason or "").strip()[:500] or None

    record_auth_event(
        "role_rejected", user=role_request.user,
        details=f"{role_request.requested_role} rejected by {actor.email}",
    )

    db.session.commit()
    return role_request
