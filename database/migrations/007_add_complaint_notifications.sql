-- Apply this migration to an existing database created before complaint
-- tracking notifications and admin response messages were introduced.
-- Fresh installations already include this column and table through
-- database/schema.sql.
--
-- This migration is additive and non-destructive: it does not drop or
-- recreate any table, and it does not touch any existing row.

USE smart_street_food_safety;

-- 1. complaints.admin_response -- the admin's free-text message to the
--    customer about this complaint, shown on the customer's tracking page.
SET @admin_response_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'complaints'
    AND column_name = 'admin_response'
);

SET @admin_response_sql = IF(
  @admin_response_exists = 0,
  'ALTER TABLE complaints ADD COLUMN admin_response TEXT NULL AFTER resolved_at',
  'SELECT ''admin_response already exists'' AS migration_status'
);

PREPARE admin_response_stmt FROM @admin_response_sql;
EXECUTE admin_response_stmt;
DEALLOCATE PREPARE admin_response_stmt;

-- 2. notifications table -- in-app notifications sent to a customer when
--    their complaint's status changes or an admin leaves a response.
CREATE TABLE IF NOT EXISTS notifications (
  notification_id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  complaint_id INT NULL,
  message VARCHAR(255) NOT NULL,
  is_read TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (notification_id),
  CONSTRAINT chk_notifications_message_not_blank CHECK (CHAR_LENGTH(TRIM(message)) > 0),
  CONSTRAINT fk_notifications_user_id
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_notifications_complaint_id
    FOREIGN KEY (complaint_id) REFERENCES complaints (complaint_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB;

-- CREATE INDEX has no IF NOT EXISTS in MySQL, so guard it manually like
-- every other index added by these migrations.
SET @notifications_user_read_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'notifications'
    AND index_name = 'idx_notifications_user_id_is_read'
);

SET @notifications_user_read_index_sql = IF(
  @notifications_user_read_index_exists = 0,
  'CREATE INDEX idx_notifications_user_id_is_read ON notifications (user_id, is_read)',
  'SELECT ''idx_notifications_user_id_is_read already exists'' AS migration_status'
);

PREPARE notifications_user_read_index_stmt FROM @notifications_user_read_index_sql;
EXECUTE notifications_user_read_index_stmt;
DEALLOCATE PREPARE notifications_user_read_index_stmt;

SET @notifications_created_at_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'notifications'
    AND index_name = 'idx_notifications_created_at'
);

SET @notifications_created_at_index_sql = IF(
  @notifications_created_at_index_exists = 0,
  'CREATE INDEX idx_notifications_created_at ON notifications (created_at)',
  'SELECT ''idx_notifications_created_at already exists'' AS migration_status'
);

PREPARE notifications_created_at_index_stmt FROM @notifications_created_at_index_sql;
EXECUTE notifications_created_at_index_stmt;
DEALLOCATE PREPARE notifications_created_at_index_stmt;
