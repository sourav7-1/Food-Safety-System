-- MySQL 8.0+ inspection automation.
-- Install after database/schema.sql and database/functions.sql.
--
-- Weighted overall score:
--   SUM(score * weight) / SUM(max_score * weight) * 100
--
-- Risk and reinspection schedule:
--   85-100 low      -> 180 days
--   70-84  medium   ->  90 days
--   50-69  high     ->  30 days
--   0-49   critical ->   7 days

USE smart_street_food_safety;

DROP TRIGGER IF EXISTS trg_inspections_bi_reinspection;
DROP TRIGGER IF EXISTS trg_inspections_bu_reinspection;
DROP TRIGGER IF EXISTS trg_inspection_scores_ai_total;
DROP TRIGGER IF EXISTS trg_inspection_scores_au_total;
DROP TRIGGER IF EXISTS trg_inspection_scores_ad_total;
DROP TRIGGER IF EXISTS trg_inspection_scores_bi_validate;
DROP TRIGGER IF EXISTS trg_inspection_scores_bu_validate;
DROP TRIGGER IF EXISTS trg_corrective_actions_bi_source;
DROP TRIGGER IF EXISTS trg_corrective_actions_bu_source;

DELIMITER $$

CREATE TRIGGER trg_inspections_bi_reinspection
BEFORE INSERT ON inspections
FOR EACH ROW
BEGIN
  IF NEW.risk_level IS NULL THEN
    SET NEW.reinspection_date = NULL;
  ELSE
    SET NEW.reinspection_date = DATE_ADD(
      DATE(NEW.inspection_date),
      INTERVAL (
        CASE NEW.risk_level
          WHEN 'critical' THEN 7
          WHEN 'high' THEN 30
          WHEN 'medium' THEN 90
          WHEN 'low' THEN 180
        END
      ) DAY
    );
  END IF;
END$$

CREATE TRIGGER trg_corrective_actions_bi_source
BEFORE INSERT ON corrective_actions
FOR EACH ROW
BEGIN
  IF NEW.inspection_id IS NULL AND NEW.complaint_id IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT =
        'A corrective action requires an inspection or complaint source';
  END IF;
END$$

CREATE TRIGGER trg_corrective_actions_bu_source
BEFORE UPDATE ON corrective_actions
FOR EACH ROW
BEGIN
  IF NEW.inspection_id IS NULL AND NEW.complaint_id IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT =
        'A corrective action requires an inspection or complaint source';
  END IF;
END$$

CREATE TRIGGER trg_inspection_scores_bi_validate
BEFORE INSERT ON inspection_scores
FOR EACH ROW
BEGIN
  DECLARE v_max_score DECIMAL(5,2);
  DECLARE v_is_active BOOLEAN;

  SELECT max_score, is_active
    INTO v_max_score, v_is_active
    FROM inspection_criteria
   WHERE criteria_id = NEW.criteria_id;

  IF v_max_score IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Unknown inspection criterion';
  ELSEIF v_is_active = FALSE THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Cannot score an inactive inspection criterion';
  ELSEIF NEW.score < 0 OR NEW.score > v_max_score THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Inspection score is outside the allowed range';
  END IF;
END$$

CREATE TRIGGER trg_inspection_scores_bu_validate
BEFORE UPDATE ON inspection_scores
FOR EACH ROW
BEGIN
  DECLARE v_max_score DECIMAL(5,2);
  DECLARE v_is_active BOOLEAN;

  SELECT max_score, is_active
    INTO v_max_score, v_is_active
    FROM inspection_criteria
   WHERE criteria_id = NEW.criteria_id;

  IF v_max_score IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Unknown inspection criterion';
  ELSEIF v_is_active = FALSE THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Cannot score an inactive inspection criterion';
  ELSEIF NEW.score < 0 OR NEW.score > v_max_score THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Inspection score is outside the allowed range';
  END IF;
END$$

CREATE TRIGGER trg_inspections_bu_reinspection
BEFORE UPDATE ON inspections
FOR EACH ROW
BEGIN
  IF NEW.risk_level IS NULL THEN
    SET NEW.reinspection_date = NULL;
  ELSEIF NOT (NEW.risk_level <=> OLD.risk_level)
      OR NOT (NEW.inspection_date <=> OLD.inspection_date)
      OR NEW.reinspection_date IS NULL THEN
    SET NEW.reinspection_date = DATE_ADD(
      DATE(NEW.inspection_date),
      INTERVAL (
        CASE NEW.risk_level
          WHEN 'critical' THEN 7
          WHEN 'high' THEN 30
          WHEN 'medium' THEN 90
          WHEN 'low' THEN 180
        END
      ) DAY
    );
  END IF;
END$$

CREATE TRIGGER trg_inspection_scores_ai_total
AFTER INSERT ON inspection_scores
FOR EACH ROW
BEGIN
  DECLARE v_score DECIMAL(6,2);

  SELECT ROUND(
           100 * SUM(s.score * c.weight)
           / NULLIF(
               (
                 SELECT SUM(ca.max_score * ca.weight)
                 FROM inspection_criteria AS ca
                 WHERE ca.is_active = TRUE
               ),
               0
             ),
           2
         )
    INTO v_score
    FROM inspection_scores AS s
    INNER JOIN inspection_criteria AS c
      ON c.criteria_id = s.criteria_id
    WHERE s.inspection_id = NEW.inspection_id
      AND c.is_active = TRUE;

  UPDATE inspections
     SET overall_score = v_score,
         risk_level = CASE
           WHEN v_score IS NULL THEN NULL
           WHEN v_score >= 85.00 THEN 'low'
           WHEN v_score >= 70.00 THEN 'medium'
           WHEN v_score >= 50.00 THEN 'high'
           ELSE 'critical'
         END
   WHERE inspection_id = NEW.inspection_id;
END$$

CREATE TRIGGER trg_inspection_scores_au_total
AFTER UPDATE ON inspection_scores
FOR EACH ROW
BEGIN
  DECLARE v_score DECIMAL(6,2);
  DECLARE v_old_score DECIMAL(6,2);

  SELECT ROUND(
           100 * SUM(s.score * c.weight)
           / NULLIF(
               (
                 SELECT SUM(ca.max_score * ca.weight)
                 FROM inspection_criteria AS ca
                 WHERE ca.is_active = TRUE
               ),
               0
             ),
           2
         )
    INTO v_score
    FROM inspection_scores AS s
    INNER JOIN inspection_criteria AS c
      ON c.criteria_id = s.criteria_id
    WHERE s.inspection_id = NEW.inspection_id
      AND c.is_active = TRUE;

  UPDATE inspections
     SET overall_score = v_score,
         risk_level = CASE
           WHEN v_score IS NULL THEN NULL
           WHEN v_score >= 85.00 THEN 'low'
           WHEN v_score >= 70.00 THEN 'medium'
           WHEN v_score >= 50.00 THEN 'high'
           ELSE 'critical'
         END
   WHERE inspection_id = NEW.inspection_id;

  IF OLD.inspection_id <> NEW.inspection_id THEN
    SELECT ROUND(
             100 * SUM(s.score * c.weight)
             / NULLIF(
                 (
                   SELECT SUM(ca.max_score * ca.weight)
                   FROM inspection_criteria AS ca
                   WHERE ca.is_active = TRUE
                 ),
                 0
               ),
             2
           )
      INTO v_old_score
      FROM inspection_scores AS s
      INNER JOIN inspection_criteria AS c
        ON c.criteria_id = s.criteria_id
      WHERE s.inspection_id = OLD.inspection_id
        AND c.is_active = TRUE;

    UPDATE inspections
       SET overall_score = v_old_score,
           risk_level = CASE
             WHEN v_old_score IS NULL THEN NULL
             WHEN v_old_score >= 85.00 THEN 'low'
             WHEN v_old_score >= 70.00 THEN 'medium'
             WHEN v_old_score >= 50.00 THEN 'high'
             ELSE 'critical'
           END
     WHERE inspection_id = OLD.inspection_id;
  END IF;
END$$

CREATE TRIGGER trg_inspection_scores_ad_total
AFTER DELETE ON inspection_scores
FOR EACH ROW
BEGIN
  DECLARE v_score DECIMAL(6,2);

  SELECT ROUND(
           100 * SUM(s.score * c.weight)
           / NULLIF(
               (
                 SELECT SUM(ca.max_score * ca.weight)
                 FROM inspection_criteria AS ca
                 WHERE ca.is_active = TRUE
               ),
               0
             ),
           2
         )
    INTO v_score
    FROM inspection_scores AS s
    INNER JOIN inspection_criteria AS c
      ON c.criteria_id = s.criteria_id
    WHERE s.inspection_id = OLD.inspection_id
      AND c.is_active = TRUE;

  UPDATE inspections
     SET overall_score = v_score,
         risk_level = CASE
           WHEN v_score IS NULL THEN NULL
           WHEN v_score >= 85.00 THEN 'low'
           WHEN v_score >= 70.00 THEN 'medium'
           WHEN v_score >= 50.00 THEN 'high'
           ELSE 'critical'
         END
   WHERE inspection_id = OLD.inspection_id;
END$$

DELIMITER ;
