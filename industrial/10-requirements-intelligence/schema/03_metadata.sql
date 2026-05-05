-- =====================================================================
-- UC #10 Requirements Intelligence — Step 3: Augment Metadata
-- =====================================================================
-- COMMENT ON statements + 26ai annotations to drive accurate NL2SQL
-- =====================================================================

-- ---------------------------------------------------------------------
-- 3a. Table-level comments
-- ---------------------------------------------------------------------
COMMENT ON TABLE programs IS
  'Master catalogue of defence engineering programmes. Each programme has its own security_class and customer_country. Used as the program-isolation pivot in UC10 VPD.';

COMMENT ON TABLE requirements IS
  'All requirements across all programmes. SHALL/SHOULD/MAY semantics per ISO/IEC/IEEE 29148. Embedding vector is 1024-dim (cohere.embed-multilingual-v3.0). quality_score is the SMART/INCOSE-aware score (0..100).';

COMMENT ON TABLE trace_links IS
  'Many-to-many traceability between requirements. link_type captures the semantics: satisfies (parent satisfied by child), verifies (test verifies requirement), derives (child derived from parent), conflicts (contradiction). Used as the basis for the SQL/PGQ property graph.';

COMMENT ON TABLE verification_artifacts IS
  'Verification evidence per requirement: test cases, analyses, inspections, demonstrations. Status indicates V&V outcome.';

COMMENT ON TABLE requirement_sources IS
  'Provenance info per requirement: which Lastenheft / specification / standard it came from, with page and span.';

COMMENT ON TABLE reqif_imports IS
  'Audit log of ReqIF-XML imports from DOORS NG, Polarion, Codebeamer or manual uploads. raw_xml retained for full traceability.';

COMMENT ON TABLE reuse_candidates IS
  'Reuse-search results: when a new requirement is added, the top-N similar past requirements are stored here with similarity score and engineer decision.';

-- ---------------------------------------------------------------------
-- 3b. Column-level comments (the ones that drive NL2SQL accuracy)
-- ---------------------------------------------------------------------
COMMENT ON COLUMN requirements.req_type IS
  'SHALL = mandatory, SHOULD = recommended, MAY = optional, INFO = informational only. Per ISO/IEC/IEEE 29148.';

COMMENT ON COLUMN requirements.quality_score IS
  'SMART + INCOSE quality score (0=poor, 100=excellent). Computed by the smart_check agent tool. Score < 60 typically requires rework.';

COMMENT ON COLUMN requirements.embedding IS
  'Vector embedding of req_text via cohere.embed-multilingual-v3.0 (1024 dim). Used by AI Vector Search for semantic similarity.';

COMMENT ON COLUMN requirements.category IS
  'Requirement category: functional, performance, safety, interface, environmental, regulatory.';

COMMENT ON COLUMN trace_links.link_type IS
  'satisfies = downward (parent satisfied by child); verifies = test/V&V link; derives = derived requirement; conflicts = contradiction (used by the Quality Agent to surface inconsistencies).';

COMMENT ON COLUMN programs.security_class IS
  'VS-NfD = Verschlusssache nur für den Dienstgebrauch (RESTRICTED equivalent); VS-VS = VS-Vertraulich (CONFIDENTIAL); VS-GEHEIM = SECRET.';

-- ---------------------------------------------------------------------
-- 3c. 26ai data annotations
-- ---------------------------------------------------------------------
-- Annotations help Select AI / NL2SQL understand domain semantics
-- without having to memorize them in prompt context.
BEGIN
  DBMS_CLOUD_AI.SET_PROFILE('DEFENCE_GENAI_EU');
  DBMS_CLOUD_AI.ENABLE_ANNOTATIONS(
    p_object_owner => USER,
    p_object_name  => 'REQUIREMENTS'
  );
EXCEPTION
  WHEN OTHERS THEN
    -- ENABLE_ANNOTATIONS may not be available in all 26ai patches;
    -- COMMENT-driven hinting still works.
    NULL;
END;
/

PROMPT UC10 step 3 (metadata) complete.
