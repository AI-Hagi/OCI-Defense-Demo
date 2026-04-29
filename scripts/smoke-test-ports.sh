#!/usr/bin/env bash
# =============================================================================
# Recipe L Layer #6 — End-to-End Smoke Test for the UC4 Ports Proxy
# (Pattern A static-load with hybrid OSM + curated classifier).
#
# Verifies in order:
#   0. Pre-flight: required binaries.
#   1. /healthz returns a JSON status.
#   2. /metrics exposes the expected counters.
#   3. /api/osint/ports/current returns a FeatureCollection.
#   4. /api/osint/ports/refresh without token returns 503 (refresh
#      disabled by default) — proves the endpoint is gated.
#   5. audit_events row written by ports-proxy in the last day
#      (only if SQLCL + ATP_TNS + ATP_USER are configured).
#   6. Frontend serves /lagebild.
#   7. Manual checklist printed at the end.
#
# Usage:
#   bash scripts/smoke-test-ports.sh
#
# Required env (overrideable):
#   PROXY_BASE        (default http://localhost:8011)
#   FRONTEND_BASE     (default http://localhost:5173)
#   PUBLIC_LB         (e.g. http://152.70.18.236) — also probes ingress.
# Optional:
#   SQLCL, ATP_TNS, ATP_USER  — for step 5.
# =============================================================================
set -euo pipefail

PROXY_BASE="${PROXY_BASE:-http://localhost:8011}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:5173}"
PUBLIC_LB="${PUBLIC_LB:-}"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
section() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

section "0. Pre-flight"
for bin in curl python3; do
  command -v "$bin" >/dev/null 2>&1 || { red "FAIL: missing $bin"; exit 1; }
done
green "OK: curl, python3"

section "1. ports-proxy /healthz"
hz_status="$(curl -sS -o /tmp/_p_hz.json -w '%{http_code}' "${PROXY_BASE}/healthz" || echo 000)"
case "$hz_status" in
  200) green "OK: /healthz 200"; cat /tmp/_p_hz.json; echo ;;
  503) yellow "DEGRADED: /healthz 503"; cat /tmp/_p_hz.json; echo ;;
  000) red "FAIL: proxy unreachable at ${PROXY_BASE}"; exit 1 ;;
  *)   red "FAIL: /healthz returned ${hz_status}"; exit 1 ;;
esac

section "2. /metrics counters"
metrics_body="$(curl -sS "${PROXY_BASE}/metrics")"
for m in ports_cache_hits ports_cache_misses ports_classifier_lookups ports_curated_matches ports_osm_fallbacks ports_last_feature_count ports_last_run_ok; do
  if echo "$metrics_body" | grep -q "^${m} "; then
    green "OK: ${m} exposed"
  else
    red "FAIL: /metrics missing ${m}"
    exit 1
  fi
done

section "3. /api/osint/ports/current"
status_code="$(curl -sS -o /tmp/_p_curr.json -w '%{http_code}' "${PROXY_BASE}/api/osint/ports/current" || echo 000)"
resp_type="$(python3 -c 'import json; d=json.load(open("/tmp/_p_curr.json")); print(d.get("type",""))' 2>/dev/null || echo '')"
count="$(python3 -c 'import json; d=json.load(open("/tmp/_p_curr.json")); print(len(d.get("features",[])))' 2>/dev/null || echo 0)"
case "$status_code" in
  200)
    if [[ "$resp_type" == "FeatureCollection" ]]; then
      green "OK: FeatureCollection with ${count} ports"
    else
      red "FAIL: 200 but not a FeatureCollection (type='$resp_type')"
      exit 1
    fi
    ;;
  503)
    yellow "COLD-CACHE: bootstrap loader hasn't finished yet."
    cat /tmp/_p_curr.json; echo
    ;;
  *)
    red "FAIL: /current returned ${status_code}"
    exit 1
    ;;
esac

section "4. /api/osint/ports/refresh without X-Internal-Token → 503"
ref_status="$(curl -sS -X POST -o /tmp/_p_ref.json -w '%{http_code}' "${PROXY_BASE}/api/osint/ports/refresh" || echo 000)"
if [[ "$ref_status" == "503" ]]; then
  green "OK: refresh disabled by default (PORTS_INTERNAL_TOKEN unset)"
else
  yellow "WARN: /refresh returned ${ref_status} (expected 503 when token unset)"
fi

section "5. audit_events row (optional)"
if [[ -n "${SQLCL:-}" && -n "${ATP_TNS:-}" && -n "${ATP_USER:-}" ]]; then
  q="SELECT COUNT(*) FROM audit_events WHERE actor_service='ports-proxy' AND event_time > SYSTIMESTAMP - INTERVAL '1' DAY;"
  echo "$q" | "$SQLCL" -L "${ATP_USER}@${ATP_TNS}" || yellow "WARN: SQLCL query failed"
else
  yellow "SKIP: set SQLCL, ATP_TNS, ATP_USER to query audit_events live"
fi

section "6. Frontend /lagebild reachable"
fe_status="$(curl -sS -o /tmp/_p_fe.html -w '%{http_code}' "${FRONTEND_BASE}/lagebild" || echo 000)"
if [[ "$fe_status" == "200" ]] && grep -q '<div id="root"' /tmp/_p_fe.html; then
  green "OK: /lagebild served"
else
  yellow "WARN: /lagebild returned ${fe_status}"
fi

if [[ -n "$PUBLIC_LB" ]]; then
  section "6b. Public LB ${PUBLIC_LB}/api/osint/ports/current"
  lb_status="$(curl -sS -o /tmp/_p_lb.json -w '%{http_code}' "${PUBLIC_LB}/api/osint/ports/current" || echo 000)"
  echo "public LB ports endpoint: ${lb_status}"
fi

section "7. Manual browser checklist"
cat <<'CHECK'
Open ${FRONTEND_BASE}/lagebild in the browser and verify:

  [ ] Sidebar lists "Häfen" toggle in the "Maritime" group.
  [ ] Activate "Häfen".
      → Within seconds: anchor / hook / sail icons appear across
        Europe + Mediterranean. Curated NATO/Bundeswehr ports are
        red anchors (military) or blue anchors (commercial).
  [ ] Click any port → Intel panel shows:
      • Name, Typ (commercial/military/fishing/marina/mixed)
      • Quelle: "Bundeswehr/NATO Stammdaten" (curated) or "OpenStreetMap"
      • OSM-ID
      • For curated rows: NATO-Mitglied + Bundeswehr-Anlage
      • Classification badge: OPEN
  [ ] Filter checkboxes (alongside the layer toggle):
      • [x] Commercial [x] Military [x] Fishing [x] Marina [x] Mixed
      • Toggle "Military" off → red anchors disappear, count drops.
      • Toggle it back on → anchors return.
  [ ] Toggle "Häfen" off → all icons disappear, count → 0.

Pass criteria: every box checked. Any FAIL above means stop and inspect.
CHECK
green "Smoke test sequence complete."
