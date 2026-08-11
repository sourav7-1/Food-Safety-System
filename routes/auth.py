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

from extensions import db, oauth
from models import Role, User


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
    endpoint_by_role = {
        "admin": "dashboard.admin",
        "inspector": "dashboard.inspector",
        "vendor": "dashboard.vendor",
        "customer": "dashboard.customer",
        "consumer": "dashboard.customer",
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


@auth_bp.route("/login", methods=["GET", "POST"])
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
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html"), 401

        if not user.is_active:
            flash(
                "Your account is disabled. Please contact an administrator.",
                "danger",
            )
            return render_template("auth/login.html"), 403

        login_user(user, remember=remember)
        flash(f"Welcome back, {user.full_name}.", "success")

        next_url = request.args.get("next")
        if _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(_dashboard_url(user))

    return render_template("auth/login.html")


@auth_bp.route("/auth/google/login")
def google_login():
    if current_user.is_authenticated:
        return redirect(_dashboard_url(current_user))

    if not _google_oauth_configured():
        flash("Google sign-in is not configured.", "danger")
        return redirect(url_for("auth.login"))

    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    if not _google_oauth_configured():
        flash("Google sign-in is not configured.", "danger")
        return redirect(url_for("auth.login"))

    try:
        token = oauth.google.authorize_access_token()
    except OAuthError:
        flash("Google sign-in was cancelled or failed. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)
    google_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    full_name = userinfo.get("name") or (email.split("@")[0] if email else "")

    if not google_id or not email or not userinfo.get("email_verified"):
        flash(
            "Could not verify your Google account email. Please try again "
            "or sign in with your email and password.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(google_id=google_id).first()

    if user is None:
        user = User.query.filter(func.lower(User.email) == email).first()

        if user is not None:
            # Existing local (or previously-linked) account: link, never duplicate.
            user.google_id = google_id
        else:
            customer_role = _default_customer_role()
            if customer_role is None:
                flash("Google sign-up is temporarily unavailable.", "danger")
                return redirect(url_for("auth.login"))

            user = User(
                role_id=customer_role.role_id,
                full_name=full_name or email,
                email=email,
                google_id=google_id,
                auth_provider="google",
                status="active",
            )
            db.session.add(user)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Could not complete Google sign-in. Please try again.", "danger")
            return redirect(url_for("auth.login"))

    if not user.is_active:
        flash(
            "Your account is disabled. Please contact an administrator.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    login_user(user)
    flash(f"Welcome, {user.full_name}.", "success")
    return redirect(_dashboard_url(user))


@auth_bp.route("/register", methods=["GET", "POST"])
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

        customer_role = _default_customer_role()
        if customer_role is None:
            errors.append(
                "Customer registration is temporarily unavailable."
            )

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("auth/register.html"), 400

        user = User(
            role_id=customer_role.role_id,
            full_name=full_name,
            email=email,
            phone=phone,
            status="active",
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

        flash("Registration successful. You can now log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/dashboard")
@login_required
def dashboard_redirect():
    return redirect(_dashboard_url(current_user))
