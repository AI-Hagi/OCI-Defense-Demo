# Maritime PGQL Demo-Queries (UC4 — OSINT-Fusion)

Diese Queries laufen gegen den Property Graph **`intel_fusion`** (definiert in
`db/schema/05_property_graphs.sql`). Vessel-Entitaeten leben als
`osint_entities`-Rows mit `kind='vessel'` und Attribut-JSON wie
`{mmsi, imo, flag, vessel_name, vessel_type, lat, lon, heading_deg, speed_kn}`
(siehe `db/schema/09_vessels_seed.sql`).

Das LLM-Tool `pgql_query` (Chat-Service, UC4) soll diese Patterns als Templates
nutzen. Alle Queries sind **read-only** und laufen unter dem ORDS-DB-User mit
DICE_POLICY-Auth — `ols_label` wird automatisch via Label Security gefiltert.

> **Konvention**: Wir nutzen `JSON_VALUE(attributes, '$.<key>')` mit
> `RETURNING NUMBER` bzw. `RETURNING VARCHAR2(...)` fuer Type-Safety. SQL/PGQ
> 26ai-Syntax: `GRAPH_TABLE(<graph> MATCH ... COLUMNS (...))`.

---

## Query 1 — Vessels in einer aktuellen Bbox (z.B. Suedl. Ostsee)

Liefert alle aktuell positionierten Vessels mit Lat/Lon innerhalb einer
gegebenen Bounding Box. Pflicht-Filter fuer das Cesium-Frontend, sobald die
Kamera auf die Ostsee zoomt.

```sql
SELECT entity_id,
       canonical_name                                                         AS vessel_name,
       JSON_VALUE(attributes, '$.mmsi'         RETURNING VARCHAR2(20))         AS mmsi,
       JSON_VALUE(attributes, '$.flag'         RETURNING VARCHAR2(3))          AS flag,
       JSON_VALUE(attributes, '$.vessel_type'  RETURNING VARCHAR2(40))         AS vessel_type,
       JSON_VALUE(attributes, '$.lat'          RETURNING NUMBER)               AS lat,
       JSON_VALUE(attributes, '$.lon'          RETURNING NUMBER)               AS lon,
       JSON_VALUE(attributes, '$.speed_kn'     RETURNING NUMBER)               AS speed_kn
  FROM osint_entities
 WHERE kind = 'vessel'
   AND JSON_VALUE(attributes, '$.lat' RETURNING NUMBER) BETWEEN :south AND :north
   AND JSON_VALUE(attributes, '$.lon' RETURNING NUMBER) BETWEEN :west  AND :east
 ORDER BY canonical_name;
```

> Bind-Variablen: `:south, :west, :north, :east`. Ostsee-Default: `53, 8, 56, 22`.

---

## Query 2 — Welche Vessels haben einen Hafen besucht? (`docks_at`)

Property-Graph-Pattern via `GRAPH_TABLE`. Findet alle (Vessel)-[docks_at]->(Location)-Paare,
optional gefiltert nach Country-ISO3 des Hafens.

```sql
SELECT *
  FROM GRAPH_TABLE (
         intel_fusion
         MATCH (v IS entity) -[r IS relates_to]-> (p IS entity)
         WHERE v.kind     = 'vessel'
           AND p.kind     = 'location'
           AND r.rel_type = 'docks_at'
         COLUMNS (
           v.canonical_name AS vessel_name,
           v.entity_id      AS vessel_id,
           p.canonical_name AS port_name,
           p.entity_id      AS port_id,
           r.confidence     AS confidence
         )
       )
 ORDER BY confidence DESC, vessel_name;
```

> Confidence kommt aus `osint_relationships.confidence` (0..1). Demo-Daten:
> `MV Hanse Bremen -> Hafen Kiel`, `M/S Finlandia -> Hafen Tallinn`.

---

## Query 3 — Vessel-Pfade als 1-/2-Hop-Edges (PATH-Query)

Variable-Length-Pattern: jede Entitaet, die in 1 bis 2 Hops von einem Vessel
erreichbar ist. Nuetzlich fuer Lagebild-Kontext ("was haengt an diesem Schiff?").
Identifies clusters of related entities (event, location, organization, etc.).

```sql
SELECT *
  FROM GRAPH_TABLE (
         intel_fusion
         MATCH (v IS entity) -[r1 IS relates_to]-> (m IS entity)
                             -[r2 IS relates_to]-> (n IS entity)
         WHERE v.kind     = 'vessel'
           AND v.entity_id = :vessel_id
         COLUMNS (
           v.canonical_name AS source_vessel,
           r1.rel_type      AS hop1_type,
           m.canonical_name AS hop1_target,
           m.kind           AS hop1_kind,
           r2.rel_type      AS hop2_type,
           n.canonical_name AS hop2_target,
           n.kind           AS hop2_kind
         )
       );
```

> Bind-Variable: `:vessel_id` (z.B. `'VES-211100100'` fuer FGS Sachsen-Anhalt).
> 1-Hop-Variante: einfach das zweite `-[r2]-> (n)` weglassen.

---

## Query 4 — Flag-Cluster ueber MMSI-MID-Range

MMSI-Praefix (erste 3 Ziffern, Maritime Identification Digits) korreliert
1:1 mit dem Flaggenstaat. Diese Query gruppiert Vessels nach MID und zeigt,
welche Flaggen wie viele Schiffe in der Demo-Umgebung haben — und welche
MMSI-Ranges potenziell verdaechtige Klone (gleicher Praefix, gleiche Flagge,
unrealistische geografische Naehe) enthalten.

```sql
SELECT SUBSTR(JSON_VALUE(attributes, '$.mmsi' RETURNING VARCHAR2(20)), 1, 3) AS mid,
       JSON_VALUE(attributes, '$.flag' RETURNING VARCHAR2(3))                AS flag,
       COUNT(*)                                                              AS vessel_count,
       LISTAGG(canonical_name, ', ') WITHIN GROUP (ORDER BY canonical_name)  AS vessels
  FROM osint_entities
 WHERE kind = 'vessel'
 GROUP BY SUBSTR(JSON_VALUE(attributes, '$.mmsi' RETURNING VARCHAR2(20)), 1, 3),
          JSON_VALUE(attributes, '$.flag' RETURNING VARCHAR2(3))
 ORDER BY vessel_count DESC, mid;
```

> Demo-Verteilung: 211 (DEU) hat 3 Schiffe, alle anderen MIDs 1.

---

## Query 5 — Welche Events sind mit einem konkreten Vessel assoziiert?

Findet alle `event`-Knoten, mit denen ein Vessel via beliebiger Edge verbunden ist
(`mentioned_in`, oder zukuenftig `participated_in`, `observed_at`, ...).
Liefert die Story-Bausteine fuer den Chat-Tool-Path "Erklaer mir Schiff X".

```sql
SELECT *
  FROM GRAPH_TABLE (
         intel_fusion
         MATCH (v IS entity) -[r IS relates_to]-> (e IS entity)
         WHERE v.kind     = 'vessel'
           AND v.entity_id = :vessel_id
           AND e.kind     = 'event'
         COLUMNS (
           v.canonical_name AS vessel_name,
           r.rel_type       AS rel_type,
           r.confidence     AS confidence,
           e.entity_id      AS event_id,
           e.canonical_name AS event_summary
         )
       )
 ORDER BY confidence DESC;
```

> Bind-Variable: `:vessel_id` (z.B. `'VES-211100100'`). Demo: liefert
> `Port Call FGS Sachsen-Anhalt @ Warnemuende`.

---

## Hinweise fuer das `pgql_query`-Tool im Chat-Service

- Alle Queries laufen mit `:bind`-Parametern — nie String-Concat aus User-Input.
- `audit_log`-Eintrag: `action='tool_call'`, `resource='pgql_query'`,
  `details={"query_id":"maritime-q1", "binds":{...}}`.
- `classification` der Query-Resultate ist nie hoeher als
  `MAX(ols_label)` der getroffenen Rows — DICE_POLICY filtert vorher.
- Frontend-Rendering: Resultate von Q1 als Cesium-Billboards (siehe
  `frontend/src/layers/maritime.ts`), Q2/Q3/Q5 als Graph-Overlay
  (`frontend/src/layers/graph-fusion.ts`).
