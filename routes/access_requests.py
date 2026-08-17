from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import limiter
from models import RoleRequest
from services.role_requests import RoleRequestError, create_role_request


access_requests_bp = Blueprint("access_requests", __name__, url_prefix="/access-requests")


@access_requests_bp.route("", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per hour", methods=["POST"])
def view():
    if request.method == "POST":
        requested_role = request.form.get("requested_role", "").strip().lower()
        reason = request.form.get("reason", "")
        try:
            create_role_request(current_user, requested_role, reason)
        except RoleRequestError as error:
            flash(str(error), "danger")
        else:
            flash(
                "Request submitted. A Super Admin will review it -- your "
                "account stays as-is until then.",
                "success",
            )
        return redirect(url_for("access_requests.view"))

    requests = (
        RoleRequest.query.filter_by(user_id=current_user.user_id)
        .order_by(RoleRequest.request_id.desc())
        .all()
    )
    is_admin_tier = bool(current_user.role and current_user.role.is_admin_tier)
    return render_template(
        "access_requests/view.html",
        requests=requests,
        base_template="admin/base.html" if is_admin_tier else "base.html",
        page_title="Request Access",
    )
