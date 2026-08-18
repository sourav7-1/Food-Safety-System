from datetime import date, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import Area, AuthAuditLog, Complaint, Review, User, Notification
from services.account_classification import is_valid_student_email
from services.email_verification import send_verification_email
from services.profile_photo import (
    ProfilePhotoValidationError,
    delete_profile_photo,
    save_profile_photo,
)


profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


@profile_bp.context_processor
def _inject_unread_notification_count():
    if not current_user.is_authenticated:
        return {"unread_notification_count": 0}
    count = Notification.query.filter_by(
        user_id=current_user.user_id, is_read=False
    ).count()
    return {"unread_notification_count": count}


_MIN_PASSWORD_LENGTH = 8


@profile_bp.route("")
@login_required
def view():
    reviews = complaints = None
    if current_user.role_name in ("customer", "consumer", "student"):
        reviews = (
            Review.query.filter_by(user_id=current_user.user_id)
            .order_by(Review.created_at.desc())
            .all()
        )
        complaints = (
            Complaint.query.filter_by(submitted_by_user_id=current_user.user_id)
            .order_by(Complaint.submitted_at.desc())
            .all()
        )
    # Admin-tier users (including custom admin-tier roles) get the profile
    # page rendered inside the admin sidebar/topbar shell instead of the
    # plain public shell, so it doesn't look like they've left the admin
    # panel entirely.
    is_admin_tier = bool(current_user.role and current_user.role.is_admin_tier)
    recent_logins = (
        AuthAuditLog.query.filter_by(user_id=current_user.user_id)
        .order_by(AuthAuditLog.audit_id.desc())
        .limit(10)
        .all()
    )
    if is_admin_tier:
        template_name = "profile/view_admin.html"
    elif current_user.role_name in ("customer", "consumer", "student"):
        template_name = "profile/view_student.html"
    elif current_user.role_name == "vendor":
        template_name = "profile/view_vendor.html"
    elif current_user.role_name == "inspector":
        template_name = "profile/view_inspector.html"
    else:
        template_name = "profile/view_default.html"

    return render_template(
        template_name,
        areas=Area.query.order_by(Area.area_name).all(),
        reviews=reviews,
        complaints=complaints,
        recent_logins=recent_logins,
        today=date.today(),
        page_title="My Profile",
    )


@profile_bp.route("/edit", methods=["POST"])
@login_required
def edit():
    full_name = request.form.get("full_name", "").strip()
    bio = request.form.get("bio", "").strip() or None
    address = request.form.get("address", "").strip() or None
    dob_raw = request.form.get("date_of_birth", "").strip()
    preferred_area_id = request.form.get("preferred_area_id", type=int)
    new_email = request.form.get("email", "").strip().lower()
    new_phone = request.form.get("phone", "").strip() or None
    current_password = request.form.get("current_password", "")

    errors = []
    if not full_name:
        errors.append("Full name is required.")

    date_of_birth = None
    if dob_raw:
        try:
            date_of_birth = datetime.strptime(dob_raw, "%Y-%m-%d").date()
        except ValueError:
            errors.append("Date of birth is not a valid date.")
        else:
            if date_of_birth > date.today():
                errors.append("Date of birth cannot be in the future.")

    if preferred_area_id and db.session.get(Area, preferred_area_id) is None:
        errors.append("Selected preferred area does not exist.")
        preferred_area_id = None

    email_changed = bool(new_email) and new_email != (current_user.email or "").lower()
    phone_changed = new_phone != (current_user.phone or None)

    if email_changed or phone_changed:
        if not current_password:
            errors.append(
                "Enter your current password to change your email or phone "
                "number."
            )
        elif not current_user.check_password(current_password):
            errors.append("Current password is incorrect.")

    if email_changed:
        if "@" not in new_email:
            errors.append("A valid email address is required.")
        elif User.query.filter(
            func.lower(User.email) == new_email,
            User.user_id != current_user.user_id,
        ).first():
            errors.append("That email address is already in use.")
        elif (
            current_user.role_name == "student"
            and not is_valid_student_email(new_email)
        ):
            # Prevents the exact drift the login-time re-check in
            # routes/auth.py guards against: a student account's email
            # is never allowed to move away from the exact DIU ID
            # format while it still holds the student role.
            errors.append(
                "Your account has the student role, so its email must "
                "stay in the exact DIU ID format, e.g. "
                "222-35-456@diu.edu.bd."
            )

    if phone_changed and new_phone:
        if User.query.filter(
            User.phone == new_phone,
            User.user_id != current_user.user_id,
        ).first():
            errors.append("That phone number is already in use.")

    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("profile.view"))

    current_user.full_name = full_name
    current_user.bio = bio
    current_user.address = address
    current_user.date_of_birth = date_of_birth
    current_user.preferred_area_id = preferred_area_id
    if phone_changed:
        current_user.phone = new_phone

    reverify_email = False
    if email_changed:
        current_user.email = new_email
        if current_user.auth_provider == "local":
            # The email-verification requirement introduced for
            # registration applies equally here: nobody should be able to
            # log in against an inbox they haven't proven they own.
            current_user.email_verified_at = None
            reverify_email = True

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That email address or phone number is already in use.", "danger")
        return redirect(url_for("profile.view"))

    if reverify_email:
        result = send_verification_email(current_user)
        if result.sent:
            flash(
                "Profile updated. Your email address changed, so check "
                "your new inbox for a link to verify it before you next "
                "log in.",
                "warning",
            )
        elif result.dev_link:
            flash(
                "Profile updated. Email sending isn't configured yet, so "
                "here is your verification link for local testing: "
                + result.dev_link,
                "warning",
            )
        else:
            flash(
                "Profile updated, but we could not send a verification "
                "email for your new address. Use \"Resend verification "
                "email\" on the login page before you next log in.",
                "warning",
            )
    else:
        flash("Profile updated.", "success")
    return redirect(url_for("profile.view"))


@profile_bp.route("/photo", methods=["POST"])
@login_required
def upload_photo():
    try:
        new_url = save_profile_photo(request.files.get("photo"))
    except ProfilePhotoValidationError as error:
        flash(str(error), "danger")
        return redirect(url_for("profile.view"))

    old_url = current_user.profile_photo_url
    current_user.profile_photo_url = new_url
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        delete_profile_photo(new_url)
        current_app.logger.exception("Failed to save profile photo")
        flash("Profile photo could not be saved. Please try again.", "danger")
        return redirect(url_for("profile.view"))

    delete_profile_photo(old_url)
    flash("Profile photo updated.", "success")
    return redirect(url_for("profile.view"))


@profile_bp.route("/photo/remove", methods=["POST"])
@login_required
def remove_photo():
    old_url = current_user.profile_photo_url
    if old_url:
        current_user.profile_photo_url = None
        db.session.commit()
        delete_profile_photo(old_url)
        flash("Profile photo removed.", "success")
    return redirect(url_for("profile.view"))


@profile_bp.route("/password", methods=["POST"])
@login_required
def change_password():
    if not current_user.password_hash:
        flash(
            "Your account signs in with Google and has no password to "
            "change.",
            "warning",
        )
        return redirect(url_for("profile.view"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("profile.view"))
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        flash(
            f"New password must contain at least {_MIN_PASSWORD_LENGTH} "
            "characters.",
            "danger",
        )
        return redirect(url_for("profile.view"))
    if new_password != confirm_password:
        flash("New password and confirmation do not match.", "danger")
        return redirect(url_for("profile.view"))
    if current_user.check_password(new_password):
        flash(
            "New password must be different from your current password.",
            "danger",
        )
        return redirect(url_for("profile.view"))

    current_user.set_password(new_password)
    db.session.commit()
    flash("Password changed.", "success")
    return redirect(url_for("profile.view"))
