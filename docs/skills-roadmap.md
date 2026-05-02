# Skills Roadmap — Sovereign OSINT Lagebild

> Sechs neue Skills zusätzlich zu den drei bestehenden
> (`oracle-26ai-schema`, `oci-crossplane`, `ords-rest-api`).
>
> Format: jede Skill als `.skill.zip` für Claude Code. Skills werden
> primär von den projekt-spezifischen Ruflo-Agents (`.agents/`)
> referenziert und beim `pre-task`-Hook geladen. Skill-Inhalte sollten
> auf Ruflo's Anti-Drift-Defaults abgestimmt sein (knapp, eindeutig,
> mit Verifikations-Schritten).

---

## 1. `cesium-layer-pattern`

**Zweck.** Garantiert, dass jedes neue Layer-File dem IIFE-Pattern aus
WorldView folgt, mit `requestRenderMode: true`-konformer Render-Logik
und der projektweiten Click-to-Inspect-Konvention. Wird primär vom
`cesium-layer-builder`-Agent geladen.

**Inhalt.**

- IIFE-Skelett: `WV.layers.X = (() => ({ enable, disable }))()`
- Code-Templates pro Cesium-Primitive:
  - `PointPrimitive`-Layer (Beispiel: Seismic, Satelliten-Punkte)
  - `Billboard`-Layer (Beispiel: Vessels, Aircraft, Ports, CCTV)
  - `Polygon`-Layer (Beispiel: GPS-Jamming-Zonen)
  - `Polyline`-Layer (Beispiel: Aircraft-Tracks, Satelliten-Bahnen)
  - `WebMapServiceImageryProvider`-Layer (Beispiel: NEXRAD, Sentinel)
- Click-to-Inspect: wie `_wvType` / `_wvMeta` / `_wvLat` / `_wvLon` /
  `_wvClassification` / `_wvSources` an verschiedenen Primitive-Typen
  anzubringen sind
- `requestRenderMode`-Disziplin: `viewer.scene.requestRender()` nach
  jeder Mutation, nicht vergessen bei async-Updates
- Status-/Count-Updates: `WV.Controls.setStatus(msg)` und
  `WV.Controls.updateCount(layer, n)`
- Domänen-Gruppe-Annotation als JSDoc-Kommentar oben im File
- Smoke-Test-Pattern: Layer toggelt sauber an/aus, keine Memory-Leaks
  beim wiederholten enable/disable
- Verifikations-Checkliste (für post-task hook): IIFE-Form ✓, Promise
  zurückgegeben aus enable ✓, requestRender nach jeder Mutation ✓,
  alle `_wv*`-Felder gesetzt ✓

**Trigger-Phrasen.** "Neuen Cesium-Layer", "WorldView-Layer hinzufügen",
"Layer für X bauen", "click-to-inspect", "PointPrimitive".

---

## 2. `osint-sovereign-proxy`

**Zweck.** Stellt sicher, dass jeder externe API-Aufruf durch den
Sovereign Proxy in `eu-frankfurt-1` läuft, mit Audit-Log und Cache.
Wird primär vom `sovereign-proxy-builder`-Agent geladen.

**Inhalt.**

- **Pattern A — REST-Poll.** ORDS-PL/SQL-Template mit:
  - Bbox-Key-Berechnung (Geo-Hash oder Tile-Koordinaten)
  - Cache-Lookup gegen `osint_cache` mit TTL pro Layer
  - `apex_web_service.make_rest_request` mit Retry/Timeout
  - JSON-Validation
  - Audit-Insert in `osint_audit`
  - Beispiele für 3 reale Layer (OpenSky, GPSJam, USGS)
- **Pattern B — WebSocket-Multiplexer.** Python-Container-Template:
  - `asyncio` + `websockets`-Lib
  - Vault-Secret-Read über OCI SDK
  - Fan-out an N verbundene Browser
  - Backpressure / disconnected-client cleanup
  - Async batched Audit-Writes (1 Insert pro N Messages)
  - Beispiel: AIS Stream
- **Pattern C — WMS-Tile-Reverse-Proxy.** API Gateway + Function:
  - URL-Routing `/api/wms/{provider}/{z}/{x}/{y}`
  - Object-Storage-Cache-Lookup
  - Fall-through zu Public WMS mit Vault-Instance-ID
  - Beispiel: Sentinel und NEXRAD
- **Vault-Pattern**: wie Free-Tier-Keys vault-seitig gehalten und
  funktionsseitig per OCID gelesen werden (kein Re-Storage in 26ai)
- **Region-Param-Pattern**: alle Region-Strings ausschließlich aus `.env`,
  nirgends hardcoded
- Verifikations-Checkliste: Audit-Row geschrieben ✓, Vault-OCID statt
  Klartext ✓, Region aus env ✓, Cache-Layer aktiv ✓

**Trigger-Phrasen.** "Sovereign Proxy", "ORDS-Handler für OSINT-Layer",
"WebSocket-Multiplexer", "Tile-Cache in Object Storage", "VS-NfD-konformer
API-Aufruf".

---

## 3. `oci-genai-tool-calling`

**Zweck.** Konsistente Implementierung des Chat-Service mit OCI
Generative AI Inference, sauberem Tool-Calling-Loop und der
`map_action`-Relay-Konvention. Wird primär vom `chat-tool-author`-Agent
geladen.

**Inhalt.**

- OCI Generative AI Inference SDK Setup (Python), bevorzugtes Modell
  `cohere.command-r-plus` (gutes Tool Use), Fallback
  `meta.llama-3.3-70b-instruct`
- **Tool-Definitions-Format** für die vier Standard-Tools:
  `pgql_query`, `vector_search`, `select_ai`, `map_action` —
  inklusive guter Descriptions als Anti-Halluzinations-Hebel
- **Tool-Calling-Loop** (Pseudo-Code):
  ```
  while True:
      resp = chat.completions(model, messages, tools)
      if resp.tool_calls:
          for tc in resp.tool_calls:
              if tc.name == "map_action":
                  await ws.send(...)         # Relay an Frontend
                  result = {"status": "dispatched"}
              else:
                  result = await execute_data_tool(tc.name, tc.args)
              messages.append({"role": "tool", ...})
      else:
          await ws.send({"type": "chat_response", "text": resp.text})
          return
  ```
- **WebSocket-Server-Pattern**: Session-Map, Reconnect-Handling,
  Graceful Shutdown
- **System-Prompt-Template** mit Slots für Map-Context, Tenant,
  Klassifizierungs-Hinweise
- **Streaming**: optional Token-Streaming an Browser, mit Back-Channel
  für `map_action` während des Streams
- **Error-Handling**: was passiert wenn Tool fehlschlägt, wie wird
  das dem LLM zurückgemeldet damit er anders fragt
- **Audit-Log pro Tool-Call** in `osint_audit` mit `action='tool_call'`
- **Anti-Pattern**: was der LLM **nicht** dürfen darf (Map-Manipulation
  außerhalb der vier `map_action`-Wrapper, freie SQL-Statements ohne
  Select-AI-Validierung, Aufrufe an externe URLs)
- Verifikations-Checkliste: alle 4 Tools registriert ✓, map_action ist
  Relay nicht Backend-Action ✓, Audit pro Tool-Call ✓, Tool-Description
  enthält Trigger-Phrasen ✓

**Trigger-Phrasen.** "Chatbot", "Chat-Service", "Tool Calling", "OCI
Generative AI", "Cohere Command R+", "Map-Action vom Chat", "LLM
Lagebild bedienen".

---

## 4. `26ai-property-graph-osint`

**Zweck.** Erweiterung von `oracle-26ai-schema` für die OSINT-Domäne.
Definiert Entity-Klassen, Beziehungen und PGQL-Beispielqueries, die der
`pgql_query`-Tool des Chatbots aufrufen wird. Wird primär vom
`pgql-schema-architect`-Agent geladen.

**Inhalt.**

- **Entity-Klassen** (Property Graph Vertex Types):
  - `Vessel` (mmsi, imo, flag, vessel_type, last_position, ...)
  - `Aircraft` (icao24, callsign, registration, country, ...)
  - `Satellite` (norad_id, name, country, orbit_class, ...)
  - `Port` (unlocode, name, country, geometry, ...)
  - `SeismicEvent` (event_id, magnitude, depth, geometry, ts, ...)
  - `JammingZone` (zone_id, geometry, intensity, observed_at, ...)
  - `OSINTSource` (source_id, type, url, classification, ...)
  - `FusionNode` (node_id, derived_from[], confidence, ...)
- **Beziehungen** (Edge Types):
  - `MENTIONED_IN(Entity → OSINTSource)` — Häufigkeit als Property
  - `CORRELATED_WITH(Entity → Entity)` — Konfidenz, Methodik
  - `WITHIN_ZONE(Entity → JammingZone | Polygon)` — räumliche Beziehung
  - `FUSED_WITH(FusionNode → Entity[])` — fusionierte Quellen
  - `CLASSIFIED_AS(Entity → ClassificationLevel)`
- **PGQL-Beispielqueries** für typische Demo-Fragen:
  - "Entitäten in N+ Quellen erwähnt"
  - "Schiffe innerhalb Jamming-Zone in Zeitfenster"
  - "Fusion-Cluster mit Konfidenz > X"
  - "Welche OSINT-Quellen erwähnen sowohl Entity A als auch B"
- **Klassifizierungs-Vererbung**: Entity-Klassifizierung per Label
  Security, Edge-Klassifizierung als Maximum der angrenzenden Vertices
- **Migrationsskript**: vom heutigen UC4-Schema zum erweiterten Schema
  ohne Datenverlust
- **Indexierung**: welche Properties indexieren, welche
  Spatial-Indizes auf welchen Entity-Klassen
- Verifikations-Checkliste: Entity-Klasse hat Spatial-Index falls
  geo-aktiv ✓, MENTIONED_IN-Edges sind kardinalitäts-tauglich ✓,
  Klassifizierungs-Label gesetzt ✓

**Trigger-Phrasen.** "Property Graph", "PGQL", "Entity-Klassen für OSINT",
"MENTIONED_IN", "Fusion-Knoten", "Graph-Schema für UC4".

---

## 5. `vs-nfd-classification`

**Zweck.** Konsistente Klassifizierungs-Behandlung über alle Layer,
Tools und UI-Komponenten. Gleichzeitig die UC6-Compliance-Story
mechanisch absichern. Wird primär vom `compliance-auditor`-Agent
geladen.

**Inhalt.**

- **Klassifizierungs-Hierarchie**: `OPEN < VS-NfD < VS-VERTRAULICH <
  GEHEIM` als ENUM in 26ai, mit Vererbungs-Logik bei Fusion
- **Audit-Log-Schema** (`osint_audit`) — Spalten, Indizes,
  Retention-Policy
- **Frontend-Mode-Switching**:
  - VS-NfD-Modus blendet Public-Layer aus (per CSS + Layer-Disable)
  - Klassifizierungs-Banner oben in der Karte
  - `_wvClassification` per Entity sichtbar im Intel-Panel
- **Backend-Enforcement**:
  - Label Security in 26ai pro Tenant
  - Compartment-Isolation: Public-OSINT in eigenem Compartment, niemals
    in den klassifizierten Daten-Compartments
  - Tag-basiertes IAM für Vault-Secrets
- **Sanitization-Regeln**: was passiert bei Fusion eines OPEN-Vessel
  mit einer VS-NfD-SIGINT-Meldung — Resultat ist VS-NfD, sichtbar nur
  für entsprechende Tenants
- **DSGVO-Hooks**: CCTV-Layer per default aus im VS-NfD-Modus,
  explizite Opt-In-UI für Personenerkennbarkeit, Audit jeder Sichtung
- **NIS2 / DORA / VS-NfD Mapping**: welche Compliance-Anforderung wird
  durch welchen Audit-Mechanismus abgedeckt
- Verifikations-Checkliste (kann als post-task-hook automatisiert
  laufen): jeder neue Code-Pfad hat Audit-Row ✓, kein API-Key in
  browser-erreichbarem File ✓, jede Entity hat Klassifizierungs-Label ✓

**Trigger-Phrasen.** "VS-NfD", "Klassifizierung", "Audit-Log", "Label
Security", "Compliance", "DSGVO CCTV", "NIS2".

---

## 6. `ruflo-osint-recipes`

**Zweck.** Konkrete, kopierfertige Ruflo-Multi-Agent-Recipes für die
typischen Workflows dieses Projekts. Reduziert Setup-Overhead pro
Workflow von "Code-Tabelle nachschauen + Agents tippen" auf "Recipe
laden". Wird vom `hierarchical-coordinator` zu Beginn jedes Multi-File-
Tasks geladen.

**Inhalt.**

- **Recipe L — Add Cesium Layer (full lifecycle)**:
  - Pre-checks (welches Pattern, welche Domäne, neue Entity-Klasse?)
  - Single-message swarm_init + 6 parallel Tasks
  - TodoWrite-Template mit allen Stationen (file, script tag,
    layer-row, count badge, ORDS handler, audit, smoke test, doc)
  - Memory-Schreib-Pattern für `osint-lagebild`-Namespace
- **Recipe T — Add Chat Tool**: 4-Agent-Variante, Tool-Definition +
  Handler + System-Prompt + deterministischer Test
- **Recipe G — Property Graph Schema Change**: Migration mit Rollback,
  Index-Refresh, Tool-Description-Update
- **Recipe C — Compliance Audit Pass**: einzelner `compliance-auditor`,
  liest `git diff`, prüft gegen `vs-nfd-classification`-Skill-Regeln
- **Recipe D — Demo Storyline**: `demo-flow-curator` allein,
  3-Minuten-Story basierend auf neuen Layern
- **Recipe F — Full Feature**: alle sechs Domain-Agents, koordiniert
  über `system-architect` als Lead
- **Headless-Patterns**: wann `claude -p` parallel statt Swarm
  (z.B. Layer-Inventar-Scans, Demo-Draft-Varianten)
- **Anti-Patterns**: was nicht in Ruflo gehört (1-Line-Bugfix,
  Camera-Preset, Doc-Typo) — direkt mit Edit-Tool, kein Swarm
- **Hooks-Integration**: welche Ruflo-Hooks (`pre-task`, `post-edit`,
  `post-task`, `session-end`) bei welchem Recipe sinnvoll sind, plus
  Train-Patterns-Flags

**Trigger-Phrasen.** "Add layer with swarm", "Multi-Agent für OSINT",
"Ruflo recipe", "spawn full feature", "neue Layer Pipeline".

---

## Reihenfolge der Skill-Erstellung

Nach Demo-Hebelwirkung priorisiert:

1. **`cesium-layer-pattern`** — ohne dieses werden Layer inkonsistent
   und der erste Demo-Wow leidet sofort. Pflicht.
2. **`osint-sovereign-proxy`** — der Differentiator gegenüber
   Original-WorldView. Drei Patterns parallel dokumentiert spart
   Wochen Trial-and-Error. Pflicht.
3. **`oci-genai-tool-calling`** — der Hebel für die "Chatbot-fragt-
   Lagebild"-Demo. Pflicht.
4. **`ruflo-osint-recipes`** — sobald die ersten drei Skills stehen,
   spart dieser Skill enorm Zeit bei jedem weiteren Layer/Tool, weil
   die Multi-Agent-Workflows nur noch geladen statt getippt werden.
5. **`26ai-property-graph-osint`** — wird essentiell sobald der erste
   Fusion-Demo-Flow steht und du anfängst, weitere Fusion-Variationen
   zu bauen.
6. **`vs-nfd-classification`** — für die UC6-Compliance-Story und die
   VS-NfD-Demo-Modus-Differenzierung. Letzte vor Beschaffer-Demo.

---

## Verbindung zu den `.agents/`-Dateien

Jeder der sechs projekt-spezifischen Agents in `.agents/` referenziert
ein bis zwei dieser Skills im Frontmatter:

| Agent | Primary Skill | Secondary Skill |
|-------|---------------|-----------------|
| `cesium-layer-builder` | `cesium-layer-pattern` | — |
| `sovereign-proxy-builder` | `osint-sovereign-proxy` | `vs-nfd-classification` |
| `pgql-schema-architect` | `26ai-property-graph-osint` | `oracle-26ai-schema` |
| `chat-tool-author` | `oci-genai-tool-calling` | — |
| `compliance-auditor` | `vs-nfd-classification` | `osint-sovereign-proxy` |
| `demo-flow-curator` | `ruflo-osint-recipes` | — |

Skills werden durch den `pre-task`-Hook automatisch in den Agent-
Kontext geladen, sodass der Agent bei jedem Aufruf die aktuelle
Pattern-Definition vor sich hat.
