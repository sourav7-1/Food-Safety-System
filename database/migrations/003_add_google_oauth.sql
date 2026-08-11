-- Apply this migration to an existing database created before Google
-- "Continue with Google" sign-in was introduced. Fresh installations
-- already include these columns and constraints through
-- database/schema.sql.
--
-- This migration is additive and non-destructive: it does not drop or
-- recreate any table, and it does not touch existing rows other than
-- backfilling the new auth_provider column with its default ('local').

USE smart_street_food_safety;

-- 1. Add users.google_id (nullable, will carry a unique constraint below).
SET @google_id_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'google_id'
);

SET @google_id_migration_sql = IF(
  @google_id_column_exists = 0,
  'ALTER TABLE users ADD COLUMN google_id VARCHAR(255) NULL AFTER phone',
  'SELECT ''google_id already exists'' AS migration_status'
);

PREPARE google_id_migration_statement FROM @google_id_migration_sql;
EXECUTE google_id_migration_statement;
DEALLOCATE PREPARE google_id_migration_statement;

-- 2. Add users.auth_provider (defaults existing rows to 'local').
SET @auth_provider_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'auth_provider'
);

SET @auth_provider_migration_sql = IF(
  @auth_provider_column_exists = 0,
  'ALTER TABLE users ADD COLUMN auth_provider ENUM(''local'', ''google'') NOT NULL DEFAULT ''local'' AFTER google_id',
  'SELECT ''auth_provider already exists'' AS migration_status'
);

PREPARE auth_provider_migration_statement FROM @auth_provider_migration_sql;
EXECUTE auth_provider_migration_statement;
DEALLOCATE PREPARE auth_provider_migration_statement;

-- 3. Enforce one Google account cannot link to two local users.
SET @google_id_unique_exists = (
  SELECT COUNT(*)
  FROM information_schema.table_constraints
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND constraint_name = 'uq_users_google_id'
);

SET @google_id_unique_sql = IF(
  @google_id_unique_exists = 0,
  'ALTER TABLE users ADD CONSTRAINT uq_users_google_id UNIQUE (google_id)',
  'SELECT ''uq_users_google_id already exists'' AS migration_status'
);

PREPARE google_id_unique_statement FROM @google_id_unique_sql;
EXECUTE google_id_unique_statement;
DEALLOCATE PREPARE google_id_unique_statement;

-- 4. Google-only accounts have no local password: password_hash must
--    become nullable. chk_users_password_hash_not_blank is unaffected --
--    a NULL value satisfies a MySQL CHECK constraint (it only rejects
--    rows where the expression evaluates to FALSE, and a blank/whitespace
--    password_hash is still rejected whenever one is set).
SET @password_hash_nullable = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'password_hash'
    AND is_nullable = 'YES'
);

SET @password_hash_migration_sql = IF(
  @password_hash_nullable = 0,
  'ALTER TABLE users MODIFY COLUMN password_hash VARCHAR(255) NULL',
  'SELECT ''password_hash already nullable'' AS migration_status'
);

PREPARE password_hash_migration_statement FROM @password_hash_migration_sql;
EXECUTE password_hash_migration_statement;
DEALLOCATE PREPARE password_hash_migration_statement;

-- 5. Every user must still be able to authenticate somehow: require a
--    local password, a linked Google account, or both.
SET @password_or_google_check_exists = (
  SELECT COUNT(*)
  FROM information_schema.table_constraints
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND constraint_name = 'chk_users_password_or_google'
);

SET @password_or_google_check_sql = IF(
  @password_or_google_check_exists = 0,
  'ALTER TABLE users ADD CONSTRAINT chk_users_password_or_google CHECK (password_hash IS NOT NULL OR google_id IS NOT NULL)',
  'SELECT ''chk_users_password_or_google already exists'' AS migration_status'
);

PREPARE password_or_google_check_statement FROM @password_or_google_check_sql;
EXECUTE password_or_google_check_statement;
DEALLOCATE PREPARE password_or_google_check_statement;
