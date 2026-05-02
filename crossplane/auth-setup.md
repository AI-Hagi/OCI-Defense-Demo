# Crossplane on OKE — OCI Authentication Setup

Step-by-step for wiring the **Upbound OCI provider family** (v0.1.6) to a real
OCI tenancy on an OKE cluster that uses **virtual nodes** for application
workloads and a small **managed node pool** for system components.

## TL;DR

Virtual nodes can run the Upbound OCI provider Pods, but **cannot** run
Crossplane core (init containers are not supported). The provider also
**cannot** use Instance Principal auth on virtual nodes (no IMDS) and v0.1.6
silently ignores `auth: InstancePrincipal` even when pinned to managed
nodes — so we use **API Key auth** with credentials stored in a K8s Secret.

```
┌──────────────────────────────────────────────────────────────────────┐
│ OKE cluster (sovdefence-cluster)                                     │
│                                                                      │
│  ┌──────────────────────────────────┐   ┌────────────────────────┐  │
│  │ Virtual nodes (3)                │   │ Managed node (1)       │  │
│  │ • frontend, geoint, doc-intel,   │   │ role=system            │  │
│  │   osint, supply-chain, compliance│   │ • Crossplane core      │  │
│  │ • OCI Native Ingress Controller  │   │ • crossplane-rbac-mgr  │  │
│  │ • Upbound provider Pods          │◄──┤ • Pinned via           │  │
│  │   (work fine here)               │   │   DeploymentRuntimeCfg │  │
│  └──────────────────────────────────┘   └────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

## Limitations encountered (and why we chose API Key)

| Auth mode | Supported in v0.1.6? | Why we didn't use it |
|---|---|---|
| `InjectedIdentity` (workload identity) | **No** | `no extraction handler registered for source: InjectedIdentity` — the credential extractor was added in newer provider versions. |
| `InstancePrincipal` | **No, in practice** | The `auth: InstancePrincipal` key in the Secret JSON is silently dropped; provider falls through to API Key code path and errors with `did not find a proper configuration for private key`. |
| `ApiKey` | **Yes** ✅ | What this doc sets up. |

Future upgrade path: when Upbound publishes a newer `provider-family-oci`
that wires `InjectedIdentity` properly, switch by replacing the Secret with
a ServiceAccount + IAM policy and dropping API Key state.

## Prereqs

- An OKE cluster with the Crossplane Helm chart installed in
  `crossplane-system`. See `crossplane/base/provider.yaml` for the
  Provider CRs and `crossplane/providerconfig/runtimeconfig.yaml` for
  the DeploymentRuntimeConfig pinning Crossplane core to the managed
  node pool.
- `kubectl` context pointing at the cluster (use OCI Cloud Shell —
  the dev VM cannot reach the OKE API endpoint without a VCN egress
  rule for TCP 6443).
- `openssl`, `jq` (both pre-installed in Cloud Shell).

## Step 1 — Generate an RSA key pair (in Cloud Shell)

```bash
mkdir -p ~/.oci-crossplane && cd ~/.oci-crossplane
openssl genrsa -out crossplane.pem 2048
chmod 600 crossplane.pem
openssl rsa -in crossplane.pem -pubout > crossplane_public.pem
cat crossplane_public.pem
```

Copy the `-----BEGIN PUBLIC KEY-----` block.

## Step 2 — Upload the public key to OCI Console

1. Click profile (top-right) → **User Settings**
2. Left panel → **API Keys** → **Add API Key**
3. Select **Paste Public Key**, paste the block from Step 1, click **Add**
4. Copy the resulting **Configuration File Preview**:
   ```
   [DEFAULT]
   user=ocid1.user.oc1..aaaaaaaa...        ← USER_OCID
   fingerprint=xx:xx:xx:xx:...             ← FINGERPRINT
   tenancy=ocid1.tenancy.oc1..aaaaaaaa...  ← TENANCY_OCID
   region=eu-frankfurt-1
   ```

> Note: Cloud Shell's OpenSSL has FIPS enabled and rejects `openssl md5`,
> so we **let the Console compute the fingerprint** rather than computing
> it locally.

## Step 3 — IAM policy for the API key user

The user account whose API key we just registered needs permission to
manage database resources. If the user is already an **Administrator**
of the tenancy, skip this step.

Otherwise, create a policy in the root compartment:

```bash
oci iam policy create \
  --compartment-id <TENANCY_OCID> \
  --name crossplane-oci-user-policy \
  --description "Crossplane API key user permissions" \
  --statements '[
    "Allow group <crossplane-users> to manage database-family in compartment oci-defence-demo",
    "Allow group <crossplane-users> to use virtual-network-family in compartment oci-defence-demo"
  ]'
```

(The `sovdefence-crossplane-oci-policy` we created earlier was for the
*workload identity* path that turned out not to work with v0.1.6 —
it's harmless to keep but currently unused.)

## Step 4 — Build the credentials JSON

```bash
jq -n --rawfile k ~/.oci-crossplane/crossplane.pem '{
  auth: "ApiKey",
  tenancy_ocid: "ocid1.tenancy.oc1..aaaaaaaa...",
  user_ocid:    "ocid1.user.oc1..aaaaaaaa...",
  fingerprint:  "xx:xx:xx:xx:...",
  region:       "eu-frankfurt-1",
  private_key:  $k
}' > /tmp/oci-creds.json
```

This produces a single JSON document with the private key inlined as a
multi-line string (jq's `--rawfile` handles the escaping). Output is
mode `0644` in `/tmp` — fine for transient use, but **delete it** once
the Secret is created.

## Step 5 — Create the K8s Secret

```bash
kubectl -n crossplane-system delete secret oci-creds --ignore-not-found
kubectl -n crossplane-system create secret generic oci-creds \
  --from-file=credentials=/tmp/oci-creds.json
rm /tmp/oci-creds.json
```

The Secret has one key, `credentials`, holding the JSON document.
`crossplane/providerconfig/providerconfig.yaml` references this
exact key.

## Step 6 — Apply the ProviderConfig (idempotent)

```bash
kubectl apply -f ~/OCI-Defense-Demo/crossplane/providerconfig/providerconfig.yaml
```

Verify:
```bash
kubectl get providerconfig.oci.upbound.io default -o jsonpath='{.spec.credentials.source}{"\n"}'
# Secret
```

## Step 7 — Smoke test (Observe-only import)

`crossplane/tests/observe-sovdef26.yaml` imports the existing `sovdef26`
ADB without making any changes:

```bash
kubectl apply -f ~/OCI-Defense-Demo/crossplane/tests/observe-sovdef26.yaml
sleep 60
kubectl describe autonomousdatabases.database.oci.upbound.io sovdef26-imported | tail -15
```

Expected:
```
  Conditions:
    Reason: ReconcileSuccess     Status: True   Type: Synced
    Reason: Available            Status: True   Type: Ready
    Reason: Success              Status: True   Type: LastAsyncOperation
```

Inspect live state Crossplane fetched from OCI:
```bash
kubectl get autonomousdatabases.database.oci.upbound.io sovdef26-imported \
  -o jsonpath='{.status.atProvider}' | jq .
```

## Rotation / cleanup

When you're done with the demo:

1. Delete the API Key in OCI Console (User Settings → API Keys → trash icon
   on the key whose fingerprint you used).
2. Delete the Secret:
   ```bash
   kubectl -n crossplane-system delete secret oci-creds
   ```
3. Delete the local private key:
   ```bash
   rm -rf ~/.oci-crossplane
   ```
4. (Optional) Delete the IAM policy from Step 3 if it was demo-only.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `no extraction handler registered for source: InjectedIdentity` | ProviderConfig still uses `source: InjectedIdentity` | Apply the corrected `providerconfig.yaml` (`source: Secret`). |
| `bad configuration: did not find a proper configuration for private key` | Secret JSON missing `private_key` field, or `auth_type` used instead of `auth` | Use the `--rawfile k` jq pattern from Step 4 verbatim. |
| `did not find a proper configuration for private key` even with `auth: InstancePrincipal` | v0.1.6 doesn't honor InstancePrincipal | Use API Key (this doc). |
| Crossplane Pod stuck `ContainerCreateFailed` with `initContainers are not supported` | Crossplane scheduled on virtual node | Add `--set nodeSelector.role=system` to the Helm release (see `crossplane/providerconfig/runtimeconfig.yaml` — same approach for OCI provider Pods). |
| jq fails with `Bad JSON in --rawfile k ...: No such file or directory` | The private key file at `~/.oci-crossplane/crossplane.pem` doesn't exist (Cloud Shell session was reset) | Re-run Step 1 and re-upload the new public key (Step 2) — fingerprints are tied to the key file. |
