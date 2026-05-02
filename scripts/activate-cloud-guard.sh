#!/usr/bin/env bash
# =============================================================================
#  Sovereign Defence Intelligence Platform - OCI Cloud Guard Activation
# -----------------------------------------------------------------------------
#  Idempotently enables OCI Cloud Guard (Oracle's Cloud Security Posture
#  Management offering) for the platform's compartment, and configures the
#  detector recipes that monitor the Sovereign Defence workload.
#
#  Performs five steps:
#
#    1. Resolve the tenancy (root compartment) OCID by walking parents up
#       from $COMP until we hit a compartment that is its own parent.
#    2. Enable Cloud Guard at the tenancy level (status=ENABLED, reporting
#       region pinned to $REGION). This is a no-op if already enabled.
#    3. Create a Cloud Guard managed list of "trusted" compartment OCIDs
#       (initially just $COMP) — used later by suppression rules so that
#       findings inside our own compartment can be carved out from broader
#       tenancy-wide policy.
#    4. Discover the two Oracle-managed default detector recipes
#       (Configuration + Threat) and create a Cloud Guard target on $COMP
#       that uses both. The target is what actually causes the platform's
#       resources (ADB, OKE, OCIR, buckets, VCN, etc.) to be evaluated.
#    5. Persist every produced OCID into .oci-cloudguard.env at the repo
#       root so downstream automation (alert wiring, security-zone script)
#       can source them without inspecting the console.
#
#  Auth:      instance_principal  (this script is meant to run on the dev VM)
#  Region:    eu-frankfurt-1      (override with REGION env)
#  Idempotent: every create call tolerates HTTP 409 and falls back to a list
#             query to locate the existing OCID.
#
#  Prereqs : oci CLI >= 3.37, jq, IAM policy granting the dev VM the
#            cloud-guard-* and iam compartment-read permissions.
#  Safety  : This script DOES NOT lock the compartment as a Security Zone
#            (that's `create-security-zone.sh`). Cloud Guard alone is
#            observe-only — it raises problems, it does not block resource
#            creation. Run this first; lock the zone later.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
#  CONFIG (env-driven)
# ---------------------------------------------------------------------------
: "${COMP:?ERROR: COMP (compartment OCID) must be exported}"
REGION="${REGION:-eu-frankfurt-1}"
TENANCY_OCID="${TENANCY_OCID:-}"                            # optional override
TARGET_NAME="${TARGET_NAME:-sovdefence-target}"
MANAGED_LIST_NAME="${MANAGED_LIST_NAME:-sovdefence-trusted-compartments}"

# Root of the repo checkout this script lives in: <repo>/scripts/activate-cloud-guard.sh
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
#  .oci-cloudguard.env helpers (progressive writes keep partial runs resumable)
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
#  OCI CLI wrappers - always instance-principal auth, json output, region-pinned
#  Ref: https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/
# ---------------------------------------------------------------------------
oci_call() {
  oci --auth instance_principal --region "$REGION" --output json "$@"
}

# Runs an `oci ... create` command and tolerates 409 (already exists). On
# success returns 0 with stdout = the JSON response. On a 409 returns 0
# with empty stdout so the caller can fall back to a list/search lookup.
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
log "Env file:     $ENV_FILE"

env_upsert "REGION"         "$REGION"
env_upsert "COMPARTMENT_ID" "$COMP"

# =============================================================================
#  Step 1/5: Resolve tenancy (root) OCID
#  -----------------------------------------------------------------------------
#  iam compartment get returns the compartment's parent in `compartment-id`.
#  The root compartment is its own parent, so we walk up until they match.
#  Ref: oci iam compartment get
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/iam/compartment/get.html
# =============================================================================
resolve_tenancy_ocid() {
  if [[ -n "$TENANCY_OCID" ]]; then
    printf '%s' "$TENANCY_OCID"
    return 0
  fi
  local current="$COMP" parent
  local hops=0
  while (( hops < 10 )); do
    parent="$(oci_call iam compartment get --compartment-id "$current" \
              --query 'data."compartment-id"' --raw-output 2>/dev/null || true)"
    [[ -n "$parent" && "$parent" != "null" ]] || die "Could not resolve parent compartment for $current"
    if [[ "$parent" == "$current" ]]; then
      printf '%s' "$current"
      return 0
    fi
    current="$parent"
    hops=$((hops + 1))
  done
  die "Could not resolve tenancy OCID after 10 hops"
}

log "Step 1/5: resolving tenancy (root compartment) OCID"
TENANCY_OCID="$(resolve_tenancy_ocid)"
[[ "$TENANCY_OCID" == ocid1.tenancy.* ]] || log_warn "Resolved root OCID has unexpected prefix: $TENANCY_OCID"
env_upsert "TENANCY_OCID" "$TENANCY_OCID"
log_ok "Tenancy OCID: $TENANCY_OCID"

# =============================================================================
#  Step 2/5: Enable Cloud Guard at tenancy level
#  -----------------------------------------------------------------------------
#  This is a tenancy-wide toggle; it is idempotent — calling it on an
#  already-enabled tenancy returns the same configuration. The reporting
#  region is the region all problems are aggregated into. We pin it to $REGION
#  (eu-frankfurt-1) so EU sovereignty rules are honoured.
#  Ref: oci cloud-guard configuration update
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/cloud-guard/configuration/update.html
# =============================================================================
log "Step 2/5: enabling Cloud Guard at tenancy level (reporting region $REGION)"
cg_config_out="$(oci_create_idempotent cloud-guard configuration update \
        --compartment-id "$TENANCY_OCID" \
        --status ENABLED \
        --reporting-region "$REGION" \
        --force || true)"
cg_status="$(printf '%s' "$cg_config_out" | jq -r '.data.status // empty' 2>/dev/null || true)"
if [[ -z "$cg_status" ]]; then
  # Verify via a get
  cg_status="$(oci_call cloud-guard configuration get \
              --compartment-id "$TENANCY_OCID" \
              --query 'data.status' --raw-output 2>/dev/null || true)"
fi
[[ "$cg_status" == "ENABLED" ]] || log_warn "Cloud Guard status is '$cg_status' (expected ENABLED)"
env_upsert "CLOUD_GUARD_STATUS"           "${cg_status:-UNKNOWN}"
env_upsert "CLOUD_GUARD_REPORTING_REGION" "$REGION"
log_ok "Cloud Guard tenancy-level status: ${cg_status:-UNKNOWN}"

# =============================================================================
#  Step 3/5: Create Cloud Guard managed list of trusted compartment OCIDs
#  -----------------------------------------------------------------------------
#  A managed list lets us reference a named set of OCIDs in detector rule
#  conditions (e.g. "do not flag bucket-public-write inside trusted comps").
#  We seed it with $COMP only — extend later via `oci cloud-guard managed-list
#  add` once additional sovereign-tenant compartments are onboarded.
#  Ref: oci cloud-guard managed-list create
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/cloud-guard/managed-list/create.html
# =============================================================================
log "Step 3/5: ensure Cloud Guard managed list ($MANAGED_LIST_NAME)"
ML_ID="$(env_get CLOUD_GUARD_MANAGED_LIST_ID || true)"
if [[ -z "$ML_ID" ]]; then
  ml_items_json="[\"$COMP\"]"
  out="$(oci_create_idempotent cloud-guard managed-list create \
          --compartment-id "$COMP" \
          --display-name "$MANAGED_LIST_NAME" \
          --list-type RESOURCE_OCID \
          --list-items "$ml_items_json" || true)"
  ML_ID="$(printf '%s' "$out" | jq -r '.data.id // empty' 2>/dev/null || true)"
  if [[ -z "$ML_ID" ]]; then
    ML_ID="$(oci_call cloud-guard managed-list list \
                --compartment-id "$COMP" --all 2>/dev/null \
                | jq -r --arg n "$MANAGED_LIST_NAME" \
                  '.data.items[]? | select(."display-name"==$n) | .id' | head -n1)"
  fi
  [[ -n "$ML_ID" ]] || die "Could not obtain Cloud Guard managed-list OCID for $MANAGED_LIST_NAME"
  env_upsert "CLOUD_GUARD_MANAGED_LIST_ID" "$ML_ID"
fi
log_ok "Managed list OCID: $ML_ID"

# =============================================================================
#  Step 4/5: Discover Oracle-managed detector recipes + create target
#  -----------------------------------------------------------------------------
#  Oracle ships two default ORACLE-owned detector recipes per tenancy:
#    - "OCI Configuration Detector Recipe (Oracle Managed)"
#    - "OCI Threat Detector Recipe (Oracle Managed)"
#  We list them at the tenancy level (resource-metadata-only true to avoid
#  pulling rule bodies — they're large), pick one of each by display-name
#  substring match, and bind them to a fresh target rooted at $COMP.
#  Ref: oci cloud-guard detector-recipe list
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/cloud-guard/detector-recipe/list.html
#       oci cloud-guard target create
#       https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/cloud-guard/target/create.html
# =============================================================================
log "Step 4/5: discover Oracle-managed detector recipes"
recipes_json="$(oci_call cloud-guard detector-recipe list \
                --compartment-id "$TENANCY_OCID" \
                --all 2>/dev/null || echo '{}')"

# Pick first ORACLE-owned recipe whose display-name mentions Configuration
CONFIG_RECIPE="$(printf '%s' "$recipes_json" \
  | jq -r '[.data.items[]? | select(.owner=="ORACLE") | select(."display-name" | test("Configuration"; "i"))] | .[0].id // empty')"
# Pick first ORACLE-owned recipe whose display-name mentions Threat
THREAT_RECIPE="$(printf '%s' "$recipes_json" \
  | jq -r '[.data.items[]? | select(.owner=="ORACLE") | select(."display-name" | test("Threat"; "i"))] | .[0].id // empty')"

if [[ -z "$CONFIG_RECIPE" ]]; then
  log_err "Could not locate Oracle-managed Configuration detector recipe"
  log_err "Run: oci cloud-guard detector-recipe list --compartment-id $TENANCY_OCID --all"
  die "Cloud Guard recipe discovery failed"
fi
if [[ -z "$THREAT_RECIPE" ]]; then
  log_warn "Oracle-managed Threat detector recipe not found — target will use Configuration only"
fi
env_upsert "CLOUD_GUARD_CONFIG_RECIPE_ID" "$CONFIG_RECIPE"
[[ -n "$THREAT_RECIPE" ]] && env_upsert "CLOUD_GUARD_THREAT_RECIPE_ID" "$THREAT_RECIPE"
log_ok "Configuration recipe: $CONFIG_RECIPE"
[[ -n "$THREAT_RECIPE" ]] && log_ok "Threat recipe:        $THREAT_RECIPE"

# Build the targetDetectorRecipes JSON array
if [[ -n "$THREAT_RECIPE" ]]; then
  recipes_payload=$(cat <<JSON
[
  {"detectorRecipeId":"$CONFIG_RECIPE"},
  {"detectorRecipeId":"$THREAT_RECIPE"}
]
JSON
)
else
  recipes_payload=$(cat <<JSON
[
  {"detectorRecipeId":"$CONFIG_RECIPE"}
]
JSON
)
fi

log "Step 4/5: ensure Cloud Guard target ($TARGET_NAME) on compartment $COMP"
TARGET_ID="$(env_get CLOUD_GUARD_TARGET_ID || true)"
if [[ -z "$TARGET_ID" ]]; then
  # Ref: oci cloud-guard target create
  out="$(oci_create_idempotent cloud-guard target create \
          --compartment-id "$COMP" \
          --display-name "$TARGET_NAME" \
          --target-resource-type COMPARTMENT \
          --target-resource-id "$COMP" \
          --target-detector-recipes "$recipes_payload" || true)"
  TARGET_ID="$(printf '%s' "$out" | jq -r '.data.id // empty' 2>/dev/null || true)"
  if [[ -z "$TARGET_ID" ]]; then
    TARGET_ID="$(oci_call cloud-guard target list \
                  --compartment-id "$COMP" --all 2>/dev/null \
                  | jq -r --arg n "$TARGET_NAME" \
                    '.data.items[]? | select(."display-name"==$n) | .id' | head -n1)"
  fi
  [[ -n "$TARGET_ID" ]] || die "Could not obtain Cloud Guard target OCID for $TARGET_NAME"
  env_upsert "CLOUD_GUARD_TARGET_ID" "$TARGET_ID"
fi
log_ok "Cloud Guard target OCID: $TARGET_ID"

# =============================================================================
#  Step 5/5: print next-actions footer
# =============================================================================
cat <<NEXT >&2

==============================================================================
  OCI Cloud Guard activation complete.
  All OCIDs are in $ENV_FILE (NEVER commit this file).
==============================================================================

NEXT ACTIONS (run in order):

  1. View open problems via the Console:
       https://cloud.oracle.com/cloud-guard/problems?region=$REGION

  2. List open problems in the platform compartment via CLI:
       oci --auth instance_principal --region $REGION \\
           cloud-guard problem list \\
           --compartment-id "$COMP" \\
           --lifecycle-state OPEN \\
           --query 'data.items[].{name:"problem-name",risk:"risk-level"}'

  3. Wire problem alerts into the existing notifications topic
     (NOTIFICATION_TOPIC_ID from .oci-devops.env):
       oci --auth instance_principal --region $REGION \\
           events rule create \\
           --compartment-id "$COMP" \\
           --display-name sovdefence-cloudguard-alerts \\
           --is-enabled true \\
           --condition '{"eventType":["com.oraclecloud.cloudguard.problemdetected"]}' \\
           --actions '{"actions":[{"actionType":"ONS","topicId":"<NOTIFICATION_TOPIC_ID>","isEnabled":true}]}'

  4. Once the platform is fully deployed and Cloud Guard problems have been
     triaged to zero (or accepted-as-risk), lock the compartment as a
     Security Zone using the Maximum Security Recipe:
       bash scripts/create-security-zone.sh

  5. Suppress a known false-positive (example: trusted public bucket in dev):
       oci --auth instance_principal --region $REGION \\
           cloud-guard problem update \\
           --problem-id <PROBLEM_OCID> \\
           --comment "Accepted risk - dev bucket, no PII" \\
           --lifecycle-detail RESOLVED

==============================================================================
NEXT

log_ok "Cloud Guard activation finished successfully"
