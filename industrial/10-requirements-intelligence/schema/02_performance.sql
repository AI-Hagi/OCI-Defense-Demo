-- =====================================================================
-- UC #10 Requirements Intelligence — Step 2: Augment Performance
-- =====================================================================
-- Core requirements tables + materialized view for cross-program search
-- =====================================================================

-- ---------------------------------------------------------------------
-- 2a. Core requirements table
--     (populated by ReqIF ingest pipeline or sample-data/load_sample_data.sql)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS requirements (
  req_id              VARCHAR2(40) PRIMARY KEY,
  program_id          VARCHAR2(40) NOT NULL REFERENCES programs(program_id),
  req_text            CLOB NOT NULL,
  req_type            VARCHAR2(10) CHECK (req_type IN ('SHALL','SHOULD','MAY','INFO')),
  category            VARCHAR2(50),    -- functional, performance, safety, interface, ...
  status              VARCHAR2(20),    -- DRAFT, REVIEWED, APPROVED, OBSOLETE
  embedding           VECTOR(1024, FLOAT32),
  reqif_meta          JSON,
  quality_score       NUMBER(5,2),    -- 0.0–100.0
  clearance_required  VARCHAR2(20) DEFAULT 'RESTRICTED',
  releasable_to       VARCHAR2(100) DEFAULT 'NATO',
  created_at          TIMESTAMP DEFAULT SYSTIMESTAMP,
  updated_at          TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- ---------------------------------------------------------------------
-- 2b. Versioning, sources, traceability
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS requirement_versions (
  req_id        VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  version       NUMBER(5)    NOT NULL,
  author        VARCHAR2(100),
  change_reason VARCHAR2(500),
  ts            TIMESTAMP DEFAULT SYSTIMESTAMP,
  CONSTRAINT requirement_versions_pk PRIMARY KEY (req_id, version)
);

CREATE TABLE IF NOT EXISTS requirement_sources (
  req_id      VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  source_doc  VARCHAR2(400),
  page        NUMBER,
  section     VARCHAR2(100),
  span_start  NUMBER,
  span_end    NUMBER
);

CREATE TABLE IF NOT EXISTS trace_links (
  parent_id  VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  child_id   VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  link_type  VARCHAR2(20) CHECK (link_type IN ('satisfies','verifies','derives','conflicts')),
  CONSTRAINT trace_links_pk PRIMARY KEY (parent_id, child_id, link_type)
);

CREATE TABLE IF NOT EXISTS verification_artifacts (
  req_id        VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  artifact_type VARCHAR2(30),    -- TEST_CASE, ANALYSIS, INSPECTION, DEMONSTRATION
  location      VARCHAR2(400),    -- URI or URL to test case in Polarion / DOORS / Object Storage
  status        VARCHAR2(20),     -- PASSED, FAILED, NOT_RUN
  ts            TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE IF NOT EXISTS reqif_imports (
  import_id     VARCHAR2(100) PRIMARY KEY,
  source_tool   VARCHAR2(50),     -- DOORS_NG, POLARION, CODEBEAMER, MANUAL
  raw_xml       CLOB,
  imported_at   TIMESTAMP DEFAULT SYSTIMESTAMP,
  imported_by   VARCHAR2(100)
);

CREATE TABLE IF NOT EXISTS reuse_candidates (
  req_id        VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  candidate_id  VARCHAR2(40) NOT NULL REFERENCES requirements(req_id),
  similarity    NUMBER(5,4),
  decision      VARCHAR2(20),     -- ACCEPTED, REJECTED, PENDING
  CONSTRAINT reuse_candidates_pk PRIMARY KEY (req_id, candidate_id)
);

-- ---------------------------------------------------------------------
-- 2c. Cross-program reuse-search MV (refreshed every 4 hours)
--     - Used by the reuse_search agent tool for fast top-N similarity
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS requirements_reuse_mv
  REFRESH COMPLETE NEXT SYSDATE + 4/24
  AS
SELECT
  r.req_id,
  r.program_id,
  p.name           AS program_name,
  p.status         AS program_status,
  r.req_text,
  r.req_type,
  r.category,
  r.embedding,
  r.quality_score,
  r.clearance_required,
  r.releasable_to
FROM requirements r
JOIN programs p ON p.program_id = r.program_id
WHERE r.status IN ('APPROVED', 'REVIEWED')
  AND p.status IN ('ACTIVE', 'ARCHIVED');

PROMPT UC10 step 2 (performance) complete.
