# Flights — Demo PGQL & SQL Queries

UC4 OSINT-Korrelation für Layer #4 (Flights, Pattern A REST-Poll mit Hybrid-Klassifikator). Der `services/flights-proxy`-Service schreibt pro Tick zwei Cache-Rows nach `osint_cache`:

| Layer            | Inhalt                                                          |
|------------------|-----------------------------------------------------------------|
| `flights-civil`  | GeoJSON FeatureCollection — Aircraft ohne Mil-Match             |
| `flights-mil`    | GeoJSON FeatureCollection — Aircraft mit curated/Mictronics-Match |

Jedes Feature hat dieselben Properties:

```
hex24, callsign, icao_type, registration, altitude_ft,
ground_speed_kn, track_deg, squawk, nac_p, mil_source, mil_label
```

Voraussetzungen für die Beispiele:

- `10_osint_cache.sql` ist deployed (Tabelle `osint_cache` existiert)
- `11_flights_curated.sql` ist deployed (`mil_aircraft_curated`, `mil_aircraft_mictronics`, View `mil_aircraft_unified`)
- `services/flights-proxy` hat mindestens einmal erfolgreich gefetcht (mind. eine Row je Layer)
- Optional für Query #3: `services/jamming-poller` und `services/ais-multiplexer` haben ebenfalls Daten in `osint_cache` bzw. `osint_entities`

---

## 1. Mil-Aircraft im deutschen FIR der letzten 24 h

Reine SQL gegen `osint_cache(layer='flights-mil')` — wir entfalten den Feature-Array per `JSON_TABLE` und filtern grob auf das EDXX/EDMM/EDDF-FIR-Bbox (≈ Deutschland).

```sql
SELECT ft.fetched_at,
       ft.hex24,
       ft.callsign,
       ft.icao_type,
       ft.registration,
       ft.altitude_ft,
       ft.ground_speed_kn,
       ft.mil_source,
       ft.mil_label,
       ft.lon,
       ft.lat
  FROM (
    SELECT c.fetched_at,
           jt.hex24,
           jt.callsign,
           jt.icao_type,
           jt.registration,
           jt.altitude_ft,
           jt.ground_speed_kn,
           jt.mil_source,
           jt.mil_label,
           jt.lon,
           jt.lat
      FROM osint_cache c,
           JSON_TABLE(c.payload, '$.features[*]'
             COLUMNS (
               hex24           VARCHAR2(8)   PATH '$.properties.hex24',
               callsign        VARCHAR2(16)  PATH '$.properties.callsign',
               icao_type       VARCHAR2(8)   PATH '$.properties.icao_type',
               registration    VARCHAR2(16)  PATH '$.properties.registration',
               altitude_ft     NUMBER        PATH '$.properties.altitude_ft',
               ground_speed_kn NUMBER        PATH '$.properties.ground_speed_kn',
               mil_source      VARCHAR2(16)  PATH '$.properties.mil_source',
               mil_label       VARCHAR2(120) PATH '$.properties.mil_label',
               lon             NUMBER        PATH '$.geometry.coordinates[0]',
               lat             NUMBER        PATH '$.geometry.coordinates[1]'
             )
           ) jt
     WHERE c.layer = 'flights-mil'
       AND c.fetched_at > SYSTIMESTAMP - INTERVAL '24' HOUR
  ) ft
 WHERE ft.lat BETWEEN 47.0 AND 55.5
   AND ft.lon BETWEEN  5.5 AND 15.5
 ORDER BY ft.fetched_at DESC, ft.callsign;
```

**Storyline:** „Welche militärischen Flugbewegungen wurden in den letzten 24 h über deutschem Luftraum durch unsere klassifizierte Quelle getragen — und stammt das Match aus dem Bundeswehr-Stamm (`curated`) oder der Community-DB (`mictronics`)?"

---

## 2. Civil ↔ Mil Cross-Check über `mil_aircraft_unified`

Joint die Live-Cache-Snapshots beider Sub-Layer mit der Sovereign-Mil-DB. Liefert pro `hex24` die zuletzt beobachtete Position **und** den autoritativen Mil-Match aus der DB — der Klassifikator-Verdict wird damit direkt nachvollziehbar gemacht.

```sql
WITH latest_civil AS (
  SELECT jt.hex24,
         jt.callsign,
         jt.lon,
         jt.lat,
         c.fetched_at,
         'civil' AS sub_layer
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.features[*]'
           COLUMNS (
             hex24    VARCHAR2(8)  PATH '$.properties.hex24',
             callsign VARCHAR2(16) PATH '$.properties.callsign',
             lon      NUMBER       PATH '$.geometry.coordinates[0]',
             lat      NUMBER       PATH '$.geometry.coordinates[1]'
           )
         ) jt
   WHERE c.layer = 'flights-civil'
     AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='flights-civil')
),
latest_mil AS (
  SELECT jt.hex24,
         jt.callsign,
         jt.lon,
         jt.lat,
         c.fetched_at,
         'mil' AS sub_layer
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.features[*]'
           COLUMNS (
             hex24    VARCHAR2(8)  PATH '$.properties.hex24',
             callsign VARCHAR2(16) PATH '$.properties.callsign',
             lon      NUMBER       PATH '$.geometry.coordinates[0]',
             lat      NUMBER       PATH '$.geometry.coordinates[1]'
           )
         ) jt
   WHERE c.layer = 'flights-mil'
     AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='flights-mil')
),
all_live AS (
  SELECT * FROM latest_civil
  UNION ALL
  SELECT * FROM latest_mil
)
SELECT a.hex24,
       a.callsign,
       a.sub_layer,
       a.lon,
       a.lat,
       u.label  AS mil_label_in_db,
       u.source AS mil_source_in_db,
       CASE
         WHEN a.sub_layer = 'mil' AND u.source IS NULL THEN 'classifier_mismatch'
         WHEN a.sub_layer = 'civil' AND u.source IS NOT NULL THEN 'should_be_mil'
         ELSE 'consistent'
       END AS verdict
  FROM all_live a
  LEFT JOIN mil_aircraft_unified u ON u.hex24 = a.hex24
 ORDER BY verdict, a.sub_layer, a.callsign;
```

**Storyline:** „Wer steht in welchem Sub-Layer und stützt sich der Verdict auf die kuratierte Bundeswehr-Liste oder den Mictronics-Fallback? Plus Drift-Detection: Aircraft, die im Live-Snapshot anders klassifiziert sind als die DB-Beobachtung." Wenn der Hybrid-Klassifikator korrekt arbeitet, sind alle Rows `consistent` — Abweichungen weisen auf Cache-TTL-Effekte oder eine geänderte Stammlage hin.

---

## 3. Triple-Korrelation: Air × EW × Maritime in der Ostsee

**Der zentrale UC4-Demo-Hebel.** Verbindet drei `osint_cache`-Layer in einer einzigen Query: Mil-Aircraft, GPS-Jamming-Zonen, AIS-Vessels. Antwortet auf die Operator-Frage: *„Welche Schiffe in einer aktiven GPS-Jamming-Zone haben gerade militärischen Luftverkehr über sich?"*

Annahme: Ostsee-Bbox (53–60 °N, 8–25 °E), letzter Snapshot pro Layer.

```sql
WITH mil_in_baltic AS (
  SELECT jt.hex24,
         jt.callsign,
         jt.mil_source,
         jt.mil_label,
         jt.altitude_ft,
         jt.lon AS air_lon,
         jt.lat AS air_lat
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.features[*]'
           COLUMNS (
             hex24       VARCHAR2(8)   PATH '$.properties.hex24',
             callsign    VARCHAR2(16)  PATH '$.properties.callsign',
             mil_source  VARCHAR2(16)  PATH '$.properties.mil_source',
             mil_label   VARCHAR2(120) PATH '$.properties.mil_label',
             altitude_ft NUMBER        PATH '$.properties.altitude_ft',
             lon         NUMBER        PATH '$.geometry.coordinates[0]',
             lat         NUMBER        PATH '$.geometry.coordinates[1]'
           )
         ) jt
   WHERE c.layer = 'flights-mil'
     AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='flights-mil')
     AND jt.lat BETWEEN 53 AND 60
     AND jt.lon BETWEEN  8 AND 25
),
hot_jamming AS (
  SELECT jt.h3_index,
         jt.classification_color,
         jt.low_nacp_ratio,
         SDO_GEOMETRY(jt.geom_text, 4326) AS geom_sdo
    FROM osint_cache c,
         JSON_TABLE(c.payload, '$.features[*]'
           COLUMNS (
             h3_index             VARCHAR2(20)   PATH '$.properties.h3_index',
             classification_color VARCHAR2(10)   PATH '$.properties.classification_color',
             low_nacp_ratio       NUMBER         PATH '$.properties.low_nacp_ratio',
             geom_text            VARCHAR2(4000) FORMAT JSON PATH '$.geometry'
           )
         ) jt
   WHERE c.layer = 'jamming'
     AND c.fetched_at = (SELECT MAX(fetched_at) FROM osint_cache WHERE layer='jamming')
     AND jt.classification_color IN ('amber','red')
)
SELECT v.entity_id,
       v.canonical_name,
       JSON_VALUE(v.attributes, '$.mmsi') AS mmsi,
       JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER) AS vessel_lat,
       JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER) AS vessel_lon,
       j.h3_index,
       j.classification_color,
       j.low_nacp_ratio,
       a.callsign       AS mil_callsign,
       a.mil_source     AS mil_source,
       a.mil_label      AS mil_label,
       a.altitude_ft    AS mil_altitude_ft
  FROM osint_entities v,
       hot_jamming    j,
       mil_in_baltic  a
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
       ) = 'TRUE'
   /* Mil-Aircraft innerhalb 1° (~111 km) horizontal vom Vessel —
      grobe „Air Cover"-Heuristik ohne Spatial-Index auf Aircraft-Punkten. */
   AND ABS(a.air_lat - JSON_VALUE(v.attributes, '$.lat' RETURNING NUMBER)) < 1.0
   AND ABS(a.air_lon - JSON_VALUE(v.attributes, '$.lon' RETURNING NUMBER)) < 1.0
 ORDER BY j.classification_color DESC, j.low_nacp_ratio DESC, mmsi;
```

**Storyline:** „Schiff in einer GPS-Stör-Zone der Ostsee, mit klassifiziertem militärischen Luftverkehr direkt darüber — alle drei Layer (`flights-mil`, `jamming`, AIS-Vessel-Knoten) in einer einzigen Korrelation, vollständig sovereign aus dem `osint_cache` plus dem `intel_fusion`-Property-Graph."

---

## Hinweise

- Die Mil-DB (`mil_aircraft_unified`) ist die *Single Source of Truth* für die Klassifikator-Entscheidung. Wenn ein Aircraft im Live-Snapshot in `flights-mil` landet, *muss* `mil_aircraft_unified` einen passenden `hex24` haben — sonst gibt es einen Bug in `app.classifier`. Query #2 macht diesen Drift sichtbar.
- `mil_source = 'curated'` schlägt `mil_source = 'mictronics'` (siehe View-Definition in `11_flights_curated.sql`). Bei einer Demo, in der ein NATO-Flugzeug sowohl in `mil_aircraft_curated` als auch in `mil_aircraft_mictronics` steht, gewinnt die kuratierte Quelle — das macht die Quelle der Klassifikation transparent für die Operator-Story.
- Query #3 nutzt bewusst eine Bbox-Bounding-Heuristik statt eines echten Spatial-Joins zwischen Aircraft und Vessel — Aircraft-Positionen liegen aktuell nur in `osint_cache.payload.features[*]` und nicht in `osint_entities`. Eine spätere Iteration kann die Mil-Aircraft als `kind='aircraft'`-Entities materialisieren und damit `SDO_RELATE` über alle drei Domänen vereinheitlichen.
- Klassifikator-Cache-Größe und Hit-Rate sind über `flights_classifier_lookups` und `flights_classifier_cache_hits` in `/metrics` sichtbar — wichtig, um die DB-Last zu monitoren, da Query #2 *jeden* Aircraft pro Tick klassifiziert.
