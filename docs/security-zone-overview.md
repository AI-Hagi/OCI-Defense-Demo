# Cloud Guard & Security Zones - Sovereign Defence Platform

Operational reference for the OCI security posture controls applied to the
Sovereign Defence Intelligence Platform compartment. Companion to:

- `scripts/activate-cloud-guard.sh` - turns on detection
- `scripts/create-security-zone.sh` - turns on enforcement

## What is OCI Cloud Guard?

[Cloud Guard](https://docs.oracle.com/en-us/iaas/cloud-guard/home.htm) is
Oracle's Cloud Security Posture Management (CSPM) service. It continuously
evaluates the configuration and runtime behaviour of every resource in a
target compartment against detector recipes (rule sets) and raises
**problems** when a rule is violated.

Cloud Guard is **detective**: it surfaces issues, it does not block them.

Two Oracle-managed detector recipes ship with every tenancy:

| Recipe | What it checks |
|--------|----------------|
| Configuration Detector Recipe | Misconfigurations - public buckets, root-key disabled, unencrypted block volumes, IAM policies that grant tenancy-wide manage-all-resources, etc. |
| Threat Detector Recipe | Runtime/behavioural - impossible-travel sign-ins, anomalous API call patterns, suspicious IP ranges, login from disabled users. |

The activation script binds both recipes to a Cloud Guard **target** rooted
at the platform compartment.

## What is a Security Zone?

A [Security Zone](https://docs.oracle.com/en-us/iaas/security-zone/home.htm)
is an additional layer that **enforces** Cloud Guard's findings at the
control-plane API. Resources that would violate the recipe cannot be created
or modified in the first place - the OCI API returns 400 / 409 with a
`SecurityZonePolicyViolation` code.

A Security Zone is **preventive**.

The Sovereign Defence platform uses the Oracle-managed
**Maximum Security Recipe**, which is the strictest preset Oracle ships.

## What the Maximum Security Recipe blocks

Representative subset (full list at
<https://docs.oracle.com/en-us/iaas/security-zone/using/security-zone-policies.htm>):

1. **Buckets must be private** - no `publicAccessType=ObjectRead` or
   `ObjectReadWithoutList` on Object Storage buckets.
2. **Buckets must use customer-managed Vault keys** - Oracle-managed key
   encryption is rejected for sensitive object storage.
3. **Buckets must enable versioning** so accidental deletes are recoverable.
4. **ADBs must use customer-managed keys** - the ATP encryption key must
   reside in a Vault inside the same compartment, not Oracle-managed.
5. **ADBs must use private endpoints** - public ATP endpoints are blocked;
   the database must sit on a VCN subnet.
6. **Block volumes must be encrypted with customer-managed keys** - same
   rule as ADBs, applied to OCI Block Volume.
7. **Compute instances may not have public IPs** - traffic must enter via a
   Load Balancer or NAT Gateway; instances themselves stay on private subnets.
8. **VCNs may not have a route rule from a private subnet to an Internet
   Gateway** - egress must go via NAT/Service Gateway.
9. **Security Lists must not be 0.0.0.0/0 ingress on RDP/SSH** ports - any
   wide-open inbound TCP/22 or TCP/3389 rule is rejected.
10. **All resources must reside in the same region as the Security Zone** -
    cross-region resource references are rejected to prevent data exfil.
11. **Network Security Groups required for all NICs** - relying on Security
    Lists alone is rejected.
12. **No autonomous database "free tier"** - production-grade SKUs only.

## How the Sovereign Defence platform aligns

| Recipe rule | Platform compliance |
|-------------|---------------------|
| Buckets private | All `geoint-*` and `doc-intel-*` buckets in `crossplane/buckets/` use `accessType: NoPublicAccess`. |
| ADB customer-managed key | `crossplane/adb/sovdef26.yaml` references the platform Vault (Compartment-scoped, customer-managed AES-256). |
| ADB private endpoint | `subnetId` set on the ADB resource - no public ATP endpoint exposed. |
| Compute no public IP | OKE worker nodes sit on private subnets; the Frontend is exposed via OCI Load Balancer with TLS 1.3 (see `k8s/overlays/prod/ingress.yaml`). |
| Block volumes CMEK | OKE node pool block volumes inherit the OKE cluster's KMS key, which is the platform Vault key. |
| VCN egress via NAT | `crossplane/vcn/` defines a NAT Gateway and a Service Gateway; private subnets route 0.0.0.0/0 via NAT, OCI services via SG. |
| Region pinning | Everything declared in `eu-frankfurt-1` (EU sovereign region). |
| NSG-first networking | All five FastAPI services attach to NSGs scoped per microservice. |

## Operational runbook

### Read a Cloud Guard problem report

```bash
# All open HIGH-risk problems in the platform compartment:
oci --auth instance_principal --region eu-frankfurt-1 \
    cloud-guard problem list \
    --compartment-id "$COMP" \
    --lifecycle-state OPEN \
    --risk-level HIGH \
    --query 'data.items[].{name:"problem-name",resource:"resource-name",risk:"risk-level",detected:"time-first-detected"}'
```

Each problem links to:

- the offending **resource OCID**
- the **detector rule** that flagged it (e.g. `BUCKET_PUBLIC_ACCESS_ENABLED`)
- a **risk level** (CRITICAL / HIGH / MEDIUM / MINOR)
- a **lifecycle state** (OPEN / RESOLVED / DISMISSED)

### Triage workflow

1. **CRITICAL or HIGH** - assume real, investigate within 24h. Page the
   on-call security manager via the existing notifications topic
   (`NOTIFICATION_TOPIC_ID` in `.oci-devops.env`).
2. **MEDIUM** - batch into a weekly review.
3. **MINOR** - address only if part of a recipe-tightening sweep.

### Suppress a false-positive

False-positives happen, e.g. a deliberately-public marketing bucket, or a
test ADB without CMEK. Suppression options:

```bash
# Option A: dismiss a single problem with a reason (audited)
oci --auth instance_principal --region eu-frankfurt-1 \
    cloud-guard problem update \
    --problem-id "$PROBLEM_OCID" \
    --comment "Dev-only bucket, no PII, expires 2026-12-31" \
    --lifecycle-detail RESOLVED

# Option B: add the resource compartment to the trusted managed list so
# future detections are auto-suppressed (only do this for whole comps, not
# individual resources).
oci --auth instance_principal --region eu-frankfurt-1 \
    cloud-guard managed-list add-managed-list-item \
    --managed-list-id "$CLOUD_GUARD_MANAGED_LIST_ID" \
    --item-list-to-add '["<TRUSTED_COMP_OCID>"]'
```

Always record the reason in the `--comment` field - the platform's audit
trail consumer (`services/compliance/`) extracts these for the NIS2/DORA
quarterly evidence pack.

### Unwind a Security Zone (emergency only)

If a deployment is wedged because a legitimate change violates the recipe,
the zone can be removed (audited operation):

```bash
oci --auth instance_principal --region eu-frankfurt-1 \
    cloud-guard security-zone delete \
    --security-zone-id "$SECURITY_ZONE_ID" --force
```

The compartment itself is unaffected - only the policy enforcement is
removed. Cloud Guard *detection* (recipes/target) keeps running. Re-create
the zone with `scripts/create-security-zone.sh` once the deployment is
green.

## Cross-references

- OCI doc: <https://docs.oracle.com/en-us/iaas/cloud-guard/home.htm>
- Security Zone policies: <https://docs.oracle.com/en-us/iaas/security-zone/using/security-zone-policies.htm>
- Recipe catalogue: `oci cloud-guard security-recipe list --compartment-id $TENANCY_OCID --all`
- Platform compliance service: `services/compliance/` (consumes Cloud Guard events for NIS2/DORA evidence).

## ⚠ Compatibility caveat: sovdef26 (ADB-S Always-Free)

Locking the platform compartment with the **Maximum Security Recipe**
will conflict with this demo's `sovdef26` Autonomous Database because the
recipe enforces:

- Customer-managed encryption keys (CMEK) — Always-Free ADB-S only supports
  Oracle-managed keys; no Vault wiring path.
- Private endpoint — Always-Free ADB-S exposes only the shared regional
  public endpoint (`adb.eu-frankfurt-1.oraclecloud.com:1522`).

**Either** migrate `sovdef26` to ADB-D (Dedicated) with a private endpoint
and Vault key, **or** target a less restrictive recipe (Standard) for the
demo compartment, **or** create a separate "production" compartment that's
locked, while keeping `oci-defence-demo` unlocked for development.

`scripts/create-security-zone.sh` requires `CONFIRM=YES` precisely because
of this caveat — review your resources first.
