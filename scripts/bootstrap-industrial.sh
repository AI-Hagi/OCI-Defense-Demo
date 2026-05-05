#!/usr/bin/env bash
# =====================================================================
# scripts/bootstrap-industrial.sh   (v2 — UC10 added)
# Idempotent bootstrap for the four industrial-defence use cases.
#
# UC #07 Engineering Knowledge      (industrial/01-engineering-knowledge)
# UC #08 Quality & Incident         (industrial/02-quality-incident)
# UC #09 Software Assurance         (industrial/03-software-assurance)
# UC #10 Requirements Intelligence  (industrial/10-requirements-intelligence) ← NEW
#
# Usage:
#   ./scripts/bootstrap-industrial.sh                     # run everything
#   ./scripts/bootstrap-industrial.sh --shared-only       # just _shared/
#   ./scripts/bootstrap-industrial.sh --uc 01             # just UC #07
#   ./scripts/bootstrap-industrial.sh --uc 02             # just UC #08
#   ./scripts/bootstrap-industrial.sh --uc 03             # just UC #09
#   ./scripts/bootstrap-industrial.sh --uc 10             # just UC #10 (NEW)
#   ./scripts/bootstrap-industrial.sh --import-agents     # only push agent YAMLs
#   ./scripts/bootstrap-industrial.sh --load-uc10-samples # synthetic RE data (NEW)
#   ./scripts/bootstrap-industrial.sh --dry-run           # show plan only
# =====================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INDUSTRIAL_DIR="$REPO_ROOT/industrial"
LOG_DIR="$REPO_ROOT/.industrial-logs"
mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------
# Load .env from repo root (single source of truth)
# ---------------------------------------------------------------------
if [[ ! -f "$REPO_ROOT/.env" ]]; then
  echo "ERROR: $REPO_ROOT/.env missing. Copy .env.example and fill in." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/.env"; set +a

# ---------------------------------------------------------------------
# Required vars
# ---------------------------------------------------------------------
: "${OCI_REGION:?OCI_REGION not set}"
: "${OCI_COMPARTMENT_OCID:?OCI_COMPARTMENT_OCID not set}"
: "${ADB_NAME:?ADB_NAME not set}"
: "${ADB_TNS_ALIAS:?ADB_TNS_ALIAS not set}"
: "${ADB_WALLET_PATH:?ADB_WALLET_PATH not set}"
: "${DB_APP_USER:?DB_APP_USER not set}"
: "${DB_APP_PWD:?DB_APP_PWD not set}"

# ---------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------
MODE="all"
UC=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --shared-only)        MODE="shared"; shift ;;
    --uc)                 MODE="uc"; UC="$2"; shift 2 ;;
    --import-agents)      MODE="agents"; shift ;;
    --load-uc10-samples)  MODE="uc10-samples"; shift ;;
    --dry-run)            DRY_RUN=1; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------
# SQLcl wrapper with substitution-variable support
# ---------------------------------------------------------------------
run_sql() {
  local file="$1"
  local logfile="$LOG_DIR/$(basename "$file" .sql).log"
  echo "  → running $file"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "    (dry-run, would execute against $ADB_TNS_ALIAS)"
    return 0
  fi
  envsubst < "$file" \
    | sql -L "$DB_APP_USER/$DB_APP_PWD@$ADB_TNS_ALIAS" \
        \
        > "$logfile" 2>&1 \
    || { echo "    FAILED. See $logfile"; tail -20 "$logfile"; exit 1; }
  echo "    ok ($(wc -l < "$logfile") log lines)"
}

# ---------------------------------------------------------------------
# Phase 1 — shared layer
# ---------------------------------------------------------------------
bootstrap_shared() {
  echo "[shared] coalition_ctx + AI profiles"
  run_sql "$INDUSTRIAL_DIR/_shared/coalition_ctx_bootstrap.sql"
  run_sql "$INDUSTRIAL_DIR/_shared/ai_profile_template.sql"
}

# ---------------------------------------------------------------------
# Phase 2 — single UC (auto-discovers by directory prefix)
# ---------------------------------------------------------------------
bootstrap_uc() {
  local uc_num="$1"
  local uc_dir
  uc_dir=$(find "$INDUSTRIAL_DIR" -maxdepth 1 -type d -name "${uc_num}-*" | head -1)
  if [[ -z "$uc_dir" ]]; then
    echo "ERROR: UC $uc_num not found in $INDUSTRIAL_DIR" >&2
    exit 1
  fi
  echo "[uc-$uc_num] $(basename "$uc_dir")"
  for sql_file in "$uc_dir"/schema/0[1-5]_*.sql; do
    run_sql "$sql_file"
  done
}

# ---------------------------------------------------------------------
# Phase 3 — push agent specs to Private Agent Factory
# ---------------------------------------------------------------------
import_agents() {
  : "${AGENT_FACTORY_HOST:?AGENT_FACTORY_HOST not set}"
  : "${AGENT_FACTORY_ADMIN_USER:?AGENT_FACTORY_ADMIN_USER not set}"
  : "${AGENT_FACTORY_ADMIN_PWD:?AGENT_FACTORY_ADMIN_PWD not set}"

  for agent_yaml in "$INDUSTRIAL_DIR"/*/agent/*.agent.yaml; do
    echo "[agent] $agent_yaml"
    if [[ $DRY_RUN -eq 1 ]]; then
      echo "    (dry-run, would POST to $AGENT_FACTORY_HOST/v1/agents)"
      continue
    fi
    local rendered="/tmp/$(basename "$agent_yaml")"
    envsubst < "$agent_yaml" > "$rendered"

    curl -fsS -X POST "$AGENT_FACTORY_HOST/v1/agents" \
      -u "$AGENT_FACTORY_ADMIN_USER:$AGENT_FACTORY_ADMIN_PWD" \
      -H "Content-Type: application/yaml" \
      --data-binary "@$rendered" \
      || { echo "    FAILED to import $agent_yaml"; exit 1; }
    echo "    ok"
    rm -f "$rendered"
  done
}

# ---------------------------------------------------------------------
# Phase 4 — UC10 synthetic sample data (NEW in v2)
# ---------------------------------------------------------------------
load_uc10_samples() {
  local uc10_dir="$INDUSTRIAL_DIR/10-requirements-intelligence"
  if [[ ! -d "$uc10_dir/sample-data" ]]; then
    echo "ERROR: $uc10_dir/sample-data not found" >&2
    exit 1
  fi
  echo "[uc-10-samples] generating synthetic Requirements via OCI GenAI"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "    (dry-run, would generate ~240 synthetic requirements across 3 programs)"
    return 0
  fi
  : "${OCI_GENAI_ENDPOINT:?OCI_GENAI_ENDPOINT not set}"
  python3 "$uc10_dir/sample-data/generate.py" \
    --output "$uc10_dir/sample-data/synthetic.json" \
    --programs 3 --requirements-per-program 80 \
    || { echo "    FAILED to generate synthetic data"; exit 1; }
  run_sql "$uc10_dir/sample-data/load_sample_data.sql"
  echo "    ok — synthetic UC10 corpus loaded"
}

# ---------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------
echo "=== bootstrap-industrial.sh ==="
echo "MODE=$MODE  UC=$UC  DRY_RUN=$DRY_RUN  REGION=$OCI_REGION"
echo

case "$MODE" in
  shared)       bootstrap_shared ;;
  uc)           bootstrap_uc "$UC" ;;
  agents)       import_agents ;;
  uc10-samples) load_uc10_samples ;;
  all)
    bootstrap_shared
    bootstrap_uc "01"
    bootstrap_uc "02"
    bootstrap_uc "03"
    bootstrap_uc "10"
    import_agents
    ;;
esac

echo
echo "=== done. Logs in $LOG_DIR/ ==="
