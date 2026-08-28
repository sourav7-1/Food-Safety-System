-- Apply this migration to a database created before the "customer" and
-- "student" roles were consolidated into a single public-user role.
-- Fresh installations never see the old "customer"/"consumer" role rows
-- at all -- services/database_setup.py only seeds "student" now.
--
-- Self-service signup has been restricted to exact-format DIU student
-- emails for a while (see services/account_classification.py); every
-- new account has therefore already been landing on "student", not
-- "customer". This migration catches up any account created before
-- that restriction (or any account an admin manually assigned the old
-- "customer"/"consumer" role to) and retires the now-redundant role
-- rows.
--
-- Non-destructive with respect to users: no user row is deleted, only
-- re-pointed to the "student" role. The "customer"/"consumer" role rows
-- themselves are deleted, but only once nothing references them any
-- more (users, role_permissions, and role_audit_log) -- if a historical
-- role_audit_log entry still references one (new_role_id is ON DELETE
-- RESTRICT), the role row is deliberately left in place rather than
-- destroying that audit history.

USE smart_street_food_safety;

-- 1. Make sure "student" exists before anything is repointed to it
--    (idempotent; matches services/database_setup.py's seed).
INSERT INTO roles (role_name, description, is_system, is_admin_tier)
SELECT 'student', 'DIU students (exact ID-pattern email match) -- the only public-user role', 1, 0
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE role_name = 'student');

SET @student_role_id = (SELECT role_id FROM roles WHERE role_name = 'student');

-- 2. Re-point every user still on the old "customer"/"consumer" role to
--    "student".
UPDATE users u
JOIN roles r ON r.role_id = u.role_id
SET u.role_id = @student_role_id
WHERE r.role_name IN ('customer', 'consumer');

-- 3. Drop the now-orphaned role_permissions rows for those roles (both
--    are plain public-user roles with no permission grants in practice,
--    but this is harmless if any exist).
DELETE rp FROM role_permissions rp
JOIN roles r ON r.role_id = rp.role_id
WHERE r.role_name IN ('customer', 'consumer');

-- 4. Delete each retired role row, but only if role_audit_log no longer
--    references it (new_role_id is ON DELETE RESTRICT -- deliberately
--    so this migration can never silently erase audit history).
SET @customer_role_id = (SELECT role_id FROM roles WHERE role_name = 'customer');
SET @customer_role_referenced = (
  SELECT COUNT(*) FROM role_audit_log
  WHERE old_role_id = @customer_role_id OR new_role_id = @customer_role_id
);
SET @delete_customer_sql = IF(
  @customer_role_id IS NOT NULL AND @customer_role_referenced = 0,
  'DELETE FROM roles WHERE role_id = @customer_role_id',
  'SELECT ''customer role left in place (missing or still referenced by role_audit_log)'' AS migration_status'
);
PREPARE delete_customer_stmt FROM @delete_customer_sql;
EXECUTE delete_customer_stmt;
DEALLOCATE PREPARE delete_customer_stmt;

SET @consumer_role_id = (SELECT role_id FROM roles WHERE role_name = 'consumer');
SET @consumer_role_referenced = (
  SELECT COUNT(*) FROM role_audit_log
  WHERE old_role_id = @consumer_role_id OR new_role_id = @consumer_role_id
);
SET @delete_consumer_sql = IF(
  @consumer_role_id IS NOT NULL AND @consumer_role_referenced = 0,
  'DELETE FROM roles WHERE role_id = @consumer_role_id',
  'SELECT ''consumer role left in place (missing or still referenced by role_audit_log)'' AS migration_status'
);
PREPARE delete_consumer_stmt FROM @delete_consumer_sql;
EXECUTE delete_consumer_stmt;
DEALLOCATE PREPARE delete_consumer_stmt;
