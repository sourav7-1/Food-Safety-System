from flask import request

from extensions import db
from models import AuthAuditLog


def record_auth_event(event, user=None, email=None, auth_provider=None, details=None):
    """Append-only audit trail for authentication/account-lifecycle
    events (login success/failure, logout, account creation, account
    suspension). Call this in the same transaction as any related write,
    before commit; never raises, since the auth flow succeeding or
    failing on its own terms is what matters -- audit logging is
    best-effort and must never be why a login breaks.

    Never pass OAuth tokens, passwords, or client secrets in `details`.
    """
    try:
        db.session.add(
            AuthAuditLog(
                user_id=user.user_id if user else None,
                email_attempted=(email or (user.email if user else None) or "")[:150] or None,
                event=event,
                auth_provider=auth_provider or (user.auth_provider if user else None),
                ip_address=(request.remote_addr or "")[:45] or None,
                user_agent=(request.headers.get("User-Agent") or "")[:255] or None,
                details=details[:255] if details else None,
            )
        )
    except RuntimeError:
        # No request context (e.g. called from a CLI command) -- skip
        # the IP/user-agent capture rather than failing the caller.
        pass
