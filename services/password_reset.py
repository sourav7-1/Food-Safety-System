import hashlib
from collections import namedtuple

from flask import current_app, url_for
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import mail


_SALT = "password-reset"

EmailSendResult = namedtuple("EmailSendResult", ["sent", "dev_link"])


class ResetTokenExpired(Exception):
    """The token's signature is valid but PASSWORD_RESET_MAX_AGE_SECONDS has passed."""


class ResetTokenInvalid(Exception):
    """The token is malformed, tampered with, signed with a different key,
    or was already used (the password has changed since it was issued)."""


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _password_fingerprint(user):
    """A one-way, non-reversible digest of the user's current password
    hash. Included in the signed token so that once the password
    actually changes (either via this same reset link, or via the
    logged-in change-password form), the fingerprint no longer matches
    and every previously issued reset link for this user is
    automatically invalidated -- without needing a database column or
    row to track single-use state. The raw password_hash itself is
    never embedded: itsdangerous signs the token, it does not encrypt
    it, so anything placed in the payload is readable by whoever holds
    the link.
    """
    raw = f"{current_app.config['SECRET_KEY']}:{user.password_hash or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def generate_reset_token(user):
    return _serializer().dumps(
        {"uid": user.user_id, "pf": _password_fingerprint(user)}, salt=_SALT
    )


def decode_reset_token(token):
    """Verify `token`'s signature and age, returning its (user_id,
    fingerprint) payload. Raises ResetTokenExpired or ResetTokenInvalid
    instead of returning a bare False, so callers can show the right
    message without inspecting itsdangerous internals.

    This only proves the token was issued by this app and hasn't
    expired -- it does NOT prove the token is still unused. Callers
    must look the user up by the returned user_id and compare the
    returned fingerprint against `_password_fingerprint(user)`
    themselves (see routes/auth.py:reset_password); that comparison is
    what makes a token single-use, since it stops matching the moment
    the password actually changes.
    """
    max_age = current_app.config.get("PASSWORD_RESET_MAX_AGE_SECONDS", 3600)
    try:
        payload = _serializer().loads(token, salt=_SALT, max_age=max_age)
    except SignatureExpired:
        raise ResetTokenExpired() from None
    except BadSignature:
        raise ResetTokenInvalid() from None

    if not isinstance(payload, dict) or "uid" not in payload or "pf" not in payload:
        raise ResetTokenInvalid()

    return payload["uid"], payload["pf"]


def reset_token_matches_user(fingerprint, user):
    return fingerprint == _password_fingerprint(user)


def send_password_reset_email(user):
    """Email a password-reset link to the user.

    Returns an EmailSendResult. `dev_link` is only ever populated when
    DEBUG is on and delivery didn't happen, so a developer testing on
    localhost without SMTP configured can still complete the flow -- the
    link is handed back to that same request/response, never written to
    logs (which may be shared/aggregated) or to any other user's session.
    """
    token = generate_reset_token(user)
    link = url_for("auth.reset_password", token=token, _external=True)
    dev_link = link if current_app.debug else None

    if not current_app.config.get("MAIL_SERVER"):
        current_app.logger.warning(
            "MAIL_SERVER is not configured; password reset email not sent to %s",
            user.email,
        )
        return EmailSendResult(sent=False, dev_link=dev_link)

    message = Message(
        subject="Reset your Smart Street Food Safety password",
        recipients=[user.email],
        body=(
            f"Hi {user.full_name},\n\n"
            "We received a request to reset your password. Click the "
            "link below to choose a new one:\n"
            f"{link}\n\n"
            "This link expires in "
            f"{current_app.config.get('PASSWORD_RESET_MAX_AGE_SECONDS', 3600) // 60} "
            "minutes and can only be used once. If you did not request "
            "this, you can safely ignore this email -- your password "
            "will not be changed."
        ),
    )

    try:
        mail.send(message)
    except Exception:
        current_app.logger.exception(
            "Failed to send password reset email to %s", user.email
        )
        return EmailSendResult(sent=False, dev_link=dev_link)

    return EmailSendResult(sent=True, dev_link=None)
