from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*allowed_roles):
    normalized_roles = {role.lower() for role in allowed_roles}

    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            if current_user.role_name not in normalized_roles:
                abort(403)
            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator


def _is_admin_tier(user):
    return bool(user.role and user.role.is_admin_tier)


def admin_tier_required(view_function):
    """Any role marked is_admin_tier can enter the admin panel -- not
    just a user whose role_name is literally "admin"."""

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not _is_admin_tier(current_user):
            abort(403)
        return view_function(*args, **kwargs)

    return wrapped_view


def permission_required(*codes):
    """Admin-tier and holds at least one of the given permission codes
    (see models.User.has_permission). A super admin always passes."""

    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            if not _is_admin_tier(current_user):
                abort(403)
            if not any(current_user.has_permission(code) for code in codes):
                abort(403)
            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator


def super_admin_required(view_function):
    """Admin-tier and is_super_admin -- used only for the routes that
    manage roles and permissions themselves."""

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not (_is_admin_tier(current_user) and current_user.is_super_admin):
            abort(403)
        return view_function(*args, **kwargs)

    return wrapped_view
