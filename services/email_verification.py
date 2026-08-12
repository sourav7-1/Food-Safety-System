from collections import namedtuple

from flask import current_app, url_for
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import mail


_SALT = "email-verification"

EmailSendResult = namedtuple("EmailSendResult", ["sent", "dev_link"])


class VerificationTokenExpired(Exception):
    """The token's signature is valid but EMAIL_VERIFICATION_MAX_AGE has passed."""


class VerificationTokenInvalid(Exception):
    """The token is malformed, tampered with, or was signed with a different key/salt."""


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_verification_token(user):
    return _serializer().dumps(user.user_id, salt=_SALT)


def verify_verification_token(token):
    """Return the encoded user_id.

    Raises VerificationTokenExpired or VerificationTokenInvalid instead of
    returning None, so callers can show the right message ("expired" vs.
    "invalid or already used") without inspecting itsdangerous internals.
    Note this only checks the signature/age; single-use enforcement lives
    in the caller (it checks whether the user is already verified), since
    this token is stateless and nothing about it is stored server-side.
    """
    max_age = current_app.config.get("EMAIL_VERIFICATION_MAX_AGE", 86400)
    try:
        return _serializer().loads(token, salt=_SALT, max_age=max_age)
    except SignatureExpired:
        raise VerificationTokenExpired() from None
    except BadSignature:
        raise VerificationTokenInvalid() from None


def send_verification_email(user):
    """Email a verification link to the user.

    Returns an EmailSendResult. `dev_link` is only ever populated when
    DEBUG is on and delivery didn't happen, so a developer testing on
    localhost without SMTP configured can still complete the flow -- the
    link is handed back to that same request/response, never written to
    logs (which may be shared/aggregated) or to any other user's session.
    """
    token = generate_verification_token(user)
    link = url_for("auth.verify_email", token=token, _external=True)
    dev_link = link if current_app.debug else None

    if not current_app.config.get("MAIL_SERVER"):
        current_app.logger.warning(
            "MAIL_SERVER is not configured; verification email not sent to %s",
            user.email,
        )
        return EmailSendResult(sent=False, dev_link=dev_link)

    message = Message(
        subject="Verify your Smart Street Food Safety account",
        recipients=[user.email],
        body=(
            f"Hi {user.full_name},\n\n"
            "Please verify your email address to activate your account:\n"
            f"{link}\n\n"
            "This link expires in 24 hours. If you did not create this "
            "account, you can ignore this email."
        ),
    )

    try:
        mail.send(message)
    except Exception:
        current_app.logger.exception(
            "Failed to send verification email to %s", user.email
        )
        return EmailSendResult(sent=False, dev_link=dev_link)

    return EmailSendResult(sent=True, dev_link=None)
