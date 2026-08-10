from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
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

        customer_role = Role.query.filter(
            func.lower(Role.role_name).in_(("customer", "consumer"))
        ).order_by(
            (func.lower(Role.role_name) == "customer").desc()
        ).first()
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
