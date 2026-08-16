-- Apply this migration to a database that already ran migration 008
-- (the 10 coarse "<resource>.manage" permission codes). It replaces
-- them with a CRUD-level breakdown (view/create/edit/delete, plus a
-- couple of resource-specific splits) so roles can be scoped much more
-- precisely -- e.g. "can view vendors but never delete one."
--
-- Fresh installations never see the old coarse codes at all --
-- services/database_setup.py seeds the fine-grained catalog directly.
--
-- Non-destructive with respect to *rows*: no table is dropped. It does,
-- however, delete the 7 superseded permission rows once every role that
-- held one has been re-granted the equivalent new permissions, so no
-- role loses access it had before this migration ran.

USE smart_street_food_safety;

-- 1. Seed every new/renamed permission code (idempotent).
INSERT IGNORE INTO permissions (code, description) VALUES
  ('vendors.view', 'View vendor accounts'),
  ('vendors.create', 'Create vendor accounts'),
  ('vendors.edit', 'Edit vendor accounts'),
  ('vendors.delete', 'Delete vendor accounts'),
  ('stalls.view', 'View stalls'),
  ('stalls.create', 'Create stalls'),
  ('stalls.edit', 'Edit stalls'),
  ('stalls.delete', 'Delete stalls'),
  ('users.view', 'View user accounts'),
  ('users.create', 'Create user accounts'),
  ('users.edit', 'Edit user accounts'),
  ('users.status', 'Activate, suspend, or disable user accounts'),
  ('users.inspectors', 'Create and edit inspector accounts specifically'),
  ('complaints.view', 'View complaints'),
  ('complaints.respond', 'Change a complaint''s status or add a response'),
  ('complaints.evidence', 'Verify or reject complaint evidence'),
  ('inspections.view', 'View submitted inspections'),
  ('inspections.approve', 'Approve submitted inspections'),
  ('inspections.reject', 'Reject submitted inspections'),
  ('reviews.view', 'View customer reviews'),
  ('reviews.moderate', 'Hide, flag, or restore customer reviews'),
  ('settings.view', 'View system settings and reference data');

-- 2. Re-grant: every role that held an old coarse code gets all the new
--    codes that replace it, before the old code is deleted.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'vendors.manage'
CROSS JOIN permissions p_new
WHERE p_new.code IN ('vendors.view', 'vendors.create', 'vendors.edit', 'vendors.delete');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'stalls.manage'
CROSS JOIN permissions p_new
WHERE p_new.code IN ('stalls.view', 'stalls.create', 'stalls.edit', 'stalls.delete');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'users.manage'
CROSS JOIN permissions p_new
WHERE p_new.code IN ('users.view', 'users.create', 'users.edit', 'users.status', 'users.inspectors');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'complaints.manage'
CROSS JOIN permissions p_new
WHERE p_new.code IN ('complaints.view', 'complaints.respond', 'complaints.evidence');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'inspections.manage'
CROSS JOIN permissions p_new
WHERE p_new.code IN ('inspections.view', 'inspections.approve', 'inspections.reject');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'reviews.manage'
CROSS JOIN permissions p_new
WHERE p_new.code IN ('reviews.view', 'reviews.moderate');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, p_new.permission_id
FROM role_permissions rp
JOIN permissions p_old ON p_old.permission_id = rp.permission_id AND p_old.code = 'settings.manage'
CROSS JOIN permissions p_new
WHERE p_new.code = 'settings.view';

-- 3. Remove the superseded coarse codes. This cascades to delete any
--    remaining role_permissions rows referencing them (all such grants
--    were already replaced with fine-grained equivalents above).
DELETE FROM permissions
WHERE code IN (
  'vendors.manage', 'stalls.manage', 'users.manage', 'complaints.manage',
  'inspections.manage', 'reviews.manage', 'settings.manage'
);
