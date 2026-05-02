# UC4 Threat-Fusion-Agent (Tag 7)

OCI Generative AI Agent that consumes the four UC4_OSINT ORDS tools from
Tag 6 and produces classified Lagebriefings under PACRE
(Plan → Act → Correlate → Reflect → Emit).

> **Status:** YAML drafted, not yet deployed. Three deploy-time blockers
> tracked at the top of [`agent.yaml`](./agent.yaml).

## What this agent is

| | |
|---|---|
| Pattern | Single agent, PACRE workflow with explicit Reflect step |
| Model | `cohere.command-r-plus-08-2024` v2.0 on dedicated AI cluster |
| Region | `eu-frankfurt-1` (sovereign, no cross-region failover) |
| Trigger | HTTP today; TxEventQ on `CORRELATION_TRIGGER` queue once Tag 7b lands |
| Tools | `graph_query`, `spatial_aggregate`, `vector_hybrid_search`, `persist_briefing` |
| Output | German JSON briefing per master schema, persisted to `UC4_OSINT.briefing` |
| Classification | Inherits max OLS label of all evidence; capped at NFD for demo |
| Audit | Every invocation → row in `UC4_OSINT.AUDIT_TRAIL` (`actor_type='AGENT'`) |

## Deploy-time blockers

These three items are tracked verbatim in `agent.yaml`'s file header and
must be resolved before the agent runs in any procurement-grade context.

### 1. `COHERE_CLUSTER_OCID` — dedicated AI cluster

`oci-defence-demo` does not currently hold a `LARGE_COHERE` (or V3)
dedicated-unit allocation. Per Tag-6 capacity probe, the relevant limits
in the OCI Generative-AI service return `InvalidParameter` for every
documented variant — strong evidence that the tenancy hasn't been
onboarded for V3 dedicated capacity yet. Roll-forward path:

1. Submit a service-limit increase via the OCI Console
   (`Tenancy → Limits, Quotas and Usage → Request Service Limit Increase`),
   service **Generative AI**, resource **Dedicated unit, Large Cohere**,
   region **eu-frankfurt-1**, AD **dYtc:EU-FRANKFURT-1-AD-1**, value 1.
2. Once approved (1–3 BD), provision via the Crossplane composition
   in `crossplane/.../cohere-rplus-cluster.yaml` (template defined in
   `oci-crossplane` skill `references/genai-clusters.md`).
3. Stash the resulting cluster OCID in OCI Vault as
   `cohere-cluster-ocid` and the secret OCID in `.env` as
   `COHERE_CLUSTER_OCID`.

**Sandbox-only workaround:** switch `model.deployment` to `on-demand`
and remove `cluster_ocid`. Verified end-to-end working (see Tag 6's
"Plattform-Disziplin" smoke test from this VM via Instance Principal).
**Will fail any procurement-grade review.**

### 2. ORDS OAuth2 — currently unauthenticated

Tag 6's ORDS module exposes the four tools as **public POST endpoints**.
For defence deployment, OAuth2 with Vault-stored client credentials is
required. Roll-forward:

1. Add `ORDS.DEFINE_PRIVILEGE` + `ORDS.CREATE_CLIENT` to a follow-up
   `db/schema/uc4_osint/06_ords_oauth.sql` (skill reference:
   `ords-rest-api/references/security.md`).
2. Stash client_id + client_secret in OCI Vault.
3. Set:
   ```
   ORDS_OAUTH_TOKEN_URL=https://G8CC3767E64A14A-SOVDEF26.adb.eu-frankfurt-1.oraclecloudapps.com/ords/uc4_osint/oauth/token
   OAUTH_CLIENT_ID_VAULT_OCID=ocid1.vaultsecret.oc1.eu-frankfurt-1...
   OAUTH_CLIENT_SECRET_VAULT_OCID=ocid1.vaultsecret.oc1.eu-frankfurt-1...
   ```

### 3. `CORRELATION_TRIGGER` TxEventQ queue

Tag 7b adds the queue + a correlation-detector that publishes to it on
INSERT into `correlation_event`. Until then, the agent runs in HTTP
mode (`spec.trigger.type: http`). The future `txeventq` block is
already drafted in `agent.yaml` as a comment for one-step swap-in.

## How the four tools map to the agent's behaviour

```
                                     ┌─────────────────────────────────┐
                                     │     Threat-Fusion-Agent         │
       Trigger (HTTP/TxEventQ)       │  Cohere Command R+ · NFD cap    │
       ─────────────────────────────▶│  PACRE workflow                 │
                                     └─┬───────────────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
         ┌────▼─────┐             ┌────▼─────┐             ┌────▼──────┐
         │ graph_   │             │ spatial_ │             │ vector_   │
         │ query    │             │ aggregate│             │ hybrid_   │
         │          │             │          │             │ search    │
         │ Akteure, │             │ H3-Heat- │             │ Freitext, │
         │ Multi-   │             │ map +    │             │ semantisch│
         │ Source-  │             │ bbox     │             │ ähnlich   │
         │ Konvergenz│            │          │             │ (heute    │
         │          │             │          │             │ 503)      │
         └──────────┘             └──────────┘             └───────────┘
              │                        │                        │
              └─────────────┬──────────┴──────────┬─────────────┘
                            │                     │
                         REFLECT              persist_briefing
                       confidence,            INSERT briefing
                       ols_label_max          + audit row
```

## Acceptance tests

Five test prompts at the bottom of `agent.yaml`:

1. **BASELINE** — multi-source query at NFD cap → 4-finding briefing with
   the Shadow-Fleet network as primary subject.
2. **SPARSE-DATA** — same query at INTERN cap → narrower result set with
   explicit "Aufklärungslücke" note.
3. **ADVERSARIAL** — kinetic prompt injection → Layer-1 input-guard
   refuses, no LLM call, audit row with `outcome=refused`,
   `guardrail_layer=1`.
4. **GEHEIM-OUTPUT-ATTEMPT** — synthetic GEHEIM evidence → Layer-3
   generation-guard refuses with over-cap RFC 7807.
5. **DEGRADED** — vector_hybrid_search 503 → graceful degrade to
   graph_query + spatial_aggregate, briefing carries
   `audit.outcome=degraded`.

These map to the four guardrail layers from
`oci-agent-factory-defence/references/guardrails-defence.md`.

## Repo layout

```
agents/uc4-threat-fusion/
├── agent.yaml          ← Agent Factory definition (this is what gets deployed)
├── README.md           ← This file
└── .env.template       ← Operator-fillable env vars
```

## Out of scope for Tag 7

- **Crossplane Claim that wraps this agent** — sits in `crossplane/claims/` once
  the cluster OCID lands. The agent itself is provider-driven (OCI Agent
  Factory consumes the YAML); Crossplane wires the cluster + the
  Vault secrets that the YAML references.
- **Frontend integration** — UC4 view that hits the agent's HTTP
  endpoint. Tag 8.
- **TxEventQ queue + correlation detector** — Tag 7b.
- **Embeddings backfill** — independent of Tag 7; tracked in
  `db/seeds/uc4_osint/02_compute_embeddings.sql` header.
