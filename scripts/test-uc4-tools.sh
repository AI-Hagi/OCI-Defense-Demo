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
#  Optional:
#      JQ_FILTER       jq filter applied to each response (default: '.')
#                      e.g. JQ_FILTER='.duration_ms,.ols_cap_label' for tighter output
# =============================================================================
set -u
IFS=$'\n\t'

BASE="${ORDS_BASE_URL:-https://${ATP_HOST:-localhost}:8443/ords}"
TOOLS="${BASE}/uc4_osint/api/v1/tools"
JQ_FILTER="${JQ_FILTER:-.}"

# An existing correlation_id from the seed (Shadow-Tanker chain).  Resolved
# on first run by querying the seed marker.  If you've truncated the seed
# this lookup will fail; in that case hand-set CORRELATION_ID below.
discover_correlation_id() {
  if [[ -n "${CORRELATION_ID:-}" ]]; then return 0; fi
  CORRELATION_ID=$(curl -sk -X POST "$TOOLS/graph_query" \
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
  curl -sk -X POST "${TOOLS}${path}" \
    -H "Content-Type: application/json" \
    -H "X-OLS-Label-Max: ${persona}" \
    -d "${body}" \
    -w '\n  http=%{http_code} time=%{time_total}s\n' \
    | jq "${JQ_FILTER}" 2>/dev/null \
    || echo "  (jq parse failed — server returned non-JSON or empty)"
}

echo "Testing tools at: ${TOOLS}"
echo "Personas: OFFEN (10), INTERN (30), NFD (50)"

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
