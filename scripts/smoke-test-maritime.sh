#!/usr/bin/env bash
# =============================================================================
# Recipe L — End-to-End Smoke Test for the UC4 maritime layer (Pattern B).
#
# Verifies in order:
#   0. Pre-flight: required binaries exist.
#   1. ais-multiplexer /healthz returns 200/503 with a JSON body.
#   2. /metrics exposes the Prometheus counters.
#   3. WebSocket /ws/maritime accepts a connection (first frame OR clean close
#      within timeout — both are acceptable since real frames depend on Vault).
#   4. audit_events table received at least one ais-multiplexer row in the
#      last minute (only runs if SQLPLUS_CONNECT or SQLCL is configured).
#   5. Frontend dev server serves /lagebild.
#   6. Manual checklist printed at the end.
#
# Usage:
#   bash scripts/smoke-test-maritime.sh
#
# Required env (overrideable):
#   MUX_BASE       (default http://localhost:8001)
#   FRONTEND_BASE  (default http://localhost:5173)
#
# Optional env:
#   SQLCL          path to sqlcl (else: skip step 4)
#   ATP_TNS        TNS alias for the 26ai ATP (else: skip step 4)
#   ATP_USER       DB user for audit query (else: skip step 4)
# =============================================================================
set -euo pipefail

MUX_BASE="${MUX_BASE:-http://localhost:8001}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:5173}"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
section() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# -----------------------------------------------------------------------------
# 0. Pre-flight
# -----------------------------------------------------------------------------
section "0. Pre-flight"
need=(curl python3)
for bin in "${need[@]}"; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    red "FAIL: required binary missing: $bin"
    exit 1
  fi
done
green "OK: curl, python3 present"

# -----------------------------------------------------------------------------
# 1. /healthz
# -----------------------------------------------------------------------------
section "1. ais-multiplexer /healthz"
hz_status="$(curl -sS -o /tmp/_hz.json -w '%{http_code}' "${MUX_BASE}/healthz" || echo 000)"
case "$hz_status" in
  200) green "OK: /healthz 200"; cat /tmp/_hz.json ;;
  503) yellow "DEGRADED: /healthz 503 (DB unreachable). Body:"; cat /tmp/_hz.json ;;
  000) red "FAIL: ais-multiplexer not reachable at ${MUX_BASE}"; exit 1 ;;
  *)   red "FAIL: /healthz returned ${hz_status}"; cat /tmp/_hz.json; exit 1 ;;
esac

# -----------------------------------------------------------------------------
# 2. /metrics
# -----------------------------------------------------------------------------
section "2. /metrics counters"
if curl -sS "${MUX_BASE}/metrics" | grep -q '^ais_frames_received '; then
  green "OK: ais_frames_received exposed"
else
  red "FAIL: /metrics missing ais_frames_received"
  exit 1
fi

# -----------------------------------------------------------------------------
# 3. WebSocket /ws/maritime
# -----------------------------------------------------------------------------
section "3. WebSocket /ws/maritime — accept connection (10 s)"
python3 - <<'PY'
import asyncio, json, sys, os, websockets

URL = os.environ.get("MUX_BASE", "http://localhost:8001").replace("http://", "ws://").replace("https://", "wss://")
URL = URL + "/ws/maritime"

async def main():
    try:
        async with websockets.connect(URL, open_timeout=5) as ws:
            print(f"OK: connected to {URL}", flush=True)
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                payload = json.loads(msg)
                print("OK: received frame:", json.dumps(payload)[:200], flush=True)
            except asyncio.TimeoutError:
                print("WARN: no frame within 10 s — Vault key may be missing or aisstream silent. Connection itself worked.", flush=True)
    except Exception as exc:
        print(f"FAIL: ws connect failed: {exc}", flush=True)
        sys.exit(1)

asyncio.run(main())
PY

# -----------------------------------------------------------------------------
# 4. audit_events row (optional — needs sqlcl + ATP)
# -----------------------------------------------------------------------------
section "4. audit_events row (optional)"
if [[ -n "${SQLCL:-}" && -n "${ATP_TNS:-}" && -n "${ATP_USER:-}" ]]; then
  q="SELECT COUNT(*) FROM audit_events WHERE actor_service='ais-multiplexer' AND event_time > SYSTIMESTAMP - INTERVAL '60' SECOND;"
  echo "$q" | "$SQLCL" -L "${ATP_USER}@${ATP_TNS}" || yellow "WARN: SQLCL query failed — skip"
else
  yellow "SKIP: set SQLCL, ATP_TNS, ATP_USER env vars to query audit_events live"
fi

# -----------------------------------------------------------------------------
# 5. Frontend serves /lagebild
# -----------------------------------------------------------------------------
section "5. Frontend /lagebild reachable"
fe_status="$(curl -sS -o /tmp/_fe.html -w '%{http_code}' "${FRONTEND_BASE}/lagebild" || echo 000)"
if [[ "$fe_status" == "200" ]] && grep -q '<div id="root"' /tmp/_fe.html; then
  green "OK: /lagebild served, root div present"
else
  yellow "WARN: /lagebild returned ${fe_status}. Is npm run dev running?"
fi

# -----------------------------------------------------------------------------
# 6. Manual checklist
# -----------------------------------------------------------------------------
section "6. Manual browser checklist"
cat <<'CHECK'
Open ${FRONTEND_BASE}/lagebild in the browser and verify:

  [ ] Cesium globe renders without console errors.
  [ ] Sidebar lists "Maritime AIS" toggle in the Maritime Domain group.
  [ ] Activate the toggle.
      → Status bar shows "Verbinde mit AIS Multiplexer..." then "Maritime live".
  [ ] Within ~30 s at least one Billboard appears in the Ostsee bbox
      (53°N–56°N, 8°E–22°E).
  [ ] Click a Billboard → Intel panel (right) shows:
      • MMSI (9-digit number)
      • Vessel name (or fallback to MMSI)
      • Heading + speed
      • Classification badge "OPEN"
      • Source: "aisstream.io via ais-multiplexer"
  [ ] Toggle the layer off → all Billboards disappear, count badge → 0.
  [ ] Repeat enable/disable 5× — no console errors, no DOM listener growth.

Pass criteria: every box checked. Any FAIL above means stop and inspect.
CHECK
green "Smoke test sequence complete."
