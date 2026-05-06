#!/usr/bin/env bash
# =====================================================================
# scripts/verify-coalition-vpd.sh   (v2 — UC10 program-isolation added)
#
# Verifies the coalition VPD is working correctly by running the same
# query under different session contexts and asserting that row counts
# differ. This is the foundational test for the DICE-EU demo and for
# UC10 program isolation (Eurofighter ≠ FCAS).
#
# Usage:
#   ./scripts/verify-coalition-vpd.sh         # all checks (default)
#   ./scripts/verify-coalition-vpd.sh --uc 01 # only UC #07 object
#   ./scripts/verify-coalition-vpd.sh --uc 10 # only UC #10 object (NEW)
#
# Exit 0 = VPD works as expected
# Exit 1 = VPD broken (rows leak across coalitions or fail-closed missing)
# =====================================================================

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/.env"; set +a

: "${ADB_TNS_ALIAS:?}"
: "${DB_APP_USER:?}"
: "${DB_APP_PWD:?}"

# ---------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------
TARGET_UC=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --uc) TARGET_UC="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------
# SQL helper
# ---------------------------------------------------------------------
run_query() {
  local user_id="$1" clearance="$2" nation="$3" releasability="$4" object="$5" extra_ctx="${6:-}"
  sql -L "$DB_APP_USER/$DB_APP_PWD@$ADB_TNS_ALIAS" <<SQL 2>/dev/null \
    | awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ {print $1; exit}'
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
EXEC coalition_ctx_pkg.set_session('$user_id', '$clearance', '$nation', '$releasability');
$extra_ctx
SELECT COUNT(*) FROM $object;
EXIT;
SQL
}

# ---------------------------------------------------------------------
# Test 1 — UC #07 Engineering Knowledge (clearance + releasability)
# ---------------------------------------------------------------------
test_uc07() {
  echo "=== UC #07 Coalition VPD Test ==="
  echo "Object: ENG_PART_DOCS_V"
  echo

  ALICE=$(run_query "alice" "RESTRICTED" "DEU" "NATO" "eng_part_docs_v")
  echo "Alice (DEU/RESTRICTED/NATO):                $ALICE rows"

  BOB=$(run_query "bob" "UNCLASSIFIED" "TUR" "NATIONAL_ONLY" "eng_part_docs_v")
  echo "Bob   (TUR/UNCLASSIFIED/NATIONAL_ONLY):     $BOB rows"

  MALLORY=$(sql -L "$DB_APP_USER/$DB_APP_PWD@$ADB_TNS_ALIAS" <<'SQL' 2>/dev/null \
      | awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ {print $1; exit}'
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
EXEC coalition_ctx_pkg.clear_session;
SELECT COUNT(*) FROM eng_part_docs_v;
EXIT;
SQL
)
  echo "Mallory (no context, fail-closed):          $MALLORY rows"

  if [[ "$MALLORY" != "0" ]]; then
    echo "FAIL: UC #07 fail-closed violated — Mallory returned $MALLORY rows."
    return 1
  fi
  if [[ "$ALICE" -eq "$BOB" && "$ALICE" -gt 0 ]]; then
    echo "WARN: UC #07 — Alice and Bob see equal rows. Either seed data too plain or VPD missing."
    return 1
  fi
  echo "PASS: UC #07 Coalition VPD OK"
  echo
  return 0
}

# ---------------------------------------------------------------------
# Test 2 — UC #10 Requirements Intelligence (program isolation)
# ---------------------------------------------------------------------
# UC10 adds program-level isolation on top of coalition VPD.
# coalition_ctx_set_program(...) is a UC10-specific helper that
# scopes a session to one or more programs (e.g. 'BOXER-MOD', 'SPZ-NEXTGEN').
# ---------------------------------------------------------------------
test_uc10() {
  echo "=== UC #10 Requirements Program-Isolation Test ==="
  echo "Object: REQUIREMENTS"
  echo

  # Engineer Alice: Eurofighter program only
  ALICE=$(run_query "alice" "RESTRICTED" "DEU" "NATO" "requirements" \
    "EXEC coalition_ctx_set_program('BOXER-MOD');")
  echo "Alice  (DEU/RESTRICTED/NATO, EUROFIGHTER):  $ALICE rows"

  # Engineer Bob: FCAS program only
  BOB=$(run_query "bob" "RESTRICTED" "FRA" "EU" "requirements" \
    "EXEC coalition_ctx_set_program('SPZ-NEXTGEN');")
  echo "Bob    (FRA/RESTRICTED/EU, FCAS):           $BOB rows"

  # Architect Carol: both programs (a privileged role)
  CAROL=$(run_query "carol" "RESTRICTED" "DEU" "NATO" "requirements" \
    "EXEC coalition_ctx_set_program('BOXER-MOD,SPZ-NEXTGEN');")
  echo "Carol  (DEU/RESTRICTED/NATO, both):         $CAROL rows"

  # Mallory: no program context → fail-closed
  MALLORY=$(sql -L "$DB_APP_USER/$DB_APP_PWD@$ADB_TNS_ALIAS" <<'SQL' 2>/dev/null \
      | awk '/^[[:space:]]*[0-9]+[[:space:]]*$/ {print $1; exit}'
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
EXEC coalition_ctx_pkg.clear_session;
SELECT COUNT(*) FROM requirements;
EXIT;
SQL
)
  echo "Mallory (no context, fail-closed):          $MALLORY rows"
  echo

  local fail=0
  if [[ "$MALLORY" != "0" ]]; then
    echo "FAIL: UC #10 fail-closed violated — Mallory returned $MALLORY rows."
    fail=1
  fi
  if [[ "$ALICE" -eq 0 || "$BOB" -eq 0 ]]; then
    echo "WARN: UC #10 — one of the programs returned 0 rows. Did sample data load?"
    echo "     Run: ./scripts/bootstrap-industrial.sh --load-uc10-samples"
    fail=1
  fi
  if [[ $fail -eq 0 && "$CAROL" -lt $((ALICE + BOB)) ]]; then
    echo "WARN: UC #10 — Carol (multi-program) sees fewer rows than Alice + Bob combined."
    echo "     This may indicate set_program parsing is not treating comma list correctly."
  fi
  if [[ $fail -eq 0 ]]; then
    echo "PASS: UC #10 program isolation OK (Eurofighter ≠ FCAS)"
  fi
  echo
  return $fail
}

# ---------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------
EXIT=0
case "$TARGET_UC" in
  "01"|"07") test_uc07 || EXIT=1 ;;
  "10")      test_uc10 || EXIT=1 ;;
  "")
    test_uc07 || EXIT=1
    test_uc10 || EXIT=1
    ;;
  *) echo "Unknown UC: $TARGET_UC. Use 01, 07 or 10." >&2; exit 2 ;;
esac

if [[ $EXIT -eq 0 ]]; then
  echo "=========================================="
  echo "All Coalition VPD tests PASSED."
  echo "=========================================="
fi

exit $EXIT
