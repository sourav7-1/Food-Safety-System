-- Apply this migration to a database created before the "forgot
-- password" self-service reset flow was added. Fresh installations
-- already include these enum values through database/schema.sql and
-- models/__init__.py (db.create_all() reads the enum straight off the
-- SQLAlchemy model).
--
-- Adds two new auth_audit_log.event values:
--   password_reset_requested -- a reset link was generated and (attempted
--   to be) emailed for a "local" auth-provider account.
--   password_reset_completed -- the user followed a valid link and
--   successfully set a new password.
--
-- Purely additive to the enum; no existing rows change meaning.

USE smart_street_food_safety;

ALTER TABLE auth_audit_log
  MODIFY COLUMN event ENUM(
    'login_success',
    'login_failed',
    'logout',
    'account_created',
    'account_suspended',
    'account_reactivated',
    'role_requested',
    'role_approved',
    'role_rejected',
    'password_reset_requested',
    'password_reset_completed'
  ) NOT NULL;
