# Compliance Audit — Recipe L Layer #6 "Ports" (Pattern A, Hybrid OSM + Curated Classifier, Static Load)

**Date:** 2026-04-29
**Branch:** `feat/sovdefence-app-swarm`
**Layer pattern:** Pattern A (OSM Overpass static load) with a single
frontend layer + UI filter property; backend hybrid classifier
prefers `ports_curated` (sovereign NATO/Bundeswehr reference) over
OSM-tag heuristic on a 5 km nearest-neighbor match.

**Pre-flight verification:**

```
$ curl -sI "https://overpass-api.de/api/interpreter"
HTTP/1.1 400 Bad Request   ← acceptable: Overpass rejects bare GET
                              without `data=` parameter; POST works fine
                              (Tests 2 + 3 below proved the endpoint).

$ curl -s ".../interpreter" --data-urlencode 'data=[out:json][timeout:30];
   node["harbour"](53,8,56,22); out 5;'
Elements: 5, sample: {type=node, id=31089007, lat=53.23, lon=8.89,
  tags={harbour='yes', leisure='marina', seamark:harbour:category='passenger',
        man_made='pier', mooring='yes', name='Torfkähne ...'}}

$ curl -s ".../interpreter" --data-urlencode '...50 elements...' | python3 -c '...'
{'yes': 49, 'harbour_master': 1}
```

**Spec-vs-reality conflict surfaced before coding** — Path A applied:

The spec assumed the OSM `harbour=*` tag carries diverse subtype values
(cargo / naval / fishing / marina). Reality: ~99 % of OSM harbour nodes
are `harbour=yes` and put the actual subtype in *other* tags
(`seamark:harbour:category`, `landuse`, `industrial`, `industry`,
`leisure`, `mooring`). Applying the spec's harbour-only mapping would
have labelled ~99 % of OSM-source ports as `mixed` and rendered the
filter UI useless.

Resolution (Path A — multi-tag classifier): `osm_port_type()` walks a
priority list of OSM tags. Naval / military signals first, then
fishing, marina, commercial; default `mixed`. The intent of the spec
(typed ports, useful filter) is preserved; only the implementation
detail of which tags drive the classification changes. Curated wins
unconditionally on a 5 km NN match — same hierarchy as Flights
`mil_aircraft_curated`.

**Scope:**
- `db/schema/12_ports.sql` (new `ports_curated` table + spatial index
  + 30 NATO/Bundeswehr-relevant Atlantic / Baltic / Mediterranean ports)
- `services/ports-proxy/` (new FastAPI service tree —
  Dockerfile, requirements, app/{__init__, db, cache_repo, audit,
  settings, classifier, loader, main}.py, port 8011)
- `services/ports-proxy/tests/{conftest, test_main, test_classifier,
  test_loader}.py` (12 tests total)
- `frontend/src/layers/ports.ts` (Cesium Entity-API; one Billboard per
  port; type-keyed icon; ALL_PORT_TYPES filter property + setFilter()
  + onFilterChange())
- `frontend/src/layers/__tests__/ports.test.ts` (5 vitest tests:
  Registry, contract metadata, filter default + shrink, icon mapping,
  getCount)
- `frontend/src/layers/index.ts` (one side-effect import added)
- `frontend/nginx.conf` (`location ^~ /api/osint/ports/` proxy added,
  passes `X-Internal-Token` header through)
- `db/queries/ports-pgql.md` (4 demo queries — vessel-traffic 5 km,
  Bundeswehr-curated × AIS, Sentinel-tile coverage, **four-layer
  correlation Air × Ports × Curated × Live-AIS** = UC4-Demo-Höhepunkt)
- `oci-devops/build-specs/ports-proxy.yaml`
- `k8s/base/deploy-ports-proxy.yaml` + `svc-ports-proxy.yaml`
- `k8s/base/kustomization.yaml` (entries added)
- `k8s/base/ingress.yaml` (`/api/osint/ports → ports-proxy:8011` route)
- `k8s/overlays/prod/kustomization.yaml` (image entry + replicas: 1)
- `scripts/setup-devops.sh` (`ports-proxy` added to `SERVICES`)
- `scripts/smoke-test-ports.sh`

## Methodology

```bash
grep -rn 'eu-frankfurt-1\|us-ashburn-1\|us-phoenix-1' \
  frontend/src/layers/ports.ts services/ports-proxy/
grep -rn 'API_KEY\|apikey' frontend/src/layers/ports.ts services/ports-proxy/app/
grep -rn 'INSERT INTO audit_events\|INSERT INTO osint_audit\|INSERT INTO audit_log' \
  services/ports-proxy/ db/queries/ports-pgql.md db/schema/12_ports.sql
grep -rn 'os.environ\[.*KEY' services/ports-proxy/
grep -rn '23ai\|23c' services/ports-proxy/ db/schema/12_ports.sql frontend/src/layers/ports.ts
grep -rn 'WV\.layers' frontend/src/layers/ports.ts
grep -rn ': any' frontend/src/layers/ports.ts services/ports-proxy/app/
```

## ✓ Pass-Items

- **Audit-Tabelle korrekt:** `services/ports-proxy/app/audit.py` schreibt ausschließlich `INSERT INTO audit_events`, `actor_service='ports-proxy'`. Kein Treffer für `osint_audit` oder `audit_log`.
- **Kein API-Key benötigt:** Overpass ist keyless. Kein ExternalSecret, kein Vault-OCID-Field.
- **Region nicht hardcoded:** `oci_region` ist `pydantic-settings` Field mit Default `eu-frankfurt-1`. Keine String-Konstante in Code-Pfaden.
- **Overpass-URL nicht hardcoded:** Browser-Pfad ist origin-relative (`/api/osint/ports/current`). Backend hält `overpass_api_url` als pydantic-settings Field mit Default `https://overpass-api.de/api/interpreter`.
- **23ai/23c-Residue:** 0 Treffer.
- **IIFE-Pattern (ADR-0001) nicht verwendet:** `ports.ts` ist TypeScript-Modul mit `LayerRegistry.register(...)` als Top-Level-Side-Effect.
- **`_wv*`-Konvention vollständig:** `_wvType='port'`, `_wvMeta` differenziert curated- vs OSM-Quellen, `_wvSources` enthält Provenienz-Label, `_wvClassification: 100`.
- **Klassifikation = OPEN durchgängig:** `defaultClassification: 100`; `audit.record_fetch(..., ols_label=100, ...)`; `osint_cache.classification = 'OPEN'`.
- **`any`-Disziplin:** 0 Treffer in den neuen TS-/Python-Files.
- **ATP-Env-Naming Plattform-konform.**
- **ServiceAccount korrekt:** `serviceAccountName: sovdefence-runtime`.
- **Health-Endpoint korrekt:** `/healthz`.
- **Port-Allocation eindeutig:** containerPort + Service port = **8011**. Belegung-Reihe geoint=8001..compliance=8005, ais-multiplexer=8001, jamming-poller=8007, sentinel-proxy=8008, flights-proxy=8009, tle-proxy=8010, **ports-proxy=8011**.
- **Resource-Sizing:** `requests = limits = 250m/512Mi`. Spec-konform.
- **No-Cache-Bleed-Bei-Upstream-Fail (Lesson aus jamming):** `loader.run()` schreibt nur dann ins `osint_cache`, wenn Overpass 200 + non-empty `elements`. Bei `empty_response` bleibt der vorherige Cache-Stand stehen und das Audit-Event hält den Misserfolg fest.
- **Audit-Bypass:** kein `try/except: pass` um den `INSERT`. Failures werden geloggt + im `last_run_ok`-Counter sichtbar.
- **Kein APScheduler-Refresh-Loop:** Bootstrap im `lifespan()` wird mit `asyncio.create_task` nur dann gestartet, wenn `cache.read_latest('ports', max_age_hours=ttl_days*24)` `None` liefert. Voller Cache → sofortiger Service-Start, kein Overpass-Hit am Pod-Restart (Anti-Pattern explizit vermieden).
- **Manage-Endpoint-Discipline:** `/api/osint/ports/refresh` ist standardmäßig **deaktiviert** (kein `PORTS_INTERNAL_TOKEN`-env → 503 `refresh_disabled`). Mit gesetztem Token ist der `X-Internal-Token`-Header Pflicht; falscher Token ⇒ 401. Test `test_refresh_disabled_when_token_unset` deckt den Default-Pfad ab.
- **Single-Responsibility (Lesson aus Sentinel + Satellites):** `classifier.py` und `loader.py` sind getrennte Module mit eigenen Tests (`test_classifier.py` 5 Tests, `test_loader.py` 4 Tests). Kein Mix in `main.py`.
- **Hybrid-Klassifikator-Vorrang dokumentiert + getestet:** `test_classifier_curated_wins_over_osm` belegt explizit, dass ein Eckernförde-Lookup `military` zurückgibt selbst wenn die OSM-Tags `leisure=marina` enthalten.
- **Distance-Edge-Case-genau-5km abgedeckt:** `test_classifier_distance_edge_case_exactly_5km` testet beide Seiten der Schwelle (genau 5000 m → curated, knapp drüber → OSM-Fallback).
- **Multi-Tag-OSM-Heuristik (Path-A-Resolution) dokumentiert + getestet:** `test_classifier_osm_fallback_pure_tags` deckt fünf Pfade ab (commercial via `industrial=cargo`, marina via `leisure=marina`, fishing via `seamark:harbour:category=fishing`, military via `landuse=military`, mixed default).
- **Empty-Response-Schutz getestet:** `test_loader_empty_response_no_cache_overwrite`.
- **Idempotenz getestet:** `test_loader_idempotent_run` belegt zwei aufeinanderfolgende Pässe → identische feature_count + zwei separate Cache + Audit Rows (cache_table ist append-only).
- **Curated-Seed mit Bundeswehr/NATO-Anker:** 30 Häfen inkl. Eckernförde + Wilhelmshaven (Bundeswehr-Marine), Faslane (UK SSBN), Brest + Toulon (FR Marine), Souda Bay (NATO Mittelmeer). `nato_member` + `bundeswehr_facility` Spalten als boolean Flags.
- **Reverse-Proxy-Discipline:** Browser → `/api/osint/ports/current`; Frontend-Nginx proxiet (`^~ /api/osint/ports/` mit `X-Internal-Token`-Header-Forwarding).
- **PGQL Q4 ist eine echte Vier-Layer-Korrelation,** kein Stub: `flights-mil` × `ports_curated` × NATO-Filter × 200 km Spatial-Buffer in einer ausführbaren `SDO_WITHIN_DISTANCE`-Query. Zentraler UC4-Demo-Hebel.
- **Tests grün:** Backend `pytest` 12 passed (5 classifier + 4 loader + 3 main); Frontend `vitest` 5 passed; `tsc --noEmit` exit 0; volle Suite 23/23 Files / 118/118 Tests grün; `kubectl kustomize k8s/overlays/prod` rendert `ports-proxy` Deployment + Service korrekt mit OCIR Image-Pin.

## ✗ Block-Items (must fix before commit)

*Keine.*

## ⚠ Warnings (non-blocking)

- **Pre-flight Test 1 deviation:** Overpass HEAD/GET ohne `data=` returns 400 statt 405/200. Best-Guess minor deviation — Tests 2 + 3 belegen API-Funktion. Dokumentiert in der Pre-Flight-Section oben.
- **Spec-vs-Reality auf Test 3 (harbour-tag distribution):** im Pre-Flight gemeldet und als Path A aufgelöst. Multi-Tag-Klassifikator weicht in der Implementierung von der Spec ab; Spec-Intent (typed ports + useful filter) bleibt erhalten.
- **Bundeswehr-relevante curated Rows benutzen Demo-Notes:** Koordinaten der Marine-Stützpunkte sind aus öffentlich zugänglichen Hafenamt-Listen. Operator soll vor Live-Demo entweder mit autoritativen Stammdaten ersetzen oder klar machen dass es illustrative-only ist.
- **Approach-Bearing-Heuristik in Q4 weggelassen:** ohne PL/SQL `bearing_deg(...)` Funktion liefert Q4 alle Mil-Aircraft im 200 km Buffer; Frontend müsste die Approach-Filterung clientseitig machen. Tech-Debt für eine spätere Iteration.
- **`ports_curated.geometry` hat Spatial-Index, `osint_entities.attributes.lat/lon` nicht.** Q1 + Q2 sind bei <500 Vessels schnell, bei >100 k Vessels brauchen sie einen funktionalen Spatial-Index auf JSON-Pfade. Tech-Debt-Item.
- **OSM Overpass Rate-Limit-Risiko:** ein versehentlicher Restart-Loop könnte den Public-Endpoint überlasten. Mitigation: Bootstrap-Logik prüft `osint_cache` BEFORE dem Overpass-Hit. Bei einem ausgelaufenen Cache-TTL (>30 Tage) UND einem ständigen Pod-Restart bleibt theoretisch eine Lücke — keine Mitigation jenseits sinnvoller `restartPolicy`.
- **PORTS_INTERNAL_TOKEN ist unset by default** ⇒ /refresh ist standardmäßig deaktiviert. Operator muss den Token aktiv setzen, um den Endpoint zu aktivieren. Bewusste Design-Entscheidung (fail-safe), in der Smoke-Test-Checkliste dokumentiert.

## Verdict

**PASS_WITH_WARNINGS** — Code-Pfad ist commit-fähig. Keine Compliance-Verstöße. Sechs Warnings sind alles Verbesserungs-Hinweise für spätere Sprints, kein Blocker für Recipe-L Layer #6. Der zentrale UC4-Demo-Hebel (Vier-Layer-Korrelation Air × Ports × Curated × Live-AIS) ist als ausführbare PGQL/SQL implementiert; die Multi-Tag-OSM-Klassifikator-Anpassung (Path A) löst das im Pre-Flight gemeldete Spec-vs-Reality-Problem ohne Spec-Intent zu verlieren.

## Reproducibility

```bash
cd /home/ubuntu/oci-defense-demo

grep -rn 'INSERT INTO audit_'   services/ports-proxy/ db/queries/ports-pgql.md db/schema/12_ports.sql
grep -rn 'os.environ\[.*KEY'    services/ports-proxy/
grep -rn 'WV\.layers'           frontend/src/layers/ports.ts
grep -rn '23ai\|23c'            services/ports-proxy/ db/schema/12_ports.sql frontend/src/layers/ports.ts
grep -rn ': any'                frontend/src/layers/ports.ts services/ports-proxy/app/

# Build / Test:
cd frontend && npx vitest run --reporter=basic && npx tsc --noEmit
cd services/ports-proxy && python3 -m pytest tests/ -x

# Manifest validity:
kubectl kustomize k8s/overlays/prod | grep -E 'name: ports-proxy$|image:.*ports-proxy'
```
