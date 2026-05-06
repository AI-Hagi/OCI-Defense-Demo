-- =====================================================================
-- UC #3 Software Assurance — Step 5: Create AI Workload
-- =====================================================================
-- The differentiator for this UC is the Property Graph traceability
-- model. ADB 26ai supports SQL/PGQ for graph queries directly on
-- relational tables.
--
--   REQUIREMENT --[satisfied_by]--> TEST_CASE
--   TEST_CASE   --[has_result]--> TEST_RESULT
--   TEST_CASE   --[surfaces]--> DEFECT
--   COMMIT      --[implements]--> REQUIREMENT
-- =====================================================================

-- ---------------------------------------------------------------------
-- 5a. Property Graph definition (SQL/PGQ)
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROPERTY GRAPH swassure_graph
  VERTEX TABLES (
    requirements_mv    KEY (req_id)    LABEL requirement
                       PROPERTIES ALL COLUMNS,
    test_cases_mv      KEY (test_id)   LABEL test_case
                       PROPERTIES ALL COLUMNS,
    test_results_mv    KEY (result_id) LABEL test_result
                       PROPERTIES ALL COLUMNS,
    defects_mv         KEY (defect_id) LABEL defect
                       PROPERTIES ALL COLUMNS,
    git_commits_ext    KEY (commit_sha) LABEL commit
                       PROPERTIES ALL COLUMNS
  )
  EDGE TABLES (
    req_test_link
      SOURCE KEY (req_id) REFERENCES requirements_mv (req_id)
      DESTINATION KEY (test_id) REFERENCES test_cases_mv (test_id)
      LABEL satisfied_by,
    test_results_mv AS test_to_result
      SOURCE KEY (test_id) REFERENCES test_cases_mv (test_id)
      DESTINATION KEY (result_id) REFERENCES test_results_mv (result_id)
      LABEL has_result,
    defects_mv AS test_to_defect
      SOURCE KEY (found_in_test) REFERENCES test_cases_mv (test_id)
      DESTINATION KEY (defect_id) REFERENCES defects_mv (defect_id)
      LABEL surfaces,
    git_commits_ext AS commit_to_req
      SOURCE KEY (commit_sha) REFERENCES git_commits_ext (commit_sha)
      DESTINATION KEY (linked_req) REFERENCES requirements_mv (req_id)
      LABEL implements
  );

-- ---------------------------------------------------------------------
-- 5b. Graph queries used by the agent
-- ---------------------------------------------------------------------
-- Coverage gap: APPROVED requirements with no PASSING test result
CREATE OR REPLACE VIEW coverage_gaps_v AS
SELECT * FROM GRAPH_TABLE (swassure_graph
  MATCH (r IS requirement)
  WHERE r.status = 'APPROVED'
    AND NOT EXISTS (
      MATCH (r) -[IS satisfied_by]-> (t IS test_case)
                -[IS has_result]-> (res IS test_result)
      WHERE res.outcome = 'PASS'
    )
  COLUMNS (r.req_id AS req_id, r.title AS title, r.priority AS priority)
);

-- Defect impact: from a defect, walk back to all requirements affected
CREATE OR REPLACE VIEW defect_impact_v AS
SELECT * FROM GRAPH_TABLE (swassure_graph
  MATCH (d IS defect) <-[IS surfaces]- (t IS test_case) <-[IS satisfied_by]- (r IS requirement)
  COLUMNS (
    d.defect_id, d.severity, t.test_id, r.req_id, r.priority
  )
);

BEGIN
  attach_coalition_policy(USER, 'COVERAGE_GAPS_V');
  attach_coalition_policy(USER, 'DEFECT_IMPACT_V');
END;
/

-- ---------------------------------------------------------------------
-- 5c. Vector embeddings for requirements (so the agent can do
--     "find similar requirements", "find duplicate-ish reqs" etc.)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS requirement_embeddings (
  req_id              VARCHAR2(40) PRIMARY KEY,
  project_id          VARCHAR2(40),
  title_desc_embed    VECTOR(1024, FLOAT32),
  clearance_required  VARCHAR2(20),
  releasable_to       VARCHAR2(100)
);

CREATE OR REPLACE PROCEDURE refresh_req_embeddings AS
BEGIN
  MERGE INTO requirement_embeddings t
  USING (
    SELECT
      r.req_id, r.project_id, r.clearance_required, r.releasable_to,
      DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING(
        r.title || CHR(10) || r.description,
        JSON('{"provider":"oci","credential_name":"OCI_GENAI_CRED",
               "model":"cohere.embed-multilingual-v3.0"}')
      ) AS embed
    FROM requirements_mv r
  ) s ON (t.req_id = s.req_id)
  WHEN MATCHED THEN UPDATE SET title_desc_embed = s.embed
  WHEN NOT MATCHED THEN INSERT VALUES (s.req_id, s.project_id, s.embed,
                                        s.clearance_required, s.releasable_to);
  COMMIT;
END;
/

CREATE VECTOR INDEX IF NOT EXISTS req_hnsw_idx
  ON requirement_embeddings (title_desc_embed)
  ORGANIZATION INMEMORY NEIGHBOR GRAPH
  DISTANCE COSINE WITH TARGET ACCURACY 95
  PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200);

-- ---------------------------------------------------------------------
-- 5d. Select AI profile
-- ---------------------------------------------------------------------
BEGIN DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'SWASSURE_AGENT', force => TRUE);
EXCEPTION WHEN OTHERS THEN NULL; END;
/
BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'SWASSURE_AGENT',
    attributes   => '{
      "provider":"oci","credential_name":"OCI_GENAI_CRED",
      "region":"eu-frankfurt-1",
      "model":"cohere.command-r-plus-08-2024",
      "embedding_model":"cohere.embed-multilingual-v3.0",
      "vector_index_name":"req_hnsw_idx",
      "object_list":[
        {"owner":"DEFENCE_ADMIN","name":"requirements_mv"},
        {"owner":"DEFENCE_ADMIN","name":"test_cases_mv"},
        {"owner":"DEFENCE_ADMIN","name":"test_results_mv"},
        {"owner":"DEFENCE_ADMIN","name":"defects_mv"},
        {"owner":"DEFENCE_ADMIN","name":"coverage_gaps_v"},
        {"owner":"DEFENCE_ADMIN","name":"defect_impact_v"}
      ],
      "comments":"true","annotations":"true",
      "max_tokens":4096,"temperature":0.1
    }'
  );
END;
/

PROMPT UC3 step 5 (AI workload) complete.
