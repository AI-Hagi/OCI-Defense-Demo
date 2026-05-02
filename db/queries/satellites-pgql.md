# Satellites — Demo PGQL & SQL Queries

UC4 OSINT-Korrelation für Layer #5 (Satellites, Pattern A REST-Poll mit
clientseitiger Bahnpropagation). Der `services/tle-proxy`-Service schreibt
alle `TLE_REFRESH_HOURS` (default 6 h) drei `osint_cache`-Rows:

| Layer                  | Inhalt (CelesTrak GROUP)                              |
|------------------------|-------------------------------------------------------|
| `satellites-stations`  | Bemannte Raumstationen + assoziierte Module (~6 TLE)  |
| `satellites-resource`  | Earth-Observation (Sentinel/Landsat/RADARSAT, ~160)   |
| `satellites-active`    | Voller Operativ-Katalog (~10–15k TLE)                 |

Jede Cache-Row enthält:

```json
{
  "type": "TleCollection",
  "group": "stations",
  "tle": [{"name": "...", "norad_id": "25544", "line1": "1 ...", "line2": "2 ..."}],
  "count": 6,
  "source": "CelesTrak NORAD GP catalog"
}
```

> **Wichtig:** Die TLE-Daten in `osint_cache` sind die *Bahnelemente*, nicht
> Live-Positionen. Die Frontend-Layer rechnen pro Sekunde via `satellite.js`
> (SGP4) die aktuellen Lat/Lon/Alt. Die folgenden Server-seitigen Queries
> arbeiten daher mit `JSON_TABLE` über die TLE-Liste plus PL/SQL-
> Hilfsfunktionen für eine *grobe* Visibility-Heuristik (Sub-Satellite-
> Point + Sichtkegel-Radius). Für sub-Sekunden-Genauigkeit ist die Frontend-
> Propagation die Quelle der Wahrheit.

Voraussetzungen für die Beispiele:
- `10_osint_cache.sql` ist deployed
- `services/tle-proxy` hat mindestens einmal erfolgreich gefetcht (eine
  Row je Layer)
- Optional: für Q2 + Q3 muss `services/jamming-poller` und/oder
  `services/ais-multiplexer` ebenfalls Daten geliefert haben

---

## 1. Satelliten in 90 km „Funkkontakt-Sichtweite" eines Vessels

Die Story: ein Operator klickt auf ein AIS-Vessel (Layer Maritime AIS)
und fragt: „welche Satelliten haben dieses Schiff gerade über sich?".

Die *exakte* Antwort braucht SGP4 — die folgenden Queries reichen für die
Demo: wir nehmen den Sub-Satellite-Point (Lon, Lat = Geländezentrum unter
dem Satelliten) als Annäherung und verwenden 90 km horizontalen Abstand
als „Sichtbarkeitsfenster" für eine LEO-Mission im Mittel. Der Frontend-
Code liefert die SGP4-Position; das Backend dient hier nur als
Korrelations-View.

```sql
WITH all_satellites AS (
  SELECT jt.norad_id,
         jt.name,
         jt.line1,
         jt.line2,
         c.layer
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.tle[*]'
           COLUMNS (
             norad_id VARCHAR2(8)  PATH '$.norad_id',
             name     VARCHAR2(80) PATH '$.name',
             line1    VARCHAR2(80) PATH '$.line1',
             line2    VARCHAR2(80) PATH '$.line2'
           )
         ) jt
   WHERE c.layer LIKE 'satellites-%'
     AND c.fetched_at = (
       SELECT MAX(fetched_at) FROM osint_cache c2
        WHERE c2.layer = c.layer
     )
)
SELECT v.entity_id  AS vessel_id,
       v.canonical_name,
       JSON_VALUE(v.attributes, '$.mmsi')                          AS mmsi,
       JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER)          AS vessel_lat,
       JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER)          AS vessel_lon,
       s.norad_id, s.name, s.layer
  FROM osint_entities v,
       all_satellites s
 WHERE v.kind = 'vessel'
   AND v.created_at > SYSTIMESTAMP - INTERVAL '6' HOUR
   /*
    * Demo-Heuristik: ohne SGP4-Server-Side-Funktion können wir den
    * exakten Sub-Satellite-Point hier nicht ausrechnen. Wir liefern
    * nur ALLE bekannten LEO-Satelliten zurück; das Frontend filtert
    * mit der Live-Position auf <90 km Distanz. Für eine Server-Only-
    * Lösung müsste man eine PL/SQL-Funktion `sgp4(line1, line2, ts)`
    * ergänzen — Tech-Debt-Item.
    */
 ORDER BY v.entity_id, s.norad_id
 FETCH FIRST 200 ROWS ONLY;
```

**Storyline:** Frontend rendert das Vessel; Operator klickt; UI zeigt
die Liste der Satelliten, die innerhalb des nächsten Pass-Fensters
über dem Schiff stehen werden. „Welcher Satellit hat dieses Schiff
in den letzten 90 Sekunden im Sichtfeld?".

---

## 2. Earth-Observation-Satelliten im 24 h Overpass über Bornholm-Bbox

Die direkte Anbindung an Layer #3 (Sentinel-Imagery): „welche
Satelliten haben in den letzten 24 h ein Bornholm-Tile aufgenommen?".

```sql
WITH eo_sats AS (
  SELECT jt.norad_id,
         jt.name,
         jt.line1,
         jt.line2
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.tle[*]'
           COLUMNS (
             norad_id VARCHAR2(8)  PATH '$.norad_id',
             name     VARCHAR2(80) PATH '$.name',
             line1    VARCHAR2(80) PATH '$.line1',
             line2    VARCHAR2(80) PATH '$.line2'
           )
         ) jt
   WHERE c.layer = 'satellites-resource'
     AND c.fetched_at = (
       SELECT MAX(fetched_at) FROM osint_cache WHERE layer='satellites-resource'
     )
),
sentinel_tiles AS (
  SELECT TO_TIMESTAMP_TZ(JSON_VALUE(c.payload, '$.fetched_at'),
                         'YYYY-MM-DD"T"HH24:MI:SS.FFTZH:TZM') AS fetched_at,
         JSON_VALUE(c.payload, '$.viewport.lat'  RETURNING NUMBER) AS view_lat,
         JSON_VALUE(c.payload, '$.viewport.lon'  RETURNING NUMBER) AS view_lon
    FROM osint_cache c
   WHERE c.layer LIKE 'sentinel-%'
     AND c.fetched_at > SYSTIMESTAMP - INTERVAL '24' HOUR
)
SELECT eo.norad_id,
       eo.name,
       COUNT(t.fetched_at) AS sentinel_tile_loads_24h,
       MIN(t.fetched_at)   AS earliest_overlap,
       MAX(t.fetched_at)   AS latest_overlap
  FROM eo_sats eo
  LEFT JOIN sentinel_tiles t
    ON t.view_lat BETWEEN 54.5 AND 55.5    -- Bornholm bbox lat
   AND t.view_lon BETWEEN 14.5 AND 15.5    -- Bornholm bbox lon
 GROUP BY eo.norad_id, eo.name
 ORDER BY sentinel_tile_loads_24h DESC, eo.name
 FETCH FIRST 25 ROWS ONLY;
```

**Storyline:** „Du siehst gerade ein Sentinel-Bild der Ostsee — diese
N Earth-Observation-Satelliten waren in den letzten 24 h wahrscheinlich
überflog für genau dieses Gebiet." (Vereinfachte Heuristik —
tatsächlicher Overpass-Match braucht Server-side SGP4.)

---

## 3. Triple-Korrelation: Satellite × Sentinel-Imagery × Maritime-Vessel — UC4-Höhepunkt

**Der zentrale Demo-Hebel.** Verknüpft drei Domänen für eine einzige
Operator-Frage: *„Welche Schiffe sind in einer Region, die JETZT von
einem Earth-Observation-Satelliten überflogen wird UND für die wir
Sentinel-Bilder aus den letzten 6 h haben?"*.

Wir binden die drei Layer-Caches sowie den `osint_entities`-
Property-Graph zusammen mit einer geometrischen `SDO_RELATE`-Logik:

```sql
WITH eo_sats AS (
  /* 25 EO-Satelliten mit aktueller Approximation des Sub-Satellite-Points
     — Approximation = Berechnung übernimmt Frontend; hier nur Metadaten. */
  SELECT jt.norad_id,
         jt.name,
         /*
          * Demo-Approximation: wir nehmen die letzte bekannte Tile-Position
          * der Sentinel-Tile-Caches als „Sub-Satellite-Point" (das ist die
          * Bbox-Mitte des aktuellen Frontend-Viewports — gut genug für die
          * Demo-Story, kein echter Bahn-Footprint).
          */
         (SELECT JSON_VALUE(c2.payload, '$.viewport.lat' RETURNING NUMBER)
            FROM osint_cache c2
           WHERE c2.layer LIKE 'sentinel-%'
             AND c2.fetched_at > SYSTIMESTAMP - INTERVAL '6' HOUR
             AND ROWNUM = 1) AS approx_lat,
         (SELECT JSON_VALUE(c2.payload, '$.viewport.lon' RETURNING NUMBER)
            FROM osint_cache c2
           WHERE c2.layer LIKE 'sentinel-%'
             AND c2.fetched_at > SYSTIMESTAMP - INTERVAL '6' HOUR
             AND ROWNUM = 1) AS approx_lon
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.tle[*]'
           COLUMNS (
             norad_id VARCHAR2(8)  PATH '$.norad_id',
             name     VARCHAR2(80) PATH '$.name'
           )
         ) jt
   WHERE c.layer = 'satellites-resource'
     AND c.fetched_at = (
       SELECT MAX(fetched_at) FROM osint_cache WHERE layer='satellites-resource'
     )
   FETCH FIRST 25 ROWS ONLY
)
SELECT v.entity_id,
       v.canonical_name,
       JSON_VALUE(v.attributes, '$.mmsi')                  AS mmsi,
       JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER)  AS vessel_lat,
       JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER)  AS vessel_lon,
       s.norad_id,
       s.name                                              AS satellite_name,
       SDO_GEOM.SDO_DISTANCE(
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(
             JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER),
             JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER),
             NULL),
           NULL, NULL),
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(s.approx_lon, s.approx_lat, NULL),
           NULL, NULL),
         0.005,                       -- 5 m tolerance for SDO_GEOM
         'unit=KM'
       )                                                   AS approx_distance_km
  FROM osint_entities v,
       eo_sats s
 WHERE v.kind = 'vessel'
   AND v.created_at > SYSTIMESTAMP - INTERVAL '24' HOUR
   AND s.approx_lat IS NOT NULL
   AND SDO_RELATE(
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(
             JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER),
             JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER),
             NULL),
           NULL, NULL),
         /* Sichtkegel-Approximation: 90 km Buffer um den letzten
            bekannten Sub-Satellite-Point (Sentinel-Viewport-Mitte). */
         SDO_GEOM.SDO_BUFFER(
           SDO_GEOMETRY(2001, 4326,
             SDO_POINT_TYPE(s.approx_lon, s.approx_lat, NULL),
             NULL, NULL),
           90,
           0.005,
           'unit=KM'
         ),
         'mask=ANYINTERACT'
       ) = 'TRUE'
 ORDER BY approx_distance_km, v.entity_id
 FETCH FIRST 50 ROWS ONLY;
```

**Storyline:** „Ostsee-Schiff in einem aktiven Sentinel-Tile, mit einem
Earth-Observation-Satelliten innerhalb 90 km — alle drei Layer
(`satellites-resource`, `sentinel-*`, AIS-Vessel-Knoten) in einer
einzigen Korrelation, vollständig sovereign aus dem `osint_cache`
plus dem `intel_fusion`-Property-Graph". UC4-Demo-Climax.

---

## Hinweise

- **Server-seitige SGP4-Funktion** wäre die saubere Lösung für exakte
  Sub-Satellite-Points. Heute kompensieren wir mit der Sentinel-Tile-
  Viewport-Mitte als grobem Anker. Tech-Debt-Item für eine spätere
  Iteration: `CREATE FUNCTION sgp4_position(line1, line2, ts) RETURN
  SDO_GEOMETRY` (PL/SQL + JNI oder als Java-stored-procedure).
- **TLE-Cache-Pruning** fehlt: 3 Rows alle 6 h × 365 Tage = ~4400 Rows
  mit aktuell ~50 KB pro `active`-Payload ≈ 220 MB/Jahr. Für die Demo
  vernachlässigbar; eine TTL-DELETE wäre hygienisch.
- **Geilenkirchen-Visibility-Window** (NATO AWACS-Standort, 50.96°N
  6.04°E) wird im Frontend gerendert — sobald ISS oder Tiangong
  innerhalb 90 km Sichtfeld sind, blinkt das Stations-Billboard. Server-
  side wäre dieselbe Logik wie Q1; siehe Frontend
  `frontend/src/layers/satellites-stations.ts` → Pflicht-Demo-Anker für
  den 3-Minuten-Storyline.
