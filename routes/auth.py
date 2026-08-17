from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db, limiter, oauth
from models import Role, User
from services.account_classification import (
    classify_email,
    is_student_domain_email,
    is_valid_student_email,
    resolve_signup_role_name,
)
from services.auth_audit import record_auth_event
from services.email_verification import (
    VerificationTokenExpired,
    VerificationTokenInvalid,
    send_verification_email,
    verify_verification_token,
)
from services.turnstile import verify_turnstile


auth_bp = Blueprint("auth", __name__)


def _is_safe_redirect(target):
    if not target:
        return False
    # Reject backslashes and "//" up front: browsers normalize a leading
    # "\" or "//" to a scheme-relative URL, which urljoin/urlparse below
    # would otherwise resolve as same-host and let slip through.
    if "\\" in target or not target.startswith("/") or target.startswith("//"):
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return (
        redirect_url.scheme in {"http", "https"}
        and host_url.netloc == redirect_url.netloc
    )


def _dashboard_url(user):
    # Any admin-tier role (not just the literal "admin" role_name) lands
    # on the admin dashboard -- see routes/__init__.py:admin_tier_required.
    if user.role and user.role.is_admin_tier:
        return url_for("dashboard.admin")
    endpoint_by_role = {
        "inspector": "dashboard.inspector",
        "vendor": "dashboard.vendor",
        "customer": "dashboard.customer",
        "consumer": "dashboard.customer",
        # "student" is a classification of public user, not a separate
        # portal -- it shares the customer dashboard/routes.
        "student": "dashboard.customer",
    }
    endpoint = endpoint_by_role.get(user.role_name)
    if not endpoint:
        return url_for("home")
    return url_for(endpoint)


def _google_oauth_configured():
    return bool(
        current_app.config.get("GOOGLE_CLIENT_ID")
        and current_app.config.get("GOOGLE_CLIENT_SECRET")
    )


def _default_customer_role():
    return (
        Role.query.filter(func.lower(Role.role_name).in_(("customer", "consumer")))
        .order_by((func.lower(Role.role_name) == "customer").desc())
        .first()
    )


def _role_for_signup(email):
    """The only role a self-service signup (local register or Google
    OAuth) may ever receive, resolved purely from the email address --
    see services/account_classification.py. Never returns an admin,
    super-admin, or vendor role; vendor access is only ever activated
    later by an admin approving a dedicated application
    (routes/customer.py:vendor_application + routes/admin.py:
    vendor_approve), and admin/super-admin can only be granted through
    routes/admin.py's role management, never here.

    Falls back to the plain customer role if the resolved role_name
    (e.g. "student") doesn't exist in this database yet -- e.g. a
    database that hasn't had migration 011 applied -- so signup never
    hard-fails just because that role row is missing.
    """
    role_name, classification = resolve_signup_role_name(email)
    role = Role.query.filter(func.lower(Role.role_name) == role_name).first()
    if role is None:
        role = _default_customer_role()
    return role, classification


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_dashboard_url(current_user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        user = User.query.filter(
            func.lower(User.email) == email
        ).first()

        if user is None or not user.check_password(password):
            record_auth_event(
                "login_failed", email=email, auth_provider="local",
                details="invalid credentials",
            )
            db.session.commit()
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html"), 401

        if not user.is_active:
            record_auth_event(
                "login_failed", user=user, details="account not active"
            )
            db.session.commit()
            flash(
                "Your account is disabled. Please contact an administrator.",
                "danger",
            )
            return render_template("auth/login.html"), 403

        if user.auth_provider == "local" and not user.is_email_verified:
            flash(
                "Please verify your email address before logging in. "
                "Check your inbox for the verification link, or request "
                "a new one below.",
                "warning",
            )
            return render_template("auth/login.html"), 403

        if user.role_name == "student" and not is_valid_student_email(user.email):
            # Defense in depth: the student role can only ever be granted
            # at signup when the email matched the exact DIU ID pattern
            # (see _role_for_signup below), but the email itself can
            # later change via the profile page -- re-check it here so a
            # student account can never keep logging in against a
            # since-changed, non-matching email.
            flash(
                "This account's email no longer matches the required "
                "DIU student ID format. Please contact an administrator.",
                "danger",
            )
            return render_template("auth/login.html"), 403

        login_user(user, remember=remember)
        record_auth_event("login_success", user=user)
        db.session.commit()
        flash(f"Welcome back, {user.full_name}.", "success")

        next_url = request.args.get("next")
        if _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(_dashboard_url(user))

    return render_template("auth/login.html")


@auth_bp.route("/auth/google/login")
@limiter.limit("10 per minute")
def google_login():
    if current_user.is_authenticated:
        return redirect(_dashboard_url(current_user))

    if not _google_oauth_configured():
        flash("Google sign-in is not configured.", "danger")
        return redirect(url_for("auth.login"))

    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
@limiter.limit("10 per minute")
def google_callback():
    if not _google_oauth_configured():
        flash("Google sign-in is not configured.", "danger")
        return redirect(url_for("auth.login"))

    try:
        token = oauth.google.authorize_access_token()
    except OAuthError:
        # Never log the underlying OAuthError -- it can carry the raw
        # token exchange response. The audit trail only needs to know an
        # attempt failed, not why in token-level detail.
        record_auth_event(
            "login_failed", auth_provider="google", details="oauth exchange failed"
        )
        db.session.commit()
        flash("Google sign-in was cancelled or failed. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)
    google_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    full_name = userinfo.get("name") or (email.split("@")[0] if email else "")
    picture_url = userinfo.get("picture") or None

    if not google_id or not email or not userinfo.get("email_verified"):
        record_auth_event(
            "login_failed", email=email or None, auth_provider="google",
            details="unverified or missing google email",
        )
        db.session.commit()
        flash(
            "Could not verify your Google account email. Please try again "
            "or sign in with your email and password.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(google_id=google_id).first()
    created_account = False

    if user is None:
        user = User.query.filter(func.lower(User.email) == email).first()

        if user is not None:
            # Existing local (or previously-linked) account: link, never
            # duplicate, and never touch role_id here -- Google only
            # confirms identity, it can't move an existing account
            # between roles (that would let a plain user silently become
            # a vendor/admin just by re-authenticating with a different
            # inbox pattern). Only the classification tag is refreshed.
            user.google_id = google_id
            user.email_classification = classify_email(email)
            if user.email_verified_at is None:
                # Google already confirmed ownership of this inbox above.
                user.email_verified_at = datetime.now(timezone.utc)
        else:
            if is_student_domain_email(email) and not is_valid_student_email(email):
                # Same rule as local register(): a diu.edu.bd address
                # that doesn't match the exact ID format never creates
                # an account at all, Google or otherwise.
                record_auth_event(
                    "login_failed", email=email, auth_provider="google",
                    details="malformed diu student email",
                )
                db.session.commit()
                flash(
                    "DIU student Google accounts must use the exact ID "
                    "email format, e.g. 222-35-456@diu.edu.bd. Please "
                    "sign in with a different account.",
                    "danger",
                )
                return redirect(url_for("auth.login"))

            signup_role, classification = _role_for_signup(email)
            if signup_role is None:
                flash("Google sign-up is temporarily unavailable.", "danger")
                return redirect(url_for("auth.login"))

            user = User(
                role_id=signup_role.role_id,
                full_name=full_name or email,
                email=email,
                google_id=google_id,
                auth_provider="google",
                status="active",
                email_verified_at=datetime.now(timezone.utc),
                email_classification=classification,
                profile_photo_url=picture_url,
            )
            db.session.add(user)
            created_account = True

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Could not complete Google sign-in. Please try again.", "danger")
            return redirect(url_for("auth.login"))

        if created_account:
            record_auth_event(
                "account_created", user=user, auth_provider="google"
            )
            db.session.commit()

    if not user.is_active:
        record_auth_event(
            "login_failed", user=user, details="account not active"
        )
        db.session.commit()
        flash(
            "Your account is disabled. Please contact an administrator.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    if user.role_name == "student" and not is_valid_student_email(user.email):
        # Same defense-in-depth re-check as the local login() route.
        flash(
            "This account's email no longer matches the required DIU "
            "student ID format. Please contact an administrator.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    login_user(user)
    record_auth_event("login_success", user=user)
    db.session.commit()
    flash(f"Welcome, {user.full_name}.", "success")
    return redirect(_dashboard_url(user))


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(_dashboard_url(current_user))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip() or None
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        if not email or "@" not in email:
            errors.append("A valid email address is required.")
        if len(password) < 8:
            errors.append("Password must contain at least 8 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if User.query.filter(func.lower(User.email) == email).first():
            errors.append("An account with that email already exists.")
        if phone and User.query.filter_by(phone=phone).first():
            errors.append("An account with that phone number already exists.")
        if email and is_student_domain_email(email) and not is_valid_student_email(email):
            # A diu.edu.bd address that doesn't match the exact ID format
            # is rejected outright rather than silently falling back to
            # a plain customer account -- it's far more likely a typo or
            # a spoofing attempt than a legitimate different account.
            errors.append(
                "DIU student emails must use the exact ID format, e.g. "
                "222-35-456@diu.edu.bd, to register."
            )
        if not verify_turnstile(
            request.form.get("cf-turnstile-response"),
            remote_ip=request.remote_addr,
        ):
            errors.append("Bot verification failed. Please try again.")

        signup_role, classification = _role_for_signup(email)
        if signup_role is None:
            errors.append(
                "Registration is temporarily unavailable."
            )

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("auth/register.html"), 400

        user = User(
            role_id=signup_role.role_id,
            full_name=full_name,
            email=email,
            phone=phone,
            status="active",
            email_classification=classification,
        )
        user.set_password(password)
        db.session.add(user)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                "That email address or phone number is already registered.",
                "danger",
            )
            return render_template("auth/register.html"), 409

        record_auth_event("account_created", user=user, auth_provider="local")
        db.session.commit()

        result = send_verification_email(user)
        if result.sent:
            flash(
                "Registration successful. Check your email for a link to "
                "verify your account before logging in.",
                "success",
            )
        elif result.dev_link:
            # DEBUG-only fallback so localhost testing works without real
            # SMTP credentials configured yet. Never logged; shown only in
            # this response, to the person who just typed this address in.
            flash(
                "Registration successful. Email sending isn't configured "
                "yet, so here is your verification link for local testing: "
                + result.dev_link,
                "warning",
            )
        else:
            flash(
                "Registration successful, but we could not send a "
                "verification email right now. Use \"Resend verification "
                "email\" on the login page once you're ready to try again.",
                "warning",
            )
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    if current_user.is_authenticated:
        return redirect(_dashboard_url(current_user))

    try:
        user_id = verify_verification_token(token)
    except VerificationTokenExpired:
        flash("This verification link has expired.", "danger")
        return redirect(url_for("auth.resend_verification"))
    except VerificationTokenInvalid:
        flash(
            "This verification link is invalid or has already been used.",
            "danger",
        )
        return redirect(url_for("auth.resend_verification"))

    user = db.session.get(User, user_id)

    # A signature can verify successfully yet still be "used up": once
    # email_verified_at is set, the same link must not work a second time.
    if user is None or user.email_verified_at is not None:
        flash(
            "This verification link is invalid or has already been used.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    user.email_verified_at = datetime.now(timezone.utc)
    db.session.commit()

    flash("Your email has been verified. You can now log in.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/resend-verification", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def resend_verification():
    if current_user.is_authenticated:
        return redirect(_dashboard_url(current_user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()

        if (
            user is not None
            and user.auth_provider == "local"
            and user.email_verified_at is None
        ):
            send_verification_email(user)

        # Same message regardless of outcome, so this endpoint can't be
        # used to check which email addresses are registered.
        flash(
            "If that email address is registered and not yet verified, "
            "a new verification link has been sent.",
            "info",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/resend_verification.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    record_auth_event("logout", user=current_user)
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/dashboard")
@login_required
def dashboard_redirect():
    return redirect(_dashboard_url(current_user))
