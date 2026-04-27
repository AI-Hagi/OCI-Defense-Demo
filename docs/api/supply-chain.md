# Supply Chain API

Source: `services/supply-chain/app/routers/sc.py`. Use case 5
("Rüstungs-Lieferketten & Risk Scoring") per `CLAUDE_DEV9.md`.

## `GET /api/sc/nodes`

List all `supply_nodes` for the tenant. Each row carries the latest
risk score from the rolling daily aggregate.

Response `200 OK`:

```json
[
  {
    "node_id": "N001",
    "node_type": "mine",
    "display_name": "Kiruna",
    "country_iso3": "SWE",
    "latitude": 67.85,
    "longitude": 20.22,
    "criticality": 0.9,
    "ols_label": 20,
    "latest_risk_score": 0.42
  }
]
```

`node_type` ∈ `mine | port | factory | distribution | warehouse | hub`.

## `GET /api/sc/edges`

List all `supply_edges` for the tenant.

Response `200 OK`:

```json
[
  {
    "edge_id": "EDG1",
    "src_node": "N001",
    "dst_node": "N002",
    "edge_type": "ships_to",
    "lead_time_days": 7,
    "dependency_level": 0.6,
    "ols_label": 20
  }
]
```

## `GET /api/sc/risk/{node_id}`

Return the historical risk timeline for a node.

Response `200 OK`:

```json
[
  { "as_of": "2026-04-01", "risk_score": 0.33,
    "risk_breakdown": { "geo": 0.2 } },
  { "as_of": "2026-04-15", "risk_score": 0.42,
    "risk_breakdown": { "geo": 0.3 } }
]
```

Errors: `404` if `node_id` does not exist or is OLS-filtered out.
