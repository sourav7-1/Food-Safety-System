-- MySQL 8.0+ scalar functions.
-- Install after database/schema.sql and before triggers.sql, procedures.sql,
-- and views.sql.

USE smart_street_food_safety;

DROP FUNCTION IF EXISTS get_hygiene_grade;

DELIMITER $$

CREATE FUNCTION get_hygiene_grade(p_score DECIMAL(6,2))
RETURNS CHAR(1)
DETERMINISTIC
NO SQL
BEGIN
  RETURN CASE
    WHEN p_score IS NULL THEN NULL
    WHEN p_score >= 85.00 THEN 'A'
    WHEN p_score >= 70.00 THEN 'B'
    WHEN p_score >= 50.00 THEN 'C'
    ELSE 'D'
  END;
END$$

DELIMITER ;
