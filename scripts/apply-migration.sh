#!/usr/bin/env bash
# =============================================================================
#  Apply a single SQL migration via SQLcl against sovdef26 ADB.
# -----------------------------------------------------------------------------
#  Usage:
#      ADB_ADMIN_PASSWORD='<password>' \
#          bash scripts/apply-migration.sh db/migrations/01_add_image_uri.sql
#
#  Required env:
#      ADB_ADMIN_PASSWORD   ADMIN user password for sovdef26.
#  Optional env:
#      ADB_USER             default ADMIN
#      ADB_TNS_ALIAS        default sovdef26_tp (matches tnsnames.ora)
#      WALLET_DIR           default ~/wallet (contains tnsnames.ora + cwallet.sso)
#
#  Notes:
#   - Migrations live under db/migrations/ and are intended to be idempotent
#     (each one wraps its DDL in a PL/SQL existence check).
#   - SQLcl's `sql` binary is expected on PATH (`which sql`).
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <path-to-migration.sql>" >&2
  exit 2
fi

MIGRATION_FILE="$1"
[[ -f "$MIGRATION_FILE" ]] || { echo "ERROR: file not found: $MIGRATION_FILE" >&2; exit 1; }

: "${ADB_ADMIN_PASSWORD:?ERROR: export ADB_ADMIN_PASSWORD before running}"
ADB_USER="${ADB_USER:-ADMIN}"
ADB_TNS_ALIAS="${ADB_TNS_ALIAS:-sovdef26_tp}"
WALLET_DIR="${WALLET_DIR:-$HOME/wallet}"

[[ -d "$WALLET_DIR" ]] || { echo "ERROR: wallet dir missing: $WALLET_DIR" >&2; exit 1; }
command -v sql >/dev/null || { echo "ERROR: SQLcl 'sql' not on PATH" >&2; exit 1; }

export TNS_ADMIN="$WALLET_DIR"

echo "[apply-migration] file=$MIGRATION_FILE user=$ADB_USER alias=$ADB_TNS_ALIAS"
sql -S "$ADB_USER/$ADB_ADMIN_PASSWORD@$ADB_TNS_ALIAS" <<EOF
WHENEVER SQLERROR EXIT FAILURE
SET ECHO ON
SET FEEDBACK ON
@${MIGRATION_FILE}
EXIT
EOF
echo "[apply-migration] done"
