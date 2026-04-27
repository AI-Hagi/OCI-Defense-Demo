# OCI Vault — IAM policy for sovdefence Workload Identity

Two policies are needed before the OKE-side `oci-vault-store`
SecretStore + ExternalSecret resources work end-to-end. Both are
created **once** at the tenancy level; neither hits the cluster.

## 1. Vault provisioning (Crossplane managed-node)

Crossplane runs on the managed node pool and uses the API-Key auth
already configured in `crossplane/auth-setup.md`. The same API-Key
identity provisions the Vault + master key + secret entries via
the composition in `crossplane/vault/composition.yaml`.

Required statement:

```
Allow group sovdef-crossplane-admins to manage vaults in compartment oci-defence-demo
Allow group sovdef-crossplane-admins to manage keys in compartment oci-defence-demo
Allow group sovdef-crossplane-admins to manage secret-family in compartment oci-defence-demo
```

`sovdef-crossplane-admins` is the IAM group that owns the API key
already in use. Adjust the group name to match your tenancy.

## 2. Read-from-Vault (OKE Workload Identity)

The pods reach OCI Vault using the existing
`sovdefence-runtime` ServiceAccount
(`k8s/base/serviceaccount-workload-identity.yaml`). No second SA
is required — ESO and the application share the identity.

Required statement:

```
Allow any-user to read secret-family in compartment oci-defence-demo
  where all {
    request.principal.type='workload',
    request.principal.namespace='sovdefence',
    request.principal.service_account='sovdefence-runtime'
  }
Allow any-user to read vaults in compartment oci-defence-demo
  where all {
    request.principal.type='workload',
    request.principal.namespace='sovdefence',
    request.principal.service_account='sovdefence-runtime'
  }
```

The `read` verb is sufficient — ESO never writes Vault entries
back; rotations happen out-of-band via `oci vault secret …`
or the OCI Console.

## Vault entries provisioned by Crossplane

| Vault key | Used by | Refresh |
|---|---|---|
| `adb-admin-password` | `externalsecret-adb` → `adb-credentials` | 5m |
| `adb-wallet-password` | `externalsecret-adb` → `adb-credentials` | 5m |
| `ocir-auth-token` | `externalsecret-ocir` → `ocir-secret` | 1h |
| `ocir-username` | `externalsecret-ocir` → `ocir-secret` | 1h |

Bootstrap from current K8s Secret content (one-time):

```bash
# From a host with kubectl + oci CLI access.
NS=sovdefence
ADMIN_PW=$(kubectl -n $NS get secret adb-credentials -o jsonpath='{.data.ORACLE_PASSWORD}' | base64 -d)
WALLET_PW=$(kubectl -n $NS get secret adb-credentials -o jsonpath='{.data.WALLET_PASSWORD}' | base64 -d)
OCIR_TOKEN=$(kubectl -n $NS get secret ocir-secret -o jsonpath='{.data.\.dockerconfigjson}' \
    | base64 -d | jq -r '.auths."fra.ocir.io".password')
OCIR_USER=$(kubectl -n $NS get secret ocir-secret -o jsonpath='{.data.\.dockerconfigjson}' \
    | base64 -d | jq -r '.auths."fra.ocir.io".username')

VAULT_OCID=ocid1.vault.oc1.eu-frankfurt-1.<…>
KEY_OCID=ocid1.key.oc1.eu-frankfurt-1.<…>

for pair in "adb-admin-password:$ADMIN_PW" \
            "adb-wallet-password:$WALLET_PW" \
            "ocir-auth-token:$OCIR_TOKEN" \
            "ocir-username:$OCIR_USER"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  oci vault secret create-base64 \
      --secret-name "$name" \
      --vault-id "$VAULT_OCID" \
      --key-id "$KEY_OCID" \
      --secret-content-content "$(echo -n "$value" | base64)"
done
```

Once provisioned, ESO will sync the K8s Secrets automatically
within the configured refresh interval.
