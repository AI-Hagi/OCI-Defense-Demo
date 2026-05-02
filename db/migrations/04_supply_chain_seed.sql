-- ===========================================================================
-- Migration: sc_nodes / sc_edges / sc_risk demo seed
-- ---------------------------------------------------------------------------
-- The Lieferketten-Graph view (UC5) was wired against empty tables, so
-- the map pane was always blank. This seed creates a small but coherent
-- European defence-industrial supply chain:
--
--   * 13 nodes spanning mine -> supplier -> hub -> port -> factory
--     (Kiruna ore -> LKAB hub -> Kaliningrad/Hamburg ports -> KMW Munich /
--      Rheinmetall Unterluess factory tracks)
--   * 16 directed edges (ships_to, supplies, transports, depends_on, owned_by)
--   * 30 days of synthetic risk-score history per node, with a JSON breakdown
--     (geopolitical, sanctions, weather, cyber).
--
-- Idempotent: deterministic IDs derived from a slug-hash so re-applying
-- overwrites in place. Hash via STANDARD_HASH(...) wrapped in SELECT FROM
-- dual to satisfy ATP-Shared PL/SQL grants.
--
-- Apply with: ADB_USER=ADMIN bash scripts/apply-migration.sh \
--             db/migrations/04_supply_chain_seed.sql
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
  TYPE t_node IS RECORD (
    slug      VARCHAR2(48),
    ntype     VARCHAR2(40),
    name      VARCHAR2(200),
    country   CHAR(3),
    lat       NUMBER,
    lon       NUMBER,
    crit      NUMBER
  );
  TYPE t_node_tab IS TABLE OF t_node INDEX BY PLS_INTEGER;
  v t_node_tab;

  TYPE t_edge IS RECORD (
    slug    VARCHAR2(96),
    src     VARCHAR2(48),
    dst     VARCHAR2(48),
    etype   VARCHAR2(40),
    lead    NUMBER,
    dep     NUMBER
  );
  TYPE t_edge_tab IS TABLE OF t_edge INDEX BY PLS_INTEGER;
  e t_edge_tab;

  v_nid VARCHAR2(36);
  v_eid VARCHAR2(36);
  v_src VARCHAR2(36);
  v_dst VARCHAR2(36);
  v_count NUMBER;

  FUNCTION slug_to_id(p_slug VARCHAR2) RETURN VARCHAR2 IS
    v_raw RAW(16);
  BEGIN
    SELECT STANDARD_HASH(p_slug, 'MD5') INTO v_raw FROM dual;
    -- node_id is VARCHAR2(36); store as 32-char hex string.
    RETURN RAWTOHEX(v_raw);
  END;

BEGIN
  ----------------------------------------------------------------------------
  -- NODES
  ----------------------------------------------------------------------------
  v(1).slug:='kiruna-mine';        v(1).ntype:='mine';
  v(1).name:='Kiruna Iron Ore Mine';
  v(1).country:='SWE'; v(1).lat:=67.85; v(1).lon:=20.22; v(1).crit:=92;

  v(2).slug:='lkab-hub';           v(2).ntype:='hub';
  v(2).name:='LKAB Logistics Hub Lulea';
  v(2).country:='SWE'; v(2).lat:=65.58; v(2).lon:=22.16; v(2).crit:=78;

  v(3).slug:='narvik-port';        v(3).ntype:='port';
  v(3).name:='Narvik Iron-Ore Port';
  v(3).country:='NOR'; v(3).lat:=68.43; v(3).lon:=17.43; v(3).crit:=84;

  v(4).slug:='hamburg-port';       v(4).ntype:='port';
  v(4).name:='Hamburg Container Port';
  v(4).country:='DEU'; v(4).lat:=53.55; v(4).lon:=9.99;  v(4).crit:=88;

  v(5).slug:='gdansk-port';        v(5).ntype:='port';
  v(5).name:='Gdansk DCT Container Terminal';
  v(5).country:='POL'; v(5).lat:=54.40; v(5).lon:=18.71; v(5).crit:=72;

  v(6).slug:='kmw-muenchen';       v(6).ntype:='factory';
  v(6).name:='KMW Werk Muenchen';
  v(6).country:='DEU'; v(6).lat:=48.20; v(6).lon:=11.62; v(6).crit:=95;

  v(7).slug:='rheinmetall-unterluess'; v(7).ntype:='factory';
  v(7).name:='Rheinmetall Unterluess';
  v(7).country:='DEU'; v(7).lat:=52.83; v(7).lon:=10.32; v(7).crit:=93;

  v(8).slug:='thyssenkrupp-duisburg'; v(8).ntype:='factory';
  v(8).name:='ThyssenKrupp Duisburg Steel';
  v(8).country:='DEU'; v(8).lat:=51.43; v(8).lon:=6.76;  v(8).crit:=86;

  v(9).slug:='nexans-fr-supplier'; v(9).ntype:='supplier';
  v(9).name:='Nexans Cable Supplier Lyon';
  v(9).country:='FRA'; v(9).lat:=45.76; v(9).lon:=4.84;  v(9).crit:=68;

  v(10).slug:='hensoldt-radar';    v(10).ntype:='supplier';
  v(10).name:='Hensoldt Radar Electronics Ulm';
  v(10).country:='DEU'; v(10).lat:=48.40; v(10).lon:=9.99; v(10).crit:=82;

  v(11).slug:='diehl-defence-roethenbach'; v(11).ntype:='supplier';
  v(11).name:='Diehl Defence Roethenbach';
  v(11).country:='DEU'; v(11).lat:=49.50; v(11).lon:=11.25; v(11).crit:=75;

  v(12).slug:='kaliningrad-port';  v(12).ntype:='port';
  v(12).name:='Kaliningrad Port (Risk Watch)';
  v(12).country:='RUS'; v(12).lat:=54.71; v(12).lon:=20.51; v(12).crit:=40;

  v(13).slug:='taiwan-tsmc';       v(13).ntype:='supplier';
  v(13).name:='TSMC Hsinchu (Semiconductors)';
  v(13).country:='TWN'; v(13).lat:=24.78; v(13).lon:=120.99; v(13).crit:=99;

  FOR i IN 1 .. v.COUNT LOOP
    v_nid := slug_to_id(v(i).slug);
    MERGE INTO sc_nodes n
    USING (SELECT v_nid AS nid FROM dual) s
    ON (n.node_id = s.nid)
    WHEN MATCHED THEN UPDATE SET
      n.node_type    = v(i).ntype,
      n.display_name = v(i).name,
      n.country_iso3 = v(i).country,
      n.location     = SDO_GEOMETRY(2001, 4326,
                                    SDO_POINT_TYPE(v(i).lon, v(i).lat, NULL),
                                    NULL, NULL),
      n.criticality  = v(i).crit,
      n.ols_label    = 20
    WHEN NOT MATCHED THEN INSERT
      (node_id, tenant_id, node_type, display_name, country_iso3,
       location, criticality, ols_label)
    VALUES
      (s.nid, 'T001', v(i).ntype, v(i).name, v(i).country,
       SDO_GEOMETRY(2001, 4326,
                    SDO_POINT_TYPE(v(i).lon, v(i).lat, NULL),
                    NULL, NULL),
       v(i).crit, 20);
  END LOOP;
  COMMIT;
  SELECT COUNT(*) INTO v_count FROM sc_nodes;
  DBMS_OUTPUT.PUT_LINE('sc_nodes upserted; total = '||v_count);

  ----------------------------------------------------------------------------
  -- EDGES
  ----------------------------------------------------------------------------
  e(1).slug:='kiruna-ships-lkab';        e(1).src:='kiruna-mine';            e(1).dst:='lkab-hub';
  e(1).etype:='ships_to'; e(1).lead:=2; e(1).dep:=95;

  e(2).slug:='kiruna-ships-narvik';      e(2).src:='kiruna-mine';            e(2).dst:='narvik-port';
  e(2).etype:='ships_to'; e(2).lead:=1; e(2).dep:=80;

  e(3).slug:='lkab-ships-narvik';        e(3).src:='lkab-hub';               e(3).dst:='narvik-port';
  e(3).etype:='transports'; e(3).lead:=1; e(3).dep:=70;

  e(4).slug:='narvik-ships-hamburg';     e(4).src:='narvik-port';            e(4).dst:='hamburg-port';
  e(4).etype:='ships_to'; e(4).lead:=8; e(4).dep:=60;

  e(5).slug:='hamburg-supplies-thyssen'; e(5).src:='hamburg-port';           e(5).dst:='thyssenkrupp-duisburg';
  e(5).etype:='supplies'; e(5).lead:=2; e(5).dep:=85;

  e(6).slug:='thyssen-supplies-rheinmetall'; e(6).src:='thyssenkrupp-duisburg'; e(6).dst:='rheinmetall-unterluess';
  e(6).etype:='supplies'; e(6).lead:=4; e(6).dep:=75;

  e(7).slug:='thyssen-supplies-kmw';     e(7).src:='thyssenkrupp-duisburg';  e(7).dst:='kmw-muenchen';
  e(7).etype:='supplies'; e(7).lead:=5; e(7).dep:=70;

  e(8).slug:='nexans-supplies-rheinmetall'; e(8).src:='nexans-fr-supplier'; e(8).dst:='rheinmetall-unterluess';
  e(8).etype:='supplies'; e(8).lead:=10; e(8).dep:=55;

  e(9).slug:='hensoldt-supplies-kmw';    e(9).src:='hensoldt-radar';         e(9).dst:='kmw-muenchen';
  e(9).etype:='supplies'; e(9).lead:=14; e(9).dep:=88;

  e(10).slug:='hensoldt-supplies-rheinmetall'; e(10).src:='hensoldt-radar'; e(10).dst:='rheinmetall-unterluess';
  e(10).etype:='supplies'; e(10).lead:=14; e(10).dep:=82;

  e(11).slug:='diehl-supplies-rheinmetall'; e(11).src:='diehl-defence-roethenbach'; e(11).dst:='rheinmetall-unterluess';
  e(11).etype:='supplies'; e(11).lead:=7; e(11).dep:=78;

  e(12).slug:='gdansk-ships-thyssen';    e(12).src:='gdansk-port';           e(12).dst:='thyssenkrupp-duisburg';
  e(12).etype:='ships_to'; e(12).lead:=3; e(12).dep:=45;

  e(13).slug:='kmw-depends-tsmc';        e(13).src:='kmw-muenchen';          e(13).dst:='taiwan-tsmc';
  e(13).etype:='depends_on'; e(13).lead:=42; e(13).dep:=92;

  e(14).slug:='hensoldt-depends-tsmc';   e(14).src:='hensoldt-radar';        e(14).dst:='taiwan-tsmc';
  e(14).etype:='depends_on'; e(14).lead:=42; e(14).dep:=95;

  e(15).slug:='rheinmetall-depends-kmw'; e(15).src:='rheinmetall-unterluess'; e(15).dst:='kmw-muenchen';
  e(15).etype:='depends_on'; e(15).lead:=NULL; e(15).dep:=40;

  e(16).slug:='kaliningrad-ships-gdansk'; e(16).src:='kaliningrad-port';     e(16).dst:='gdansk-port';
  e(16).etype:='ships_to'; e(16).lead:=2; e(16).dep:=20;

  FOR i IN 1 .. e.COUNT LOOP
    v_eid := slug_to_id(e(i).slug);
    v_src := slug_to_id(e(i).src);
    v_dst := slug_to_id(e(i).dst);
    MERGE INTO sc_edges sc
    USING (SELECT v_eid AS eid FROM dual) s
    ON (sc.edge_id = s.eid)
    WHEN MATCHED THEN UPDATE SET
      sc.src_node         = v_src,
      sc.dst_node         = v_dst,
      sc.edge_type        = e(i).etype,
      sc.lead_time_days   = e(i).lead,
      sc.dependency_level = e(i).dep,
      sc.ols_label        = 20
    WHEN NOT MATCHED THEN INSERT
      (edge_id, src_node, dst_node, edge_type,
       lead_time_days, dependency_level, ols_label)
    VALUES
      (s.eid, v_src, v_dst, e(i).etype,
       e(i).lead, e(i).dep, 20);
  END LOOP;
  COMMIT;
  SELECT COUNT(*) INTO v_count FROM sc_edges;
  DBMS_OUTPUT.PUT_LINE('sc_edges upserted; total = '||v_count);

  ----------------------------------------------------------------------------
  -- RISK HISTORY: 30 days of scores per node, with a JSON breakdown.
  -- Score is roughly correlated with criticality + a deterministic noise term
  -- so the chart shows a believable trend.
  ----------------------------------------------------------------------------
  DECLARE
    v_score   NUMBER;
    v_geo     NUMBER;
    v_sanc    NUMBER;
    v_wx      NUMBER;
    v_cy      NUMBER;
    v_seed    NUMBER;
  BEGIN
    FOR i IN 1 .. v.COUNT LOOP
      v_nid := slug_to_id(v(i).slug);
      v_seed := MOD(ASCII(SUBSTR(v(i).slug, 1, 1)), 17) + i; -- per-node bias
      FOR d IN 0 .. 29 LOOP
        v_geo  := MOD(v_seed + d * 3, 50)         + GREATEST(v(i).crit - 70, 0) / 4;
        v_sanc := CASE WHEN v(i).country IN ('RUS') THEN 60 + MOD(d * 5, 30) ELSE MOD(d * 7 + v_seed, 25) END;
        v_wx   := MOD(d * 11 + v_seed, 30);
        v_cy   := MOD(d * 13 + v_seed * 2, 35);
        v_score := LEAST(99, GREATEST(5, ROUND(0.4*v_geo + 0.3*v_sanc + 0.15*v_wx + 0.15*v_cy)));

        MERGE INTO sc_risk r
        USING (SELECT v_nid AS nid, TRUNC(SYSDATE) - (29 - d) AS asof FROM dual) s
        ON (r.node_id = s.nid AND r.as_of = s.asof)
        WHEN MATCHED THEN UPDATE SET
          r.risk_score     = v_score,
          r.risk_breakdown = '{"geopolitical":'||v_geo||',"sanctions":'||v_sanc||
                             ',"weather":'||v_wx||',"cyber":'||v_cy||'}',
          r.ols_label      = 20
        WHEN NOT MATCHED THEN INSERT
          (node_id, as_of, risk_score, risk_breakdown, ols_label)
        VALUES
          (s.nid, s.asof, v_score,
           '{"geopolitical":'||v_geo||',"sanctions":'||v_sanc||
           ',"weather":'||v_wx||',"cyber":'||v_cy||'}',
           20);
      END LOOP;
    END LOOP;
    COMMIT;
  END;

  SELECT COUNT(*) INTO v_count FROM sc_risk;
  DBMS_OUTPUT.PUT_LINE('sc_risk upserted; total rows = '||v_count);
END;
/

-- Tail-sanity
DECLARE
  v_n NUMBER; v_e NUMBER; v_r NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_n FROM sc_nodes WHERE tenant_id='T001';
  SELECT COUNT(*) INTO v_e FROM sc_edges;
  SELECT COUNT(*) INTO v_r FROM sc_risk;
  IF v_n < 13 OR v_e < 16 OR v_r < 13*30 THEN
    RAISE_APPLICATION_ERROR(-20010,
      '04_supply_chain_seed.sql: expected at least 13 nodes / 16 edges / 390 risk-rows, '||
      'got n='||v_n||' e='||v_e||' r='||v_r);
  END IF;
  DBMS_OUTPUT.PUT_LINE(
    '04_supply_chain_seed.sql OK: nodes='||v_n||' edges='||v_e||' risk='||v_r);
END;
/
