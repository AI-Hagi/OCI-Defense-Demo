-- =====================================================================
-- UC #1 Engineering Knowledge Assistant — Step 5: Create AI Workload
-- =====================================================================
-- - Vector chain to chunk + embed engineering documents
-- - HNSW index for fast similarity search
-- - Select AI RAG profile pointed at this vector store
-- - Knowledge agent will be defined in agent/engineering-knowledge.agent.yaml
-- =====================================================================

-- ---------------------------------------------------------------------
-- 5a. Vector store table
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering_doc_chunks (
  chunk_id           VARCHAR2(100) PRIMARY KEY,
  doc_id             VARCHAR2(100) NOT NULL,
  part_number        VARCHAR2(40),
  chunk_text         CLOB,
  chunk_embedding    VECTOR(1024, FLOAT32),  -- cohere multilingual v3 dim
  clearance_required VARCHAR2(20),
  releasable_to      VARCHAR2(100),
  ingested_at        TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- ---------------------------------------------------------------------
-- 5b. Ingestion procedure using DBMS_VECTOR_CHAIN
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE ingest_engineering_docs AS
BEGIN
  INSERT INTO engineering_doc_chunks (
    chunk_id, doc_id, part_number, chunk_text, chunk_embedding,
    clearance_required, releasable_to
  )
  SELECT
    d.doc_id || '_' || c.chunk_offset                 AS chunk_id,
    d.doc_id,
    REGEXP_SUBSTR(d.doc_id, '[^_]+', 1, 1)            AS part_number,
    c.chunk_data,
    DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING(
      c.chunk_data,
      JSON('{"provider":"oci","credential_name":"OCI_GENAI_CRED",
             "model":"cohere.embed-multilingual-v3.0"}')
    ),
    d.clearance_required,
    d.releasable_to
  FROM engineering_docs_classified_v d
  CROSS APPLY DBMS_VECTOR_CHAIN.UTL_TO_CHUNKS(
    DBMS_VECTOR_CHAIN.UTL_TO_TEXT(d.content),
    JSON('{"by":"words","max":512,"overlap":50,"split":"recursively"}')
  ) c
  WHERE NOT EXISTS (
    SELECT 1 FROM engineering_doc_chunks ec
    WHERE ec.doc_id = d.doc_id
  );
  COMMIT;
END ingest_engineering_docs;
/

-- ---------------------------------------------------------------------
-- 5c. HNSW index for low-latency similarity search
-- ---------------------------------------------------------------------
CREATE VECTOR INDEX IF NOT EXISTS engineering_doc_hnsw_idx
  ON engineering_doc_chunks (chunk_embedding)
  ORGANIZATION INMEMORY NEIGHBOR GRAPH
  DISTANCE COSINE
  WITH TARGET ACCURACY 95
  PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200);

-- ---------------------------------------------------------------------
-- 5d. Apply VPD to the chunk table (so vector search is also filtered)
-- ---------------------------------------------------------------------
BEGIN
  attach_coalition_policy(USER, 'ENGINEERING_DOC_CHUNKS');
END;
/

-- ---------------------------------------------------------------------
-- 5e. RAG-enabled Select AI profile (extends shared profile with
--     vector store binding)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'ENG_KNOW_RAG', force => TRUE);
EXCEPTION WHEN OTHERS THEN NULL; END;
/

BEGIN
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'ENG_KNOW_RAG',
    attributes   => '{
      "provider":         "oci",
      "credential_name":  "OCI_GENAI_CRED",
      "region":           "eu-frankfurt-1",
      "model":            "cohere.command-r-plus-08-2024",
      "embedding_model":  "cohere.embed-multilingual-v3.0",
      "vector_index_name":"engineering_doc_hnsw_idx",
      "object_list":      [{"owner":"DEFENCE_ADMIN","name":"plm_parts_mv"},
                           {"owner":"DEFENCE_ADMIN","name":"eng_part_docs_v"}],
      "comments":         "true",
      "annotations":      "true",
      "max_tokens":       4096,
      "temperature":      0.2
    }'
  );
END;
/

-- ---------------------------------------------------------------------
-- 5f. Schedule incremental re-ingestion every hour
-- ---------------------------------------------------------------------
BEGIN
  DBMS_SCHEDULER.CREATE_JOB(
    job_name        => 'ENGINEERING_DOC_INGEST_JOB',
    job_type        => 'PLSQL_BLOCK',
    job_action      => 'BEGIN ingest_engineering_docs; END;',
    start_date      => SYSTIMESTAMP,
    repeat_interval => 'FREQ=HOURLY; INTERVAL=1',
    enabled         => TRUE
  );
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -27477 THEN NULL;  -- already exists
    ELSE RAISE; END IF;
END;
/

PROMPT UC1 step 5 (AI workload) complete. Now import agent/engineering-knowledge.agent.yaml into Agent Factory.
