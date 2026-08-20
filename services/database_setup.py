from pathlib import Path

from sqlalchemy import select

from extensions import db
from models import (
    ComplaintType,
    FoodCategory,
    InspectionCriterion,
    Permission,
    Role,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROLES = {
    "admin": "System administrators",
    "vendor": "Registered street-food stall operators",
    "inspector": "Authorised food-safety inspectors",
    "customer": "Public users of the food-safety platform",
    "student": "DIU students (exact ID-pattern email match)",
}

# All 5 built-in roles are is_system (can't be renamed/deleted from the
# Roles UI); only "admin" is is_admin_tier (can enter the admin panel).
# "student" is deliberately NOT admin-tier and is never assignable except
# by services/account_classification.py matching the exact DIU student
# email pattern at signup.
DEFAULT_ADMIN_TIER_ROLES = {"admin"}

# CRUD-level breakdown per admin resource area, rather than one coarse
# "can touch this page at all" flag -- lets a super admin build roles as
# narrow as "can view vendors but never delete one."
DEFAULT_PERMISSIONS = {
    "vendors.view": "View vendor accounts",
    "vendors.create": "Create vendor accounts",
    "vendors.edit": "Edit vendor accounts",
    "vendors.delete": "Delete vendor accounts",
    "stalls.view": "View stalls",
    "stalls.create": "Create stalls",
    "stalls.edit": "Edit stalls",
    "stalls.delete": "Delete stalls",
    "users.view": "View user accounts",
    "users.create": "Create user accounts",
    "users.edit": "Edit user accounts",
    "users.status": "Activate, suspend, or disable user accounts",
    "users.inspectors": "Create and edit inspector accounts specifically",
    "complaints.view": "View complaints",
    "complaints.respond": "Change a complaint's status or add a response",
    "complaints.evidence": "Verify or reject complaint evidence",
    "inspections.view": "View submitted inspections",
    "inspections.approve": "Approve submitted inspections",
    "inspections.reject": "Reject submitted inspections",
    "inspection_disputes.view": "View vendor-filed inspection disputes",
    "inspection_disputes.respond": "Resolve or reject an inspection dispute",
    "reviews.view": "View customer reviews",
    "reviews.moderate": "Hide, flag, or restore customer reviews",
    "risk_engine.view": "View the risk engine dashboard",
    "reports.view": "View analytics and reports",
    "settings.view": "View system settings and reference data",
    "roles.manage": "Manage roles and permissions (super admin only)",
}

DEFAULT_FOOD_CATEGORIES = (
    ("Fast Food", "Burgers, sandwiches and similar prepared food", "medium"),
    ("Snacks", "Light prepared snacks", "medium"),
    ("Beverage", "Hot and cold drinks", "low"),
    ("Dessert", "Sweets, bakery items and desserts", "medium"),
    ("BBQ", "Grilled and barbecued food", "high"),
    ("Meal", "Rice, curry and complete meals", "high"),
)

DEFAULT_COMPLAINT_TYPES = (
    ("Food contamination", "Suspected contaminated or unsafe food", "critical"),
    ("Poor hygiene", "Unclean food, equipment, staff or premises", "high"),
    ("Foodborne illness", "Illness suspected after eating at the stall", "critical"),
    ("Waste disposal", "Unsafe waste storage or disposal", "medium"),
    ("Pest activity", "Evidence of insects, rodents or other pests", "high"),
    ("Other", "Other food-safety concern", "low"),
)

DEFAULT_INSPECTION_CRITERIA = (
    ("Food protection", "Food is covered and protected from contamination", 10, 1.5),
    ("Clean water", "Safe water is used for food and cleaning", 10, 1.5),
    ("Hand hygiene", "Handlers wash hands and use hygienic practices", 10, 1.5),
    ("Utensil cleanliness", "Utensils and food-contact surfaces are clean", 10, 1.0),
    ("Waste management", "Covered bins and safe waste disposal are available", 10, 1.0),
    ("Pest control", "The stall is free from pest activity", 10, 1.5),
    ("Temperature control", "Food is stored and served at safe temperatures", 10, 1.5),
    ("Premises cleanliness", "The stall and surrounding area are clean", 10, 1.0),
)


def _seed_reference_data():
    existing_roles = {
        name.lower()
        for name in db.session.scalars(select(Role.role_name)).all()
    }
    for name, description in DEFAULT_ROLES.items():
        if name not in existing_roles:
            db.session.add(
                Role(
                    role_name=name,
                    description=description,
                    is_system=True,
                    is_admin_tier=name in DEFAULT_ADMIN_TIER_ROLES,
                )
            )
    db.session.flush()

    # Self-healing backfill: a database that already had these 4 roles
    # before is_system/is_admin_tier existed (e.g. db.create_all() ran
    # once, long before migration 008) would otherwise leave them
    # unflagged even after this function runs again.
    for role in Role.query.filter(Role.role_name.in_(DEFAULT_ROLES)).all():
        role.is_system = True
        role.is_admin_tier = role.role_name in DEFAULT_ADMIN_TIER_ROLES

    existing_categories = {
        name.lower()
        for name in db.session.scalars(
            select(FoodCategory.category_name)
        ).all()
    }
    for name, description, risk_level in DEFAULT_FOOD_CATEGORIES:
        if name.lower() not in existing_categories:
            db.session.add(
                FoodCategory(
                    category_name=name,
                    description=description,
                    risk_level=risk_level,
                )
            )

    existing_types = {
        name.lower()
        for name in db.session.scalars(
            select(ComplaintType.type_name)
        ).all()
    }
    for name, description, severity in DEFAULT_COMPLAINT_TYPES:
        if name.lower() not in existing_types:
            db.session.add(
                ComplaintType(
                    type_name=name,
                    description=description,
                    severity_level=severity,
                )
            )

    existing_criteria = {
        name.lower()
        for name in db.session.scalars(
            select(InspectionCriterion.criteria_name)
        ).all()
    }
    for name, description, max_score, weight in DEFAULT_INSPECTION_CRITERIA:
        if name.lower() not in existing_criteria:
            db.session.add(
                InspectionCriterion(
                    criteria_name=name,
                    description=description,
                    max_score=max_score,
                    weight=weight,
                    is_active=True,
                )
            )

    existing_permissions = {
        code for code in db.session.scalars(select(Permission.code)).all()
    }
    for code, description in DEFAULT_PERMISSIONS.items():
        if code not in existing_permissions:
            db.session.add(Permission(code=code, description=description))
    db.session.flush()

    # The built-in 'admin' role keeps every permission, matching its
    # previous all-or-nothing access exactly.
    admin_role = Role.query.filter_by(role_name="admin").first()
    if admin_role is not None:
        granted_codes = {permission.code for permission in admin_role.permissions}
        for permission in Permission.query.all():
            if permission.code not in granted_codes:
                admin_role.permissions.append(permission)

    db.session.commit()


def _split_mysql_script(script):
    delimiter = ";"
    statement_lines = []

    for line in script.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            delimiter = stripped.split(maxsplit=1)[1]
            continue

        statement_lines.append(line)
        combined = "\n".join(statement_lines).rstrip()
        if combined.endswith(delimiter):
            statement = combined[: -len(delimiter)].strip()
            statement_lines = []
            if statement:
                yield statement

    trailing = "\n".join(statement_lines).strip()
    if trailing:
        yield trailing


def _install_database_objects():
    script_names = (
        "functions.sql",
        "triggers.sql",
        "procedures.sql",
        "views.sql",
    )
    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        try:
            for script_name in script_names:
                script = (
                    PROJECT_ROOT / "database" / script_name
                ).read_text(encoding="utf-8")
                for statement in _split_mysql_script(script):
                    cursor.execute(statement)
            connection.commit()
        finally:
            cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    """Create missing tables and install required MySQL database objects."""
    db.create_all()
    _seed_reference_data()
    _install_database_objects()
