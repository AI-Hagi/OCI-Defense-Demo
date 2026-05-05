-- ===========================================================================
-- Migration: collab_shares — add title column + 3-way demo seed
-- ---------------------------------------------------------------------------
-- The Zusammenarbeit (UC3 Multi-Tenant Collaboration) view paints a
-- DICE-EU-style federated dashboard with one column per tenant. To make
-- that dashboard meaningful, each share needs:
--   1) a human-readable title (artefact_id alone is opaque),
--   2) demo data so the columns aren't always empty.
--
-- This migration is idempotent:
--   * ALTER TABLE wraps the column add in BEGIN..EXCEPTION; ORA-1430
--     (column already exists) is swallowed.
--   * The seed uses a marker source_uri pattern so re-applying skips
--     rows that are already present.
--
-- Apply with: ADB_USER=ADMIN bash scripts/apply-migration.sh \
--             db/migrations/02_collab_shares_title_and_seed.sql
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------------
-- (1) Add title column (nullable). Backend reads it via SELECT; old rows
--     return NULL and the frontend falls back to artefact_id.
-- ---------------------------------------------------------------------------
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE collab_shares ADD title VARCHAR2(400)';
  DBMS_OUTPUT.PUT_LINE('Added column collab_shares.title.');
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE = -1430 THEN
    DBMS_OUTPUT.PUT_LINE('Column collab_shares.title already exists - skipping.');
  ELSE
    RAISE;
  END IF;
END;
/

-- ---------------------------------------------------------------------------
-- (2) Seed three demo shares — one per tenant pair so all three columns
--     show data on first load.
--
--     Existence check uses (owner_tenant, partner_tenant, artefact_type,
--     artefact_id) which is unique enough for the seed.
-- ---------------------------------------------------------------------------
DECLARE
  TYPE t_share IS RECORD (
    owner_tenant   VARCHAR2(36),
    partner_tenant VARCHAR2(36),
    artefact_type  VARCHAR2(40),
    artefact_id    VARCHAR2(64),
    title          VARCHAR2(400),
    ols_label      NUMBER,
    days_valid     NUMBER
  );
  TYPE t_share_tab IS TABLE OF t_share INDEX BY PLS_INTEGER;
  v_shares t_share_tab;
  v_count  NUMBER;
BEGIN
  v_shares(1).owner_tenant   := 'T001';  v_shares(1).partner_tenant := 'T002';
  v_shares(1).artefact_type  := 'document';
  v_shares(1).artefact_id    := 'BMVG-DGA-LAGEBILD-2026Q2';
  v_shares(1).title          := 'BMVg -> DGA Lagebild Q2/2026';
  v_shares(1).ols_label      := 30;
  v_shares(1).days_valid     := 90;

  v_shares(2).owner_tenant   := 'T002';  v_shares(2).partner_tenant := 'T003';
  v_shares(2).artefact_type  := 'osint_entity';
  v_shares(2).artefact_id    := 'DGA-MOD-AUFKLAERUNG-OSTSEE';
  v_shares(2).title          := 'DGA -> MoD Aufklaerung Ostsee';
  v_shares(2).ols_label      := 50;
  v_shares(2).days_valid     := 60;

  v_shares(3).owner_tenant   := 'T003';  v_shares(3).partner_tenant := 'T001';
  v_shares(3).artefact_type  := 'compliance_finding';
  v_shares(3).artefact_id    := 'MOD-BMVG-NIS2-CONTROL-44';
  v_shares(3).title          := 'MoD -> BMVg Threat Actor Briefing';
  v_shares(3).ols_label      := 30;
  v_shares(3).days_valid     := 30;

  FOR i IN 1 .. v_shares.COUNT LOOP
    SELECT COUNT(*) INTO v_count
      FROM collab_shares
     WHERE owner_tenant   = v_shares(i).owner_tenant
       AND partner_tenant = v_shares(i).partner_tenant
       AND artefact_type  = v_shares(i).artefact_type
       AND artefact_id    = v_shares(i).artefact_id;

    IF v_count = 0 THEN
      INSERT INTO collab_shares
        (owner_tenant, partner_tenant, artefact_type, artefact_id,
         expires_at, ols_label, title)
      VALUES
        (v_shares(i).owner_tenant, v_shares(i).partner_tenant,
         v_shares(i).artefact_type, v_shares(i).artefact_id,
         SYSTIMESTAMP + NUMTODSINTERVAL(v_shares(i).days_valid, 'DAY'),
         v_shares(i).ols_label, v_shares(i).title);
      DBMS_OUTPUT.PUT_LINE(
        'Seeded share #' || i || ': ' || v_shares(i).title);
    ELSE
      DBMS_OUTPUT.PUT_LINE(
        'Share #' || i || ' already present - skipping (' ||
        v_shares(i).artefact_id || ').');
    END IF;
  END LOOP;
  COMMIT;
END;
/

-- ---------------------------------------------------------------------------
-- Tail-sanity: confirm we have at least three shares, one per ordered
-- tenant pair (T001->T002, T002->T003, T003->T001).
-- ---------------------------------------------------------------------------
DECLARE
  v_total NUMBER;
  v_pair1 NUMBER;
  v_pair2 NUMBER;
  v_pair3 NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_total FROM collab_shares;
  SELECT COUNT(*) INTO v_pair1 FROM collab_shares
   WHERE owner_tenant='T001' AND partner_tenant='T002';
  SELECT COUNT(*) INTO v_pair2 FROM collab_shares
   WHERE owner_tenant='T002' AND partner_tenant='T003';
  SELECT COUNT(*) INTO v_pair3 FROM collab_shares
   WHERE owner_tenant='T003' AND partner_tenant='T001';
  IF v_pair1 < 1 OR v_pair2 < 1 OR v_pair3 < 1 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '02_collab_shares_title_and_seed.sql: ' ||
      'expected at least one share per tenant pair, got '||
      'T001->T002='||v_pair1||', T002->T003='||v_pair2||
      ', T003->T001='||v_pair3);
  END IF;
  DBMS_OUTPUT.PUT_LINE(
    '02_collab_shares_title_and_seed.sql OK: total='||v_total||
    ' (T001->T002='||v_pair1||', T002->T003='||v_pair2||
    ', T003->T001='||v_pair3||')');
END;
/
