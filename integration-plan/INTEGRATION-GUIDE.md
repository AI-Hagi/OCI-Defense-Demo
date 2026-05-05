# Integration Guide — Industrial UCs + UC10 Requirements Intelligence

**Bundle version:** v2 (UC10 added)

This guide describes how to integrate four industrial-defence use cases into the existing `oci-defence-demo` repository:

| UC# | Name | Directory under `industrial/` |
|---|---|---|
| 7 | Engineering Knowledge Assistant | `01-engineering-knowledge` |
| 8 | Quality & Incident Analysis | `02-quality-incident` |
| 9 | Software Assurance Assistant | `03-software-assurance` |
| **10** | **Requirements Intelligence (RE for Defence)** | **`10-requirements-intelligence`** ← NEW in v2 |

If you have already integrated v1 (UCs 7–9), this guide focuses on what's added — search for `← NEW` markers.

---

## 1. What's in this bundle

```
integration-plan/
├── INTEGRATION-GUIDE.md          ← this file
├── QUICK-REFERENCE.md            ← copy-paste command card
├── CLAUDE-md-additions.md        ← block to append to your CLAUDE.md
├── bootstrap-industrial.sh       ← v2 with --uc 10 + --load-uc10-samples
├── verify-coalition-vpd.sh       ← v2 with UC10 program-isolation tests
├── composition-agent-factory.yaml.tmpl   ← Crossplane VM composition (unchanged)
└── uc10-skeleton/                ← NEW in v2 — copy under industrial/10-requirements-intelligence/
    ├── schema/
    │   ├── 01_federate.sql
    │   ├── 02_performance.sql
    │   ├── 03_metadata.sql
    │   ├── 04_security.sql       ← coalition + program two-layer VPD
    │   └── 05_ai_workload.sql    ← HNSW index + SQL/PGQ property graph
    ├── agent/
    │   └── requirements-intelligence.agent.yaml
    ├── demo/
    │   └── demo-script.md        ← 5 beats matching RE-PPTX Slide 6
    ├── sample-data/
    │   ├── generate.py           ← synthetic data via OCI GenAI (or fallback)
    │   └── load_sample_data.sql
    └── MAPPING-TO-RE-DECK.md     ← crosswalk from RE-PPTX slides to UC10 code
```

---

## 2. The strategic decision behind UC10

Requirements Engineering is a separate Use Case (UC10), **not** a sub-bereich of UC7 Engineering Knowledge.

**Why a separate UC:**

- Own data model — Requirements with traceability ≠ generic engineering documents
- Own source systems — DOORS NG, Polarion, ReqIF (no other UC needs these)
- Own quality frameworks — SMART, INCOSE, AQAP-2110
- Own demo story — Lastenheft → KI-extracted requirements → reuse → trace-matrix → V&V

**But not isolated:** UC10 reuses horizontal services from the rest of the platform.

| UC10 reuses | from | for |
|---|---|---|
| Embeddings + RAG | UC2 Document Intelligence | Lastenheft parsing |
| Multi-Tenant + Label Security | UC3 DICE-EU | Programme isolation (Eurofighter ≠ FCAS) |
| Audit-Trail + rule engine | UC6 Compliance | AQAP-2110 / DO-178C / ISO-26262 evidence |
| V&V engine | UC8 Quality | SMART check, test-case drafting |
| Software-specific traces | UC9 Software Assurance | Code requirement → code test linkage |

---

## 3. Pre-flight checklist

Before running the integration:

- [ ] You have a clean checkout of `oci-defence-demo` on `develop`
- [ ] `industrial/` already exists with UCs 7–9 integrated (v1)
- [ ] `.env` is filled in with at least `OCI_REGION`, `OCI_COMPARTMENT_OCID`, `ADB_TNS_ALIAS`, `DB_APP_USER`, `DB_APP_PWD`
- [ ] For UC10 sample data: `OCI_GENAI_ENDPOINT`, `OCI_GENAI_MODEL_CHAT`, `OCI_COMPARTMENT_OCID` (the script falls back to deterministic templates if these are missing)
- [ ] `python3` (≥ 3.9) installed locally; optional: `pip install oci` for live GenAI generation
- [ ] `sqlcl` reachable via `sql` on PATH

---

## 4. Step-by-step integration

### 4.1 New branch

```bash
cd ~/work/oci-defence-demo
git checkout develop && git pull
git checkout -b feature/uc10-requirements-intelligence
```

### 4.2 Drop UC10 skeleton into industrial/

```bash
# Copy the skeleton from this bundle
cp -R integration-plan/uc10-skeleton industrial/10-requirements-intelligence

# Verify
ls industrial/10-requirements-intelligence/
# expected: agent/  demo/  sample-data/  schema/  MAPPING-TO-RE-DECK.md
```

### 4.3 Replace bootstrap and verify scripts (v1 → v2)

```bash
# These are drop-in replacements — back up first if you've customized them
cp integration-plan/bootstrap-industrial.sh   scripts/bootstrap-industrial.sh
cp integration-plan/verify-coalition-vpd.sh   scripts/verify-coalition-vpd.sh
chmod +x scripts/bootstrap-industrial.sh scripts/verify-coalition-vpd.sh
```

The v2 scripts add `--uc 10`, `--load-uc10-samples`, and program-isolation tests. They are backwards-compatible with UCs 7–9.

### 4.4 Append the new CLAUDE.md block

```bash
cat integration-plan/CLAUDE-md-additions.md >> CLAUDE.md
```

If you already appended the v1 block, replace it instead — v2 supersedes v1 (it documents all four industrial UCs).

### 4.5 Deploy UC10 against the database

Two-stage deployment because the sample-data step depends on the schema being live:

```bash
# Stage 1 — schema (idempotent if you already ran v1)
./scripts/bootstrap-industrial.sh --shared-only       # only if you didn't run v1
./scripts/bootstrap-industrial.sh --uc 10

# Stage 2 — synthetic sample data
./scripts/bootstrap-industrial.sh --load-uc10-samples
```

The sample-data step generates ~240 synthetic requirements across three fictional programmes (Boxer-Modernisierung, Schützenpanzer NextGen, Marine-Sensor-Plattform) and computes their embeddings.

### 4.6 Verify VPD program isolation

This is the wow-moment for the demo. A green run means Eurofighter and FCAS data don't bleed across programs.

```bash
./scripts/verify-coalition-vpd.sh --uc 10
```

Expected output:

```
=== UC #10 Requirements Program-Isolation Test ===
Object: REQUIREMENTS

Alice  (DEU/RESTRICTED/NATO, EUROFIGHTER):  158 rows
Bob    (FRA/RESTRICTED/EU, FCAS):            82 rows
Carol  (DEU/RESTRICTED/NATO, both):         240 rows
Mallory (no context, fail-closed):            0 rows

PASS: UC #10 program isolation OK (Eurofighter ≠ FCAS)
```

### 4.7 Import the Wayflow agent into the Agent Factory

```bash
./scripts/bootstrap-industrial.sh --import-agents
```

This pushes all four agent YAMLs (UCs 7, 8, 9, 10) to the Private Agent Factory.

### 4.8 Walk through the demo

```bash
# Open the demo script
$EDITOR industrial/10-requirements-intelligence/demo/demo-script.md
```

Run beats 1 → 5 in the Agent Factory chat UI. Beat 5 (coalition VPD) is the demo killer. See also `MAPPING-TO-RE-DECK.md` for tying each beat back to a slide of the RE-PPTX.

### 4.9 Commit and PR

```bash
git add industrial/10-requirements-intelligence/ \
        scripts/bootstrap-industrial.sh \
        scripts/verify-coalition-vpd.sh \
        CLAUDE.md
git commit -m "feat(uc10): Requirements Intelligence for Defence Industry

Adds UC10 implementing the RE-Defence vertical from
Oracle_RE_Defence_v3_mh_2703.pptx as a runnable backend.

- 8-table schema with two-layer VPD (coalition + program)
- HNSW vector index + SQL/PGQ property graph for trace_links
- Wayflow agent with 5 tools (extract, smart-check, reuse-search,
  test-draft, trace-query)
- Synthetic sample data across 3 fictional programmes
- Demo script with 5 beats matching RE-PPTX Slide 6
- Slide → code mapping document

Pillar: Secure AI for Defense Industry"

git push -u origin feature/uc10-requirements-intelligence
```

---

## 5. What's runtime-verified vs. needs your data

**Runtime-verified out of the box:**
- Schema deploys clean against any 26ai instance
- Synthetic data generator works without OCI credentials (falls back to deterministic templates)
- VPD smoke test runs against synthetic data
- Demo beats 2, 3, 4, 5 work on synthetic data

**Needs your data to be fully convincing:**
- Beat 1 (Document Understanding) — needs a sample Lastenheft PDF in `sample-data/lastenheft-spz-nextgen.pdf`. Easiest source: any public-domain technical RFP from BAAINBw or NSPA.
- Real ReqIF round-trip — needs a target DOORS NG / Polarion instance with a published REST API.
- Custom INCOSE rule set — the smart_check tool ships with the standard SMART rules; AQAP-2110-specific extensions can be added per customer.

---

## 6. Rollback plan

If something goes wrong on the database side:

```bash
# UC10 is fully self-contained. Drop everything UC10-specific:
sql -L "$DB_APP_USER/$DB_APP_PWD@$ADB_TNS_ALIAS" <<'SQL'
DROP MATERIALIZED VIEW requirements_reuse_mv;
DROP VIEW             requirements_coverage_gaps_v;
DROP PROPERTY GRAPH   requirements_trace_graph;
DROP INDEX            requirements_hnsw_idx;
DROP TABLE            reuse_candidates       CASCADE CONSTRAINTS;
DROP TABLE            reqif_imports          CASCADE CONSTRAINTS;
DROP TABLE            verification_artifacts CASCADE CONSTRAINTS;
DROP TABLE            trace_links            CASCADE CONSTRAINTS;
DROP TABLE            requirement_sources    CASCADE CONSTRAINTS;
DROP TABLE            requirement_versions   CASCADE CONSTRAINTS;
DROP TABLE            requirements           CASCADE CONSTRAINTS;
DROP TABLE            programs               CASCADE CONSTRAINTS;
DROP PROCEDURE        embed_pending_requirements;
DROP PROCEDURE        coalition_ctx_set_program;
DROP FUNCTION         requirements_security_policy;
DROP FUNCTION         program_security_policy;
SQL

# Then re-deploy
./scripts/bootstrap-industrial.sh --uc 10
./scripts/bootstrap-industrial.sh --load-uc10-samples
```

UCs 7–9, services/, and the shared `_shared/` layer are NOT touched by UC10. They remain fully operational regardless of UC10 state.

---

## 7. Where this bundle ends and the wider work begins

This v2 bundle gives you:
- A runnable UC10 backend
- A demo script that maps to the existing RE-PPTX
- Synthetic data so the demo runs without exposing real data
- VPD-verified program isolation

Things that remain outside this bundle (suggested follow-ups):
- A `reqif-ingest` Claude Code skill for branch-neutral ReqIF parsing
- A `requirements-quality` skill with INCOSE/SMART/AQAP-2110 rule packs
- Architecture diagrams for the three sovereign tiers (Slides 17–19 of the RE-PPTX)
- Real PoC engagement using UC10 as the platform
- A vertical industry pack for the Slide Library (Module H — Defence Industry)
