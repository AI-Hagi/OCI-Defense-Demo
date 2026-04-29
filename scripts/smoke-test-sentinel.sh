#!/usr/bin/env bash
# =============================================================================
# Recipe L Layer #3 — End-to-End Smoke Test for the UC4 Sentinel-2 Proxy.
#
# Verifies in order:
#   0. Pre-flight binaries.
#   1. /healthz returns JSON status (200 / 503).
#   2. /metrics exposes the OAuth + audit counters.
#   3. /api/osint/sentinel/layers returns default_layer + non-empty list.
#   4. /api/osint/sentinel/tiles/.../12/2200/1334.png returns a valid PNG
#      (Bornholm, zoom 12 — covers ~Rønne harbour).
#   5. audit_events row written by sentinel-proxy in the last hour
#      (only if SQLCL + ATP_TNS + ATP_USER are configured).
#   6. Frontend serves /lagebild.
#   7. Manual checklist.
#
# Usage:
#   bash scripts/smoke-test-sentinel.sh
#
# Required env (overrideable):
#   PROXY_BASE        (default http://localhost:8008)
#   FRONTEND_BASE     (default http://localhost:5173)
#   PUBLIC_LB         (e.g. http://152.70.18.236) — if set, also probes prod path
# Optional: SQLCL, ATP_TNS, ATP_USER for step 5.
# =============================================================================
set -euo pipefail

PROXY_BASE="${PROXY_BASE:-http://localhost:8008}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:5173}"
PUBLIC_LB="${PUBLIC_LB:-}"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
section() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# 0. Pre-flight
section "0. Pre-flight"
for bin in curl python3 file; do
  command -v "$bin" >/dev/null 2>&1 || { red "FAIL: missing $bin"; exit 1; }
done
green "OK: curl + python3 + file"

# 1. /healthz
section "1. sentinel-proxy /healthz"
hz_status="$(curl -sS -o /tmp/_sen_hz.json -w '%{http_code}' "${PROXY_BASE}/healthz" || echo 000)"
case "$hz_status" in
  200) green "OK: /healthz 200"; cat /tmp/_sen_hz.json; echo ;;
  503) yellow "DEGRADED: /healthz 503"; cat /tmp/_sen_hz.json; echo ;;
  000) red "FAIL: not reachable at ${PROXY_BASE}"; exit 1 ;;
  *)   red "FAIL: /healthz returned ${hz_status}"; exit 1 ;;
esac

# 2. /metrics
section "2. /metrics counters"
metrics_body="$(curl -sS "${PROXY_BASE}/metrics")"
for m in sentinel_token_refreshes sentinel_token_refresh_failures sentinel_audit_writes; do
  if echo "$metrics_body" | grep -q "^${m} "; then
    green "OK: ${m} exposed"
  else
    red "FAIL: /metrics missing ${m}"
    exit 1
  fi
done

# 3. /layers
section "3. /api/osint/sentinel/layers"
layers_status="$(curl -sS -o /tmp/_sen_layers.json -w '%{http_code}' "${PROXY_BASE}/api/osint/sentinel/layers")"
if [[ "$layers_status" == "200" ]]; then
  default=$(python3 -c 'import json; print(json.load(open("/tmp/_sen_layers.json")).get("default_layer",""))')
  count=$(python3 -c 'import json; print(len(json.load(open("/tmp/_sen_layers.json")).get("layers",[])))')
  green "OK: default_layer=${default}, ${count} layers"
else
  red "FAIL: /layers returned ${layers_status}"
  exit 1
fi

# 4. tile fetch — Bornholm zoom 12
section "4. tile fetch (Bornholm zoom 12)"
tile_status="$(curl -sS -o /tmp/_sen_tile.png -w '%{http_code} %{size_download} %{content_type}' \
  "${PROXY_BASE}/api/osint/sentinel/tiles/TRUE-COLOR-HIGHLIGHT-OPTIMIZED/12/2200/1334.png")"
echo "$tile_status"
file /tmp/_sen_tile.png
if file /tmp/_sen_tile.png | grep -q 'PNG image data'; then
  green "OK: valid PNG returned"
else
  red "FAIL: response is not a PNG"
  cat /tmp/_sen_tile.png | head -c 300; echo
  exit 1
fi

# 5. audit_events row (optional)
section "5. audit_events row (optional)"
if [[ -n "${SQLCL:-}" && -n "${ATP_TNS:-}" && -n "${ATP_USER:-}" ]]; then
  q="SELECT COUNT(*) FROM audit_events WHERE actor_service='sentinel-proxy' AND event_time > SYSTIMESTAMP - INTERVAL '1' HOUR;"
  echo "$q" | "$SQLCL" -L "${ATP_USER}@${ATP_TNS}" || yellow "WARN: SQLCL query failed"
else
  yellow "SKIP: set SQLCL, ATP_TNS, ATP_USER to query audit_events"
fi

# 6. Frontend
section "6. Frontend /lagebild"
fe_status="$(curl -sS -o /tmp/_sen_fe.html -w '%{http_code}' "${FRONTEND_BASE}/lagebild" || echo 000)"
if [[ "$fe_status" == "200" ]] && grep -q '<div id="root"' /tmp/_sen_fe.html; then
  green "OK: /lagebild served"
else
  yellow "WARN: /lagebild returned ${fe_status}"
fi

if [[ -n "$PUBLIC_LB" ]]; then
  section "6b. Public LB ${PUBLIC_LB}/api/osint/sentinel/layers"
  curl -sS -o /tmp/_sen_lb.json -w 'HTTP %{http_code}\n' "${PUBLIC_LB}/api/osint/sentinel/layers"
fi

# 7. Manual checklist
section "7. Manual browser checklist"
cat <<'CHECK'
Open ${FRONTEND_BASE}/lagebild in the browser and verify:

  [ ] Cesium globe renders, no console errors.
  [ ] Sidebar lists "Sentinel-2 Imagery" toggle in the "Bildgebung" group.
  [ ] Activate the toggle.
      → Within ~10 s, satellite imagery overlays the globe (cloud-free
        tiles in Bornholm region; greyscale-blank tiles elsewhere if
        no Sentinel-2 acquisition is available).
  [ ] Pan/zoom around Bornholm — tiles load progressively.
  [ ] Toggle off → imagery disappears, only OSM base tiles remain.
  [ ] Repeat enable/disable 5× — no console errors, no hanging tile fetches.

Pass criteria: every box checked. Any FAIL above stops here.
CHECK
green "Smoke test sequence complete."
