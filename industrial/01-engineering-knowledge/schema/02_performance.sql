-- =====================================================================
-- UC #1 Engineering Knowledge Assistant — Step 2: Augment Performance
-- =====================================================================
-- Materialize PLM parts every 15 minutes; document content is
-- re-vectorized on object change (handled in step 5).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 2a. Materialized snapshot of PLM parts catalog
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW plm_parts_mv
  REFRESH COMPLETE NEXT SYSDATE + 15/1440  -- 15 minutes
  AS
SELECT
  part_number,
  description,
  revision,
  lifecycle_state,
  classification,
  clearance_required,
  releasable_to,
  last_modified
FROM TABLE(plm_parts_pipe(NULL));

-- ---------------------------------------------------------------------
-- 2b. Helper view that joins PLM parts to docs via part_number
--     (assumes doc_id naming convention "<part_number>_<rev>_<doctype>")
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW eng_part_docs_v AS
SELECT
  p.part_number,
  p.description       AS part_description,
  p.revision,
  p.lifecycle_state,
  p.clearance_required,
  p.releasable_to,
  d.doc_id,
  d.file_name,
  d.content
FROM plm_parts_mv p
LEFT JOIN engineering_docs_ext d
  ON REGEXP_SUBSTR(d.doc_id, '^[^_]+') = p.part_number;

PROMPT UC1 step 2 (performance) complete.
