# Runbook — Sovereign Defence Intelligence Platform

End-to-end operational procedures for the live deployment in
`eu-frankfurt-1`. Every step assumes an operator with:

- An IAM user in tenancy `MARKUS.HAGENKOETTER@ORACLE.COM`'s tenancy
  with `manage all-resources` on compartment
  `ocid1.compartment.oc1..…aaaaaaaamcjaobwgnwwwkaphfzuzavq2dez6jkonahdwsn6ys7apqgiqelmq`
- An active OCIR auth token (rotated per the schedule below)
- An ADB ADMIN password for `sovdef26`

The dev VM cannot reach the OKE private API endpoint
(`10.0.0.14:6443`). Anything `kubectl ...` runs from **OCI Cloud Shell**.
OCIR pushes and `oci os …` work from the dev VM.

---

## 0. Bootstrap (one-shot)

```bash
# Tenancy + compartment + base resources
bash scripts/setup-oci.sh

# OCI DevOps project + 6 build pipelines + OCIR repos
bash scripts/setup-devops.sh                  # writes .oci-devops.env

# Cloud Guard target on the platform compartment (opt-in Security Zone)
COMP=<compartment_ocid> TENANCY_OCID=<root_ocid> \
  bash scripts/setup-security.sh              # writes .oci-cloudguard.env
```

`.oci-devops.env` and `.oci-cloudguard.env` are gitignored. Both files
are required for the steps below.

---

## 1. Demo URL

```
http://152.70.18.236
```

OCI Native Ingress Controller (workloadIdentity auth). All routes are
under `/api/<svc>` per `k8s/base/ingress.yaml`. Internal `/health`
endpoints are pod-local (kubelet probes only).

---

## 2. Apply a database migration

Migrations are idempotent SQL files under `db/migrations/`.

```bash
ADB_ADMIN_PASSWORD='<sovdef26 ADMIN pw>' \
  bash scripts/apply-migration.sh db/migrations/02_add_uav_platform.sql
```

The script uses SQLcl with the wallet at `~/wallet/`. Already-applied
migrations are no-ops (PL/SQL existence guard). Currently applied:

- `01_add_image_uri.sql` — `satellite_scenes.image_uri`
- `02_add_uav_platform.sql` — `platform_kind`, `altitude_m`, `heading_deg`
- `03_extend_osint_kind.sql` — `'ems_emission'` in `ck_osint_ent_kind`

Phase 2 OLS migrations (`04..08`) are written but not yet applied —
see "Phase 2 cutover" below.

---

## 3. Build + push a service image

The OCI DevOps deploy pipelines are gated; for now we push from the
dev VM directly:

```bash
# 3a. Login to OCIR (one-time per shell)
echo '<OCIR_AUTH_TOKEN>' | docker login fra.ocir.io \
    --username 'fri3jnkhmoew/MARKUS.HAGENKOETTER@ORACLE.COM' \
    --password-stdin

# 3b. Build with the commit SHA so :IfNotPresent is forced to pull
SHA=$(git rev-parse --short=12 HEAD)
docker build -t fra.ocir.io/fri3jnkhmoew/sovdefence/compliance:$SHA \
             -t fra.ocir.io/fri3jnkhmoew/sovdefence/compliance:latest \
             services/compliance/

# 3c. Push both tags
docker push fra.ocir.io/fri3jnkhmoew/sovdefence/compliance:$SHA
docker push fra.ocir.io/fri3jnkhmoew/sovdefence/compliance:latest
```

Replace `compliance` with any of: `geoint`, `doc-intel`, `osint`,
`supply-chain`, `frontend`. The build context is the matching
`services/<svc>/` directory.

---

## 4. Roll a Deployment (from Cloud Shell)

```bash
# Use the SHA tag — :latest can hit cached IfNotPresent on virtual nodes
kubectl -n sovdefence set image deploy/compliance \
    compliance=fra.ocir.io/fri3jnkhmoew/sovdefence/compliance:<SHA>
kubectl -n sovdefence rollout status deploy/compliance --timeout=300s
```

If a pod stays `pending termination` past 5 min, force-delete it:

```bash
kubectl -n sovdefence get pods -l app.kubernetes.io/name=compliance \
    -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image
kubectl -n sovdefence delete pod <stuck-pod-name> --grace-period=10
```

The base manifests now use `imagePullPolicy: Always`, so once the
overlay is applied to the cluster (`kubectl apply -k k8s/overlays/prod`),
a plain `kubectl rollout restart deploy/<svc>` is enough — the SHA
tag dance is only needed when `IfNotPresent` is still in effect on
running pods.

---

## 5. Train + upload YOLOv8 weights

```bash
sudo apt-get install -y libgl1 libglib2.0-0
cd datasets && source .venv/bin/activate
cd YOLO-Military-1
yolo train data=data.yaml model=yolov8n.pt epochs=1 imgsz=640 \
     batch=16 device=cpu workers=2 project=../runs name=mil-v1 exist_ok=True

# Upload best weights to the bucket
cd ../..
bash scripts/upload-yolo-weights.sh \
    runs/runs/mil-v1/weights/best.pt \
    models/yolov8n-military-v1.pt
```

The geoint service does **not** auto-load weights from the bucket
yet — it falls back to `yolov8n.pt` baked into the image. To swap,
mount a Vault-backed file or add a startup-time pull (out of scope
for v2.0).

---

## 6. Check live OCI compliance tiles

```bash
for tile in cloud-guard adb-encryption bucket-public-access ols-status; do
  echo "=== $tile ==="
  curl -s -m 8 -w "\nHTTP %{http_code} %{time_total}s\n" \
       "http://152.70.18.236/api/compliance/live/$tile"
  echo
done
```

Expected on virtual nodes (no IMDS): three of four tiles return a
degraded JSON payload with `error: instance_principal_unavailable`
in <1s; `ols-status` is pure DB and reports the policy state.

---

## 7. Run the integration suite

```bash
/tmp/integration-venv/bin/python -m pytest tests/integration/ -v
```

19 tests against the live LB. Latency report at session end. Skip
with `SKIP_LIVE=1`.

---

## 8. Run the Playwright e2e suite

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://152.70.18.236 npx playwright test --reporter=list
```

9 tests across 6 routes + nav. Reuses the chromium browser cache at
`~/.cache/ms-playwright/`.

---

## 9. Credential rotation schedule

Rotate quarterly or after any secret leaves a private channel.

| Credential | Where it lives | Rotation procedure |
|---|---|---|
| ADB ADMIN | OCI Console → ADB → "Administrator password" | Update + re-apply migrations + force `kubectl rollout restart` |
| OCIR auth token | OCI Console → User → Auth Tokens | Re-issue + `docker login` + update `ocir-secret` |
| Crossplane API key | OCI Console → User → API Keys | Re-issue + update Crossplane Secret + restart provider |
| Roboflow | Roboflow account dashboard | Re-issue + update download script |

Phase 4 (OCI Vault + ESO) replaces the manual path for ADB +
OCIR — see `scripts/setup-vault.sh` once Phase 4 lands.

---

## 10. Demo-day cheat sheet

```bash
# Verify everything green from this VM
curl -sf http://152.70.18.236/                         # 200
curl -sf http://152.70.18.236/api/geoint/scenes        # JSON list
curl -sf http://152.70.18.236/api/compliance/score     # 4 frameworks
/tmp/integration-venv/bin/python -m pytest tests/integration -q

# Tail compliance pod
# (from Cloud Shell)
kubectl -n sovdefence logs -l app.kubernetes.io/name=compliance --tail=100

# Watch Cloud Guard problems
oci cloud-guard problem list --compartment-id $TENANCY_OCID \
    --lifecycle-state ACTIVE --query 'data."items"[].{id:"id",risk:"risk-level",resource:"resource-name"}'
```
