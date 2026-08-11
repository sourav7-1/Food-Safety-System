-- Apply this migration to an existing database created before stalls
-- carried a photo. Fresh installations already include the column
-- through database/schema.sql.

USE smart_street_food_safety;

SET @photo_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'stalls'
    AND column_name = 'photo_url'
);

SET @photo_migration_sql = IF(
  @photo_column_exists = 0,
  'ALTER TABLE stalls ADD COLUMN photo_url VARCHAR(1000) NULL AFTER longitude',
  'SELECT ''photo_url already exists'' AS migration_status'
);

PREPARE photo_migration_statement FROM @photo_migration_sql;
EXECUTE photo_migration_statement;
DEALLOCATE PREPARE photo_migration_statement;
