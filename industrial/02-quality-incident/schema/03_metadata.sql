-- =====================================================================
-- UC #2 Quality & Incident Analysis — Step 3: Augment Metadata
-- =====================================================================

COMMENT ON MATERIALIZED VIEW ncr_recent_mv IS
  'Non-Conformance Reports raised in the last 90 days, federated from the corporate Quality DB. Refreshed every 30 minutes. Severity is 1 (minor) to 5 (safety-critical).';

COMMENT ON MATERIALIZED VIEW spc_hourly_mv IS
  'Statistical Process Control measurements aggregated to hourly buckets per plant/line/part/parameter. oos_count is the number of out-of-spec samples in that bucket. Source: SPC CSV exports in Object Storage.';

COMMENT ON COLUMN ncr_recent_mv.severity        IS 'NCR severity: 1=minor, 2=moderate, 3=major, 4=critical, 5=safety-critical. Severity >=4 triggers immediate plant manager notification.';
COMMENT ON COLUMN ncr_recent_mv.status          IS 'NCR lifecycle: OPEN, IN_INVESTIGATION, ROOT_CAUSE_IDENTIFIED, CONTAINMENT_ACTIVE, CLOSED.';
COMMENT ON COLUMN ncr_recent_mv.defect_category IS 'High-level defect taxonomy: DIMENSIONAL, MATERIAL, ASSEMBLY, FUNCTIONAL, COSMETIC, DOCUMENTATION.';
COMMENT ON COLUMN spc_hourly_mv.oos_count       IS 'Out-of-specification sample count in the hour bucket. Non-zero values indicate process drift or special-cause variation.';

PROMPT UC2 step 3 (metadata) complete.
