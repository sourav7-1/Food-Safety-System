import hmac
import secrets

import click
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    
)
from flask_login import current_user, logout_user

from config import Config
from extensions import db, limiter, login_manager, mail, oauth


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "warning"

    mail.init_app(app)
    limiter.init_app(app)

    oauth.init_app(app)
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    @login_manager.user_loader
    def load_user(user_id):
        from models import User

        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.dashboard import dashboard_bp
    from routes.inspector import inspector_bp
    from routes.customer import customer_bp
    from routes.profile import profile_bp
    from routes.reports import reports_bp
    from routes.vendor import vendor_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inspector_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(vendor_bp)

    def csrf_token():
        token = session.get("_csrf_token")
        if token is None:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def enforce_session_security():
        if request.method == "POST":
            expected_token = session.get("_csrf_token", "")
            submitted_token = request.form.get("_csrf_token", "")
            if not expected_token or not hmac.compare_digest(
                expected_token, submitted_token
            ):
                abort(400, description="Invalid or missing CSRF token.")

        if (
            current_user.is_authenticated
            and not current_user.is_active
            and request.endpoint != "auth.logout"
        ):
            logout_user()
            flash(
                "Your account is disabled. Please contact an administrator.",
                "danger",
            )
            return redirect(url_for("auth.login"))

    @app.route("/")
    def home():
        from sqlalchemy import func

        from models import Area, CorrectiveAction, Inspection, Vendor

        stats = {
            "vendors": Vendor.query.count(),
            "inspections": Inspection.query.count(),
            "risk_alerts_resolved": CorrectiveAction.query.filter_by(
                status="completed"
            ).count(),
            "cities": db.session.query(
                func.count(func.distinct(Area.city))
            ).scalar()
            or 0,
        }
        return render_template("home.html", stats=stats)

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--email", prompt="Email address")
    @click.option(
        "--password",
        prompt="Password (input is hidden; minimum 8 characters)",
        hide_input=True,
        confirmation_prompt=True,
    )
    def create_admin(name, email, password):
        """Create the first active administrator account."""
        from datetime import datetime, timezone

        from models import Role, User

        normalized_email = email.strip().lower()
        if len(password) < 8:
            raise click.ClickException(
                "Password must contain at least 8 characters."
            )
        if User.query.filter_by(email=normalized_email).first():
            raise click.ClickException("That email is already registered.")

        admin_role = Role.query.filter_by(role_name="admin").first()
        if admin_role is None:
            admin_role = Role(
                role_name="admin",
                description="System administrators",
                is_system=True,
                is_admin_tier=True,
            )
            db.session.add(admin_role)
            db.session.flush()

        user = User(
            role_id=admin_role.role_id,
            full_name=name.strip(),
            email=normalized_email,
            status="active",
            # Created via trusted CLI access, not public registration, so
            # it does not need to go through email verification.
            email_verified_at=datetime.now(timezone.utc),
            # The CLI-created bootstrap admin is always a super admin, so
            # a fresh install has one usable account that can configure
            # roles and permissions from the start.
            is_super_admin=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrator created: {normalized_email}")

    @app.cli.command("init-db")
    def init_db():
        """Create missing tables and install MySQL routines safely."""
        from services.database_setup import initialize_database

        initialize_database()
        click.echo(
            "Database initialized without deleting existing application data."
        )

    @app.cli.command("import-stalls")
    @click.argument(
        "zip_path",
        type=click.Path(exists=True, dir_okay=False, path_type=str),
    )
    def import_stalls(zip_path):
        """Import a Google Forms registration CSV ZIP without duplicates."""
        from services.database_setup import initialize_database
        from services.registration_import import import_registration_zip

        initialize_database()
        created, skipped = import_registration_zip(zip_path)
        click.echo(
            f"Imported {created} registration(s); skipped {skipped} duplicate(s)."
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False))
