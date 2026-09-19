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
# before this ever runs). A name (one or more letters) must come first,
# immediately followed by the batch-dept-id block; the final ID segment
# is 3 or 4 digits -- real DIU IDs roll over to 4 digits once a
# batch-department's enrollment passes 999.
STUDENT_EMAIL_PATTERN = re.compile(
    r"^[a-z]+[0-9]{3}-[0-9]{2}-[0-9]{3,4}@diu\.edu\.bd\Z"
)

STUDENT_DOMAIN = "diu.edu.bd"
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


def is_student_domain_email(email):
    """True if the email's domain is exactly the DIU student domain
    (diu.edu.bd), regardless of whether the ID part matches the strict
    pattern. Used to REJECT signup/login outright for a diu.edu.bd
    address that isn't in the exact ID format, instead of silently
    letting it through as a plain external/customer account -- a
    close-but-wrong diu.edu.bd address is far more likely a typo or a
    spoofing attempt than a legitimate different kind of account.
    """
    normalized = (email or "").strip().lower()
    if "@" not in normalized:
        return False
    return normalized.rsplit("@", 1)[-1] == STUDENT_DOMAIN


def is_valid_student_email(email):
    """True only for an exact, correctly formatted DIU student email."""
    return classify_email(email) == STUDENT


def is_allowed_signup_email(email):
    """True only for a new account signup (local register or Google
    OAuth account creation) -- i.e. an exact, correctly formatted DIU
    student email (@diu.edu.bd). No other domain -- including Gmail and
    the official daffodilvariversity.edu.bd staff domain -- may create a
    NEW account. This does not affect logging in to an account that
    already exists; it only gates who can sign up going forward.
    """
    return classify_email(email) == STUDENT


# A self-service *vendor* signup (/register?role=vendor) accepts any email
# address, not just a DIU student ID -- a stall owner has no reason to hold
# one. Such an account is still created with the plain "student" role (the
# starting point routes/customer.py:vendor_application requires; the vendor
# role itself is only ever granted by an admin approving that application),
# and its classification is stamped EXTERNAL or OFFICIAL_DIU from the email.
# That stamp is what exempts it from the exact-DIU-ID rule below, so a
# genuine student account can never slip out of that rule by changing its
# email: their classification stays STUDENT.
VENDOR_SIGNUP_CLASSIFICATIONS = frozenset({EXTERNAL, OFFICIAL_DIU})


def is_vendor_applicant_account(role_name, classification):
    """True for a student-role account that signed up through the vendor
    sign-up page with a non-DIU-student email."""
    return role_name == "student" and classification in VENDOR_SIGNUP_CLASSIFICATIONS


def refreshed_classification(role_name, current_classification, email):
    """The classification to store when an existing account re-authenticates
    (Google login refreshes it from the email each time).

    A student-role account must never *enter* a vendor-applicant
    classification this way -- that would exempt it from the exact-DIU-ID
    rule just by signing in with Google (e.g. a legacy student-role account
    with a Gmail address). Only the vendor sign-up page may stamp one.
    """
    new = classify_email(email)
    if (
        role_name == "student"
        and new in VENDOR_SIGNUP_CLASSIFICATIONS
        and current_classification not in VENDOR_SIGNUP_CLASSIFICATIONS
    ):
        return current_classification
    return new


def violates_student_email_rule(role_name, email, classification):
    """True when a student-role account's email isn't in the exact DIU ID
    format and it isn't a vendor applicant (see above). Used at login and on
    profile email changes so a real student's email can't drift away from
    the DIU ID format."""
    return (
        role_name == "student"
        and not is_valid_student_email(email)
        and classification not in VENDOR_SIGNUP_CLASSIFICATIONS
    )


def resolve_signup_role_name(email):
    """The only role a self-service signup (local register or Google
    OAuth) may ever receive is "student" -- see is_allowed_signup_email,
    which already restricts signup to a genuine DIU student email before
    this is ever reached. The classification tag is still returned so
    the caller can stamp users.email_classification.

    Admin, Super Admin, and Vendor are never returned here -- vendor
    access is only ever activated later by an admin approving a
    dedicated application (see routes/customer.py:vendor_application and
    routes/admin.py:vendor_approve), and admin/super-admin can only be
    granted by an existing admin through routes/admin.py.
    """
    return "student", classify_email(email)
