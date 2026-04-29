#!/usr/bin/env bash
# =============================================================================
# Recipe L Layer #4 — End-to-End Smoke Test for the UC4 Flights proxy
# (Pattern A REST-poll, hybrid classifier curated → Mictronics → civil).
#
# Verifies in order:
#   0. Pre-flight: required binaries.
#   1. /healthz returns a JSON status (200 or 503).
#   2. /metrics exposes flights_fetches_total + flights_classifier_lookups
#      + flights_last_civil_count + flights_last_mil_count.
#   3. /api/osint/flights/civil/current returns a GeoJSON FeatureCollection
#      (200 with features, or 503 cold-cache shape — both acceptable).
#   4. /api/osint/flights/mil/current returns a GeoJSON FeatureCollection
#      (200 — possibly empty features list, since the demo curated rows may
#      not match anything live in the Baltic radius).
#   5. partial-bbox 400 contract: civil endpoint with only some bbox params
#      returns HTTP 400 (the canonical input-validation case).
#   6. audit_events row written by flights-proxy in the last day
#      (only if SQLCL + ATP_TNS + ATP_USER are configured).
#   7. Frontend serves /lagebild.
#   8. Manual checklist printed at the end.
#
# Usage:
#   bash scripts/smoke-test-flights.sh
#
# Required env (overrideable):
#   PROXY_BASE        (default http://localhost:8009)
#   FRONTEND_BASE     (default http://localhost:5173)
#   PUBLIC_LB         (e.g. http://152.70.18.236) — if set, also probes
#                      the public ingress path.
# Optional:
#   SQLCL, ATP_TNS, ATP_USER  — for step 6.
# =============================================================================
set -euo pipefail

PROXY_BASE="${PROXY_BASE:-http://localhost:8009}"
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
section "1. flights-proxy /healthz"
hz_status="$(curl -sS -o /tmp/_fl_hz.json -w '%{http_code}' "${PROXY_BASE}/healthz" || echo 000)"
case "$hz_status" in
  200) green "OK: /healthz 200"; cat /tmp/_fl_hz.json; echo ;;
  503) yellow "DEGRADED: /healthz 503 (DB unreachable). Body:"; cat /tmp/_fl_hz.json; echo ;;
  000) red "FAIL: proxy unreachable at ${PROXY_BASE}"; exit 1 ;;
  *)   red "FAIL: /healthz returned ${hz_status}"; cat /tmp/_fl_hz.json; exit 1 ;;
esac

# -----------------------------------------------------------------------------
# 2. /metrics
# -----------------------------------------------------------------------------
section "2. /metrics counters"
metrics_body="$(curl -sS "${PROXY_BASE}/metrics")"
for m in flights_fetches_total flights_classifier_lookups flights_last_civil_count flights_last_mil_count; do
  if echo "$metrics_body" | grep -q "^${m} "; then
    green "OK: ${m} exposed"
  else
    red "FAIL: /metrics missing ${m}"
    exit 1
  fi
done

# -----------------------------------------------------------------------------
# 3. Civil endpoint
# -----------------------------------------------------------------------------
section "3. /api/osint/flights/civil/current"
civil_status="$(curl -sS -o /tmp/_fl_civ.json -w '%{http_code}' "${PROXY_BASE}/api/osint/flights/civil/current" || echo 000)"
civil_type="$(python3 -c 'import json; d=json.load(open("/tmp/_fl_civ.json")); print(d.get("type",""))' 2>/dev/null || echo '')"
civil_count="$(python3 -c 'import json; d=json.load(open("/tmp/_fl_civ.json")); print(len(d.get("features",[])))' 2>/dev/null || echo 0)"
case "$civil_status" in
  200)
    if [[ "$civil_type" == "FeatureCollection" ]]; then
      green "OK: civil FeatureCollection with ${civil_count} features"
    else
      red "FAIL: 200 but body is not a FeatureCollection (got type='$civil_type')"
      exit 1
    fi
    ;;
  503)
    yellow "COLD-CACHE: 503 — first poller fetch hasn't completed yet. Body:"
    cat /tmp/_fl_civ.json
    ;;
  *)
    red "FAIL: civil endpoint returned ${civil_status}"
    exit 1
    ;;
esac

# -----------------------------------------------------------------------------
# 4. Mil endpoint
# -----------------------------------------------------------------------------
section "4. /api/osint/flights/mil/current"
mil_status="$(curl -sS -o /tmp/_fl_mil.json -w '%{http_code}' "${PROXY_BASE}/api/osint/flights/mil/current" || echo 000)"
mil_type="$(python3 -c 'import json; d=json.load(open("/tmp/_fl_mil.json")); print(d.get("type",""))' 2>/dev/null || echo '')"
mil_count="$(python3 -c 'import json; d=json.load(open("/tmp/_fl_mil.json")); print(len(d.get("features",[])))' 2>/dev/null || echo 0)"
case "$mil_status" in
  200)
    if [[ "$mil_type" == "FeatureCollection" ]]; then
      green "OK: mil FeatureCollection with ${mil_count} features"
      if [[ "$mil_count" == "0" ]]; then
        yellow "  Note: empty mil list is normal if no curated/Mictronics aircraft are airborne in radius right now."
      fi
    else
      red "FAIL: 200 but body is not a FeatureCollection (got type='$mil_type')"
      exit 1
    fi
    ;;
  503)
    yellow "COLD-CACHE: 503 — first poller fetch hasn't completed yet. Body:"
    cat /tmp/_fl_mil.json
    ;;
  *)
    red "FAIL: mil endpoint returned ${mil_status}"
    exit 1
    ;;
esac

# -----------------------------------------------------------------------------
# 5. partial-bbox 400
# -----------------------------------------------------------------------------
section "5. /api/osint/flights/mil/current?bbox_s=53&bbox_n=56 → 400"
pb_status="$(curl -sS -o /tmp/_fl_pb.json -w '%{http_code}' "${PROXY_BASE}/api/osint/flights/mil/current?bbox_s=53&bbox_n=56" || echo 000)"
if [[ "$pb_status" == "400" ]]; then
  green "OK: partial bbox rejected with 400"
  cat /tmp/_fl_pb.json
  echo
else
  red "FAIL: partial-bbox returned ${pb_status} (expected 400)"
  cat /tmp/_fl_pb.json
  exit 1
fi

# -----------------------------------------------------------------------------
# 6. audit_events row (optional)
# -----------------------------------------------------------------------------
section "6. audit_events row (optional)"
if [[ -n "${SQLCL:-}" && -n "${ATP_TNS:-}" && -n "${ATP_USER:-}" ]]; then
  q="SELECT COUNT(*) FROM audit_events WHERE actor_service='flights-proxy' AND event_time > SYSTIMESTAMP - INTERVAL '1' DAY;"
  echo "$q" | "$SQLCL" -L "${ATP_USER}@${ATP_TNS}" || yellow "WARN: SQLCL query failed"
else
  yellow "SKIP: set SQLCL, ATP_TNS, ATP_USER env vars to query audit_events live"
fi

# -----------------------------------------------------------------------------
# 7. Frontend serves /lagebild
# -----------------------------------------------------------------------------
section "7. Frontend /lagebild reachable"
fe_status="$(curl -sS -o /tmp/_fl_fe.html -w '%{http_code}' "${FRONTEND_BASE}/lagebild" || echo 000)"
if [[ "$fe_status" == "200" ]] && grep -q '<div id="root"' /tmp/_fl_fe.html; then
  green "OK: /lagebild served"
else
  yellow "WARN: /lagebild returned ${fe_status}"
fi

# Public LB probe (only if PUBLIC_LB env set).
if [[ -n "$PUBLIC_LB" ]]; then
  section "7b. Public LB ${PUBLIC_LB}/api/osint/flights/civil/current"
  lb_status="$(curl -sS -o /tmp/_fl_lb.json -w '%{http_code}' "${PUBLIC_LB}/api/osint/flights/civil/current" || echo 000)"
  echo "public LB civil endpoint: ${lb_status}"
  if [[ "$lb_status" == "200" ]]; then
    green "OK: public LB serves civil GeoJSON"
  else
    yellow "WARN: public LB returned ${lb_status} (frontend nginx proxy may not be reloaded yet)"
  fi
fi

# -----------------------------------------------------------------------------
# 8. Manual browser checklist
# -----------------------------------------------------------------------------
section "8. Manual browser checklist"
cat <<'CHECK'
Open ${FRONTEND_BASE}/lagebild in the browser and verify:

  [ ] Cesium globe renders, no console errors related to /api/osint/flights.
  [ ] Sidebar lists "Flüge: Civil" and "Flüge: Mil" toggles in the "Air" group.
  [ ] Activate "Flüge: Civil".
      → Within ~30 s: blue plane billboards appear, oriented along the track.
  [ ] Click any blue plane → Intel panel shows:
      • Hex (ICAO24)
      • Callsign + Registration + Type
      • Altitude / Speed / Track / Squawk / NACp
      • Sources: "adsb.lol via ADS-B Exchange community feeders"
      • Classification badge: OPEN
  [ ] Activate "Flüge: Mil" alongside.
      → Red plane billboards appear (typically far fewer, sometimes zero).
  [ ] Click any red plane → Intel panel ALSO shows:
      • Operator (e.g. "Bundeswehr (German Army)")
      • Mil Source ("curated" or "mictronics")
      • Sources include the matching DB row provenance.
  [ ] Toggle either layer off → its billboards disappear; count badge → 0.
  [ ] Repeat civil enable/disable 5× — no console errors, no network-tab leaks.

Pass criteria: every box checked. Any FAIL above means stop and inspect.
CHECK
green "Smoke test sequence complete."
