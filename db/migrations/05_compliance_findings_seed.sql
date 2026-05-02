-- ===========================================================================
-- Migration: compliance_findings demo seed
-- ---------------------------------------------------------------------------
-- The Compliance view (UC6) renders ScoreCards for NIS2/DORA/GDPR/VSNFD that
-- depend on `implemented` counts from compliance_findings (status in
-- ('mitigated','closed')). The findings table was empty, so every framework
-- showed 0% — visually broken even though 31 controls were seeded.
--
-- This seed inserts exactly one "current" finding per control with a
-- deterministic status derived from STANDARD_HASH(code). Roughly 70% land
-- on 'mitigated' / 'closed' (the implementation/satisfaction terminal
-- states) and ~30% on 'open' / 'accepted' / 'false_positive'. Stable across
-- re-runs — same input -> same status.
--
-- Idempotent: deletes any prior demo-seed findings for T001 first, then
-- inserts a fresh row per control. We don't merge because the natural key
-- is the (control_id, status, detected_at) triple and a single "current
-- finding per control" is enough for the score view to render.
--
-- Apply with: ADB_USER=ADMIN bash scripts/apply-migration.sh \
--             db/migrations/05_compliance_findings_seed.sql
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
  v_status   VARCHAR2(20);
  v_bucket   NUMBER;
  v_count    NUMBER;
  v_impl     NUMBER := 0;
  v_open     NUMBER := 0;
BEGIN
  -- Wipe any prior demo-seed rows so the re-run is deterministic.
  DELETE FROM compliance_findings
  WHERE control_id IN (
    SELECT control_id FROM compliance_controls WHERE tenant_id = 'T001'
  );

  FOR rec IN (
    SELECT control_id, code FROM compliance_controls
    WHERE tenant_id = 'T001'
    ORDER BY framework, code
  ) LOOP
    -- Deterministic bucket 0..9 from the control code.
    SELECT MOD(TO_NUMBER(SUBSTR(STANDARD_HASH(rec.code, 'MD5'), 1, 4), 'XXXX'), 10)
      INTO v_bucket FROM dual;

    -- 0..6  -> 'mitigated' / 'closed' (implemented)   ~70%
    -- 7     -> 'accepted'  (compensating control accepted, not implemented)
    -- 8     -> 'open'      (unresolved finding)
    -- 9     -> 'false_positive'
    v_status :=
      CASE
        WHEN v_bucket <= 3 THEN 'mitigated'
        WHEN v_bucket <= 6 THEN 'closed'
        WHEN v_bucket = 7  THEN 'accepted'
        WHEN v_bucket = 8  THEN 'open'
        ELSE 'false_positive'
      END;

    IF v_status IN ('mitigated', 'closed') THEN
      v_impl := v_impl + 1;
    ELSE
      v_open := v_open + 1;
    END IF;

    INSERT INTO compliance_findings
      (control_id, status, detected_at, evidence_ref, ols_label)
    VALUES
      (rec.control_id, v_status,
       SYSTIMESTAMP - NUMTODSINTERVAL(MOD(v_bucket, 5), 'DAY'),
       'demo-seed:'||rec.code, 20);
  END LOOP;

  COMMIT;
  SELECT COUNT(*) INTO v_count FROM compliance_findings;
  DBMS_OUTPUT.PUT_LINE(
    'compliance_findings seeded: total='||v_count||
    ' implemented='||v_impl||' open='||v_open);
END;
/

-- Tail-sanity
DECLARE
  v_n NUMBER;
  v_impl NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_n FROM compliance_findings f
   WHERE EXISTS (SELECT 1 FROM compliance_controls c
                  WHERE c.control_id = f.control_id AND c.tenant_id = 'T001');
  SELECT COUNT(*) INTO v_impl FROM compliance_findings f
   JOIN compliance_controls c ON c.control_id = f.control_id
   WHERE c.tenant_id = 'T001' AND f.status IN ('mitigated','closed');
  IF v_n < 31 OR v_impl < 1 THEN
    RAISE_APPLICATION_ERROR(-20011,
      '05_compliance_findings_seed.sql: expected at least 31 findings (1/control) '||
      'and at least 1 implemented; got total='||v_n||' impl='||v_impl);
  END IF;
  DBMS_OUTPUT.PUT_LINE(
    '05_compliance_findings_seed.sql OK: findings='||v_n||' implemented='||v_impl);
END;
/
