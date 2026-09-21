"""Admin -> applicant messages for vendor requests.

An admin reviewing a vendor sign-up or application can send an *inquiry*
("please add your licence number", "which gate is the stall at?"). It is
stored as an ordinary in-app notification for the applicant (shown on their
Become a Vendor page, since an applicant is confined to that page -- see
routes/customer.py:_keep_vendor_applicants_on_their_application) and, when
SMTP is configured, also emailed. No new table or column.
"""

from flask import current_app
from flask_mail import Message
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, mail
from models import Notification

MESSAGE_PREFIX = "Vendor review team: "
# notifications.message is VARCHAR(255); leave room for the prefix.
INQUIRY_MAX_LENGTH = 255 - len(MESSAGE_PREFIX)


def send_vendor_inquiry(applicant, sender, text):
    """Record the inquiry for `applicant` and email it if mail is set up.

    Returns (saved, emailed). `saved` False means the database write failed
    (nothing was sent); `emailed` is best-effort and never affects `saved`.
    """
    try:
        db.session.add(
            Notification(
                user_id=applicant.user_id,
                message=f"{MESSAGE_PREFIX}{text}"[:255],
            )
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to record vendor inquiry for user %s", applicant.user_id
        )
        return False, False

    if not current_app.config.get("MAIL_SERVER"):
        return True, False
    try:
        mail.send(
            Message(
                subject="A question about your vendor request",
                recipients=[applicant.email],
                body=(
                    f"Hi {applicant.full_name},\n\n"
                    "The DIU Food Safety team has a question about your vendor "
                    "request:\n\n"
                    f"{text}\n\n"
                    "Sign in and open \"Become a Vendor\" to update your "
                    "details."
                ),
            )
        )
    except Exception:
        current_app.logger.exception(
            "Failed to email vendor inquiry to %s", applicant.email
        )
        return True, False
    return True, True
