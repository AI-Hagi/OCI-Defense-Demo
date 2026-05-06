-- =====================================================================
-- UC #2 Quality & Incident Analysis — Step 1: Federate Data
-- =====================================================================
-- Sources:
--   - Quality DB (Oracle/Postgres) → Heterogeneous Connectivity DB-Link
--   - SPC time-series CSV in Object Storage → External Table
--   - NCR PDFs (Non-Conformance Reports) in Object Storage → External
-- =====================================================================

-- DEFINE QUALITY_DB_HOST    = quality.contractor.internal
-- DEFINE QUALITY_DB_PORT    = 1521
-- DEFINE QUALITY_DB_SERVICE = qualpdb
-- DEFINE QUALITY_DB_USER    = quality_reader
-- DEFINE QUALITY_DB_PWD     = __FILL_IN__

BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'QUALITY_DB_CRED',
    username        => '&QUALITY_DB_USER',
    password        => '&QUALITY_DB_PWD'
  );
EXCEPTION WHEN OTHERS THEN IF SQLCODE = -20022 THEN NULL; ELSE RAISE; END IF; END;
/

-- ---------------------------------------------------------------------
-- 1a. DB-Link to Quality DB (assumes Oracle source; for Postgres
--     change gateway_params accordingly)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD_ADMIN.CREATE_DATABASE_LINK(
    db_link_name    => 'QUALITY_DB_LINK',
    hostname        => '&QUALITY_DB_HOST',
    port            => '&QUALITY_DB_PORT',
    service_name    => '&QUALITY_DB_SERVICE',
    credential_name => 'QUALITY_DB_CRED',
    private_target  => TRUE
  );
EXCEPTION WHEN OTHERS THEN IF SQLCODE = -2018 THEN NULL; ELSE RAISE; END IF; END;
/

-- ---------------------------------------------------------------------
-- 1b. External Table for SPC time-series (CSV in Object Storage)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name      => 'spc_measurements_ext',
    credential_name => 'OBJ_STORE_CRED',
    file_uri_list   => 'https://objectstorage.&OCI_REGION..oraclecloud.com/n/&OCI_NAMESPACE/b/defence-spc/o/*.csv',
    format          => JSON_OBJECT(
                         'type'        VALUE 'csv',
                         'skipheaders' VALUE 1,
                         'delimiter'   VALUE ',',
                         'recorddelimiter' VALUE '''\n''',
                         'rejectlimit' VALUE 'unlimited'
                       ),
    column_list     => 'measurement_ts TIMESTAMP, plant_code VARCHAR2(10), line_code VARCHAR2(20), part_number VARCHAR2(40), parameter_name VARCHAR2(60), measured_value NUMBER, lsl NUMBER, usl NUMBER'
  );
END;
/

-- ---------------------------------------------------------------------
-- 1c. External Table for NCR documents (PDF/DOCX)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name      => 'ncr_docs_ext',
    credential_name => 'OBJ_STORE_CRED',
    file_uri_list   => 'https://objectstorage.&OCI_REGION..oraclecloud.com/n/&OCI_NAMESPACE/b/defence-ncr/o/*',
    format          => JSON_OBJECT('type' VALUE 'document', 'characterset' VALUE 'UTF8'),
    column_list     => 'doc_id VARCHAR2(100), file_name VARCHAR2(400), content CLOB'
  );
END;
/

PROMPT UC2 step 1 (federate) complete.
