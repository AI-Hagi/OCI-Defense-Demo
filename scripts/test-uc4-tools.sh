#!/usr/bin/env bash
# =============================================================================
#  Smoke tests for the four UC4_OSINT ORDS tools.
# -----------------------------------------------------------------------------
#  Tests each of:
#      POST /api/v1/tools/graph_query
#      POST /api/v1/tools/spatial_aggregate
#      POST /api/v1/tools/persist_briefing
#      POST /api/v1/tools/vector_hybrid_search
#
#  Three OLS personas: cap=10/30/50. The graph + spatial calls must return
#  monotonically more rows as cap rises. persist_briefing at cap=10 is
#  expected to be REJECTED with 403 when the briefing classification is
#  INTERN/NFD (privilege-escalation guard). vector_hybrid_search returns
#  503 today (embeddings still NULL).
#
#  Required env:
#      ORDS_BASE_URL   ORDS root, e.g. https://ords.sovdef26.example
#                      Default: https://${ATP_HOST}:8443/ords
#      ATP_HOST        ATP-Shared host (default: localhost — only useful
#                      if you've port-forwarded; ATP usually exposes via
#                      its public ORDS endpoint)
#
#  OAuth2 (Tag 6b — required when calling the live ORDS endpoint):
#      ORDS_OAUTH_TOKEN_URL                Default: ${ORDS_BASE_URL}/uc4_osint/oauth/token
#      OAUTH_CLIENT_ID_VAULT_OCID          OCI Vault secret OCID for client_id
#      OAUTH_CLIENT_SECRET_VAULT_OCID      OCI Vault secret OCID for client_secret
#                                          (resolves via instance principal —
#                                           run from a host with the right policy)
#  Override path (skip Vault):
#      OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET (plain values)
#
#  Optional:
#      JQ_FILTER       jq filter applied to each response (default: '.')
#                      e.g. JQ_FILTER='.duration_ms,.ols_cap_label' for tighter output
#      SKIP_AUTH=1     Don't fetch a bearer (only useful pre-Tag-6b)
# =============================================================================
set -u
IFS=$'\n\t'

BASE="${ORDS_BASE_URL:-https://${ATP_HOST:-localhost}:8443/ords}"
TOOLS="${BASE}/uc4_osint/api/v1/tools"
TOKEN_URL="${ORDS_OAUTH_TOKEN_URL:-${BASE}/uc4_osint/oauth/token}"
JQ_FILTER="${JQ_FILTER:-.}"

# -----------------------------------------------------------------------------
# Bearer token fetch — pulls client_id/client_secret from OCI Vault by OCID,
# unless overridden by OAUTH_CLIENT_ID + OAUTH_CLIENT_SECRET env vars.
# -----------------------------------------------------------------------------
ACCESS_TOKEN=""
if [[ "${SKIP_AUTH:-0}" != "1" ]]; then
  if [[ -z "${OAUTH_CLIENT_ID:-}" || -z "${OAUTH_CLIENT_SECRET:-}" ]]; then
    : "${OAUTH_CLIENT_ID_VAULT_OCID:?ERROR: set OAUTH_CLIENT_ID_VAULT_OCID or OAUTH_CLIENT_ID}"
    : "${OAUTH_CLIENT_SECRET_VAULT_OCID:?ERROR: set OAUTH_CLIENT_SECRET_VAULT_OCID or OAUTH_CLIENT_SECRET}"
    command -v oci >/dev/null || { echo "ERROR: 'oci' CLI not on PATH"; exit 1; }
    OAUTH_CLIENT_ID=$(oci secrets secret-bundle get \
        --auth instance_principal \
        --secret-id "$OAUTH_CLIENT_ID_VAULT_OCID" \
        --query 'data."secret-bundle-content".content' --raw-output | base64 -d)
    OAUTH_CLIENT_SECRET=$(oci secrets secret-bundle get \
        --auth instance_principal \
        --secret-id "$OAUTH_CLIENT_SECRET_VAULT_OCID" \
        --query 'data."secret-bundle-content".content' --raw-output | base64 -d)
  fi
  echo "[auth] fetching bearer from ${TOKEN_URL}"
  ACCESS_TOKEN=$(curl -sk -X POST "$TOKEN_URL" \
    -u "${OAUTH_CLIENT_ID}:${OAUTH_CLIENT_SECRET}" \
    -d 'grant_type=client_credentials' \
    | jq -r '.access_token // empty')
  if [[ -z "$ACCESS_TOKEN" ]]; then
    echo "ERROR: token fetch failed (empty access_token). Check client + URL."
    exit 1
  fi
  echo "[auth] bearer obtained (len=${#ACCESS_TOKEN})"
fi
AUTH_HDR=()
[[ -n "$ACCESS_TOKEN" ]] && AUTH_HDR=(-H "Authorization: Bearer ${ACCESS_TOKEN}")

# An existing correlation_id from the seed (Shadow-Tanker chain).  Resolved
# on first run by querying the seed marker.  If you've truncated the seed
# this lookup will fail; in that case hand-set CORRELATION_ID below.
discover_correlation_id() {
  if [[ -n "${CORRELATION_ID:-}" ]]; then return 0; fi
  CORRELATION_ID=$(curl -sk -X POST "$TOOLS/graph_query" \
    "${AUTH_HDR[@]}" \
    -H "Content-Type: application/json" \
    -H "X-OLS-Label-Max: NFD" \
    -d '{"pattern":"multi_source_entity","args":{"hours":72,"min_correlations":2}}' \
    | jq -r '.data.entities[0].correlation_ids[0] // empty' 2>/dev/null)
}

run() {
  local label="$1"; shift
  local persona="$1"; shift
  local path="$1"; shift
  local body="$1"; shift
  echo
  echo "================================================================"
  echo "  [${persona}] ${label} — POST ${path}"
  echo "================================================================"
  # Capture body and metadata separately so the metadata footer doesn't end
  # up in jq's stdin (the previous "(jq parse failed …)" trailer was caused
  # by curl's -w line streaming after the JSON body).
  local body_file
  body_file=$(mktemp)
  local meta
  meta=$(curl -sk -X POST "${TOOLS}${path}" \
    "${AUTH_HDR[@]}" \
    -H "Content-Type: application/json" \
    -H "X-OLS-Label-Max: ${persona}" \
    -d "${body}" \
    -o "$body_file" \
    -w 'http=%{http_code} time=%{time_total}s')
  if jq -e . >/dev/null 2>&1 <"$body_file"; then
    jq "${JQ_FILTER}" <"$body_file"
  else
    echo "  (non-JSON response):"
    sed 's/^/    /' "$body_file" | head -10
  fi
  echo "  ${meta}"
  rm -f "$body_file"
}

echo "Testing tools at: ${TOOLS}"
echo "Personas: OFFEN (10), INTERN (30), NFD (50)"

# ---- OAuth gate sanity: anon must get 401 (skip if SKIP_AUTH=1 — the gate's
# already off by definition, no need to verify) ----
if [[ "${SKIP_AUTH:-0}" != "1" ]]; then
  echo
  echo "================================================================"
  echo "  [anon] OAuth gate — POST /graph_query (expect 401)"
  echo "================================================================"
  ANON_CODE=$(curl -sk -o /dev/null -w '%{http_code}' \
    -X POST "${TOOLS}/graph_query" \
    -H "Content-Type: application/json" \
    -H "X-OLS-Label-Max: NFD" \
    -d '{"pattern":"multi_source_entity","args":{"hours":72,"min_correlations":2}}')
  echo "  http=${ANON_CODE} (expected 401)"
  if [[ "$ANON_CODE" != "401" ]]; then
    echo "  WARN: OAuth gate may not be active — saw $ANON_CODE, not 401."
  fi
fi

# ---- Tool 1: graph_query — multi_source_entity pattern, 3 personas ----
for persona in OFFEN INTERN NFD; do
  run "graph_query / multi_source_entity" "$persona" "/graph_query" \
    '{"pattern":"multi_source_entity","args":{"hours":72,"min_correlations":2}}'
done

# ---- Tool 1: graph_query — convergence pattern (NFD persona) ----
run "graph_query / convergence" "NFD" "/graph_query" \
  '{"pattern":"convergence","args":{"hours":72,"h3_cell":"r5/55.3/15.5"}}'

# ---- Tool 2: spatial_aggregate — global, 3 personas ----
for persona in OFFEN INTERN NFD; do
  run "spatial_aggregate / global, 72h" "$persona" "/spatial_aggregate" \
    '{"h3_resolution":5,"hours":72,"min_events":3}'
done

# ---- Tool 2: spatial_aggregate — Baltic bbox ----
run "spatial_aggregate / Baltic bbox" "INTERN" "/spatial_aggregate" \
  '{"h3_resolution":5,"hours":72,"min_events":2,
    "bbox":{"min_lat":53,"max_lat":58,"min_lon":13,"max_lon":23}}'

# ---- Tool 3: persist_briefing — happy path (cap=NFD, classification=INTERN) ----
discover_correlation_id
if [[ -n "${CORRELATION_ID:-}" ]]; then
  run "persist_briefing / happy path" "NFD" "/persist_briefing" \
    '{"briefing":{
      "title":"smoke-test briefing",
      "summary":"Tool smoke test — synthetic briefing referencing a seeded correlation.",
      "classification":"INTERN",
      "findings":[{"text":"placeholder finding"}],
      "confidence":0.7,
      "correlation_id":"'"${CORRELATION_ID}"'"
    }}'

  # ---- Tool 3: persist_briefing — privilege-escalation guard (cap=OFFEN, classification=NFD) ----
  # Expected: 403 with type=forbidden + clear detail message.
  run "persist_briefing / over-cap (expect 403)" "OFFEN" "/persist_briefing" \
    '{"briefing":{
      "title":"forbidden briefing",
      "summary":"Should be rejected: NFD classification > OFFEN cap.",
      "classification":"NFD",
      "findings":[{"text":"placeholder finding"}],
      "confidence":0.5,
      "correlation_id":"'"${CORRELATION_ID}"'"
    }}'

  # ---- Tool 3: persist_briefing — bad input (missing classification) ----
  run "persist_briefing / bad input (expect 400)" "INTERN" "/persist_briefing" \
    '{"briefing":{
      "title":"missing-class briefing",
      "summary":"Should be rejected: classification field omitted.",
      "findings":[{"text":"x"}],
      "confidence":0.5,
      "correlation_id":"'"${CORRELATION_ID}"'"
    }}'
else
  echo
  echo "  WARN: no correlation_id discovered — skipping persist_briefing tests."
fi

# ---- Tool 4: vector_hybrid_search — expected 503 (embeddings still NULL) ----
run "vector_hybrid_search / expect 503" "INTERN" "/vector_hybrid_search" \
  '{"query":"jamming activity baltic","top_k":5}'

echo
echo "================================================================"
echo "  Done.  Look for:"
echo "    - graph_query: monotonic entity counts as persona OFFEN→INTERN→NFD"
echo "    - spatial_aggregate: monotonic feature counts; Baltic-bbox subset"
echo "    - persist_briefing happy: 201 + briefing_id"
echo "    - persist_briefing over-cap: 403 + 'User-Cap erlaubt nur bis ...'"
echo "    - persist_briefing bad input: 400"
echo "    - vector_hybrid_search: 503 with embeddings-not-ready"
echo "================================================================"
