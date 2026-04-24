--==============================================================================
-- File:        04_vector_search.sql
-- Purpose:     AI Vector Search assets for the Sovereign Defence Intelligence
--              Platform. Creates HNSW indexes on the three VECTOR columns
--              declared in 02_core_tables.sql and exposes reusable
--              similarity-search helpers.
--
-- Target:      Oracle AI Database 26ai
-- Depends on:  02_core_tables.sql (document_embeddings, scene_embeddings,
--              osint_entities)
--
-- Index plan:
--   * document_embeddings.embedding   VECTOR(1024, FLOAT32)  COSINE
--   * scene_embeddings.embedding      VECTOR(768,  FLOAT32)  COSINE
--   * osint_entities.embedding        VECTOR(768,  FLOAT32)  EUCLIDEAN
--
-- Operational notes:
--   * ORGANIZATION INMEMORY NEIGHBOR GRAPH puts the HNSW graph in the
--     Vector Memory Pool (VECTOR_MEMORY_SIZE must be sized by the DBA).
--   * TARGET ACCURACY 95 is the recall target; the optimizer picks efSearch
--     at query time to meet it.
--   * HNSW parameters tuned for ~10^6 rows: NEIGHBORS 32, EFCONSTRUCTION 200.
--==============================================================================

SET DEFINE OFF;

--------------------------------------------------------------------------------
-- 1) HNSW index on document_embeddings (1024-dim, cosine)
--------------------------------------------------------------------------------
CREATE VECTOR INDEX idx_doc_emb
    ON document_embeddings (embedding)
    ORGANIZATION INMEMORY NEIGHBOR GRAPH
    DISTANCE COSINE
    WITH TARGET ACCURACY 95
    PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200);

--------------------------------------------------------------------------------
-- 2) HNSW index on scene_embeddings (768-dim, cosine)
--------------------------------------------------------------------------------
CREATE VECTOR INDEX idx_scene_emb
    ON scene_embeddings (embedding)
    ORGANIZATION INMEMORY NEIGHBOR GRAPH
    DISTANCE COSINE
    WITH TARGET ACCURACY 95
    PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200);

--------------------------------------------------------------------------------
-- 3) HNSW index on osint_entities.embedding (768-dim, euclidean)
--    Euclidean chosen because OSINT entity embeddings are not normalised.
--------------------------------------------------------------------------------
CREATE VECTOR INDEX idx_osint_ent_emb
    ON osint_entities (embedding)
    ORGANIZATION INMEMORY NEIGHBOR GRAPH
    DISTANCE EUCLIDEAN
    WITH TARGET ACCURACY 95
    PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200);

--------------------------------------------------------------------------------
-- Helper function: top-k document chunks by cosine similarity to a query
-- embedding. Returns doc_id, chunk_id, chunk_idx and the distance score.
-- Uses FETCH APPROX FIRST ... ROWS ONLY so the optimizer uses the HNSW index.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_top_k_docs (
    p_query  IN VECTOR,
    p_k      IN NUMBER DEFAULT 10
) RETURN SYS_REFCURSOR
AS
    l_cur SYS_REFCURSOR;
BEGIN
    OPEN l_cur FOR
        SELECT c.doc_id,
               e.chunk_id,
               c.chunk_idx,
               VECTOR_DISTANCE(e.embedding, p_query, COSINE) AS distance
          FROM document_embeddings e
          JOIN document_chunks     c ON c.chunk_id = e.chunk_id
         ORDER BY VECTOR_DISTANCE(e.embedding, p_query, COSINE)
         FETCH APPROX FIRST p_k ROWS ONLY;
    RETURN l_cur;
END fn_top_k_docs;
/

--------------------------------------------------------------------------------
-- Helper function: top-k satellite scenes by cosine similarity to a query
-- embedding. Filters by tenant for multi-tenant isolation on top of OLS.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_top_k_scenes (
    p_query     IN VECTOR,
    p_tenant_id IN VARCHAR2,
    p_k         IN NUMBER DEFAULT 10
) RETURN SYS_REFCURSOR
AS
    l_cur SYS_REFCURSOR;
BEGIN
    OPEN l_cur FOR
        SELECT s.scene_id,
               s.captured_at,
               s.sensor,
               VECTOR_DISTANCE(e.embedding, p_query, COSINE) AS distance
          FROM scene_embeddings  e
          JOIN satellite_scenes  s ON s.scene_id = e.scene_id
         WHERE s.tenant_id = p_tenant_id
         ORDER BY VECTOR_DISTANCE(e.embedding, p_query, COSINE)
         FETCH APPROX FIRST p_k ROWS ONLY;
    RETURN l_cur;
END fn_top_k_scenes;
/

--------------------------------------------------------------------------------
-- Helper function: top-k OSINT entities by euclidean distance to a query
-- embedding. Useful for "find similar actor / vessel / indicator" lookups.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_top_k_osint (
    p_query     IN VECTOR,
    p_tenant_id IN VARCHAR2,
    p_kind      IN VARCHAR2 DEFAULT NULL,
    p_k         IN NUMBER DEFAULT 10
) RETURN SYS_REFCURSOR
AS
    l_cur SYS_REFCURSOR;
BEGIN
    OPEN l_cur FOR
        SELECT entity_id,
               kind,
               canonical_name,
               VECTOR_DISTANCE(embedding, p_query, EUCLIDEAN) AS distance
          FROM osint_entities
         WHERE tenant_id = p_tenant_id
           AND (p_kind IS NULL OR kind = p_kind)
         ORDER BY VECTOR_DISTANCE(embedding, p_query, EUCLIDEAN)
         FETCH APPROX FIRST p_k ROWS ONLY;
    RETURN l_cur;
END fn_top_k_osint;
/

--------------------------------------------------------------------------------
-- Read-only helper view: flattens document chunks with their parent doc for
-- the ORDS RAG endpoint. The vector column itself is not exposed.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_document_search AS
    SELECT d.doc_id,
           d.tenant_id,
           d.title,
           d.classification,
           d.ols_label      AS doc_ols_label,
           c.chunk_id,
           c.chunk_idx,
           c.text           AS chunk_text,
           c.ols_label      AS chunk_ols_label
      FROM documents        d
      JOIN document_chunks  c ON c.doc_id = d.doc_id;

COMMENT ON TABLE vw_document_search IS
  'Flattened read projection used by fn_top_k_docs consumers to hydrate chunk text alongside similarity scores.';

--==============================================================================
-- End of 04_vector_search.sql
--==============================================================================
