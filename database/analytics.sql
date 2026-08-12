-- Smart Street Food Safety analytical query library
-- MySQL 8.0+; run after schema, advanced routines, and operational data.

USE smart_street_food_safety;

-- 1. Lowest average hygiene area.
-- Uses only the latest submitted/approved inspection for each stall so areas
-- with frequently inspected stalls are not over-weighted.
WITH ranked_inspections AS (
  SELECT
    i.stall_id,
    i.overall_score,
    ROW_NUMBER() OVER (
      PARTITION BY i.stall_id
      ORDER BY i.inspection_date DESC, i.inspection_id DESC
    ) AS row_num
  FROM inspections AS i
  WHERE i.status IN ('submitted', 'approved')
    AND i.overall_score IS NOT NULL
)
SELECT
  a.area_id,
  a.area_name,
  a.city,
  COUNT(ri.stall_id) AS inspected_stalls,
  ROUND(AVG(ri.overall_score), 2) AS average_hygiene_score,
  get_hygiene_grade(AVG(ri.overall_score)) AS hygiene_grade
FROM areas AS a
INNER JOIN stalls AS s
  ON s.area_id = a.area_id
INNER JOIN ranked_inspections AS ri
  ON ri.stall_id = s.stall_id
 AND ri.row_num = 1
GROUP BY a.area_id, a.area_name, a.city
ORDER BY average_hygiene_score ASC
LIMIT 1;

-- 2. Complaint volume versus latest inspection score.
-- Useful for identifying stalls whose official score conflicts with customer
-- reports or whose complaint burden confirms a weak inspection result.
WITH ranked_inspections AS (
  SELECT
    i.stall_id,
    i.overall_score,
    i.risk_level,
    i.inspection_date,
    ROW_NUMBER() OVER (
      PARTITION BY i.stall_id
      ORDER BY i.inspection_date DESC, i.inspection_id DESC
    ) AS row_num
  FROM inspections AS i
  WHERE i.status IN ('submitted', 'approved')
),
complaint_totals AS (
  SELECT
    c.stall_id,
    COUNT(*) AS total_complaints,
    SUM(c.status IN ('submitted', 'under_review', 'investigation', 'action_required')) AS unresolved_complaints,
    SUM(ct.severity_level IN ('high', 'critical')) AS severe_complaints
  FROM complaints AS c
  INNER JOIN complaint_types AS ct
    ON ct.complaint_type_id = c.complaint_type_id
  GROUP BY c.stall_id
)
SELECT
  s.stall_id,
  s.stall_name,
  ri.overall_score AS latest_hygiene_score,
  ri.risk_level,
  COALESCE(ct.total_complaints, 0) AS total_complaints,
  COALESCE(ct.unresolved_complaints, 0) AS unresolved_complaints,
  COALESCE(ct.severe_complaints, 0) AS severe_complaints
FROM stalls AS s
LEFT JOIN ranked_inspections AS ri
  ON ri.stall_id = s.stall_id
 AND ri.row_num = 1
LEFT JOIN complaint_totals AS ct
  ON ct.stall_id = s.stall_id
WHERE ri.stall_id IS NOT NULL OR ct.stall_id IS NOT NULL
ORDER BY total_complaints DESC, latest_hygiene_score ASC;

-- 3. Most frequently failed inspection criterion.
-- A score below 50 percent of the criterion maximum is counted as a failure.
SELECT
  ic.criteria_id,
  ic.criteria_name,
  COUNT(isc.score_id) AS times_scored,
  SUM(isc.score < ic.max_score * 0.50) AS failure_count,
  ROUND(
    100 * SUM(isc.score < ic.max_score * 0.50)
    / NULLIF(COUNT(isc.score_id), 0),
    2
  ) AS failure_rate_percent,
  ROUND(AVG(100 * isc.score / ic.max_score), 2)
    AS average_attainment_percent
FROM inspection_criteria AS ic
INNER JOIN inspection_scores AS isc
  ON isc.criteria_id = ic.criteria_id
INNER JOIN inspections AS i
  ON i.inspection_id = isc.inspection_id
WHERE i.status IN ('submitted', 'approved')
GROUP BY ic.criteria_id, ic.criteria_name
ORDER BY failure_count DESC, failure_rate_percent DESC
LIMIT 1;

-- 4. Reinspection improvement.
-- Compares each inspection with the immediately preceding inspection for the
-- same stall and reports both score and risk movement.
WITH inspection_sequence AS (
  SELECT
    i.inspection_id,
    i.stall_id,
    i.inspection_date,
    i.overall_score,
    i.risk_level,
    LAG(i.inspection_id) OVER (
      PARTITION BY i.stall_id
      ORDER BY i.inspection_date, i.inspection_id
    ) AS previous_inspection_id,
    LAG(i.inspection_date) OVER (
      PARTITION BY i.stall_id
      ORDER BY i.inspection_date, i.inspection_id
    ) AS previous_inspection_date,
    LAG(i.overall_score) OVER (
      PARTITION BY i.stall_id
      ORDER BY i.inspection_date, i.inspection_id
    ) AS previous_score,
    LAG(i.risk_level) OVER (
      PARTITION BY i.stall_id
      ORDER BY i.inspection_date, i.inspection_id
    ) AS previous_risk_level
  FROM inspections AS i
  WHERE i.status IN ('submitted', 'approved')
    AND i.overall_score IS NOT NULL
)
SELECT
  s.stall_id,
  s.stall_name,
  seq.previous_inspection_id,
  seq.inspection_id AS reinspection_id,
  seq.previous_score,
  seq.overall_score AS reinspection_score,
  ROUND(seq.overall_score - seq.previous_score, 2)
    AS score_improvement,
  seq.previous_risk_level,
  seq.risk_level AS current_risk_level,
  DATEDIFF(seq.inspection_date, seq.previous_inspection_date)
    AS days_between_inspections
FROM inspection_sequence AS seq
INNER JOIN stalls AS s
  ON s.stall_id = seq.stall_id
WHERE seq.previous_inspection_id IS NOT NULL
ORDER BY score_improvement DESC;

-- 5. Vendors with repeated failures.
-- Repeated failure means at least two submitted/approved inspections below
-- 50 percent or classified as high/critical.
SELECT
  v.vendor_id,
  v.business_name,
  u.full_name AS vendor_name,
  COUNT(DISTINCT s.stall_id) AS affected_stalls,
  COUNT(i.inspection_id) AS failed_inspections,
  ROUND(AVG(i.overall_score), 2) AS failed_inspection_average,
  MAX(i.inspection_date) AS latest_failure_at
FROM vendors AS v
INNER JOIN users AS u
  ON u.user_id = v.user_id
INNER JOIN stalls AS s
  ON s.vendor_id = v.vendor_id
INNER JOIN inspections AS i
  ON i.stall_id = s.stall_id
WHERE i.status IN ('submitted', 'approved')
  AND (
    i.overall_score < 50
    OR i.risk_level IN ('high', 'critical')
  )
GROUP BY v.vendor_id, v.business_name, u.full_name
HAVING COUNT(i.inspection_id) >= 2
ORDER BY failed_inspections DESC, failed_inspection_average ASC;
