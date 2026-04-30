#!/usr/bin/env bash
# Hits each running service's /openapi.json and writes it to docs/openapi/.
#
# Usage:
#   chmod +x scripts/dump-openapi.sh
#   ./scripts/dump-openapi.sh
#
# Services that are not currently running are skipped (not a failure).
set -euo pipefail

mkdir -p docs/openapi

for pair in "geoint:8001" "doc-intelligence:8002" "osint-fusion:8003" "supply-chain:8004" "compliance:8005"; do
  name="${pair%%:*}"
  port="${pair##*:}"
  if curl -sf "http://localhost:${port}/openapi.json" -o "docs/openapi/${name}.json"; then
    echo "[ok] ${name} -> docs/openapi/${name}.json"
  else
    echo "[skip] ${name} (not running on :${port})"
  fi
done
