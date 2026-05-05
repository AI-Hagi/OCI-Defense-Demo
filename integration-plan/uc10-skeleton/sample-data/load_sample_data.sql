-- =====================================================================
-- UC #10 Requirements Intelligence — Sample Data Loader
-- =====================================================================
-- Loads synthetic.json (output of generate.py) into programs and
-- requirements tables, then computes embeddings.
--
-- Prerequisite:
--   1. ./schema/01_federate.sql  ... 05_ai_workload.sql have been applied
--   2. ./sample-data/generate.py has produced ./sample-data/synthetic.json
--   3. The JSON file is uploaded to Object Storage at the URI below
--      OR placed in a directory accessible to DBMS_CLOUD
-- =====================================================================

SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------
-- 1. Read the JSON corpus from local file or Object Storage
-- ---------------------------------------------------------------------
-- Option A: file is in Object Storage (production-like)
--   Substitute &OCI_NAMESPACE / &OCI_REGION accordingly
-- Option B: file uploaded as DIRECTORY object (quick demo)
--   Create or use an existing DIRECTORY pointing at the sample-data dir

DECLARE
  l_json_clob   CLOB;
  l_json_obj    JSON_OBJECT_T;
  l_programs    JSON_ARRAY_T;
  l_reqs        JSON_ARRAY_T;
  l_program     JSON_OBJECT_T;
  l_req         JSON_OBJECT_T;
  l_inserted_p  NUMBER := 0;
  l_inserted_r  NUMBER := 0;
BEGIN
  -- --- Option A: from Object Storage -----------------------------------
  -- l_json_clob := DBMS_CLOUD.GET_OBJECT_TEXT(
  --   credential_name => 'OBJ_STORE_CRED',
  --   object_uri      => 'https://objectstorage.&OCI_REGION..oraclecloud.com/n/&OCI_NAMESPACE/b/defence-reqif/o/synthetic.json'
  -- );

  -- --- Option B: from directory (demo path) ----------------------------
  l_json_clob := TO_CLOB(BFILENAME('UC10_SAMPLE_DIR', 'synthetic.json'));

  l_json_obj := JSON_OBJECT_T.PARSE(l_json_clob);

  -- Sanity check the synthetic-data marker
  IF NOT l_json_obj.get_object('header').get_boolean('synthetic') THEN
    RAISE_APPLICATION_ERROR(-20100,
      'Refusing to load: header.synthetic must be true for UC10 sample data.');
  END IF;
  DBMS_OUTPUT.PUT_LINE('Loading synthetic corpus, run_id=' ||
                       l_json_obj.get_object('header').get_string('run_id'));

  -- --- Insert programs -------------------------------------------------
  l_programs := l_json_obj.get_array('programs');
  FOR i IN 0 .. l_programs.get_size - 1 LOOP
    l_program := TREAT(l_programs.get(i) AS JSON_OBJECT_T);
    MERGE INTO programs p USING (
      SELECT
        l_program.get_string('program_id')        AS program_id,
        l_program.get_string('name')              AS name,
        l_program.get_string('domain')            AS domain,
        l_program.get_string('security_class')    AS security_class,
        l_program.get_string('customer_country')  AS customer_country,
        l_program.get_number('start_year')        AS start_year,
        l_program.get_string('status')            AS status
      FROM dual
    ) s ON (p.program_id = s.program_id)
    WHEN NOT MATCHED THEN INSERT (
      program_id, name, domain, security_class,
      customer_country, start_year, status,
      clearance_required, releasable_to
    ) VALUES (
      s.program_id, s.name, s.domain, s.security_class,
      s.customer_country, s.start_year, s.status,
      'RESTRICTED', 'NATO'
    );
    l_inserted_p := l_inserted_p + 1;
  END LOOP;

  -- --- Insert requirements --------------------------------------------
  l_reqs := l_json_obj.get_array('requirements');
  FOR i IN 0 .. l_reqs.get_size - 1 LOOP
    l_req := TREAT(l_reqs.get(i) AS JSON_OBJECT_T);
    MERGE INTO requirements r USING (
      SELECT
        l_req.get_string('req_id')              AS req_id,
        l_req.get_string('program_id')          AS program_id,
        l_req.get_string('req_text')            AS req_text,
        l_req.get_string('req_type')            AS req_type,
        l_req.get_string('category')            AS category,
        l_req.get_string('status')              AS status,
        l_req.get_string('clearance_required')  AS clearance_required,
        l_req.get_string('releasable_to')       AS releasable_to
      FROM dual
    ) s ON (r.req_id = s.req_id)
    WHEN NOT MATCHED THEN INSERT (
      req_id, program_id, req_text, req_type, category,
      status, clearance_required, releasable_to
    ) VALUES (
      s.req_id, s.program_id, s.req_text, s.req_type, s.category,
      s.status, s.clearance_required, s.releasable_to
    );
    l_inserted_r := l_inserted_r + 1;
  END LOOP;

  COMMIT;
  DBMS_OUTPUT.PUT_LINE('  programs inserted/merged:     ' || l_inserted_p);
  DBMS_OUTPUT.PUT_LINE('  requirements inserted/merged: ' || l_inserted_r);
END;
/

-- ---------------------------------------------------------------------
-- 2. Compute embeddings for the new requirements
-- ---------------------------------------------------------------------
EXEC embed_pending_requirements;

-- ---------------------------------------------------------------------
-- 3. Refresh the reuse MV
-- ---------------------------------------------------------------------
EXEC DBMS_MVIEW.REFRESH('REQUIREMENTS_REUSE_MV', 'C');

-- ---------------------------------------------------------------------
-- 4. Quick sanity counts
-- ---------------------------------------------------------------------
PROMPT
PROMPT --- Sanity check (without VPD context) ---
COL program_id FORMAT A20
COL cnt        FORMAT 9999

EXEC coalition_ctx_pkg.set_session('admin','SECRET','DEU','ALL');
EXEC coalition_ctx_set_program('BOXER-MOD,SPZ-NEXTGEN,MARINE-SENS');

SELECT program_id, COUNT(*) AS cnt FROM requirements GROUP BY program_id ORDER BY 1;

PROMPT
PROMPT UC10 sample data loaded. Run verify-coalition-vpd.sh --uc 10 next.
