-- ===========================================================================
-- Migration: replicate compliance_controls + findings for T002 and T003
-- ---------------------------------------------------------------------------
-- The original seed (db/seed/01_compliance_controls.sql) populated 31
-- controls only for T001 (DEU_BMVG). The Compliance view's tenant switcher
-- lets the user select FRA_DGA (T002) or NLD_MOD (T003) too — and for those
-- tenants the controls table comes back empty, which makes the framework
-- filter pills look broken (Filter NIS2 = nothing).
--
-- This migration mirrors the 31 T001 controls into T002 and T003 with fresh
-- control_ids (each tenant gets its own copy — uq_comp_controls_code is on
-- (tenant_id, framework, code) so the codes can repeat across tenants),
-- and seeds one current finding per new control with the same deterministic
-- status logic used in 05_compliance_findings_seed.sql so each tenant gets
-- a realistic implemented/open mix.
--
-- Idempotent: deletes existing T002 / T003 rows first.
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
  v_count NUMBER;
  v_status VARCHAR2(20);
  v_bucket NUMBER;
  v_impl   NUMBER := 0;
BEGIN
  ----------------------------------------------------------------------------
  -- 1) Wipe (cascades to compliance_findings via FK ON DELETE CASCADE)
  ----------------------------------------------------------------------------
  DELETE FROM compliance_controls WHERE tenant_id IN ('T002', 'T003');

  ----------------------------------------------------------------------------
  -- 2) Replicate the 31 T001 controls for T002 and T003
  ----------------------------------------------------------------------------
  FOR t IN (SELECT 'T002' AS tid FROM dual UNION ALL SELECT 'T003' FROM dual) LOOP
    INSERT INTO compliance_controls
      (control_id, framework, code, title, description, tenant_id, ols_label)
    SELECT RAWTOHEX(SYS_GUID()), framework, code, title, description, t.tid, ols_label
      FROM compliance_controls
     WHERE tenant_id = 'T001';
  END LOOP;
  COMMIT;

  SELECT COUNT(*) INTO v_count FROM compliance_controls WHERE tenant_id IN ('T002','T003');
  DBMS_OUTPUT.PUT_LINE('compliance_controls T002+T003 rows = '||v_count);

  ----------------------------------------------------------------------------
  -- 3) Seed findings for the new controls (same deterministic logic as
  --    05_compliance_findings_seed.sql so each tenant gets ~70% implemented).
  ----------------------------------------------------------------------------
  FOR rec IN (
    SELECT control_id, code FROM compliance_controls
    WHERE tenant_id IN ('T002', 'T003')
    ORDER BY tenant_id, framework, code
  ) LOOP
    SELECT MOD(TO_NUMBER(SUBSTR(STANDARD_HASH(rec.code, 'MD5'), 1, 4), 'XXXX'), 10)
      INTO v_bucket FROM dual;

    v_status :=
      CASE
        WHEN v_bucket <= 3 THEN 'mitigated'
        WHEN v_bucket <= 6 THEN 'closed'
        WHEN v_bucket = 7  THEN 'accepted'
        WHEN v_bucket = 8  THEN 'open'
        ELSE 'false_positive'
      END;
    IF v_status IN ('mitigated','closed') THEN v_impl := v_impl + 1; END IF;

    INSERT INTO compliance_findings
      (control_id, status, detected_at, evidence_ref, ols_label)
    VALUES
      (rec.control_id, v_status,
       SYSTIMESTAMP - NUMTODSINTERVAL(MOD(v_bucket, 5), 'DAY'),
       'demo-seed:'||rec.code, 20);
  END LOOP;
  COMMIT;

  SELECT COUNT(*) INTO v_count
    FROM compliance_findings f
    JOIN compliance_controls c ON c.control_id = f.control_id
   WHERE c.tenant_id IN ('T002','T003');
  DBMS_OUTPUT.PUT_LINE(
    'compliance_findings T002+T003 rows = '||v_count||' (implemented='||v_impl||')');
END;
/

-- Tail-sanity
DECLARE
  v_t002 NUMBER; v_t003 NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_t002 FROM compliance_controls WHERE tenant_id = 'T002';
  SELECT COUNT(*) INTO v_t003 FROM compliance_controls WHERE tenant_id = 'T003';
  IF v_t002 < 31 OR v_t003 < 31 THEN
    RAISE_APPLICATION_ERROR(-20012,
      '06_compliance_controls_t002_t003.sql: expected at least 31 controls per tenant, '||
      'got T002='||v_t002||' T003='||v_t003);
  END IF;
  DBMS_OUTPUT.PUT_LINE(
    '06_compliance_controls_t002_t003.sql OK: T002='||v_t002||' T003='||v_t003);
END;
/
