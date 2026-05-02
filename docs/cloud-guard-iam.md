# Cloud Guard / Database / Object Storage IAM for the Compliance Service

The compliance service exposes four read-only "live" compliance probes that
call the OCI control plane:

| Endpoint                              | OCI service     | API call                       |
|---------------------------------------|-----------------|--------------------------------|
| `GET /api/compliance/live/cloud-guard`     | Cloud Guard     | `ListProblems`                 |
| `GET /api/compliance/live/adb-encryption`  | Database        | `ListAutonomousDatabases`      |
| `GET /api/compliance/live/bucket-public-access` | Object Storage  | `ListBuckets`, `GetBucket`     |
| `GET /api/compliance/live/ols-status`      | Oracle DB (ATP) | (no OCI API — DB query only)   |

## Required IAM policy statements

The pod runs under the OKE *workload identity* / *instance principal* of its
node. Add a dynamic group covering the worker nodes (or virtual nodes) the
compliance pods land on, then grant read-only access:

```text
Allow dynamic-group <oke-virtual-nodes-dg> to read cloud-guard-family in tenancy
Allow dynamic-group <oke-virtual-nodes-dg> to read autonomous-database-family in compartment oci-defence-demo
Allow dynamic-group <oke-virtual-nodes-dg> to read buckets in compartment oci-defence-demo
Allow dynamic-group <oke-virtual-nodes-dg> to read objects in compartment oci-defence-demo
```

Replace `<oke-virtual-nodes-dg>` with the actual dynamic group name (for the
sovdef26 demo environment that is `dg-oke-defence-demo`).

`read cloud-guard-family` must be at the tenancy level because Cloud Guard
problems are surfaced from a tenancy-scoped target.

## Environment variables expected by the pod

| Variable                | Purpose                                       |
|-------------------------|-----------------------------------------------|
| `OCI_TENANCY_OCID`      | Tenancy OCID (used for Cloud Guard scoping).   |
| `OCI_COMPARTMENT_OCID`  | Compartment containing ADBs / buckets.         |
| `COMPLIANCE_BASE_URL`   | Self-URL for `/score` to call `/live/...`.     |

## Virtual nodes and IMDS — runtime caveat

OKE *virtual nodes* (the serverless variant) **do not expose the instance
metadata service (IMDS)**. The OCI Python SDK's
`InstancePrincipalsSecurityTokenSigner` therefore fails immediately at
construction with a connection error to `169.254.169.254`. Each live
endpoint catches this and returns:

```json
{ "open_problems": -1, "as_of": "...", "error": "instance_principal_unavailable" }
```

The frontend treats `-1` (and any payload containing `error`) as "metric
unavailable" and renders a placeholder.

### Two supported workarounds

1. **Pin the compliance pod to a managed (non-virtual) node** — managed
   nodes are real VMs and do expose IMDS. This is enforced by the K8s
   `DeploymentRuntimeConfig` / `nodeSelector`. The infrastructure agent
   owns the manifest; coordinate the node-pool label and pin the pod with
   `nodeSelector: oke.oraclecloud.com/node-pool=managed-default`.

2. **Provide an API-key Secret** following the
   `crossplane/auth-setup.md` pattern. The Secret is mounted as
   `~/.oci/config` plus a PEM key file, and the SDK client falls back to
   file-based auth when the instance principal signer cannot be built. The
   key must belong to a user whose group has the same four `read` policies
   listed above. This is the recommended path for virtual-node demos.

## Local development

For local development outside OCI, set `OCI_CLI_AUTH=api_key` and ensure
`~/.oci/config` is populated. The endpoints will still work but will hit
the real tenancy — use a non-production profile or test compartment.
