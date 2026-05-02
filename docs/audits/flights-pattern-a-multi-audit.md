# Compliance Audit — Recipe L Layer #4 "Flights" (Pattern A, Multi-Sub-Layer, Hybrid Classifier)

**Date:** 2026-04-28
**Branch:** `feat/sovdefence-app-swarm`
**Layer pattern:** Pattern A (REST poll) with two logical sub-layers (`flights-civil` + `flights-mil`) served by a single backend service. The classifier walks `mil_aircraft_curated` (sovereign) → `mil_aircraft_mictronics` (community) → `civil` (default).
**Data-source pivot note:** the original spec referenced a Mictronics CSV
(`https://raw.githubusercontent.com/Mictronics/readsb/dev/webapp/src/db/aircrafts.csv`); that file does not exist in the upstream repo. The implementation polls **`aircrafts.json`** on the same dev branch (~28 MB, ~445 k entries, mil-flag = bit 0 of `f`). Schema and frontend wire format are unchanged; only the loader script's parser changed.

**Scope:**
- `frontend/src/layers/flights-civil.ts` + `__tests__/flights-civil.test.ts`
- `frontend/src/layers/flights-mil.ts`   + `__tests__/flights-mil.test.ts`
- `frontend/src/layers/index.ts` (two side-effect imports added)
- `frontend/nginx.conf` (`location ^~ /api/osint/flights/` proxy added)
- `services/flights-proxy/` (new FastAPI service tree, REST poll + hybrid classifier)
- `db/schema/11_flights_curated.sql` (`mil_aircraft_curated`, `mil_aircraft_mictronics`, view `mil_aircraft_unified`)
- `db/queries/flights-pgql.md` (3 demo SQL/PGQ queries — incl. Air × EW × Maritime triple correlation)
- `scripts/load-mictronics-aircraft.sh` (manual weekly Mictronics JSON loader)
- `oci-devops/build-specs/flights-proxy.yaml`
- `k8s/base/deploy-flights-proxy.yaml` + `svc-flights-proxy.yaml`
- `k8s/base/kustomization.yaml` (flights entries added)
- `k8s/base/ingress.yaml` (`/api/osint/flights` route added)
- `k8s/overlays/prod/kustomization.yaml` (image entry + replicas: 1)
- `scripts/setup-devops.sh` (`flights-proxy` added to `SERVICES`)
- `scripts/smoke-test-flights.sh`

## Methodology

The same mechanical grep checklist from `.agents/compliance-auditor.md`, applied to the new files:

```bash
grep -rn 'eu-frankfurt-1\|us-ashburn-1\|us-phoenix-1' \
  frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts services/flights-proxy/
grep -rn 'API_KEY\|apikey\|adsb\.lol' \
  frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts
grep -rn 'INSERT INTO audit_events\|INSERT INTO osint_audit\|INSERT INTO audit_log' \
  services/flights-proxy/ db/schema/11_flights_curated.sql
grep -rn 'os.environ\[.*KEY' services/flights-proxy/
grep -rn '23ai\|23c' db/schema/11_flights_curated.sql services/flights-proxy/
grep -rn 'WV\.layers' frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts
grep -rn '_wvClassification\|_wvType' \
  frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts
grep -rn ': any' frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts services/flights-proxy/
```

## ✓ Pass-Items

- **Audit-Tabelle korrekt:** `services/flights-proxy/app/audit.py` schreibt ausschließlich `INSERT INTO audit_events`. Kein Treffer für `osint_audit` oder `audit_log`.
- **Kein API-Key benötigt:** adsb.lol publiziert öffentliche JSON-Snapshots ohne Authentifizierung. Kein ExternalSecret, kein Vault-OCID-Field — die Settings erwähnen das gar nicht. Identische Eigenschaft wie jamming-poller.
- **adsb.lol-URL nicht hardcoded** im Frontend-Code: Die einzigen Browser-Pfade gehen gegen `/api/osint/flights/{civil|mil}/current` (origin-relative). Backend hält `adsb_api_base` als pydantic-settings-Field mit Default — der Browser sieht nur die Sovereign-Proxy-URL.
- **Region nicht hardcoded:** `oci_region` ist `pydantic-settings` Field mit Default `eu-frankfurt-1`. Keine String-Konstante in Code-Pfaden.
- **23ai/23c-Residue:** `grep -rn '23ai\|23c' db/schema/11_flights_curated.sql services/flights-proxy/` → 0 Treffer. Kommentare sprechen ausschließlich von 26ai.
- **IIFE-Pattern (ADR-0001) nicht verwendet:** `grep -rn 'WV\.layers' frontend/src/layers/flights-*.ts` → 0. Beide Layer sind TypeScript-Module mit `LayerRegistry.register(...)` als Top-Level-Side-Effect.
- **`_wv*`-Konvention vollständig** in beiden Sub-Layern:
  - civil: `_wvType='aircraft'`, `_wvSources=['adsb.lol via ADS-B Exchange community feeders']`
  - mil: `_wvType='aircraft'`, `_wvSources` enthält zusätzlich die DB-Provenienz (`Bundeswehr-Stammdaten` oder `Mictronics community DB`) je nach Verdict.
  Beide setzen `_wvClassification: 100` (numerisch, OPEN).
- **Klassifikation = OPEN durchgängig:** Pattern-A-Default `defaultClassification: 100` in beiden Layer-Modulen; Backend `audit.record_fetch(..., ols_label=100, ...)`; `osint_cache.classification = 'OPEN'` für beide Sub-Layer.
- **`any`-Disziplin:** `grep -rn ': any' frontend/src/layers/flights-*.ts` → 0 Treffer. Jeder Feature-Property-Pfad ist getypt (`FlightProperties`, `FlightFeature`, `FlightFeatureCollection`).
- **ATP-Env-Naming Plattform-konform:** `app/settings.py` aliases sind `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_CONNECT_STRING`, `WALLET_PASSWORD`. Identisch zu compliance, geoint, osint-fusion, ais-multiplexer, jamming-poller.
- **ServiceAccount korrekt:** `serviceAccountName: sovdefence-runtime` (Plattform-Standard).
- **Health-Endpoint korrekt:** `/healthz`; ReadinessProbe in `deploy-flights-proxy.yaml` zeigt auf den richtigen Pfad.
- **Port-Allocation eindeutig:** containerPort + Service port = **8009**. Belegung: geoint=8001..compliance=8005, ais-multiplexer=8001 (eigener Service), jamming-poller=8007, sentinel-proxy=8008, **flights-proxy=8009**. Keine Kollisionen. Dockerfile ENTRYPOINT bindet auf 8009 — kein Port-Mismatch.
- **Resource-Sizing:** `requests = limits = 250m/512Mi` fix. Identisch zu jamming-poller (Pattern-A, kein WS, eine APScheduler-Tick alle 2 min). Virtual-Node-Guaranteed-QoS.
- **Audit-Bypass:** `app/audit.py` hat keinen `try/except: pass` um den `INSERT INTO audit_events`. Failures werden geloggt + counter incremented, aber der nächste Tick versucht es wieder.
- **No-Cache-Bleed-Bei-Upstream-Fail:** `poller.fetch_once()` schreibt nur dann ins `osint_cache`, wenn Upstream 200 + non-empty Body + Parse-OK. Bei 4xx/5xx/Network/Empty-Body bleibt der vorherige Cache-Stand stehen.
- **Hybrid-Klassifikator fail-open:** `app/classifier.py` `_lookup()` exception-handler returniert `Verdict('civil', None, None)` und cached *nicht* — der nächste Tick retried die DB. Kein „False-Mil-Stamp bei DB-Outage".
- **In-Process-Cache-Hits + DB-Lookups Metric-getragen:** `flights_classifier_lookups` und `flights_classifier_cache_hits` in `/metrics` exposed; Tests `test_classifier_in_process_cache_hits` & `test_classifier_db_error_fails_open` decken Hit-Path und Fail-Open-Path ab.
- **Reverse-Proxy-Discipline:** Browser → `/api/osint/flights/civil/current` und `/api/osint/flights/mil/current`; Frontend-Nginx proxiet (siehe neue `location ^~ /api/osint/flights/`-Block); Ingress-Rule `pathType: Prefix /api/osint/flights → flights-proxy:8009`. Keine direkten adsb.lol-Calls aus dem Browser.
- **Curated > Mictronics > civil deterministic:** Die View `mil_aircraft_unified` setzt `UNION ALL` mit Filter `NOT EXISTS (SELECT 1 FROM mil_aircraft_curated c WHERE c.hex24 = m.hex24)` für die Mictronics-Hälfte. Test `test_classifier_curated_match` verifiziert die Präzedenz auf Klassifikator-Ebene.
- **Mictronics-Loader idempotent:** `scripts/load-mictronics-aircraft.sh` macht TRUNCATE + executemany INSERT, batchsize 500. Wiederholtes Aufrufen führt zum identischen DB-State.
- **DevOps-Glue konsistent:** `setup-devops.sh` `SERVICES` array um `flights-proxy` erweitert; OCIR-Repo, Build-Pipeline, Deploy-Pipeline, Code-Push-Trigger werden auto-provisioniert beim nächsten Run.
- **Tests grün:** Backend `pytest` 9 passed; Frontend `vitest` 78 passed (incl. 4 flights-civil + 4 flights-mil); `tsc --noEmit` exit 0; `kubectl kustomize k8s/overlays/prod` rendert `flights-proxy` Deployment + Service korrekt mit OCIR-Image-Pin.

## ✗ Block-Items (must fix before commit)

*Keine.*

## ⚠ Warnings (non-blocking)

- **adsb.lol ist Open Community Feed, kein SLA.** Wenn upstream temporär 5xx liefert oder Cloudflare den Sovereign-Proxy-IP rate-limitet, bleibt der Cache stale. Operator sieht das im `flights_fetches_failed`-Counter und an `fetched_at` im Payload. Mitigation: Add a Cloudflare-Friendly User-Agent header oder ein Fallback auf opensky-network.org. Nicht blocking — sentinel-proxy hat dasselbe Risiko-Profil.
- **Mictronics-Stammdaten-Refresh ist manuell.** `scripts/load-mictronics-aircraft.sh` muss wöchentlich vom Operator gefahren werden. Eine OCI-DevOps-Pipeline mit Wochen-Trigger oder ein OCI-Functions-Schedule wäre die saubere Auto-Variante. Tech-Debt-Item.
- **Kein Spatial-Index auf `osint_cache.payload.features[*].geometry.coordinates`.** Die Triple-Correlation-Query in `db/queries/flights-pgql.md` Q3 nutzt eine Bbox-Bounding-Heuristik (`ABS(lat-vlat) < 1.0`) statt eines echten `SDO_RELATE`. Bei <500 Aircraft pro Snapshot funktioniert das, aber bei einem 5000-Aircraft-Datensatz wäre die Query langsam. Eine alternative Materialisierung als `osint_entities(kind='aircraft')` mit getrenntem Spatial-Index wäre der Ausbau-Pfad — Kandidat für eine spätere Iteration.
- **Cache-Pruning fehlt** (gemeinsam mit jamming + sentinel). `osint_cache` wächst monoton: 2 Rows pro 2-min-Tick × 720 Ticks/Tag = ~1.440 Rows/Tag × ~50 KB Payload ≈ 70 MB/Tag — bei 90 Tagen ~6.3 GB. ATP hat genug Headroom, aber eine TTL-Job-DELETE wäre hygienisch.
- **Replicas: 1 ist hart codiert** für den APScheduler-Singleton. Eine HPA mit Lock-Tabelle wäre nötig, um Multi-Replica-Fetch ohne Doppel-Tick zu erlauben. Heute ist 1 Replica + RollingUpdate `maxUnavailable: 0` der pragmatische Weg.
- **Demo-Seed-Rows in `mil_aircraft_curated` sind explizit als `notes='demo placeholder'` markiert** — keine autoritativen Bundeswehr-Daten. Operator muss vor Live-Demo entweder (a) mit echten Stammdaten ersetzen oder (b) der Audience deutlich kommunizieren, dass die curated rows illustrative-only sind.

## Verdict

**PASS_WITH_WARNINGS** — Code-Pfad ist commit-fähig. Keine Compliance-Verstöße. Sechs Warnings sind alles Verbesserungs-Hinweise für spätere Sprints, kein Blocker für Recipe-L Layer #4. Die zentrale UC4-Demo-Story (Air × EW × Maritime, Sovereign-Klassifikator über curated > Mictronics > civil) ist End-to-End sauber implementiert.

## Reproducibility

```bash
cd /home/ubuntu/oci-defense-demo

grep -rn 'INSERT INTO audit_'   services/flights-proxy/ db/schema/11_flights_curated.sql
grep -rn 'os.environ\[.*KEY'    services/flights-proxy/
grep -rn 'WV\.layers'           frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts
grep -rn '23ai\|23c'            db/schema/11_flights_curated.sql services/flights-proxy/
grep -rn ': any'                frontend/src/layers/flights-civil.ts frontend/src/layers/flights-mil.ts services/flights-proxy/

# Build / Test:
cd frontend && npx vitest run --reporter=basic && npx tsc --noEmit
cd services/flights-proxy && python3 -m pytest tests/ -x

# Manifest validity:
kubectl kustomize k8s/overlays/prod | grep -E 'name: flights-proxy$'
```
