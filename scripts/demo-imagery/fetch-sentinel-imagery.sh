#!/usr/bin/env bash
# fetch-sentinel-imagery.sh
#
# Lädt 5 Sentinel-2 L2A True-Color-Aufnahmen für die GEOINT-Demo
# via Sentinel Hub Process API. Nutzt die OAuth2-Credentials und
# Instance-ID aus OCI Vault (gleiche OCIDs wie sentinel-proxy
# Service in services/sentinel-proxy).
#
# Voraussetzungen:
#   - OCI CLI Profil DEFENCE_DEMO funktional
#   - .env mit VAULT_SENTINEL_CLIENT_ID_OCID,
#     VAULT_SENTINEL_CLIENT_SECRET_OCID, VAULT_SENTINEL_INSTANCE_ID_OCID
#   - jq, curl, python3 installiert
#   - Sentinel-Hub Configuration hat TRUE-COLOR-HIGHLIGHT-OPTIMIZED Layer
#
# Output: ./demo-images/sentinel-*.png (5 Bilder, 1024x1024)
#
# Verwendung:
#   bash fetch-sentinel-imagery.sh
#
# Falls die zeitliche Wolkenfilterung zu wenig liefert: Process API hat
# automatisches Mosaicking mit "leastCC" (least cloud cover).

set -euo pipefail

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

OUT_DIR="${OUT_DIR:-./demo-images}"
WIDTH="${WIDTH:-1024}"
HEIGHT="${HEIGHT:-1024}"
TIME_FROM="${TIME_FROM:-2026-03-01T00:00:00Z}"
TIME_TO="${TIME_TO:-2026-04-29T23:59:59Z}"
MAX_CLOUD="${MAX_CLOUD:-30}"

OCI_PROFILE="${OCI_PROFILE:-DEFENCE_DEMO}"
ENV_FILE="${ENV_FILE:-../../.env}"

# Demo-Locations: name|west,south,east,north|description
LOCATIONS=(
  "bornholm|14.7,55.0,15.2,55.3|Bornholm: Konsistenz mit Maritime-Layer-Bbox"
  "eckernfoerde|9.82,54.45,9.92,54.50|Bundeswehr-Marinebasis aus ports_curated"
  "wilhelmshaven|8.05,53.50,8.20,53.58|Groesster deutscher Marinehafen"
  "suwalki-gap|22.85,54.05,23.20,54.30|Geopolitisch hochrelevant (PL/LT-Korridor)"
  "kaliningrad-approach|20.30,54.65,20.65,54.85|NATO-Kontext, Seehafen Pillau"
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

echo "[1/4] Loading .env from $ENV_FILE"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE — adjust ENV_FILE env var" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for var in VAULT_SENTINEL_CLIENT_ID_OCID VAULT_SENTINEL_CLIENT_SECRET_OCID VAULT_SENTINEL_INSTANCE_ID_OCID; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: $var not set in .env" >&2
    exit 1
  fi
done

mkdir -p "$OUT_DIR"

# ---------------------------------------------------------------------------
# Vault-Secrets ziehen
# ---------------------------------------------------------------------------

echo "[2/4] Pulling Sentinel credentials from OCI Vault"

CLIENT_ID=$(oci secrets secret-bundle get \
  --secret-id "$VAULT_SENTINEL_CLIENT_ID_OCID" \
  --profile "$OCI_PROFILE" \
  --query 'data."secret-bundle-content".content' \
  --raw-output | base64 -d)

CLIENT_SECRET=$(oci secrets secret-bundle get \
  --secret-id "$VAULT_SENTINEL_CLIENT_SECRET_OCID" \
  --profile "$OCI_PROFILE" \
  --query 'data."secret-bundle-content".content' \
  --raw-output | base64 -d)

INSTANCE_ID=$(oci secrets secret-bundle get \
  --secret-id "$VAULT_SENTINEL_INSTANCE_ID_OCID" \
  --profile "$OCI_PROFILE" \
  --query 'data."secret-bundle-content".content' \
  --raw-output | base64 -d)

echo "       client_id length:     ${#CLIENT_ID}"
echo "       client_secret length: ${#CLIENT_SECRET}"
echo "       instance_id:          $INSTANCE_ID"

# ---------------------------------------------------------------------------
# OAuth Token holen
# ---------------------------------------------------------------------------

echo "[3/4] Fetching OAuth access token"

TOKEN_RESPONSE=$(curl -sf -X POST \
  https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  --data-urlencode "client_secret=$CLIENT_SECRET")

TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

if [[ -z "$TOKEN" || "$TOKEN" == "None" ]]; then
  echo "ERROR: failed to obtain OAuth token" >&2
  echo "Response: $TOKEN_RESPONSE" >&2
  exit 1
fi

echo "       Token length: ${#TOKEN} (expected ~1500-1600 for valid JWT)"

# ---------------------------------------------------------------------------
# Process-API GetMap-Request pro Location
# ---------------------------------------------------------------------------

EVALSCRIPT='//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02","B03","B04"], units: "REFLECTANCE" }],
    output: { bands: 3, sampleType: "AUTO" }
  };
}
function evaluatePixel(s) {
  // True-Color-Highlight-Optimized: Gain 2.5 für gut sichtbare Strukturen
  return [2.5*s.B04, 2.5*s.B03, 2.5*s.B02];
}'

echo "[4/4] Fetching ${#LOCATIONS[@]} Sentinel-2 scenes"

for entry in "${LOCATIONS[@]}"; do
  IFS='|' read -r name bbox description <<< "$entry"

  out_file="$OUT_DIR/sentinel-${name}.png"
  echo ""
  echo "    -> $name"
  echo "       bbox: $bbox"
  echo "       desc: $description"

  # bbox als JSON-Array
  bbox_json=$(echo "$bbox" | python3 -c "
import sys
b = [float(x) for x in sys.stdin.read().strip().split(',')]
import json
print(json.dumps(b))
")

  request_body=$(python3 <<PYEOF
import json
print(json.dumps({
  "input": {
    "bounds": {
      "bbox": $bbox_json,
      "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
    },
    "data": [{
      "type": "sentinel-2-l2a",
      "dataFilter": {
        "timeRange": {"from": "$TIME_FROM", "to": "$TIME_TO"},
        "maxCloudCoverage": $MAX_CLOUD,
        "mosaickingOrder": "leastCC"
      }
    }]
  },
  "output": {
    "width": $WIDTH,
    "height": $HEIGHT,
    "responses": [{"identifier": "default", "format": {"type": "image/png"}}]
  },
  "evalscript": $(python3 -c "import json,sys; print(json.dumps(open('/dev/stdin').read()))" <<< "$EVALSCRIPT")
}))
PYEOF
)

  http_status=$(curl -s -w "%{http_code}" -o "$out_file" \
    -X POST "https://sh.dataspace.copernicus.eu/api/v1/process" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: image/png" \
    -d "$request_body")

  if [[ "$http_status" != "200" ]]; then
    echo "       FAILED (HTTP $http_status)"
    echo "       Response body:"
    cat "$out_file" | head -c 500
    echo ""
    rm -f "$out_file"
    continue
  fi

  size=$(stat -c%s "$out_file" 2>/dev/null || stat -f%z "$out_file")
  echo "       OK ($size bytes saved to $out_file)"
done

echo ""
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"/sentinel-*.png 2>/dev/null || echo "  (no files — check error messages above)"
