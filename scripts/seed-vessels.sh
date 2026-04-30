#!/usr/bin/env bash
# =============================================================================
# Wrapper for db/schema/09_vessels_seed.sql.
#
# Reads AIS_BBOX_DEFAULT from environment (or repo-root .env via dotenv if
# python-dotenv is available), splits it into &BBOX_SOUTH/WEST/NORTH/EAST
# SQLcl substitution variables, and runs the seed script. The vessel
# coordinates inside the SQL are FIXED — the substitution variables only
# drive an informational PROMPT block at the top so the operator sees which
# bbox the platform is configured for at the moment of seeding.
#
# Usage:
#   AIS_BBOX_DEFAULT=53,8,56,22 \
#   ORACLE_CONNECT_STRING=sovdef26_tp \
#   ORACLE_USER=DICE_APP ORACLE_PASSWORD=secret \
#   bash scripts/seed-vessels.sh
#
# Required env (read from current shell only — this script does not parse
# .env files itself):
#   AIS_BBOX_DEFAULT       (south,west,north,east — defaults to 53,8,56,22)
#   ORACLE_CONNECT_STRING  (TNS alias, e.g. sovdef26_tp)
#   ORACLE_USER            (DB user)
#   ORACLE_PASSWORD        (DB password)
#   TNS_ADMIN              (wallet path; defaults to /app/wallet)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_FILE="$REPO_ROOT/db/schema/09_vessels_seed.sql"

[[ -f "$SQL_FILE" ]] || { echo "SQL file not found: $SQL_FILE" >&2; exit 1; }

# Resolve bbox from env, fall back to canonical Baltic.
BBOX="${AIS_BBOX_DEFAULT:-53,8,56,22}"
IFS=',' read -r BBOX_SOUTH BBOX_WEST BBOX_NORTH BBOX_EAST <<<"$BBOX"

# Sanity check.
if [[ -z "${BBOX_SOUTH:-}" || -z "${BBOX_WEST:-}" || -z "${BBOX_NORTH:-}" || -z "${BBOX_EAST:-}" ]]; then
  echo "AIS_BBOX_DEFAULT must be 'south,west,north,east' (got: $BBOX)" >&2
  exit 1
fi

# Required DB env.
: "${ORACLE_CONNECT_STRING:?ORACLE_CONNECT_STRING must be set (e.g. sovdef26_tp)}"
: "${ORACLE_USER:?ORACLE_USER must be set}"
: "${ORACLE_PASSWORD:?ORACLE_PASSWORD must be set}"
TNS_ADMIN="${TNS_ADMIN:-/app/wallet}"

if ! command -v sql >/dev/null 2>&1; then
  echo "sqlcl ('sql') not found in PATH — install Oracle SQLcl." >&2
  exit 1
fi

echo "Seeding vessels using bbox=${BBOX_SOUTH},${BBOX_WEST},${BBOX_NORTH},${BBOX_EAST} into ${ORACLE_CONNECT_STRING}"

TNS_ADMIN="$TNS_ADMIN" sql -S "${ORACLE_USER}/${ORACLE_PASSWORD}@${ORACLE_CONNECT_STRING}" <<SQL
DEFINE BBOX_SOUTH = '${BBOX_SOUTH}'
DEFINE BBOX_WEST  = '${BBOX_WEST}'
DEFINE BBOX_NORTH = '${BBOX_NORTH}'
DEFINE BBOX_EAST  = '${BBOX_EAST}'
@${SQL_FILE}
SQL
