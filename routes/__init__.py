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
