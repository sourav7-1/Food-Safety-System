-- Apply this migration to an existing database created before evidence
-- uploads were introduced. Fresh installations already include the column
-- through database/schema.sql.

USE smart_street_food_safety;

SET @evidence_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'corrective_actions'
    AND column_name = 'evidence_path'
);

SET @evidence_migration_sql = IF(
  @evidence_column_exists = 0,
  'ALTER TABLE corrective_actions ADD COLUMN evidence_path VARCHAR(500) NULL AFTER completion_notes',
  'SELECT ''evidence_path already exists'' AS migration_status'
);

PREPARE evidence_migration_statement FROM @evidence_migration_sql;
EXECUTE evidence_migration_statement;
DEALLOCATE PREPARE evidence_migration_statement;
