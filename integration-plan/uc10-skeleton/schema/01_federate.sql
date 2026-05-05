-- =====================================================================
-- UC #10 Requirements Intelligence — Step 1: Federate Data
-- =====================================================================
-- Sources:
--   - ReqIF-XML in OCI Object Storage (zentraler Hub für DOORS / Polarion / Codebeamer Exporte)
--   - Optional: DOORS NG REST via DBMS_CLOUD.SEND_REQUEST
--   - Optional: Polarion REST via DBMS_CLOUD.SEND_REQUEST
-- =====================================================================

-- DEFINE OCI_NAMESPACE       = your-tenancy-namespace
-- DEFINE OCI_REGION          = eu-frankfurt-1
-- DEFINE OCI_USER_OCID       = ocid1.user.oc1..__FILL__
-- DEFINE OCI_TENANCY_OCID    = ocid1.tenancy.oc1..__FILL__
-- DEFINE OCI_API_KEY_PEM     = -----BEGIN PRIVATE KEY-----...
-- DEFINE OCI_API_KEY_FINGERPRINT = aa:bb:cc:...

-- ---------------------------------------------------------------------
-- 1a. Object Storage credential (idempotent)
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
-- 1b. External Table for ReqIF imports (XML files in Object Storage)
-- ---------------------------------------------------------------------
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name      => 'reqif_imports_ext',
    credential_name => 'OBJ_STORE_CRED',
    file_uri_list   => 'https://objectstorage.&OCI_REGION..oraclecloud.com/n/&OCI_NAMESPACE/b/defence-reqif/o/*.xml',
    format          => JSON_OBJECT(
                         'type'         VALUE 'document',
                         'characterset' VALUE 'UTF8'
                       ),
    column_list     => 'import_id VARCHAR2(100), file_name VARCHAR2(400), raw_xml CLOB'
  );
END;
/

-- ---------------------------------------------------------------------
-- 1c. Programs catalogue (master table — populated by sample-data/load_sample_data.sql)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS programs (
  program_id          VARCHAR2(40) PRIMARY KEY,
  name                VARCHAR2(200) NOT NULL,
  domain              VARCHAR2(100),
  security_class      VARCHAR2(20)  NOT NULL,
  customer_country    VARCHAR2(10),
  start_year          NUMBER(4),
  status              VARCHAR2(20),     -- ACTIVE, ARCHIVED, BIDDING
  clearance_required  VARCHAR2(20)  DEFAULT 'RESTRICTED',
  releasable_to       VARCHAR2(100) DEFAULT 'NATO',
  created_at          TIMESTAMP DEFAULT SYSTIMESTAMP
);

-- ---------------------------------------------------------------------
-- 1d. Optional: DOORS NG / Polarion REST credentials
--     (uncomment and populate when wiring up real source systems)
-- ---------------------------------------------------------------------
-- BEGIN
--   DBMS_CLOUD.CREATE_CREDENTIAL(
--     credential_name => 'DOORS_NG_CRED',
--     username        => '&DOORS_USER',
--     password        => '&DOORS_PWD'
--   );
-- EXCEPTION WHEN OTHERS THEN IF SQLCODE = -20022 THEN NULL; ELSE RAISE; END IF; END;
-- /

PROMPT UC10 step 1 (federate) complete.
