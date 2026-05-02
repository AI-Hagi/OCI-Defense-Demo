# Compliance Audit — Recipe L Layer #3 "Sentinel-2 Imagery" (Pattern C)

**Date:** 2026-04-29
**Branch:** `feat/sovdefence-app-swarm`
**Scope:**
- `frontend/src/layers/sentinel.ts` + `__tests__/sentinel.test.ts`
- `frontend/src/layers/index.ts` (sentinel side-effect import added)
- `frontend/nginx.conf` (`location /api/osint/sentinel/` proxy added)
- `services/sentinel-proxy/` (new FastAPI service tree, OAuth2 + WMS reverse-proxy + tile-bbox math + audit batching)
- `db/queries/sentinel-pgql.md` (3 demo SQL queries for UC4 Maritime × Imagery narrative)
- `oci-devops/build-specs/sentinel-proxy.yaml`
- `k8s/base/deploy-sentinel-proxy.yaml` + `svc-sentinel-proxy.yaml`
- `k8s/base/external-secrets/externalsecret-sentinel.yaml` (3 Vault secrets → 1 K8s Secret with 3 data keys)
- `k8s/base/external-secrets/kustomization.yaml` (entry added)
- `k8s/base/kustomization.yaml` (entry added)
- `k8s/base/ingress.yaml` (`/api/osint/sentinel` route added)
- `k8s/overlays/prod/kustomization.yaml` (image pin + replicas: 1)
- `scripts/setup-devops.sh` (sentinel-proxy added to SERVICES array)
- `scripts/smoke-test-sentinel.sh`

## Methodology

Mechanical greps from `.agents/compliance-auditor.md`:

```bash
grep -rn 'eu-frankfurt-1\|us-ashburn-1\|us-phoenix-1' frontend/src/layers/sentinel.ts services/sentinel-proxy/
grep -rn 'CLIENT_ID\|CLIENT_SECRET\|INSTANCE_ID' frontend/src/layers/sentinel.ts
grep -rn 'INSERT INTO audit_events\|INSERT INTO osint_audit\|INSERT INTO audit_log' services/sentinel-proxy/
grep -rn 'os.environ\[.*KEY\|os.getenv(.*KEY' services/sentinel-proxy/
grep -rn '23ai\|23c' services/sentinel-proxy/
grep -rn 'WV\.layers' frontend/src/layers/sentinel.ts
grep -rn ': any' frontend/src/layers/sentinel.ts services/sentinel-proxy/
```

## ✓ Pass-Items

- **Audit-Tabelle korrekt:** `services/sentinel-proxy/app/audit.py` schreibt nur `INSERT INTO audit_events`. Keine Treffer für `osint_audit` oder `audit_log`. Audit-Batching auf 50 Tiles oder 30 s — schützt vor Flut bei Pan/Zoom.
- **OAuth-Credentials nicht im Browser-Bundle:** `frontend/src/layers/sentinel.ts` referenziert weder `CLIENT_ID` noch `CLIENT_SECRET` noch `INSTANCE_ID` — der Browser hit nur `/api/osint/sentinel/tiles/...`, alle Credentials bleiben im Backend.
- **OAuth-Token via ESO:** Drei Vault-OCIDs → eine `sentinel-credentials-secret`-K8s-Secret mit drei Daten-Keys (`SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET`, `SENTINEL_INSTANCE_ID`). Pydantic-settings liest sie via Env. Kein OCI-SDK-Call inside dem Pod (anders als das ais-multiplexer-Vault-Fallback-Pattern — hier nutzen wir konsequent die ESO-direct-Inject-Variante).
- **Region nicht hardcoded:** Einzige Region-Treffer in `app/settings.py` als `Field(default="eu-frankfurt-1")`-Konvention. Keine String-Konstanten in produktivem Code-Pfad.
- **Kein 23ai/23c-Residue:** 0 Treffer.
- **Kein IIFE-Pattern:** `WV\.layers` gibt 0 Treffer in `frontend/src/layers/sentinel.ts` — Layer-Modul ist strikt TypeScript + LayerRegistry.
- **Kein `: any`** im neuen TS-Code (Sentinel-Layer-Modul + Tests).
- **ATP-Env-Naming Plattform-konform:** `ORACLE_USER`/`ORACLE_PASSWORD`/`ORACLE_CONNECT_STRING`/`WALLET_PASSWORD` — gleiche Konvention wie alle anderen Services (gelernt aus Maritime-Erstrun-Bug).
- **ServiceAccount korrekt:** `sovdefence-runtime`. Health-Endpoint: `/healthz`. Port 8008 in Dockerfile-ENTRYPOINT + deploy.yaml + svc.yaml + ingress + nginx — kein Mismatch.
- **Resource-Sizing:** `requests = limits = 250m/512Mi` fix. Token-Cache + Tile-Forwarding sind I/O-bound, kein CPU-Burst zu erwarten.
- **Cache-Header für Browser:** `Cache-Control: public, max-age=3600` auf jedem Tile-Response — entlastet Sentinel-Hub-Quota.
- **Audit-Bypass:** `app/audit.py` hat keinen `try/except: pass` um den Insert. Failures werden geloggt + counter incremented.
- **Token-Failure-Robustness:** Refresh-Failure killt nicht den Service. In-flight Tile-Requests nutzen den (about-to-expire) gecachten Token; nächste Refresh-Iteration retried. Counter `sentinel_token_refresh_failures` steigt sichtbar in `/metrics`.
- **TS Build:** `npm run build` in `frontend/` durchläuft. `vitest run`: 70/70 (4 neu für Sentinel-Layer + alle bestehenden).
- **Python Compile + pytest:** `python3 -m py_compile app/*.py` clean. `pytest`: 8/8 (3 TokenManager + 5 Main, davon 2 Tile-Math).
- **Pre-Flight verified:** WMS-GetMap-Call gegen Sentinel-Hub mit echtem Token + Bornholm-Bbox liefert `PNG image data, 512 x 512, 8-bit/color RGBA, non-interlaced` (232 KB). gpsjam-style Spec-vs-Reality-Konflikt vermieden.

## ✗ Block-Items (must fix before commit)

*Keine.*

## ⚠ Warnings (non-blocking)

- **Kein Object-Storage-Tile-Cache.** Demo verlässt sich auf Browser-HTTP-Cache via `Cache-Control: max-age=3600`. Bei Sentinel-Hub-Quota-Engpass (Free-Tier hat 30k Requests/Monat) → OCI Object Storage Pattern-C-Bucket einbauen (write-through cache pro `(layer, z, x, y)`-Key). Tech-Debt-Item.
- **Keine Bbox-Spillover-Protection.** Aktuell durch jedes `(z, x, y)` durchgereicht — ein Angreifer könnte Tile-Calls für andere Regionen/Zoomstufen burnen, was Sentinel-Hub-Quota frisst. Sanity-Check gegen `SENTINEL_BBOX_DEFAULT` (Bornholm) lohnt, falls Quota knapp wird.
- **TokenManager hält den Token in Klartext im Pod-Memory.** Bei Pod-Memory-Dump (Forensics) wäre der OAuth-Token kompromittiert (Lifetime 30 min, daher begrenztes Risiko-Fenster). Industriestandard für OAuth-Bearer-Caches; nicht "broken", aber explicit dokumentiert.
- **`/api/osint/sentinel/layers` cacht 24 h** — bei Style-Änderung in der Sentinel-Hub Configuration UI muss der Pod neu gestartet werden, sonst sieht das Frontend bis zu 24 h die alte Layer-Liste. Manuelle `kubectl rollout restart deployment/sentinel-proxy` ist der Workaround.
- **Nicht-Default-Layer (`TRUE-COLOR`, `NDVI`, `NDMI`, `NDWI`, `FALSE-COLOR`) liefern noch 400** — die Default-Style-Config in der Sentinel-Hub UI ist nur für `TRUE-COLOR-HIGHLIGHT-OPTIMIZED` angelegt. Wenn der Demo Layer-Switching zeigen soll: Style für jedes Layer separat konfigurieren.
- **Liveness-Probe `tcpSocket`** — gleiche Plattform-weite Limitation wie compliance/maritime/jamming. Ein Pod mit kaputtem Token-Cache (z.B. dauerhafte Vault-Auth-Failure) erscheint live, fetcht aber 502 für jeden Tile.

## Verdict

**PASS_WITH_WARNINGS** — Code-Pfad ist commit-fähig. Keine Compliance-Verstöße. Alle 5 Warnings sind Verbesserungs-Hinweise; vier davon sind Quota- bzw. Operations-Themen für eine spätere Sprint-Iteration, einer (Style-Konfig der Non-Default-Layer) ist eine Sentinel-Hub-UI-Action.

## Reproducibility

```bash
cd /home/ubuntu/oci-defense-demo

grep -rn 'INSERT INTO audit_'   services/sentinel-proxy/
grep -rn 'os.environ\[.*KEY'    services/sentinel-proxy/
grep -rn 'WV\.layers'           frontend/src/layers/
grep -rn 'CLIENT_ID\|CLIENT_SECRET\|INSTANCE_ID' frontend/src/layers/sentinel.ts
grep -rn ': any'                frontend/src/layers/sentinel.ts services/sentinel-proxy/

cd frontend && npx vitest run --reporter=basic
cd ../services/sentinel-proxy && python3 -m pytest tests/ -x

kubectl kustomize k8s/overlays/prod | head -1
```
