from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class Role(db.Model):
    __tablename__ = "roles"

    role_id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    users = db.relationship("User", back_populates="role", lazy="dynamic")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(
        db.Integer,
        db.ForeignKey("roles.role_id", onupdate="CASCADE"),
        nullable=False,
    )
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), unique=True)
    password_hash = db.Column(db.String(255), nullable=True)
    google_id = db.Column(db.String(255), unique=True)
    auth_provider = db.Column(
        db.Enum("local", "google"),
        nullable=False,
        default="local",
        server_default="local",
    )
    status = db.Column(
        db.Enum("active", "inactive", "suspended"),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
        server_onupdate=db.func.current_timestamp(),
    )

    role = db.relationship("Role", back_populates="users")
    vendor_profile = db.relationship(
        "Vendor", back_populates="user", uselist=False
    )
    inspector_profile = db.relationship(
        "Inspector", back_populates="user", uselist=False
    )

    def get_id(self):
        return str(self.user_id)

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def role_name(self):
        return self.role.role_name.lower() if self.role else ""

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        try:
            return check_password_hash(self.password_hash, password)
        except (TypeError, ValueError):
            return False


class Vendor(db.Model):
    __tablename__ = "vendors"

    vendor_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE"),
        nullable=False,
        unique=True,
    )
    business_name = db.Column(db.String(150), nullable=False)
    license_number = db.Column(db.String(80), nullable=False, unique=True)
    license_expiry_date = db.Column(db.Date)
    national_id = db.Column(db.String(80), unique=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="vendor_profile")
    stalls = db.relationship("Stall", back_populates="vendor")


class Area(db.Model):
    __tablename__ = "areas"
    __table_args__ = (
        db.UniqueConstraint(
            "area_name",
            "city",
            "zone",
            name="uq_areas_area_city_zone",
        ),
    )

    area_id = db.Column(db.Integer, primary_key=True)
    area_name = db.Column(db.String(120), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    zone = db.Column(db.String(100), nullable=False, default="")
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    stalls = db.relationship("Stall", back_populates="area")
    inspectors = db.relationship("Inspector", back_populates="assigned_area")


class Stall(db.Model):
    __tablename__ = "stalls"

    stall_id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.vendor_id", onupdate="CASCADE"),
        nullable=False,
    )
    area_id = db.Column(
        db.Integer,
        db.ForeignKey("areas.area_id", onupdate="CASCADE"),
        nullable=False,
    )
    stall_name = db.Column(db.String(150), nullable=False)
    stall_code = db.Column(db.String(80), nullable=False, unique=True)
    address = db.Column(db.String(255), nullable=False)
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    photo_url = db.Column(db.String(1000))
    status = db.Column(
        db.Enum("active", "closed", "suspended"),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    vendor = db.relationship("Vendor", back_populates="stalls")
    area = db.relationship("Area", back_populates="stalls")
    inspections = db.relationship("Inspection", back_populates="stall")
    complaints = db.relationship("Complaint", back_populates="stall")
    food_items = db.relationship(
        "FoodItem", back_populates="stall", cascade="all, delete-orphan"
    )
    reviews = db.relationship(
        "Review", back_populates="stall", cascade="all, delete-orphan"
    )


class Inspector(db.Model):
    __tablename__ = "inspectors"

    inspector_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE"),
        nullable=False,
        unique=True,
    )
    employee_code = db.Column(db.String(80), nullable=False, unique=True)
    designation = db.Column(db.String(100))
    assigned_area_id = db.Column(
        db.Integer,
        db.ForeignKey("areas.area_id", onupdate="CASCADE"),
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="inspector_profile")
    assigned_area = db.relationship("Area", back_populates="inspectors")
    inspections = db.relationship("Inspection", back_populates="inspector")


class Inspection(db.Model):
    __tablename__ = "inspections"

    inspection_id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(
        db.Integer,
        db.ForeignKey("stalls.stall_id", onupdate="CASCADE"),
        nullable=False,
    )
    inspector_id = db.Column(
        db.Integer,
        db.ForeignKey("inspectors.inspector_id", onupdate="CASCADE"),
        nullable=False,
    )
    inspection_date = db.Column(db.DateTime, nullable=False)
    overall_score = db.Column(db.Numeric(6, 2))
    risk_level = db.Column(
        db.Enum("low", "medium", "high", "critical")
    )
    reinspection_date = db.Column(db.Date)
    status = db.Column(
        db.Enum("draft", "submitted", "approved", "rejected"),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    remarks = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    stall = db.relationship("Stall", back_populates="inspections")
    inspector = db.relationship("Inspector", back_populates="inspections")
    scores = db.relationship(
        "InspectionScore",
        back_populates="inspection",
        cascade="all, delete-orphan",
    )


class InspectionCriterion(db.Model):
    __tablename__ = "inspection_criteria"

    criteria_id = db.Column(db.Integer, primary_key=True)
    criteria_name = db.Column(db.String(150), nullable=False, unique=True)
    description = db.Column(db.String(255))
    max_score = db.Column(db.Numeric(5, 2), nullable=False)
    weight = db.Column(
        db.Numeric(5, 2),
        nullable=False,
        default=1,
        server_default="1.00",
    )
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.true(),
    )

    scores = db.relationship("InspectionScore", back_populates="criterion")


class InspectionScore(db.Model):
    __tablename__ = "inspection_scores"
    __table_args__ = (
        db.UniqueConstraint(
            "inspection_id",
            "criteria_id",
            name="uq_inspection_scores_inspection_criteria",
        ),
    )

    score_id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "inspections.inspection_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    criteria_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "inspection_criteria.criteria_id",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    score = db.Column(db.Numeric(5, 2), nullable=False)
    comments = db.Column(db.String(255))

    inspection = db.relationship("Inspection", back_populates="scores")
    criterion = db.relationship("InspectionCriterion", back_populates="scores")


class ComplaintType(db.Model):
    __tablename__ = "complaint_types"

    complaint_type_id = db.Column(db.Integer, primary_key=True)
    type_name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    severity_level = db.Column(
        db.Enum("low", "medium", "high", "critical"),
        nullable=False,
        default="medium",
        server_default="medium",
    )


class Complaint(db.Model):
    __tablename__ = "complaints"

    complaint_id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(
        db.Integer,
        db.ForeignKey("stalls.stall_id", onupdate="CASCADE"),
        nullable=False,
    )
    complaint_type_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "complaint_types.complaint_type_id", onupdate="CASCADE"
        ),
        nullable=False,
    )
    submitted_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE"),
    )
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.Enum("open", "under_review", "resolved", "rejected"),
        nullable=False,
        default="open",
        server_default="open",
    )
    submitted_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    resolved_at = db.Column(db.DateTime)

    stall = db.relationship("Stall", back_populates="complaints")
    complaint_type = db.relationship("ComplaintType")
    submitted_by = db.relationship("User")
    corrective_actions = db.relationship(
        "CorrectiveAction", back_populates="complaint"
    )


class FoodCategory(db.Model):
    __tablename__ = "food_categories"

    category_id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    risk_level = db.Column(
        db.Enum("low", "medium", "high"),
        nullable=False,
        default="medium",
        server_default="medium",
    )

    food_items = db.relationship("FoodItem", back_populates="category")


class FoodItem(db.Model):
    __tablename__ = "food_items"
    __table_args__ = (
        db.UniqueConstraint(
            "stall_id",
            "category_id",
            "item_name",
            name="uq_food_items_stall_category_item",
        ),
    )

    food_item_id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "stalls.stall_id", onupdate="CASCADE", ondelete="CASCADE"
        ),
        nullable=False,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("food_categories.category_id", onupdate="CASCADE"),
        nullable=False,
    )
    item_name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Numeric(10, 2))
    is_available = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.true(),
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    stall = db.relationship("Stall", back_populates="food_items")
    category = db.relationship("FoodCategory", back_populates="food_items")


class Review(db.Model):
    __tablename__ = "reviews"
    __table_args__ = (
        db.UniqueConstraint(
            "stall_id",
            "user_id",
            name="uq_reviews_stall_user",
        ),
    )

    review_id = db.Column(db.Integer, primary_key=True)
    stall_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "stalls.stall_id", onupdate="CASCADE", ondelete="CASCADE"
        ),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE"),
        nullable=False,
    )
    rating = db.Column(db.SmallInteger, nullable=False)
    review_text = db.Column(db.Text)
    status = db.Column(
        db.Enum("visible", "hidden", "flagged"),
        nullable=False,
        default="visible",
        server_default="visible",
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    stall = db.relationship("Stall", back_populates="reviews")
    user = db.relationship("User")


class CorrectiveAction(db.Model):
    __tablename__ = "corrective_actions"

    action_id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(
        db.Integer,
        db.ForeignKey("inspections.inspection_id", onupdate="CASCADE"),
    )
    complaint_id = db.Column(
        db.Integer,
        db.ForeignKey("complaints.complaint_id", onupdate="CASCADE"),
    )
    assigned_to_vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.vendor_id", onupdate="CASCADE"),
        nullable=False,
    )
    action_description = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(
        db.Enum(
            "pending",
            "in_progress",
            "completed",
            "overdue",
            "cancelled",
        ),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    completion_notes = db.Column(db.Text)
    evidence_path = db.Column(db.String(500))
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    completed_at = db.Column(db.DateTime)

    inspection = db.relationship("Inspection")
    complaint = db.relationship("Complaint", back_populates="corrective_actions")
    vendor = db.relationship("Vendor")


class StreetFoodStallRegistration(db.Model):
    __tablename__ = "street_food_stall_registrations"

    registration_id = db.Column(db.Integer, primary_key=True)
    submitted_at = db.Column(db.DateTime, nullable=False)
    vendor_name = db.Column(db.String(150), nullable=False)
    phone_number = db.Column(db.String(30), nullable=False)
    stall_name = db.Column(db.String(200), nullable=False)
    area = db.Column(db.String(200), nullable=False)
    full_address = db.Column(db.String(500), nullable=False)
    food_category = db.Column(db.String(255), nullable=False)
    food_items = db.Column(db.String(500), nullable=False)
    average_price_bdt = db.Column(db.String(50), nullable=False)
    food_covered = db.Column(db.Enum("Yes", "No"), nullable=False)
    clean_water_used = db.Column(db.Enum("Yes", "No"), nullable=False)
    waste_bin_available = db.Column(db.Enum("Yes", "No"), nullable=False)
    vendor_uses_gloves = db.Column(db.Enum("Yes", "No"), nullable=False)
    payment_method = db.Column(db.String(255))
    stall_photo_url = db.Column(db.String(1000))
    additional_comments = db.Column(db.Text)
    source_timestamp = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
