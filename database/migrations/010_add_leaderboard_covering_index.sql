-- Apply this migration to a database created before the Risk Leaderboard
-- feature. Fresh installations already include this index through
-- database/schema.sql.
--
-- latest_stall_inspection (database/views.sql) runs a ROW_NUMBER() window
-- function partitioned by stall_id, ordered by inspection_date/inspection_id,
-- filtered on status. Both the High Risk and Low Risk leaderboard boards
-- read from that view (directly, or via high_risk_stalls/low_risk_stalls),
-- so this composite index lets MySQL satisfy the partition/order/filter
-- from the index instead of a temporary table + filesort per stall.

USE smart_street_food_safety;

SET @leaderboard_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'inspections'
    AND index_name = 'idx_inspections_stall_status_date'
);

SET @leaderboard_index_sql = IF(
  @leaderboard_index_exists = 0,
  'CREATE INDEX idx_inspections_stall_status_date ON inspections (stall_id, status, inspection_date, inspection_id)',
  'SELECT ''idx_inspections_stall_status_date already exists'' AS migration_status'
);

PREPARE leaderboard_index_statement FROM @leaderboard_index_sql;
EXECUTE leaderboard_index_statement;
DEALLOCATE PREPARE leaderboard_index_statement;
