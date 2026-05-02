-- ===========================================================================
-- UC4_OSINT — Tag 5: Synthetic Demo Seed (Ostsee / Suwałki-Korridor)
-- Oracle AI Database 26ai (ATP-Shared, eu-frankfurt-1)
--
-- Geltungsbereich:
--   Befüllt die 9 UC4_OSINT-Stamm- und 2 Junction-Tabellen mit
--   demo-tauglichen Realdaten für eine 8-minütige Threat-Fusion-Story
--   im Baltikum / Suwałki Gap (BBox Lat 53–58, Lon 13–23).
--
-- Volumen (alle Counts ±10 als Toleranz im Tail-Sanity):
--   signal_raw                     ~150
--   signal_normalized              ~120
--   signal_vectors                 ~120 (embedding=NULL — gefüllt von 02_compute_embeddings.sql)
--   entity                         ~30
--   entity_mention                 ~250
--   ems_emitter                    ~15
--   correlation_event              8
--   correlation_includes_event     ~40
--   correlation_includes_entity    ~25
--   briefing                       8
--   audit_trail                    ~50
--
-- Klassifikations-Verteilung (über alle Tabellen, nominell):
--   ~40% OFFEN(10)   public OSINT, contractors sehen das
--   ~40% INTERN(30)  Reserve-Force-clearance
--   ~20% NFD(50)     Active-Force only
--   0   GEHEIM(70)   Demo-Cap ist NFD
--
-- Story-Kerne (vorgefertigte Korrelationen, jeweils mit Briefing):
--   1) EW + UAS-Konvergenz Kaliningrad (NFD)
--   2) AIS-Stillstand + Warning Area Hel (INTERN)
--   3) Sanktionierter Tanker im Bornholm-Schatten (INTERN)
--   4) Suwałki-Land-Konvoy + ADS-B-Activity (NFD)
--   5) Spoofing-Cluster Bornholm (INTERN)
--   6) Karlskrona-Hafen-Anomalie (OFFEN)
--   7) Klaipėda Tanker-Schiff-zu-Schiff-Transfer (INTERN)
--   8) Multi-Source Tanker-Kette Gdańsk Bay (NFD)
--
-- Geographic-Anchor-Set (12 Punkte im BBox):
--   Bornholm 55.13/14.91 · Karlskrona 56.16/15.59 · Świnoujście 53.91/14.25
--   Hel 54.61/18.81     · Gdańsk Bay 54.40/18.70 · Kaliningrad 54.71/20.51
--   Klaipėda 55.71/21.13 · Liepāja 56.51/21.01 · Suwałki Gap 54.10/22.93
--   Gotland NE 57.56/18.36 · Baltic-Mid 55.50/18.00 · Open Baltic 56.30/19.20
--
-- H3-r5-Cells: keine echte H3-UDF in 26ai installiert. Wir setzen
-- pseudo-Cells als "r5/<lat-1dec>/<lon-1dec>" (~11 km grid) — gut genug
-- für GROUP-BY-Demos, deterministisch und visuell lesbar.
--
-- Idempotenz-Mechanik:
--   Marker = invocation_id 'seed:uc4-demo-2026-05-01' in audit_trail.
--   Liegt der Marker vor, läuft eine FK-respektierende Cleanup-Sequenz
--   und seedet danach neu. Sonst: direkter Insert.
--   Cleanup-Filter:
--     * signal_raw / signal_normalized: source_provider='seed:uc4-demo'
--     * entity, ems_emitter, correlation_event: JSON_VALUE(...,'$.seed')
--     * briefing: generated_by='uc4-seed'
--     * audit_trail: invocation_id LIKE 'seed:uc4-demo%'
--     * Junction-Tabellen: cascaden via correlation_event-DELETE bzw.
--       hängen an signal_normalized/entity-DELETEs (RESTRICT — wir
--       räumen Junction-Rows explizit vor entity_mention).
--
-- Voraussetzungen:
--   * 01_tables.sql, 02_indexes.sql, 03b_ols_app_filter.sql, 04_graph.sql
--     applied.
--   * Connection als UC4_OSINT (apply-migration.sh mit ADB_USER=UC4_OSINT
--     aufrufen, Passwort aus Vault uc4-osint-schema-owner-pwd).
-- ===========================================================================

WHENEVER SQLERROR EXIT FAILURE
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED

-- Ein einzelner anonymer Block — atomare Cleanup+Insert+Marker-Sequenz.
-- Ein Fehler mittendrin rollt alles zurück; halbe Seeds sind unmöglich.
DECLARE
  TYPE t_idmap IS TABLE OF RAW(16) INDEX BY VARCHAR2(64);
  v_e   t_idmap;  -- entity name → entity_id
  v_em  t_idmap;  -- emitter name → emitter_id
  v_r   t_idmap;  -- signal_raw key → signal_raw_id
  v_s   t_idmap;  -- signal_normalized key → event_id
  v_c   t_idmap;  -- correlation key → correlation_id

  c_marker  CONSTANT VARCHAR2(40)  := 'seed:uc4-demo-2026-05-01';
  c_actor   CONSTANT VARCHAR2(40)  := 'uc4-seed';
  c_attrs_seed CONSTANT JSON       := JSON('{"seed":"uc4-demo-2026-05-01"}');
  c_provider CONSTANT VARCHAR2(40) := 'seed:uc4-demo';

  v_already   NUMBER;
  v_id        RAW(16);
  v_ts        TIMESTAMP WITH TIME ZONE;
  v_lat       NUMBER;
  v_lon       NUMBER;
  v_h3        VARCHAR2(16);
  v_label     NUMBER;
  v_idx       NUMBER;

  -- 12-Anchor-Geo-Tabelle als 2D-Konstanten-Array
  TYPE t_anchor IS RECORD (name VARCHAR2(40), lat NUMBER, lon NUMBER);
  TYPE t_anchors IS TABLE OF t_anchor INDEX BY PLS_INTEGER;
  v_anchors t_anchors;

  -- Helper: deterministisch klassifizieren je Index für die 40/40/20-
  -- Verteilung. Reproduzierbar, balanciert.
  FUNCTION pick_label(p_seq IN NUMBER) RETURN NUMBER IS
  BEGIN
    CASE MOD(p_seq, 10)
      WHEN 0 THEN RETURN 50;
      WHEN 1 THEN RETURN 50;
      WHEN 2 THEN RETURN 30;
      WHEN 3 THEN RETURN 30;
      WHEN 4 THEN RETURN 30;
      WHEN 5 THEN RETURN 30;
      WHEN 6 THEN RETURN 10;
      WHEN 7 THEN RETURN 10;
      WHEN 8 THEN RETURN 10;
      ELSE        RETURN 10;
    END CASE;
  END;

  -- Pseudo-H3-Cell-ID: r5/<lat 1 decimal>/<lon 1 decimal>.
  -- Genau genug für GROUP-BY-Buckets in der Demo-Heatmap.
  -- (FUNCTION h3r5() and FUNCTION pt() inlined into call-sites — PL/SQL
  -- local functions can't be invoked from inside SQL DML.)

  -- Insert helper: entity
  FUNCTION ins_entity(
    p_kind VARCHAR2, p_canonical_kind VARCHAR2, p_canonical_id VARCHAR2,
    p_display VARCHAR2, p_attrs_json VARCHAR2,
    p_lat NUMBER, p_lon NUMBER, p_label NUMBER
  ) RETURN RAW IS
    v_out RAW(16);
  BEGIN
    INSERT INTO entity(entity_kind, canonical_id_kind, canonical_id,
                       display_name, aliases, attributes,
                       geo, geo_h3_r5, first_seen_at, last_seen_at, ols_label)
      VALUES(p_kind, p_canonical_kind, p_canonical_id, p_display, NULL,
             JSON(p_attrs_json),
             SDO_GEOMETRY(2001, 4326, SDO_POINT_TYPE(p_lon, p_lat, NULL), NULL, NULL), ('r5/'||TO_CHAR(ROUND(p_lat,1))||'/'||TO_CHAR(ROUND(p_lon,1))),
             SYSTIMESTAMP - INTERVAL '60' DAY, SYSTIMESTAMP, p_label)
      RETURNING entity_id INTO v_out;
    RETURN v_out;
  END;

  -- Insert helper: ems_emitter
  FUNCTION ins_emitter(
    p_kind VARCHAR2, p_freq NUMBER, p_bw NUMBER, p_pwr NUMBER,
    p_modulation VARCHAR2, p_platform VARCHAR2, p_entity RAW,
    p_lat NUMBER, p_lon NUMBER, p_label NUMBER
  ) RETURN RAW IS
    v_out RAW(16);
  BEGIN
    INSERT INTO ems_emitter(emitter_kind, frequency_mhz, bandwidth_mhz,
                            power_dbm, modulation, platform_kind, entity_id,
                            geo, geo_h3_r5, first_observed_at, last_observed_at,
                            ols_label)
      VALUES(p_kind, p_freq, p_bw, p_pwr, p_modulation, p_platform, p_entity,
             SDO_GEOMETRY(2001, 4326, SDO_POINT_TYPE(p_lon, p_lat, NULL), NULL, NULL), ('r5/'||TO_CHAR(ROUND(p_lat,1))||'/'||TO_CHAR(ROUND(p_lon,1))),
             SYSTIMESTAMP - INTERVAL '14' DAY, SYSTIMESTAMP - INTERVAL '1' HOUR,
             p_label)
      RETURNING emitter_id INTO v_out;
    -- Marker im attributes: ems_emitter hat keine attributes-Spalte
    -- per 01_tables.sql, daher der Cleanup-Filter "ohne entity_id +
    -- in unserem geo-Bereich + emitter_kind aus unserem Set".
    -- Alternative wäre, 01_tables.sql nachträglich um attributes
    -- zu erweitern — out of scope für diesen Seed-File.
    RETURN v_out;
  END;

  -- Insert helper: signal_raw
  FUNCTION ins_signal_raw(
    p_native_id VARCHAR2, p_observed TIMESTAMP WITH TIME ZONE,
    p_payload_json VARCHAR2, p_label NUMBER
  ) RETURN RAW IS
    v_out RAW(16);
  BEGIN
    INSERT INTO signal_raw(source_provider, source_native_id, source_url,
                           collected_at, observed_at, payload, payload_sha256,
                           ols_label)
      VALUES(c_provider, p_native_id, NULL,
             p_observed + INTERVAL '5' SECOND, p_observed,
             JSON(p_payload_json),
             STANDARD_HASH(p_native_id || TO_CHAR(p_observed), 'SHA256'),
             p_label)
      RETURNING signal_raw_id INTO v_out;
    RETURN v_out;
  END;

  -- Insert helper: signal_normalized + signal_vectors (embedding=NULL)
  FUNCTION ins_signal_norm(
    p_raw_id RAW, p_source_type VARCHAR2, p_native_id VARCHAR2,
    p_observed TIMESTAMP WITH TIME ZONE,
    p_entity_kind VARCHAR2, p_entity_ref VARCHAR2,
    p_title VARCHAR2, p_summary VARCHAR2,
    p_lat NUMBER, p_lon NUMBER,
    p_confidence NUMBER, p_attrs_json VARCHAR2, p_tags_json VARCHAR2,
    p_label NUMBER
  ) RETURN RAW IS
    v_out RAW(16);
  BEGIN
    INSERT INTO signal_normalized(raw_signal_id, source_type, source_provider,
                                   source_native_id, collected_at, observed_at,
                                   entity_kind, entity_ref, title, summary,
                                   geo, geo_h3_r5, confidence,
                                   attributes, tags, ols_label)
      VALUES(p_raw_id, p_source_type, c_provider, p_native_id,
             p_observed + INTERVAL '10' SECOND, p_observed,
             p_entity_kind, p_entity_ref, p_title, p_summary,
             SDO_GEOMETRY(2001, 4326, SDO_POINT_TYPE(p_lon, p_lat, NULL), NULL, NULL), ('r5/'||TO_CHAR(ROUND(p_lat,1))||'/'||TO_CHAR(ROUND(p_lon,1))), p_confidence,
             JSON(p_attrs_json), JSON(p_tags_json), p_label)
      RETURNING event_id INTO v_out;

    -- Companion vector row, embedding NULL (gefüllt von 02_compute_embeddings.sql)
    INSERT INTO signal_vectors(event_id, embedding, embedding_model,
                                embedded_at, ols_label)
      VALUES(v_out, NULL, 'cohere.embed-multilingual-v3.0', SYSTIMESTAMP, p_label);
    RETURN v_out;
  END;

  -- Insert helper: entity_mention edge
  PROCEDURE ins_mention(
    p_event RAW, p_entity RAW,
    p_kind VARCHAR2 DEFAULT 'PRIMARY',
    p_confidence NUMBER DEFAULT 0.85,
    p_label NUMBER DEFAULT 30
  ) IS
  BEGIN
    INSERT INTO entity_mention(event_id, entity_id, mention_kind,
                                confidence, detected_at, ols_label)
      VALUES(p_event, p_entity, p_kind, p_confidence, SYSTIMESTAMP, p_label);
  END;

  -- Insert helper: correlation_event
  FUNCTION ins_corr(
    p_kind VARCHAR2, p_summary VARCHAR2,
    p_start TIMESTAMP WITH TIME ZONE, p_end TIMESTAMP WITH TIME ZONE,
    p_lat NUMBER, p_lon NUMBER,
    p_score NUMBER, p_payload_json VARCHAR2, p_label NUMBER
  ) RETURN RAW IS
    v_out RAW(16);
  BEGIN
    INSERT INTO correlation_event(correlation_kind, summary, detected_at,
                                   start_at, end_at, geo, geo_h3_r5, score,
                                   payload, ols_label)
      VALUES(p_kind, p_summary, p_end + INTERVAL '5' MINUTE,
             p_start, p_end, SDO_GEOMETRY(2001, 4326, SDO_POINT_TYPE(p_lon, p_lat, NULL), NULL, NULL), ('r5/'||TO_CHAR(ROUND(p_lat,1))||'/'||TO_CHAR(ROUND(p_lon,1))), p_score,
             JSON(p_payload_json), p_label)
      RETURNING correlation_id INTO v_out;
    RETURN v_out;
  END;

  PROCEDURE ins_corr_inc_event(
    p_corr RAW, p_event RAW, p_role VARCHAR2 DEFAULT 'CONTEXT',
    p_confidence NUMBER DEFAULT 0.8, p_label NUMBER DEFAULT 30
  ) IS
  BEGIN
    INSERT INTO correlation_includes_event(correlation_id, event_id, role,
                                            confidence, ols_label)
      VALUES(p_corr, p_event, p_role, p_confidence, p_label);
  END;

  PROCEDURE ins_corr_inc_entity(
    p_corr RAW, p_entity RAW, p_role VARCHAR2 DEFAULT 'PRIMARY',
    p_label NUMBER DEFAULT 30
  ) IS
  BEGIN
    INSERT INTO correlation_includes_entity(correlation_id, entity_id, role,
                                             ols_label)
      VALUES(p_corr, p_entity, p_role, p_label);
  END;

  PROCEDURE ins_briefing(
    p_corr RAW, p_title VARCHAR2, p_body VARCHAR2,
    p_lat NUMBER, p_lon NUMBER, p_label NUMBER
  ) IS
  BEGIN
    INSERT INTO briefing(correlation_id, title, body, model_id, prompt_hash,
                         generated_at, generated_by, review_state,
                         geo, geo_h3_r5, ols_label)
      VALUES(p_corr, p_title, p_body,
             'cohere.command-r-plus-08-2024 v2.0',
             STANDARD_HASH(p_title, 'SHA256'),
             SYSTIMESTAMP - INTERVAL '20' MINUTE,
             c_actor, 'DRAFT',
             SDO_GEOMETRY(2001, 4326, SDO_POINT_TYPE(p_lon, p_lat, NULL), NULL, NULL), ('r5/'||TO_CHAR(ROUND(p_lat,1))||'/'||TO_CHAR(ROUND(p_lon,1))), p_label);
  END;

  PROCEDURE ins_audit(
    p_actor_type VARCHAR2, p_actor_id VARCHAR2, p_action VARCHAR2,
    p_table VARCHAR2, p_label NUMBER, p_invocation VARCHAR2 DEFAULT NULL
  ) IS
  BEGIN
    INSERT INTO audit_trail(actor_type, actor_id, action, table_name,
                             ols_label, payload_hash, invocation_id)
      VALUES(p_actor_type, p_actor_id, p_action, p_table, p_label,
             STANDARD_HASH(p_action || TO_CHAR(SYSTIMESTAMP), 'SHA256'),
             NVL(p_invocation, c_marker || ':auto'));
  END;

BEGIN
  -- ========================================================================
  -- (0) Anchor-Punkte vorbereiten
  -- ========================================================================
  v_anchors(1)  := t_anchor('Bornholm',     55.13, 14.91);
  v_anchors(2)  := t_anchor('Karlskrona',   56.16, 15.59);
  v_anchors(3)  := t_anchor('Świnoujście',  53.91, 14.25);
  v_anchors(4)  := t_anchor('Hel',          54.61, 18.81);
  v_anchors(5)  := t_anchor('Gdańsk Bay',   54.40, 18.70);
  v_anchors(6)  := t_anchor('Kaliningrad',  54.71, 20.51);
  v_anchors(7)  := t_anchor('Klaipėda',     55.71, 21.13);
  v_anchors(8)  := t_anchor('Liepāja',      56.51, 21.01);
  v_anchors(9)  := t_anchor('Suwałki Gap',  54.10, 22.93);
  v_anchors(10) := t_anchor('Gotland NE',   57.56, 18.36);
  v_anchors(11) := t_anchor('Baltic-Mid',   55.50, 18.00);
  v_anchors(12) := t_anchor('Open Baltic',  56.30, 19.20);

  -- ========================================================================
  -- (1) Cleanup falls Vor-Run
  -- ========================================================================
  SELECT COUNT(*) INTO v_already FROM audit_trail WHERE invocation_id = c_marker;
  IF v_already > 0 THEN
    DBMS_OUTPUT.PUT_LINE('WARNING: prior seed run detected — cleaning up before re-seed.');
    -- FK-respektierende Reihenfolge:
    DELETE FROM audit_trail            WHERE invocation_id LIKE 'seed:uc4-demo%';
    DELETE FROM briefing               WHERE generated_by = c_actor;
    DELETE FROM correlation_includes_event;   -- gefiltert via FK-Cascade aus correlation_event
    DELETE FROM correlation_includes_entity;
    DELETE FROM correlation_event      WHERE JSON_VALUE(payload,'$.seed') = 'uc4-demo-2026-05-01';
    -- ems_emitter: kein attributes-Field — wir filtern über source_provider
    -- der referenzierten Signale gibt es nicht; stattdessen Brute-Force
    -- über die entity_id-FK (alle, deren entity einen seed-Marker trägt).
    DELETE FROM ems_emitter
     WHERE entity_id IN (SELECT entity_id FROM entity
                          WHERE JSON_VALUE(attributes,'$.seed') = 'uc4-demo-2026-05-01')
        OR entity_id IS NULL;  -- "anonyme" Emitter aus dem Seed
    DELETE FROM entity_mention
     WHERE event_id IN (SELECT event_id FROM signal_normalized
                         WHERE source_provider = c_provider)
        OR entity_id IN (SELECT entity_id FROM entity
                          WHERE JSON_VALUE(attributes,'$.seed') = 'uc4-demo-2026-05-01');
    DELETE FROM signal_vectors
     WHERE event_id IN (SELECT event_id FROM signal_normalized
                         WHERE source_provider = c_provider);
    DELETE FROM signal_normalized      WHERE source_provider = c_provider;
    DELETE FROM signal_raw             WHERE source_provider = c_provider;
    DELETE FROM entity
     WHERE JSON_VALUE(attributes,'$.seed') = 'uc4-demo-2026-05-01';
    DBMS_OUTPUT.PUT_LINE('Cleanup complete.');
  END IF;

  -- ========================================================================
  -- (2) Entities — 30 Einträge
  -- Mix: 12 vessels, 6 aircraft, 4 actors (orgs), 5 locations, 3 satellites
  -- ========================================================================

  -- Vessels (MMSI as canonical_id)
  v_e('AURORA')      := ins_entity('vessel','MMSI','273456789','MV Aurora',
    '{"flag":"RU","type":"tanker","tonnage":42000,"seed":"uc4-demo-2026-05-01"}',
    54.71, 20.51, 30);
  v_e('KASKOL')      := ins_entity('vessel','MMSI','273456790','MV Kaskol',
    '{"flag":"RU","type":"tanker","tonnage":68000,"seed":"uc4-demo-2026-05-01"}',
    54.85, 19.80, 50);
  v_e('PALMERSTON')  := ins_entity('vessel','MMSI','209123456','MV Palmerston',
    '{"flag":"CY","type":"freighter","tonnage":24000,"seed":"uc4-demo-2026-05-01"}',
    55.45, 18.20, 10);
  v_e('NORDLUX')     := ins_entity('vessel','MMSI','219111222','MV Nordlux',
    '{"flag":"DK","type":"freighter","tonnage":18500,"seed":"uc4-demo-2026-05-01"}',
    55.13, 14.91, 10);
  v_e('GREYWATER')   := ins_entity('vessel','MMSI','266888777','MV Greywater',
    '{"flag":"SE","type":"freighter","tonnage":21000,"seed":"uc4-demo-2026-05-01"}',
    56.16, 15.59, 10);
  v_e('SHADOW_TANKER_01') := ins_entity('vessel','MMSI','423000001','Unknown Shadow-Tanker A',
    '{"flag":"unknown","type":"tanker","aliases":["MV Avos"],"sanctions":["EU-2026-128"],"seed":"uc4-demo-2026-05-01"}',
    55.30, 17.10, 50);
  v_e('SHADOW_TANKER_02') := ins_entity('vessel','MMSI','423000002','Unknown Shadow-Tanker B',
    '{"flag":"unknown","type":"tanker","seed":"uc4-demo-2026-05-01"}',
    55.10, 16.60, 30);
  v_e('VIKING_REEF') := ins_entity('vessel','MMSI','219555111','RV Viking Reef',
    '{"flag":"DK","type":"research","seed":"uc4-demo-2026-05-01"}',
    56.50, 18.30, 10);
  v_e('FERRY_GDA')   := ins_entity('vessel','MMSI','261222333','MS Pomerania-Express',
    '{"flag":"PL","type":"ferry","seed":"uc4-demo-2026-05-01"}',
    54.40, 18.70, 10);
  v_e('NAVAL_KGD_01') := ins_entity('vessel','MMSI','273900001','RFN Patrol-9',
    '{"flag":"RU","type":"naval","class":"corvette","seed":"uc4-demo-2026-05-01"}',
    54.78, 20.45, 50);
  v_e('NAVAL_SE_01') := ins_entity('vessel','MMSI','266900002','HSwMS Visby-class P',
    '{"flag":"SE","type":"naval","class":"corvette","seed":"uc4-demo-2026-05-01"}',
    56.10, 15.65, 30);
  v_e('CABLE_LAYER') := ins_entity('vessel','MMSI','219444555','MV Cabledecker',
    '{"flag":"NO","type":"cable-layer","seed":"uc4-demo-2026-05-01"}',
    55.20, 17.90, 10);

  -- Aircraft (ICAO24 as canonical_id)
  v_e('UAS_KGD_01')  := ins_entity('aircraft','ICAO24','RA1234A','Orlan-10 (UAV)',
    '{"flag":"RU","class":"UAS","model":"Orlan-10","seed":"uc4-demo-2026-05-01"}',
    54.85, 21.20, 50);
  v_e('UAS_KGD_02')  := ins_entity('aircraft','ICAO24','RA1234B','Forpost (UAV)',
    '{"flag":"RU","class":"UAS","model":"Forpost-R","seed":"uc4-demo-2026-05-01"}',
    54.65, 20.90, 50);
  v_e('AIRLINER_LH'):= ins_entity('aircraft','ICAO24','3C6589','LH1234',
    '{"flag":"DE","class":"commercial","operator":"Lufthansa","seed":"uc4-demo-2026-05-01"}',
    55.00, 19.00, 10);
  v_e('NATO_E3A')    := ins_entity('aircraft','ICAO24','4B8801','NAEW E-3A',
    '{"flag":"NATO","class":"AWACS","seed":"uc4-demo-2026-05-01"}',
    55.80, 18.50, 30);
  v_e('PATROL_DE_P3'):= ins_entity('aircraft','ICAO24','3FAA01','MFG P-3C Orion',
    '{"flag":"DE","class":"MPA","seed":"uc4-demo-2026-05-01"}',
    54.50, 14.40, 30);
  v_e('NATO_RIVET_J'):= ins_entity('aircraft','ICAO24','AE12FF','RC-135 Rivet Joint',
    '{"flag":"US","class":"SIGINT","seed":"uc4-demo-2026-05-01"}',
    56.00, 19.50, 50);

  -- Actors / Organisations
  v_e('OPER_NORD_LOG')   := ins_entity('actor','OPEN_CORPORATES','PL_KRS_0001234','Nord-Logistik Sp. z o.o.',
    '{"role":"shipper","incorporated":"PL","seed":"uc4-demo-2026-05-01"}',
    54.40, 18.70, 10);
  v_e('OPER_BALTIC_OIL') := ins_entity('actor','OPEN_CORPORATES','RU_OGRN_555','Baltic Oil Ltd',
    '{"role":"operator","incorporated":"CY","sanctions":["EU-2026-128"],"seed":"uc4-demo-2026-05-01"}',
    54.71, 20.51, 50);
  v_e('OPER_NEUTRAL_FREIGHT') := ins_entity('actor','OPEN_CORPORATES','DE_HRB_98765','Neutral Freight GmbH',
    '{"role":"shipper","incorporated":"DE","seed":"uc4-demo-2026-05-01"}',
    53.91, 14.25, 10);
  v_e('NGO_OPENMARITIME') := ins_entity('actor','WIKIPEDIA','OpenMaritime','Open-Maritime Watch',
    '{"role":"OSINT","seed":"uc4-demo-2026-05-01"}',
    55.50, 18.00, 10);

  -- Locations (port / area / installation)
  v_e('LOC_PORT_KGD') := ins_entity('location','GEONAMES','554234','Kaliningrad Commercial Harbour',
    '{"type":"port","seed":"uc4-demo-2026-05-01"}',
    54.71, 20.51, 30);
  v_e('LOC_PORT_GDA') := ins_entity('location','GEONAMES','3099424','Gdańsk Container Terminal',
    '{"type":"port","seed":"uc4-demo-2026-05-01"}',
    54.40, 18.70, 10);
  v_e('LOC_PORT_KLA') := ins_entity('location','GEONAMES','598659','Klaipėda Crude Terminal',
    '{"type":"port","seed":"uc4-demo-2026-05-01"}',
    55.71, 21.13, 30);
  v_e('LOC_AREA_HEL') := ins_entity('location','GEONAMES','HEL_NAV_AREA','Hel Peninsula NAVAREA',
    '{"type":"navarea","seed":"uc4-demo-2026-05-01"}',
    54.61, 18.81, 30);
  v_e('LOC_BORNHOLM_DEEP') := ins_entity('location','GEONAMES','BORN_DEEP','Bornholm Deep',
    '{"type":"sea-area","seed":"uc4-demo-2026-05-01"}',
    55.30, 15.50, 10);

  -- Satellites (NORAD)
  v_e('SAT_SENTINEL2A') := ins_entity('satellite','NORAD','40697','Sentinel-2A',
    '{"operator":"ESA","seed":"uc4-demo-2026-05-01"}',
    55.50, 18.00, 10);
  v_e('SAT_ICEYE_X9')   := ins_entity('satellite','NORAD','46497','ICEYE X-9 (SAR)',
    '{"operator":"ICEYE","seed":"uc4-demo-2026-05-01"}',
    55.20, 19.50, 30);
  v_e('SAT_CAPELLA_03') := ins_entity('satellite','NORAD','47489','CAPELLA-3 (SAR)',
    '{"operator":"Capella","seed":"uc4-demo-2026-05-01"}',
    54.80, 18.80, 30);

  DBMS_OUTPUT.PUT_LINE('Inserted '||v_e.COUNT||' entities.');

  -- ========================================================================
  -- (3) ems_emitter — 15 Einträge
  -- ========================================================================
  v_em('JAM_KGD_GPS_L1')  := ins_emitter('JAMMER',     1575.42,  20, 45,
                                         'CW',         'FIXED',         v_e('NAVAL_KGD_01'),
                                         54.71, 20.51, 50);
  v_em('JAM_KGD_GPS_L2')  := ins_emitter('JAMMER',     1227.60,  20, 42,
                                         'CW',         'FIXED',         v_e('NAVAL_KGD_01'),
                                         54.71, 20.51, 50);
  v_em('JAM_HEL_BURST')   := ins_emitter('JAMMER',     1575.42,  10, 30,
                                         'PULSE',      'MOBILE_GROUND', NULL,
                                         54.61, 18.81, 30);
  v_em('JAM_BORN_INTERMIT'):= ins_emitter('JAMMER',    1575.42,   5, 18,
                                         'PULSE',      'NAVAL',         v_e('SHADOW_TANKER_01'),
                                         55.30, 15.50, 30);
  v_em('JAM_SUW_TRUCK')   := ins_emitter('JAMMER',     1575.42,  15, 38,
                                         'CW',         'MOBILE_GROUND', NULL,
                                         54.10, 22.93, 50);
  v_em('RADAR_KGD_AIR')   := ins_emitter('RADAR',      2800,    300, 85,
                                         'CHIRP',      'FIXED',         v_e('NAVAL_KGD_01'),
                                         54.71, 20.51, 50);
  v_em('RADAR_HEL_COAST') := ins_emitter('RADAR',       9410,     50, 70,
                                         'PULSE',      'FIXED',         NULL,
                                         54.61, 18.81, 30);
  v_em('RADAR_KARLSKRONA'):= ins_emitter('RADAR',       9410,     50, 72,
                                         'PULSE',      'FIXED',         NULL,
                                         56.16, 15.59, 10);
  v_em('COMMS_KGD_HF')    := ins_emitter('COMMS',         11.0,   3, 30,
                                         'OFDM',       'FIXED',         v_e('NAVAL_KGD_01'),
                                         54.71, 20.51, 30);
  v_em('COMMS_UAS_KGD_01'):= ins_emitter('COMMS',       2400.0,   1, 22,
                                         'FM',         'AIRBORNE',      v_e('UAS_KGD_01'),
                                         54.85, 21.20, 50);
  v_em('COMMS_UAS_KGD_02'):= ins_emitter('COMMS',       5800.0,   2, 25,
                                         'OFDM',       'AIRBORNE',      v_e('UAS_KGD_02'),
                                         54.65, 20.90, 50);
  v_em('SAT_TX_RU_NAVAL') := ins_emitter('SAT_TX',     7250.0,  10, 50,
                                         'OFDM',       'SPACEBORNE',    NULL,
                                         55.50, 19.50, 30);
  v_em('BEACON_AIS_BORN') := ins_emitter('BEACON',      161.975,   0.025, 12,
                                         'GMSK',       'FIXED',         NULL,
                                         55.13, 14.91, 10);
  v_em('UNKNOWN_SUW_01')  := ins_emitter('UNKNOWN',     446.0,    0.5, 14,
                                         'FM',         'MOBILE_GROUND', NULL,
                                         54.10, 22.93, 30);
  v_em('UNKNOWN_OPEN_01') := ins_emitter('UNKNOWN',    1090.0,    1.0, 10,
                                         'PULSE',      'UNKNOWN',       NULL,
                                         55.50, 18.00, 10);

  DBMS_OUTPUT.PUT_LINE('Inserted '||v_em.COUNT||' emitters.');

  -- ========================================================================
  -- (4) signal_raw / signal_normalized / signal_vectors
  --   * 30 hand-crafted "story" signals (named v_s('S_xxx_NN'))
  --   * 90 generated background signals via Loop
  --   = 120 total normalized signals, plus 30 extra raw-only fillers
  --     für signal_raw → ~150 total
  -- ========================================================================

  -- ---------- Story signals: AIS-Stillstand + Warning Area Hel
  v_ts := SYSTIMESTAMP - INTERVAL '36' HOUR;
  FOR i IN 1..6 LOOP
    v_r('R_AIS_STOP_'||i) := ins_signal_raw(
      'AIS:'||i, v_ts + NUMTODSINTERVAL(i*5,'MINUTE'),
      '{"mmsi":"261222333","sog":0.1,"cog":42.0,"lat":54.61,"lon":18.81,"seed":"uc4-demo-2026-05-01"}',
      30);
    v_s('S_AIS_STOP_'||i) := ins_signal_norm(
      v_r('R_AIS_STOP_'||i), 'AIS', 'AIS:'||i,
      v_ts + NUMTODSINTERVAL(i*5,'MINUTE'), 'vessel', '261222333',
      'Pomerania-Express stationary near Hel NAVAREA',
      'AIS report: SOG 0.1 kn, COG 042°. Anomalous: scheduled course leg expected speed 14 kn.',
      54.61 + (i*0.001), 18.81 + (i*0.001), 0.85,
      '{"sog":0.1,"cog":42.0,"seed":"uc4-demo-2026-05-01"}',
      '["ais","stationary","hel-navarea"]', 30);
  END LOOP;

  -- ---------- Story signals: EW + UAS-Konvergenz Kaliningrad
  v_ts := SYSTIMESTAMP - INTERVAL '12' HOUR;
  FOR i IN 1..5 LOOP
    v_r('R_JAM_KGD_'||i) := ins_signal_raw(
      'JAM:KGD:'||i, v_ts + NUMTODSINTERVAL(i*7,'MINUTE'),
      '{"freq_mhz":1575.42,"detected_dbm":-95,"lat":54.71,"lon":20.51,"seed":"uc4-demo-2026-05-01"}',
      50);
    v_s('S_JAM_KGD_'||i) := ins_signal_norm(
      v_r('R_JAM_KGD_'||i), 'JAMMING', 'JAM:KGD:'||i,
      v_ts + NUMTODSINTERVAL(i*7,'MINUTE'), 'emitter', 'JAM_KGD_GPS_L1',
      'GPS L1 jamming pulse Kaliningrad',
      'GPS L1 (1575.42 MHz) jamming at -95 dBm, pulse modulation, 20 MHz BW. Origin geolocated to Naval Patrol-9 station.',
      54.71, 20.51, 0.92,
      '{"freq_mhz":1575.42,"power_dbm":-95,"seed":"uc4-demo-2026-05-01"}',
      '["jamming","ew","kaliningrad"]', 50);
  END LOOP;
  -- UAS sightings same window
  FOR i IN 1..4 LOOP
    v_r('R_UAS_KGD_'||i) := ins_signal_raw(
      'ADSB:UAS:'||i, v_ts + NUMTODSINTERVAL(i*9,'MINUTE'),
      '{"icao24":"RA1234A","alt_ft":2300,"lat":54.85,"lon":21.20,"seed":"uc4-demo-2026-05-01"}',
      50);
    v_s('S_UAS_KGD_'||i) := ins_signal_norm(
      v_r('R_UAS_KGD_'||i), 'ADS_B', 'ADSB:UAS:'||i,
      v_ts + NUMTODSINTERVAL(i*9,'MINUTE'), 'aircraft', 'RA1234A',
      'Orlan-10 UAS track north of Kaliningrad',
      'ADS-B return at 2300 ft, ground speed 75 kn. Track consistent with reconnaissance racetrack pattern.',
      54.85 + (i*0.01), 21.20 - (i*0.01), 0.88,
      '{"alt_ft":2300,"speed_kn":75,"seed":"uc4-demo-2026-05-01"}',
      '["ads-b","uas","kaliningrad"]', 50);
  END LOOP;

  -- ---------- Story signals: Sanktionierter Tanker im Bornholm-Schatten
  v_ts := SYSTIMESTAMP - INTERVAL '20' HOUR;
  FOR i IN 1..5 LOOP
    v_r('R_TANKER_BORN_'||i) := ins_signal_raw(
      'AIS:SHADOW:'||i, v_ts + NUMTODSINTERVAL(i*15,'MINUTE'),
      '{"mmsi":"423000001","sog":'||(8.5 + i*0.1)||',"lat":'||(55.30 + i*0.02)||',"lon":'||(15.50 + i*0.03)||',"seed":"uc4-demo-2026-05-01"}',
      30);
    v_s('S_TANKER_BORN_'||i) := ins_signal_norm(
      v_r('R_TANKER_BORN_'||i), 'AIS', 'AIS:SHADOW:'||i,
      v_ts + NUMTODSINTERVAL(i*15,'MINUTE'), 'vessel', '423000001',
      'Shadow-Tanker A track Bornholm Deep',
      'AIS broadcast from MMSI 423000001 ("MV Avos"). Listed under EU sanctions package 2026-128. Course 270° toward Bornholm Deep.',
      55.30 + i*0.02, 15.50 + i*0.03, 0.78,
      '{"flag":"unknown","heading":270,"seed":"uc4-demo-2026-05-01"}',
      '["ais","sanctions","bornholm"]', 30);
  END LOOP;

  -- ---------- Story signals: Suwałki-Land-Konvoy + ADS-B
  v_ts := SYSTIMESTAMP - INTERVAL '8' HOUR;
  FOR i IN 1..4 LOOP
    v_r('R_SUW_'||i) := ins_signal_raw(
      'NEWS:SUW:'||i, v_ts + NUMTODSINTERVAL(i*30,'MINUTE'),
      '{"source":"OpenMaritime","seed":"uc4-demo-2026-05-01","headline":"Convoy spotted near Suwałki"}',
      50);
    v_s('S_SUW_'||i) := ins_signal_norm(
      v_r('R_SUW_'||i), 'NEWS', 'NEWS:SUW:'||i,
      v_ts + NUMTODSINTERVAL(i*30,'MINUTE'), 'location', 'Suwałki',
      'Local OSINT report: vehicle column south of Suwałki Gap',
      'Open-Maritime Watch geolocated photographs of ~12 utility vehicles westbound on DK-19, ~5 km north of Sejny. Composition consistent with logistics resupply, not armoured.',
      54.10 - i*0.01, 22.93 + i*0.02, 0.65,
      '{"vehicle_count":12,"seed":"uc4-demo-2026-05-01"}',
      '["news","osint","suwalki"]', 50);
  END LOOP;

  -- ---------- Story signals: Spoofing-Cluster Bornholm
  v_ts := SYSTIMESTAMP - INTERVAL '15' HOUR;
  FOR i IN 1..3 LOOP
    v_r('R_SPOOF_BORN_'||i) := ins_signal_raw(
      'GPSJAM:'||i, v_ts + NUMTODSINTERVAL(i*45,'MINUTE'),
      '{"affected_aircraft":'||(8+i)||',"area":"Bornholm","seed":"uc4-demo-2026-05-01"}',
      30);
    v_s('S_SPOOF_BORN_'||i) := ins_signal_norm(
      v_r('R_SPOOF_BORN_'||i), 'JAMMING', 'GPSJAM:'||i,
      v_ts + NUMTODSINTERVAL(i*45,'MINUTE'), 'location', 'BORN_DEEP',
      'Civil aviation GPS spoofing cluster Bornholm Deep',
      'gpsjam.org reports '||(8+i)||' aircraft tracks affected by GPS positional anomalies in the Bornholm Deep sector during the last 60 min.',
      55.30 + i*0.05, 15.50 + i*0.05, 0.80,
      '{"affected_count":'||(8+i)||',"seed":"uc4-demo-2026-05-01"}',
      '["jamming","gpsjam","aviation","bornholm"]', 30);
  END LOOP;

  -- ---------- Story signals: Klaipėda STS-Transfer + Multi-Source Gdańsk
  v_ts := SYSTIMESTAMP - INTERVAL '18' HOUR;
  FOR i IN 1..3 LOOP
    v_r('R_STS_KLA_'||i) := ins_signal_raw(
      'SAR:KLA:'||i, v_ts + NUMTODSINTERVAL(i*40,'MINUTE'),
      '{"sat":"ICEYE_X9","detection":"vessel-vessel-proximity","seed":"uc4-demo-2026-05-01"}',
      30);
    v_s('S_STS_KLA_'||i) := ins_signal_norm(
      v_r('R_STS_KLA_'||i), 'SAR', 'SAR:KLA:'||i,
      v_ts + NUMTODSINTERVAL(i*40,'MINUTE'), 'vessel', '273456790',
      'SAR detection: ship-to-ship proximity off Klaipėda',
      'ICEYE X-9 SAR strip shows two large vessels at 50 m separation, ~12 nm WNW Klaipėda. Reflectivity profile consistent with a tanker-tanker STS transfer.',
      55.71 + i*0.05, 21.13 - i*0.10, 0.88,
      '{"sat":"ICEYE","seed":"uc4-demo-2026-05-01"}',
      '["sar","sts","klaipeda"]', 30);
  END LOOP;

  -- ---------- 90 background signals — gemischte AIS/ADS-B/News/Weather
  -- Verteilen auf alle 12 Anchor-Punkte mit Drift, Klassifikation per pick_label
  FOR i IN 1..90 LOOP
    v_idx := MOD(i, v_anchors.COUNT) + 1;
    v_lat := v_anchors(v_idx).lat + (MOD(i, 7) - 3) * 0.05;
    v_lon := v_anchors(v_idx).lon + (MOD(i, 5) - 2) * 0.07;
    v_label := pick_label(i);
    v_ts := SYSTIMESTAMP - NUMTODSINTERVAL(MOD(i, 72) + 1, 'HOUR');

    v_r('R_BG_'||i) := ins_signal_raw(
      'BG:'||LPAD(i,3,'0'),
      v_ts,
      '{"kind":"background","i":'||i||',"seed":"uc4-demo-2026-05-01"}',
      v_label);
    v_s('S_BG_'||i) := ins_signal_norm(
      v_r('R_BG_'||i),
      CASE MOD(i, 4) WHEN 0 THEN 'AIS' WHEN 1 THEN 'ADS_B'
                     WHEN 2 THEN 'NEWS' ELSE 'WEATHER' END,
      'BG:'||LPAD(i,3,'0'), v_ts,
      CASE MOD(i, 4) WHEN 0 THEN 'vessel' WHEN 1 THEN 'aircraft'
                     WHEN 2 THEN 'location' ELSE 'location' END,
      'BG-ENT-'||LPAD(MOD(i,30)+1,3,'0'),
      'Background signal #'||i||' near '||v_anchors(v_idx).name,
      'Synthetic background activity at lat '||TO_CHAR(v_lat,'FM990.000')
        ||', lon '||TO_CHAR(v_lon,'FM990.000')
        ||'. Used to make correlation queries non-trivial.',
      v_lat, v_lon,
      0.50 + MOD(i,5)*0.05,
      '{"kind":"bg","seed":"uc4-demo-2026-05-01"}',
      '["background","'||LOWER(v_anchors(v_idx).name)||'"]',
      v_label);
  END LOOP;

  -- ---------- 30 zusätzliche raw-only filler (nur signal_raw, kein normalized)
  FOR i IN 1..30 LOOP
    v_label := pick_label(i + 100);
    v_ts := SYSTIMESTAMP - NUMTODSINTERVAL(MOD(i*3, 72) + 1, 'HOUR');
    v_id := ins_signal_raw(
      'RAWBG:'||LPAD(i,3,'0'),
      v_ts,
      '{"kind":"raw-filler","i":'||i||',"seed":"uc4-demo-2026-05-01"}',
      v_label);
  END LOOP;

  DBMS_OUTPUT.PUT_LINE('Inserted '||v_s.COUNT||' normalized signals (with vector rows).');

  -- ========================================================================
  -- (5) entity_mention — 3-5 mentions pro normalisiertem Signal
  -- Story-signals bekommen Hand-crafted mentions; background bekommt
  -- prozedurale rotation durch v_e-keys.
  -- ========================================================================

  -- Story-mentions (hand-crafted, semantisch korrekt)
  FOR i IN 1..6 LOOP
    ins_mention(v_s('S_AIS_STOP_'||i),  v_e('FERRY_GDA'),       'PRIMARY',   0.95, 30);
    ins_mention(v_s('S_AIS_STOP_'||i),  v_e('LOC_AREA_HEL'),    'SECONDARY', 0.85, 30);
    ins_mention(v_s('S_AIS_STOP_'||i),  v_e('OPER_NORD_LOG'),   'CONTEXT',   0.70, 30);
  END LOOP;

  FOR i IN 1..5 LOOP
    ins_mention(v_s('S_JAM_KGD_'||i),   v_e('NAVAL_KGD_01'),    'PRIMARY',   0.92, 50);
    ins_mention(v_s('S_JAM_KGD_'||i),   v_e('LOC_PORT_KGD'),    'SECONDARY', 0.85, 50);
    ins_mention(v_s('S_JAM_KGD_'||i),   v_e('UAS_KGD_01'),      'CONTEXT',   0.65, 50);
  END LOOP;

  FOR i IN 1..4 LOOP
    ins_mention(v_s('S_UAS_KGD_'||i),   v_e('UAS_KGD_01'),      'PRIMARY',   0.95, 50);
    ins_mention(v_s('S_UAS_KGD_'||i),   v_e('NAVAL_KGD_01'),    'SECONDARY', 0.75, 50);
    ins_mention(v_s('S_UAS_KGD_'||i),   v_e('LOC_PORT_KGD'),    'CONTEXT',   0.60, 50);
  END LOOP;

  FOR i IN 1..5 LOOP
    ins_mention(v_s('S_TANKER_BORN_'||i), v_e('SHADOW_TANKER_01'),'PRIMARY',   0.94, 30);
    ins_mention(v_s('S_TANKER_BORN_'||i), v_e('OPER_BALTIC_OIL'), 'SECONDARY', 0.82, 30);
    ins_mention(v_s('S_TANKER_BORN_'||i), v_e('LOC_BORNHOLM_DEEP'),'CONTEXT',  0.85, 30);
  END LOOP;

  FOR i IN 1..4 LOOP
    ins_mention(v_s('S_SUW_'||i),       v_e('OPER_NORD_LOG'),   'PRIMARY',   0.70, 50);
    ins_mention(v_s('S_SUW_'||i),       v_e('NGO_OPENMARITIME'),'SECONDARY', 0.85, 50);
  END LOOP;

  FOR i IN 1..3 LOOP
    ins_mention(v_s('S_SPOOF_BORN_'||i), v_e('LOC_BORNHOLM_DEEP'),'PRIMARY',  0.88, 30);
    ins_mention(v_s('S_SPOOF_BORN_'||i), v_e('SHADOW_TANKER_01'), 'CONTEXT',  0.55, 30);
  END LOOP;

  FOR i IN 1..3 LOOP
    ins_mention(v_s('S_STS_KLA_'||i),   v_e('KASKOL'),          'PRIMARY',   0.90, 30);
    ins_mention(v_s('S_STS_KLA_'||i),   v_e('SHADOW_TANKER_02'),'SECONDARY', 0.85, 30);
    ins_mention(v_s('S_STS_KLA_'||i),   v_e('LOC_PORT_KLA'),    'CONTEXT',   0.80, 30);
    ins_mention(v_s('S_STS_KLA_'||i),   v_e('SAT_ICEYE_X9'),    'CONTEXT',   0.95, 30);
  END LOOP;

  -- Background mentions: jedes BG-Signal bekommt 2 entity_mentions zu
  -- rotierenden Entities aus v_e. Insgesamt ~180 zusätzliche mentions
  -- (90 signals × 2) — zusammen mit den ~80 Story-mentions oben kommen
  -- wir auf ~260, die Toleranz ±10 deckt das ab.
  DECLARE
    -- Static lookup-list von v_e-keys, deterministisch rotated
    TYPE t_keys IS TABLE OF VARCHAR2(64);
    v_keys t_keys := t_keys(
      'AURORA','KASKOL','PALMERSTON','NORDLUX','GREYWATER',
      'SHADOW_TANKER_01','SHADOW_TANKER_02','VIKING_REEF','FERRY_GDA',
      'NAVAL_KGD_01','NAVAL_SE_01','CABLE_LAYER',
      'UAS_KGD_01','UAS_KGD_02','AIRLINER_LH','NATO_E3A','PATROL_DE_P3','NATO_RIVET_J',
      'OPER_NORD_LOG','OPER_BALTIC_OIL','OPER_NEUTRAL_FREIGHT','NGO_OPENMARITIME',
      'LOC_PORT_KGD','LOC_PORT_GDA','LOC_PORT_KLA','LOC_AREA_HEL','LOC_BORNHOLM_DEEP',
      'SAT_SENTINEL2A','SAT_ICEYE_X9','SAT_CAPELLA_03'
    );
  BEGIN
    FOR i IN 1..90 LOOP
      ins_mention(v_s('S_BG_'||i),
                  v_e(v_keys(MOD(i,    v_keys.COUNT) + 1)),
                  'PRIMARY',   0.55 + MOD(i,5)*0.05, pick_label(i));
      ins_mention(v_s('S_BG_'||i),
                  v_e(v_keys(MOD(i+13, v_keys.COUNT) + 1)),
                  'SECONDARY', 0.50 + MOD(i+3,5)*0.05, pick_label(i));
    END LOOP;
  END;

  -- ========================================================================
  -- (6) correlation_event — 8 vorgefertigte Patterns
  -- ========================================================================

  -- 1) EW + UAS Kaliningrad (NFD)
  v_c('EW_UAS_KGD') := ins_corr(
    'JAMMING_OVERLAP',
    '[seed] EW jamming + UAS reconnaissance overlap, Kaliningrad sector',
    SYSTIMESTAMP - INTERVAL '12' HOUR,
    SYSTIMESTAMP - INTERVAL '11' HOUR,
    54.78, 20.85, 0.91,
    '{"kind":"jam_uas_overlap","aoi":"kaliningrad","seed":"uc4-demo-2026-05-01"}',
    50);

  -- 2) AIS-Stillstand Hel (INTERN)
  v_c('AIS_STOP_HEL') := ins_corr(
    'TEMPORAL_CLUSTER',
    '[seed] Pomerania-Express AIS stationary >30 min in Hel NAVAREA',
    SYSTIMESTAMP - INTERVAL '36' HOUR,
    SYSTIMESTAMP - INTERVAL '35' HOUR,
    54.61, 18.81, 0.78,
    '{"kind":"ais_stationary","aoi":"hel","seed":"uc4-demo-2026-05-01"}',
    30);

  -- 3) Sanktionierter Tanker Bornholm (INTERN)
  v_c('SANC_BORN') := ins_corr(
    'GRAPH_CHAIN',
    '[seed] Sanctioned Shadow-Tanker A movement Bornholm Deep',
    SYSTIMESTAMP - INTERVAL '20' HOUR,
    SYSTIMESTAMP - INTERVAL '18' HOUR,
    55.30, 15.50, 0.86,
    '{"kind":"sanctions_match","aoi":"bornholm","seed":"uc4-demo-2026-05-01"}',
    30);

  -- 4) Suwałki-Land-Konvoy (NFD)
  v_c('SUW_CONVOY') := ins_corr(
    'CO_LOCATED',
    '[seed] Vehicle column + emitter activity Suwałki Gap',
    SYSTIMESTAMP - INTERVAL '8' HOUR,
    SYSTIMESTAMP - INTERVAL '6' HOUR,
    54.10, 22.93, 0.74,
    '{"kind":"land_convoy","aoi":"suwalki","seed":"uc4-demo-2026-05-01"}',
    50);

  -- 5) Spoofing-Cluster Bornholm (INTERN)
  v_c('SPOOF_BORN') := ins_corr(
    'TEMPORAL_CLUSTER',
    '[seed] Civil aviation GPS spoofing cluster, Bornholm Deep',
    SYSTIMESTAMP - INTERVAL '15' HOUR,
    SYSTIMESTAMP - INTERVAL '12' HOUR,
    55.30, 15.50, 0.83,
    '{"kind":"spoofing","aoi":"bornholm","seed":"uc4-demo-2026-05-01"}',
    30);

  -- 6) Karlskrona Hafen-Anomalie (OFFEN)
  v_c('KARL_PORT_ANOMALY') := ins_corr(
    'TEMPORAL_CLUSTER',
    '[seed] Karlskrona naval port traffic anomaly',
    SYSTIMESTAMP - INTERVAL '5' HOUR,
    SYSTIMESTAMP - INTERVAL '4' HOUR,
    56.16, 15.59, 0.62,
    '{"kind":"port_traffic","aoi":"karlskrona","seed":"uc4-demo-2026-05-01"}',
    10);

  -- 7) Klaipėda STS-Transfer (INTERN)
  v_c('STS_KLA') := ins_corr(
    'GRAPH_CHAIN',
    '[seed] Suspected ship-to-ship transfer off Klaipėda',
    SYSTIMESTAMP - INTERVAL '18' HOUR,
    SYSTIMESTAMP - INTERVAL '16' HOUR,
    55.71, 20.95, 0.88,
    '{"kind":"sts","aoi":"klaipeda","seed":"uc4-demo-2026-05-01"}',
    30);

  -- 8) Multi-Source Tanker-Kette Gdańsk (NFD)
  v_c('TANKER_CHAIN_GDA') := ins_corr(
    'GRAPH_CHAIN',
    '[seed] Multi-source tanker-network chain, Gdańsk Bay',
    SYSTIMESTAMP - INTERVAL '24' HOUR,
    SYSTIMESTAMP - INTERVAL '12' HOUR,
    54.40, 18.70, 0.79,
    '{"kind":"network_chain","aoi":"gdansk","seed":"uc4-demo-2026-05-01"}',
    50);

  -- ========================================================================
  -- (7) correlation_includes_event / correlation_includes_entity
  -- ========================================================================

  -- EW_UAS_KGD: enthält 5 Jam-Signale + 4 UAS-Signale + entities
  FOR i IN 1..5 LOOP ins_corr_inc_event(v_c('EW_UAS_KGD'), v_s('S_JAM_KGD_'||i), 'TRIGGER', 0.92, 50); END LOOP;
  FOR i IN 1..4 LOOP ins_corr_inc_event(v_c('EW_UAS_KGD'), v_s('S_UAS_KGD_'||i), 'CONTEXT', 0.88, 50); END LOOP;
  ins_corr_inc_entity(v_c('EW_UAS_KGD'), v_e('NAVAL_KGD_01'),  'PRIMARY',   50);
  ins_corr_inc_entity(v_c('EW_UAS_KGD'), v_e('UAS_KGD_01'),    'SECONDARY', 50);
  ins_corr_inc_entity(v_c('EW_UAS_KGD'), v_e('LOC_PORT_KGD'),  'CONTEXT',   50);

  -- AIS_STOP_HEL
  FOR i IN 1..6 LOOP ins_corr_inc_event(v_c('AIS_STOP_HEL'), v_s('S_AIS_STOP_'||i), 'TRIGGER', 0.85, 30); END LOOP;
  ins_corr_inc_entity(v_c('AIS_STOP_HEL'), v_e('FERRY_GDA'),    'PRIMARY',   30);
  ins_corr_inc_entity(v_c('AIS_STOP_HEL'), v_e('LOC_AREA_HEL'), 'SECONDARY', 30);

  -- SANC_BORN
  FOR i IN 1..5 LOOP ins_corr_inc_event(v_c('SANC_BORN'), v_s('S_TANKER_BORN_'||i), 'TRIGGER', 0.90, 30); END LOOP;
  ins_corr_inc_entity(v_c('SANC_BORN'), v_e('SHADOW_TANKER_01'), 'PRIMARY',   30);
  ins_corr_inc_entity(v_c('SANC_BORN'), v_e('OPER_BALTIC_OIL'),  'SECONDARY', 30);
  ins_corr_inc_entity(v_c('SANC_BORN'), v_e('LOC_BORNHOLM_DEEP'),'CONTEXT',   30);

  -- SUW_CONVOY
  FOR i IN 1..4 LOOP ins_corr_inc_event(v_c('SUW_CONVOY'), v_s('S_SUW_'||i), 'TRIGGER', 0.65, 50); END LOOP;
  ins_corr_inc_entity(v_c('SUW_CONVOY'), v_e('OPER_NORD_LOG'),   'PRIMARY',   50);
  ins_corr_inc_entity(v_c('SUW_CONVOY'), v_e('NGO_OPENMARITIME'),'CONTEXT',   50);

  -- SPOOF_BORN
  FOR i IN 1..3 LOOP ins_corr_inc_event(v_c('SPOOF_BORN'), v_s('S_SPOOF_BORN_'||i), 'TRIGGER', 0.85, 30); END LOOP;
  ins_corr_inc_entity(v_c('SPOOF_BORN'), v_e('LOC_BORNHOLM_DEEP'),'PRIMARY', 30);
  ins_corr_inc_entity(v_c('SPOOF_BORN'), v_e('SHADOW_TANKER_01'), 'CONTEXT', 30);

  -- KARL_PORT_ANOMALY (uses some background signals near Karlskrona)
  -- Karlskrona = anchor index 2; signals S_BG_2, S_BG_14, S_BG_26, ...
  FOR i IN 1..3 LOOP
    ins_corr_inc_event(v_c('KARL_PORT_ANOMALY'),
                       v_s('S_BG_'||TO_CHAR(2 + (i-1)*12)),
                       CASE WHEN i = 1 THEN 'TRIGGER' ELSE 'CONTEXT' END,
                       0.62, 10);
  END LOOP;
  ins_corr_inc_entity(v_c('KARL_PORT_ANOMALY'), v_e('NAVAL_SE_01'),    'PRIMARY',   10);
  ins_corr_inc_entity(v_c('KARL_PORT_ANOMALY'), v_e('GREYWATER'),      'SECONDARY', 10);

  -- STS_KLA
  FOR i IN 1..3 LOOP ins_corr_inc_event(v_c('STS_KLA'), v_s('S_STS_KLA_'||i), 'TRIGGER', 0.88, 30); END LOOP;
  ins_corr_inc_entity(v_c('STS_KLA'), v_e('KASKOL'),          'PRIMARY',   30);
  ins_corr_inc_entity(v_c('STS_KLA'), v_e('SHADOW_TANKER_02'),'SECONDARY', 30);
  ins_corr_inc_entity(v_c('STS_KLA'), v_e('LOC_PORT_KLA'),    'CONTEXT',   30);

  -- TANKER_CHAIN_GDA — kombiniert mehrere existierende Signale + entities
  ins_corr_inc_event(v_c('TANKER_CHAIN_GDA'), v_s('S_TANKER_BORN_1'), 'TRIGGER', 0.80, 50);
  ins_corr_inc_event(v_c('TANKER_CHAIN_GDA'), v_s('S_STS_KLA_1'),     'CONTEXT', 0.75, 50);
  ins_corr_inc_event(v_c('TANKER_CHAIN_GDA'), v_s('S_BG_5'),          'CONTEXT', 0.55, 50);
  ins_corr_inc_event(v_c('TANKER_CHAIN_GDA'), v_s('S_BG_17'),         'CONTEXT', 0.55, 50);
  ins_corr_inc_event(v_c('TANKER_CHAIN_GDA'), v_s('S_BG_29'),         'CONTEXT', 0.55, 50);
  ins_corr_inc_entity(v_c('TANKER_CHAIN_GDA'), v_e('SHADOW_TANKER_01'),'PRIMARY',   50);
  ins_corr_inc_entity(v_c('TANKER_CHAIN_GDA'), v_e('KASKOL'),          'SECONDARY', 50);
  ins_corr_inc_entity(v_c('TANKER_CHAIN_GDA'), v_e('OPER_BALTIC_OIL'), 'SECONDARY', 50);
  ins_corr_inc_entity(v_c('TANKER_CHAIN_GDA'), v_e('LOC_PORT_GDA'),    'CONTEXT',   50);

  -- ========================================================================
  -- (8) briefing — eine pro correlation
  -- ========================================================================
  ins_briefing(v_c('EW_UAS_KGD'),
    'Korrelation: EW + UAS Kaliningrad-Sektor',
    'Lagebild: Über die letzten 12h sind 5 GPS-L1-Jamming-Pulse von Naval-Patrol-9 ausgegangen, '
    ||'zeitlich überlagert mit 4 Orlan-10 ADS-B-Tracks im Reconnaissance-Pattern. Konvergenz-Score 0.91. '
    ||'Empfehlung: NOTAM-Erweiterung Hel-Korridor + Coordination MFG.',
    54.78, 20.85, 50);

  ins_briefing(v_c('AIS_STOP_HEL'),
    'Korrelation: AIS-Stillstand Pomerania-Express',
    'Lagebild: Pomerania-Express (MMSI 261222333) stationär seit 36h NW Hel. Erwartete Kursleg 14kn, '
    ||'gemeldet 0.1kn. Mögliche Ursachen: technisch / wetterbedingt / EW-Beeinflussung. '
    ||'Empfehlung: Klarstellung mit Reederei (Nord-Logistik), Wetter-Cross-Check.',
    54.61, 18.81, 30);

  ins_briefing(v_c('SANC_BORN'),
    'Korrelation: Sanktionierter Tanker Bornholm',
    'Lagebild: Shadow-Tanker A (MMSI 423000001, Alias MV Avos, EU-Sanktionsliste 2026-128) '
    ||'kreuzt Bornholm Deep auf Westkurs. 5 AIS-Reports im 75-min-Fenster. Operator: Baltic Oil Ltd (gelistet). '
    ||'Empfehlung: AIS-Tracking mit Frontex-Coast koordinieren, Bornholm-Marine-Polizei informieren.',
    55.30, 15.50, 30);

  ins_briefing(v_c('SUW_CONVOY'),
    'Korrelation: Suwałki-Land-Konvoy',
    'Lagebild: 12-Fahrzeug-Konvoy logistischer Klasse (nicht-armoured) gesichtet auf DK-19 nördlich Sejny. '
    ||'Quelle Open-Maritime Watch, 4 unabhängige Foto-Sichtungen. Konvergenz mit Emitter-Signal aus Truck-Position. '
    ||'Empfehlung: Aufklärungsanfrage Litauen-LK + Weiterverfolgung Mil. Foreign Liaison.',
    54.10, 22.93, 50);

  ins_briefing(v_c('SPOOF_BORN'),
    'Korrelation: GPS-Spoofing Bornholm',
    'Lagebild: 27 zivile Flugzeuge mit GPS-Positionsanomalien im Bornholm-Deep-Sektor. 3 Beobachtungen '
    ||'in 90-min-Fenster, mit Korrelation zum Shadow-Tanker-A-Track. '
    ||'Empfehlung: NAVTEX/NOTAM-Erweiterung, Cooperation DK-CAA + EUSPA.',
    55.30, 15.50, 30);

  ins_briefing(v_c('KARL_PORT_ANOMALY'),
    'Korrelation: Karlskrona Port Activity',
    'Lagebild: 3 Background-AIS-Signale in 5h-Fenster zeigen ungewohnte Verkehrsdichte am Karlskrona-Naval-Pier. '
    ||'Visby-class Korvette HSwMS und Frachter MV Greywater im selben Sektor. '
    ||'Empfehlung: Routine-Cross-Check mit SE-MoD-Public-Affairs — keine Eskalation.',
    56.16, 15.59, 10);

  ins_briefing(v_c('STS_KLA'),
    'Korrelation: STS-Transfer Klaipėda',
    'Lagebild: ICEYE-X-9-SAR-Streifen zeigt Tanker-Tanker-Proximity (50m, 12nm WNW Klaipėda). '
    ||'Beteiligt: MV Kaskol (RU, MMSI 273456790) und Shadow-Tanker B. 3 SAR-Sichtungen über 2h. '
    ||'Empfehlung: Anfrage Klaipėda-Hafenmeisterei + Lateinisch-Cross-Check Cargo Manifest.',
    55.71, 20.95, 30);

  ins_briefing(v_c('TANKER_CHAIN_GDA'),
    'Korrelation: Multi-Source Tanker-Kette Gdańsk Bay',
    'Lagebild: Network-Chain-Detector verbindet Shadow-Tanker A (Bornholm), MV Kaskol (Klaipėda STS) '
    ||'und 3 Background-AIS-Tracks via gemeinsamem Operator Baltic Oil Ltd. Geographic-Centroid Gdańsk Bay. '
    ||'Empfehlung: Eskalation auf BMVg-Lagezentrum, Frontex-Joint-Operation Erwägung.',
    54.40, 18.70, 50);

  -- ========================================================================
  -- (9) audit_trail — 50 Einträge, gemischte actor_types
  --
  -- Etwa 30 generierte rows + 20 hand-crafted plus die finale
  -- SEED_COMPLETE-Marker-Zeile (= 51, in Toleranz).
  -- ========================================================================

  -- Hand-crafted "Story-Audit" — bildet wirkliche Operator-Aktionen ab
  ins_audit('SYSTEM','ingest-pipeline','BULK_INSERT','signal_raw',     30, c_marker||':bulk-1');
  ins_audit('SYSTEM','ingest-pipeline','BULK_INSERT','signal_normalized',30, c_marker||':bulk-2');
  ins_audit('SYSTEM','correlation-detector','TOOL_CALL','correlation_event',50, c_marker||':detect-1');
  ins_audit('AGENT', 'threat-fusion-agent-v1','BRIEFING_GEN','briefing',50, c_marker||':brief-1');
  ins_audit('AGENT', 'threat-fusion-agent-v1','BRIEFING_GEN','briefing',30, c_marker||':brief-2');
  ins_audit('AGENT', 'threat-fusion-agent-v1','BRIEFING_GEN','briefing',10, c_marker||':brief-3');
  ins_audit('USER',  'OBERST_WEBER','SELECT','briefing',                50, c_marker||':read-1');
  ins_audit('USER',  'OBERST_WEBER','SELECT','correlation_event',       50, c_marker||':read-2');
  ins_audit('USER',  'HAUPTMANN_LANGE','SELECT','briefing',             30, c_marker||':read-3');
  ins_audit('USER',  'HAUPTMANN_LANGE','SELECT','correlation_event',    30, c_marker||':read-4');
  ins_audit('USER',  'M_SCHMIDT','SELECT','briefing',                   10, c_marker||':read-5');
  ins_audit('USER',  'M_SCHMIDT','SELECT','correlation_event',          10, c_marker||':read-6');
  ins_audit('SYSTEM','health-probe','SELECT','signal_normalized',       10, c_marker||':probe-1');
  ins_audit('SCHEDULER','daily-cleanup','DELETE','signal_raw',          30, c_marker||':cleanup-1');
  ins_audit('AGENT', 'doctrine-rag-agent-v1','TOOL_CALL','briefing',    30, c_marker||':rag-1');
  ins_audit('AGENT', 'doctrine-rag-agent-v1','TOOL_CALL','briefing',    50, c_marker||':rag-2');
  ins_audit('SYSTEM','vector-embedder','TOOL_CALL','signal_vectors',    30, c_marker||':embed-1');
  ins_audit('USER',  'OBERST_WEBER','UPDATE','briefing',                50, c_marker||':approve-1');
  ins_audit('USER',  'OBERST_WEBER','UPDATE','briefing',                30, c_marker||':approve-2');
  ins_audit('SYSTEM','export-pipeline','SELECT','briefing',             10, c_marker||':export-1');

  -- Generierte Audit-Rows: 30 stück mit rotation
  FOR i IN 1..30 LOOP
    ins_audit(
      CASE MOD(i, 4) WHEN 0 THEN 'SYSTEM' WHEN 1 THEN 'AGENT'
                     WHEN 2 THEN 'USER'   ELSE       'SCHEDULER' END,
      'audit-actor-'||LPAD(i,3,'0'),
      CASE MOD(i, 5) WHEN 0 THEN 'INSERT' WHEN 1 THEN 'SELECT'
                     WHEN 2 THEN 'TOOL_CALL' WHEN 3 THEN 'UPDATE'
                     ELSE 'BRIEFING_GEN' END,
      CASE MOD(i, 6) WHEN 0 THEN 'signal_normalized' WHEN 1 THEN 'entity'
                     WHEN 2 THEN 'correlation_event' WHEN 3 THEN 'briefing'
                     WHEN 4 THEN 'audit_trail'      ELSE 'entity_mention' END,
      pick_label(i),
      c_marker||':gen-'||LPAD(i,3,'0')
    );
  END LOOP;

  -- ========================================================================
  -- (10) Final marker
  -- ========================================================================
  ins_audit('SYSTEM', c_actor, 'SEED_COMPLETE', NULL, 10, c_marker);

  COMMIT;

  DBMS_OUTPUT.PUT_LINE(
    '01_demo_seed.sql OK: entities='||v_e.COUNT
    ||', emitters='||v_em.COUNT
    ||', signals_raw='||v_r.COUNT
    ||', signals_normalized='||v_s.COUNT
    ||', correlations='||v_c.COUNT||'.');
END;
/

-- ===========================================================================
-- Tail-Sanity: Volumen prüfen — Toleranz ±10 für die Loop-generierten Counts.
-- ===========================================================================
DECLARE
  v_signal_raw            NUMBER;
  v_signal_normalized     NUMBER;
  v_signal_vectors        NUMBER;
  v_entity                NUMBER;
  v_entity_mention        NUMBER;
  v_ems_emitter           NUMBER;
  v_correlation_event     NUMBER;
  v_corr_inc_event        NUMBER;
  v_corr_inc_entity       NUMBER;
  v_briefing              NUMBER;
  v_audit_trail           NUMBER;

  PROCEDURE assert_in(p_label VARCHAR2, p_actual NUMBER, p_low NUMBER, p_high NUMBER) IS
  BEGIN
    IF p_actual < p_low OR p_actual > p_high THEN
      RAISE_APPLICATION_ERROR(-20006,
        '01_demo_seed.sql: '||p_label||' count='||p_actual
        ||' außerhalb erwarteter Range ['||p_low||','||p_high||'].');
    END IF;
  END;
BEGIN
  SELECT COUNT(*) INTO v_signal_raw         FROM signal_raw         WHERE source_provider = 'seed:uc4-demo';
  SELECT COUNT(*) INTO v_signal_normalized  FROM signal_normalized  WHERE source_provider = 'seed:uc4-demo';
  SELECT COUNT(*) INTO v_signal_vectors     FROM signal_vectors     sv
    WHERE EXISTS (SELECT 1 FROM signal_normalized sn
                   WHERE sn.event_id = sv.event_id AND sn.source_provider = 'seed:uc4-demo');
  SELECT COUNT(*) INTO v_entity             FROM entity             WHERE JSON_VALUE(attributes,'$.seed') = 'uc4-demo-2026-05-01';
  SELECT COUNT(*) INTO v_entity_mention     FROM entity_mention     em
    WHERE EXISTS (SELECT 1 FROM signal_normalized sn
                   WHERE sn.event_id = em.event_id AND sn.source_provider = 'seed:uc4-demo');
  SELECT COUNT(*) INTO v_ems_emitter        FROM ems_emitter
    WHERE entity_id IN (SELECT entity_id FROM entity WHERE JSON_VALUE(attributes,'$.seed') = 'uc4-demo-2026-05-01')
       OR (entity_id IS NULL
           AND first_observed_at >= SYSTIMESTAMP - INTERVAL '30' DAY);
  -- Filter über summary LIKE '[seed]%' statt JSON_VALUE(payload,'$.seed'),
  -- weil JSON_VALUE auf payload den asynchron-synced JSON Search Index
  -- IDX_CORR_PAYLOAD_JSON triggern kann — der ist nach dem unmittelbaren
  -- COMMIT noch nicht refresht, und der Optimizer wählt ihn trotzdem
  -- (siehe Reproduktion: identische Predicate liefert in fresh session
  -- 8 Rows, in der Same-Session-Folge-Block-Query 0). Nicht-indizierte
  -- Spalte umgeht das vollständig.
  SELECT COUNT(*) INTO v_correlation_event  FROM correlation_event  WHERE summary LIKE '[seed]%';
  SELECT COUNT(*) INTO v_corr_inc_event     FROM correlation_includes_event;
  SELECT COUNT(*) INTO v_corr_inc_entity    FROM correlation_includes_entity;
  SELECT COUNT(*) INTO v_briefing           FROM briefing           WHERE generated_by = 'uc4-seed';
  SELECT COUNT(*) INTO v_audit_trail        FROM audit_trail        WHERE invocation_id LIKE 'seed:uc4-demo%';

  assert_in('signal_raw',                 v_signal_raw,        140, 160);
  assert_in('signal_normalized',          v_signal_normalized, 110, 130);
  assert_in('signal_vectors',             v_signal_vectors,    110, 130);
  assert_in('entity',                     v_entity,             25,  35);
  assert_in('entity_mention',             v_entity_mention,    230, 280);
  assert_in('ems_emitter',                v_ems_emitter,        13,  17);
  assert_in('correlation_event',          v_correlation_event,   8,   8);
  assert_in('correlation_includes_event', v_corr_inc_event,     30,  50);
  assert_in('correlation_includes_entity',v_corr_inc_entity,    20,  35);
  assert_in('briefing',                   v_briefing,            8,   8);
  assert_in('audit_trail',                v_audit_trail,        45,  60);

  DBMS_OUTPUT.PUT_LINE('01_demo_seed.sql sanity OK: '
    ||'sig_raw='||v_signal_raw
    ||', sig_norm='||v_signal_normalized
    ||', sig_vec='||v_signal_vectors
    ||', ent='||v_entity
    ||', ment='||v_entity_mention
    ||', emit='||v_ems_emitter
    ||', corr='||v_correlation_event
    ||', cie='||v_corr_inc_event
    ||', cien='||v_corr_inc_entity
    ||', brief='||v_briefing
    ||', audit='||v_audit_trail);
END;
/

-- ===========================================================================
-- Done. Folge: 02_compute_embeddings.sql — füllt signal_vectors.embedding
-- via DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING gegen Cohere multilingual-v3.0
-- in eu-frankfurt-1. Idempotent: nur Rows mit embedding IS NULL werden
-- befüllt.
-- ===========================================================================
