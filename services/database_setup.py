from pathlib import Path

from sqlalchemy import select

from extensions import db
from models import (
    ComplaintType,
    FoodCategory,
    InspectionCriterion,
    Role,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROLES = {
    "admin": "System administrators",
    "vendor": "Registered street-food stall operators",
    "inspector": "Authorised food-safety inspectors",
    "customer": "Public users of the food-safety platform",
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
            db.session.add(Role(role_name=name, description=description))

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
