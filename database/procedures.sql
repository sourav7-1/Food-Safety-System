-- MySQL 8.0+ stored procedures.
-- Install after database/schema.sql and database/functions.sql.

USE smart_street_food_safety;

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

-- Example:
-- CALL calculate_stall_risk(1, @risk_level, @risk_score, @reinspection_date);
-- SELECT @risk_level, @risk_score, @reinspection_date;
