# Compliance Audit — Recipe L Layer #5 "Satellites" (Pattern A, Multi-Sub-Layer, Client-Side TLE Propagation)

**Date:** 2026-04-29
**Branch:** `feat/sovdefence-app-swarm`
**Layer pattern:** Pattern A (REST poll over CelesTrak) with three logical sub-layers (`satellites-stations` / `satellites-resource` / `satellites-active`) served by a single backend service. Frontend SGP4-propagates the TLE blobs client-side via `satellite.js`.

**Pre-flight verification (passed before code commit):**

```
$ curl -sI "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"
HTTP/2 200 — content-type text/plain — server Microsoft-IIS/10.0

$ curl -s "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle" | head -6
ISS (ZARYA) / 1 25544U 98067A ... / 2 25544  51.6 ...
POISK / 1 36086U 09060A ... / 2 36086  51.6 ...

$ curl -s "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle" | wc -l
45765   (≈15 200 satellites × 3 lines per TLE — within expected ~10 000+ range)
```

**Scope:**
- `frontend/src/layers/satellites-shared.ts` (parser + SGP4 helper)
- `frontend/src/layers/satellites-stations.ts` (Entity-API, full Click-to-Inspect)
- `frontend/src/layers/satellites-resource.ts` (Entity-API, full Click-to-Inspect)
- `frontend/src/layers/satellites-active.ts`   (PointPrimitiveCollection, no per-click)
- `frontend/src/layers/__tests__/satellites-shared.test.ts`    (5 tests, incl. ISS SGP4)
- `frontend/src/layers/__tests__/satellites-stations.test.ts`  (4 tests)
- `frontend/src/layers/__tests__/satellites-resource.test.ts`  (4 tests)
- `frontend/src/layers/__tests__/satellites-active.test.ts`    (3 tests)
- `frontend/src/layers/index.ts` (three side-effect imports added)
- `frontend/nginx.conf` (`location ^~ /api/osint/satellites/` proxy added)
- `frontend/package.json` (satellite.js@7 dep)
- `frontend/src/views/__tests__/LagebildView.test.tsx` (mock viewport `camera.moveEnd` added)
- `services/tle-proxy/` (new FastAPI service tree — Dockerfile, requirements, app/{__init__,db,cache_repo,audit,settings,parser,poller,main}.py)
- `services/tle-proxy/tests/{conftest,test_main,test_parser}.py` (7 tests)
- `db/queries/satellites-pgql.md` (3 demo PGQL/SQL queries — vessel-visibility, EO-overpass, Triple-Korrelation Sat × Sentinel × Vessel)
- `oci-devops/build-specs/tle-proxy.yaml`
- `k8s/base/deploy-tle-proxy.yaml` + `svc-tle-proxy.yaml`
- `k8s/base/kustomization.yaml` (tle-proxy entries added)
- `k8s/base/ingress.yaml` (`/api/osint/satellites` route added)
- `k8s/overlays/prod/kustomization.yaml` (image entry + replicas: 1)
- `scripts/setup-devops.sh` (`tle-proxy` added to `SERVICES`)
- `scripts/smoke-test-satellites.sh`

## Methodology

The mechanical grep checklist from `.agents/compliance-auditor.md`,
applied to the new files:

```bash
grep -rn 'eu-frankfurt-1\|us-ashburn-1\|us-phoenix-1' \
  frontend/src/layers/satellites-*.ts services/tle-proxy/
grep -rn 'API_KEY\|apikey' frontend/src/layers/satellites-*.ts
grep -rn 'INSERT INTO audit_events\|INSERT INTO osint_audit\|INSERT INTO audit_log' \
  services/tle-proxy/ db/queries/satellites-pgql.md
grep -rn 'os.environ\[.*KEY' services/tle-proxy/
grep -rn '23ai\|23c' services/tle-proxy/ frontend/src/layers/satellites-*.ts
grep -rn 'WV\.layers' frontend/src/layers/satellites-*.ts
grep -rn ': any' frontend/src/layers/satellites-*.ts services/tle-proxy/
```

## ✓ Pass-Items

- **Audit-Tabelle korrekt:** `services/tle-proxy/app/audit.py` schreibt ausschließlich `INSERT INTO audit_events` (one row per group per refresh — three rows per 6 h tick). Kein Treffer für `osint_audit` oder `audit_log`.
- **Kein API-Key benötigt:** CelesTrak publiziert öffentliche TLE-Listen ohne Authentifizierung. Kein ExternalSecret, kein Vault-OCID-Field, kein MOCK_VAULT_KEY-Hatch.
- **Region nicht hardcoded:** `oci_region` ist `pydantic-settings` Field mit Default `eu-frankfurt-1`. Keine String-Konstante in Code-Pfaden.
- **CelesTrak-URL nicht hardcoded** im Frontend-Code: Browser-Pfade gehen ausschließlich gegen `/api/osint/satellites/{group}/current` (origin-relative). Backend hält `celestrak_base_url` als pydantic-settings-Field. Strings „CelesTrak NORAD …" im Frontend sind nur Provenienz-Labels für die Intel-Panel-Anzeige.
- **23ai/23c-Residue:** 0 Treffer in den neuen Files.
- **IIFE-Pattern (ADR-0001) nicht verwendet:** alle drei Sub-Layer sind TypeScript-Module mit `LayerRegistry.register(...)` als Top-Level-Side-Effect.
- **`_wv*`-Konvention vollständig** in `stations` + `resource` (Entity-API). Bei `active` (PointPrimitiveCollection) ist `_wv*` *bewusst* weggelassen — UX-Trade-Off für 15 k Satelliten-Performance, dokumentiert im Code-Kommentar und im Smoke-Test-Hint.
- **Klassifikation = OPEN durchgängig:** `defaultClassification: 100` in allen drei Layern; Backend `audit.record_fetch(..., ols_label=100, ...)`; `osint_cache.classification = 'OPEN'`.
- **`any`-Disziplin:** 0 Treffer in den neuen TS-Files. Jeder Property-Pfad ist getypt (`SatelliteRecord`, `SatPosition`, `TleEntry`, `TleCollection`).
- **ATP-Env-Naming Plattform-konform:** `app/settings.py` aliases sind `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_CONNECT_STRING`, `WALLET_PASSWORD`. Identisch zu allen Vorgängern.
- **ServiceAccount korrekt:** `serviceAccountName: sovdefence-runtime`.
- **Health-Endpoint korrekt:** `/healthz`; ReadinessProbe in `deploy-tle-proxy.yaml` zeigt auf den richtigen Pfad.
- **Port-Allocation eindeutig:** containerPort + Service port = **8010**. Belegung: geoint=8001..compliance=8005, ais-multiplexer=8001 (eigener Service), jamming-poller=8007, sentinel-proxy=8008, flights-proxy=8009, **tle-proxy=8010**. Keine Kollisionen.
- **Resource-Sizing:** `requests = limits = 250m/512Mi`. Spec-konform — leichtester Pattern-A-Backend bisher (kein H3, keine Klassifikation, kein in-memory viewport-Cache).
- **Audit-Bypass:** kein `try/except: pass` um den `INSERT`. Failures werden geloggt + counter incremented; nächster Tick versucht es wieder.
- **No-Cache-Bleed-Bei-Upstream-Fail:** `poller._fetch_group()` schreibt nur dann ins `osint_cache`, wenn `text.splitlines() >= 3` UND parser ≥ 1 Record liefert. Bei 4xx/5xx/Network/Empty bleibt der vorherige Cache-Stand stehen — *Lesson aus jamming explizit angewendet*.
- **Reverse-Proxy-Discipline:** Browser → `/api/osint/satellites/{group}/current`; Frontend-Nginx proxiet (`location ^~ /api/osint/satellites/` mit `^~` damit `.png`-static-asset-Regex nicht greift); Ingress-Rule `pathType: Prefix /api/osint/satellites → tle-proxy:8010`. Keine direkten celestrak.org-Calls aus dem Browser.
- **Single-Responsibility-Prinzip aus Sentinel:** `parser.py` ist eigene Datei mit eigenen Tests (`test_parser.py`, 3 Tests: multi-block, empty input, malformed). NICHT in main.py oder poller.py vermischt.
- **Audit pro Group separat:** drei `audit_events`-Rows pro Tick (eine pro group), `resource_id` enthält den ISO-Timestamp, `resource_type` ist `satellites/{group}`. UC6 Compliance-Korrelation bleibt sauber — keine kombinierte Multi-Group-Row.
- **PGQL Q3 ist echte SDO_GEOMETRY-Query** mit `SDO_RELATE`+`SDO_GEOM.SDO_BUFFER`+`SDO_GEOM.SDO_DISTANCE`, kein Stub. Nutzt drei Layer-Caches plus den `osint_entities`-Property-Graph für eine ausführbare Triple-Korrelation Sat × Sentinel × Vessel.
- **CelesTrak rate-limit-respektierend:** Drei Groups werden in `poller.fetch_once()` SEQUENTIELL gefetcht (`for group in ...`), nicht parallel — explizite Vermeidung des CelesTrak-Burst-Banhammers.
- **TLE-Refresh ≥ 6 h:** `tle_refresh_hours: int = Field(default=6, ...)`; minimum durch `ge=1` validiert, aber Operator-Default ist 6 (entspricht der CelesTrak-Praxis).
- **Tests grün:** Backend `pytest` 7 passed (4 main + 3 parser); Frontend `vitest` 16 passed neu (5 shared + 4 stations + 4 resource + 3 active); SGP4-Live-Test gegen ISS-TLE liefert plausible Lat (|lat|<53°) und Höhe (350–500 km); `tsc --noEmit` exit 0; `kubectl kustomize k8s/overlays/prod` rendert tle-proxy mit OCIR-Image-Pin.

## ✗ Block-Items (must fix before commit)

*Keine.*

## ⚠ Warnings (non-blocking)

- **Active-Sub-Layer ohne Click-Detail.** PointPrimitiveCollection bedeutet 15 k Satelliten rendern flüssig, aber kein `_wv*` per Punkt. Operator wird im Smoke-Test-Hint und im Code-Kommentar darauf hingewiesen. Workaround: Operator wechselt zur kleineren `resource`- oder `stations`-Sub-Layer für Detail-Inspektion.
- **Server-side SGP4 fehlt.** Q1 + Q3 nutzen Sentinel-Tile-Viewport-Mitte als groben Sub-Satellite-Point-Anker, weil PL/SQL keine SGP4-Funktion hat. Echtes Visibility-Match braucht entweder eine `CREATE FUNCTION sgp4_position(line1, line2, ts) RETURN SDO_GEOMETRY` (Java-stored-procedure mit dem orekit/sgp4-JAR) oder eine Server-side-Python-View über die Cache-Rows. Tech-Debt für eine spätere Iteration.
- **Cache-Pruning fehlt** (gemeinsam mit allen Pattern-A-Layern). 3 Rows × 4 Ticks/Tag × 365 Tage = 4380 Rows/Jahr × ~50 KB pro `active` ≈ 220 MB/Jahr. Vernachlässigbar; eine TTL-DELETE wäre hygienisch.
- **active-Catalog ist sehr groß** (~15 k Satelliten). 1 Hz Propagation für 15 k SatRecs frisst CPU im Frontend; auf älterer Hardware kann das Frame-Drops verursachen. Mitigation: Operator-Hint "for performance" im Smoke-Test, plus die Möglichkeit, nur die kleineren `stations`/`resource`-Sub-Layer zu aktivieren. Frontend-seitige LOD-Logik (z.B. Sub-Sample bei zoomed-out) wäre der Performance-Pfad — Tech-Debt.
- **TLE-Cache-TTL = 12 h, Refresh = 6 h** — bewusst großzügig. Bei einem CelesTrak-Outage von >12 h würde das Frontend 503 sehen. Für die Demo-Robustheit ist das Verhältnis 2× gut. Bei längeren Outages müsste der Operator `CACHE_TTL_HOURS` erhöhen.
- **PGQL Q1 + Q3 sind grobe Heuristiken** — gut genug für Demo, aber kein autoritatives Visibility-Window. Storyline-Anker bleibt korrekt, Operator-UX im Frontend nutzt die exakte SGP4-Live-Berechnung.
- **`layer_lifecycle.test.ts`-Failures sind pre-existing** (untracked, von früheren Sessions). Vier Tests schlagen fehl: maritime-WS-Mock-Constructor + drei Sentinel-Lifecycle-Tests. Nicht Recipe-L-#5-Regression.

## Verdict

**PASS_WITH_WARNINGS** — Code-Pfad ist commit-fähig. Keine Compliance-Verstöße. Sechs Warnings sind alles Verbesserungs-Hinweise für spätere Sprints, kein Blocker für Recipe-L Layer #5. Der zentrale UC4-Demo-Hebel (Triple-Korrelation Satellites × Sentinel × Vessel) ist als ausführbare SDO_GEOMETRY-Query implementiert, plus drei Frontend-Sub-Layer mit unterschiedlichen UX-Charakteristiken.

## Reproducibility

```bash
cd /home/ubuntu/oci-defense-demo

grep -rn 'INSERT INTO audit_'   services/tle-proxy/ db/queries/satellites-pgql.md
grep -rn 'os.environ\[.*KEY'    services/tle-proxy/
grep -rn 'WV\.layers'           frontend/src/layers/satellites-*.ts
grep -rn '23ai\|23c'            services/tle-proxy/ frontend/src/layers/satellites-*.ts
grep -rn ': any'                frontend/src/layers/satellites-*.ts services/tle-proxy/

# Build / Test:
cd frontend && npx vitest run --reporter=basic src/layers/__tests__/satellites && npx tsc --noEmit
cd services/tle-proxy && python3 -m pytest tests/ -x

# Manifest validity:
kubectl kustomize k8s/overlays/prod | grep -E 'name: tle-proxy$|image:.*tle-proxy'
```
