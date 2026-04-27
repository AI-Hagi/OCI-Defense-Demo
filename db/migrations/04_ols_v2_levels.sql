-- =============================================================================
--  Migration 04 — OLS v2 levels (CLAUDE_DEV9.md §Konventionen → Datenbank)
-- -----------------------------------------------------------------------------
--  Spec mandates:
--      UNCLASSIFIED  100
--      RESTRICTED    200
--      CONFIDENTIAL  300
--      SECRET        400
--
--  The original schema (db/schema/01_tenants_and_security.sql:61-93) used
--  10 / 30 / 50 / 70. This migration *adds* the new spec values without
--  removing the old ones — the drop happens in migration 08, gated by a
--  row-count probe so we never orphan a labelled row.
--
--  Idempotent: each SA_COMPONENTS.CREATE_LEVEL is wrapped with
--  ``EXCEPTION WHEN OTHERS THEN NULL`` mirroring the schema's own pattern.
-- =============================================================================
SET ECHO ON
SET DEFINE OFF

BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 100,
    short_name  => 'U2',
    long_name   => 'Unclassified (DEV9 v2)');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level U2: '||SQLERRM); END;
/

BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 200,
    short_name  => 'R2',
    long_name   => 'Restricted (DEV9 v2)');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level R2: '||SQLERRM); END;
/

BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 300,
    short_name  => 'C2',
    long_name   => 'Confidential (DEV9 v2)');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level C2: '||SQLERRM); END;
/

BEGIN
  SA_COMPONENTS.CREATE_LEVEL(
    policy_name => 'DICE_POLICY',
    level_num   => 400,
    short_name  => 'S2',
    long_name   => 'Secret (DEV9 v2)');
EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('level S2: '||SQLERRM); END;
/

COMMIT;
