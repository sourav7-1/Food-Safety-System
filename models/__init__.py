from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


# Pure junction table (no extra columns), used as SQLAlchemy's
# `secondary=` for the Role<->Permission many-to-many relationship.
role_permissions = db.Table(
    "role_permissions",
    db.Column(
        "role_id",
        db.Integer,
        db.ForeignKey("roles.role_id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "permission_id",
        db.Integer,
        db.ForeignKey(
            "permissions.permission_id", onupdate="CASCADE", ondelete="CASCADE"
        ),
        primary_key=True,
    ),
)


class Permission(db.Model):
    __tablename__ = "permissions"

    permission_id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))

    roles = db.relationship(
        "Role", secondary=role_permissions, back_populates="permissions"
    )


class Role(db.Model):
    __tablename__ = "roles"

    role_id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.String(255))
    # The 4 built-in roles (admin/vendor/inspector/customer) are
    # is_system=True and can't be renamed/deleted from the Roles UI --
    # many call sites outside the admin panel still reference these exact
    # role_name strings. is_admin_tier controls whether this role can
    # enter the admin panel at all, independent of which permissions it
    # holds (see routes/__init__.py:admin_tier_required).
    is_system = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    is_admin_tier = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    users = db.relationship("User", back_populates="role", lazy="dynamic")
    permissions = db.relationship(
        "Permission", secondary=role_permissions, back_populates="roles"
    )


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
    email_verified_at = db.Column(db.DateTime, nullable=True)
    profile_photo_url = db.Column(db.String(255))
    bio = db.Column(db.Text)
    address = db.Column(db.String(255))
    date_of_birth = db.Column(db.Date)
    preferred_area_id = db.Column(
        db.Integer,
        db.ForeignKey("areas.area_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    is_super_admin = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    # Informational only -- derived purely from the email address by
    # services/account_classification.py and never used to grant a role
    # or permission by itself. Set at signup (local or Google) and
    # refreshed on each Google login; MySQL's roles table (role_id) is
    # the only thing that ever authorizes access.
    email_classification = db.Column(
        db.Enum("unclassified", "student", "official_diu", "external"),
        nullable=False,
        default="unclassified",
        server_default="unclassified",
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
        "Vendor",
        back_populates="user",
        uselist=False,
        foreign_keys="Vendor.user_id",
    )
    inspector_profile = db.relationship(
        "Inspector", back_populates="user", uselist=False
    )
    preferred_area = db.relationship("Area", foreign_keys=[preferred_area_id])

    def get_id(self):
        return str(self.user_id)

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    @property
    def role_name(self):
        return self.role.role_name.lower() if self.role else ""

    def has_permission(self, code):
        """True if this user can perform the given admin action -- a
        super admin always can; otherwise it depends on what their role
        has been granted via the Roles & Permissions page."""
        if self.is_super_admin:
            return True
        if not self.role:
            return False
        return any(permission.code == code for permission in self.role.permissions)

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
    # Approval workflow for self-service applications (routes/customer.py
    # :vendor_application). Defaults to 'approved' because a Vendor row
    # created directly by an admin (routes/admin.py:vendor_create) is
    # already vetted at creation time -- only self-submitted applications
    # are explicitly inserted as 'pending'. The user's role_id is NOT the
    # vendor role until an admin approves (see admin.py:vendor_approve),
    # so the vendor role itself is never self-granted.
    status = db.Column(
        db.Enum("pending", "approved", "rejected", "suspended"),
        nullable=False,
        default="approved",
        server_default="approved",
    )
    requested_stall_name = db.Column(db.String(150))
    requested_area_id = db.Column(
        db.Integer,
        db.ForeignKey("areas.area_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    requested_address = db.Column(db.String(255))
    rejection_reason = db.Column(db.String(500))
    reviewed_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship(
        "User", back_populates="vendor_profile", foreign_keys=[user_id]
    )
    stalls = db.relationship("Stall", back_populates="vendor")
    requested_area = db.relationship("Area", foreign_keys=[requested_area_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_user_id])


class RoleAuditLog(db.Model):
    __tablename__ = "role_audit_log"

    audit_id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE"),
        nullable=False,
    )
    actor_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    old_role_id = db.Column(
        db.Integer,
        db.ForeignKey("roles.role_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    new_role_id = db.Column(
        db.Integer,
        db.ForeignKey("roles.role_id", onupdate="CASCADE"),
        nullable=False,
    )
    reason = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    target_user = db.relationship("User", foreign_keys=[target_user_id])
    actor_user = db.relationship("User", foreign_keys=[actor_user_id])
    old_role = db.relationship("Role", foreign_keys=[old_role_id])
    new_role = db.relationship("Role", foreign_keys=[new_role_id])


class AuthAuditLog(db.Model):
    """Append-only trail of authentication/account-lifecycle events --
    who signed in (or failed to), when, from where, and what changed on
    their account. Distinct from role_audit_log (role changes) and
    evidence_audit_logs (evidence actions). Never stores OAuth tokens,
    passwords, or client secrets -- only the outcome of an auth attempt."""

    __tablename__ = "auth_audit_log"

    audit_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    # email_attempted covers login_failed events where the address didn't
    # match any account, so there's no user_id to attach the row to.
    email_attempted = db.Column(db.String(150))
    event = db.Column(
        db.Enum(
            "login_success",
            "login_failed",
            "logout",
            "account_created",
            "account_suspended",
            "account_reactivated",
            "role_requested",
            "role_approved",
            "role_rejected",
        ),
        nullable=False,
    )
    auth_provider = db.Column(db.Enum("local", "google"))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    details = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User")


class RoleRequest(db.Model):
    """Self-service request from an authenticated user to be granted an
    operational role that can never be self-granted -- Inspector or
    Admin. (Vendor has its own dedicated request flow already: see the
    Vendor model's status/requested_* columns and
    routes/customer.py:vendor_application -- it isn't duplicated here.)

    A role_id change never happens until a Super Admin approves the
    request (routes/admin.py:access_request_approve); this table is the
    only record of the pending state in between."""

    __tablename__ = "role_requests"

    request_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    requested_role = db.Column(db.Enum("inspector", "admin"), nullable=False)
    reason = db.Column(db.String(500))
    status = db.Column(
        db.Enum("pending", "approved", "rejected", "cancelled"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    requested_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    reviewed_by = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    reviewed_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.String(500))

    user = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])


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
    disputes = db.relationship(
        "InspectionDispute",
        back_populates="inspection",
        cascade="all, delete-orphan",
        order_by="InspectionDispute.submitted_at",
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


class InspectionDispute(db.Model):
    __tablename__ = "inspection_disputes"

    dispute_id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "inspections.inspection_id", onupdate="CASCADE", ondelete="CASCADE"
        ),
        nullable=False,
    )
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.vendor_id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.Enum("submitted", "under_review", "resolved", "rejected"),
        nullable=False,
        default="submitted",
        server_default="submitted",
    )
    submitted_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    resolved_at = db.Column(db.DateTime)
    admin_response = db.Column(db.Text)

    inspection = db.relationship("Inspection", back_populates="disputes")
    vendor = db.relationship("Vendor")
    evidence = db.relationship(
        "InspectionDisputeEvidence",
        back_populates="dispute",
        cascade="all, delete-orphan",
        order_by="InspectionDisputeEvidence.uploaded_at",
    )


class InspectionDisputeEvidence(db.Model):
    __tablename__ = "inspection_dispute_evidence"

    evidence_id = db.Column(db.Integer, primary_key=True)
    dispute_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "inspection_disputes.dispute_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    file_name = db.Column(db.String(255), nullable=False)
    stored_file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(
        db.Enum("image", "video", "audio", "document"), nullable=False
    )
    mime_type = db.Column(db.String(150), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False)
    uploaded_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    dispute = db.relationship("InspectionDispute", back_populates="evidence")
    uploader = db.relationship("User")


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
        db.Enum(
            "submitted",
            "under_review",
            "investigation",
            "action_required",
            "resolved",
            "rejected",
            "closed",
        ),
        nullable=False,
        default="submitted",
        server_default="submitted",
    )
    submitted_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    resolved_at = db.Column(db.DateTime)
    admin_response = db.Column(db.Text)

    stall = db.relationship("Stall", back_populates="complaints")
    complaint_type = db.relationship("ComplaintType")
    submitted_by = db.relationship("User")
    corrective_actions = db.relationship(
        "CorrectiveAction", back_populates="complaint"
    )
    evidence = db.relationship(
        "ComplaintEvidence",
        back_populates="complaint",
        cascade="all, delete-orphan",
        order_by="ComplaintEvidence.uploaded_at",
    )


class ComplaintEvidence(db.Model):
    __tablename__ = "complaint_evidence"

    evidence_id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "complaints.complaint_id", onupdate="CASCADE", ondelete="CASCADE"
        ),
        nullable=False,
    )
    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    file_name = db.Column(db.String(255), nullable=False)
    stored_file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(
        db.Enum("image", "video", "audio", "document"), nullable=False
    )
    mime_type = db.Column(db.String(150), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False)
    evidence_description = db.Column(db.String(500))
    uploaded_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    verification_status = db.Column(
        db.Enum("pending", "under_review", "verified", "rejected"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    verified_by = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    verified_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.String(500))

    complaint = db.relationship("Complaint", back_populates="evidence")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])
    verifier = db.relationship("User", foreign_keys=[verified_by])
    audit_logs = db.relationship(
        "EvidenceAuditLog",
        back_populates="evidence",
        cascade="all, delete-orphan",
        order_by="EvidenceAuditLog.action_time",
    )


class EvidenceAuditLog(db.Model):
    __tablename__ = "evidence_audit_logs"

    audit_id = db.Column(db.Integer, primary_key=True)
    evidence_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "complaint_evidence.evidence_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="SET NULL"),
    )
    action = db.Column(
        db.Enum(
            "uploaded",
            "viewed",
            "downloaded",
            "marked_under_review",
            "verified",
            "rejected",
        ),
        nullable=False,
    )
    action_time = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    details = db.Column(db.String(255))

    evidence = db.relationship("ComplaintEvidence", back_populates="audit_logs")
    user = db.relationship("User")


class Notification(db.Model):
    __tablename__ = "notifications"

    notification_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    complaint_id = db.Column(
        db.Integer,
        db.ForeignKey("complaints.complaint_id", onupdate="CASCADE", ondelete="CASCADE"),
    )
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User")
    complaint = db.relationship("Complaint")


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
