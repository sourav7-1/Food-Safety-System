-- Apply this migration to an existing database created before the
-- admin RBAC (roles/permissions/super-admin) system was introduced.
-- Fresh installations already include these columns/tables through
-- database/schema.sql and services/database_setup.py.
--
-- This migration is additive and non-destructive: it does not drop or
-- recreate any table. It does, however, deliberately change data on two
-- points so nobody is locked out after migrating:
--   1. The built-in 'admin' role is granted every permission in the new
--      catalog, matching its previous all-or-nothing access exactly.
--   2. Every existing user with the 'admin' role is promoted to
--      is_super_admin=1, since otherwise nobody could reach the new
--      Roles & Permissions page after this migration runs.

USE smart_street_food_safety;

-- 1. roles.is_system -- the 4 built-in roles can't be renamed/deleted
--    through the new Roles UI (many call sites still reference these
--    exact role_name strings outside the admin panel).
SET @roles_is_system_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'roles'
    AND column_name = 'is_system'
);

SET @roles_is_system_sql = IF(
  @roles_is_system_exists = 0,
  'ALTER TABLE roles ADD COLUMN is_system TINYINT(1) NOT NULL DEFAULT 0 AFTER description',
  'SELECT ''roles.is_system already exists'' AS migration_status'
);

PREPARE roles_is_system_stmt FROM @roles_is_system_sql;
EXECUTE roles_is_system_stmt;
DEALLOCATE PREPARE roles_is_system_stmt;

-- 2. roles.is_admin_tier -- does this role get into the admin panel at
--    all, independent of which permissions it holds.
SET @roles_is_admin_tier_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'roles'
    AND column_name = 'is_admin_tier'
);

SET @roles_is_admin_tier_sql = IF(
  @roles_is_admin_tier_exists = 0,
  'ALTER TABLE roles ADD COLUMN is_admin_tier TINYINT(1) NOT NULL DEFAULT 0 AFTER is_system',
  'SELECT ''roles.is_admin_tier already exists'' AS migration_status'
);

PREPARE roles_is_admin_tier_stmt FROM @roles_is_admin_tier_sql;
EXECUTE roles_is_admin_tier_stmt;
DEALLOCATE PREPARE roles_is_admin_tier_stmt;

-- 3. Mark the 4 built-in roles. 'admin' is the only one that is
--    admin-tier today; a super admin can promote a new custom role into
--    the admin panel later via the Roles UI.
UPDATE roles SET is_system = 1 WHERE role_name IN ('admin', 'vendor', 'inspector', 'customer');
UPDATE roles SET is_admin_tier = 1 WHERE role_name = 'admin';

-- 4. users.is_super_admin
SET @users_is_super_admin_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'is_super_admin'
);

SET @users_is_super_admin_sql = IF(
  @users_is_super_admin_exists = 0,
  'ALTER TABLE users ADD COLUMN is_super_admin TINYINT(1) NOT NULL DEFAULT 0 AFTER preferred_area_id',
  'SELECT ''users.is_super_admin already exists'' AS migration_status'
);

PREPARE users_is_super_admin_stmt FROM @users_is_super_admin_sql;
EXECUTE users_is_super_admin_stmt;
DEALLOCATE PREPARE users_is_super_admin_stmt;

-- 5. Bootstrap: every existing admin becomes a super admin so nobody is
--    locked out of role/permission management after this migration.
UPDATE users u
JOIN roles r ON r.role_id = u.role_id
SET u.is_super_admin = 1
WHERE r.role_name = 'admin';

-- 6. permissions table
CREATE TABLE IF NOT EXISTS permissions (
  permission_id INT NOT NULL AUTO_INCREMENT,
  code VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  PRIMARY KEY (permission_id),
  CONSTRAINT uq_permissions_code UNIQUE (code),
  CONSTRAINT chk_permissions_code_not_blank CHECK (CHAR_LENGTH(TRIM(code)) > 0)
) ENGINE=InnoDB;

-- 7. role_permissions junction table
CREATE TABLE IF NOT EXISTS role_permissions (
  role_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_role_permissions_role_id
    FOREIGN KEY (role_id) REFERENCES roles (role_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_role_permissions_permission_id
    FOREIGN KEY (permission_id) REFERENCES permissions (permission_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB;

-- 8. Seed the permission catalog (idempotent -- INSERT IGNORE on the
--    unique `code` column).
INSERT IGNORE INTO permissions (code, description) VALUES
  ('vendors.manage', 'Create, edit, and manage vendor accounts and stalls they own'),
  ('stalls.manage', 'Create, edit, and manage stalls'),
  ('users.manage', 'Create, edit, and manage user and inspector accounts'),
  ('complaints.manage', 'Review complaints and their evidence'),
  ('inspections.manage', 'Approve or reject submitted inspections'),
  ('reviews.manage', 'Moderate customer reviews'),
  ('risk_engine.view', 'View the risk engine dashboard'),
  ('reports.view', 'View analytics and reports'),
  ('settings.manage', 'Manage system settings'),
  ('roles.manage', 'Manage roles and permissions (super admin only)');

-- 9. Grant the built-in 'admin' role every permission, matching its
--    previous all-or-nothing access exactly.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
CROSS JOIN permissions p
WHERE r.role_name = 'admin';
