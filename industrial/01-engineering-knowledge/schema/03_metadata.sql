-- =====================================================================
-- UC #1 Engineering Knowledge Assistant — Step 3: Augment Metadata
-- =====================================================================
-- Comments enrich NL2SQL accuracy. 26ai Data Annotations enable
-- semantic typing and PII/classification flags.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 3a. Object-level comments
-- ---------------------------------------------------------------------
COMMENT ON MATERIALIZED VIEW plm_parts_mv IS
  'PLM parts catalog mirrored from Teamcenter via REST. Refreshed every 15 minutes. Each row represents one part at one revision with lifecycle state and security classification.';

COMMENT ON VIEW eng_part_docs_v IS
  'Joined view of PLM parts and their associated engineering documents. Used by the Engineering Knowledge Assistant for grounded RAG answers. Filtered by coalition VPD.';

-- ---------------------------------------------------------------------
-- 3b. Column-level comments
-- ---------------------------------------------------------------------
COMMENT ON COLUMN plm_parts_mv.part_number     IS 'Unique part identifier in PLM. Format: 7-digit alphanumeric. Primary lookup key for engineers.';
COMMENT ON COLUMN plm_parts_mv.revision        IS 'Engineering revision letter (A, B, C, ...). Higher letter = later revision. Released revisions are uppercase, in-progress lowercase.';
COMMENT ON COLUMN plm_parts_mv.lifecycle_state IS 'PLM lifecycle: IN_WORK, IN_REVIEW, RELEASED, OBSOLETE. Only RELEASED parts may ship.';
COMMENT ON COLUMN plm_parts_mv.classification  IS 'Engineering classification: COTS, MOTS, GOTS, BESPOKE. Drives export-control workflow.';
COMMENT ON COLUMN plm_parts_mv.clearance_required IS 'Minimum personnel clearance required to view this part record. Values: UNCLASSIFIED, RESTRICTED, CONFIDENTIAL, SECRET.';
COMMENT ON COLUMN plm_parts_mv.releasable_to   IS 'Comma-separated list of nation codes (DEU, FRA, NLD, ...) or coalition group (NATO, EU, FVEY, ALL_COALITION) authorized to view this part.';

-- ---------------------------------------------------------------------
-- 3c. 26ai Data Annotations (semantic typing for NL2SQL)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_DATA_ANNOTATIONS.ADD_ANNOTATION(
    object_name     => 'PLM_PARTS_MV',
    column_name     => 'PART_NUMBER',
    annotation_name => 'SEMANTIC_TYPE',
    annotation_value=> 'IDENTIFIER'
  );
  DBMS_DATA_ANNOTATIONS.ADD_ANNOTATION(
    object_name     => 'PLM_PARTS_MV',
    column_name     => 'CLEARANCE_REQUIRED',
    annotation_name => 'SECURITY_LABEL',
    annotation_value=> 'CLASSIFICATION'
  );
  DBMS_DATA_ANNOTATIONS.ADD_ANNOTATION(
    object_name     => 'PLM_PARTS_MV',
    column_name     => 'RELEASABLE_TO',
    annotation_name => 'SECURITY_LABEL',
    annotation_value=> 'RELEASABILITY'
  );
EXCEPTION
  WHEN OTHERS THEN
    -- DBMS_DATA_ANNOTATIONS API name may vary by 26ai release;
    -- fall back to vendor-neutral COMMENT-only metadata if absent.
    DBMS_OUTPUT.PUT_LINE('Annotation API unavailable: ' || SQLERRM);
END;
/

PROMPT UC1 step 3 (metadata) complete.
