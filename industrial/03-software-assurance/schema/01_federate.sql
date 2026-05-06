-- =====================================================================
-- UC #3 Software Assurance Assistant — Step 1: Federate Data
-- =====================================================================
-- Sources:
--   - Polarion / Jama (Requirements) → REST via DBMS_CLOUD.SEND_REQUEST
--   - Defect tracker (Jira-style)    → REST
--   - Test execution system          → REST or DB-Link
--   - Source repos (Git metadata)    → External Tables on Object Storage
-- =====================================================================

-- Credential
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'POLARION_CRED',
    username => '&POLARION_USER', password => '&POLARION_PWD'
  );
EXCEPTION WHEN OTHERS THEN IF SQLCODE = -20022 THEN NULL; ELSE RAISE; END IF; END;
/

-- ---------------------------------------------------------------------
-- 1a. Requirements pipelined from Polarion
-- ---------------------------------------------------------------------
CREATE OR REPLACE TYPE req_t AS OBJECT (
  req_id          VARCHAR2(40),
  project_id      VARCHAR2(40),
  title           VARCHAR2(400),
  description     CLOB,
  status          VARCHAR2(40),
  priority        VARCHAR2(20),
  classification  VARCHAR2(40),
  clearance_required VARCHAR2(20),
  releasable_to   VARCHAR2(100),
  last_modified   TIMESTAMP
);
/
CREATE OR REPLACE TYPE req_tab IS TABLE OF req_t;
/

CREATE OR REPLACE FUNCTION polarion_reqs_pipe(
  p_project VARCHAR2 DEFAULT NULL
) RETURN req_tab PIPELINED AS
  l_resp DBMS_CLOUD_TYPES.RESP;
  l_json JSON_OBJECT_T;
  l_arr  JSON_ARRAY_T;
  l_item JSON_OBJECT_T;
BEGIN
  l_resp := DBMS_CLOUD.SEND_REQUEST(
    credential_name => 'POLARION_CRED',
    uri             => 'https://&SWASSURE_POLARION_HOST/polarion/rest/v1/projects/' ||
                       NVL(p_project, 'all') || '/workitems?type=requirement',
    method          => DBMS_CLOUD.METHOD_GET
  );
  l_json := JSON_OBJECT_T.PARSE(DBMS_CLOUD.GET_RESPONSE_TEXT(l_resp));
  l_arr  := l_json.GET_ARRAY('data');
  FOR i IN 0 .. l_arr.GET_SIZE - 1 LOOP
    l_item := TREAT(l_arr.GET(i) AS JSON_OBJECT_T);
    PIPE ROW(req_t(
      l_item.GET_STRING('id'),
      l_item.GET_STRING('projectId'),
      l_item.GET_STRING('title'),
      l_item.GET_STRING('description'),
      l_item.GET_STRING('status'),
      l_item.GET_STRING('priority'),
      l_item.GET_STRING('classification'),
      l_item.GET_STRING('clearanceRequired'),
      l_item.GET_STRING('releasableTo'),
      TO_TIMESTAMP(l_item.GET_STRING('updated'),'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    ));
  END LOOP;
  RETURN;
END;
/

-- Similar pipe functions exist in production for tests, defects, links
-- (omitted here; pattern is identical).

-- ---------------------------------------------------------------------
-- 1b. External Tables for Git metadata exports (commits, code reviews)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name      => 'git_commits_ext',
    credential_name => 'OBJ_STORE_CRED',
    file_uri_list   => 'https://objectstorage.&OCI_REGION..oraclecloud.com/n/&OCI_NAMESPACE/b/defence-git/o/commits/*.json',
    format          => JSON_OBJECT('type' VALUE 'json'),
    column_list     => 'commit_sha VARCHAR2(40), repo VARCHAR2(100), author_email VARCHAR2(200), authored_at TIMESTAMP, message CLOB, linked_req VARCHAR2(40)'
  );
END;
/

PROMPT UC3 step 1 (federate) complete.
