"""Email-based account classification for self-service signup (local
register and Google OAuth).

This module is pure and stateless -- it never touches the database and
never grants a role by itself. MySQL (the roles table + explicit admin
actions in routes/admin.py) remains the only source of authorization.
Google (or a locally-typed email address) only ever tells us who someone
claims to be; what they're allowed to do is decided here from the email
string alone, then enforced by the roles table.
"""

import re

# Exact, anchored -- \Z (not $) so a trailing newline can't smuggle a
# non-matching suffix past the pattern. Deliberately strict: no partial
# match, no "contains", no case games (email is lowercased by callers
# before this ever runs).
STUDENT_EMAIL_PATTERN = re.compile(r"^[0-9]{3}-[0-9]{2}-[0-9]{3}@diu\.edu\.bd\Z")

OFFICIAL_DIU_DOMAIN = "daffodilvariversity.edu.bd"

STUDENT = "student"
OFFICIAL_DIU = "official_diu"
EXTERNAL = "external"


def classify_email(email):
    """Classify a normalized (lowercased, stripped) email address.

    Returns one of STUDENT / OFFICIAL_DIU / EXTERNAL. Never returns
    anything that implies admin, super admin, or vendor -- those are
    never derived from an email address.
    """
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized:
        return EXTERNAL

    if STUDENT_EMAIL_PATTERN.match(normalized):
        return STUDENT

    # Split on '@' and compare the FULL domain string -- never a
    # substring/"in" check, which would wrongly accept a domain like
    # "fake-daffodilvariversity.edu.bd" or
    # "daffodilvariversity.edu.bd.attacker.com".
    domain = normalized.rsplit("@", 1)[-1]
    if domain == OFFICIAL_DIU_DOMAIN:
        return OFFICIAL_DIU

    return EXTERNAL


def resolve_signup_role_name(email):
    """The only role name a self-service signup (local register or
    Google OAuth) may ever receive, plus its classification tag.

    Admin, Super Admin, and Vendor are never returned here -- vendor
    access is only ever activated later by an admin approving a
    dedicated application (see routes/customer.py:vendor_application and
    routes/admin.py:vendor_approve), and admin/super-admin can only be
    granted by an existing admin through routes/admin.py.
    """
    classification = classify_email(email)
    role_name = "student" if classification == STUDENT else "customer"
    return role_name, classification
