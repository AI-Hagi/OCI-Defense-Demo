# Sovereign Defence Intelligence Platform — Claude Code Configuration

> Souveräne Multi-Source Intelligence Plattform auf Oracle EU Sovereign Cloud,
> inspiriert von Oracles DICE (Defence Industrial Base Isolated Cloud Environment,
> 2026). EU-Variante als souveränes Daten-, KI- und Compliance-Backbone.
> Orchestriert mit [Ruflo](https://github.com/ruvnet/ruflo) v3.5
> (hierarchical topology, raft consensus, anti-drift defaults).

**Owner:** Markus Hagenkoetter
**OCI Region:** `eu-frankfurt-1` (EU Sovereign Cloud)
**Compartment:** `oci-defence-demo`

> **ADR-0001 Frontend-Bundler:** React 18 + Vite + TypeScript ist die einheitliche
> Frontend-Plattform für ALLE 6+1 Use Cases inklusive UC4 Cesium-Lagebild.
> WorldViews IIFE-Pattern (`WV.layers.X = ...`) wird durch TypeScript-Module
> mit zentralem `LayerRegistry` ersetzt. Begründung: keine zwei parallelen
> Frontend-Welten, einheitliches Tooling (HMR, Tree-Shaking, strict TS),
> typed-`map_action`-Interface zwischen Chat-Service und Cesium.

---

## Behavioral Rules (Always Enforced)

Allgemein (Ruflo-Standard):

- Do what has been asked; nothing more, nothing less.
- NEVER create files unless absolutely necessary for the goal.
- ALWAYS prefer editing an existing file over creating a new one.
- NEVER proactively create `*.md` or README files unless explicitly requested.
- NEVER save working files, scratch tests, or notes to the root folder.
- ALWAYS read a file before editing it.
- NEVER commit secrets, credentials, `.env` files, or OCI Vault OCIDs.
- After spawning a swarm: do not poll status — wait for results via hooks.

Projekt-spezifisch:

- Datenbank ist **IMMER Oracle AI Database 26ai** — niemals 23ai oder 23c referenzieren.
- NEVER hardcode an OCI region — read from `.env`, default `eu-frankfurt-1`.
- NEVER write API keys (AIS Stream, Sentinel, OpenSky, etc.) into
  `frontend/src/config.ts` oder andere browser-erreichbare Files. **OCI Vault only.**
- NEVER let frontend layer modules call public APIs directly — always via Sovereign Proxy.
- NEVER create entities in compartments other than `oci-defence-demo`.
- ALWAYS write an `audit_log` row for every external API call and every chat tool invocation.
- **Scope-Disziplin:** Diese Plattform ist Daten-, KI- und Compliance-Layer. Sie führt
  **keine** Aktionen in operativen Drittsystemen aus. Keine Wirksysteme, keine C2,
  keine Feuerleitung. Anschlussfähigkeit zu Drittsystemen wird als Schnittstelle gedacht
  — nicht als Ersatz.

---

## File Organization

| Path | Use |
|------|-----|
| `/services/` | Backend Microservices (FastAPI, ML, ORDS handlers) |
| `/frontend/` | React SPA (Vite, TypeScript, Tailwind, Cesium für UC4) |
| `/db/` | Oracle 26ai Schema, Seeds, Migrations |
| `/crossplane/` | OCI IaC (Providers, XRDs, Compositions, Claims) |
| `/k8s/` | Kubernetes Manifests (Kustomize base + overlays) |
| `/oci-devops/` | Build Specs (eine `build_spec.yaml` pro Container) |
| `/datasets/` | GEOINT + UAV Testdaten + Loader-Skripte |
| `/scripts/` | Setup- und Demo-Skripte |
| `/tests/` | Unit, Integration, Swarm-Recipes |
| `/docs/` | Architektur, Runbooks, ADRs, Layer-Master-Tabelle |
| `/config/` | Swarm-Config, Agent-Defaults (kein App-Config) |
| `/examples/` | Reference-Layers, Demo-Flows, Prompt-Templates |
| `/.claude/` | Claude Code Project Config (Ruflo-managed) |
| `/.agents/` | Project-specific Agent-Definitionen |
| `/.ruflo/` | Ruflo Memory + Config |

NEVER save to root. NEVER mix Frontend- und Backend-Code in derselben Tree-Ebene
außerhalb der dedizierten Pfade.

### Konfigurations-Dateien — drei Pfade, drei Zwecke

| Datei | Zweck |
|-------|-------|
| `.env` (Repo-Root) | Backend, Crossplane, OCI CLI, alle Service-Container — geladen via `python-dotenv` / `dotenvx` / `oci-devops`-Build-Stage |
| `frontend/src/config.ts` | Cesium-Token, WebSocket-URL, Sovereign-Proxy-Base-URL — wird via `import.meta.env.VITE_*` aus `.env` befüllt |
| `config/swarm.yaml` | Ruflo-Topologie-Defaults, Agent-Defaults, Memory-Backend-Konfig |

`.env.example` und `frontend/src/config.example.ts` sind in Git, die echten Files sind in `.gitignore`.

---

## Project Architecture — 100% OCI

```
┌─────────────────────────────────────────────────┐
│  Client (Mac)                                   │
│  └── VS Code UI + OCI CLI + kubectl + SSH      │
└────────────────┬────────────────────────────────┘
                 │ Remote-SSH
┌────────────────▼────────────────────────────────┐
│  OCI Compute Instance (dev-workstation)        │
│  └── Claude Code + Ruflo Multi-Agent Swarm    │
│      Git, SQLcl, Docker, Node, Python         │
│      Instance Principal Auth (keine API Keys) │
└────────────────┬────────────────────────────────┘
                 │ git push
┌────────────────▼────────────────────────────────┐
│  OCI DevOps                                     │
│  ├── Code Repository Mirror (GitHub)           │
│  ├── Build Pipelines (7 Container-Images)      │
│  └── Deployment Pipeline → OKE                 │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│  OKE Kubernetes Cluster (sovdefence)           │
│  ├── Frontend (React SPA, Nginx)               │
│  ├── Backend: geoint, doc-intel, osint,        │
│  │            supply-chain, compliance,        │
│  │            convergence (UC7 Preview)        │
│  └── Crossplane v1.0.1 (IaC)                   │
└────────────────┬────────────────────────────────┘
                 │ ORDS + FastAPI
┌────────────────▼────────────────────────────────┐
│  Oracle 26ai ATP (Managed, Autonomous)         │
│  Vector + Graph + Spatial + JSON Duality       │
│  Label Security + Database Vault                │
└─────────────────────────────────────────────────┘

Öffentlicher Zugang: OCI Load Balancer → HTTPS
Storage: OCI Object Storage (Bilder + Dokumente)
Registry: OCI Container Registry (OCIR)
```

**Kein Edge, keine lokalen Container in Production. Keine lokalen Builds — OCI DevOps baut.**

### Architectural Rules

- Domain-Driven Design mit bounded contexts pro Use-Case-Domäne.
- Files unter 500 Zeilen halten.
- Typed interfaces für alle public APIs (TypeScript Frontend, Pydantic Backend).
- Input validation an System-Grenzen (Zod / Pydantic / ORDS-Handler-Schemas).
- Event-driven Coordination Front-zu-Back via WebSocket-Messages, niemals direkte
  DOM-Manipulation aus Chat-/LLM-Pfaden.

---

## 6 Use Cases (+ UC7 Preview)

| # | Name | Implementierung |
|---|---|---|
| 1 | **Multi-Source GEOINT & UAV-Aufklärungsfusion** | Satelliten- und Drohnen-Feeds, YOLOv8 ONNX in `services/geoint/`, AI Vector Search (HNSW) in 26ai, Spatial-Layer mit SRID 4326 |
| 2 | **Doktrin- & Lage-RAG (VS-NfD)** | OCI Generative AI Agents über klassifizierte Dokumente, Embeddings in 26ai Vector Store, Service `services/doc-intelligence/` |
| 3 | **Multi-Tenant Collaboration** | Tenant-Trennung über 26ai Label Security, Behörden-/Industrie-/Programm-Mandate isoliert, Audit pro Tenant |
| 4 | **OSINT & EMS-Lagebildfusion** | Cesium-3D-Lagebild als React-Component, OSINT-Feeds via Sovereign Proxy A/B/C, Property-Graph-Korrelation, EMS-Indikatoren, Service `services/osint-fusion/` |
| 5 | **Rüstungs-Lieferketten & Risk Scoring** | Knowledge Graph (SQL/PGQ), Sanktionsabgleich, Lieferketten-Resilienz, Service `services/supply-chain/` |
| 6 | **Compliance Automation** | NIS2 / DORA / GDPR / VS-NfD automatisiert prüfbar, liest aus zentralem `audit_log`, Service `services/compliance/` |
| 7 | *Konvergenz-Empfehler* *(Preview, v2.1+)* | KI-gestützte Empfehlungslogik in `services/convergence/` — als Read-only Recommender, **keine** Aktions-Trigger |

---

## Tech Stack

### Datenbank
- **Oracle AI Database 26ai** (NICHT 23ai, NICHT 23c)
- AI Vector Search (HNSW), Property Graph (SQL/PGQ), Spatial (`SDO_GEOMETRY`, SRID 4326),
  JSON Duality Views, Label Security, Database Vault, TxEventQ

### API Layer
- **ORDS** (Oracle REST Data Services) — AutoREST auf Duality Views, Pattern-A-Sovereign-Proxy
- **FastAPI** (Python 3.11) — ML-Services und Business Logic
- **oracledb Thin Mode** — keine Oracle-Client-Installation in Containern

### Frontend
- **React 18 + Vite + TypeScript (strict) + Tailwind CSS** — einheitliches Setup für alle UCs
- **Cesium.js** als npm-Package (`npm install cesium`), Vite-Plugin für Asset-Handling
- Leaflet (2D-Karten), D3.js (Graphen), Recharts
- `@tanstack/react-query` (Data Fetching + Caching)
- Axios mit Nginx Reverse-Proxy
- Oracle Redwood Design: `#C74634` (Red), `#1A1816` (Dark), `#F5F4F2` (Light)
- 6 Views — eine pro Use Case (UC7 als Preview-Tab)

### AI / ML
- **OCI Vision** + **OCI Document Understanding** — Inferenz-Services
- **OCI Generative AI Agents** — RAG Pipeline (UC2)
- **OCI Generative AI** Cohere Command R+ (default), Llama 3.3 70B Instruct (fallback) — UC4 Chat
- **YOLOv8 ONNX** — GEOINT Objekterkennung (Sat + UAV)
- **26ai AI Vector Search** — Embedding-basierte Suche (HNSW Index)

### Infrastructure
- **OKE** (Oracle Kubernetes Engine) — alle Workloads
- **OCI Container Registry** (OCIR) — Image Registry
- **Crossplane v1.0.1** — deklarative OCI-Provisionierung
- **OCI DevOps** — Build + Deployment Pipelines

### Security
- **Instance Principal** auf Dev-VM (keine API Keys)
- **Workload Identity** für OKE Pods → ATP
- **OCI Cloud Guard** — Threat Detection
- **Security Zones** — Compartment Guardrails
- **OCI Vault** — Key Management (alle externen API-Keys nur als OCID referenziert)
- **26ai Label Security + Database Vault** — Data Access Control

---

## Concurrency: 1 MESSAGE = ALL RELATED OPERATIONS

Ruflo's Concurrency-Regel gilt für jeden Multi-Step-Task:

- ALWAYS batch ALL todos in ONE `TodoWrite` call (5–10+ minimum).
- ALWAYS spawn ALL agents in ONE message via `Task`-Tool.
- ALWAYS batch File reads/writes/edits in ONE message.
- ALWAYS batch Terminal-Operationen in ONE Bash-Message.
- ALWAYS batch Memory Store/Retrieve in ONE message.

Initialize swarm via MCP-Tools, **execute via Claude Codes `Task`-Tool.**
**Ruflo coordinates, Claude Code creates.**

---

## Swarm Configuration

Anti-Drift Defaults für dieses Projekt:

```js
mcp__ruv-swarm__swarm_init({
  topology: "hierarchical",   // central coordination prevents drift
  maxAgents: 8,               // tight team — most workflows use 4–6
  strategy: "specialized",    // clear, non-overlapping roles
  consensus: "raft",          // leader holds authoritative state
})
```

**Memory Backend:** hybrid (SQLite + AgentDB). HNSW-Indexing aktiv. SONA Neural Learning aktiv.
Frequent Checkpoints via `post-task` Hooks. Alle Agents teilen den Memory-Namespace
`sovdefence`.

---

## Project-Specific Agents (`.agents/`)

Zusätzlich zu Ruflos Stock-Agents definiert das Projekt sechs Domain-Agents:

| Agent | Subagent type | Zweck |
|-------|--------------|-------|
| `cesium-layer-builder` | `coder` | UC4 — Generiert TypeScript Layer-Module (`frontend/src/layers/*.ts`) mit Click-to-Inspect-Convention, registriert in `LayerRegistry` |
| `sovereign-proxy-builder` | `backend-dev` | Generiert ORDS-Handler / OCI-Function / WMS-Proxy für Layer (Pattern A/B/C) |
| `pgql-schema-architect` | `system-architect` | Designt Property-Graph Entity Classes und Edges in 26ai für neue Entitäten |
| `chat-tool-author` | `coder` | Fügt Tool zum Chat-Service hinzu (Definition, Handler, System-Prompt) |
| `compliance-auditor` | `security-auditor` | Verifiziert Audit-Log-Coverage, Classification-Labelling, Vault-Nutzung |
| `demo-flow-curator` | `researcher` | 3-Minuten-Demo-Storylines die Layer/Tools an UC4–UC6-Narrative anbinden |

Definitionen in `.agents/<agent-name>.md` — Standard-Subagent-Format: Rolle, erlaubte Tools,
Output-Format, Erfolgskriterien.

### Stock-Ruflo-Agents in diesem Projekt am häufigsten genutzt

`coder`, `tester`, `reviewer`, `system-architect`, `backend-dev`, `frontend-dev`, `database`,
`infrastructure-dev`, `cicd-engineer`, `security-manager`, `security-auditor`,
`tdd-london-swarm`, `api-docs`, `researcher`, `hierarchical-coordinator`,
`performance-benchmarker`, `code-analyzer`, `production-validator`, `planner`.

---

## Agent Routing Codes

Anti-Drift-Routing für wiederkehrende Workflows. Verwendung beim Auto-Start-Swarm-Protokoll:

| Code | Task | Agents |
|------|------|--------|
| **L** | Add Cesium Layer (UC4) | coordinator, cesium-layer-builder, sovereign-proxy-builder, tester, reviewer |
| **P** | Sovereign-Proxy-Arbeit (neuer Endpoint, neues Pattern) | coordinator, sovereign-proxy-builder, security-auditor, tester |
| **G** | Property-Graph Schema-Änderung | coordinator, pgql-schema-architect, backend-dev, tester |
| **T** | Add Chat-Tool | coordinator, chat-tool-author, tester, reviewer |
| **C** | Compliance / Classification Audit | coordinator, compliance-auditor, security-architect |
| **D** | Demo-Storyline / UI-Polish | demo-flow-curator, api-docs, reviewer |
| **F** | Full Feature (Layer + Proxy + Graph + Tool + Demo) | coordinator, system-architect, alle sechs Domain-Agents |

Alle Codes nutzen **hierarchical topology + specialized strategy**. Code D darf
mesh/balanced verwenden.

### Auto-Start Swarm Protocol

Bei Task-Match in einem **einzigen** Message ausführen:

```js
// 1. Initialize swarm
mcp__ruv-swarm__swarm_init({
  topology: "hierarchical", maxAgents: 8, strategy: "specialized"
})

// 2. Spawn agents (Task tool — concurrent)
Task("Coordinator", "Coordinate the [code] workflow. Run npx ruflo hooks session-start.", "hierarchical-coordinator")
Task("Layer builder", "Build frontend/src/layers/<name>.ts (TypeScript module, click-to-inspect, register in LayerRegistry)...", "cesium-layer-builder")
Task("Proxy builder", "Build matching backend/ords/ or services/<svc>/ handler (Pattern A/B/C)...", "sovereign-proxy-builder")
Task("Schema architect", "Extend 26ai property graph with required entity classes...", "pgql-schema-architect")
Task("Tester", "Write smoke tests for layer toggle, proxy round-trip, audit row...", "tester")
Task("Compliance", "Verify audit-log coverage and Vault usage...", "compliance-auditor")

// 3. Batch todos
TodoWrite({ todos: [...] })

// 4. Store swarm state
mcp__ruv-swarm__memory_usage({
  action: "store", namespace: "sovdefence",
  key: "current-session", value: JSON.stringify({...})
})
```

### Task Complexity Detection

**INVOKE SWARM bei:**

- Multiple Files (3+).
- Neuer Layer end-to-end (Frontend + Backend + Schema).
- Cross-cutting Compliance-Änderung.
- API-Änderung mit Tests.

**SKIP SWARM bei:**

- Single Layer Toggle Tweak.
- Camera-Preset-Addition.
- Doc-Fix.
- Config-Change.

---

## Konventionen

### Datenbank
- DB ist **IMMER 26ai** — niemals 23ai oder 23c schreiben.
- VECTOR-Spalten: `VECTOR(512, FLOAT32)` als Standard.
- HNSW-Index für alle VECTOR-Spalten.
- `SDO_GEOMETRY` mit SRID 4326 (WGS84).
- Label Security Levels: `UNCLASSIFIED` (100), `RESTRICTED` (200), `CONFIDENTIAL` (300), `SECRET` (400).
- Alle DB-Zugriffe vom Frontend ausschließlich über ORDS REST.

### Compartments (Domänen-Isolation)

Demo-Compartments für Use-Case-Daten:

`GEOINT`, `HUMINT`, `SIGINT`, `LOGISTICS`, `EW`, `C_UAS`, `UAS_OPS`

### Multi-Tenant-Modell

Demo-Tenants für UC3 (Multi-Tenant Collaboration). Rein rollen-/funktionsbasiert,
keine doktrinäre Strukturlogik:

| Tenant-ID | Rolle | Live-Datenzugriff |
|-----------|-------|-------------------|
| `TENANT_GOV_PRIMARY` | Behördlicher Hauptnutzer | voll |
| `TENANT_GOV_RESTRICTED` | Behördlicher Nutzer mit eingeschränktem Zugriff | eingeschränkt |
| `TENANT_PROGRAM_LEAD` | Programmverantwortliche Stelle | mandatsbezogen |
| `TENANT_INDUSTRY_A` | Industrie-Tenant A | mandatsbezogen |
| `TENANT_INDUSTRY_B` | Industrie-Tenant B (z. B. Sandbox-Profil) | sandbox |

### Code
- **Deutsche UI-Texte**, **englischer Code** + Kommentare.
- **ORDS REST** für alle DB-Zugriffe (kein direktes DB-Connect vom Frontend).
- **FastAPI** für ML-Services und Business Logic.
- **TypeScript strict mode** im Frontend — keine `*.js`-Files in `frontend/src/`.
- Technische Abkürzungen in UI-Strings konsistent: `UAV`, `cUAS`, `EMS`, `OSINT`, `GEOINT`.
  Doktrin-/Strategievokabular gehört nicht in Code oder UI-Strings, sondern in
  `docs/GLOSSARY.md` (optional).

### Infrastructure
- Region + OCIDs + Credentials **immer aus `.env`**, niemals hardcoden.
- Crossplane nutzt `.yaml.tmpl` Templates + `envsubst`.
- Keine lokalen Docker-Builds — immer via OCI DevOps.
- K8s-Manifests via Kustomize (base + overlays).

### Security
- **Instance Principal** auf Dev-VM (kein `~/.oci/config` für Scripts).
- **Workload Identity** für OKE-Pods (keine DB-Secrets in Umgebungsvariablen).
- **OCI Vault** für alle sensiblen Werte (API-Keys nur als OCID-Referenz).

### Git
- Branch-Strategie: `main` (stable) + `develop` (working).
- Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`.
- Push auf `main` triggert automatischen Build + Deploy via OCI DevOps.
- Tags: `v<major>.<minor>.<patch>` für Releases.

---

## Sovereign Proxy — Three Backend Patterns

Jeder externe API-Aufruf folgt einem von drei Patterns. Mapping pro Layer in
`docs/layers.md`.

| Pattern | Use | Mechanik |
|---------|-----|----------|
| **A — REST-Poll** | Satelliten, Civil/Mil Flights, GPS-Jamming, Seismic, Traffic, CCTV, Ports | ORDS-Handler in 26ai: cache-check → external call → cache-write → audit-log |
| **B — WebSocket Multiplexer** | Maritime AIS | Eine Function/Container-Instance hält eine Upstream-Connection, fan-out an N Browser, Vault-Key-Only |
| **C — WMS Tile Reverse Proxy** | Weather Radar, Sentinel | API-Gateway vor Public WMS, Tile-Cache in Object-Storage-Bucket `osint-tile-cache` |

Free-Tier-API-Keys (AIS Stream, Sentinel Instance ID, OpenSky optional Account) **liegen in
OCI Vault** unter dem `oci-defence-demo`-Compartment, runtime-zugriff per OCID.

---

## UC4 — Cesium Layer Pattern (TypeScript Module)

Jedes Layer-File in `frontend/src/layers/` ist ein TypeScript-Modul, das die
`LayerModule`-Schnittstelle implementiert und im zentralen `LayerRegistry`
registriert wird.

### Schnittstellen (`frontend/src/layers/types.ts`)

```ts
import type { Viewer } from 'cesium';

export type Domain   = 'air' | 'maritime' | 'ew' | 'surface' | 'environment' | 'imagery' | 'fusion';
export type Pattern  = 'A' | 'B' | 'C' | 'sovereign';
export type Classification = 'OPEN' | 'VS-NfD' | 'VS-VERTRAULICH' | 'GEHEIM';

export interface LayerModule {
  name:    string;
  domain:  Domain;
  pattern: Pattern;
  enable(viewer:  Viewer): Promise<void>;
  disable(viewer: Viewer): void;
}

export interface WvMetaItem { key: string; val: string }

/** Wird an PointPrimitive/Billboard als plain object angehängt
 *  oder direkt am Cesium.Entity gesetzt. */
export interface WvPickable {
  _wvType:           string;     // 'vessel' | 'aircraft' | 'satellite' | 'port' | 'seismic' | 'jamming_zone' | 'fusion_node' | …
  _wvMeta:           WvMetaItem[];
  _wvLat:            number;
  _wvLon:            number;
  _wvClassification: Classification;
  _wvSources?:       string[];   // für Fusion-Layer
}
```

### Layer-Modul Skelett

```ts
// frontend/src/layers/maritime.ts
import type { Viewer } from 'cesium';
import type { LayerModule, WvPickable } from './types';
import { setStatus, updateCount } from '@/state/layerControls';

const billboards: any[] = [];
let socket: WebSocket | null = null;

export const maritime: LayerModule = {
  name:    'maritime',
  domain:  'maritime',
  pattern: 'B',

  async enable(viewer) {
    setStatus('Maritime AIS connecting…');
    socket = new WebSocket(`${import.meta.env.VITE_WS_URL}/ais`);
    socket.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      // … Billboard erzeugen, _wv*-Properties setzen, in billboards[] pushen
      viewer.scene.requestRender();
      updateCount('maritime', billboards.length);
    };
  },

  disable(viewer) {
    socket?.close();
    billboards.forEach((b) => viewer.entities.remove(b));
    billboards.length = 0;
    viewer.scene.requestRender();
  },
};
```

### LayerRegistry (`frontend/src/layers/registry.ts`)

```ts
import type { LayerModule } from './types';
import { maritime } from './maritime';
import { jamming  } from './jamming';
// … weitere Imports

export const layerRegistry: Record<string, LayerModule> = {
  maritime,
  jamming,
  // …
};
```

### Layer-Toggle State (`frontend/src/state/layerControls.ts`)

Zustand-Store oder React-Context. Komponenten dispatchen `enable(name)` /
`disable(name)`, der State-Manager ruft `layerRegistry[name].enable(viewer)` /
`.disable(viewer)`. Status-Bar und Count-Badges abonnieren denselben Store
(`setStatus`, `updateCount` werden vom Layer-Modul direkt aufgerufen, sie
sind keine globalen `WV.Controls` mehr).

### Pflicht-Konventionen

- `requestRenderMode: true` ist im `Viewer`-Init gesetzt — nach jeder
  Mutation an Entities/Billboards `viewer.scene.requestRender()` aufrufen.
- Click-to-Inspect: jede gepickte Entity/Billboard trägt ein `WvPickable`-
  Objekt (siehe `types.ts`).
- Der `disable`-Pfad muss ALLE Entities, Listener, Sockets, Intervalle
  sauber entfernen — keine Memory-Leaks bei wiederholtem Toggle.
- Daten **ausschließlich** vom Sovereign-Proxy-Endpoint, niemals direkt
  von Public-APIs oder mit Klartext-Keys.

### Layer Domain Groups (UI)

UI gruppiert nach Domäne, nicht nach API-Typ:

- **Air Domain** — Satellites, Civil Flights, Mil Flights
- **Maritime Domain** — Maritime AIS, Global Ports
- **Electromagnetic / EW** — GPS Jamming
- **Surface / Urban** — Street Traffic, CCTV
- **Environment** — Weather Radar, Seismic
- **Imagery** — Sentinel
- **Sovereign Fusion** (eigene Layer, kein Public API) — `graph-fusion`,
  `doctrine-pins`, `geoint-overlay`, `ems-spectrum`

**VS-NfD-Display-Mode** hebt Sovereign-Fusion-Gruppe hervor und dimmt alle Public-OSINT-Layer.

---

## UC4 — Chat-Service Tool Calling

WebSocket-Server auf OKE spricht mit OCI Generative AI (Cohere Command R+ default,
Llama 3.3 70B Instruct fallback). Vier Tools:

| Tool | Backend-Execution |
|------|-------------------|
| `pgql_query` | ORDS-Handler gegen 26ai Property Graph (read-only) |
| `vector_search` | 26ai AI Vector Search |
| `select_ai` | 26ai Select AI (NL → SQL) |
| `map_action` | **Relay an Frontend** — wird **nicht** im Backend ausgeführt |

`map_action` wird als WebSocket-Message an den ursprünglichen Browser weitergereicht.
Frontend-`MapActions`-Dispatcher (TypeScript, typed) führt aus: `flyto`, `enable_layer`,
`highlight_entities`, `draw_zone`. **Das LLM kann keine DOM-/Cesium-API außerhalb
dieser vier typed Wrapper erreichen.**

`collectMapContext()` läuft vor jedem Chat-Send: aktive Layer, Camera-BBox,
last-clicked Entity, aktueller Display-Mode. Wird in den System-Prompt injiziert.

---

## Audit & Compliance (UC6 Hook)

Jeder externe API-Call und jede Chat-Tool-Invocation schreibt:

```sql
CREATE TABLE audit_log (
  ts             TIMESTAMP DEFAULT SYSTIMESTAMP,
  user_id        VARCHAR2(200),
  tenant_id      VARCHAR2(50),
  action         VARCHAR2(50),     -- 'layer_fetch' | 'tool_call' | 'map_action'
  resource       VARCHAR2(200),
  classification VARCHAR2(20),     -- 'OPEN' | 'VS-NfD' | höher
  details        JSON
);
```

UC6 Compliance Automation liest aus dieser Tabelle und generiert
NIS2 / DORA / DSGVO / VS-NfD-Reports. Der `compliance-auditor`-Agent stellt sicher,
dass kein Code-Pfad diesen Audit umgeht.

---

## Verzeichnisstruktur

```
oci-defence-demo/
├── crossplane/              # OCI IaC
│   ├── providers/           # OCI Provider v1.0.1 + Workload Identity
│   ├── xrds/                # SovereignDefence Composite Resource Definition
│   ├── compositions/        # network, database, storage, oke
│   └── claims/              # full-environment.yaml.tmpl
├── db/                      # Oracle 26ai
│   ├── schema/              # 01_users.sql … 08_ords.sql
│   ├── seed/                # Demo-Daten (Tenant × Compartment)
│   └── migrations/          # Schema-Evolution
├── services/                # Backend Microservices (FastAPI)
│   ├── geoint/              # UC1 Sat + UAV Aufklärungsfusion
│   ├── doc-intelligence/    # UC2 Doktrin- & Lage-RAG
│   ├── osint-fusion/        # UC4 OSINT + EMS + Graph Correlation
│   ├── supply-chain/        # UC5 Knowledge Graph + Risk Scoring
│   ├── compliance/          # UC6 NIS2/DORA/GDPR/VS-NfD Checks
│   └── convergence/         # UC7 Preview — Recommender (read-only)
├── frontend/                # React SPA (Vite + TypeScript)
│   ├── src/
│   │   ├── components/      # Layout, Sidebar, TopBar
│   │   ├── views/           # 6 Use-Case-Views (UC7 Preview-Tab)
│   │   ├── layers/          # UC4 Cesium TypeScript-Module
│   │   │   ├── types.ts
│   │   │   ├── registry.ts
│   │   │   ├── maritime.ts
│   │   │   └── …
│   │   ├── chat/            # UC4 Chat-Panel + typed map_action-Relay
│   │   ├── state/           # Zustand-Stores (layerControls, …)
│   │   ├── services/        # API Clients (Axios)
│   │   ├── hooks/           # React-Query-Hooks
│   │   ├── types/           # Shared TypeScript Interfaces
│   │   ├── config.ts        # gitignored
│   │   └── config.example.ts
│   ├── vite.config.ts
│   ├── Dockerfile           # Multi-Stage: Vite Build → Nginx
│   └── nginx.conf           # SPA Routing + Reverse Proxy
├── datasets/                # GEOINT + UAV Testdaten
│   ├── scripts/             # Download + Upload nach OCI Object Storage
│   └── sample_images/       # Demo-Bilder
├── k8s/                     # Kubernetes Manifests
│   ├── base/                # Deployments, Services, Ingress
│   └── overlays/prod/       # Production-Overrides
├── oci-devops/              # CI/CD Build Specs
│   └── build-specs/         # Pro Container eine build_spec.yaml
├── scripts/                 # Bash Scripts
│   ├── setup-oci.sh         # Tenancy + Compartment + Resources
│   ├── setup-devops.sh      # OCI DevOps Project + Pipelines
│   ├── setup-security.sh    # Cloud Guard + Security Zones
│   └── demo-check.sh        # E2E Endpoint-Check
├── docs/                    # Dokumentation
│   ├── ARCHITECTURE.md      # C4-Diagramme (Mermaid)
│   ├── RUNBOOK.md           # Demo-Ablauf
│   ├── layers.md            # UC4 Layer-Master-Tabelle
│   ├── skills-roadmap.md    # Plan für sechs neue Skills
│   ├── adrs/                # Architecture Decision Records
│   │   └── 0001-frontend-bundler.md
│   └── api/                 # OpenAPI-Specs pro Service
├── config/                  # Swarm + Agent Defaults
│   └── swarm.yaml
├── .agents/                 # Project-specific Subagent-Definitionen
├── .claude/skills/          # Custom Claude Code Skills
├── .ruflo/                  # Ruflo Config + Memory + Agents
├── CLAUDE.md                # DIESE DATEI — Projektkontext
├── .env.example             # Template für .env (kein Secret in Git)
└── README.md                # Projekt-Übersicht
```

---

## Headless Background Workers

`claude -p` für parallele Arbeit, die nicht die Haupt-Session braucht:

```bash
# Layer-Scan (read-only, low budget)
claude -p --model haiku --max-budget-usd 0.10 \
  --allowedTools "Read,Grep,Glob" \
  "List all frontend/src/layers/*.ts files missing _wvClassification"

# Demo-Flow-Drafts (parallel)
claude -p "Draft 3-Minuten Demo-Flow für graph-fusion Layer" &
claude -p "Draft 3-Minuten Demo-Flow für VS-NfD Mode Toggle" &
wait
```

Budget-Caps verhindern Runaway-Sessions während langer Ruflo-Orchestrationen.

---

## Local Dev Setup

```bash
# Frontend
cd frontend
cp src/config.example.ts src/config.ts
# CESIUM_TOKEN, VITE_SOVEREIGN_PROXY_URL, VITE_WS_URL setzen
npm install
npm run dev                 # Vite dev-server auf http://localhost:5173

# Backend (pro Service)
cd services/<service>
uvicorn app:app --reload    # FastAPI dev-server auf http://localhost:8000

# OCI Auth
oci session authenticate --profile DEFENCE_DEMO

# Ruflo init (first time only)
npx ruflo@alpha init --wizard
npx ruflo@alpha daemon start
npx ruflo@alpha doctor --fix
```

---

## Environment Variables

```
# OCI Tenancy / Region
OCI_REGION=eu-frankfurt-1
OCI_COMPARTMENT_OCID=ocid1.compartment.oc1..oci-defence-demo
OCI_PROFILE=DEFENCE_DEMO

# Vault OCIDs (NIE die Secret-Werte selbst)
VAULT_AIS_STREAM_KEY_OCID=ocid1.vaultsecret.oc1...
VAULT_SENTINEL_INSTANCE_ID_OCID=ocid1.vaultsecret.oc1...
VAULT_OPENSKY_PASS_OCID=ocid1.vaultsecret.oc1...

# 26ai
DB_CONNECTION_NAME=defence_demo_high
DB_USER=osint_app

# Chat-Service (UC4)
CHAT_MODEL=cohere.command-r-plus
CHAT_FALLBACK_MODEL=meta.llama-3.3-70b-instruct

# Frontend (Vite — Prefix VITE_ für Browser-Bundling)
VITE_CESIUM_TOKEN=...
VITE_SOVEREIGN_PROXY_URL=https://api.sovdefence.example/proxy
VITE_WS_URL=wss://api.sovdefence.example/ws

# Ruflo
RUFLO_LOG_LEVEL=info
RUFLO_MEMORY_BACKEND=hybrid
RUFLO_MEMORY_PATH=./data/memory
```

---

## Skills

### Installiert (`.skill.zip`)

- **`oracle-26ai-schema`** — Schema-Konventionen, Spatial, Vector. **Erweiterung geplant**
  um Property-Graph-Entity-Classes für OSINT-Entitäten (`Vessel`, `Aircraft`, `Satellite`,
  `Port`, `JammingZone`, `SeismicEvent`, `FusionNode`) und Relationen (`MENTIONED_IN`,
  `CORRELATED_WITH`, `WITHIN_ZONE`, `FUSED_WITH`).
- **`oci-crossplane`** — Crossplane mit OCI Provider v1.0.1.
- **`ords-rest-api`** — ORDS-Handler-Pattern; Pattern-A-Foundation.

### Geplant (siehe `docs/skills-roadmap.md`)

Sechs weitere Skills sind in `docs/skills-roadmap.md` spezifiziert und werden iterativ
gebaut. Reihenfolge dort priorisiert nach Demo-Hebelwirkung:
`cesium-layer-pattern`, `osint-sovereign-proxy`, `oci-genai-tool-calling`,
`26ai-property-graph-osint`, `vs-nfd-classification`, `ruflo-osint-recipes`.

### Weitere Tools

- **obra/superpowers** — `/brainstorm`, `/write-plan`, `/execute-plan`, `/review`, `/simplify`
- **SPARC Methodology** — built-in in Ruflo (Specification → Pseudocode → Architecture
  → Refinement → Completion)

### MCP Server

- `filesystem` — File-Operations für Agents
- `github` — Issues, PRs, Repo-Suche
- `oracle-db` — Direct SQL Queries (optional)

---

## Demo Principles

- **Functional first, polish second.** Maritime + GPS-Jamming als erstes Pattern-A/B-Paar
  liefert die erste storyfähige Demo („welche Schiffe haben Jamming-Korridore durchquert?").
- **Sovereign Fusion vor Public OSINT.** `graph-fusion.ts` schlägt drei weitere Public-Layer
  als Differenzierungsargument.
- **VS-NfD-Mode in jeder Demo.** 30 Sekunden, schließt jede Demo mit dem
  „kein Internet, läuft trotzdem"-Reveal.
- **Audit-Log auf dem Bildschirm.** UC6 verkauft sich live, nicht in Slides.

---

## Quick Reference

- **Ruflo coordinates, Claude Code creates.**
- `26ai`, niemals `23ai` / `23c`. `eu-frankfurt-1` aus `.env`, niemals hardcoded.
  Compartment `oci-defence-demo` only.
- Sovereign-Proxy-Patterns A/B/C — jeder externe Call läuft durch eines davon.
- Chat-Tools: vier — `pgql_query`, `vector_search`, `select_ai`, `map_action` (Relay).
- Layer-Module: TypeScript-Module in `frontend/src/layers/`, registriert in
  `LayerRegistry`, Click-to-Inspect mit `WvPickable`-Interface, `requestRender()`
  nach Mutationen.
- Audit-Row für alles Externe. Keine Ausnahmen.
- Plattform = Daten / KI / Compliance. **Keine** Wirksysteme, **keine** C2,
  **keine** Aktions-Trigger.
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
