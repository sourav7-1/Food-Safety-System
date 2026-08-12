-- Apply this migration to an existing database created before the
-- complaint evidence system and the richer complaint status workflow.
-- Fresh installations already include these tables and this enum through
-- database/schema.sql, database/procedures.sql, and database/views.sql.
--
-- This migration is additive where possible. The one non-additive part is
-- widening complaints.status: the old 4-value enum ('open', 'under_review',
-- 'resolved', 'rejected') becomes 7 values ('submitted', 'under_review',
-- 'investigation', 'action_required', 'resolved', 'rejected', 'closed').
-- Existing rows are preserved and re-mapped ('open' -> 'submitted', every
-- other existing value keeps its name), so no complaint changes meaning
-- and nothing is deleted.

USE smart_street_food_safety;

-- 1. Widen complaints.status to the 7-value workflow.
SET @complaints_status_type = (
  SELECT COLUMN_TYPE
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'complaints'
    AND column_name = 'status'
);

SET @complaints_status_migration_sql = IF(
  @complaints_status_type NOT LIKE '%investigation%',
  "ALTER TABLE complaints MODIFY COLUMN status ENUM('submitted', 'under_review', 'investigation', 'action_required', 'resolved', 'rejected', 'closed') NOT NULL DEFAULT 'submitted'",
  'SELECT ''complaints.status already widened'' AS migration_status'
);

PREPARE complaints_status_migration_statement FROM @complaints_status_migration_sql;
EXECUTE complaints_status_migration_statement;
DEALLOCATE PREPARE complaints_status_migration_statement;

-- 2. Re-map the old 'open' value to 'submitted' (safe to run repeatedly;
--    a no-op once every row has already been migrated).
UPDATE complaints SET status = 'submitted' WHERE status = 'open';

-- 3. Evidence metadata table (file contents live on disk, not in MySQL).
CREATE TABLE IF NOT EXISTS complaint_evidence (
  evidence_id INT NOT NULL AUTO_INCREMENT,
  complaint_id INT NOT NULL,
  uploaded_by INT NULL,
  file_name VARCHAR(255) NOT NULL,
  stored_file_name VARCHAR(255) NOT NULL,
  file_type ENUM('image', 'video', 'audio', 'document') NOT NULL,
  mime_type VARCHAR(150) NOT NULL,
  file_size INT UNSIGNED NOT NULL,
  storage_path VARCHAR(500) NOT NULL,
  file_hash CHAR(64) NOT NULL,
  evidence_description VARCHAR(500) NULL,
  uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  verification_status ENUM('pending', 'under_review', 'verified', 'rejected') NOT NULL DEFAULT 'pending',
  verified_by INT NULL,
  verified_at TIMESTAMP NULL,
  rejection_reason VARCHAR(500) NULL,
  PRIMARY KEY (evidence_id),
  CONSTRAINT chk_complaint_evidence_file_name_not_blank CHECK (CHAR_LENGTH(TRIM(file_name)) > 0),
  CONSTRAINT chk_complaint_evidence_file_size_positive CHECK (file_size > 0),
  CONSTRAINT chk_complaint_evidence_file_hash_length CHECK (CHAR_LENGTH(file_hash) = 64),
  CONSTRAINT fk_complaint_evidence_complaint_id
    FOREIGN KEY (complaint_id) REFERENCES complaints (complaint_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_complaint_evidence_uploaded_by
    FOREIGN KEY (uploaded_by) REFERENCES users (user_id)
    ON UPDATE CASCADE
    ON DELETE SET NULL,
  CONSTRAINT fk_complaint_evidence_verified_by
    FOREIGN KEY (verified_by) REFERENCES users (user_id)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_complaint_evidence_complaint_id ON complaint_evidence (complaint_id);
CREATE INDEX idx_complaint_evidence_uploaded_by ON complaint_evidence (uploaded_by);
CREATE INDEX idx_complaint_evidence_verification_status ON complaint_evidence (verification_status);

-- 4. Audit trail for every sensitive evidence action.
CREATE TABLE IF NOT EXISTS evidence_audit_logs (
  audit_id INT NOT NULL AUTO_INCREMENT,
  evidence_id INT NOT NULL,
  user_id INT NULL,
  action ENUM('uploaded', 'viewed', 'downloaded', 'marked_under_review', 'verified', 'rejected') NOT NULL,
  action_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip_address VARCHAR(45) NULL,
  user_agent VARCHAR(255) NULL,
  details VARCHAR(255) NULL,
  PRIMARY KEY (audit_id),
  CONSTRAINT fk_evidence_audit_logs_evidence_id
    FOREIGN KEY (evidence_id) REFERENCES complaint_evidence (evidence_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_evidence_audit_logs_user_id
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_evidence_audit_logs_evidence_id ON evidence_audit_logs (evidence_id);
CREATE INDEX idx_evidence_audit_logs_action_time ON evidence_audit_logs (action_time);

-- 5. Recreate calculate_stall_risk so its complaint-penalty subquery covers
--    every non-terminal status in the new 7-value workflow (previously
--    just 'open' and 'under_review').
DROP PROCEDURE IF EXISTS calculate_stall_risk;

DELIMITER $$

CREATE PROCEDURE calculate_stall_risk(
  IN p_stall_id INT,
  OUT p_risk_level VARCHAR(10),
  OUT p_risk_score DECIMAL(6,2),
  OUT p_reinspection_date DATE
)
BEGIN
  DECLARE v_stall_exists INT DEFAULT 0;
  DECLARE v_inspection_date DATETIME DEFAULT NULL;
  DECLARE v_inspection_score DECIMAL(6,2) DEFAULT NULL;
  DECLARE v_complaint_penalty DECIMAL(6,2) DEFAULT 0.00;

  SELECT COUNT(*)
    INTO v_stall_exists
    FROM stalls
   WHERE stall_id = p_stall_id;

  IF v_stall_exists = 0 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Unknown stall_id';
  END IF;

  SELECT i.inspection_date, i.overall_score
    INTO v_inspection_date, v_inspection_score
    FROM inspections AS i
   WHERE i.stall_id = p_stall_id
     AND i.status IN ('submitted', 'approved')
     AND i.overall_score IS NOT NULL
   ORDER BY i.inspection_date DESC, i.inspection_id DESC
   LIMIT 1;

  SELECT LEAST(
           40.00,
           COALESCE(
             SUM(
               CASE ct.severity_level
                 WHEN 'critical' THEN 20.00
                 WHEN 'high' THEN 12.00
                 WHEN 'medium' THEN 6.00
                 WHEN 'low' THEN 2.00
               END
             ),
             0.00
           )
         )
    INTO v_complaint_penalty
    FROM complaints AS c
    INNER JOIN complaint_types AS ct
      ON ct.complaint_type_id = c.complaint_type_id
   WHERE c.stall_id = p_stall_id
     AND c.status IN ('submitted', 'under_review', 'investigation', 'action_required');

  -- No eligible inspection is treated as unverified and therefore critical.
  SET p_risk_score = GREATEST(
    0.00,
    COALESCE(v_inspection_score, 0.00) - v_complaint_penalty
  );

  SET p_risk_level = CASE
    WHEN p_risk_score >= 85.00 THEN 'low'
    WHEN p_risk_score >= 70.00 THEN 'medium'
    WHEN p_risk_score >= 50.00 THEN 'high'
    ELSE 'critical'
  END;

  SET p_reinspection_date = DATE_ADD(
    DATE(COALESCE(v_inspection_date, CURRENT_DATE)),
    INTERVAL (
      CASE p_risk_level
        WHEN 'critical' THEN 7
        WHEN 'high' THEN 30
        WHEN 'medium' THEN 90
        WHEN 'low' THEN 180
      END
    ) DAY
  );
END$$

DELIMITER ;

-- 6. Recreate complaint_summary with the new status breakdown.
CREATE OR REPLACE VIEW complaint_summary AS
SELECT
  s.stall_id,
  s.stall_name,
  s.stall_code,
  a.area_id,
  a.area_name,
  COUNT(c.complaint_id) AS total_complaints,
  SUM(CASE WHEN c.status = 'submitted' THEN 1 ELSE 0 END)
    AS submitted_complaints,
  SUM(CASE WHEN c.status IN ('under_review', 'investigation', 'action_required') THEN 1 ELSE 0 END)
    AS complaints_under_review,
  SUM(CASE WHEN c.status = 'resolved' THEN 1 ELSE 0 END)
    AS resolved_complaints,
  SUM(CASE WHEN c.status = 'rejected' THEN 1 ELSE 0 END)
    AS rejected_complaints,
  SUM(CASE WHEN c.status = 'closed' THEN 1 ELSE 0 END)
    AS closed_complaints,
  SUM(
    CASE
      WHEN c.status IN ('submitted', 'under_review', 'investigation', 'action_required')
       AND ct.severity_level IN ('high', 'critical')
      THEN 1 ELSE 0
    END
  ) AS unresolved_high_severity_complaints,
  MAX(c.submitted_at) AS latest_complaint_at,
  MAX(c.resolved_at) AS latest_resolution_at
FROM stalls AS s
INNER JOIN areas AS a
  ON a.area_id = s.area_id
LEFT JOIN complaints AS c
  ON c.stall_id = s.stall_id
LEFT JOIN complaint_types AS ct
  ON ct.complaint_type_id = c.complaint_type_id
GROUP BY
  s.stall_id,
  s.stall_name,
  s.stall_code,
  a.area_id,
  a.area_name;
