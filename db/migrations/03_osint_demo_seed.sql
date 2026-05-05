-- ===========================================================================
-- Migration: osint_entities + osint_relationships demo seed
-- ---------------------------------------------------------------------------
-- The OsintView (UC4 OSINT-Fusion) was wired against an empty graph: the
-- table `osint_entities` had no rows so every fetch returned an empty
-- node list. This migration seeds a coherent Baltic / Suwałki narrative
-- that matches the UC4_OSINT schema's Tag-5 demo (Shadow-Tanker A,
-- MV Kaskol, Baltic Oil Ltd, Bornholm Deep, Suwalki-Lücke) so the two
-- views read as one story.
--
-- Idempotent:
--   * Uses MERGE INTO with a deterministic entity_id derived from a
--     stable "ent:<slug>" external key, so re-applying overwrites the
--     same rows instead of creating duplicates.
--   * Relationships use a similar deterministic rel_id "rel:<slug>" key.
--
-- Apply with: ADB_USER=ADMIN bash scripts/apply-migration.sh \
--             db/migrations/03_osint_demo_seed.sql
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- ---------------------------------------------------------------------------
-- Helper: deterministic id derived from a slug (16-byte RAW). Same input
-- always yields the same entity_id so re-runs are idempotent.
-- ---------------------------------------------------------------------------
DECLARE
  TYPE t_ent IS RECORD (
    slug   VARCHAR2(48),
    kind   VARCHAR2(40),
    name   VARCHAR2(400),
    attrs  VARCHAR2(2000)
  );
  TYPE t_ent_tab IS TABLE OF t_ent INDEX BY PLS_INTEGER;
  v t_ent_tab;
  v_eid RAW(16);
  v_count NUMBER;

  TYPE t_rel IS RECORD (
    slug    VARCHAR2(96),
    src     VARCHAR2(48),
    dst     VARCHAR2(48),
    rtype   VARCHAR2(60),
    conf    NUMBER,
    evid    VARCHAR2(2000)
  );
  TYPE t_rel_tab IS TABLE OF t_rel INDEX BY PLS_INTEGER;
  r t_rel_tab;
  v_rid RAW(16);
  v_src RAW(16);
  v_dst RAW(16);

  FUNCTION slug_to_id(p_slug VARCHAR2) RETURN RAW IS
    -- STANDARD_HASH is a SQL function and not callable directly from PL/SQL
    -- under restricted ADB grants; wrap via SELECT FROM dual.
    v_raw RAW(16);
  BEGIN
    SELECT STANDARD_HASH(p_slug, 'MD5') INTO v_raw FROM dual;
    RETURN v_raw;
  END;
BEGIN
  -- ENTITIES --
  v(1).slug:='shadow-tanker-a';      v(1).kind:='vessel';
  v(1).name:='Unknown Shadow-Tanker A';
  v(1).attrs:='{"flag":"unknown","mmsi":"423000001","class":"ULCC"}';
  v(2).slug:='mv-kaskol';            v(2).kind:='vessel';
  v(2).name:='MV Kaskol';
  v(2).attrs:='{"flag":"RU","mmsi":"273456790","class":"Aframax"}';
  v(3).slug:='baltic-oil-ltd';       v(3).kind:='organization';
  v(3).name:='Baltic Oil Ltd';
  v(3).attrs:='{"country":"RU","ogrn":"RU_OGRN_555","sector":"oil-trading"}';
  v(4).slug:='bornholm-deep';        v(4).kind:='location';
  v(4).name:='Bornholm Deep';
  v(4).attrs:='{"area":"Baltic","lat":55.18,"lon":15.1,"depth_m":75}';
  v(5).slug:='suwalki-gap';          v(5).kind:='location';
  v(5).name:='Suwalki-Luecke';
  v(5).attrs:='{"area":"Border-PL-LT","strategic":true}';
  v(6).slug:='kaliningrad-port';     v(6).kind:='location';
  v(6).name:='Kaliningrad Port';
  v(6).attrs:='{"area":"Baltic","lat":54.71,"lon":20.51}';
  v(7).slug:='hel-naval';            v(7).kind:='location';
  v(7).name:='Hel Peninsula Naval';
  v(7).attrs:='{"area":"Baltic","lat":54.61,"lon":18.81,"force":"PL-Navy"}';
  v(8).slug:='actor-redfleet';       v(8).kind:='actor';
  v(8).name:='Threat Actor RedFleet';
  v(8).attrs:='{"motivation":"state-sponsored","origin":"RU"}';
  v(9).slug:='ind-jamming';          v(9).kind:='indicator';
  v(9).name:='GPS-Jamming Cluster Suwalki';
  v(9).attrs:='{"signal":"L1-1575.42MHz","intensity":"high","last_seen":"2026-04-30"}';
  v(10).slug:='evt-ais-spoofing';    v(10).kind:='event';
  v(10).name:='AIS-Spoofing Bornholm 2026-04-28';
  v(10).attrs:='{"observed":"2026-04-28T03:14:00Z","source":"NATO-MARCOM"}';
  v(11).slug:='asset-pipeline';      v(11).kind:='asset';
  v(11).name:='Subsea Cable Cluster Baltic';
  v(11).attrs:='{"type":"submarine-cable","operator":"NORDLINK"}';
  v(12).slug:='org-blue-task';       v(12).kind:='organization';
  v(12).name:='NATO MARCOM Task Group BLUE';
  v(12).attrs:='{"country":"NATO","role":"surveillance"}';

  FOR i IN 1 .. v.COUNT LOOP
    v_eid := slug_to_id(v(i).slug);
    MERGE INTO osint_entities oe
    USING (SELECT v_eid AS eid FROM dual) s
    ON (oe.entity_id = s.eid)
    WHEN MATCHED THEN UPDATE SET
      oe.canonical_name = v(i).name,
      oe.kind           = v(i).kind,
      oe.attributes     = v(i).attrs,
      oe.ols_label      = 30
    WHEN NOT MATCHED THEN INSERT
      (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
    VALUES
      (s.eid, 'T001', v(i).kind, v(i).name, v(i).attrs, 30);
  END LOOP;
  COMMIT;
  SELECT COUNT(*) INTO v_count FROM osint_entities;
  DBMS_OUTPUT.PUT_LINE('Entities upserted; total in osint_entities = '||v_count);

  -- RELATIONSHIPS --
  -- Each rel: src slug -> dst slug, rel_type, confidence
  r(1).slug:='kaskol-owned-by-baltic-oil';
  r(1).src:='mv-kaskol'; r(1).dst:='baltic-oil-ltd';
  r(1).rtype:='owned_by'; r(1).conf:=0.92;
  r(1).evid:='{"source":"OFAC-2026-Q1","doc":"sanction-listing"}';

  r(2).slug:='shadow-near-bornholm';
  r(2).src:='shadow-tanker-a'; r(2).dst:='bornholm-deep';
  r(2).rtype:='located_at'; r(2).conf:=0.78;
  r(2).evid:='{"source":"AIS-cross-check","gap_minutes":18}';

  r(3).slug:='kaskol-near-bornholm';
  r(3).src:='mv-kaskol'; r(3).dst:='bornholm-deep';
  r(3).rtype:='located_at'; r(3).conf:=0.81;
  r(3).evid:='{"source":"AIS-cross-check"}';

  r(4).slug:='shadow-co-located-kaskol';
  r(4).src:='shadow-tanker-a'; r(4).dst:='mv-kaskol';
  r(4).rtype:='co_located_with'; r(4).conf:=0.74;
  r(4).evid:='{"window_h":4,"distance_km":2.1}';

  r(5).slug:='evt-involves-shadow';
  r(5).src:='evt-ais-spoofing'; r(5).dst:='shadow-tanker-a';
  r(5).rtype:='mentions'; r(5).conf:=0.86;
  r(5).evid:='{"source":"NATO-MARCOM-spotrep"}';

  r(6).slug:='evt-involves-kaskol';
  r(6).src:='evt-ais-spoofing'; r(6).dst:='mv-kaskol';
  r(6).rtype:='mentions'; r(6).conf:=0.71;
  r(6).evid:='{"source":"NATO-MARCOM-spotrep"}';

  r(7).slug:='actor-uses-jamming';
  r(7).src:='actor-redfleet'; r(7).dst:='ind-jamming';
  r(7).rtype:='uses_ttp'; r(7).conf:=0.83;
  r(7).evid:='{"ttp":"GPS-jamming","mitre_ref":"T1565.003"}';

  r(8).slug:='jamming-at-suwalki';
  r(8).src:='ind-jamming'; r(8).dst:='suwalki-gap';
  r(8).rtype:='located_at'; r(8).conf:=0.90;
  r(8).evid:='{"source":"FlightRadar24+GPSJam"}';

  r(9).slug:='actor-targets-pipeline';
  r(9).src:='actor-redfleet'; r(9).dst:='asset-pipeline';
  r(9).rtype:='targets'; r(9).conf:=0.65;
  r(9).evid:='{"hypothesis":"sabotage-Q2-2026"}';

  r(10).slug:='blue-monitors-bornholm';
  r(10).src:='org-blue-task'; r(10).dst:='bornholm-deep';
  r(10).rtype:='monitors'; r(10).conf:=0.95;
  r(10).evid:='{"task_group":"BLUE"}';

  r(11).slug:='blue-monitors-suwalki';
  r(11).src:='org-blue-task'; r(11).dst:='suwalki-gap';
  r(11).rtype:='monitors'; r(11).conf:=0.92;
  r(11).evid:='{"task_group":"BLUE"}';

  r(12).slug:='kaskol-from-kaliningrad';
  r(12).src:='mv-kaskol'; r(12).dst:='kaliningrad-port';
  r(12).rtype:='departed_from'; r(12).conf:=0.88;
  r(12).evid:='{"source":"AIS-history"}';

  r(13).slug:='actor-controls-baltic-oil';
  r(13).src:='actor-redfleet'; r(13).dst:='baltic-oil-ltd';
  r(13).rtype:='controls'; r(13).conf:=0.62;
  r(13).evid:='{"hypothesis":"shell-company"}';

  r(14).slug:='shadow-departed-kaliningrad';
  r(14).src:='shadow-tanker-a'; r(14).dst:='kaliningrad-port';
  r(14).rtype:='departed_from'; r(14).conf:=0.55;
  r(14).evid:='{"AIS_loss":"60min"}';

  r(15).slug:='evt-near-pipeline';
  r(15).src:='evt-ais-spoofing'; r(15).dst:='asset-pipeline';
  r(15).rtype:='occurred_near'; r(15).conf:=0.72;
  r(15).evid:='{"distance_km":4.7}';

  FOR i IN 1 .. r.COUNT LOOP
    v_rid := slug_to_id(r(i).slug);
    v_src := slug_to_id(r(i).src);
    v_dst := slug_to_id(r(i).dst);
    MERGE INTO osint_relationships orl
    USING (SELECT v_rid AS rid FROM dual) s
    ON (orl.rel_id = s.rid)
    WHEN MATCHED THEN UPDATE SET
      orl.src_id     = v_src,
      orl.dst_id     = v_dst,
      orl.rel_type   = r(i).rtype,
      orl.confidence = r(i).conf,
      orl.evidence   = r(i).evid,
      orl.ols_label  = 30
    WHEN NOT MATCHED THEN INSERT
      (rel_id, src_id, dst_id, rel_type, confidence, evidence, ols_label)
    VALUES
      (s.rid, v_src, v_dst, r(i).rtype, r(i).conf, r(i).evid, 30);
  END LOOP;
  COMMIT;
  SELECT COUNT(*) INTO v_count FROM osint_relationships;
  DBMS_OUTPUT.PUT_LINE('Relationships upserted; total in osint_relationships = '||v_count);
END;
/

-- ---------------------------------------------------------------------------
-- Tail-sanity: minimal expected counts.
-- ---------------------------------------------------------------------------
DECLARE
  v_ents NUMBER;
  v_rels NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_ents FROM osint_entities WHERE tenant_id='T001';
  SELECT COUNT(*) INTO v_rels FROM osint_relationships;
  IF v_ents < 12 OR v_rels < 15 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '03_osint_demo_seed.sql: expected at least 12 entities + 15 relationships, '||
      'got entities='||v_ents||', relationships='||v_rels);
  END IF;
  DBMS_OUTPUT.PUT_LINE(
    '03_osint_demo_seed.sql OK: entities='||v_ents||', relationships='||v_rels);
END;
/
