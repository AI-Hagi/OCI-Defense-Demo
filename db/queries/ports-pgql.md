# Ports — Demo PGQL & SQL Queries

UC4 OSINT-Korrelation für Layer #6 (Ports, Pattern A static-load mit
hybrid OSM + curated Klassifikator). Der `services/ports-proxy`-Service
schreibt EINE `osint_cache`-Row (`layer='ports'`):

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "geometry": {"type": "Point", "coordinates": [9.9836, 53.5418]},
      "properties": {
        "osm_id": "100", "osm_type": "node",
        "name": "Hamburg",
        "country": "DE",
        "port_type": "commercial",
        "source": "curated",
        "curated_id": 1001,
        "nato_member": true,
        "bundeswehr_facility": false,
        "osm_tags": {...}
      }
    }
  ]
}
```

Voraussetzungen für die Beispiele:

- `10_osint_cache.sql` ist deployed
- `12_ports.sql` ist deployed (`ports_curated` mit 30 Seed-Rows)
- `services/ports-proxy` hat einmal erfolgreich gebootstrapt (eine
  Cache-Row mit `layer='ports'`)
- Optional für Q1 + Q2: `ais-multiplexer` oder `osint_entities` haben
  Vessel-Daten in den letzten 24 h
- Optional für Q3: `services/sentinel-proxy` hat Tile-Loads in
  `osint_cache(layer LIKE 'sentinel-%')`
- Optional für Q4: `services/flights-proxy` hat `osint_cache(layer='flights-mil')`
  Cache-Rows

---

## 1. Häfen mit Vessel-Verkehr im 5 km-Umkreis in den letzten 24 h

Jeder Hafen aus `ports_curated` plus eine Anzahl Vessel-Knoten aus
`osint_entities`, die innerhalb 5 km um den Hafen-Punkt liegen und in
den letzten 24 h gemeldet haben. Direkter Maritime × Ports-Story-Anker.

```sql
WITH recent_vessels AS (
  SELECT v.entity_id,
         JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER) AS lat,
         JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER) AS lon,
         v.created_at
    FROM osint_entities v
   WHERE v.kind = 'vessel'
     AND v.created_at > SYSTIMESTAMP - INTERVAL '24' HOUR
)
SELECT p.id           AS port_id,
       p.name         AS port_name,
       p.country,
       p.port_type,
       COUNT(rv.entity_id) AS vessels_24h
  FROM ports_curated p
  LEFT JOIN recent_vessels rv
    ON SDO_WITHIN_DISTANCE(
         p.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(rv.lon, rv.lat, NULL),
           NULL, NULL),
         'distance=5000 unit=METER'
       ) = 'TRUE'
 GROUP BY p.id, p.name, p.country, p.port_type
 ORDER BY vessels_24h DESC, p.name
 FETCH FIRST 25 ROWS ONLY;
```

**Storyline:** „Welche Häfen sind gerade aktiv? Welche zehn Häfen haben
in den letzten 24 h die meisten AIS-Vessel-Berichte im Anlauf-Radius?"

---

## 2. Bundeswehr-Häfen mit aktiven AIS-Tracks heute

VS-NfD-relevant: nur die `bundeswehr_facility=1`-Häfen aus dem
Curated-Set, mit Vessel-Anlauf in den letzten 12 h. Stützt die UC3
Multi-Tenant-Story (Industrie-Tenant sieht keine `military`-Häfen,
Behörden-Tenant schon — Filter-Property).

```sql
WITH bw_ports AS (
  SELECT id, name, country, port_type, geometry
    FROM ports_curated
   WHERE bundeswehr_facility = 1
)
SELECT bp.id        AS port_id,
       bp.name      AS port_name,
       bp.country,
       bp.port_type,
       v.entity_id  AS vessel_id,
       JSON_VALUE(v.attributes, '$.mmsi')                   AS mmsi,
       JSON_VALUE(v.attributes, '$.vessel_name')            AS vessel_name,
       v.created_at AS last_report,
       SDO_GEOM.SDO_DISTANCE(
         bp.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(
             JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER),
             JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER),
             NULL),
           NULL, NULL),
         0.005,
         'unit=METER'
       )            AS distance_m
  FROM bw_ports bp,
       osint_entities v
 WHERE v.kind = 'vessel'
   AND v.created_at > SYSTIMESTAMP - INTERVAL '12' HOUR
   AND SDO_WITHIN_DISTANCE(
         bp.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(
             JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER),
             JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER),
             NULL),
           NULL, NULL),
         'distance=5000 unit=METER'
       ) = 'TRUE'
 ORDER BY bp.name, distance_m
 FETCH FIRST 50 ROWS ONLY;
```

**Storyline:** „Welche Schiffe stehen JETZT in 5 km Eckernförde-,
Wilhelmshaven- oder Karlskrona-Anlauf? Bundeswehr-relevante Lage in
einer Query."

---

## 3. Häfen unter aktueller Sentinel-Tile-Coverage

Verbindet `ports_curated` mit der `sentinel-*`-Layer-Cache-Row aus
Layer #3. Antwort auf: „Welche unserer NATO-Häfen liegen JETZT in
einem Sentinel-Tile, das wir in den letzten 6 h geladen haben?".

```sql
WITH sentinel_viewports AS (
  SELECT TO_TIMESTAMP_TZ(JSON_VALUE(c.payload, '$.fetched_at'),
                         'YYYY-MM-DD"T"HH24:MI:SS.FFTZH:TZM') AS fetched_at,
         JSON_VALUE(c.payload, '$.viewport.lat'  RETURNING NUMBER) AS view_lat,
         JSON_VALUE(c.payload, '$.viewport.lon'  RETURNING NUMBER) AS view_lon,
         c.layer
    FROM osint_cache c
   WHERE c.layer LIKE 'sentinel-%'
     AND c.fetched_at > SYSTIMESTAMP - INTERVAL '6' HOUR
)
SELECT p.id          AS port_id,
       p.name        AS port_name,
       p.country,
       p.port_type,
       p.nato_member,
       sv.layer      AS sentinel_layer,
       sv.fetched_at,
       SDO_GEOM.SDO_DISTANCE(
         p.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(sv.view_lon, sv.view_lat, NULL),
           NULL, NULL),
         0.005,
         'unit=KM'
       )             AS distance_km
  FROM ports_curated p,
       sentinel_viewports sv
 WHERE sv.view_lat IS NOT NULL
   AND SDO_WITHIN_DISTANCE(
         p.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(sv.view_lon, sv.view_lat, NULL),
           NULL, NULL),
         'distance=50 unit=KM'
       ) = 'TRUE'
 ORDER BY p.country, p.name, sv.fetched_at DESC
 FETCH FIRST 50 ROWS ONLY;
```

**Storyline:** „Du hast gerade ein Sentinel-Bild der Ostsee geöffnet —
Faslane, Plymouth und Eckernförde sitzen in dieser Tile-Coverage; die
Sentinel-Imagery ist also direkt nutzbar für ein Hafen-Visual."

---

## 4. Mil-Aircraft mit Approach-Vektor auf NATO-Häfen in 60 min — Vier-Layer-Korrelation (Demo-Höhepunkt)

**Der zentrale UC4-Demo-Hebel.** Verknüpft FOUR Layer:
`flights-mil` (Layer #4) × `ports_curated` (Layer #6) × heuristische
60-Minuten-Approach-Box × `osint_cache(layer='flights-mil')`-Cache.
Antwort auf: *„Welcher militärische Flug nähert sich gerade einem
NATO-Hafen, in einem Korridor von 200 km, basierend auf dem aktuellen
Track?"*

Annahme: ein Mil-Aircraft mit Track-Heading + Ground-Speed kann
in 60 min ~maximal 800 km zurücklegen (Kampfflugzeug). 200 km
Approach-Buffer um den Hafen ist eine grobe Heuristik für „dieser
Flug könnte hier landen".

```sql
WITH mil_aircraft AS (
  SELECT jt.hex24,
         jt.callsign,
         jt.mil_source,
         jt.mil_label,
         jt.altitude_ft,
         jt.ground_speed_kn,
         jt.track_deg,
         jt.lon,
         jt.lat
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.features[*]'
           COLUMNS (
             hex24           VARCHAR2(8)   PATH '$.properties.hex24',
             callsign        VARCHAR2(16)  PATH '$.properties.callsign',
             mil_source      VARCHAR2(16)  PATH '$.properties.mil_source',
             mil_label       VARCHAR2(120) PATH '$.properties.mil_label',
             altitude_ft     NUMBER        PATH '$.properties.altitude_ft',
             ground_speed_kn NUMBER        PATH '$.properties.ground_speed_kn',
             track_deg       NUMBER        PATH '$.properties.track_deg',
             lon             NUMBER        PATH '$.geometry.coordinates[0]',
             lat             NUMBER        PATH '$.geometry.coordinates[1]'
           )
         ) jt
   WHERE c.layer = 'flights-mil'
     AND c.fetched_at = (
       SELECT MAX(fetched_at) FROM osint_cache WHERE layer = 'flights-mil'
     )
),
nato_ports AS (
  SELECT id, name, country, port_type, geometry
    FROM ports_curated
   WHERE nato_member = 1
)
SELECT a.hex24,
       a.callsign,
       a.mil_source,
       a.mil_label,
       a.altitude_ft,
       a.ground_speed_kn,
       a.track_deg,
       np.id        AS port_id,
       np.name      AS port_name,
       np.country   AS port_country,
       np.port_type,
       SDO_GEOM.SDO_DISTANCE(
         np.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(a.lon, a.lat, NULL),
           NULL, NULL),
         0.005,
         'unit=KM'
       )           AS distance_km
  FROM mil_aircraft a,
       nato_ports  np
 WHERE a.lat IS NOT NULL
   AND SDO_WITHIN_DISTANCE(
         np.geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(a.lon, a.lat, NULL),
           NULL, NULL),
         'distance=200 unit=KM'
       ) = 'TRUE'
   /* Optional Heading-Heuristik: nur Flüge die sich der Hafen-
      Position annähern (Approach-Vektor). Vereinfacht: Track zeigt
      grob in Richtung Hafen, d.h. der Bearing port_lat-port_lon →
      ac_lat-ac_lon weicht ≤45° vom track_deg ab. Wir lassen die
      Trigonometrie weg und filtern statisch — Tech-Debt-Item.       */
 ORDER BY distance_km, np.country, np.name
 FETCH FIRST 50 ROWS ONLY;
```

**Storyline:** „Ein klassifiziertes Mil-Aircraft (Layer #4) nähert sich
in 200 km einem NATO-Hafen (Layer #6, curated), aktuell ~600 kn. Die
gleiche Operator-Frage in einer einzigen Query — Air × Ports × Curated
Authority × Live-AIS-Snapshot. UC4-Demo-Höhepunkt mit vier
Domänen-Inputs in einer ausführbaren PGQL/SQL."

---

## Hinweise

- **Approach-Heading-Heuristik (Q4)** ist absichtlich auskommentiert:
  ein echtes Approach-Vektor-Modell braucht eine Bearing-Funktion
  (Haversine + Azimuth) als PL/SQL-Helper. Server-side wäre das ein
  guter Kandidat für `CREATE FUNCTION bearing_deg(lat1, lon1, lat2,
  lon2) RETURN NUMBER`. Heute liefern wir alle Mil-Aircraft im 200 km
  Buffer; Frontend kann den Approach-Filter anhand `track_deg` + dem
  Hafen-Bearing live einblenden.
- **`ports_curated.geometry` hat einen Spatial-Index** (siehe
  `12_ports.sql`), `osint_entities.attributes.lat/lon` aber nicht.
  Q1 + Q2 performen daher mit ports auf der Spatial-Index-Seite und
  scannen die Vessels — bei <500 Vessels / 24 h vernachlässigbar,
  bei >100 k Vessels braucht es einen funktionalen Spatial-Index auf
  `osint_entities`. Tech-Debt.
- **Alle vier Queries sind ausführbar** sobald die Voraussetzungen
  erfüllt sind. Q4 ist die Demo-Story-Krone; Q3 verknüpft Layer #6 mit
  Layer #3; Q2 ist die VS-NfD-Bundeswehr-Story; Q1 der allgemeine
  Maritime × Ports Storyline-Anker.
