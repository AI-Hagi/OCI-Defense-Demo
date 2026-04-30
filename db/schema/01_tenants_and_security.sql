-- =====================================================================
-- Sovereign Defence Intelligence Platform
-- File: 01_tenants_and_security.sql
-- Purpose: Tenant master table + Oracle Label Security (OLS) policy
--          DICE_POLICY (labels, compartments, groups) + optional
--          Database Vault realm + demo tenants (DEU/FRA/NLD).
-- Target : Oracle AI Database 26ai (Autonomous Transaction Processing)
-- Runs first: defines OLS primitives consumed by 02_ - 07_.
-- =====================================================================

SET SERVEROUTPUT ON SIZE UNLIMITED
SET DEFINE OFF
WHENEVER SQLERROR CONTINUE

-- ---------------------------------------------------------------------
-- 1. Tenant master table
-- ---------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE '
    CREATE TABLE tenants (
      tenant_id     VARCHAR2(36)  PRIMARY KEY,
      display_name  VARCHAR2(200) NOT NULL,
      short_code    VARCHAR2(10)  UNIQUE NOT NULL,
      country_iso3  CHAR(3)       NOT NULL,
      home_region   VARCHAR2(40)  DEFAULT ''eu-frankfurt-1'',
      created_at    TIMESTAMP     DEFAULT SYSTIMESTAMP,
      ols_label     NUMBER
    )';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN
      DBMS_OUTPUT.PUT_LINE('tenants table already exists - skipping');
    ELSE
      DBMS_OUTPUT.PUT_LINE('tenants create error: '||SQLERRM);
    END IF;
END;
/

COMMENT ON TABLE  tenants              IS 'Registered sovereign tenants (e.g. BMVg, DGA, MoD)';
COMMENT ON COLUMN tenants.tenant_id    IS 'Opaque UUID used across all domain tables as FK';
COMMENT ON COLUMN tenants.short_code   IS 'Human-readable short code (DEU_BMVG, FRA_DGA, ...)';
COMMENT ON COLUMN tenants.home_region  IS 'OCI sovereign region (default eu-frankfurt-1)';
COMMENT ON COLUMN tenants.ols_label    IS 'OLS label tag attached to the tenant row itself';

-- ---------------------------------------------------------------------
-- 2. OLS policy DICE_POLICY
-- ---------------------------------------------------------------------
BEGIN
  SA_SYSDBA.CREATE_POLICY(
    policy_name     => 'DICE_POLICY',
    column_name     => 'OLS_LABEL',
    default_options => 'LABEL_DEFAULT,NO_CONTROL');
  DBMS_OUTPUT.PUT_LINE('DICE_POLICY created');
EXCEPTION
  WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('DICE_POLICY create skipped: '||SQLERRM);
END;
/

-- ---------------------------------------------------------------------
-- 3. Levels  (U=10, R=30, C=50, S=70)
-- ---------------------------------------------------------------------
BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 10,
    short_name  => 'U',
    long_name   => 'Unclassified');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level U: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 30,
    short_name  => 'R',
    long_name   => 'Restricted');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level R: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 50,
    short_name  => 'C',
    long_name   => 'Confidential');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level C: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 70,
    short_name  => 'S',
    long_name   => 'Secret');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level S: '||SQLERRM); END;
/

-- ---------------------------------------------------------------------
-- 4. Compartments  (INTEL=100, OPS=110, LOG=120, LEGAL=130)
-- ---------------------------------------------------------------------
BEGIN
  SA_COMPONENTS.CREATE_COMPARTMENT(
    policy_name => 'DICE_POLICY',
    comp_num    => 100,
    short_name  => 'INTEL',
    long_name   => 'Intelligence');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('comp INTEL: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_COMPARTMENT(
    policy_name => 'DICE_POLICY',
    comp_num    => 110,
    short_name  => 'OPS',
    long_name   => 'Operations');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('comp OPS: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_COMPARTMENT(
    policy_name => 'DICE_POLICY',
    comp_num    => 120,
    short_name  => 'LOG',
    long_name   => 'Logistics');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('comp LOG: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_COMPARTMENT(
    policy_name => 'DICE_POLICY',
    comp_num    => 130,
    short_name  => 'LEGAL',
    long_name   => 'Legal');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('comp LEGAL: '||SQLERRM); END;
/

-- ---------------------------------------------------------------------
-- 5. Groups  (one per demo tenant: DEU=1000, FRA=1010, NLD=1020)
-- ---------------------------------------------------------------------
BEGIN
  SA_COMPONENTS.CREATE_GROUP(
    policy_name => 'DICE_POLICY',
    group_num   => 1000,
    short_name  => 'DEU',
    long_name   => 'Germany BMVg');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('group DEU: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_GROUP(
    policy_name => 'DICE_POLICY',
    group_num   => 1010,
    short_name  => 'FRA',
    long_name   => 'France DGA');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('group FRA: '||SQLERRM); END;
/
BEGIN
  SA_COMPONENTS.CREATE_GROUP(
    policy_name => 'DICE_POLICY',
    group_num   => 1020,
    short_name  => 'NLD',
    long_name   => 'Netherlands MoD');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('group NLD: '||SQLERRM); END;
/

-- ---------------------------------------------------------------------
-- 6. Label bindings (label_tag = numeric handle used in ols_label)
--    Format: U:INTEL:<GROUP>
-- ---------------------------------------------------------------------
BEGIN
  SA_LABEL_ADMIN.CREATE_LABEL(
    policy_name => 'DICE_POLICY',
    label_tag   => 10001000,
    label_value => 'U:INTEL:DEU');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('label DEU: '||SQLERRM); END;
/
BEGIN
  SA_LABEL_ADMIN.CREATE_LABEL(
    policy_name => 'DICE_POLICY',
    label_tag   => 10001010,
    label_value => 'U:INTEL:FRA');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('label FRA: '||SQLERRM); END;
/
BEGIN
  SA_LABEL_ADMIN.CREATE_LABEL(
    policy_name => 'DICE_POLICY',
    label_tag   => 10001020,
    label_value => 'U:INTEL:NLD');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('label NLD: '||SQLERRM); END;
/

-- ---------------------------------------------------------------------
-- 7. Demo tenants seed (idempotent via MERGE)
-- ---------------------------------------------------------------------
MERGE INTO tenants t
USING (SELECT 'T001' AS tenant_id,
              'DEU_BMVG'              AS short_code,
              'Germany BMVg'          AS display_name,
              'DEU'                   AS country_iso3,
              'eu-frankfurt-1'        AS home_region,
              10001000                AS ols_label FROM dual) s
ON (t.tenant_id = s.tenant_id)
WHEN NOT MATCHED THEN INSERT
  (tenant_id, display_name, short_code, country_iso3, home_region, ols_label)
  VALUES
  (s.tenant_id, s.display_name, s.short_code, s.country_iso3, s.home_region, s.ols_label);

MERGE INTO tenants t
USING (SELECT 'T002' AS tenant_id,
              'FRA_DGA'               AS short_code,
              'France DGA'            AS display_name,
              'FRA'                   AS country_iso3,
              'eu-marseille-1'        AS home_region,
              10001010                AS ols_label FROM dual) s
ON (t.tenant_id = s.tenant_id)
WHEN NOT MATCHED THEN INSERT
  (tenant_id, display_name, short_code, country_iso3, home_region, ols_label)
  VALUES
  (s.tenant_id, s.display_name, s.short_code, s.country_iso3, s.home_region, s.ols_label);

MERGE INTO tenants t
USING (SELECT 'T003' AS tenant_id,
              'NLD_MOD'               AS short_code,
              'Netherlands MoD'       AS display_name,
              'NLD'                   AS country_iso3,
              'eu-amsterdam-1'        AS home_region,
              10001020                AS ols_label FROM dual) s
ON (t.tenant_id = s.tenant_id)
WHEN NOT MATCHED THEN INSERT
  (tenant_id, display_name, short_code, country_iso3, home_region, ols_label)
  VALUES
  (s.tenant_id, s.display_name, s.short_code, s.country_iso3, s.home_region, s.ols_label);

COMMIT;

-- ---------------------------------------------------------------------
-- 8. Database Vault realm (graceful degrade if DBV not enabled)
-- ---------------------------------------------------------------------
BEGIN
  DVSYS.DBMS_MACADM.CREATE_REALM(
    realm_name    => 'SOVDEFENCE_TENANT_REALM',
    description   => 'Per-tenant isolation realm for Sovereign Defence',
    enabled       => 'Y',
    audit_options => DBMS_MACUTL.G_REALM_AUDIT_FAIL + DBMS_MACUTL.G_REALM_AUDIT_SUCCESS,
    realm_type    => 1);
EXCEPTION
  WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('DBV realm skipped: '||SQLERRM);
END;
/

-- ---------------------------------------------------------------------
-- 9. Helper: apply DICE_POLICY to a table (used by sibling 07_* file)
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_apply_dice_policy(p_table IN VARCHAR2)
IS
BEGIN
  SA_POLICY_ADMIN.APPLY_TABLE_POLICY(
    policy_name      => 'DICE_POLICY',
    schema_name      => SYS_CONTEXT('USERENV','CURRENT_SCHEMA'),
    table_name       => UPPER(p_table),
    table_options    => 'READ_CONTROL,WRITE_CONTROL,CHECK_CONTROL,LABEL_DEFAULT',
    label_function   => NULL,
    predicate        => NULL);
  DBMS_OUTPUT.PUT_LINE('DICE_POLICY applied on '||UPPER(p_table));
EXCEPTION
  WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('apply_dice_policy('||p_table||') failed: '||SQLERRM);
END;
/

-- ---------------------------------------------------------------------
-- 10. Apply DICE_POLICY to tenants itself so the ols_label column is
--     actively enforced for tenant-row reads/writes.
-- ---------------------------------------------------------------------
BEGIN
  sp_apply_dice_policy('TENANTS');
END;
/

-- End of 01_tenants_and_security.sql
