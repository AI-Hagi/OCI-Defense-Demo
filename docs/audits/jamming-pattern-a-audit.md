# Compliance Audit — Recipe L Layer #2 "GPS Jamming" (Pattern A)

**Date:** 2026-04-29
**Branch:** `feat/sovdefence-app-swarm`
**Scope:**
- `frontend/src/layers/jamming.ts` + `__tests__/jamming.test.ts`
- `frontend/src/layers/index.ts` (jamming side-effect import added)
- `frontend/nginx.conf` (`location /api/osint/jamming/` proxy added)
- `services/jamming-poller/` (new FastAPI service tree, daily REST poll + H3 transform)
- `db/schema/10_osint_cache.sql` (new generic cache table for Pattern-A layers)
- `db/queries/jamming-pgql.md` (3 demo SQL/PGQ queries for UC4 narrative)
- `oci-devops/build-specs/jamming-poller.yaml`
- `k8s/base/deploy-jamming-poller.yaml` + `svc-jamming-poller.yaml`
- `k8s/base/kustomization.yaml` (jamming entries added)
- `k8s/base/ingress.yaml` (`/api/osint/jamming` route added)
- `k8s/overlays/prod/kustomization.yaml` (image pin + replicas: 1)
- `scripts/smoke-test-jamming.sh`

## Methodology

The same mechanical grep checklist from `.agents/compliance-auditor.md`:

```bash
grep -rn 'eu-frankfurt-1\|us-ashburn-1\|us-phoenix-1' frontend/src/layers/jamming.ts services/jamming-poller/
grep -rn 'API_KEY\|apikey\|gpsjam\.org' frontend/src/layers/jamming.ts
grep -rn 'INSERT INTO audit_events\|INSERT INTO osint_audit\|INSERT INTO audit_log' services/jamming-poller/ db/
grep -rn 'os.environ\[.*KEY' services/jamming-poller/
grep -rn '23ai\|23c' db/schema/10_osint_cache.sql services/jamming-poller/
grep -rn 'WV\.layers' frontend/src/layers/jamming.ts
grep -rn '_wvClassification\|_wvType' frontend/src/layers/jamming.ts
grep -rn ': any' frontend/src/layers/jamming.ts services/jamming-poller/
```

## ✓ Pass-Items

- **Audit-Tabelle korrekt:** `services/jamming-poller/app/audit.py` schreibt ausschließlich `INSERT INTO audit_events` (siehe `_INSERT_AUDIT_SQL`). Kein Treffer für `osint_audit` oder `audit_log`.
- **Kein API-Key benötigt:** gpsjam.org publiziert öffentliche tägliche CSVs ohne Authentifizierung. Kein ExternalSecret, kein Vault-OCID-Field, kein MOCK_VAULT_KEY-Hatch — die Settings erwähnen das gar nicht. Das eliminiert eine ganze Klasse von Key-Rotation-Konzern.
- **gpsjam.org-URL nicht hardcoded** im Frontend-Code: Die einzigen Browser-Pfade gehen gegen `/api/osint/jamming/current` (origin-relative). Backend hält `gpsjam_url_template` als pydantic-settings-Field mit Default — der Browser sieht nur die Sovereign-Proxy-URL, nie gpsjam.org.
- **Region nicht hardcoded:** `oci_region` ist `pydantic-settings` Field mit Default `eu-frankfurt-1`. Keine String-Konstante in Code-Pfaden.
- **23ai/23c-Residue:** `grep -rn '23ai\|23c' db/schema/10_osint_cache.sql services/jamming-poller/` → 0 Treffer.
- **IIFE-Pattern (ADR-0001) nicht verwendet:** `grep -rn 'WV\.layers' frontend/src/layers/jamming.ts` → 0. Layer ist als TypeScript-Modul mit `LayerRegistry.register(...)` als Top-Level-Side-Effect.
- **`_wv*`-Konvention vollständig:** `_wvType='jamming_zone'`, `_wvMeta`, `_wvLat`, `_wvLon`, `_wvClassification` (numerisch 100), `_wvSources=['gpsjam.org via ADS-B Exchange']` (siehe `applyWvProps()` in `jamming.ts`).
- **Klassifikation = OPEN:** Pattern-A-Default `defaultClassification: 100` und `audit.record_fetch(..., ols_label=100, ...)`. `osint_cache.classification = 'OPEN'`.
- **`any`-Disziplin:** `grep -rn ': any' frontend/src/layers/jamming.ts` → 0 Treffer im neuen TS-Code.
- **ATP-Env-Naming Plattform-konform:** `app/settings.py` aliases sind `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_CONNECT_STRING`, `WALLET_PASSWORD` — gleiche Konvention wie compliance, geoint, osint-fusion und der ais-multiplexer-fix vom 2026-04-28.
- **ServiceAccount korrekt:** `serviceAccountName: sovdefence-runtime` (nicht `workload-identity` wie ursprünglich in der Spec).
- **Health-Endpoint korrekt:** `/healthz` (nicht `/health`); ReadinessProbe in deploy.yaml zeigt auf den richtigen Pfad.
- **Port-Allocation eindeutig:** containerPort + Service port = 8007 (nächster freier nach geoint=8001..compliance=8005, ais-multiplexer=8001 [eigener ClusterIP], jamming-poller=8007). Dockerfile ENTRYPOINT bindet auf 8007 — kein Port-Mismatch wie beim ais-multiplexer-Erstrun.
- **Resource-Sizing:** `requests = limits = 250m/512Mi` fix. Niedriger als ais-multiplexer (500m/1Gi) wegen fehlender WS-Long-Connection. Virtual-Node-Guaranteed-QoS-tauglich.
- **Audit-Bypass:** `app/audit.py` hat keinen `try/except: pass` um den `INSERT INTO audit_events`. Failures werden geloggt + counter incremented, aber der nächste Tick versucht es wieder.
- **No-Cache-Bleed-Bei-Upstream-Fail:** `poller.fetch_once()` schreibt nur dann ins `osint_cache`, wenn Upstream 200 + non-empty Body + Parse-OK. Bei 4xx/5xx/Network/Empty-Body bleibt der vorherige Cache-Stand stehen. Verhindert „leerer Cache nach kurzem Outage".
- **Reverse-Proxy-Discipline:** Browser hits `/api/osint/jamming/current`; Frontend-Nginx proxiet (siehe `nginx.conf` neue `location /api/osint/jamming/`-Block); Ingress route auf jamming-poller:8007. Keine direkten gpsjam-Calls aus dem Browser.

## ✗ Block-Items (must fix before commit)

*Keine.*

## ⚠ Warnings (non-blocking)

- **`osint_cache.classification`-Spalte nutzt String, `audit_events.ols_label` nutzt Number.** Der Cache-Eintrag schreibt `classification='OPEN'`, der Audit-Eintrag `ols_label=100`. Konsistent mit dem existierenden Frontend-Helper (`numericToLabel`/`labelColor` in `frontend/src/types/classification.ts`), aber kann beim Lesen verwirren. Nicht blocking — die beiden Tabellen haben unterschiedliche Konsumenten.
- **`SDO_RELATE`-basierte PGQL-Query in `db/queries/jamming-pgql.md` braucht Spatial-Index** auf `osint_entities` (Lat/Lon aus `attributes` JSON). Heute ist kein Spatial-Index auf JSON-Pfaden definiert; bei <100 Vessels und <500 Hex-Cells funktioniert die Query trotzdem, aber die Performance-Story für >10k Vessels ist offen. Tech-Debt-Item für einen späteren Sprint.
- **APScheduler-First-Fetch ist asyncio.create_task, nicht awaited.** Wenn der erste Fetch crasht, läuft der Service trotzdem an und liefert 503 cold-cache, bis der nächste Tick erfolgreich ist. Das ist by design (Service muss starten auch wenn gpsjam.org gerade down ist), aber bei einer permanent-broken-URL würde der Pod fröhlich Bytes fressen ohne sinnvoll zu laufen. Ein Liveness-Counter „last_successful_fetch_age > 48h → unhealthy" wäre ein Robustness-Patch.
- **Cache-Pruning fehlt.** `osint_cache` wächst monoton (eine Row pro 6 h-Tick × N Layer). Bei 1 Layer × 4 Ticks/Tag × 365 Tage = 1.460 Rows/Jahr × ~10 KB Payload ≈ 14 MB/Jahr — vernachlässigbar. Aber bei 10 Pattern-A-Layern: 140 MB/Jahr. Ein TTL-Job (`DELETE FROM osint_cache WHERE fetched_at < SYSTIMESTAMP - INTERVAL '30' DAY`) wäre hygienisch.
- **`audit_events.payload` wird mit `json.dumps(payload)` serialisiert, aber `osint_cache.payload` ist Oracle JSON.** Der Multiplexer macht's auch so; passt zur Plattform-Konvention. Keine Änderung notwendig, nur dokumentiert.

## Verdict

**PASS_WITH_WARNINGS** — Code-Pfad ist commit-fähig. Keine Compliance-Verstöße. Vier Warnings sind alles Verbesserungs-Hinweise für spätere Sprints, kein Blocker für Recipe-L Layer #2.

## Reproducibility

```bash
cd /home/ubuntu/oci-defense-demo

grep -rn 'INSERT INTO audit_'           services/jamming-poller/ db/
grep -rn 'os.environ\[.*KEY'            services/jamming-poller/
grep -rn 'WV\.layers'                   frontend/src/layers/
grep -rn '23ai\|23c'                    db/schema/10_osint_cache.sql services/jamming-poller/
grep -rn ': any'                        frontend/src/layers/jamming.ts services/jamming-poller/

# Build / Test:
cd frontend && npx vitest run --reporter=basic
cd services/jamming-poller && python3 -m pytest tests/ -x

# Manifest validity:
kubectl kustomize k8s/overlays/prod | head -1   # any error appears here
```
