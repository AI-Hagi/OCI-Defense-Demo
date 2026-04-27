# OSINT Fusion API

Source: `services/osint-fusion/app/routers/graph.py`. Use case 4
("OSINT & EMS-Lagebildfusion") per `CLAUDE_DEV9.md`.

## `GET /api/osint/entities`

Prefix search over `osint_entities.canonical_name`. Optional `kind`
filter for the UC4 EMS overlay.

| Query param | Type | Notes |
|---|---|---|
| `q` | string (required) | prefix to match (case-insensitive) |
| `kind` | string | one of `osint_entities.kind` enum (e.g. `actor`, `malware`, `ems_emission`) |

Response `200 OK`:

```json
[
  {
    "entity_id": "E-EMS-001",
    "canonical_name": "S-Band Search Radar (3 GHz)",
    "kind": "ems_emission",
    "attributes": { "frequency_mhz": 3000, "modulation": "pulse" }
  }
]
```

## `GET /api/osint/ems/clusters`

UC4 — bucket EMS emitters by reported `frequency_mhz`.

| Query param | Type | Default | Notes |
|---|---|---|---|
| `band_mhz_step` | number | `50` | bucket width in MHz (1..10000) |

Response `200 OK`:

```json
[
  { "bucket_mhz_start": 3000.0, "bucket_mhz_end": 3050.0,
    "emitter_count": 4, "sample_entity_id": "E-EMS-001" }
]
```

Buckets with zero rows are omitted. Sample entity is the lex-min
`entity_id` for drill-down.

## `POST /api/osint/query-graph`

One-hop expansion of the `intel_fusion` property graph from a start
entity, used by the d3 force layout in `OsintView`.

Request:

```json
{ "startEntity": "E100", "maxHops": 2 }
```

`maxHops` is reserved for future server-side breadth-first
expansion; today the endpoint always returns a single hop and the
client expands iteratively.

Response `200 OK`:

```json
{
  "nodes": [
    { "id": "E100", "name": "Fancy Bear", "kind": "actor" },
    { "id": "E101", "name": "X-Agent", "kind": "malware" }
  ],
  "edges": [
    { "source": "E100", "target": "E101", "rel_type": "uses",
      "confidence": 0.8 }
  ],
  "maxHops": 2
}
```

Errors: `400` if `startEntity` is empty; `422` on body validation.
