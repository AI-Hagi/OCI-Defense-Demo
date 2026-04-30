#!/usr/bin/env bash
# =============================================================================
#  Sovereign Defence Intelligence Platform - OCI DevOps Teardown
# -----------------------------------------------------------------------------
#  Reads .oci-devops.env (produced by setup-devops.sh) and deletes every
#  resource in the REVERSE of creation order:
#
#    triggers -> deploy pipelines -> deploy artifacts -> deploy environment
#             -> build pipelines  -> mirrored repository -> DevOps project
#             -> notifications topic -> OCIR container repositories
#
#  Each delete is best-effort; a missing OCID is warned-then-skipped.
#  Never echoes secrets. Same auth pattern as setup-devops.sh.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

REGION="${REGION:-eu-frankfurt-1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.oci-devops.env"

[[ -f "$ENV_FILE" ]] || { echo "[ERR ] $ENV_FILE not found - nothing to tear down" >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"

log()      { printf "[%s] [INFO] %s\n"  "$(date -u +%FT%TZ)" "$*" >&2; }
log_ok()   { printf "[%s] [ OK ] %s\n"  "$(date -u +%FT%TZ)" "$*" >&2; }
log_warn() { printf "[%s] [WARN] %s\n"  "$(date -u +%FT%TZ)" "$*" >&2; }

readonly -a SERVICES=("frontend" "geoint" "doc-intel" "osint" "supply-chain" "compliance")

oci_call() { oci --auth instance_principal --region "$REGION" --output json "$@"; }

try_delete() {
  # $1=description $2=command...
  local desc="$1"; shift
  local id="${1:-}"
  [[ -n "$id" && "$id" != "null" ]] || { log_warn "$desc: OCID empty, skipping"; return 0; }
  shift
  if "$@" "$id" --force --wait-for-state DELETED >/dev/null 2>&1; then
    log_ok "$desc deleted"
  else
    log_warn "$desc delete failed or already gone"
  fi
}

# --- CONFIRMATION -----------------------------------------------------------
echo "About to DELETE the OCI DevOps chain defined in $ENV_FILE"
echo "Project: ${DEVOPS_PROJECT_ID:-<unset>}"
read -r -p "Type 'TEARDOWN' to continue: " _confirm
[[ "$_confirm" == "TEARDOWN" ]] || { log_warn "Aborted"; exit 0; }

# --- 9) TRIGGERS ------------------------------------------------------------
log "Removing triggers"
for svc in "${SERVICES[@]}"; do
  key="TRIGGER_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  try_delete "trigger $svc" "${!key:-}" oci_call devops trigger delete --trigger-id
done

# --- 8) DEPLOY PIPELINES ----------------------------------------------------
log "Removing deploy pipelines"
for svc in "${SERVICES[@]}"; do
  key="DEPLOY_PIPELINE_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  try_delete "deploy-pipeline $svc" "${!key:-}" oci_call devops deploy-pipeline delete --deploy-pipeline-id
done

# --- 7) DEPLOY ARTIFACTS ----------------------------------------------------
log "Removing deploy artifacts"
for svc in "${SERVICES[@]}"; do
  key="DEPLOY_ARTIFACT_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  try_delete "deploy-artifact $svc" "${!key:-}" oci_call devops deploy-artifact delete --deploy-artifact-id
done

# --- 6) DEPLOY ENVIRONMENT --------------------------------------------------
log "Removing OKE deploy environment"
try_delete "deploy-environment oke-prod" "${DEPLOY_ENV_OKE_ID:-}" \
    oci_call devops deploy-environment delete --deploy-environment-id

# --- 5) BUILD PIPELINES -----------------------------------------------------
log "Removing build pipelines"
for svc in "${SERVICES[@]}"; do
  key="BUILD_PIPELINE_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  try_delete "build-pipeline $svc" "${!key:-}" oci_call devops build-pipeline delete --build-pipeline-id
done

# --- 4) MIRRORED REPO -------------------------------------------------------
log "Removing mirrored code repository"
try_delete "code-repository" "${CODE_REPOSITORY_ID:-}" \
    oci_call devops repository delete --repository-id

# --- 3) PROJECT -------------------------------------------------------------
log "Removing DevOps project"
try_delete "devops-project" "${DEVOPS_PROJECT_ID:-}" \
    oci_call devops project delete --project-id

# --- 2) NOTIFICATIONS TOPIC -------------------------------------------------
log "Removing notifications topic"
if [[ -n "${NOTIFICATION_TOPIC_ID:-}" ]]; then
  oci_call ons topic delete --topic-id "$NOTIFICATION_TOPIC_ID" --force >/dev/null 2>&1 \
    && log_ok "notifications topic deleted" \
    || log_warn "notifications topic delete failed or already gone"
fi

# --- 1) OCIR REPOSITORIES ---------------------------------------------------
log "Removing OCIR container repositories"
for svc in "${SERVICES[@]}"; do
  key="OCIR_REPO_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  id="${!key:-}"
  [[ -n "$id" ]] || { log_warn "ocir $svc: empty, skip"; continue; }
  if oci_call artifacts container repository delete \
       --repository-id "$id" --force >/dev/null 2>&1; then
    log_ok "ocir $svc deleted"
  else
    log_warn "ocir $svc delete failed or already gone"
  fi
done

log_ok "Teardown complete. $ENV_FILE left intact for audit - delete manually if desired."
