---
name: defence-industrial-uc
description: "Wayflow / Open Agent Spec templates plus ADB 26ai bootstrap for three industrial-defence use cases (Engineering Knowledge, Quality Incident Analysis, Software Assurance). Use when extending the Sovereign Defence Intelligence Platform demo to cover Defence Contractor and Beschaffung audiences. Each UC ships a SQL bootstrap (5-step methodology), an Open Agent Spec YAML, optional MCP/OpenAPI tool stubs, and a demo script. Companion to oracle-26ai-schema, oci-crossplane, ords-rest-api skills."
version: 0.1.0
target_platform: Oracle AI Database 26ai + Private Agent Factory 25.3+
---

# Defence Industrial Use Case Templates

Three sovereign-grade Wayflow agents that complement the existing six intelligence-focused use cases:

| # | Agent | Audience | Key ADB Feature |
|---|---|---|---|
| 01 | Engineering Knowledge Assistant | Rüstungsindustrie / Defence Contractors | AI Vector Search + Select AI RAG |
| 02 | Quality & Incident Analysis Agent | Manufacturing / Quality Engineering | Vector clustering + ML anomaly detection |
| 03 | Software Assurance Assistant | Software-driven programs (FCAS, NNbS) | Property Graph + traceability |

## Methodology

All three agents follow the canonical 5-step methodology from the Oracle AI on Live Data pattern:

1. **Federate Data** — `DBMS_CLOUD.CREATE_CREDENTIAL` + `DBMS_CLOUD_ADMIN.CREATE_DATABASE_LINK` for heterogeneous sources; External Tables on OCI Object Storage for unstructured files.
2. **Augment Performance** — Materialized Views with `REFRESH COMPLETE NEXT SYSDATE + n/24` for federated sources where staleness is acceptable.
3. **Augment Metadata** — `COMMENT ON` plus 26ai Data Annotations for semantic precision on engineering vocabulary.
4. **Augment Security** — VPD with `coalition_ctx` Application Context (clearance_level, nation_code, releasability) — fail-closed by default.
5. **Create AI Workload** — Select AI profile + RAG pipeline + Wayflow agent definition + tool registration.

## Hard Rules (do not deviate)

- **ADB version: 26ai only.** Never 23ai or 23c, regardless of legacy Oracle docs.
- **Region parameterized via `.env`.** Default `OCI_REGION=eu-frankfurt-1`. No hardcoded regions in any SQL or YAML.
- **Compartment: `oci-defence-demo`.**
- **Coalition VPD on every agent-readable view.** Fail-closed if `coalition_ctx` is unset.
- **LLM: OCI GenAI in EU region as default; Private AI Services Container as fallback for VS-NfD workloads.** No public OpenAI/Anthropic endpoints in agent specs (only listed as commented-out alternatives for non-classified demos).

## Directory Layout

```
defence-industrial-uc/
├── SKILL.md                              # this file
├── _shared/
│   ├── env.example                       # OCI_REGION, COMPARTMENT_OCID, etc.
│   ├── coalition_ctx_bootstrap.sql       # shared App Context + VPD policy template
│   └── ai_profile_template.sql           # Select AI profile for OCI GenAI EU
├── 01-engineering-knowledge/
│   ├── schema/0[1-5]_*.sql               # 5-step methodology SQL
│   ├── agent/engineering-knowledge.agent.yaml
│   └── demo/demo-script.md
├── 02-quality-incident/
│   └── ... (same layout)
└── 03-software-assurance/
    └── ... (same layout)
```

## Deployment Order

For each UC:

```bash
# 1. Set env
source _shared/env.example  # edit first!

# 2. Bootstrap shared layer (once per ADB)
sql -l defence_admin/$DB_PWD@$DB_TNS @_shared/coalition_ctx_bootstrap.sql
sql -l defence_admin/$DB_PWD@$DB_TNS @_shared/ai_profile_template.sql

# 3. Run UC schema (in order 01..05)
for f in 01-engineering-knowledge/schema/0*.sql; do
  sql -l defence_admin/$DB_PWD@$DB_TNS @"$f"
done

# 4. Import the agent spec into Private Agent Factory
# (UI: Agent Builder → Import → Open Agent Spec → upload .agent.yaml)
# OR via REST: see Agent Factory REST API docs for /v1/agents
```

## Integration Points with Existing Skills

- **`oracle-26ai-schema`** — provides the user/grant/parameter setup; this skill assumes that bootstrap has already run.
- **`oci-crossplane`** — provisions the ADB 26ai instance and the Agent Factory VM. Reference Composition `composition-agent-factory.yaml`.
- **`ords-rest-api`** — exports custom PL/SQL tools as OpenAPI 3.0 JSON, which is referenced by each agent spec under `tools:`.

## Open Agent Spec note

The YAML format here follows the Open Agent Specification structure as documented for Private Agent Factory 25.3. If your installed Agent Factory version has evolved the schema, validate each spec via the Agent Builder UI import dialog before publishing — minor field renames are expected and normal.
