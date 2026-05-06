# Demo Script — Engineering Knowledge Assistant (UC #01)

**Audience:** Defence Contractor (Rüstungsindustrie) engineering management, head of digital engineering, CDO of program office

**Duration:** ~6 minutes

**Setup:** Two browser tabs / two Agent Factory chat sessions, authenticated as different users.

| Tab | User | Clearance | Nation | Releasability |
|---|---|---|---|---|
| A | alice@contractor.de | RESTRICTED | DEU | NATO |
| B | bob@partner.tr   | UNCLASSIFIED | TUR | NATIONAL_ONLY |

---

## Beat 1 — Same query, different visibility (the trust moment)

**In Tab A (Alice):**
> "Welche Revisionen von Teil 1234567 sind aktuell freigegeben und welche Doktrinen-Klauseln gelten dafür?"

Alice receives a grounded answer citing `1234567_C_SPEC_RESTRICTED_NATO.pdf` plus references to the release record. Coalition VPD allowed the RESTRICTED-classified spec.

**In Tab B (Bob):**
> Same question.

Bob receives a much shorter answer — only the UNCLASSIFIED parts of the catalog. No leak, no error, no mention of the existence of the restricted record.

**Talking point:** The same agent, same database, same query — VPD filters at the row level *before* the LLM ever sees the data. The LLM cannot leak what it never received.

---

## Beat 2 — Live-vs-cached evidence (PLM passthrough)

**In Tab A:**
> "Ist die Revision die ich gerade in der Antwort sehe wirklich die aktuellste? Schau in PLM nach."

The agent invokes `fetch_plm_part_live` (PLM REST, not the 15-min MV). Returns either confirmation or an alert that PLM has a newer in-work revision the snapshot has not yet picked up.

**Talking point:** Federation gives you cache-when-fast, live-when-needed. Demo shows both paths in one conversation.

---

## Beat 3 — Cross-document reasoning

**In Tab A:**
> "Was hat sich zwischen Revision B und C geändert? Welche Tests müssen wiederholt werden?"

The agent does:
1. NL2SQL on `plm_parts_mv` to confirm both revisions exist and their lifecycle states
2. Vector search on change-note documents (`*_CHANGE_*.pdf`)
3. Vector search on test-report documents (`*_TEST_*.pdf`)
4. Synthesizes a structured answer with explicit citations

**Talking point:** Multi-tool agent reasoning, not just RAG. Mix of structured (parts table) and unstructured (change notes, test reports) — exactly what the AI on Live Data pattern enables.

---

## Beat 4 — Shut-down: groundedness check

**In Tab A:**
> "Was wäre wenn Revision D existieren würde — was würde sich ändern?"

The agent should refuse to speculate (system prompt rule). Output guardrail confirms.

**Talking point:** Built-in groundedness check makes the agent production-safe. No hallucinated specs.

---

## What this demonstrates

| Capability | Where it shows |
|---|---|
| Heterogeneous Connectivity (PLM REST → DB) | Beat 2 |
| External Tables on Object Storage | Beat 1, 3 |
| Materialized View with auto-refresh | Beat 2 (cache vs live) |
| Comments + Annotations driving NL2SQL | Beat 1, 3 |
| Coalition VPD (App Context + Policy) | Beat 1 (the highlight) |
| Vector Search + Select AI RAG | Beat 1, 3 |
| Multi-tool agent | Beat 3 |
| Guardrails | Beat 4 |
| Sovereign deployment (EU GenAI region only) | Sub-message throughout |
