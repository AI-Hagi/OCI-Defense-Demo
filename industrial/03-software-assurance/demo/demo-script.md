# Demo Script — Software Assurance Assistant (UC #08)

**Audience:** Verification & validation leads, programme auditors, software architects, BAAINBw / BWB technical reviewers

**Duration:** ~7 minutes

**Setup:** Single chat session as a Verification Lead with access to project `FCAS-MissionPlanner`, clearance RESTRICTED, nation DEU, releasability NATO.

---

## Beat 1 — "Where are my coverage gaps?"

> "Welche freigegebenen Requirements im Projekt FCAS-MissionPlanner haben noch keinen erfolgreichen Test-Nachweis?"

The agent calls `query_swassure` against `coverage_gaps_v` (the SQL/PGQ-backed view). Returns a clean list of requirement IDs with title and priority.

**Talking point:** This is a SQL/PGQ graph query running natively in the database against federated PLM/test data. No graph database to operate, no separate ETL, no Neo4j licence.

---

## Beat 2 — "Which requirements are at risk because of defect XYZ?"

> "Defekt DEF-2347 — welche Requirements sind betroffen, und wie kritisch sind die?"

The agent calls `graph_traceability` starting at `defect:DEF-2347`, walks back via `surfaces` → `satisfied_by` to all affected requirements, returns the chain.

**Talking point:** Backward traceability in one query. Auditors love this — "show me impact" used to take hours of spreadsheet work.

---

## Beat 3 — "Do we have duplicate requirements?"

> "Gibt es Requirements im Projekt die im Wesentlichen das Gleiche fordern wie REQ-1042?"

The agent calls `search_requirements` (vector similarity on title + description), returns 4 semantically similar requirements, ranked by cosine distance. The agent presents them with a comparison table and asks whether they are redundant or differentiated by domain context.

**Talking point:** Embedding-based similarity catches what keyword search and ID-based traceability miss — *semantic* duplication.

---

## Beat 4 — "Pull me the test evidence for VERIFIED requirement REQ-0987"

> "REQ-0987 ist als VERIFIED markiert. Zeig mir das signierte Test-Evidenz-Dokument."

The agent walks the graph: REQ-0987 → satisfied_by → TEST-301 → has_result → RESULT-9912 (PASS) → evidence_doc_id. Calls `fetch_test_evidence` on that doc_id and presents the citation.

**Talking point:** This is what an audit looks like, automated. From requirement to signed evidence in one chat turn.

---

## Beat 5 — Refusal of speculation

> "Wenn wir REQ-1500 jetzt freigeben, glaubst du das geht durch die V&V?"

The agent refuses (system prompt rule), offers to instead retrieve historical pass/fail rates for similar requirements based on vector similarity.

**Talking point:** Built-in safety against speculative answers in an assurance context. Hallucinations here would be career-ending.

---

## What this demonstrates

| Capability | Where it shows |
|---|---|
| Heterogeneous Connectivity to Polarion / Jama | All beats |
| External Tables on Git metadata | Beats 1, 2 |
| **Property Graph + SQL/PGQ in 26ai** | **Beats 1, 2, 4 — the centerpiece** |
| Vector embeddings + similarity search | Beat 3 |
| Multi-tool reasoning with structured + graph + vector | Beat 4 |
| Coalition + project-level VPD | implicit throughout |
| Strict groundedness guardrail | Beat 5 |

---

## Why this matters strategically

Software-driven defence programmes (FCAS, NNbS, MGCS) are *ALL* under pressure to deliver evidence-grade traceability. Most contractors today do this with a brittle mix of DOORS + Polarion + Excel + manual review. This demo shows that a single Oracle AI Database 26ai instance with Agent Factory can collapse that entire stack — federated, governed, and auditable from day one.
