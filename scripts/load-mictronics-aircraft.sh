#!/usr/bin/env bash
# =============================================================================
# Load mil-flagged entries from the Mictronics readsb aircraft database into
# the 26ai mil_aircraft_mictronics table. This is the bulk seed of the hybrid
# flights classifier — see services/flights-proxy/app/classifier.py.
#
# Source: https://github.com/Mictronics/readsb/blob/dev/webapp/src/db/aircrafts.json
#         (~28 MB JSON, ~445k entries; we filter to mil-flag-bit=1 only,
#          typically 4k-8k surviving rows)
#
# Per-entry shape:
#   "<HEX24>": {"r": "<reg>", "t": "<icao_type>", "f": "<flags_hex>", "d": "<desc>"}
#   `f` is a hex string. Bit 0 = military flag (matches adsb.lol dbFlags
#   semantics). We keep entries where (int(f, 16) & 0x01) != 0.
#
# Usage:
#   ADB_ADMIN_PASSWORD='<pwd>' bash scripts/load-mictronics-aircraft.sh
#
# Env (overrideable):
#   MICTRONICS_JSON_URL   default https://raw.githubusercontent.com/Mictronics/readsb/dev/webapp/src/db/aircrafts.json
#   ADB_USER              default ADMIN
#   ADB_TNS_ALIAS         default sovdef26_tp
#   TNS_ADMIN             default ~/wallet
#   BATCH_SIZE            default 500   inserts per executemany batch
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

MICTRONICS_JSON_URL="${MICTRONICS_JSON_URL:-https://raw.githubusercontent.com/Mictronics/readsb/dev/webapp/src/db/aircrafts.json}"
ADB_USER="${ADB_USER:-ADMIN}"
ADB_TNS_ALIAS="${ADB_TNS_ALIAS:-sovdef26_tp}"
TNS_ADMIN="${TNS_ADMIN:-$HOME/wallet}"
BATCH_SIZE="${BATCH_SIZE:-500}"

: "${ADB_ADMIN_PASSWORD:?ADB_ADMIN_PASSWORD must be set}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found in PATH" >&2
  exit 1
fi

if [[ ! -d "$TNS_ADMIN" ]]; then
  echo "TNS_ADMIN directory not found: $TNS_ADMIN" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
JSON_FILE="$WORKDIR/aircrafts.json"

echo "[load-mictronics] downloading $MICTRONICS_JSON_URL"
curl -sSL --max-time 120 "$MICTRONICS_JSON_URL" -o "$JSON_FILE"
size=$(wc -c <"$JSON_FILE")
echo "[load-mictronics] downloaded $size bytes"
[[ "$size" -gt 1000000 ]] || { echo "JSON too small — bad URL?"; exit 1; }

# Load via oracledb thin mode (no native client).
TNS_ADMIN="$TNS_ADMIN" \
ORACLE_PASSWORD="$ADB_ADMIN_PASSWORD" \
ORACLE_USER="$ADB_USER" \
ORACLE_DSN="$ADB_TNS_ALIAS" \
JSON_PATH="$JSON_FILE" \
BATCH="$BATCH_SIZE" \
python3 - <<'PY'
import json, os, sys, time
import oracledb

USER = os.environ['ORACLE_USER']
PWD  = os.environ['ORACLE_PASSWORD']
DSN  = os.environ['ORACLE_DSN']
TNS  = os.environ['TNS_ADMIN']
PATH = os.environ['JSON_PATH']
BATCH = int(os.environ['BATCH'])

print(f'[load-mictronics] connecting to {DSN} as {USER}', flush=True)
conn = oracledb.connect(
    user=USER, password=PWD, dsn=DSN,
    config_dir=TNS, wallet_location=TNS,
    wallet_password=PWD,
)

# Idempotent: truncate before reload (full refresh weekly).
with conn.cursor() as cur:
    cur.execute('TRUNCATE TABLE mil_aircraft_mictronics')
print('[load-mictronics] truncated mil_aircraft_mictronics', flush=True)

with open(PATH, 'r', encoding='utf-8') as f:
    db = json.load(f)
print(f'[load-mictronics] loaded JSON: {len(db)} aircraft entries', flush=True)

mil_rows = []
for hex24, attrs in db.items():
    if not isinstance(attrs, dict):
        continue
    flags = attrs.get('f') or '00'
    try:
        if not (int(flags, 16) & 0x01):
            continue
    except ValueError:
        continue
    mil_rows.append({
        'hex24': hex24.upper()[:6],
        'reg':   (attrs.get('r') or '')[:20] or None,
        'typ':   (attrs.get('t') or '')[:8] or None,
        'desc':  (attrs.get('d') or '')[:200] or None,
        'flags': flags[:8],
    })

print(f'[load-mictronics] mil-flagged entries: {len(mil_rows)}', flush=True)

INSERT_SQL = """
INSERT INTO mil_aircraft_mictronics
  (hex24, registration, icao_type, description, flag_bits_hex)
VALUES (:hex24, :reg, :typ, :desc, :flags)
"""

t0 = time.time()
with conn.cursor() as cur:
    for i in range(0, len(mil_rows), BATCH):
        chunk = mil_rows[i:i+BATCH]
        cur.executemany(INSERT_SQL, chunk, batcherrors=True)
        for err in cur.getbatcherrors():
            print(f'  row error: {err.message}', flush=True)
conn.commit()
print(f'[load-mictronics] inserted {len(mil_rows)} rows in {time.time()-t0:.1f}s', flush=True)
PY

echo "[load-mictronics] done"
