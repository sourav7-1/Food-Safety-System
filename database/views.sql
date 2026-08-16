-- MySQL 8.0+ reporting views.
-- Install after schema.sql, functions.sql, triggers.sql, and procedures.sql.

USE smart_street_food_safety;

CREATE OR REPLACE VIEW latest_stall_inspection AS
SELECT
  ranked.stall_id,
  ranked.stall_name,
  ranked.stall_code,
  ranked.area_id,
  ranked.area_name,
  ranked.city,
  ranked.zone,
  ranked.inspection_id,
  ranked.inspector_id,
  ranked.inspector_name,
  ranked.inspection_date,
  ranked.overall_score,
  get_hygiene_grade(ranked.overall_score) AS hygiene_grade,
  ranked.risk_level,
  ranked.reinspection_date,
  ranked.inspection_status,
  ranked.remarks
FROM (
  SELECT
    s.stall_id,
    s.stall_name,
    s.stall_code,
    a.area_id,
    a.area_name,
    a.city,
    a.zone,
    i.inspection_id,
    i.inspector_id,
    u.full_name AS inspector_name,
    i.inspection_date,
    i.overall_score,
    i.risk_level,
    i.reinspection_date,
    i.status AS inspection_status,
    i.remarks,
    ROW_NUMBER() OVER (
      PARTITION BY s.stall_id
      ORDER BY i.inspection_date DESC, i.inspection_id DESC
    ) AS row_num
  FROM stalls AS s
  INNER JOIN areas AS a
    ON a.area_id = s.area_id
  INNER JOIN inspections AS i
    ON i.stall_id = s.stall_id
   AND i.status IN ('submitted', 'approved')
  INNER JOIN inspectors AS inspector
    ON inspector.inspector_id = i.inspector_id
  INNER JOIN users AS u
    ON u.user_id = inspector.user_id
) AS ranked
WHERE ranked.row_num = 1;

CREATE OR REPLACE VIEW high_risk_stalls AS
SELECT
  lsi.stall_id,
  lsi.stall_name,
  lsi.stall_code,
  lsi.area_id,
  lsi.area_name,
  lsi.city,
  lsi.inspection_id,
  lsi.inspection_date,
  lsi.overall_score,
  lsi.hygiene_grade,
  lsi.risk_level,
  lsi.reinspection_date,
  CASE
    WHEN lsi.reinspection_date < CURRENT_DATE
      THEN DATEDIFF(CURRENT_DATE, lsi.reinspection_date)
    ELSE 0
  END AS days_overdue
FROM latest_stall_inspection AS lsi
WHERE lsi.risk_level IN ('high', 'critical');

CREATE OR REPLACE VIEW low_risk_stalls AS
SELECT
  lsi.stall_id,
  lsi.stall_name,
  lsi.stall_code,
  lsi.area_id,
  lsi.area_name,
  lsi.city,
  lsi.inspection_id,
  lsi.inspection_date,
  lsi.overall_score,
  lsi.hygiene_grade,
  lsi.risk_level,
  lsi.reinspection_date
FROM latest_stall_inspection AS lsi
WHERE lsi.risk_level = 'low';

CREATE OR REPLACE VIEW area_hygiene_summary AS
SELECT
  a.area_id,
  a.area_name,
  a.city,
  a.zone,
  COUNT(DISTINCT s.stall_id) AS total_stalls,
  COUNT(lsi.inspection_id) AS inspected_stalls,
  COUNT(DISTINCT s.stall_id) - COUNT(lsi.inspection_id)
    AS uninspected_stalls,
  ROUND(AVG(lsi.overall_score), 2) AS average_hygiene_score,
  get_hygiene_grade(AVG(lsi.overall_score)) AS area_hygiene_grade,
  SUM(CASE WHEN lsi.risk_level = 'low' THEN 1 ELSE 0 END)
    AS low_risk_stalls,
  SUM(CASE WHEN lsi.risk_level = 'medium' THEN 1 ELSE 0 END)
    AS medium_risk_stalls,
  SUM(CASE WHEN lsi.risk_level = 'high' THEN 1 ELSE 0 END)
    AS high_risk_stalls,
  SUM(CASE WHEN lsi.risk_level = 'critical' THEN 1 ELSE 0 END)
    AS critical_risk_stalls
FROM areas AS a
LEFT JOIN stalls AS s
  ON s.area_id = a.area_id
 AND s.status = 'active'
LEFT JOIN latest_stall_inspection AS lsi
  ON lsi.stall_id = s.stall_id
GROUP BY a.area_id, a.area_name, a.city, a.zone;

CREATE OR REPLACE VIEW pending_reinspection AS
SELECT
  lsi.stall_id,
  lsi.stall_name,
  lsi.stall_code,
  lsi.area_id,
  lsi.area_name,
  lsi.city,
  lsi.inspection_id,
  lsi.inspection_date AS last_inspection_date,
  lsi.overall_score,
  lsi.hygiene_grade,
  lsi.risk_level,
  lsi.reinspection_date,
  DATEDIFF(lsi.reinspection_date, CURRENT_DATE) AS days_until_due,
  CASE
    WHEN lsi.reinspection_date < CURRENT_DATE THEN 'overdue'
    WHEN lsi.reinspection_date = CURRENT_DATE THEN 'due_today'
    ELSE 'scheduled'
  END AS reinspection_status
FROM latest_stall_inspection AS lsi
INNER JOIN stalls AS s
  ON s.stall_id = lsi.stall_id
WHERE s.status = 'active'
  AND lsi.reinspection_date IS NOT NULL;

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
