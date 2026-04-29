#!/usr/bin/env bash
# =============================================================================
# Recipe L Layer #2 — End-to-End Smoke Test for the UC4 GPS Jamming poller.
#
# Verifies in order:
#   0. Pre-flight: required binaries.
#   1. /healthz returns a JSON status (200 or 503).
#   2. /metrics exposes jamming_fetches_total + jamming_cache_hits.
#   3. /api/osint/jamming/current returns a GeoJSON FeatureCollection
#      (200 with features, or 503 cold-cache shape — both are acceptable).
#   4. audit_events row written by jamming-poller in the last day
#      (only if SQLCL + ATP_TNS + ATP_USER are configured).
#   5. Frontend serves /lagebild.
#   6. Manual checklist printed at the end.
#
# Usage:
#   bash scripts/smoke-test-jamming.sh
#
# Required env (overrideable):
#   POLLER_BASE       (default http://localhost:8007)
#   FRONTEND_BASE     (default http://localhost:5173)
#   PUBLIC_LB         (e.g. http://152.70.18.236) — if set, also probes
#                      the public ingress path.
# Optional:
#   SQLCL, ATP_TNS, ATP_USER  — for step 4.
# =============================================================================
set -euo pipefail

POLLER_BASE="${POLLER_BASE:-http://localhost:8007}"
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
section "1. jamming-poller /healthz"
hz_status="$(curl -sS -o /tmp/_jam_hz.json -w '%{http_code}' "${POLLER_BASE}/healthz" || echo 000)"
case "$hz_status" in
  200) green "OK: /healthz 200"; cat /tmp/_jam_hz.json; echo ;;
  503) yellow "DEGRADED: /healthz 503 (DB unreachable). Body:"; cat /tmp/_jam_hz.json; echo ;;
  000) red "FAIL: poller unreachable at ${POLLER_BASE}"; exit 1 ;;
  *)   red "FAIL: /healthz returned ${hz_status}"; cat /tmp/_jam_hz.json; exit 1 ;;
esac

# -----------------------------------------------------------------------------
# 2. /metrics
# -----------------------------------------------------------------------------
section "2. /metrics counters"
metrics_body="$(curl -sS "${POLLER_BASE}/metrics")"
if echo "$metrics_body" | grep -q '^jamming_fetches_total '; then
  green "OK: jamming_fetches_total exposed"
else
  red "FAIL: /metrics missing jamming_fetches_total"
  exit 1
fi
if echo "$metrics_body" | grep -q '^jamming_cache_hits '; then
  green "OK: jamming_cache_hits exposed"
else
  red "FAIL: /metrics missing jamming_cache_hits"
  exit 1
fi

# -----------------------------------------------------------------------------
# 3. GeoJSON endpoint
# -----------------------------------------------------------------------------
section "3. /api/osint/jamming/current"
gj_status="$(curl -sS -o /tmp/_jam_gj.json -w '%{http_code}' "${POLLER_BASE}/api/osint/jamming/current" || echo 000)"
gj_type="$(python3 -c 'import json,sys; d=json.load(open("/tmp/_jam_gj.json")); print(d.get("type",""))' 2>/dev/null || echo '')"
gj_count="$(python3 -c 'import json,sys; d=json.load(open("/tmp/_jam_gj.json")); print(len(d.get("features",[])))' 2>/dev/null || echo 0)"
case "$gj_status" in
  200)
    if [[ "$gj_type" == "FeatureCollection" ]]; then
      green "OK: FeatureCollection with ${gj_count} features"
    else
      red "FAIL: 200 but body is not a FeatureCollection (got type='$gj_type')"
      exit 1
    fi
    ;;
  503)
    yellow "COLD-CACHE: 503 — first poller fetch hasn't completed yet. Body:"
    cat /tmp/_jam_gj.json
    ;;
  *)
    red "FAIL: /api/osint/jamming/current returned ${gj_status}"
    exit 1
    ;;
esac

# -----------------------------------------------------------------------------
# 4. audit_events row (optional)
# -----------------------------------------------------------------------------
section "4. audit_events row (optional)"
if [[ -n "${SQLCL:-}" && -n "${ATP_TNS:-}" && -n "${ATP_USER:-}" ]]; then
  q="SELECT COUNT(*) FROM audit_events WHERE actor_service='jamming-poller' AND event_time > SYSTIMESTAMP - INTERVAL '1' DAY;"
  echo "$q" | "$SQLCL" -L "${ATP_USER}@${ATP_TNS}" || yellow "WARN: SQLCL query failed"
else
  yellow "SKIP: set SQLCL, ATP_TNS, ATP_USER env vars to query audit_events live"
fi

# -----------------------------------------------------------------------------
# 5. Frontend serves /lagebild
# -----------------------------------------------------------------------------
section "5. Frontend /lagebild reachable"
fe_status="$(curl -sS -o /tmp/_jam_fe.html -w '%{http_code}' "${FRONTEND_BASE}/lagebild" || echo 000)"
if [[ "$fe_status" == "200" ]] && grep -q '<div id="root"' /tmp/_jam_fe.html; then
  green "OK: /lagebild served"
else
  yellow "WARN: /lagebild returned ${fe_status}"
fi

# Public LB probe (only if PUBLIC_LB env set).
if [[ -n "$PUBLIC_LB" ]]; then
  section "5b. Public LB ${PUBLIC_LB}/api/osint/jamming/current"
  lb_status="$(curl -sS -o /tmp/_jam_lb.json -w '%{http_code}' "${PUBLIC_LB}/api/osint/jamming/current" || echo 000)"
  echo "public LB jamming endpoint: ${lb_status}"
  if [[ "$lb_status" == "200" ]]; then
    green "OK: public LB serves jamming GeoJSON"
  else
    yellow "WARN: public LB returned ${lb_status} (frontend nginx proxy may not be reloaded yet)"
  fi
fi

# -----------------------------------------------------------------------------
# 6. Manual browser checklist
# -----------------------------------------------------------------------------
section "6. Manual browser checklist"
cat <<'CHECK'
Open ${FRONTEND_BASE}/lagebild in the browser and verify:

  [ ] Cesium globe renders, no console errors related to /api/osint/jamming.
  [ ] Sidebar lists "GPS Jamming" toggle in the "Elektromagnetik / EW" group.
  [ ] Activate the toggle.
      → Within seconds: hex-shaped polygons appear (mostly green / amber / red).
  [ ] Click any polygon → Intel panel (right) shows:
      • H3 index (15-char hex string)
      • Aircraft (total + low NACp)
      • Low-NACp ratio (percent)
      • Classification color
      • Source: "gpsjam.org via ADS-B Exchange"
      • Classification badge: OPEN
  [ ] Toggle off → all polygons disappear, count badge → 0.
  [ ] Repeat enable/disable 5× — no console errors, no network-tab leaks.

Pass criteria: every box checked. Any FAIL above means stop and inspect.
CHECK
green "Smoke test sequence complete."
