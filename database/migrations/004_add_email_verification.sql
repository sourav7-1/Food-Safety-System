-- Apply this migration to an existing database created before mandatory
-- email verification was introduced for locally-registered accounts.
-- Fresh installations already include this column through
-- database/schema.sql.
--
-- This migration is additive and non-destructive: it does not drop or
-- recreate any table. Existing users are backfilled as already verified
-- (using their created_at timestamp) so nobody already registered is
-- locked out of an account they could log in to before this migration.

USE smart_street_food_safety;

-- 1. Add users.email_verified_at (nullable; NULL means "not verified yet").
SET @email_verified_at_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'email_verified_at'
);

SET @email_verified_at_migration_sql = IF(
  @email_verified_at_column_exists = 0,
  'ALTER TABLE users ADD COLUMN email_verified_at DATETIME NULL AFTER status',
  'SELECT ''email_verified_at already exists'' AS migration_status'
);

PREPARE email_verified_at_migration_statement FROM @email_verified_at_migration_sql;
EXECUTE email_verified_at_migration_statement;
DEALLOCATE PREPARE email_verified_at_migration_statement;

-- 2. Grandfather in every account that existed before this migration.
UPDATE users
SET email_verified_at = created_at
WHERE email_verified_at IS NULL;
