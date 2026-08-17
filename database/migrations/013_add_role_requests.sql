-- Apply this migration to a database created before the controlled
-- role-approval system was added. Fresh installations already include
-- this through database/schema.sql.
--
-- Adds:
--   1. role_requests -- self-service Inspector/Admin access requests,
--      reviewed only by a Super Admin (routes/admin.py:
--      access_request_approve/access_request_reject). Vendor requests
--      keep using the existing vendors.status workflow (migration 011)
--      instead of this table.
--   2. Widens auth_audit_log.event to also cover role_requested,
--      role_approved, role_rejected, and account_reactivated.

USE smart_street_food_safety;

-- 1. role_requests
CREATE TABLE IF NOT EXISTS role_requests (
  request_id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  requested_role ENUM('inspector', 'admin') NOT NULL,
  reason VARCHAR(500) NULL,
  status ENUM('pending', 'approved', 'rejected', 'cancelled') NOT NULL DEFAULT 'pending',
  requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_by INT NULL,
  reviewed_at DATETIME NULL,
  rejection_reason VARCHAR(500) NULL,
  PRIMARY KEY (request_id),
  CONSTRAINT fk_role_requests_user_id
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_role_requests_reviewed_by
    FOREIGN KEY (reviewed_by) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=INNODB;

SET @role_requests_idx1_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'role_requests'
    AND index_name = 'idx_role_requests_user_id'
);

SET @role_requests_idx1_sql = IF(
  @role_requests_idx1_exists = 0,
  'CREATE INDEX idx_role_requests_user_id ON role_requests (user_id)',
  'SELECT ''idx_role_requests_user_id already exists'' AS migration_status'
);

PREPARE role_requests_idx1_statement FROM @role_requests_idx1_sql;
EXECUTE role_requests_idx1_statement;
DEALLOCATE PREPARE role_requests_idx1_statement;

SET @role_requests_idx2_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'role_requests'
    AND index_name = 'idx_role_requests_status'
);

SET @role_requests_idx2_sql = IF(
  @role_requests_idx2_exists = 0,
  'CREATE INDEX idx_role_requests_status ON role_requests (status)',
  'SELECT ''idx_role_requests_status already exists'' AS migration_status'
);

PREPARE role_requests_idx2_statement FROM @role_requests_idx2_sql;
EXECUTE role_requests_idx2_statement;
DEALLOCATE PREPARE role_requests_idx2_statement;

-- 2. Widen auth_audit_log.event (idempotent: only runs if the new
-- values aren't already present in the column type).
SET @auth_audit_log_event_needs_widening = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'auth_audit_log'
    AND column_name = 'event'
    AND column_type NOT LIKE '%role_requested%'
);

SET @auth_audit_log_event_sql = IF(
  @auth_audit_log_event_needs_widening = 1,
  "ALTER TABLE auth_audit_log MODIFY COLUMN event ENUM('login_success', 'login_failed', 'logout', 'account_created', 'account_suspended', 'account_reactivated', 'role_requested', 'role_approved', 'role_rejected') NOT NULL",
  'SELECT ''auth_audit_log.event already widened'' AS migration_status'
);

PREPARE auth_audit_log_event_statement FROM @auth_audit_log_event_sql;
EXECUTE auth_audit_log_event_statement;
DEALLOCATE PREPARE auth_audit_log_event_statement;
