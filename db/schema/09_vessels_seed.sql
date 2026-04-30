--==============================================================================
-- File:        09_vessels_seed.sql
-- Purpose:     Demo-Vessels (Maritime AIS, Ostsee/Baltic Sea) als Seed-Daten
--              fuer UC4 OSINT-Fusion. Alle Vessels werden als osint_entities
--              mit kind='vessel' und attributes-JSON gespeichert. Die Property
--              Graph 'intel_fusion' (siehe 05_property_graphs.sql) sieht diese
--              Rows automatisch als entity-Vertices ueber dieselbe Tabelle.
--
--              Zusaetzlich: 2 Hafen-Locations (kind='location') und 1 Event
--              (kind='event'), plus 3 Beziehungen in osint_relationships
--              ('docks_at' Vessel->Location, 'mentioned_in' Vessel->Event).
--
-- Target:      Oracle AI Database 26ai (Autonomous Transaction Processing)
-- Depends on:  01_tenants_and_security.sql (tenant T001 = DEU_BMVG existiert)
--              02_core_tables.sql          (osint_entities + osint_relationships)
--              05_property_graphs.sql      (intel_fusion graph)
--
-- Idempotency: MERGE statements; deterministische entity_id-Praefixe ('VES-', 'LOC-',
--              'EVT-', 'REL-') so dass wiederholtes Ausfuehren keine Duplikate erzeugt.
--
-- Klassifizierung: ols_label = 100 (UNCLASSIFIED / OPEN) fuer alle Demo-Daten.
-- Tenant:          T001 (DEU_BMVG) — der einzige im Repo seedete DEU-Tenant.
-- BBox-Daten:      ca. 53N..60N, 8E..25E. Bewusst weiter als die Live-AIS-
--                  Subscription-Bbox (AIS_BBOX_DEFAULT in app/settings.py),
--                  damit Demo-Queries auch die Helsinki-Tallinn-Route, Gotland
--                  und Saaremaa abdecken. Die Seed-Daten und der Live-AIS-
--                  Stream sind getrennte Datenquellen — die Lagebild-View
--                  zeigt Live-Frames als Billboards, die OSINT-Graph-View
--                  zeigt diese Seed-Rows.
-- MMSI-Ranges:     Real reservierte MID-Codes pro Flag — nicht 1xxxxxxxx Range.
--                  211=DEU, 244=NLD, 230=FIN, 219=DNK, 265=SWE, 276=EST.
--
-- BBox-Parametrisierung: SQLcl substitution variables &BBOX_SOUTH, &BBOX_WEST,
--                  &BBOX_NORTH, &BBOX_EAST sind nur informativ — sie steuern
--                  einen PROMPT-Block am Anfang dieses Skripts, NICHT die
--                  Vessel-Koordinaten. Letztere sind absichtlich an realen
--                  Hafen-/Routen-Positionen verankert und ändern sich nicht
--                  mit der Bbox. Das Wrapper-Skript scripts/seed-vessels.sh
--                  liest AIS_BBOX_DEFAULT aus dem Environment und setzt die
--                  Variablen via `sqlcl -DBBOX_SOUTH=...` o.ä.
--==============================================================================

-- BBox PROMPT (substitution-on for one block)
SET DEFINE ON;
DEFINE BBOX_SOUTH = '53';
DEFINE BBOX_WEST  = '8';
DEFINE BBOX_NORTH = '56';
DEFINE BBOX_EAST  = '22';
PROMPT Loading vessels into the AIS subscription envelope: &BBOX_SOUTH..&BBOX_NORTH N, &BBOX_WEST..&BBOX_EAST E
PROMPT (Vessel positions are fixed real-world coords; the bbox above is the live-feed filter, not a seed parameter.)
SET DEFINE OFF;

SET SERVEROUTPUT ON SIZE UNLIMITED;
WHENEVER SQLERROR CONTINUE;

--------------------------------------------------------------------------------
-- 1. Vessels — 8 Demo-Schiffe in der Ostsee
--    Mix: 2x cargo, 2x passenger, 1x fishing, 1x research, 2x navy/coast guard
--------------------------------------------------------------------------------

-- Vessel 1: Cargo Container — DEU-flagged, vor Kiel
MERGE INTO osint_entities t
USING (SELECT
         'VES-211554000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'MV Hanse Bremen'                                     AS canonical_name,
         JSON('{"mmsi":"211554000","imo":"9456321","flag":"DEU","vessel_name":"MV Hanse Bremen","vessel_type":"cargo_container","lat":54.4232,"lon":10.1539,"heading_deg":275,"speed_kn":12.4}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 2: Cargo Tanker — NLD-flagged, suedwestlich Bornholm
MERGE INTO osint_entities t
USING (SELECT
         'VES-244670000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'MT Eemshaven Star'                                   AS canonical_name,
         JSON('{"mmsi":"244670000","imo":"9587412","flag":"NLD","vessel_name":"MT Eemshaven Star","vessel_type":"cargo_tanker","lat":54.8901,"lon":14.7723,"heading_deg":68,"speed_kn":10.1}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 3: Passenger Ferry — DNK-flagged, Roedby-Puttgarden Route
MERGE INTO osint_entities t
USING (SELECT
         'VES-219015000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'M/F Prinsesse Benedikte'                             AS canonical_name,
         JSON('{"mmsi":"219015000","imo":"9144419","flag":"DNK","vessel_name":"M/F Prinsesse Benedikte","vessel_type":"passenger_ferry","lat":54.5589,"lon":11.4112,"heading_deg":190,"speed_kn":18.6}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 4: Passenger Ferry — FIN-flagged, Helsinki-Tallinn Route
MERGE INTO osint_entities t
USING (SELECT
         'VES-230636000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'M/S Finlandia'                                       AS canonical_name,
         JSON('{"mmsi":"230636000","imo":"9214379","flag":"FIN","vessel_name":"M/S Finlandia","vessel_type":"passenger_ferry","lat":59.6234,"lon":24.7423,"heading_deg":205,"speed_kn":21.3}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 5: Fishing Vessel — SWE-flagged, suedl. Gotland
MERGE INTO osint_entities t
USING (SELECT
         'VES-265814000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'F/V Nordstjernan'                                    AS canonical_name,
         JSON('{"mmsi":"265814000","imo":"8923471","flag":"SWE","vessel_name":"F/V Nordstjernan","vessel_type":"fishing","lat":56.7812,"lon":18.4533,"heading_deg":134,"speed_kn":4.2}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 6: Research Vessel — DEU-flagged, vor Ruegen
MERGE INTO osint_entities t
USING (SELECT
         'VES-211221000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'RV Alkor'                                            AS canonical_name,
         JSON('{"mmsi":"211221000","imo":"9023234","flag":"DEU","vessel_name":"RV Alkor","vessel_type":"research","lat":54.6101,"lon":13.7822,"heading_deg":355,"speed_kn":6.0}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 7: Navy / German Navy Frigate — DEU-flagged, vor Warnemuende
MERGE INTO osint_entities t
USING (SELECT
         'VES-211100100'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'FGS Sachsen-Anhalt'                                  AS canonical_name,
         JSON('{"mmsi":"211100100","imo":"4185621","flag":"DEU","vessel_name":"FGS Sachsen-Anhalt","vessel_type":"navy","lat":54.2003,"lon":12.0934,"heading_deg":92,"speed_kn":15.5}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Vessel 8: Coast Guard — EST-flagged, oestl. Saaremaa
MERGE INTO osint_entities t
USING (SELECT
         'VES-276910000'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'vessel'                                              AS kind,
         'PV Raju'                                             AS canonical_name,
         JSON('{"mmsi":"276910000","imo":"9512874","flag":"EST","vessel_name":"PV Raju","vessel_type":"coast_guard","lat":58.3812,"lon":22.4011,"heading_deg":48,"speed_kn":11.8}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

--------------------------------------------------------------------------------
-- 2. Hafen-Locations (kind='location') — fuer 'docks_at'-Korrelation
--------------------------------------------------------------------------------

-- Location: Hafen Kiel
MERGE INTO osint_entities t
USING (SELECT
         'LOC-PORT-KIEL'                                       AS entity_id,
         'T001'                                                AS tenant_id,
         'location'                                            AS kind,
         'Hafen Kiel'                                          AS canonical_name,
         JSON('{"location_type":"port","unlocode":"DEKEL","country_iso3":"DEU","lat":54.3233,"lon":10.1394}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

-- Location: Hafen Tallinn
MERGE INTO osint_entities t
USING (SELECT
         'LOC-PORT-TLL'                                        AS entity_id,
         'T001'                                                AS tenant_id,
         'location'                                            AS kind,
         'Hafen Tallinn'                                       AS canonical_name,
         JSON('{"location_type":"port","unlocode":"EETLL","country_iso3":"EST","lat":59.4444,"lon":24.7536}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

--------------------------------------------------------------------------------
-- 3. Event (kind='event') — Hafenbesuch fuer 'mentioned_in'-Korrelation
--------------------------------------------------------------------------------

MERGE INTO osint_entities t
USING (SELECT
         'EVT-PORT-CALL-001'                                   AS entity_id,
         'T001'                                                AS tenant_id,
         'event'                                               AS kind,
         'Port Call FGS Sachsen-Anhalt @ Warnemuende'          AS canonical_name,
         JSON('{"event_type":"port_call","port_unlocode":"DEWAR","occurred_at":"2026-04-25T14:30:00Z","summary":"Routine logistical resupply, 6 hours alongside."}') AS attributes,
         100                                                   AS ols_label
       FROM dual) s
ON (t.entity_id = s.entity_id)
WHEN NOT MATCHED THEN INSERT
  (entity_id, tenant_id, kind, canonical_name, attributes, ols_label)
  VALUES
  (s.entity_id, s.tenant_id, s.kind, s.canonical_name, s.attributes, s.ols_label);

--------------------------------------------------------------------------------
-- 4. Relationships — Vessel<->Location, Vessel<->Event
--    Idempotent via deterministische rel_id.
--------------------------------------------------------------------------------

-- MV Hanse Bremen docks_at Hafen Kiel
MERGE INTO osint_relationships t
USING (SELECT
         'REL-VES-211554000-DOCKS-KIEL'                        AS rel_id,
         'VES-211554000'                                       AS src_id,
         'LOC-PORT-KIEL'                                       AS dst_id,
         'docks_at'                                            AS rel_type,
         0.92                                                  AS confidence,
         JSON('{"source":"AIS-derived","method":"distance_to_port_centroid<2nm"}') AS evidence,
         100                                                   AS ols_label
       FROM dual) s
ON (t.rel_id = s.rel_id)
WHEN NOT MATCHED THEN INSERT
  (rel_id, src_id, dst_id, rel_type, confidence, evidence, ols_label)
  VALUES
  (s.rel_id, s.src_id, s.dst_id, s.rel_type, s.confidence, s.evidence, s.ols_label);

-- M/S Finlandia docks_at Hafen Tallinn
MERGE INTO osint_relationships t
USING (SELECT
         'REL-VES-230636000-DOCKS-TLL'                         AS rel_id,
         'VES-230636000'                                       AS src_id,
         'LOC-PORT-TLL'                                        AS dst_id,
         'docks_at'                                            AS rel_type,
         0.88                                                  AS confidence,
         JSON('{"source":"AIS-derived","method":"distance_to_port_centroid<2nm"}') AS evidence,
         100                                                   AS ols_label
       FROM dual) s
ON (t.rel_id = s.rel_id)
WHEN NOT MATCHED THEN INSERT
  (rel_id, src_id, dst_id, rel_type, confidence, evidence, ols_label)
  VALUES
  (s.rel_id, s.src_id, s.dst_id, s.rel_type, s.confidence, s.evidence, s.ols_label);

-- FGS Sachsen-Anhalt mentioned_in Port Call Event
MERGE INTO osint_relationships t
USING (SELECT
         'REL-VES-211100100-MENTIONED-EVT001'                  AS rel_id,
         'VES-211100100'                                       AS src_id,
         'EVT-PORT-CALL-001'                                   AS dst_id,
         'mentioned_in'                                        AS rel_type,
         1.00                                                  AS confidence,
         JSON('{"source":"navy_press_release","ref":"BMVg-Tagesbericht-2026-04-25"}') AS evidence,
         100                                                   AS ols_label
       FROM dual) s
ON (t.rel_id = s.rel_id)
WHEN NOT MATCHED THEN INSERT
  (rel_id, src_id, dst_id, rel_type, confidence, evidence, ols_label)
  VALUES
  (s.rel_id, s.src_id, s.dst_id, s.rel_type, s.confidence, s.evidence, s.ols_label);

COMMIT;

--==============================================================================
-- Rollback (manuell — nur ausfuehren wenn explizit erwuenscht):
--
--   DELETE FROM osint_relationships WHERE rel_id IN (
--     'REL-VES-211554000-DOCKS-KIEL',
--     'REL-VES-230636000-DOCKS-TLL',
--     'REL-VES-211100100-MENTIONED-EVT001'
--   );
--
--   DELETE FROM osint_entities WHERE entity_id IN (
--     'VES-211554000','VES-244670000','VES-219015000','VES-230636000',
--     'VES-265814000','VES-211221000','VES-211100100','VES-276910000',
--     'LOC-PORT-KIEL','LOC-PORT-TLL',
--     'EVT-PORT-CALL-001'
--   );
--
--   COMMIT;
--==============================================================================
-- End of 09_vessels_seed.sql
--==============================================================================
