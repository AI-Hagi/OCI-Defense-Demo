# Sentinel-2 Imagery — Demo SQL/PGQL queries

UC4 OSINT-Korrelation. Die Sentinel-Tiles werden NICHT in 26ai persistiert (Browser-Cache reicht — siehe `services/sentinel-proxy/README.md`), aber die `audit_events`-Rows tragen pro Tile-Batch Metadaten, die mit den existierenden vessel/aircraft/event-Knoten aus dem `intel_fusion`-Property-Graph (`db/schema/05_property_graphs.sql`) korrelierbar sind.

Die Queries unten zeigen den **Maritime × Imagery**-Hebel, der die UC4-Demo-Story-3 trägt: „Live-Satellitenbild über AIS-Schiffsbewegungen".

Voraussetzungen:
- `09_vessels_seed.sql` ist gelaufen (8 Demo-Vessels in der Ostsee, inkl. Bornholm-Bbox-Region)
- `services/sentinel-proxy` hat mindestens einen Tile-Batch in `audit_events` geschrieben (`actor_service='sentinel-proxy'`, `action='tile_fetch_batch'`)

---

## 1. Vessels innerhalb der zuletzt geladenen Sentinel-Tiles

Die `audit_events.payload` einer Tile-Batch-Row enthält die Layer-Liste und Zoom-Bandbreite. Wir können daraus keine Bbox direkt ableiten (XYZ-Tile-Indizes sind nicht in der Row), aber wir kennen den **Default-Bbox des Demo** (Bornholm via `SENTINEL_BBOX_DEFAULT`). Diese Query nutzt diesen Default als Filterkriterium.

```sql
WITH bornholm_bbox AS (
  -- Bornholm default (matches services/sentinel-proxy/app/settings.py:
  --                  SENTINEL_BBOX_DEFAULT=55.0,14.7,55.3,15.2)
  SELECT 55.0 AS s, 14.7 AS w, 55.3 AS n, 15.2 AS e FROM dual
),
recent_sentinel_activity AS (
  SELECT MAX(event_time) AS last_seen
    FROM audit_events
   WHERE actor_service = 'sentinel-proxy'
     AND action = 'tile_fetch_batch'
     AND event_time > SYSTIMESTAMP - INTERVAL '1' HOUR
)
SELECT v.entity_id,
       v.canonical_name,
       JSON_VALUE(v.attributes, '$.mmsi') AS mmsi,
       JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER) AS lat,
       JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER) AS lon,
       (SELECT last_seen FROM recent_sentinel_activity) AS sentinel_active_since
  FROM osint_entities v,
       bornholm_bbox b
 WHERE v.kind = 'vessel'
   AND JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER) BETWEEN b.s AND b.n
   AND JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER) BETWEEN b.w AND b.e
 ORDER BY v.canonical_name;
```

**Storyline:** „Welche Schiffe waren im Sentinel-Tile-Bereich, während die Operatorin die Imagery aktiv hatte?" — der visuelle Vergleich „Sat-Bild + AIS-Track" wird damit auch in der Audit-Spur korrelierbar.

---

## 2. Hafenstandorte mit Sentinel-Coverage und Vessel-Verkehr im 5km-Umkreis

```sql
WITH ports AS (
  SELECT entity_id,
         canonical_name,
         JSON_VALUE(attributes, '$.lat' RETURNING NUMBER) AS lat,
         JSON_VALUE(attributes, '$.lon' RETURNING NUMBER) AS lon
    FROM osint_entities
   WHERE kind = 'location'
     AND JSON_VALUE(attributes, '$.location_type') = 'port'
),
vessels_near_ports AS (
  SELECT p.canonical_name AS port_name,
         p.lat AS port_lat,
         p.lon AS port_lon,
         COUNT(v.entity_id) AS vessel_count_5km
    FROM ports p,
         osint_entities v
   WHERE v.kind = 'vessel'
     AND SDO_WITHIN_DISTANCE(
           SDO_GEOMETRY(2001, 4326,
             SDO_POINT_TYPE(
               JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER),
               JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER),
               NULL),
             NULL, NULL),
           SDO_GEOMETRY(2001, 4326,
             SDO_POINT_TYPE(p.lon, p.lat, NULL),
             NULL, NULL),
           'distance=5 unit=km'
         ) = 'TRUE'
   GROUP BY p.canonical_name, p.lat, p.lon
)
SELECT port_name,
       vessel_count_5km,
       CASE
         WHEN port_lat BETWEEN 55.0 AND 55.3
          AND port_lon BETWEEN 14.7 AND 15.2
         THEN 'covered_by_sentinel_default'
         ELSE 'outside_sentinel_default'
       END AS sentinel_coverage
  FROM vessels_near_ports
 ORDER BY vessel_count_5km DESC;
```

**Storyline:** „Hafen-Aktivitäts-Score mit Sentinel-Visualisierung" — Häfen mit hohem AIS-Verkehr in der Sentinel-Default-Bbox sind die ersten Demo-Anker (Bornholm Rønne, Kiel-Förde-Eingang etc.).

---

## 3. Demo-Storyboard-Generator: Letzte Sentinel-Audit-Batches mit Default-Layer

```sql
SELECT event_time,
       JSON_VALUE(payload, '$.tile_count' RETURNING NUMBER) AS tile_count,
       JSON_VALUE(payload, '$.z_min' RETURNING NUMBER)      AS z_min,
       JSON_VALUE(payload, '$.z_max' RETURNING NUMBER)      AS z_max,
       JSON_QUERY(payload, '$.layers')                       AS layers_used
  FROM audit_events
 WHERE actor_service = 'sentinel-proxy'
   AND action = 'tile_fetch_batch'
   AND event_time > SYSTIMESTAMP - INTERVAL '24' HOUR
 ORDER BY event_time DESC
 FETCH FIRST 10 ROWS ONLY;
```

**Storyline:** Storyboard-Hilfe — wann wurden welche Sentinel-Layer wie oft mit welcher Zoom-Stufe gefetcht. Hilft beim Demo-Run, den Operator-Pfad nachzuvollziehen.

---

## Hinweise

- Sentinel-Tiles selbst werden NICHT in `osint_cache` persistiert. Die einzige Spur in 26ai ist die batched `audit_events`-Row.
- Die `tile_count`/`z_min`/`z_max`-Felder im Audit-Payload sind ausreichend für Compliance (NIS2: Wer hat wann auf welche Klassifikation zugegriffen) und Demo-Storytelling, aber nicht für eine vollständige geometrische Rekonstruktion der angesehenen Bbox. Falls eine echte Bbox-Spur gebraucht wird: das Tile-Math in `services/sentinel-proxy/app/tile_math.py` wandelt `(z, x, y)` in eine 3857-Bbox um — das müsste serverseitig vor dem Audit-Insert passieren.
- Die `bornholm_bbox`-CTE in Query #1 ist absichtlich hartcodiert auf den Default — eine echte Plattform-Lösung würde den Wert aus der ConfigMap (`SENTINEL_BBOX_DEFAULT`) lesen, nicht aus dem SQL.
