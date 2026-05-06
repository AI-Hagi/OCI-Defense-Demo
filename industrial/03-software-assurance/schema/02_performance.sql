-- =====================================================================
-- UC #3 Software Assurance — Step 2: Augment Performance
-- =====================================================================
CREATE MATERIALIZED VIEW requirements_mv
  REFRESH COMPLETE NEXT SYSDATE + 30/1440 AS
SELECT * FROM TABLE(polarion_reqs_pipe(NULL));

-- (Equivalent MVs for test_cases_mv, test_results_mv, defects_mv exist
-- in production and follow the same pattern.)

-- For demo seed data we provide minimal local stand-ins:
CREATE TABLE IF NOT EXISTS test_cases_mv (
  test_id            VARCHAR2(40) PRIMARY KEY,
  project_id         VARCHAR2(40),
  title              VARCHAR2(400),
  test_type          VARCHAR2(20),  -- UNIT, INTEGRATION, SYSTEM, ACCEPTANCE
  automation_level   VARCHAR2(20),
  clearance_required VARCHAR2(20),
  releasable_to      VARCHAR2(100)
);

CREATE TABLE IF NOT EXISTS test_results_mv (
  result_id          VARCHAR2(40) PRIMARY KEY,
  test_id            VARCHAR2(40),
  executed_at        TIMESTAMP,
  outcome            VARCHAR2(10),  -- PASS, FAIL, BLOCKED, SKIP
  evidence_doc_id    VARCHAR2(100),
  clearance_required VARCHAR2(20),
  releasable_to      VARCHAR2(100)
);

CREATE TABLE IF NOT EXISTS defects_mv (
  defect_id          VARCHAR2(40) PRIMARY KEY,
  project_id         VARCHAR2(40),
  title              VARCHAR2(400),
  severity           NUMBER,
  status             VARCHAR2(30),
  found_in_test      VARCHAR2(40),
  clearance_required VARCHAR2(20),
  releasable_to      VARCHAR2(100)
);

CREATE TABLE IF NOT EXISTS req_test_link (
  req_id  VARCHAR2(40),
  test_id VARCHAR2(40),
  CONSTRAINT req_test_pk PRIMARY KEY (req_id, test_id)
);

PROMPT UC3 step 2 (performance) complete.
