# UC #10 Requirements Intelligence — Demo Script

> **Audience:** Defence Contractors / RE-Engineers / V&V-Leads / BAAINBw-Reviewer
> **Runtime:** ~12 minutes (5 beats)
> **Mapping:** This script follows Slide 6 of `Oracle_RE_Defence_v3_mh_2703.pptx` ("Vom Altprojekt zum Neuprojekt") and produces a runnable counterpart for every beat shown there.

---

## Pre-flight (before the demo)

1. ADB 26ai is reachable via `ADB_TNS_ALIAS`
2. `bootstrap-industrial.sh --uc 10` has been run (schema + property graph deployed)
3. `bootstrap-industrial.sh --load-uc10-samples` has been run (~240 synthetic requirements across 3 programs)
4. `verify-coalition-vpd.sh --uc 10` is green (program isolation works)
5. Two browser tabs / two Agent Factory sessions ready:
   - **Alice** (DEU/RESTRICTED/NATO, EUROFIGHTER) — RE Engineer at the customer
   - **Carol** (DEU/RESTRICTED/NATO, EUROFIGHTER+FCAS) — Multi-program Architect

---

## Beat 1 — "Lastenheft hochladen" (Document Understanding)

**Story:** A new Lastenheft for "Schützenpanzer NextGen Variant DEU" arrives as PDF. Today: the engineer reads it, copy-pastes SHALL statements into DOORS NG. Time: weeks. With the platform: drag-and-drop, seconds.

**Live action:**

1. Open Agent Factory, log in as **Alice**, select `requirements-intelligence-agent`
2. Drag the demo PDF (`industrial/10-requirements-intelligence/sample-data/lastenheft-spz-nextgen.pdf`) into the chat
3. The agent calls the `extract_requirements` tool (OCI Document Understanding)
4. Wait ~10 seconds — agent returns a table:

```
Extracted 47 requirements from 12 pages:
- 28 SHALL statements
- 14 SHOULD statements
-  5 MAY statements

Top-level categories: functional (19), performance (9),
                      safety (12), interface (7)
```

**The pitch:** "What you just saw is not a slide deck. It's OCI Document Understanding running against a real PDF. The agent placed all 47 requirements in DRAFT status in the database — Alice still has to review them, but the manual extraction work is gone."

---

## Beat 2 — "Quality Check" (OCI Language NLP)

**Story:** Half of the new requirements have ambiguous wording: "angemessen schnell", "möglichst leicht", "soweit möglich". Today: caught only in late review, after weeks. With the platform: caught immediately, with concrete improvement suggestion.

**Live action:**

1. Alice asks the agent: *"Run smart_check on the requirements I just extracted."*
2. Agent calls `smart_check` tool, returns a score table:

```
Quality scores for 47 newly extracted requirements:

  Pass (>= 80):  29 requirements
  Borderline:    11 requirements  ← review recommended
  Fail (< 60):    7 requirements  ← rewrite recommended

Worst offender: REQ-NEW-0023
  "Das System soll möglichst schnell auf Bedrohungen reagieren."
  Score: 32 / 100
  Issue: ambiguous quantifier ("möglichst schnell" — not measurable)
  Suggested rewrite:
  "Das System SHALL auf erkannte Bedrohungen innerhalb von 200 ms
   eine akustische und visuelle Warnung ausgeben (Detect-to-Alert)."
```

**The pitch:** "INCOSE plus SMART rules running in OCI Language. Quality score is persisted in the requirements table — auditors get a tamper-proof history."

---

## Beat 3 — "Reuse-Suche" (Oracle 26ai AI Vector Search)

**Story:** Half the requirements in any new programme already exist somewhere in the organization's history. Today: nobody knows. With the platform: top-5 most similar past requirements with similarity score and source program — in milliseconds.

**Live action:**

1. Alice asks the agent: *"For REQ-NEW-0014 ('Das System SHALL eine 360-Grad-Rundumsicht bei Tag und Nacht ermöglichen'), find similar requirements from past programs."*
2. Agent calls `reuse_search` (HNSW vector search across `requirements_reuse_mv`)
3. Result:

```
Top-5 similar approved requirements from past programmes:

1. REQ-BOXER-0287  (98.2% similar) — Boxer-Modernisierung
   "Das System SHALL eine 360°-Sichtabdeckung bei Tag und Nacht
    bereitstellen über Multi-Spektral-Sensoren."

2. REQ-MARINE-0094 (94.7% similar) — Marine-Sensor-Plattform
   "Sensors SHALL provide full hemispheric coverage in visual
    and IR wavelengths for night operations."

3. REQ-BOXER-0451 (87.1% similar) — Boxer-Modernisierung
   ...
```

**The pitch:** "98.2% similarity. Alice can re-use the Boxer-formulation directly, including its V&V evidence. Similarity is computed by Oracle 26ai AI Vector Search natively — no Pinecone, no separate vector store."

---

## Beat 4 — "Coverage-Gap-Analyse" (SQL/PGQ Property Graph)

**Story:** Once a programme is approved, V&V leads need to see which SHALL/SHOULD requirements still have no test evidence. Today: spreadsheet maintenance. With the platform: one graph query, live.

**Live action:**

1. Alice asks: *"Show me coverage gaps in the EUROFIGHTER programme."*
2. Agent calls `trace_query` with preset `coverage_gaps`
3. Result:

```
Coverage gaps in EUROFIGHTER (APPROVED SHALL/SHOULD without verifies-link):

  Total requirements:    158
  With test evidence:    142
  Coverage:              89.9%
  Gaps:                   16

Top open gaps by category:
  - Safety:        7 gaps  ← critical
  - Performance:   5 gaps
  - Interface:     4 gaps

Showing first 5 gaps:
  REQ-EUROF-0078  Safety  "SHALL fail to safe state on..."
  REQ-EUROF-0091  Safety  "SHALL maintain altitude during..."
  ...
```

**The pitch:** "This is a SQL/PGQ property-graph query in Oracle 26ai — the same database that holds the requirements. No graph database (Neo4j) needed. The view `requirements_coverage_gaps_v` returns this in milliseconds even with millions of requirements."

---

## Beat 5 — "Coalition VPD: Eurofighter ≠ FCAS" (the wow moment)

**Story:** Same agent, same SQL — but Alice (Eurofighter only) and Carol (Eurofighter + FCAS) see different worlds. This is the demo killer for any defence contractor who runs multiple programs in parallel.

**Live action:**

1. Both tabs open. Both ask: *"How many requirements are in our knowledge base?"*
2. Alice's tab returns:

```
Total requirements visible to your session: 158
  EUROFIGHTER: 158
  FCAS: 0 (not in your program list)
```

3. Carol's tab (other browser, multi-program access):

```
Total requirements visible to your session: 240
  EUROFIGHTER: 158
  FCAS: 82
```

4. Live in Carol's tab: *"Show me reuse candidates for REQ-NEW-0014 across all my programs"* — agent returns matches from BOTH Eurofighter and FCAS.
5. Same query in Alice's tab: only Eurofighter matches surface. **FCAS data is invisible — not just filtered out at the LLM, but invisible at the row level via VPD.**

**The pitch:** "This is the heart of the platform: program isolation enforced at the database row level via VPD. The LLM never sees what the user is not authorized to see. Auditors call this *fail-closed by default*. Defence contractors call it *the only way we can run multi-program AI*."

---

## Closing line

> "Everything you saw is in Oracle 26ai, on OCI Sovereign Cloud, EU only.
> Document Understanding, Language NLP, Generative AI, Vector Search, Property Graph,
> VPD, Audit — one platform, one API, one sovereign deployment.
> Slide 22 of the briefing offered you a Proof of Concept. This is the PoC."

---

## Backup beats (if there's time)

- **Beat 6:** Test-case generation (`draft_test_case` tool) for one of the new requirements
- **Beat 7:** ReqIF export back to DOORS NG (`reqif_export` tool)
- **Beat 8:** Compliance audit trail — show how UC6 logs everything Alice and Carol did

## What this demo does NOT show (and why)

- No real classified data — all sample data is synthetic, generated via OCI GenAI
- No real customer programmes — names are fictional ("Schützenpanzer NextGen Variant DEU")
- No air-gap / C3I deployment — the EU Sovereign Cloud tier is sufficient for this demo
- No fine-tuned LLM — base cohere.command-r-plus-v2 is good enough for the demo flow
