# GPS Jamming — Demo PGQL & SQL Queries

UC4 OSINT-Korrelation. Die GeoJSON-Polygone aus dem `osint_cache(layer='jamming')`-Blob werden hier mit den existierenden Vessel-, Aircraft- und Event-Knoten aus dem `intel_fusion`-Property-Graph (siehe `db/schema/05_property_graphs.sql`) verbunden. Alle Beispiele setzen voraus, dass:

- `09_vessels_seed.sql` ist gelaufen (8 Demo-Vessels in der Ostsee)
- `10_osint_cache.sql` ist deployed (Tabelle `osint_cache` existiert)
- Der `services/jamming-poller`-Service hat mindestens einmal erfolgreich gefetcht (mind. eine Row mit `layer='jamming'`)

---

## 1. Vessels innerhalb einer Jamming-Zone in den letzten 24 h

Die Jamming-Zone wird als GeoJSON-Polygon im `payload`-JSON gehalten. Wir parsen das in einer Inline-CTE und joinen via `SDO_RELATE` gegen die Vessel-Position aus `osint_entities.attributes`:

```sql
WITH jamming_features AS (
  SELECT jt.h3_index,
         jt.classification_color,
         jt.low_nacp_ratio,
         SDO_GEOMETRY(
           jt.geom_text,
           4326
         ) AS geom_sdo
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.features[*]'
           COLUMNS (
             h3_index             VARCHAR2(20)  PATH '$.properties.h3_index',
             classification_color VARCHAR2(10)  PATH '$.properties.classification_color',
             low_nacp_ratio       NUMBER        PATH '$.properties.low_nacp_ratio',
             geom_text            VARCHAR2(4000) FORMAT JSON PATH '$.geometry'
           )
         ) jt
   WHERE c.layer = 'jamming'
     AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='jamming')
)
SELECT v.entity_id,
       v.canonical_name,
       JSON_VALUE(v.attributes, '$.mmsi') AS mmsi,
       j.h3_index,
       j.classification_color,
       j.low_nacp_ratio
  FROM osint_entities v,
       jamming_features j
 WHERE v.kind = 'vessel'
   AND v.created_at > SYSTIMESTAMP - INTERVAL '24' HOUR
   AND SDO_RELATE(
         SDO_GEOMETRY(
           2001, 4326,
           SDO_POINT_TYPE(
             JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER),
             JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER),
             NULL
           ),
           NULL, NULL
         ),
         j.geom_sdo,
         'mask=ANYINTERACT'
       ) = 'TRUE';
```

**Storyline:** „Welche Schiffe haben in den letzten 24 h einen GPS-Jamming-Korridor durchquert?" — der zentrale UC4-Demo-Hebel („Maritime + EW Fusion").

---

## 2. Top-5 Jamming-Zonen nach Intensität in einer Bbox

Reine SQL gegen den JSON-Blob, kein Property-Graph nötig:

```sql
SELECT *
  FROM (
    SELECT jt.h3_index,
           jt.classification_color,
           jt.aircraft_total,
           jt.aircraft_low_nacp,
           jt.low_nacp_ratio,
           jt.centroid_lat,
           jt.centroid_lon
      FROM osint_cache c,
           JSON_TABLE(c.payload, '$.features[*]'
             COLUMNS (
               h3_index             VARCHAR2(20) PATH '$.properties.h3_index',
               classification_color VARCHAR2(10) PATH '$.properties.classification_color',
               aircraft_total       NUMBER       PATH '$.properties.aircraft_total',
               aircraft_low_nacp    NUMBER       PATH '$.properties.aircraft_low_nacp',
               low_nacp_ratio       NUMBER       PATH '$.properties.low_nacp_ratio',
               centroid_lat         NUMBER       PATH '$.properties.centroid_lat',
               centroid_lon         NUMBER       PATH '$.properties.centroid_lon'
             )
           ) jt
     WHERE c.layer = 'jamming'
       AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='jamming')
       AND jt.centroid_lat BETWEEN :bbox_s AND :bbox_n
       AND jt.centroid_lon BETWEEN :bbox_w AND :bbox_e
     ORDER BY jt.low_nacp_ratio DESC
  )
 WHERE ROWNUM <= 5;
```

**Storyline:** „Wo ist die GPS-Störung gerade am stärksten — und wer fliegt/fährt da rein?"

---

## 3. Cross-domain Korrelation: Jamming-Zone × Civil-Flight-Durchquerung

Setzt voraus, dass `osint_entities.kind='aircraft'` mit Position-JSON gefüllt sind (durch Civil/Mil-Flights-Layer in einer späteren Iteration). Heute liefert die Query ein leeres Resultset — ist aber als Vorbereitung für die Air-EW-Fusion-Story dokumentiert.

```sql
SELECT a.entity_id   AS aircraft_id,
       a.canonical_name,
       JSON_VALUE(a.attributes, '$.icao24') AS icao24,
       j.h3_index,
       j.classification_color
  FROM osint_entities a,
       (SELECT jt.h3_index,
               jt.classification_color,
               SDO_GEOMETRY(jt.geom_text, 4326) AS geom_sdo
          FROM osint_cache c,
               JSON_TABLE(c.payload, '$.features[*]'
                 COLUMNS (
                   h3_index             VARCHAR2(20)  PATH '$.properties.h3_index',
                   classification_color VARCHAR2(10)  PATH '$.properties.classification_color',
                   geom_text            VARCHAR2(4000) FORMAT JSON PATH '$.geometry'
                 )
               ) jt
         WHERE c.layer = 'jamming'
           AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='jamming')
           AND jt.classification_color IN ('amber','red')
       ) j
 WHERE a.kind = 'aircraft'
   AND SDO_RELATE(
         SDO_GEOMETRY(
           2001, 4326,
           SDO_POINT_TYPE(
             JSON_VALUE(a.attributes, '$.lon' RETURNING NUMBER),
             JSON_VALUE(a.attributes, '$.lat' RETURNING NUMBER),
             NULL
           ),
           NULL, NULL
         ),
         j.geom_sdo,
         'mask=ANYINTERACT'
       ) = 'TRUE';
```

**Storyline:** „Civil-Aviation Risk Picture" — die EW-Lage trifft die zivile Luftfahrt sichtbar (Vorbereitung für Air-Domain-Layer in Iteration 3).

---

## Hinweise

- `SDO_RELATE` verlangt einen funktionierenden Spatial-Index. Falls `osint_entities` keinen Spatial-Index auf den JSON-Lat/Lon hat, performt die Query langsam — funktional korrekt, aber für Demo bei <100 Vessels & <500 Hex-Cells noch akzeptabel.
- Die JSON_TABLE-Inline-Form ist absichtlich nicht in einer View materialisiert — der `osint_cache.payload` ist eine atomare Snapshot-Einheit, kein modellierter Property-Graph-Vertex. Eine `intel_fusion`-Erweiterung würde Jamming-Hexes als eigene `kind='jamming_zone'`-Entities materialisieren — Kandidat für eine spätere Iteration.
- `services/osint-fusion` kann diese Queries via einem neuen Router-Endpoint `/api/osint/jamming/correlations` exposen, wenn das Frontend mehr als die rohen Hex-Polygone braucht.
