from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from routes import admin_tier_required, role_required
from services.admin_dashboard import get_admin_dashboard_data


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _render_dashboard(role, title, description):
    return render_template(
        "dashboard.html",
        dashboard_role=role,
        dashboard_title=title,
        dashboard_description=description,
    )


@dashboard_bp.route("/admin")
@login_required
@admin_tier_required
def admin():
    data = get_admin_dashboard_data(current_user)
    return render_template(
        "admin/dashboard.html",
        page_title="Dashboard",
        **data,
    )


@dashboard_bp.route("/inspector")
@login_required
@role_required("inspector")
def inspector():
    return redirect(url_for("inspection_workflow.inspections"))


@dashboard_bp.route("/vendor")
@login_required
@role_required("vendor")
def vendor():
    return redirect(url_for("vendor_portal.dashboard"))


@dashboard_bp.route("/customer")
@login_required
@role_required("student")
def customer():
    return redirect(url_for("customer_portal.dashboard"))
