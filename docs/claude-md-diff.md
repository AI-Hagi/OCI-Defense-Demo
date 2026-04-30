# Diff-Report: CLAUDE_DEV9.md vs. _proposed/CLAUDE.md

> **Hinweis:** Es existiert keine `CLAUDE_DEV7.md` im Root — verglichen wurde
> `/home/ubuntu/oci-defense-demo/CLAUDE_DEV9.md` (329 Zeilen, projekt-strategisch,
> umfasst alle 7 Use Cases) gegen `/home/ubuntu/oci-defense-demo/_proposed/CLAUDE.md`
> (493 Zeilen, fokussiert auf UC4 "OSINT & EMS-Lagebildfusion" als Cesium-Frontend).

> **Scope-Asymmetrie wichtig:** Die neue Datei ist **kein** 1:1-Ersatz, sondern
> eine deutlich engere, operativ dichtere Sicht auf einen Use Case. Ein Merge
> sollte daher additiv gedacht werden, nicht ersetzend.

---

## Übernehmen aus `_proposed/CLAUDE.md` (NEU oder besser)

- **Behavioral Rules (Always Enforced)** (Zeilen 13–34) — explizite Negativ- und Positivregeln,
  inkl. projekt-spezifischer Härtung (kein 23ai/23c, kein hardcoded Region, kein API-Key in
  browser-reachable Files, kein direkter Public-API-Call aus Layer-Files, `osint_audit`-Pflicht).
  Fehlen in `CLAUDE_DEV9.md` als enforceable Regelblock.
- **File Organization als Tabelle** (Zeilen 37–53) — präziser, Ruflo-konform, mit klarer
  Trennung `/src` vs `/backend` vs `/.agents` und „NEVER save to root".
- **Concurrency-Block „1 MESSAGE = ALL RELATED OPERATIONS"** (Zeilen 92–103) — gehört in jede
  Ruflo-orientierte CLAUDE.md, fehlt aktuell komplett.
- **Swarm Configuration mit konkretem MCP-Snippet** (Zeilen 106–119) — `topology: hierarchical`,
  `maxAgents: 8`, `strategy: specialized`, `consensus: raft`, hybrid Memory + HNSW + SONA. Das
  ist der projektweite Anti-Drift-Default und sollte in die Haupt-CLAUDE.md gehoben werden.
- **Project-Specific Agents (`.agents/`-Pattern)** (Zeilen 123–141) — sechs Domain-Agents
  (`cesium-layer-builder`, `sovereign-proxy-builder`, `pgql-schema-architect`,
  `chat-tool-author`, `compliance-auditor`, `demo-flow-curator`). Strukturell überlegen
  gegenüber der reinen Stock-Agent-Liste in DEV9 — sollte zumindest der `compliance-auditor`
  und `pgql-schema-architect` projektweit übernommen werden.
- **Agent Routing Codes L/P/G/T/C/D/F mit Auto-Start Swarm Protocol** (Zeilen 144–203) —
  reproduzierbares Routing-Pattern. DEV9 hat nur eine flache Agent-Liste ohne Trigger-Logik.
- **Task Complexity Detection (INVOKE / SKIP)** (Zeilen 188–203) — verhindert Swarm-Overhead
  bei Trivialtasks. Fehlt in DEV9.
- **Layer Pattern (IIFE) + Click-to-inspect Convention** (Zeilen 206–230) — UC4-Implementations-
  vertrag. Gehört in eine UC4-spezifische Sektion, nicht in die Top-Level-CLAUDE.md.
- **Sovereign Proxy — Three Backend Patterns A/B/C** (Zeilen 233–243) — wertvoll, projektweit
  konsumierbar (gilt analog für UC1 GEOINT-Feeds, UC5 Sanktionsfeeds).
- **Chat-Service — Tool Calling (4 Tools, `map_action` als Frontend-Relay)** (Zeilen 247–261) —
  Sicherheits-/Architektur-Vertrag (LLM kann DOM/Cesium nur über vier Wrapper erreichen).
  Wichtig für Compliance — übernehmen.
- **Audit-Schema `osint_audit`** (Zeilen 388–404) — konkretes DDL für UC6-Hook. Gehört
  entweder hier oder als Verweis nach `db/schema/`.
- **Headless Background Workers mit `claude -p` + `--max-budget-usd`** (Zeilen 369–384) —
  praktischer Ruflo-Workflow, fehlt komplett in DEV9.
- **Quick Reference (Zeilen 482–489)** — kompakter Cheat-Sheet-Block am Ende, gut für
  Drift-Prävention.

---

## Behalten aus `CLAUDE_DEV9.md` (projekt-spezifisch, nicht in der neuen)

- **Projekt-Header & Owner-Block** (Zeilen 1–11) — DICE-EU-Bezug, Owner-Mail. Identitäts-
  notwendig, fehlt in der neuen Datei.
- **Vollständige Liste der 7 Use Cases als Tabelle** (Zeilen 41–51) — die neue Datei kennt
  nur UC4 + Querverweise auf UC1/UC2/UC5/UC6. Top-Level-CLAUDE.md muss alle 7 abbilden.
- **Architektur-ASCII-Diagramm Mac → OCI Compute → DevOps → OKE → 26ai** (Zeilen 55–95) —
  vollständige Deployment-Topologie inkl. Region (`eu-frankfurt-1`), Compartment, kein Edge.
  Die neue Datei hat nur ein 3-Tier-Mini-Diagramm für UC4.
- **Tech-Stack-Sektionen für Datenbank / API / Frontend / AI-ML / Infrastructure / Security**
  (Zeilen 103–142) — die neue Datei hat eine kürzere UC4-Tech-Stack-Tabelle, ersetzt das
  nicht.
- **Verzeichnisstruktur des Gesamt-Repos** (Zeilen 252–305) — `services/` (6 Microservices),
  `db/schema/`, `crossplane/xrds/`, `oci-devops/build-specs/`, `datasets/`. Die neue Datei
  beschreibt nur die UC4-Subtree.
- **Konventionen-Block** (Zeilen 201–249) — speziell:
  - VECTOR(512, FLOAT32) + HNSW als Standard
  - SDO_GEOMETRY SRID 4326
  - Label Security Levels U/R/C/S mit numerischen Codes
  - Compartments-Liste (`GEOINT, HUMINT, SIGINT, LOGISTICS, EW, C_UAS, UAS_OPS`)
  - Defense-Terminologie-Disziplin (LV/BV, MDO, A2AD, EMS, cUAS, LMS, UGV, UAV)
  - Git-Branch-Strategie (`main` + `develop`, Conventional Commits, Tag-Schema)
- **Scope-Disziplin „keine Wirksysteme, keine C2, keine Feuerleitung"** (Zeilen 224–231) —
  rechtlich/positionierungs-kritisch. Muss in jeder Top-Level-CLAUDE.md stehen, fehlt in der
  neuen Datei (die dort nur einen impliziten Read-only-Vertrag hat).
- **Multi-Agent-Stock-Liste (12 Agents)** (Zeilen 153–166) mit `infrastructure-dev`,
  `cicd-engineer`, `performance-benchmarker`, `database` — die neue Datei nennt diese nicht,
  arbeitet aber implizit damit.
- **Skills-Inventar (3 Custom + obra/superpowers + Antigravity)** (Zeilen 168–173) — projekt-
  weiter Werkzeugkasten.

---

## Konflikte (Entscheidung nötig)

- **Topology / Coordination — DEV9: keine Aussage; neu: hierarchical + raft.**
  → **Empfehlung:** den Block aus der neuen Datei übernehmen. Steht zudem in der
  bereits existierenden `/home/ubuntu/oci-defense-demo/CLAUDE.md` (RuFlo V3 Config) konsistent
  drin → keine Reibung.

- **Ruflo-Versionsangabe — DEV9: ohne Version; neu: „Ruflo v3.5"; bestehende Root-CLAUDE.md:
  „RuFlo V3".**
  → **Empfehlung:** auf eine Variante konsolidieren („Ruflo v3.5") und in beiden Files
  identisch halten. Inkonsistenz erzeugt Verwirrung beim CLI-Versions-Pin.

- **Init-Befehl — neu: `npx ruflo@alpha init --wizard`; bestehende Root-CLAUDE.md:
  `npx @claude-flow/cli@latest init --wizard`.**
  → **Empfehlung:** **Klären, welches Paket gilt.** Beide CLIs gleichzeitig zu pflegen ist
  fragil. Wenn `ruflo` der echte Orchestrator ist (so beschrieben in DEV9), sollte
  `@claude-flow/cli` nicht in CLAUDE.md zementiert sein. Diese Frage betrifft die ganze
  Repo-Identität, nicht nur dieses Diff.

- **MCP-Tool-Namespace — neu: `mcp__ruv-swarm__*`; bestehende Root-CLAUDE.md: `swarm_init`,
  `agent_spawn` (ohne Namespace, MCP-Tool-IDs).**
  → **Empfehlung:** Eine Variante wählen. Wenn beide MCP-Server gleichzeitig laufen, beide
  dokumentieren mit klarer Trennung.

- **Demo-Tenants `ACTIVE_FORCE` / `RESERVE_FORCE` — DEV9: harte Tenant-Namen; neu: nicht
  erwähnt.**
  → **Empfehlung:** **Umbenennen.** Die Begriffe „Active Force / Reserve Force" sind
  doktrin-belastete Strukturbegriffe (siehe „Hübner-Reste" unten). Neutralere Tenant-Namen
  vorschlagen, z. B. `TENANT_PRIMARY`, `TENANT_RESERVE_OPS`, oder rein
  rollen-basiert: `TENANT_GOV`, `TENANT_INDUSTRY_A`, `TENANT_INDUSTRY_B`. Die *technische*
  Funktion (Aktiv vs. nichtaktiv) bleibt dadurch unverändert.

- **„7 Use Cases" vs. „6 Use Cases" — DEV9: 7 (mit UC7 Konvergenz-Empfehler als Preview);
  bestehende `/home/ubuntu/CLAUDE.md` (User-Level): 6.**
  → **Empfehlung:** Auf 7 vereinheitlichen, UC7 explizit als „Preview, v2.1+" markieren
  (DEV9-Wording übernehmen). Falls UC7 wegen Scope-Disziplin (siehe unten) gestrichen wird,
  in beiden Files konsistent zurück auf 6.

- **Compartments-Liste — DEV9: enthält `C_UAS`, `UAS_OPS`; neu: nicht erwähnt.**
  → **Empfehlung:** `C_UAS` ist UC1/UC4-konform und bleibt. `UAS_OPS` (UAV-Operationen) ist
  borderline operativ → prüfen, ob das in der „keine C2/keine Wirksysteme"-Disziplin bleiben
  soll. Im Zweifel umbenennen zu `UAS_DATA` (reine Daten-/Telemetrie-Senke).

- **`docs/ECOSYSTEM.md`-Referenzen (Defense-Innovation-Ecosystem-Block)** — DEV9 listet
  konkrete Ökosystem-Anker; neu: nicht erwähnt.
  → **Empfehlung:** Block behalten, aber von „Anschlussfähigkeit" auf neutrale Begriffe
  reduzieren (siehe „Hübner-Reste" unten). Keine konkreten Programm-Namen / Behörden-Kürzel
  in CLAUDE.md, nur in `docs/ECOSYSTEM.md`.

- **Owner-Mail in DEV9: `markus.hagenkoetter@oracle.com`; User-Profil in dieser Session:
  `markus.hagenkoetter@gmail.com`.**
  → **Empfehlung:** klären welche im Public-Repo sichtbar sein soll. Wenn das Repo nach außen
  geht, ist `@oracle.com` problematisch (impliziert offizielle Oracle-Position).

---

## Hübner-Reste zu entfernen

> Wörtlich kommen weder „Hübner", „HF1–HF6" noch „Blume des Krieges" in `CLAUDE_DEV9.md`
> vor. Die folgenden Stellen sind aber **strukturell** doktrinanknüpfende Reste, die sich am
> Hübner'schen Fähigkeits-/Strukturmodell orientieren und für eine sauber positionierte,
> data-/AI-fokussierte Plattform-CLAUDE.md zu generisch oder zu doktrinlastig sind:

- **Zeilen 13–18 — Sektion „Strategischer Bezug" mit „Data-centric warfare", „DLBO",
  „Software Defined Defence (SDD)"**
  → entfernen oder in `docs/POSITIONING.md` auslagern. CLAUDE.md ist Build-Kontext, nicht
  Strategie-Papier.

- **Zeilen 20–30 — FB1–FB5-Tabelle (Fähigkeitsbereiche) inkl. Zeile „übergreifend |
  Aktiv-/Reserve-Strukturen, Mobilisierungsfähigkeit | UC3 Multi-Tenant DICE-EU"**
  → komplette Tabelle aus CLAUDE.md entfernen. Use-Case-Begründung gehört in
  `docs/ARCHITECTURE.md` oder `docs/USECASES.md`. Die UC↔Capability-Zuordnung verleitet
  Agents dazu, militärische Fähigkeits-Sprache in Code-Kommentare zu tragen.

- **Zeilen 32–37 — Positionierungs-Disziplin-Absatz („simuliert keine Wirksysteme, keine
  C2, keine Feuerleitung … BMS, KI-gestützte Aufklärungssysteme, federated mission
  networking")**
  → **Kernaussage behalten** (Scope-Disziplin ist wichtig), aber **Begriffe entschärfen**:
  „BMS / Feuerleitung / federated mission networking" sind harte Doktrinbegriffe. Stattdessen
  formulieren als: „Diese Plattform ist ein Daten-, KI- und Compliance-Layer. Sie führt
  keine Aktionen in operativen Drittsystemen aus."

- **Zeile 30, 47, 211–212 — „Aktiv-/Reserve-Strukturen", `ACTIVE_FORCE`, `RESERVE_FORCE`,
  `PROGRAM_LEAD`**
  → Aktiv/Reserve ist klassische Hübner'sche Strukturkategorie. Tenant-IDs umbenennen
  (Vorschlag siehe „Konflikte" oben). „Aktiv-/Reserve-/Contractor-Trennung" als
  Beschreibungstext durch „Behörden-/Industrie-/Reserve-Tenant-Trennung" oder rein
  rollenbasiert ersetzen.

- **Zeile 221–222 — „Defense-Terminologie in UI-Strings konsistent: NATO-Abkürzungen
  korrekt (LV/BV, MDO, A2AD, EMS, cUAS, LMS, UGV, UAV)"**
  → **LV/BV (Landes-/Bündnisverteidigung), MDO, A2AD, LMS** sind Hübner-/Doktrin-Vokabular,
  in einer Build-Konfig-Datei deplatziert. **Empfehlung:** auf rein technische
  Abkürzungen reduzieren (`UAV`, `cUAS`, `EMS`, `OSINT`) und den Rest in einen optionalen
  `docs/GLOSSARY.md` verschieben. Agents brauchen LV/BV nicht für Code-Generierung.

- **Zeilen 309–327 — gesamte Sektion „Anschlussfähigkeit (Defense Innovation Ecosystem)"
  mit Bullets zu „Experimentalserien", „C2- und Battle-Management-Systeme",
  „Federated Mission Networking", „Drohnen- und cUAS-Koordination",
  „Ausbildungs- und Trainingseinrichtungen", „Innovations- und Technologiezentren",
  „Cyber Innovation Hub"**
  → komplett aus CLAUDE.md raus. Ist ein Stakeholder-/Vertriebs-Narrativ und gehört in
  `docs/ECOSYSTEM.md`. CLAUDE.md sollte den Agents nicht erzählen, an welche
  Behördenstrukturen man andocken will — das färbt Code-Output und Variablennamen.

- **Zeile 7 — „Inspiriert von Oracles DICE (Defence Industrial Base Isolated Cloud
  Environment, März 2026)"**
  → behalten okay, aber das Datum „März 2026" ist eine harte Aussage — verifizieren oder
  weicher formulieren („siehe Oracle DICE Announcement, 2026").

- **Zeile 17 — „komplementär zu nationalen Programmen wie DLBO und Software Defined
  Defence (SDD)"**
  → DLBO und SDD sind konkrete Programmbezeichnungen, mit denen sich das Projekt nicht in
  einer Build-Konfig öffentlich verheiraten sollte. Streichen oder in `docs/POSITIONING.md`.

---

## Empfohlene Konsolidierungs-Strategie

1. **Eine schlanke Top-Level `CLAUDE.md`** behält aus DEV9: 7 Use Cases (Tabelle),
   Architektur-Diagramm, Tech-Stack, Verzeichnisstruktur, Scope-Disziplin (entschärft),
   Konventionen-Block, Stock-Agents-Liste.
2. **Übernimmt aus `_proposed/CLAUDE.md`:** Behavioral Rules (enforceable), File Org,
   Concurrency-Block, Swarm Config-Snippet, Routing Codes, Task Complexity Detection,
   Headless Worker-Pattern, Quick Reference.
3. **Lagert nach `docs/` aus:** Strategischer Bezug, FB-Mapping, Defense-Innovation-
   Ecosystem-Bullets, Doktringlossar, Positionierungs-Narrativ.
4. **UC4-spezifisches** (Layer-IIFE-Pattern, Sovereign-Proxy A/B/C, Chat-Tools, `osint_audit`-
   DDL, `.agents/`-Domain-Agents) **in eine eigene `docs/uc4-osint-lagebild.md` oder
   `src/CLAUDE.md`**, nicht in die Top-Level-Datei mischen — sonst überschattet UC4 den
   Rest der Plattform.
5. **Tenant-IDs umbenennen** in einem separaten Cleanup-Commit, da das auch Seed-Data und
   Label-Security-Migrations betrifft.

---

*Generiert am 2026-04-28. Keine Quelldateien wurden geändert.*
