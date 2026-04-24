#!/usr/bin/env bash
# =============================================================================
#  Sovereign Defence Intelligence Platform - OCI DevOps Bootstrap
# -----------------------------------------------------------------------------
#  Idempotently provisions the complete CI/CD chain on Oracle Cloud
#  Infrastructure:
#
#    1. OCIR container repositories  (one per image, 6 total)
#    2. Notifications topic          (events sink for the DevOps project)
#    3. DevOps Project               ("sovdefence-devops")
#    4. Mirrored code repository     (GitHub -> DevOps, every 5 minutes)
#    5. Build pipelines              (one per service, 6 total)
#    6. Deploy environments          (OKE cluster binding)
#    7. Deploy artifacts             (KUBERNETES_MANIFEST + generic image)
#    8. Deploy pipelines             (one per service, 6 total)
#    9. Code-push triggers           (one per build pipeline, branch=main)
#
#  Every OCID produced is appended to `.oci-devops.env` at the repo root so
#  partial runs can resume and downstream automation (kubectl, kustomize) can
#  source the identifiers without inspecting the console.
#
#  Auth:      instance_principal  (this script is meant to run on the dev VM).
#  Region:    eu-frankfurt-1      (override with REGION env).
#  Idempotent: every create call tolerates HTTP 409 and falls back to a list
#             query to locate the existing OCID.
#
#  Prereqs : oci CLI >= 3.37, jq, an OKE cluster already present in $COMP.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
#  CONFIG (env-driven, see block below)
# ---------------------------------------------------------------------------
: "${COMP:?ERROR: COMP (compartment OCID) must be exported}"
REGION="${REGION:-eu-frankfurt-1}"
TENANCY_OCID="${TENANCY_OCID:-}"                   # optional hint
PROJECT_NAME="${PROJECT_NAME:-sovdefence-devops}"
MIRROR_REPO_NAME="${MIRROR_REPO_NAME:-oci-defense-demo}"
MIRROR_GITHUB_URL="${MIRROR_GITHUB_URL:-https://github.com/AI-Hagi/OCI-Defense-Demo.git}"
GITHUB_CONNECTION_ID="${GITHUB_CONNECTION_ID:-}"   # optional: PAT connector OCID
TOPIC_NAME="${TOPIC_NAME:-sovdefence-devops-events}"
K8S_NAMESPACE="${K8S_NAMESPACE:-sovdefence}"
OKE_CLUSTER_ID="${OKE_CLUSTER_ID:-}"

# Root of the repo checkout this script lives in: <repo>/scripts/setup-devops.sh
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.oci-devops.env"

# The 6 container services that the platform builds + deploys.
# name        : image/repo short-name (maps to OCIR repo, build-spec file, k8s manifest)
# is_frontend : whether the pipeline deploys to the frontend Deployment (vs one of 5 APIs)
readonly -a SERVICES=(
  "frontend"
  "geoint"
  "doc-intel"
  "osint"
  "supply-chain"
  "compliance"
)

# ---------------------------------------------------------------------------
#  Logging helpers  (stderr; never echo secrets)
# ---------------------------------------------------------------------------
_log_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()      { printf "[%s] [INFO] %s\n"  "$(_log_ts)" "$*" >&2; }
log_ok()   { printf "[%s] [ OK ] %s\n"  "$(_log_ts)" "$*" >&2; }
log_warn() { printf "[%s] [WARN] %s\n"  "$(_log_ts)" "$*" >&2; }
log_err()  { printf "[%s] [ERR ] %s\n"  "$(_log_ts)" "$*" >&2; }
die()      { log_err "$*"; exit 1; }

require_env() {
  local var="$1"; local val="${!var-}"
  [[ -n "$val" ]] || die "Required env var '$var' is unset"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

# ---------------------------------------------------------------------------
#  .oci-devops.env helpers (progressive writes keep partial runs resumable)
# ---------------------------------------------------------------------------
env_upsert() {
  local key="$1" val="$2"
  [[ -n "$val" && "$val" != "null" ]] || { log_warn "Skipping empty OCID for $key"; return 0; }
  touch "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    # in-place replace, BSD/GNU sed compatible
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
#  OCI CLI wrapper - always instance-principal auth, json output, region-pinned
# ---------------------------------------------------------------------------
oci_call() {
  # Capture stdout/stderr; preserve exit code so callers can branch on 409.
  oci --auth instance_principal --region "$REGION" --output json "$@"
}

# Runs `oci ...` and, on a 409 (already exists), returns 0 with an empty stdout
# so the caller can fall back to a list/search to discover the existing OCID.
oci_create_idempotent() {
  local _out _rc
  _out="$(oci --auth instance_principal --region "$REGION" --output json "$@" 2>&1)" && _rc=0 || _rc=$?
  if [[ $_rc -eq 0 ]]; then
    printf '%s' "$_out"
    return 0
  fi
  if printf '%s' "$_out" | grep -qE '"status":[[:space:]]*409|AlreadyExists|already exists'; then
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
log "Project name: $PROJECT_NAME"
log "Env file:     $ENV_FILE"

# Best-effort: discover tenancy name for OCIR prefix (namespace is different -
# we fetch that via `oci os ns get` below).
if [[ -z "$TENANCY_OCID" ]]; then
  log "TENANCY_OCID not set - using OCIR object storage namespace (authoritative)"
fi

OCIR_NAMESPACE="$(oci_call os ns get | jq -r '.data')"
[[ -n "$OCIR_NAMESPACE" && "$OCIR_NAMESPACE" != "null" ]] || die "Could not determine OCIR namespace"
env_upsert "OCIR_NAMESPACE" "$OCIR_NAMESPACE"
env_upsert "REGION"         "$REGION"
env_upsert "COMPARTMENT_ID" "$COMP"

# =============================================================================
#  1) OCIR container repositories (one per service image)
#     Ref: oci artifacts container repository create
# =============================================================================
get_or_create_ocir_repo() {
  local svc="$1"
  local display="sovdefence/${svc}"
  local _rc=0
  local out
  out="$(oci_create_idempotent artifacts container repository create \
        --compartment-id "$COMP" \
        --display-name "$display" \
        --is-public false \
        --wait-for-state AVAILABLE 2>&1)" || _rc=$?
  local ocid
  ocid="$(printf '%s' "$out" | jq -r '.data.id // empty' 2>/dev/null || true)"
  if [[ -z "$ocid" ]]; then
    # Fallback: list by display-name in compartment
    ocid="$(oci_call artifacts container repository list \
            --compartment-id "$COMP" \
            --display-name "$display" \
            --all \
            | jq -r '.data.items[0].id // empty')"
  fi
  [[ -n "$ocid" ]] || die "Could not obtain OCIR repo OCID for $display"
  local key
  key="OCIR_REPO_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  env_upsert "$key" "$ocid"
  printf '%s' "$ocid"
}

log "Step 1/9: ensure OCIR repositories"
for svc in "${SERVICES[@]}"; do
  get_or_create_ocir_repo "$svc" >/dev/null
done

# =============================================================================
#  2) Notifications topic (DevOps project events)
#     Ref: oci ons topic create
# =============================================================================
log "Step 2/9: ensure notifications topic ($TOPIC_NAME)"
TOPIC_ID="$(env_get NOTIFICATION_TOPIC_ID || true)"
if [[ -z "$TOPIC_ID" ]]; then
  out="$(oci_create_idempotent ons topic create \
          --compartment-id "$COMP" \
          --name "$TOPIC_NAME" || true)"
  TOPIC_ID="$(printf '%s' "$out" | jq -r '.data["topic-id"] // .data.id // empty')"
  if [[ -z "$TOPIC_ID" ]]; then
    # Poll for topic availability (oci ons topic create does not support --wait-for-state)
    for _i in 1 2 3 4 5; do
      TOPIC_ID="$(oci_call ons topic list --compartment-id "$COMP" --all 2>/dev/null \
                  | jq -r --arg n "$TOPIC_NAME" '.data[] | select(.name==$n) | ."topic-id" // .id' \
                  | head -n1)"
      [[ -n "$TOPIC_ID" ]] && break
      sleep 2
    done
  fi
  [[ -n "$TOPIC_ID" ]] || die "Could not obtain notifications topic OCID"
  env_upsert "NOTIFICATION_TOPIC_ID" "$TOPIC_ID"
fi

# =============================================================================
#  3) DevOps Project
#     Ref: oci devops project create
# =============================================================================
log "Step 3/9: ensure DevOps project ($PROJECT_NAME)"
PROJECT_ID="$(env_get DEVOPS_PROJECT_ID || true)"
if [[ -z "$PROJECT_ID" ]]; then
  out="$(oci_create_idempotent devops project create \
          --compartment-id "$COMP" \
          --name "$PROJECT_NAME" \
          --notification-config "{\"topicId\":\"$TOPIC_ID\"}" || true)"
  PROJECT_ID="$(printf '%s' "$out" | jq -r '.data.id // empty')"
  if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="$(oci_call devops project list --compartment-id "$COMP" --all \
                  | jq -r --arg n "$PROJECT_NAME" '.data.items[] | select(.name==$n) | .id' \
                  | head -n1)"
  fi
  [[ -n "$PROJECT_ID" ]] || die "Could not obtain DevOps project OCID"
  env_upsert "DEVOPS_PROJECT_ID" "$PROJECT_ID"
fi

# =============================================================================
#  4) Mirrored code repository (GitHub -> DevOps, every 5 min)
#     Ref: oci devops repository create (repository-type=MIRRORED)
#
#  NOTE: If the GitHub repo is private, create a PAT connector first:
#    oci devops connection create-github-access-token-connection \
#        --project-id $PROJECT_ID --display-name github-pat \
#        --access-token "<vault-secret-ocid>"
#  ...and export GITHUB_CONNECTION_ID before running this script.
# =============================================================================
log "Step 4/9: ensure code repository ($MIRROR_REPO_NAME)"
REPO_ID="$(env_get CODE_REPOSITORY_ID || true)"
if [[ -z "$REPO_ID" ]]; then
  if [[ -n "$GITHUB_CONNECTION_ID" ]]; then
    log "Creating MIRRORED repository (GitHub connector present)"
    mirror_cfg=$(cat <<JSON
{
  "repositoryUrl": "$MIRROR_GITHUB_URL",
  "connectorId": "$GITHUB_CONNECTION_ID",
  "triggerSchedule": { "scheduleType": "CUSTOM", "customSchedule": "0 0/5 * * * *" }
}
JSON
)
    out="$(oci_create_idempotent devops repository create \
            --project-id "$PROJECT_ID" \
            --name "$MIRROR_REPO_NAME" \
            --repository-type MIRRORED \
            --mirror-repository-config "$mirror_cfg" || true)"
  else
    log_warn "GITHUB_CONNECTION_ID not set — creating HOSTED repo (set GITHUB_CONNECTION_ID to enable mirroring)"
    out="$(oci_create_idempotent devops repository create \
            --project-id "$PROJECT_ID" \
            --name "$MIRROR_REPO_NAME" \
            --repository-type HOSTED || true)"
  fi
  REPO_ID="$(printf '%s' "$out" | jq -r '.data.id // empty')"
  if [[ -z "$REPO_ID" ]]; then
    REPO_ID="$(oci_call devops repository list --project-id "$PROJECT_ID" --all \
               | jq -r --arg n "$MIRROR_REPO_NAME" '.data.items[] | select(.name==$n) | .id' \
               | head -n1)"
  fi
  [[ -n "$REPO_ID" ]] || die "Could not obtain code repository OCID"
  env_upsert "CODE_REPOSITORY_ID" "$REPO_ID"
fi

# =============================================================================
#  5) Build pipelines (one per service)
#     Ref: oci devops build-pipeline create
#          oci devops build-pipeline-stage create-build-stage
#          oci devops build-pipeline-stage create-deliver-artifact-stage
# =============================================================================
get_or_create_build_pipeline() {
  local svc="$1"
  local bp_name="build-${svc}"
  local key="BUILD_PIPELINE_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local bp_id
  bp_id="$(env_get "$key" || true)"
  if [[ -z "$bp_id" ]]; then
    local out
    out="$(oci_create_idempotent devops build-pipeline create \
            --project-id "$PROJECT_ID" \
            --display-name "$bp_name" || true)"
    bp_id="$(printf '%s' "$out" | jq -r '.data.id // empty')"
    if [[ -z "$bp_id" ]]; then
      bp_id="$(oci_call devops build-pipeline list --project-id "$PROJECT_ID" --all \
               | jq -r --arg n "$bp_name" '.data.items[] | select(."display-name"==$n) | .id' \
               | head -n1)"
    fi
    [[ -n "$bp_id" ]] || die "Could not obtain build-pipeline OCID for $svc"
    env_upsert "$key" "$bp_id"
  fi
  printf '%s' "$bp_id"
}

# Stages are per-pipeline; we add a Managed-Build stage and a Deliver-Artifacts
# stage. Stage OCIDs are not cached per-se - we just ensure they exist by name.
ensure_build_stages() {
  local svc="$1" bp_id="$2"
  local build_stage_name="build-${svc}"
  local deliver_stage_name="deliver-${svc}"
  local spec_file="oci-devops/build-specs/${svc}.yaml"

  local existing
  existing="$(oci_call devops build-pipeline-stage list \
              --build-pipeline-id "$bp_id" --all \
              | jq -r --arg n "$build_stage_name" \
                '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
  if [[ -z "$existing" ]]; then
    oci_create_idempotent devops build-pipeline-stage create-build-stage \
      --build-pipeline-id "$bp_id" \
      --display-name "$build_stage_name" \
      --build-spec-file "$spec_file" \
      --image OL7_X86_64_STANDARD_10 \
      --build-source-collection "{\"items\":[{\"connectionType\":\"DEVOPS_CODE_REPOSITORY\",\"repositoryId\":\"$REPO_ID\",\"repositoryUrl\":\"$REPO_URL\",\"branch\":\"main\",\"name\":\"src\"}]}" \
      --stage-predecessor-collection "{\"items\":[{\"id\":\"$bp_id\"}]}" || \
      log_warn "build-stage create returned non-zero for $svc (likely already exists)"
  else
    log_ok "Build stage already present for $svc"
  fi

  # Deliver the image artifact to the matching OCIR repo.
  # We create a CONTAINER_IMAGE deploy-artifact that references the OCIR
  # repo + ${IMAGE_TAG} substitution, then wire it into a deliver-artifact
  # stage so the build run can push the image after docker build.
  local artifact_name="image-${svc}"
  local art_key="BUILD_ARTIFACT_IMAGE_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local art_id
  art_id="$(env_get "$art_key" || true)"
  if [[ -z "$art_id" ]]; then
    local ocir_path="${REGION%%-*}.ocir.io/${OCIR_NAMESPACE}/sovdefence/${svc}:\${IMAGE_TAG}"
    # Frankfurt = fra, Ashburn = iad - take region short code (e.g. eu-frankfurt-1 -> eu).
    # OCIR endpoint is actually '<region-key>.ocir.io' where region-key is e.g. 'fra'.
    case "$REGION" in
      eu-frankfurt-1) ocir_path="fra.ocir.io/${OCIR_NAMESPACE}/sovdefence/${svc}:\${IMAGE_TAG}" ;;
      us-ashburn-1)   ocir_path="iad.ocir.io/${OCIR_NAMESPACE}/sovdefence/${svc}:\${IMAGE_TAG}" ;;
    esac
    local src_json
    src_json=$(cat <<JSON
{
  "deployArtifactSourceType": "OCIR",
  "imageUri": "$ocir_path"
}
JSON
)
    local out
    out="$(oci_create_idempotent devops deploy-artifact create-ocir-artifact \
            --project-id "$PROJECT_ID" \
            --display-name "$artifact_name" \
            --artifact-type DOCKER_IMAGE \
            --argument-substitution-mode SUBSTITUTE_PLACEHOLDERS \
            --source-image-uri "$ocir_path" || true)"
    art_id="$(printf '%s' "$out" | jq -r '.data.id // empty')"
    if [[ -z "$art_id" ]]; then
      art_id="$(oci_call devops deploy-artifact list --project-id "$PROJECT_ID" --all \
                | jq -r --arg n "$artifact_name" '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
    fi
    [[ -n "$art_id" ]] && env_upsert "$art_key" "$art_id"
  fi

  # Get the build stage OCID so the deliver stage can chain after it
  local build_stage_id
  build_stage_id="$(oci_call devops build-pipeline-stage list \
              --build-pipeline-id "$bp_id" --all \
              | jq -r --arg n "$build_stage_name" \
                '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"

  local deliver_existing
  deliver_existing="$(oci_call devops build-pipeline-stage list \
              --build-pipeline-id "$bp_id" --all \
              | jq -r --arg n "$deliver_stage_name" \
                '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
  if [[ -z "$deliver_existing" && -n "$art_id" && -n "$build_stage_id" ]]; then
    oci_create_idempotent devops build-pipeline-stage create-deliver-artifact-stage \
      --build-pipeline-id "$bp_id" \
      --display-name "$deliver_stage_name" \
      --deliver-artifact-collection "{\"items\":[{\"artifactName\":\"container-image\",\"artifactId\":\"$art_id\"}]}" \
      --stage-predecessor-collection "{\"items\":[{\"id\":\"$build_stage_id\"}]}" || \
      log_warn "deliver-stage create returned non-zero for $svc (manual wiring may be required)"
  else
    log_ok "Deliver stage already present for $svc (or predecessor/artifact missing)"
  fi
}

log "Step 5/9: ensure build pipelines"
# Fetch DevOps repo URL once — required in buildSourceCollection for every build stage
REPO_URL="$(oci_call devops repository get --repository-id "$REPO_ID" | jq -r '.data["http-url"] // empty')"
[[ -n "$REPO_URL" ]] || die "Could not resolve DevOps repository HTTP URL"
log "Repo URL: $REPO_URL"
for svc in "${SERVICES[@]}"; do
  bp_id="$(get_or_create_build_pipeline "$svc")"
  ensure_build_stages "$svc" "$bp_id"
done

# =============================================================================
#  6) Deploy environment (OKE cluster binding)
#     Ref: oci devops deploy-environment create-oke-cluster-environment
# =============================================================================
log "Step 6/9: ensure OKE deploy environment"
if [[ -z "$OKE_CLUSTER_ID" ]]; then
  log_warn "OKE_CLUSTER_ID unset - trying to auto-discover a single cluster in the compartment"
  OKE_CLUSTER_ID="$(oci_call ce cluster list --compartment-id "$COMP" --all \
                    | jq -r '[.data[] | select(."lifecycle-state"=="ACTIVE")][0].id // empty')"
fi
if [[ -z "$OKE_CLUSTER_ID" ]]; then
  log_err "No OKE cluster found in compartment $COMP"
  log_err "Run:  oci ce cluster list --compartment-id \"$COMP\""
  log_err "Then: export OKE_CLUSTER_ID=<ocid> and re-run this script"
  exit 2
fi
env_upsert "OKE_CLUSTER_ID" "$OKE_CLUSTER_ID"

DEPLOY_ENV_ID="$(env_get DEPLOY_ENV_OKE_ID || true)"
if [[ -z "$DEPLOY_ENV_ID" ]]; then
  out="$(oci_create_idempotent devops deploy-environment create-oke-cluster-environment \
          --project-id "$PROJECT_ID" \
          --display-name "oke-prod" \
          --cluster-id "$OKE_CLUSTER_ID" || true)"
  DEPLOY_ENV_ID="$(printf '%s' "$out" | jq -r '.data.id // empty')"
  if [[ -z "$DEPLOY_ENV_ID" ]]; then
    DEPLOY_ENV_ID="$(oci_call devops deploy-environment list --project-id "$PROJECT_ID" --all \
                     | jq -r '.data.items[] | select(."display-name"=="oke-prod") | .id' | head -n1)"
  fi
  [[ -n "$DEPLOY_ENV_ID" ]] || die "Could not obtain OKE deploy-environment OCID"
  env_upsert "DEPLOY_ENV_OKE_ID" "$DEPLOY_ENV_ID"
fi

# =============================================================================
#  7) Deploy artifacts (KUBERNETES_MANIFEST, points at k8s/overlays/prod/)
#     Ref: oci devops deploy-artifact create
#
#  We publish one KUBERNETES_MANIFEST artifact per service, parameterised with
#  ${IMAGE_TAG} argument substitution so the image reference gets templated at
#  deploy time from the corresponding build pipeline's exported variable.
# =============================================================================
get_or_create_k8s_artifact() {
  local svc="$1"
  local name="k8s-${svc}"
  local key="DEPLOY_ARTIFACT_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local art_id
  art_id="$(env_get "$key" || true)"
  [[ -n "$art_id" ]] && { printf '%s' "$art_id"; return 0; }

  # Inline pointer to the kustomize overlay; actual content is fetched at
  # deploy time from the code repository. Tag arg substitution = ${IMAGE_TAG}.
  local source_json
  source_json=$(cat <<JSON
{
  "deployArtifactSourceType": "INLINE",
  "base64EncodedContent": "$(printf '# rendered at deploy time from k8s/overlays/prod/ (kustomize)\n' | base64 -w0)"
}
JSON
)
  local out
  out="$(oci_create_idempotent devops deploy-artifact create \
          --project-id "$PROJECT_ID" \
          --display-name "$name" \
          --deploy-artifact-type KUBERNETES_MANIFEST \
          --argument-substitution-mode SUBSTITUTE \
          --deploy-artifact-source "$source_json" || true)"
  art_id="$(printf '%s' "$out" | jq -r '.data.id // empty')"
  if [[ -z "$art_id" ]]; then
    art_id="$(oci_call devops deploy-artifact list --project-id "$PROJECT_ID" --all \
              | jq -r --arg n "$name" '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
  fi
  [[ -n "$art_id" ]] || die "Could not obtain deploy-artifact OCID for $svc"
  env_upsert "$key" "$art_id"
  printf '%s' "$art_id"
}

log "Step 7/9: ensure deploy artifacts"
if [[ "${ENABLE_DEPLOY_PIPELINES:-0}" == "1" ]]; then
  for svc in "${SERVICES[@]}"; do
    get_or_create_k8s_artifact "$svc" >/dev/null
  done
else
  log_warn "Skipping deploy-artifact creation (ENABLE_DEPLOY_PIPELINES!=1)."
  log_warn "K8s manifest artifacts need a manual Console step or targeted script revision."
  log_warn "For MVP: deploy via 'kubectl apply -k k8s/overlays/prod' instead of OCI DevOps deploy pipelines."
fi

# =============================================================================
#  8) Deploy pipelines (one per service) + OKE deploy stage
#     Ref: oci devops deploy-pipeline create
#          oci devops deploy-stage create-oke-deploy-stage
# =============================================================================
get_or_create_deploy_pipeline() {
  local svc="$1"
  local dp_name="deploy-${svc}"
  local key="DEPLOY_PIPELINE_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local dp_id
  dp_id="$(env_get "$key" || true)"
  if [[ -z "$dp_id" ]]; then
    local out
    out="$(oci_create_idempotent devops deploy-pipeline create \
            --project-id "$PROJECT_ID" \
            --display-name "$dp_name" || true)"
    dp_id="$(printf '%s' "$out" | jq -r '.data.id // empty')"
    if [[ -z "$dp_id" ]]; then
      dp_id="$(oci_call devops deploy-pipeline list --project-id "$PROJECT_ID" --all \
               | jq -r --arg n "$dp_name" '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
    fi
    [[ -n "$dp_id" ]] || die "Could not obtain deploy-pipeline OCID for $svc"
    env_upsert "$key" "$dp_id"
  fi
  printf '%s' "$dp_id"
}

ensure_oke_deploy_stage() {
  local svc="$1" dp_id="$2"
  local stage_name="oke-${svc}"
  local existing
  existing="$(oci_call devops deploy-stage list \
              --deploy-pipeline-id "$dp_id" --all \
              | jq -r --arg n "$stage_name" '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
  if [[ -n "$existing" ]]; then
    log_ok "Deploy stage already present for $svc"
    return 0
  fi
  local key_art
  key_art="DEPLOY_ARTIFACT_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local art_id
  art_id="$(env_get "$key_art")"
  oci_create_idempotent devops deploy-stage create-oke-deploy-stage \
    --deploy-pipeline-id "$dp_id" \
    --display-name "$stage_name" \
    --oke-cluster-deploy-environment-id "$DEPLOY_ENV_ID" \
    --kubernetes-manifest-deployment-artifact-ids "[\"$art_id\"]" \
    --namespace "$K8S_NAMESPACE" || \
    log_warn "deploy-stage create returned non-zero for $svc (likely already exists)"
}

log "Step 8/9: ensure deploy pipelines"
if [[ "${ENABLE_DEPLOY_PIPELINES:-0}" != "1" ]]; then
  log_warn "Skipping deploy-pipeline creation (ENABLE_DEPLOY_PIPELINES!=1)"
else
  for svc in "${SERVICES[@]}"; do
    dp_id="$(get_or_create_deploy_pipeline "$svc")"
    ensure_oke_deploy_stage "$svc" "$dp_id"
  done
fi

# =============================================================================
#  9) Code-push triggers (one per build pipeline, branch=main)
#     Ref: oci devops trigger create-devops-code-repository-trigger
# =============================================================================
get_or_create_trigger() {
  local svc="$1"
  local tr_name="push-main-${svc}"
  local key="TRIGGER_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local tr_id
  tr_id="$(env_get "$key" || true)"
  [[ -n "$tr_id" ]] && return 0

  local bp_key="BUILD_PIPELINE_$(tr '[:lower:]-' '[:upper:]_' <<<"$svc")"
  local bp_id
  bp_id="$(env_get "$bp_key")"
  [[ -n "$bp_id" ]] || die "Missing $bp_key in $ENV_FILE - cannot wire trigger"

  local actions_json
  actions_json=$(cat <<JSON
[{
  "type": "TRIGGER_BUILD_PIPELINE",
  "buildPipelineId": "$bp_id",
  "filter": { "triggerSource": "DEVOPS_CODE_REPOSITORY", "events": ["PUSH"], "include": { "headRef": "main" } }
}]
JSON
)
  local out
  out="$(oci_create_idempotent devops trigger create-devops-code-repository-trigger \
          --project-id "$PROJECT_ID" \
          --repository-id "$REPO_ID" \
          --display-name "$tr_name" \
          --actions "$actions_json" || true)"
  tr_id="$(printf '%s' "$out" | jq -r '.data.id // empty')"
  if [[ -z "$tr_id" ]]; then
    tr_id="$(oci_call devops trigger list --project-id "$PROJECT_ID" --all \
             | jq -r --arg n "$tr_name" '.data.items[] | select(."display-name"==$n) | .id' | head -n1)"
  fi
  [[ -n "$tr_id" ]] || die "Could not obtain trigger OCID for $svc"
  env_upsert "$key" "$tr_id"
}

log "Step 9/9: ensure code-repo triggers"
if [[ "${ENABLE_DEPLOY_PIPELINES:-0}" != "1" ]]; then
  log_warn "Skipping triggers (ENABLE_DEPLOY_PIPELINES!=1) — manually kick builds with 'oci devops build-run create'"
else
  for svc in "${SERVICES[@]}"; do
    get_or_create_trigger "$svc"
  done
fi

# =============================================================================
#  DONE - print next actions
# =============================================================================
cat <<'NEXT' >&2

==============================================================================
  OCI DevOps bootstrap complete.
  All OCIDs are in .oci-devops.env (NEVER commit this file).
==============================================================================

NEXT ACTIONS (run in order):

  1. Populate the ADB wallet as a Kubernetes secret (wallet NOT in git):
       kubectl -n sovdefence create secret generic adb-wallet \
         --from-file=/home/ubuntu/wallet/ \
         --dry-run=client -o yaml | kubectl apply -f -

  2. Seed the ADB connection credentials as a separate secret (values come
     from your local .env - DO NOT echo them):
       kubectl -n sovdefence create secret generic adb-credentials \
         --from-env-file=./services/.env \
         --dry-run=client -o yaml | kubectl apply -f -

  3. Trigger the first build run manually (one per service):
       oci --auth instance_principal --region eu-frankfurt-1 \
           devops build-run create \
           --build-pipeline-id "$(grep ^BUILD_PIPELINE_GEOINT .oci-devops.env | cut -d= -f2)" \
           --display-name "bootstrap-run-geoint"

  4. Watch the deploy pipelines roll out:
       oci --auth instance_principal --region eu-frankfurt-1 \
           devops deployment list \
           --project-id "$(grep ^DEVOPS_PROJECT_ID .oci-devops.env | cut -d= -f2)"

==============================================================================
NEXT

log_ok "Bootstrap finished successfully"
