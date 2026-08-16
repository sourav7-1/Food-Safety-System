-- Apply this migration to a database created before production-level
-- Google OAuth classification and the vendor approval workflow. Fresh
-- installations already include all of this through database/schema.sql
-- and services/database_setup.py (which seeds the 'student' role).
--
-- Adds:
--   1. users.email_classification -- informational tag only
--      (unclassified/student/official_diu/external), derived purely from
--      the email address by services/account_classification.py. Never
--      grants a role by itself.
--   2. A 'student' role row (is_system=1, is_admin_tier=0) -- the only
--      role a matching DIU student-pattern email may ever be assigned
--      to on signup. Vendor/Admin/Super Admin remain impossible to
--      reach through registration or Google sign-in.
--   3. vendors.status + review columns -- the pending/approved/rejected/
--      suspended approval workflow. Existing vendor rows are backfilled
--      to 'approved' (they were already vetted at creation time, being
--      created directly by an admin).
--   4. role_audit_log -- append-only trail of who changed whose role,
--      from what to what, and why.

USE smart_street_food_safety;

-- 1. users.email_classification
SET @email_classification_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'email_classification'
);

SET @email_classification_sql = IF(
  @email_classification_exists = 0,
  "ALTER TABLE users ADD COLUMN email_classification ENUM('unclassified', 'student', 'official_diu', 'external') NOT NULL DEFAULT 'unclassified' AFTER is_super_admin",
  'SELECT ''email_classification already exists'' AS migration_status'
);

PREPARE email_classification_statement FROM @email_classification_sql;
EXECUTE email_classification_statement;
DEALLOCATE PREPARE email_classification_statement;

-- 2. 'student' role (idempotent; matches services/database_setup.py's
--    DEFAULT_ROLES/DEFAULT_ADMIN_TIER_ROLES for a fresh install).
INSERT INTO roles (role_name, description, is_system, is_admin_tier)
SELECT 'student', 'DIU students (exact ID-pattern email match)', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE role_name = 'student');

-- 3. vendors.status and review columns
SET @vendor_status_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'vendors'
    AND column_name = 'status'
);

SET @vendor_status_sql = IF(
  @vendor_status_exists = 0,
  "ALTER TABLE vendors
     ADD COLUMN status ENUM('pending', 'approved', 'rejected', 'suspended') NOT NULL DEFAULT 'approved' AFTER national_id,
     ADD COLUMN requested_stall_name VARCHAR(150) NULL AFTER status,
     ADD COLUMN requested_area_id INT NULL AFTER requested_stall_name,
     ADD COLUMN requested_address VARCHAR(255) NULL AFTER requested_area_id,
     ADD COLUMN rejection_reason VARCHAR(500) NULL AFTER requested_address,
     ADD COLUMN reviewed_by_user_id INT NULL AFTER rejection_reason,
     ADD COLUMN reviewed_at DATETIME NULL AFTER reviewed_by_user_id,
     ADD CONSTRAINT fk_vendors_requested_area_id FOREIGN KEY (requested_area_id) REFERENCES areas (area_id) ON UPDATE CASCADE ON DELETE SET NULL,
     ADD CONSTRAINT fk_vendors_reviewed_by_user_id FOREIGN KEY (reviewed_by_user_id) REFERENCES users (user_id) ON UPDATE CASCADE ON DELETE SET NULL",
  'SELECT ''vendors.status already exists'' AS migration_status'
);

PREPARE vendor_status_statement FROM @vendor_status_sql;
EXECUTE vendor_status_statement;
DEALLOCATE PREPARE vendor_status_statement;

SET @vendor_status_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'vendors'
    AND index_name = 'idx_vendors_status'
);

SET @vendor_status_index_sql = IF(
  @vendor_status_index_exists = 0,
  'CREATE INDEX idx_vendors_status ON vendors (status)',
  'SELECT ''idx_vendors_status already exists'' AS migration_status'
);

PREPARE vendor_status_index_statement FROM @vendor_status_index_sql;
EXECUTE vendor_status_index_statement;
DEALLOCATE PREPARE vendor_status_index_statement;

-- 4. role_audit_log
CREATE TABLE IF NOT EXISTS role_audit_log (
  audit_id INT NOT NULL AUTO_INCREMENT,
  target_user_id INT NOT NULL,
  actor_user_id INT NULL,
  old_role_id INT NULL,
  new_role_id INT NOT NULL,
  reason VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (audit_id),
  CONSTRAINT fk_role_audit_log_target_user_id
    FOREIGN KEY (target_user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_role_audit_log_actor_user_id
    FOREIGN KEY (actor_user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE SET NULL,
  CONSTRAINT fk_role_audit_log_old_role_id
    FOREIGN KEY (old_role_id) REFERENCES roles (role_id)
    ON UPDATE CASCADE ON DELETE SET NULL,
  CONSTRAINT fk_role_audit_log_new_role_id
    FOREIGN KEY (new_role_id) REFERENCES roles (role_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=INNODB;

SET @role_audit_log_idx1_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'role_audit_log'
    AND index_name = 'idx_role_audit_log_target_user_id'
);

SET @role_audit_log_idx1_sql = IF(
  @role_audit_log_idx1_exists = 0,
  'CREATE INDEX idx_role_audit_log_target_user_id ON role_audit_log (target_user_id)',
  'SELECT ''idx_role_audit_log_target_user_id already exists'' AS migration_status'
);

PREPARE role_audit_log_idx1_statement FROM @role_audit_log_idx1_sql;
EXECUTE role_audit_log_idx1_statement;
DEALLOCATE PREPARE role_audit_log_idx1_statement;
