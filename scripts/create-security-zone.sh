#!/usr/bin/env bash
# =============================================================================
#  Sovereign Defence Intelligence Platform - OCI Security Zone Lock-Down
# -----------------------------------------------------------------------------
#  WARNING - PRODUCTION-IMPACTING SCRIPT
#  -----------------------------------------------------------------------------
#  Locking a compartment as a Security Zone is a one-way change with broad
#  side effects. Once enforced:
#
#    * Object Storage buckets MUST be private (no public access policies)
#    * ADBs MUST use customer-managed encryption keys (Vault-managed) or
#      Oracle-managed with private endpoints — public ATPs are blocked
#    * Compute instances MUST sit behind a Load Balancer, no public IPs on
#      the instance itself
#    * Block volumes MUST be encrypted with customer-managed Vault keys
#    * VCNs cannot have route rules to internet gateways from private subnets
#    * Resources that violate the recipe at lock time become read-only —
#      they are NOT auto-deleted, but they cannot be modified until they
#      conform to the policy
#
#  Recommendation: run `scripts/activate-cloud-guard.sh` first, deploy the
#  platform, drive Cloud Guard problems to zero, THEN run this script.
#  Running it on a half-deployed compartment can wedge resources mid-rollout.
# =============================================================================
#
#  This script idempotently:
#
#    1. Resolves the tenancy OCID (parent walk from $COMP)
#    2. Discovers the Oracle-managed "Maximum Security Recipe" OCID
#    3. Creates a Security Zone covering $COMP that uses the Maximum recipe
#    4. Persists the Security Zone OCID into .oci-cloudguard.env
#    5. Prints a remove-lock runbook (if the operator wants to unwind it)
#
#  Auth:      instance_principal
#  Region:    eu-frankfurt-1 (override with REGION env)
#  Idempotent: every create call tolerates HTTP 409.
#  Prereqs : oci CLI >= 3.37, jq, Cloud Guard already activated
#            (run scripts/activate-cloud-guard.sh first), IAM policy allowing
#            cloud-guard-security-zone-* and iam compartment-read.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
#  CONFIG (env-driven)
# ---------------------------------------------------------------------------
: "${COMP:?ERROR: COMP (compartment OCID) must be exported}"
REGION="${REGION:-eu-frankfurt-1}"
TENANCY_OCID="${TENANCY_OCID:-}"                              # optional override
ZONE_NAME="${ZONE_NAME:-sovdefence-secure-zone}"
ZONE_DESCRIPTION="${ZONE_DESCRIPTION:-Sovereign Defence Intelligence Platform - Maximum Security}"

# Skip the human-readable safety prompt by exporting CONFIRM=YES
CONFIRM="${CONFIRM:-}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.oci-cloudguard.env"

# ---------------------------------------------------------------------------
#  Logging helpers (stderr; never echo secrets)
# ---------------------------------------------------------------------------
_log_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()      { printf "[%s] [INFO] %s\n"  "$(_log_ts)" "$*" >&2; }
log_ok()   { printf "[%s] [ OK ] %s\n"  "$(_log_ts)" "$*" >&2; }
log_warn() { printf "[%s] [WARN] %s\n"  "$(_log_ts)" "$*" >&2; }
log_err()  { printf "[%s] [ERR ] %s\n"  "$(_log_ts)" "$*" >&2; }
die()      { log_err "$*"; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

# ---------------------------------------------------------------------------
#  .oci-cloudguard.env helpers
# ---------------------------------------------------------------------------
env_upsert() {
  local key="$1" val="$2"
  [[ -n "$val" && "$val" != "null" ]] || { log_warn "Skipping empty OCID for $key"; return 0; }
  touch "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k {$0=k"="v} {print}' "$ENV_FILE" >"$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf "%s=%s\n" "$key" "$val" >>"$ENV_FILE"
  fi
  log_ok "Recorded $key in $ENV_FILE"
}

env_get() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 1
  awk -F= -v k="$key" '$1==k{print $2; exit}' "$ENV_FILE"
}

# ---------------------------------------------------------------------------
#  OCI CLI wrappers
#  Ref: https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/
# ---------------------------------------------------------------------------
oci_call() {
  oci --auth instance_principal --region "$REGION" --output json "$@"
}

oci_create_idempotent() {
  local _out _rc
  _out="$(oci --auth instance_principal --region "$REGION" --output json "$@" 2>&1)" && _rc=0 || _rc=$?
  if [[ $_rc -eq 0 ]]; then
    printf '%s' "$_out"
    return 0
  fi
  if printf '%s' "$_out" | grep -qE '"status":[[:space:]]*409|AlreadyExists|already exists|Conflict'; then
    log_warn "Resource already exists (409) - will look it up instead"
    return 0
  fi
  printf '%s\n' "$_out" >&2
  return "$_rc"
}

# ---------------------------------------------------------------------------
#  Preflight
# ---------------------------------------------------------------------------
require_cmd oci
require_cmd jq
log "Compartment:  $COMP"
log "Region:       $REGION"
log "Zone name:    $ZONE_NAME"
log "Env file:     $ENV_FILE"

# ---------------------------------------------------------------------------
#  Safety prompt (interactive). Bypass with CONFIRM=YES.
# ---------------------------------------------------------------------------
if [[ "$CONFIRM" != "YES" ]]; then
  cat <<'PROMPT' >&2

============================================================================
  WARNING: about to lock a compartment as a Security Zone.

  Once enforced, the Oracle-managed Maximum Security Recipe will reject any
  resource creation/modification that violates its policies. If the
  Sovereign Defence platform is not yet fully deployed, deployment may fail
  in unpredictable places.

  Run scripts/activate-cloud-guard.sh first and triage all OPEN problems
  to zero before proceeding.
============================================================================

To proceed, re-run with:  CONFIRM=YES bash scripts/create-security-zone.sh
PROMPT
  exit 3
fi

# =============================================================================
#  Step 1/4: Resolve tenancy (root) OCID
#  -----------------------------------------------------------------------------
#  Reuse the same parent-walk approach as activate-cloud-guard.sh. Prefer the
#  cached value in .oci-cloudguard.env if it's already there.
#  Ref: oci iam compartment get
# =============================================================================
log "Step 1/4: resolving tenancy OCID"
if [[ -z "$TENANCY_OCID" ]]; then
  TENANCY_OCID="$(env_get TENANCY_OCID || true)"
fi
if [[ -z "$TENANCY_OCID" ]]; then
  current="$COMP"
  hops=0
  while (( hops < 10 )); do
    parent="$(oci_call iam compartment get --compartment-id "$current" \
              --query 'data."compartment-id"' --raw-output 2>/dev/null || true)"
    [[ -n "$parent" && "$parent" != "null" ]] || die "Could not resolve parent of $current"
    if [[ "$parent" == "$current" ]]; then
      TENANCY_OCID="$current"
      break
    fi
    current="$parent"
    hops=$((hops + 1))
  done
fi
[[ -n "$TENANCY_OCID" ]] || die "Could not resolve tenancy OCID"
env_upsert "TENANCY_OCID" "$TENANCY_OCID"
log_ok "Tenancy OCID: $TENANCY_OCID"

# =============================================================================
#  Step 2/4: Discover Oracle-managed Maximum Security Recipe
#  -----------------------------------------------------------------------------
#  Oracle ships exactly one ORACLE-owned recipe whose display-name mentions
#  "Maximum". We list at the tenancy level (recipes are tenancy-scoped) and
#  pick the first match. If Oracle ever renames it, override SECURITY_ZONE_RECIPE_ID
#  via env to short-circuit the discovery.
#  Ref: oci cloud-guard security-recipe list
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/cloud-guard/security-recipe/list.html
# =============================================================================
log "Step 2/4: discover Oracle-managed Maximum Security Recipe"
RECIPE_ID="${SECURITY_ZONE_RECIPE_ID:-}"
if [[ -z "$RECIPE_ID" ]]; then
  recipes_json="$(oci_call cloud-guard security-recipe list \
                  --compartment-id "$TENANCY_OCID" \
                  --all 2>/dev/null || echo '{}')"
  RECIPE_ID="$(printf '%s' "$recipes_json" \
    | jq -r '[.data.items[]? | select(.owner=="ORACLE") | select(."display-name" | test("Maximum"; "i"))] | .[0].id // empty')"
fi
if [[ -z "$RECIPE_ID" ]]; then
  log_err "Could not locate Oracle-managed Maximum Security Recipe"
  log_err "Run: oci cloud-guard security-recipe list --compartment-id $TENANCY_OCID --all"
  log_err "Then export SECURITY_ZONE_RECIPE_ID=<recipe-ocid> and re-run"
  die "Security recipe discovery failed"
fi
env_upsert "SECURITY_ZONE_RECIPE_ID" "$RECIPE_ID"
log_ok "Maximum Security Recipe OCID: $RECIPE_ID"

# =============================================================================
#  Step 3/4: Create Security Zone on the platform compartment
#  -----------------------------------------------------------------------------
#  This is the locking step. After this returns, every subsequent create-or-
#  update against $COMP must comply with the Maximum recipe.
#  Ref: oci cloud-guard security-zone create
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/cloud-guard/security-zone/create.html
# =============================================================================
log "Step 3/4: ensure Security Zone ($ZONE_NAME) on compartment $COMP"
ZONE_ID="$(env_get SECURITY_ZONE_ID || true)"
if [[ -z "$ZONE_ID" ]]; then
  out="$(oci_create_idempotent cloud-guard security-zone create \
          --compartment-id "$COMP" \
          --display-name "$ZONE_NAME" \
          --description "$ZONE_DESCRIPTION" \
          --security-zone-recipe-id "$RECIPE_ID" || true)"
  ZONE_ID="$(printf '%s' "$out" | jq -r '.data.id // empty' 2>/dev/null || true)"
  if [[ -z "$ZONE_ID" ]]; then
    ZONE_ID="$(oci_call cloud-guard security-zone list \
                --compartment-id "$COMP" --all 2>/dev/null \
                | jq -r --arg n "$ZONE_NAME" \
                  '.data.items[]? | select(."display-name"==$n) | .id' | head -n1)"
  fi
  [[ -n "$ZONE_ID" ]] || die "Could not obtain Security Zone OCID for $ZONE_NAME"
  env_upsert "SECURITY_ZONE_ID" "$ZONE_ID"
fi
log_ok "Security Zone OCID: $ZONE_ID"

# =============================================================================
#  Step 4/4: print confirmation + unwind runbook
# =============================================================================
cat <<NEXT >&2

==============================================================================
  Security Zone is ACTIVE on compartment $COMP
  Recipe: Oracle-managed Maximum Security ($RECIPE_ID)
  Zone:   $ZONE_NAME ($ZONE_ID)
==============================================================================

OPERATIONAL NOTES:

  * From now on, resource creation in this compartment is policy-checked
    against the Maximum recipe. Violations are rejected at the API layer,
    NOT at provisioning time — they will not appear as Cloud Guard
    "problems"; they appear as 4xx errors from create/update.

  * To inspect which policies the recipe enforces:
       oci --auth instance_principal --region $REGION \\
           cloud-guard security-policy list \\
           --compartment-id "$TENANCY_OCID" --all \\
           --query 'data.items[].{name:"display-name",svc:"services"}'

  * To unwind (REMOVE the lock) if a deployment is wedged:
       oci --auth instance_principal --region $REGION \\
           cloud-guard security-zone delete \\
           --security-zone-id "$ZONE_ID" --force
    The compartment remains; only the policy enforcement is removed.

  * To audit which resources currently violate the recipe (run BEFORE locking
    any future expansion compartments):
       oci --auth instance_principal --region $REGION \\
           cloud-guard problem list \\
           --compartment-id "$COMP" \\
           --lifecycle-state OPEN \\
           --risk-level HIGH \\
           --query 'data.items[].{name:"problem-name",resource:"resource-name"}'

==============================================================================
NEXT

log_ok "Security Zone setup finished successfully"
