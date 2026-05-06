-- =====================================================================
-- UC #1 Engineering Knowledge Assistant — Step 4: Augment Security
-- =====================================================================
-- Attach the shared coalition VPD policy to every object the agent
-- can read. Fail-closed by default.
-- =====================================================================

BEGIN
  attach_coalition_policy(USER, 'PLM_PARTS_MV');
  attach_coalition_policy(USER, 'ENG_PART_DOCS_V');
END;
/

-- ---------------------------------------------------------------------
-- Documents: classification lives outside the file content (in the
-- doc_id naming convention or in an Object Storage tag). For the demo,
-- we inject classification metadata via a wrapper view.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW engineering_docs_classified_v AS
SELECT
  d.doc_id,
  d.file_name,
  d.content,
  -- demo convention: doc_id = "PARTNO_REV_DOCTYPE_CLEARANCE_RELEASABLE"
  --   e.g. "1234567_A_SPEC_RESTRICTED_NATO"
  REGEXP_SUBSTR(d.doc_id, '[^_]+', 1, 4) AS clearance_required,
  REGEXP_SUBSTR(d.doc_id, '[^_]+', 1, 5) AS releasable_to
FROM engineering_docs_ext d;

BEGIN
  attach_coalition_policy(USER, 'ENGINEERING_DOCS_CLASSIFIED_V');
END;
/

-- ---------------------------------------------------------------------
-- Smoke test
-- ---------------------------------------------------------------------
PROMPT --- Smoke test: two sessions should see different rows ---
PROMPT EXEC coalition_ctx_pkg.set_session('alice', 'RESTRICTED', 'DEU', 'NATO');
PROMPT SELECT COUNT(*) FROM eng_part_docs_v;
PROMPT EXEC coalition_ctx_pkg.set_session('bob', 'UNCLASSIFIED', 'TUR', 'NATIONAL_ONLY');
PROMPT SELECT COUNT(*) FROM eng_part_docs_v;

PROMPT UC1 step 4 (security) complete.
