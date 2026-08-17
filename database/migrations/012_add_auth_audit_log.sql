-- Apply this migration to a database created before the authentication
-- audit trail was added. Fresh installations already include this table
-- through database/schema.sql and services/database_setup.py.
--
-- Adds:
--   auth_audit_log -- append-only trail of login/logout/account-lifecycle
--   events (login_success, login_failed, logout, account_created,
--   account_suspended), with IP address and user agent where available.
--   Distinct from role_audit_log (role changes) and evidence_audit_logs
--   (evidence actions). Never stores OAuth tokens, passwords, or client
--   secrets.

USE smart_street_food_safety;

CREATE TABLE IF NOT EXISTS auth_audit_log (
  audit_id INT NOT NULL AUTO_INCREMENT,
  user_id INT NULL,
  email_attempted VARCHAR(150) NULL,
  event ENUM('login_success', 'login_failed', 'logout', 'account_created', 'account_suspended') NOT NULL,
  auth_provider ENUM('local', 'google') NULL,
  ip_address VARCHAR(45) NULL,
  user_agent VARCHAR(255) NULL,
  details VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (audit_id),
  CONSTRAINT fk_auth_audit_log_user_id
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=INNODB;

SET @auth_audit_log_idx1_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'auth_audit_log'
    AND index_name = 'idx_auth_audit_log_user_id'
);

SET @auth_audit_log_idx1_sql = IF(
  @auth_audit_log_idx1_exists = 0,
  'CREATE INDEX idx_auth_audit_log_user_id ON auth_audit_log (user_id)',
  'SELECT ''idx_auth_audit_log_user_id already exists'' AS migration_status'
);

PREPARE auth_audit_log_idx1_statement FROM @auth_audit_log_idx1_sql;
EXECUTE auth_audit_log_idx1_statement;
DEALLOCATE PREPARE auth_audit_log_idx1_statement;

SET @auth_audit_log_idx2_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'auth_audit_log'
    AND index_name = 'idx_auth_audit_log_created_at'
);

SET @auth_audit_log_idx2_sql = IF(
  @auth_audit_log_idx2_exists = 0,
  'CREATE INDEX idx_auth_audit_log_created_at ON auth_audit_log (created_at)',
  'SELECT ''idx_auth_audit_log_created_at already exists'' AS migration_status'
);

PREPARE auth_audit_log_idx2_statement FROM @auth_audit_log_idx2_sql;
EXECUTE auth_audit_log_idx2_statement;
DEALLOCATE PREPARE auth_audit_log_idx2_statement;
