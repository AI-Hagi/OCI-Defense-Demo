# Demo Script — Quality & Incident Analysis Agent (UC #04)

**Audience:** Quality leaders, plant managers, manufacturing engineering heads, AS9100 / ISO 9001 audit teams

**Duration:** ~7 minutes

**Setup:** Single Agent Factory chat session, authenticated as a Quality Manager with access to plants `DE-MUC` and `DE-FRI`, clearance RESTRICTED, nation DEU, releasability NATO.

---

## Beat 1 — "What's been going wrong this month?"

> "Gib mir einen Überblick über die NCRs der letzten 30 Tage in DE-MUC und DE-FRI. Welche Defektkategorien dominieren?"

The agent calls `query_quality_data` (Select AI NL2SQL) on `ncr_recent_mv`, returns counts grouped by `defect_category` and `severity`. Plain-language summary plus a small inline table.

**Talking point:** No Python, no notebook, no BI tool. The MV refreshes every 30 minutes, so this is "live enough" for management decisions.

---

## Beat 2 — "Are these incidents related?"

> "Es scheinen viele Dimensionsfehler in DE-MUC zu sein. Sind die ähnlich?"

The agent calls `search_ncrs` (vector search) plus `ncr_clusters` (k-means). Returns 3 clusters for that plant/category, each with top descriptive terms and 2–3 example NCRs cited by ID.

**Talking point:** The agent didn't just retrieve — it grouped. Vector embeddings + in-database k-means surface patterns that keyword search misses.

---

## Beat 3 — "Is the process actually drifting?"

> "Gibt es in den letzten 24h auffällige SPC-Werte zu Teil 1234567 in DE-MUC?"

The agent calls `spc_anomalies` (OML one-class SVM scoring). Returns flagged hour-buckets with mean/stddev/oos counts. Optionally correlates with open NCRs on the same part.

**Talking point:** All three model types — vector embeddings, k-means clustering, SVM anomaly detection — running *inside* the database. No model export, no MLOps pipeline, no separate service.

---

## Beat 4 — Coalition / plant-level visibility check

Switch session to a partner-nation user with access to plant `FR-TLS` only.

> Same overview question.

Different result set. The agent makes no mention of the German plants — they're filtered at the row level by VPD before the LLM ever sees them.

**Talking point:** Plant access *and* coalition releasability layered cleanly. Same agent, two truths, both correct from the user's authorized perspective.

---

## What this demonstrates

| Capability | Where it shows |
|---|---|
| Heterogeneous DB-Link to Oracle quality system | Beat 1 |
| External Tables on SPC CSV | Beat 3 |
| MV with 30-min refresh + hourly aggregation MV | Beat 1, 3 |
| Vector embeddings + k-means in DB | Beat 2 |
| Oracle ML one-class SVM | Beat 3 |
| Combined VPD (coalition + plant access) | Beat 4 |
| Multi-tool agent reasoning | Beats 2, 3 |
| Sovereign deployment | throughout |
