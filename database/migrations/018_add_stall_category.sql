-- Apply this migration to a database created before stalls carried a
-- category (street stall / food court / hall canteen). Fresh
-- installations already include the column through database/schema.sql.
--
-- All existing rows default to 'street_stall' -- that is a placeholder,
-- not a verified fact about any existing stall. An administrator should
-- review current stalls after this runs and correct any that are
-- actually a food court or hall canteen entry via the stall edit form.
--
-- category is a display/filter concept only: every category still goes
-- through the exact same inspection workflow and get_hygiene_grade
-- logic (database/functions.sql) as before, so no other table or
-- routine changes.

USE smart_street_food_safety;

SET @stall_category_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'stalls'
    AND column_name = 'category'
);

SET @stall_category_column_sql = IF(
  @stall_category_column_exists = 0,
  "ALTER TABLE stalls ADD COLUMN category ENUM('street_stall', 'food_court', 'hall_canteen') NOT NULL DEFAULT 'street_stall' AFTER longitude",
  'SELECT ''stalls.category already exists'' AS migration_status'
);

PREPARE stall_category_column_statement FROM @stall_category_column_sql;
EXECUTE stall_category_column_statement;
DEALLOCATE PREPARE stall_category_column_statement;

SET @stall_category_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'stalls'
    AND index_name = 'idx_stalls_category'
);

SET @stall_category_index_sql = IF(
  @stall_category_index_exists = 0,
  'CREATE INDEX idx_stalls_category ON stalls (category)',
  'SELECT ''idx_stalls_category already exists'' AS migration_status'
);

PREPARE stall_category_index_statement FROM @stall_category_index_sql;
EXECUTE stall_category_index_statement;
DEALLOCATE PREPARE stall_category_index_statement;
