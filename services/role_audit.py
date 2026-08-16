from extensions import db
from models import RoleAuditLog


def record_role_change(actor, target_user, old_role_id, new_role_id, reason):
    """Append-only audit trail for role changes -- who changed whose role,
    from what to what, and why. Call this in the same transaction as the
    role_id write, before commit; never fails the caller's request if the
    write itself fails (logged instead), since the role change already
    succeeding is the important outcome."""
    if old_role_id == new_role_id:
        return
    db.session.add(
        RoleAuditLog(
            target_user_id=target_user.user_id,
            actor_user_id=actor.user_id if actor else None,
            old_role_id=old_role_id,
            new_role_id=new_role_id,
            reason=reason[:255] if reason else None,
        )
    )
