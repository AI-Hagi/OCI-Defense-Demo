# Ecosystem — Sovereign Defence Intelligence Platform

Strategic positioning, capability-area mapping, and interface
boundaries to the European defense innovation ecosystem.

Source: `CLAUDE_DEV9.md` §Strategischer Bezug + §Anschlussfähigkeit.

---

## Positioning discipline

The platform delivers four things:

1. **Daten** — multi-source ingest (Sat / UAV / OSINT / SCM / Doc).
2. **KI** — YOLOv8 detection, vector search, property-graph fusion.
3. **Kollaboration** — multi-tenant under Label Security (DICE-EU).
4. **Compliance** — NIS2 / DORA / GDPR / VS-NfD posture in one view.

It explicitly **does not** simulate:

- Wirksysteme (effectors / weapons)
- C2 / Battle Management
- Feuerleitung (fire control)
- Waffeneinsatz (weapons employment)

Connectivity to BMS, KI-gestützte Aufklärung, unmanned platforms,
and Federated Mission Networking is modelled as an **interface
concept**, not as a substitute. The line is non-negotiable for
credibility with operational stakeholders.

---

## Capability-area mapping (FB1–FB5)

Per CLAUDE_DEV9.md §Strategischer Bezug:

| # | Fähigkeitsbereich | Plattform-Beitrag | Implemented in |
|---|---|---|---|
| FB1 | Schutz im bodennahen Luftraum / cUAS | UC1 GEOINT (UAV-Detektion), UC4 Sensorfusion | `services/geoint/` (`platform_kind=uav`), `services/osint-fusion/` (EMS) |
| FB2 | Indirekte Wirkung & Effekt-Synchronisation | UC7 Konvergenz-Empfehler (Preview) | *deferred to v2.1+* |
| FB3 | Elektronischer Kampf & EMS-Überlegenheit | UC4 OSINT & EMS-Lagebildfusion | `osint_entities.kind='ems_emission'`, `/api/osint/ems/clusters` |
| FB4 | Tiefe Integration unbemannter Systeme | UC1 + UC4 Manned-Unmanned-Datentopologie | `satellite_scenes.platform_kind`, `osint_relations` graph |
| FB5 | Digitalisierung, KI & MDO-Fähigkeit | **alle Use Cases — Plattformkern** | Whole stack |
| übergreifend | Aktiv-/Reserve-Strukturen, Mobilisierungsfähigkeit | UC3 Multi-Tenant DICE-EU | `tenants` + `DICE_POLICY` (OLS) |

---

## 7 Use Cases — interface map

| UC | Name | Public surface | Interface to other systems |
|---:|---|---|---|
| 1 | Multi-Source GEOINT & UAV-Aufklärungsfusion | `/api/geoint/*`, GeointView | UAV ground-control software → POST /scenes/upload with `X-Platform-Kind: uav` |
| 2 | Doktrin- & Lage-RAG | `/api/documents/*`, DocumentView | Document Management Systeme → POST /documents/ingest (planned) |
| 3 | Multi-Tenant Collaboration (DICE-EU) | CollaborationView | Cross-tenant share by `X-Tenant-Id` propagation; OLS enforces row visibility |
| 4 | OSINT & EMS-Lagebildfusion | `/api/osint/*`, OsintView | EMS sensors / SDR → POST entities with `kind=ems_emission`; FMN feed via `osint_relations` |
| 5 | Rüstungs-Lieferketten & Risk Scoring | `/api/sc/*`, SupplyChainView | ERP / SAP integrations → push `supply_nodes` + `supply_relations` |
| 6 | Compliance Automation | `/api/compliance/*`, ComplianceView | Cloud Guard, ADB encryption posture, bucket policy, OLS — all via `/live/*` |
| 7 | Konvergenz-Empfehler *(Preview, v2.1+)* | — | Federated mission networking adapter (planned) |

---

## Anschlussfähigkeit

The platform is an explicit **data + AI backbone** for these
ecosystem partners:

- **Truppenversuche / Erprobungseinheiten** — telemetry +
  evaluation backbone for operational experimentation series.
- **C2- und Battle-Management-Systeme** — platform sits *behind*
  C2 as a data sink and AI layer, not as a replacement.
- **Federated Mission Networking** — UC7 will follow established
  patterns from international AI-recon programmes (interface, not
  protocol stack).
- **Drohnen- und cUAS-Koordination** — UC1 + UC4 sandbox for
  UAV/cUAS data, mediated by `platform_kind` and `ems_emission`
  attributes.
- **Ausbildungs- und Trainingseinrichtungen** — analysis
  environment for exercise / training data.
- **Innovations- und Technologiezentren** — anchor for UC1/UC4
  cUAS and drone showcases.
- **Cyber Innovation Hub** — pluggable as a sandbox tenant
  (`CONTRACTOR_BRAVO`-style profile).

---

## Tenant model (live)

Per CLAUDE_DEV9.md §Demo-Tenants the spec is:

| Spec slot | Demo tenant_id | Notes |
|---|---|---|
| ACTIVE_FORCE | `T001` | aktive Verbände — full live access |
| RESERVE_FORCE | `T002` | nichtaktive / Reserve — restricted live |
| PROGRAM_LEAD | `T003` | programmverantwortliche Stelle |
| CONTRACTOR_ALPHA | *(planned)* | industry tenant slot |
| CONTRACTOR_BRAVO | *(planned)* | industry tenant slot |

This release keeps the existing `T001/T002/T003` IDs and display
names (`DEU_BMVG`, `FRA_DGA`, `NLD_MOD`) — only OLS labels and
compartments are migrating to the spec values. Adding the two
contractor tenants is a follow-up seed-only change.

---

## OLS compartments (target — Phase 2 in flight)

Per CLAUDE_DEV9.md §Konventionen → Datenbank:

| Compartment | Use case primarily affected |
|---|---|
| `GEOINT` | UC1 satellite + UAV |
| `HUMINT` | (future — not actively used in this PR) |
| `SIGINT` | (future) |
| `LOGISTICS` | UC5 supply chain |
| `EW` | UC4 EMS |
| `C_UAS` | UC1 + UC4 — counter-UAS overlay |
| `UAS_OPS` | UC1 — UAV mission planning |

Levels: `UNCLASSIFIED (100)`, `RESTRICTED (200)`,
`CONFIDENTIAL (300)`, `SECRET (400)`.

Migration scripts: `db/migrations/04_ols_v2_levels.sql` …
`db/migrations/08_ols_drop_old.sql`.

---

## Future directions (not in this PR)

- UC7 Konvergenz-Empfehler (FB2) — Effekt-Synchronisation across
  UC1 / UC4 / UC5 signals, federated-mission-networking-compatible.
- OKE Workload Identity for ATP — replace wallet+password with
  pure SA-token delegation (Phase 4 lays groundwork).
- OCI Generative AI Agents for UC2 RAG — current path uses
  `all-MiniLM-L6-v2` in-cluster.
