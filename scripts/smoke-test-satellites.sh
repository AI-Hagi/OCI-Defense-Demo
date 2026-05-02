#!/usr/bin/env bash
# =============================================================================
# Recipe L Layer #5 — End-to-End Smoke Test for the UC4 TLE Proxy
# (Pattern A REST-poll over CelesTrak, three sub-layers: stations /
# resource / active).
#
# Verifies in order:
#   0. Pre-flight: required binaries.
#   1. /healthz returns a JSON status (200 or 503).
#   2. /metrics exposes tle_fetches_total + tle_cache_hits.
#   3. /api/osint/satellites/{stations|resource|active}/current each
#      return a TleCollection with count > 0 (or 503 cold-cache).
#   4. /api/osint/satellites/banana/current returns 404.
#   5. audit_events row written by tle-proxy in the last day
#      (only if SQLCL + ATP_TNS + ATP_USER are configured).
#   6. Frontend serves /lagebild.
#   7. Manual checklist printed at the end.
#
# Usage:
#   bash scripts/smoke-test-satellites.sh
#
# Required env (overrideable):
#   PROXY_BASE        (default http://localhost:8010)
#   FRONTEND_BASE     (default http://localhost:5173)
#   PUBLIC_LB         (e.g. http://152.70.18.236) — also probes ingress.
# Optional:
#   SQLCL, ATP_TNS, ATP_USER  — for step 5.
# =============================================================================
set -euo pipefail

PROXY_BASE="${PROXY_BASE:-http://localhost:8010}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:5173}"
PUBLIC_LB="${PUBLIC_LB:-}"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
section() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# -----------------------------------------------------------------------------
# 0. Pre-flight
# -----------------------------------------------------------------------------
section "0. Pre-flight"
for bin in curl python3; do
  command -v "$bin" >/dev/null 2>&1 || { red "FAIL: missing $bin"; exit 1; }
done
green "OK: curl, python3"

# -----------------------------------------------------------------------------
# 1. /healthz
# -----------------------------------------------------------------------------
section "1. tle-proxy /healthz"
hz_status="$(curl -sS -o /tmp/_tle_hz.json -w '%{http_code}' "${PROXY_BASE}/healthz" || echo 000)"
case "$hz_status" in
  200) green "OK: /healthz 200"; cat /tmp/_tle_hz.json; echo ;;
  503) yellow "DEGRADED: /healthz 503 (DB unreachable). Body:"; cat /tmp/_tle_hz.json; echo ;;
  000) red "FAIL: proxy unreachable at ${PROXY_BASE}"; exit 1 ;;
  *)   red "FAIL: /healthz returned ${hz_status}"; cat /tmp/_tle_hz.json; exit 1 ;;
esac

# -----------------------------------------------------------------------------
# 2. /metrics
# -----------------------------------------------------------------------------
section "2. /metrics counters"
metrics_body="$(curl -sS "${PROXY_BASE}/metrics")"
for m in tle_fetches_total tle_fetches_ok tle_fetches_failed tle_cache_hits tle_cache_misses; do
  if echo "$metrics_body" | grep -q "^${m} "; then
    green "OK: ${m} exposed"
  else
    red "FAIL: /metrics missing ${m}"
    exit 1
  fi
done

# -----------------------------------------------------------------------------
# 3. Three sub-layer endpoints
# -----------------------------------------------------------------------------
for group in stations resource active; do
  section "3.$group /api/osint/satellites/${group}/current"
  status_code="$(curl -sS -o /tmp/_tle_${group}.json -w '%{http_code}' "${PROXY_BASE}/api/osint/satellites/${group}/current" || echo 000)"
  resp_type="$(python3 -c 'import json; d=json.load(open("/tmp/_tle_'${group}'.json")); print(d.get("type",""))' 2>/dev/null || echo '')"
  count="$(python3 -c 'import json; d=json.load(open("/tmp/_tle_'${group}'.json")); print(d.get("count", len(d.get("tle",[]))))' 2>/dev/null || echo 0)"
  case "$status_code" in
    200)
      if [[ "$resp_type" == "TleCollection" ]] && [[ "$count" -gt 0 ]]; then
        green "OK: $group TleCollection with ${count} TLE records"
      else
        red "FAIL: $group 200 but invalid (type='$resp_type', count=$count)"
        exit 1
      fi
      ;;
    503)
      yellow "COLD-CACHE: $group 503 — first poller fetch hasn't completed yet"
      cat /tmp/_tle_${group}.json
      ;;
    *)
      red "FAIL: $group endpoint returned ${status_code}"
      exit 1
      ;;
  esac
done

# -----------------------------------------------------------------------------
# 4. Unknown group → 404
# -----------------------------------------------------------------------------
section "4. /api/osint/satellites/banana/current → 404"
status_code="$(curl -sS -o /tmp/_tle_404.json -w '%{http_code}' "${PROXY_BASE}/api/osint/satellites/banana/current" || echo 000)"
if [[ "$status_code" == "404" ]]; then
  green "OK: unknown group rejected with 404"
  cat /tmp/_tle_404.json
  echo
else
  red "FAIL: unknown group returned ${status_code} (expected 404)"
  cat /tmp/_tle_404.json
  exit 1
fi

# -----------------------------------------------------------------------------
# 5. audit_events row (optional)
# -----------------------------------------------------------------------------
section "5. audit_events row (optional)"
if [[ -n "${SQLCL:-}" && -n "${ATP_TNS:-}" && -n "${ATP_USER:-}" ]]; then
  q="SELECT COUNT(*) FROM audit_events WHERE actor_service='tle-proxy' AND event_time > SYSTIMESTAMP - INTERVAL '1' DAY;"
  echo "$q" | "$SQLCL" -L "${ATP_USER}@${ATP_TNS}" || yellow "WARN: SQLCL query failed"
else
  yellow "SKIP: set SQLCL, ATP_TNS, ATP_USER env vars to query audit_events live"
fi

# -----------------------------------------------------------------------------
# 6. Frontend serves /lagebild
# -----------------------------------------------------------------------------
section "6. Frontend /lagebild reachable"
fe_status="$(curl -sS -o /tmp/_tle_fe.html -w '%{http_code}' "${FRONTEND_BASE}/lagebild" || echo 000)"
if [[ "$fe_status" == "200" ]] && grep -q '<div id="root"' /tmp/_tle_fe.html; then
  green "OK: /lagebild served"
else
  yellow "WARN: /lagebild returned ${fe_status}"
fi

if [[ -n "$PUBLIC_LB" ]]; then
  section "6b. Public LB ${PUBLIC_LB}/api/osint/satellites/stations/current"
  lb_status="$(curl -sS -o /tmp/_tle_lb.json -w '%{http_code}' "${PUBLIC_LB}/api/osint/satellites/stations/current" || echo 000)"
  echo "public LB satellites/stations: ${lb_status}"
  if [[ "$lb_status" == "200" ]]; then
    green "OK: public LB serves stations TleCollection"
  else
    yellow "WARN: public LB returned ${lb_status} (frontend nginx proxy may not be reloaded yet)"
  fi
fi

# -----------------------------------------------------------------------------
# 7. Manual browser checklist
# -----------------------------------------------------------------------------
section "7. Manual browser checklist"
cat <<'CHECK'
Open ${FRONTEND_BASE}/lagebild in the browser and verify:

  [ ] Cesium globe renders, no console errors related to /api/osint/satellites.
  [ ] Sidebar lists three satellite toggles in the "Air" group:
      • "Satelliten: Stationen"
      • "Satelliten: Earth-Observation"
      • "Satelliten: Active"
  [ ] Activate "Satelliten: Stationen".
      → Within seconds: 5–10 purple billboards appear (ISS, Tiangong, …).
        Position updates ~once per second (visible drift).
  [ ] Click any billboard → Intel panel shows:
      • Name (e.g. "ISS (ZARYA)")
      • NORAD-ID (e.g. "25544")
      • Orbit-Klasse (LEO / MEO / GEO / HEO)
      • Periode in min
      • Höhe (aktuell), Position (aktuell)
      • Quelle: "CelesTrak NORAD GP — stations"
      • Classification badge: OPEN
  [ ] Activate "Satelliten: Earth-Observation".
      → ~150 small green dots appear; click one to see Mission =
        "Earth-Observation (CelesTrak resource)".
  [ ] Activate "Satelliten: Active".
      → 10–15 thousand cyan dots appear. Click is intentionally a
        no-op for this layer (PointPrimitive performance trade-off).
  [ ] Toggle each layer off → entities/points disappear, count → 0.
  [ ] Repeat enable/disable cycle 3× per layer — no console errors,
      no leaked entities.

Pass criteria: every box checked. Any FAIL above means stop and inspect.
CHECK
green "Smoke test sequence complete."
