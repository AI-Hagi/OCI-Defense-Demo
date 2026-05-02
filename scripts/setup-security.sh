#!/usr/bin/env bash
# =============================================================================
#  Sovereign Defence — security automation orchestrator
# -----------------------------------------------------------------------------
#  Wrapper that runs the two security-side bootstrap scripts in the
#  recommended order:
#
#    1. activate-cloud-guard.sh — enables Cloud Guard at the tenancy level
#       (idempotent; safe to re-run) and creates a target on the platform
#       compartment with the Oracle-managed default detector recipes.
#
#    2. create-security-zone.sh — locks the platform compartment to the
#       Oracle-managed Maximum Security Recipe. **Disabled by default**
#       because the recipe rejects ADB Always-Free (Shared) and other
#       resources our demo currently uses (see docs/security-zone-overview.md
#       for the compatibility caveat).
#
#  Required env:
#      COMP            compartment OCID (the platform compartment)
#      TENANCY_OCID    tenancy (root) OCID — required because the dev VM's
#                      instance principal cannot walk the parent chain
#                      above its own compartment.
#  Optional env:
#      REGION                   default eu-frankfurt-1
#      LOCK_SECURITY_ZONE       set to 'YES' to also run create-security-zone.sh
#                               (which itself requires CONFIRM=YES inside).
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

: "${COMP:?ERROR: COMP must be exported (the platform compartment OCID)}"
: "${TENANCY_OCID:?ERROR: TENANCY_OCID must be exported (root compartment OCID)}"
REGION="${REGION:-eu-frankfurt-1}"
LOCK_SECURITY_ZONE="${LOCK_SECURITY_ZONE:-NO}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()    { printf "[%s] [INFO] %s\n" "$(ts)" "$*"; }
log_ok() { printf "[%s] [ OK ] %s\n" "$(ts)" "$*"; }
log_warn(){ printf "[%s] [WARN] %s\n" "$(ts)" "$*"; }

log "Phase 1/2: activate Cloud Guard"
if bash "$SCRIPT_DIR/activate-cloud-guard.sh"; then
  log_ok "Cloud Guard activation script finished"
else
  rc=$?
  log_warn "activate-cloud-guard.sh exited $rc — check its logs above; continuing"
fi

if [[ "$LOCK_SECURITY_ZONE" == "YES" ]]; then
  log "Phase 2/2: lock compartment with Maximum Security Recipe"
  log_warn "This will REJECT non-compliant resources (no public buckets, ADB CMK only, etc.)"
  log_warn "Review docs/security-zone-overview.md before continuing."
  if CONFIRM=YES bash "$SCRIPT_DIR/create-security-zone.sh"; then
    log_ok "Security Zone created"
  else
    rc=$?
    log_warn "create-security-zone.sh exited $rc"
  fi
else
  log "Phase 2/2 skipped (LOCK_SECURITY_ZONE != YES). To run it later:"
  log "    LOCK_SECURITY_ZONE=YES CONFIRM=YES bash scripts/setup-security.sh"
fi

log_ok "setup-security.sh done — see .oci-cloudguard.env for OCIDs"
