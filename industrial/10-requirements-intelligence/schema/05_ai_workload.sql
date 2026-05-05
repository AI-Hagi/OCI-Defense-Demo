-- =====================================================================
-- UC #10 Requirements Intelligence — Step 5: Create AI Workload
-- =====================================================================
-- - HNSW vector index for semantic reuse search
-- - SQL/PGQ property graph on trace_links (coverage gap analysis)
-- - Select AI profile registration + tools
-- =====================================================================

-- ---------------------------------------------------------------------
-- 5a. HNSW vector index on requirements.embedding
--     - Tuned for ~10K-100K requirements typical for one platform programme
--     - Cosine distance (matches cohere.embed-multilingual-v3.0)
-- ---------------------------------------------------------------------
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM user_indexes WHERE index_name = 'REQUIREMENTS_HNSW_IDX';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE VECTOR INDEX requirements_hnsw_idx ' ||
                      'ON requirements (embedding) ' ||
                      'ORGANIZATION INMEMORY NEIGHBOR GRAPH ' ||
                      'DISTANCE COSINE ' ||
                      'WITH TARGET ACCURACY 95 ' ||
                      'PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200)';
  END IF;
END;
/

-- ---------------------------------------------------------------------
-- 5b. SQL/PGQ Property Graph on trace_links
--     - Used by trace_query agent tool for coverage-gap analysis
--     - Edge types: satisfies, verifies, derives, conflicts
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROPERTY GRAPH requirements_trace_graph
  VERTEX TABLES (
    requirements
      KEY (req_id)
      LABEL requirement
      PROPERTIES (req_id, program_id, req_type, category, status, quality_score)
  )
  EDGE TABLES (
    trace_links
      KEY (parent_id, child_id, link_type)
      SOURCE KEY (parent_id) REFERENCES requirements (req_id)
      DESTINATION KEY (child_id) REFERENCES requirements (req_id)
      LABEL trace
      PROPERTIES (link_type)
  );

-- ---------------------------------------------------------------------
-- 5c. Helper view: coverage gaps
--     - Shows requirements without verifies-edge, i.e. no V&V evidence
--     - Used by the demo Beat 4
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW requirements_coverage_gaps_v AS
SELECT r.req_id, r.program_id, r.req_type, r.category, r.req_text
FROM requirements r
WHERE r.req_type IN ('SHALL', 'SHOULD')
  AND r.status = 'APPROVED'
  AND NOT EXISTS (
    SELECT 1 FROM trace_links t
    WHERE t.parent_id = r.req_id AND t.link_type = 'verifies'
  );

COMMENT ON VIEW requirements_coverage_gaps_v IS
  'Requirements (SHALL/SHOULD, APPROVED) without a verifies-link in trace_links — i.e. no V&V evidence yet. Used as the coverage-gap finder.';

-- ---------------------------------------------------------------------
-- 5d. Bulk-embedding helper procedure
--     - Embeds requirements that don't have an embedding yet
--     - Called by sample-data/load_sample_data.sql after bulk insert
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE embed_pending_requirements AS
  CURSOR c_pending IS
    SELECT req_id, req_text FROM requirements WHERE embedding IS NULL;
  l_embedding VECTOR(1024, FLOAT32);
BEGIN
  FOR rec IN c_pending LOOP
    -- Use shared DEFENCE_GENAI_EU profile for embedding
    SELECT VECTOR_EMBEDDING(
             cohere_embed_multilingual_v3 USING rec.req_text AS data
           )
    INTO l_embedding
    FROM dual;

    UPDATE requirements
    SET embedding = l_embedding,
        updated_at = SYSTIMESTAMP
    WHERE req_id = rec.req_id;
  END LOOP;
  COMMIT;
END;
/

-- ---------------------------------------------------------------------
-- 5e. Register Select AI profile for the RE agent
--     - This profile is referenced by the agent YAML
--     - Tools: smart_check (NL2SQL), reuse_search (vector), trace_query (PGQ)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'UC10_RE_PROFILE');
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'UC10_RE_PROFILE',
    attributes   => '{
      "provider": "oci",
      "credential_name": "OCI_GENAI_CRED",
      "object_list": [
        {"owner": "DEFENCE_ADMIN", "name": "REQUIREMENTS"},
        {"owner": "DEFENCE_ADMIN", "name": "PROGRAMS"},
        {"owner": "DEFENCE_ADMIN", "name": "TRACE_LINKS"},
        {"owner": "DEFENCE_ADMIN", "name": "REQUIREMENTS_REUSE_MV"},
        {"owner": "DEFENCE_ADMIN", "name": "REQUIREMENTS_COVERAGE_GAPS_V"}
      ],
      "model": "cohere.command-r-plus-v2",
      "embedding_model": "cohere.embed-multilingual-v3.0",
      "comments": "true",
      "annotations": "true",
      "vector_index_name": "requirements_hnsw_idx",
      "max_tokens": 4096
    }'
  );
END;
/

PROMPT UC10 step 5 (AI workload) complete.
PROMPT --
PROMPT Run sample-data/load_sample_data.sql next to populate ~240 synthetic requirements
PROMPT and call embed_pending_requirements() to compute their vectors.
