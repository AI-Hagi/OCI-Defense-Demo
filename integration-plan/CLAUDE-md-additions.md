# CLAUDE.md — Erweiterungen für Industrial UCs (v2 mit UC10)

> **Wie verwenden:** Diesen Block in deine bestehende `CLAUDE.md` einfügen, idealerweise direkt nach dem 6-UC-Block. Keine bestehenden Inhalte ersetzen.

---

## Industrial Defence Use Cases (industrial/)

Vier zusätzliche UCs für Defence Contractors und Manufacturing-getriebene Programme.
Komplementär zu den 6 Intelligence-UCs in `services/`.

| # | Name | Verzeichnis | Audience | Kurzbeschreibung |
|---|---|---|---|---|
| 7 | Engineering Knowledge Assistant | `01-engineering-knowledge` | Engineering | RAG über PLM-Dokumente |
| 8 | Quality & Incident Analysis | `02-quality-incident` | Manufacturing / Quality | Vector-Clustering + ML-Anomalien auf NCR/SPC |
| 9 | Software Assurance Assistant | `03-software-assurance` | V&V Leads / Auditors | Property-Graph-Traceability für Reqs/Tests/Defects |
| 10 | Requirements Intelligence | `10-requirements-intelligence` | Defence Industry RE | RE-Knowledge-Base mit Reuse-Suche, INCOSE-Quality, ReqIF-Ingest |

### 5-Schritte-Methodik

Alle vier Industrial-UCs folgen dem Oracle "AI on Live Data" Pattern:

1. **Federate Data** — `DBMS_CLOUD.CREATE_CREDENTIAL` + `DBMS_CLOUD_ADMIN.CREATE_DATABASE_LINK` für REST/DB-Quellen, External Tables für Object-Storage-Inhalte (inkl. ReqIF-XML für UC10)
2. **Augment Performance** — Materialized Views mit `REFRESH COMPLETE NEXT SYSDATE + n/24`
3. **Augment Metadata** — `COMMENT ON` plus 26ai Data Annotations (für UC10: SHALL/SHOULD/MAY-Semantik)
4. **Augment Security** — VPD via `coalition_ctx` (clearance + nation + releasability), fail-closed. **UC10 erweitert um Programm-Isolation** (Eurofighter ≠ FCAS).
5. **Create AI Workload** — Select AI Profile + Vector Pipeline + Wayflow Agent Spec

### Verzeichnisstruktur

```
industrial/
├── README.md                              # UC-Übersicht und Deployment-Anleitung
├── _shared/
│   ├── coalition_ctx_bootstrap.sql        # App Context + reusable VPD policy
│   └── ai_profile_template.sql            # OCI GenAI EU + Private LLM profiles
├── 01-engineering-knowledge/
│   ├── schema/01..05_*.sql                # 5-step methodology
│   ├── agent/*.agent.yaml                 # Wayflow Open Agent Spec
│   └── demo/demo-script.md
├── 02-quality-incident/
├── 03-software-assurance/
└── 10-requirements-intelligence/          ← NEU (RE für Defence)
    ├── schema/01..05_*.sql                # incl. property graph for trace_links
    ├── agent/requirements-intelligence.agent.yaml
    ├── demo/demo-script.md                # 5 beats matching RE-PPTX Slide 6
    ├── sample-data/
    │   ├── generate.py                    # Synthetic data via OCI GenAI
    │   ├── load_sample_data.sql           # Bulk load + embedding
    │   └── synthetic.json                 # Generated corpus (gitignored)
    └── MAPPING-TO-RE-DECK.md              # Slide → Code crosswalk
```

### Konventionen für `industrial/`

- **VPD-Komposition:** Eigene Policy-Funktionen rufen die shared `coalition_security_policy` auf und addieren AND-Klauseln. UC10 erweitert um eine `program_security_policy` (Programm-Liste aus Application Context).
- **Vector Indizes:** HNSW als Default, IVF Flat nur bei Speicher-/Latenz-Constraints.
- **Property Graph:**
  - UC9 (Software Assurance): `requirements → tests → defects` — Defect-Impact-Analyse
  - UC10 (Requirements Intelligence): `trace_links` mit Edge-Typen `satisfies | verifies | derives | conflicts` — Coverage-Gap-Queries
- **Agent Specs:** Open Agent Specification YAML-Format. Beim Import in der Builder-UI prüfen.
- **Klassifikation in Daten:** Jede Zeile, die ein Agent lesen kann, muss zwei Spalten haben: `clearance_required` (UNCLASSIFIED..TOP_SECRET) und `releasable_to` (Nation-Codes oder Coalition-Gruppen). UC10 zusätzlich: `program_id`.
- **LLM-Default:** OCI Generative AI in eu-frankfurt-1. Private LLM via vLLM-Container nur als Fallback für VS-NfD-Workloads.
- **UC10-Spezifika:**
  - 8 Tabellen statt der üblichen 4-5: `programs`, `requirements`, `requirement_versions`, `requirement_sources`, `trace_links`, `verification_artifacts`, `reqif_imports`, `reuse_candidates`
  - Quality-Frameworks: SMART, INCOSE, AQAP-2110
  - Demo-Daten ausschließlich synthetisch (siehe `sample-data/generate.py`) — keine echten klassifizierten Inhalte im Repo

### AFCEA-Pillar-Zuordnung

Alle vier Industrial-UCs gehören zur Pillar **Secure AI for Defense Industry**:
- UC7, UC8, UC9: Industrial-AI-Bausteine
- UC10: vertikale Defence-Industry-Story (RE-Knowledge-Base mit Programm-übergreifendem Reuse)

### Bootstrap und Verifikation

```bash
# Initial-Setup (eine ADB, alle Industrial-UCs inklusive UC10)
./scripts/bootstrap-industrial.sh

# Einzelne UCs
./scripts/bootstrap-industrial.sh --uc 02
./scripts/bootstrap-industrial.sh --uc 10

# UC10 synthetic sample data (ein Mal nach UC10-Schema-Deploy)
./scripts/bootstrap-industrial.sh --load-uc10-samples

# VPD-Smoke-Tests
./scripts/verify-coalition-vpd.sh             # alle Tests
./scripts/verify-coalition-vpd.sh --uc 10     # nur UC10 (Programm-Isolation)
```

### Was NICHT in `industrial/` gehört

- Container-Services à la `services/geoint/` — Industrial-UCs sind datenbankzentrisch, das Frontend ist die Agent-Factory-UI
- Hardcoded Hosts/Regions/OCIDs — alles über `.env` und SQL-Substitution-Variablen
- Eigene VPD-Implementierungen ohne Anbindung an `coalition_security_policy`
- Versionsabhängige Skripte für 23ai oder 23c — diese Plattform ist 26ai-only
- **Echte klassifizierte Demo-Daten** (insbesondere für UC10) — nur Synthetic oder Public-Domain-ReqIF-Beispiele

### UC10-spezifische Konventionen

- **Sample-Daten** werden über `generate.py` aus OCI GenAI erzeugt und enthalten im Header explizit den Hinweis "Synthetisch — nicht repräsentativ für reale Programme".
- **Drei fiktive Demo-Programme** (siehe `sample-data/generate.py`): "Boxer-Modernisierung", "Schützenpanzer NextGen", "Marine-Sensor-Plattform". Bei Bedarf erweiterbar — Programmnamen müssen aber fiktiv bleiben.
- **ReqIF-Ingest-Pipeline** ist das einzige UC10-Feature, das später als eigener Skill (`reqif-ingest`) ausgelagert wird, weil es branchenneutral wiederverwendbar ist (Automotive, Aerospace).
- **Demo-Storyboard** in `demo/demo-script.md` folgt 1:1 der Slide-6-Reihenfolge der `Oracle_RE_Defence_v3_mh_2703.pptx` — von Lastenheft-Upload bis fertiger Spezifikation.
- **Mapping-Dokument** `MAPPING-TO-RE-DECK.md` verlinkt jede Folie der RE-PPTX auf das konkrete Code-Artefakt. Damit wird aus der Vertriebs-Story ein verifizierbares Demo-System.
