#!/usr/bin/env bash
# =============================================================================
#  Sovereign Defence — OCI Vault + External Secrets Operator bootstrap
# -----------------------------------------------------------------------------
#  Idempotent helper that:
#    1. Installs External Secrets Operator (ESO) into the cluster.
#    2. Applies the Crossplane Vault composition (Vault + master key).
#    3. Bootstraps the four Vault entries from the existing K8s Secrets.
#    4. Patches k8s/base/external-secrets/secretstore-oci-vault.yaml with the
#       provisioned Vault OCID.
#    5. Applies the SecretStore + ExternalSecrets and force-syncs them.
#
#  Pre-reqs:
#    * Cloud Shell (or any host with kubectl access to the OKE API).
#    * `oci` CLI authenticated against the platform compartment.
#    * `helm`, `jq`, `yq` available on PATH.
#    * `crossplane/auth-setup.md` already applied (provider working).
#
#  Run:
#    bash scripts/setup-vault.sh
#
#  Re-run-safe: each step probes for prior state.
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

REGION="${REGION:-eu-frankfurt-1}"
COMPARTMENT_ID="${COMPARTMENT_ID:-ocid1.compartment.oc1..aaaaaaaamcjaobwgnwwwkaphfzuzavq2dez6jkonahdwsn6ys7apqgiqelmq}"
NS="${NS:-sovdefence}"
ESO_NS="${ESO_NS:-external-secrets}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()    { printf "[%s] [INFO] %s\n" "$(ts)" "$*"; }
log_ok() { printf "[%s] [ OK ] %s\n" "$(ts)" "$*"; }
log_err(){ printf "[%s] [ERR ] %s\n" "$(ts)" "$*" >&2; }

# -----------------------------------------------------------------------------
# 1. Install ESO via Helm.
# -----------------------------------------------------------------------------
log "1/5 install External Secrets Operator"
if ! kubectl get ns "$ESO_NS" >/dev/null 2>&1; then
    kubectl create ns "$ESO_NS"
fi
helm repo add external-secrets https://charts.external-secrets.io >/dev/null 2>&1 || true
helm repo update >/dev/null
if ! helm -n "$ESO_NS" status external-secrets >/dev/null 2>&1; then
    helm -n "$ESO_NS" install external-secrets external-secrets/external-secrets \
        --set installCRDs=true \
        --wait --timeout 5m
    log_ok "ESO installed"
else
    log_ok "ESO already installed (skipped)"
fi

# -----------------------------------------------------------------------------
# 2. Provision the Vault + master key.
# -----------------------------------------------------------------------------
# Two paths:
#   A) Crossplane provider-oci-kms is installed → apply composition + wait.
#   B) Provider not installed → fall back to expecting pre-provisioned OCIDs
#      via VAULT_OCID + KEY_OCID env vars (created with `oci kms vault …`).
#      A short crash-course is in crossplane/vault/iam.md.
log "2/5 provision Vault + master key"

if [[ -n "${VAULT_OCID:-}" && -n "${KEY_OCID:-}" ]]; then
    log_ok "using pre-provisioned VAULT_OCID + KEY_OCID from env"
elif kubectl api-resources | grep -q "^vault.*kms.oci.upbound.io"; then
    log "provider-oci-kms detected — applying Crossplane composition"
    kubectl apply -f "$REPO_ROOT/crossplane/vault/composition.yaml"
    kubectl wait --for=condition=Ready vault.kms.oci.upbound.io/sovdefence-vault --timeout=300s
    kubectl wait --for=condition=Ready key.kms.oci.upbound.io/sovdefence-vault-key --timeout=300s
    VAULT_OCID="$(kubectl get vault.kms.oci.upbound.io/sovdefence-vault \
        -o jsonpath='{.status.atProvider.id}')"
    KEY_OCID="$(kubectl get key.kms.oci.upbound.io/sovdefence-vault-key \
        -o jsonpath='{.status.atProvider.id}')"
else
    log_err "Crossplane KMS provider not installed and VAULT_OCID/KEY_OCID not set."
    log_err "Provision once with the OCI CLI, then re-run with both OCIDs exported:"
    log_err ""
    log_err "  oci kms vault create --compartment-id \"\$COMPARTMENT_ID\" \\"
    log_err "      --display-name sovdefence-vault --vault-type DEFAULT \\"
    log_err "      --query 'data.id' --raw-output"
    log_err ""
    log_err "  oci kms management key create --compartment-id \"\$COMPARTMENT_ID\" \\"
    log_err "      --display-name sovdefence-vault-key \\"
    log_err "      --key-shape '{\"algorithm\":\"AES\",\"length\":32}' \\"
    log_err "      --protection-mode SOFTWARE \\"
    log_err "      --endpoint \"\$VAULT_MANAGEMENT_ENDPOINT\" \\"
    log_err "      --query 'data.id' --raw-output"
    log_err ""
    log_err "Then: VAULT_OCID=… KEY_OCID=… bash scripts/setup-vault.sh"
    exit 1
fi
log_ok "VAULT_OCID=$VAULT_OCID"
log_ok "KEY_OCID=$KEY_OCID"

# -----------------------------------------------------------------------------
# 3. Bootstrap Vault entries from the current K8s Secrets.
# -----------------------------------------------------------------------------
log "3/5 bootstrap Vault entries from K8s Secrets"
ADMIN_PW=$(kubectl -n "$NS" get secret adb-credentials -o jsonpath='{.data.ORACLE_PASSWORD}' | base64 -d)
WALLET_PW=$(kubectl -n "$NS" get secret adb-credentials -o jsonpath='{.data.WALLET_PASSWORD}' | base64 -d)
OCIR_TOKEN=$(kubectl -n "$NS" get secret ocir-secret -o jsonpath='{.data.\.dockerconfigjson}' \
    | base64 -d | jq -r '.auths."fra.ocir.io".password')
OCIR_USER=$(kubectl -n "$NS" get secret ocir-secret -o jsonpath='{.data.\.dockerconfigjson}' \
    | base64 -d | jq -r '.auths."fra.ocir.io".username')

create_or_update_secret() {
    local name="$1"
    local value="$2"
    local existing
    existing="$(oci vault secret list \
        --compartment-id "$COMPARTMENT_ID" \
        --vault-id "$VAULT_OCID" \
        --query "data[?\"secret-name\"=='$name'].id | [0]" \
        --raw-output 2>/dev/null || true)"
    local b64; b64="$(printf '%s' "$value" | base64 -w0)"
    if [[ -n "$existing" && "$existing" != "null" ]]; then
        oci vault secret update-base64 \
            --secret-id "$existing" \
            --secret-content-content "$b64" >/dev/null
        log_ok "  updated $name"
    else
        oci vault secret create-base64 \
            --compartment-id "$COMPARTMENT_ID" \
            --secret-name "$name" \
            --vault-id "$VAULT_OCID" \
            --key-id "$KEY_OCID" \
            --secret-content-content "$b64" >/dev/null
        log_ok "  created $name"
    fi
}

create_or_update_secret "adb-admin-password" "$ADMIN_PW"
create_or_update_secret "adb-wallet-password" "$WALLET_PW"
create_or_update_secret "ocir-auth-token" "$OCIR_TOKEN"
create_or_update_secret "ocir-username" "$OCIR_USER"

# -----------------------------------------------------------------------------
# 4. Patch SecretStore manifest with the live Vault OCID.
# -----------------------------------------------------------------------------
log "4/5 patch SecretStore manifest"
SS_FILE="$REPO_ROOT/k8s/base/external-secrets/secretstore-oci-vault.yaml"
if grep -q "<TENANCY-VAULT-OCID>" "$SS_FILE"; then
    sed -i.bak "s|ocid1.vault.oc1.eu-frankfurt-1.<TENANCY-VAULT-OCID>|$VAULT_OCID|" "$SS_FILE"
    log_ok "patched $SS_FILE"
else
    log_ok "$SS_FILE already pinned"
fi

# -----------------------------------------------------------------------------
# 5. Apply ESO manifests + force a refresh.
# -----------------------------------------------------------------------------
log "5/5 apply ESO manifests + force refresh"
kubectl apply -k "$REPO_ROOT/k8s/base/external-secrets"

# Force the new Secrets to materialise immediately.
for es in adb-credentials ocir-secret; do
    kubectl -n "$NS" annotate externalsecret "$es" \
        "force-sync=$(date +%s)" --overwrite
done

log "waiting for ExternalSecret Ready=True (≤2m)…"
kubectl -n "$NS" wait --for=condition=Ready externalsecret/adb-credentials \
    --timeout=120s
kubectl -n "$NS" wait --for=condition=Ready externalsecret/ocir-secret \
    --timeout=120s
log_ok "ExternalSecrets Ready"

log "rolling backend deployments to pick up refreshed Secrets"
for d in geoint doc-intel osint supply-chain compliance; do
    kubectl -n "$NS" rollout restart "deploy/$d" || true
done

log_ok "setup-vault.sh done"
log "Next: rotate the ADB ADMIN password in OCI Vault and watch ESO sync within 5 min."
