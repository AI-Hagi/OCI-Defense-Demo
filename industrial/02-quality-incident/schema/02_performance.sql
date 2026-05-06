-- =====================================================================
-- UC #2 Quality & Incident Analysis — Step 2: Augment Performance
-- =====================================================================
-- - MV of recent NCRs (last 90 days) refreshed every 30 minutes
-- - MV of SPC measurements aggregated to hourly buckets per plant/part
-- =====================================================================

CREATE MATERIALIZED VIEW ncr_recent_mv
  REFRESH COMPLETE NEXT SYSDATE + 30/1440
  AS
SELECT
  ncr_id,
  plant_code,
  line_code,
  part_number,
  reported_at,
  severity,
  status,
  defect_category,
  description,
  clearance_required,
  releasable_to
FROM ncr_records@QUALITY_DB_LINK
WHERE reported_at >= SYSTIMESTAMP - INTERVAL '90' DAY;

CREATE MATERIALIZED VIEW spc_hourly_mv
  REFRESH COMPLETE NEXT SYSDATE + 1/24
  AS
SELECT
  TRUNC(measurement_ts, 'HH') AS hour_bucket,
  plant_code,
  line_code,
  part_number,
  parameter_name,
  COUNT(*)                  AS sample_count,
  AVG(measured_value)       AS mean_value,
  STDDEV(measured_value)    AS stddev_value,
  MIN(measured_value)       AS min_value,
  MAX(measured_value)       AS max_value,
  SUM(CASE WHEN measured_value < lsl OR measured_value > usl
           THEN 1 ELSE 0 END) AS oos_count
FROM spc_measurements_ext
GROUP BY TRUNC(measurement_ts, 'HH'),
         plant_code, line_code, part_number, parameter_name;

PROMPT UC2 step 2 (performance) complete.
