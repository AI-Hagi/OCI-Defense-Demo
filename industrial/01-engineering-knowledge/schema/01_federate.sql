-- =====================================================================
-- UC #1 Engineering Knowledge Assistant — Step 1: Federate Data
-- =====================================================================
-- Sources:
--   - PLM REST API (Teamcenter / Windchill style) → Heterogeneous
--     Connectivity DB-Link
--   - OCI Object Storage bucket with manuals, specs, change notes
--     → External Tables (PDF/DOCX) for vector ingestion
-- =====================================================================

-- ---------------------------------------------------------------------
-- Substitution variables (set via SQLcl or sqlplus DEFINE)
-- ---------------------------------------------------------------------
-- DEFINE PLM_HOST     = plm.contractor.internal
-- DEFINE PLM_USER     = plm_service
-- DEFINE PLM_PWD      = __FILL_IN__
-- DEFINE PLM_BASE_URL = https://&PLM_HOST/tc/rest/v2

-- ---------------------------------------------------------------------
-- 1a. Credential for PLM REST
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'PLM_REST_CRED',
    username        => '&PLM_USER',
    password        => '&PLM_PWD'
  );
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -20022 THEN NULL; ELSE RAISE; END IF;
END;
/

-- ---------------------------------------------------------------------
-- 1b. Object Storage credential (resource principal in production)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'OBJ_STORE_CRED',
    user_ocid       => '&OCI_USER_OCID',
    tenancy_ocid    => '&OCI_TENANCY_OCID',
    private_key     => '&OCI_API_KEY_PEM',
    fingerprint     => '&OCI_API_KEY_FINGERPRINT'
  );
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -20022 THEN NULL; ELSE RAISE; END IF;
END;
/

-- ---------------------------------------------------------------------
-- 1c. PLM parts catalog — fetched on demand via DBMS_CLOUD.SEND_REQUEST
--     Wrapped as a pipelined function so it appears as a "table" to SQL
-- ---------------------------------------------------------------------
CREATE OR REPLACE TYPE plm_part_t AS OBJECT (
  part_number          VARCHAR2(40),
  description          VARCHAR2(400),
  revision             VARCHAR2(20),
  lifecycle_state      VARCHAR2(40),
  classification       VARCHAR2(40),
  clearance_required   VARCHAR2(20),
  releasable_to        VARCHAR2(100),
  last_modified        TIMESTAMP
);
/
CREATE OR REPLACE TYPE plm_part_tab IS TABLE OF plm_part_t;
/

CREATE OR REPLACE FUNCTION plm_parts_pipe(
  p_query VARCHAR2 DEFAULT NULL
) RETURN plm_part_tab PIPELINED AS
  l_resp DBMS_CLOUD_TYPES.RESP;
  l_json JSON_OBJECT_T;
  l_arr  JSON_ARRAY_T;
  l_item JSON_OBJECT_T;
BEGIN
  l_resp := DBMS_CLOUD.SEND_REQUEST(
    credential_name => 'PLM_REST_CRED',
    uri             => '&PLM_BASE_URL/parts?q=' ||
                       UTL_URL.ESCAPE(NVL(p_query, '*')),
    method          => DBMS_CLOUD.METHOD_GET
  );
  l_json := JSON_OBJECT_T.PARSE(DBMS_CLOUD.GET_RESPONSE_TEXT(l_resp));
  l_arr  := l_json.GET_ARRAY('items');
  FOR i IN 0 .. l_arr.GET_SIZE - 1 LOOP
    l_item := TREAT(l_arr.GET(i) AS JSON_OBJECT_T);
    PIPE ROW(plm_part_t(
      l_item.GET_STRING('partNumber'),
      l_item.GET_STRING('description'),
      l_item.GET_STRING('revision'),
      l_item.GET_STRING('lifecycleState'),
      l_item.GET_STRING('classification'),
      l_item.GET_STRING('clearanceRequired'),
      l_item.GET_STRING('releasableTo'),
      TO_TIMESTAMP(l_item.GET_STRING('lastModified'),
                   'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ));
  END LOOP;
  RETURN;
END plm_parts_pipe;
/

-- ---------------------------------------------------------------------
-- 1d. External Table for engineering documents in Object Storage
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name      => 'engineering_docs_ext',
    credential_name => 'OBJ_STORE_CRED',
    file_uri_list   => 'https://objectstorage.eu-frankfurt-1.oraclecloud.com/n/&OCI_NAMESPACE/b/defence-eng-docs/o/*',
    format          => JSON_OBJECT(
                         'type'              VALUE 'document',
                         'characterset'      VALUE 'UTF8'
                       ),
    column_list     => 'doc_id VARCHAR2(100), file_name VARCHAR2(400), content CLOB'
  );
END;
/

-- ---------------------------------------------------------------------
-- 1e. Sanity check
-- ---------------------------------------------------------------------
PROMPT 1c-test: SELECT * FROM TABLE(plm_parts_pipe('rev:A')) FETCH FIRST 3 ROWS ONLY;
PROMPT 1d-test: SELECT file_name FROM engineering_docs_ext FETCH FIRST 3 ROWS ONLY;

PROMPT UC1 step 1 (federate) complete.
