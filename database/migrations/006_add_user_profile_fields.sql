-- Apply this migration to an existing database created before the
-- customer profile dashboard was introduced. Fresh installations already
-- include these columns and constraint through database/schema.sql.
--
-- This migration is additive and non-destructive: it does not drop or
-- recreate any table, and it does not touch any existing row. Note that
-- users.updated_at already exists (added when the app first shipped) so
-- it is not part of this migration.

USE smart_street_food_safety;

-- 1. users.profile_photo_url
SET @profile_photo_url_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'profile_photo_url'
);

SET @profile_photo_url_sql = IF(
  @profile_photo_url_exists = 0,
  'ALTER TABLE users ADD COLUMN profile_photo_url VARCHAR(255) NULL AFTER email_verified_at',
  'SELECT ''profile_photo_url already exists'' AS migration_status'
);

PREPARE profile_photo_url_stmt FROM @profile_photo_url_sql;
EXECUTE profile_photo_url_stmt;
DEALLOCATE PREPARE profile_photo_url_stmt;

-- 2. users.bio
SET @bio_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'bio'
);

SET @bio_sql = IF(
  @bio_exists = 0,
  'ALTER TABLE users ADD COLUMN bio TEXT NULL AFTER profile_photo_url',
  'SELECT ''bio already exists'' AS migration_status'
);

PREPARE bio_stmt FROM @bio_sql;
EXECUTE bio_stmt;
DEALLOCATE PREPARE bio_stmt;

-- 3. users.address
SET @address_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'address'
);

SET @address_sql = IF(
  @address_exists = 0,
  'ALTER TABLE users ADD COLUMN address VARCHAR(255) NULL AFTER bio',
  'SELECT ''address already exists'' AS migration_status'
);

PREPARE address_stmt FROM @address_sql;
EXECUTE address_stmt;
DEALLOCATE PREPARE address_stmt;

-- 4. users.date_of_birth
SET @date_of_birth_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'date_of_birth'
);

SET @date_of_birth_sql = IF(
  @date_of_birth_exists = 0,
  'ALTER TABLE users ADD COLUMN date_of_birth DATE NULL AFTER address',
  'SELECT ''date_of_birth already exists'' AS migration_status'
);

PREPARE date_of_birth_stmt FROM @date_of_birth_sql;
EXECUTE date_of_birth_stmt;
DEALLOCATE PREPARE date_of_birth_stmt;

-- 5. users.preferred_area_id (nullable FK, added before its constraint)
SET @preferred_area_id_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND column_name = 'preferred_area_id'
);

SET @preferred_area_id_sql = IF(
  @preferred_area_id_exists = 0,
  'ALTER TABLE users ADD COLUMN preferred_area_id INT NULL AFTER date_of_birth',
  'SELECT ''preferred_area_id already exists'' AS migration_status'
);

PREPARE preferred_area_id_stmt FROM @preferred_area_id_sql;
EXECUTE preferred_area_id_stmt;
DEALLOCATE PREPARE preferred_area_id_stmt;

-- 6. Index + foreign key on preferred_area_id -> areas(area_id).
SET @preferred_area_id_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND index_name = 'idx_users_preferred_area_id'
);

SET @preferred_area_id_index_sql = IF(
  @preferred_area_id_index_exists = 0,
  'CREATE INDEX idx_users_preferred_area_id ON users (preferred_area_id)',
  'SELECT ''idx_users_preferred_area_id already exists'' AS migration_status'
);

PREPARE preferred_area_id_index_stmt FROM @preferred_area_id_index_sql;
EXECUTE preferred_area_id_index_stmt;
DEALLOCATE PREPARE preferred_area_id_index_stmt;

SET @preferred_area_id_fk_exists = (
  SELECT COUNT(*)
  FROM information_schema.table_constraints
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND constraint_name = 'fk_users_preferred_area_id'
);

SET @preferred_area_id_fk_sql = IF(
  @preferred_area_id_fk_exists = 0,
  'ALTER TABLE users ADD CONSTRAINT fk_users_preferred_area_id FOREIGN KEY (preferred_area_id) REFERENCES areas (area_id) ON UPDATE CASCADE ON DELETE SET NULL',
  'SELECT ''fk_users_preferred_area_id already exists'' AS migration_status'
);

PREPARE preferred_area_id_fk_stmt FROM @preferred_area_id_fk_sql;
EXECUTE preferred_area_id_fk_stmt;
DEALLOCATE PREPARE preferred_area_id_fk_stmt;
