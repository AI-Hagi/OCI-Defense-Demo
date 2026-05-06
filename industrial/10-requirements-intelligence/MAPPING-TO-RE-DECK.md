# MAPPING-TO-RE-DECK.md

> Crosswalk between **`Oracle_RE_Defence_v3_mh_2703.pptx`** (22-slide vertical defence-industry pitch) and the UC10 implementation in this directory.
>
> Use this when a stakeholder has seen the RE-deck and asks "where is the running code?". Every claim made in the deck has a concrete code artefact below.

---

## Slide-by-slide mapping

| Slide # | Slide title (DE) | Code artefact in UC10 |
|---|---|---|
| 1 | KI-gestütztes Requirements Engineering für die Rüstungsindustrie | (cover) |
| 2 | Agenda | — |
| 3 | Herausforderungen im Requirements Engineering | (motivation only — no code) |
| 4 | Typischer Ist-Zustand in der Rüstungs-RE | (motivation only — no code) |
| 5 | Oracle KI-Plattform für Requirements Engineering | `agent/requirements-intelligence.agent.yaml` (5 tools = 5 services in the slide) |
| **6** | **Vom Altprojekt zum Neuprojekt** | **`demo/demo-script.md`** — 5 demo beats map 1:1 to the 5 process steps |
| 7 | Requirements Knowledge Base | `schema/05_ai_workload.sql` — HNSW index + reuse_mv |
| 8 | KI-gestützte Anforderungsqualität & Konsistenzprüfung | Agent tools `extract_requirements`, `smart_check`, `draft_test_case` |
| 9 | OCI Document Understanding | Agent tool `extract_requirements` (type: `document-understanding`) |
| 10 | OCI Language (NLP) | Agent tool `smart_check` (type: `nl-quality-rules`) |
| 11 | OCI Generative AI (GenAI) | `spec.llm.primary` in agent YAML; `_shared/ai_profile_template.sql` |
| 12 | Oracle Database 26ai | `schema/02_performance.sql` (vector column) + `schema/05_ai_workload.sql` (HNSW) |
| 13 | OCI Data Science | (deferred — UC10 v2 will add custom ML for trace-link prediction) |
| 14 | Drei Sovereign Deployment-Optionen | `agent/.../exposure.sovereign_tiers` (eu-sovereign, cloud-at-customer, c3i-isolated) |
| 15 | Oracle Agentic AI | `agent/requirements-intelligence.agent.yaml` (Wayflow Agent Spec) |
| 16 | Agentic AI im Requirements Engineering | Same YAML — tool list matches "RE-Agenten-Typen" on the slide |
| 17 | Architektur · Option 1 · EU Sovereign Cloud | (architecture diagram — deferred to docs/) |
| 18 | Architektur · Option 2 · Cloud@Customer | (architecture diagram — deferred to docs/) |
| 19 | Architektur · Option 3 · C3I Air-Gap | (architecture diagram — deferred to docs/) |
| 20 | Warum Oracle — und nicht ein anderer Anbieter | (positioning — no code) |
| 21 | AI Center of Excellence — Platform Workshop | (offer — no code) |
| 22 | Empfehlung & Nächste Schritte | This UC10 implementation **is** the PoC offered in the slide |

---

## What is and isn't in UC10 today

✅ **In:** Federate ReqIF + Object Storage, requirements + trace_links + verification_artifacts schema, HNSW vector index, SQL/PGQ property graph, two-layer VPD (coalition + program), agent YAML with five tools, demo script with five beats, synthetic data generator, sample data loader.

⏳ **Deferred to UC10 v2:**
- OCI Data Science custom ML (trace-link prediction model)
- Architecture diagrams as SVG in `docs/architecture/uc10-*`
- ReqIF round-trip export back into DOORS NG (placeholder tool only)
- Real Lastenheft-PDF in `sample-data/lastenheft-spz-nextgen.pdf` for Beat 1

❌ **Not in scope:**
- Real classified data — sample data is synthetic only
- Fine-tuned LLM — base `cohere.command-r-plus-v2` is sufficient for demo
- Customer-specific anonymized data — that's a separate workstream, post-PoC

---

## Slide-22 PoC offering — what UC10 makes possible

| Slide-22 promise | Today's reality with UC10 |
|---|---|
| "Generative AI Platform Workshop (3h)" | UC10 demo can **be** the workshop's anchor demonstration |
| "Proof of Concept — Requirements Knowledge Base" | UC10 **is** that PoC. ReqIF import works, vector reuse works, VPD isolation works |
| "Sovereign Cloud Tier-Assessment" | UC10 deploys identically to all three tiers (same agent YAML, same SQL) |
| "Business Case & Roadmap" | UC10 metrics (extraction count, reuse rate, coverage gaps) drive the ROI calculation |

---

## How to walk a stakeholder through this

1. Show **slide 6** of the RE-PPTX
2. Open this MAPPING file
3. Show **`demo/demo-script.md`** on the same screen
4. Run beat 1, 3, and 5 live (extract → reuse-search → coalition VPD)
5. End with: "Slide 22 promised a PoC. You're looking at it."
