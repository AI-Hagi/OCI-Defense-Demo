# Security Controls Matrix - Sovereign Defence Intelligence Platform

Authoritative cross-reference between every compliance control seeded into
Oracle 26ai (`db/seed/01_compliance_controls.sql`, tenant **T001 / DEU_BMVG**)
and the OCI/platform asset that implements it.

- **Total**: 31 controls (NIS2: 12, DORA: 8, GDPR: 6, VS-NfD: 5)
- **Source of truth**: `db/seed/01_compliance_controls.sql` (re-runnable, deletes
  T001 rows then re-inserts)
- **OLS labels**: 30 = R (RESTRICTED), 50 = C (CONFIDENTIAL)
- **Cloud Guard recipes**: Configuration Detector + Threat Detector + Maximum
  Security Zone (see `docs/security-zone-overview.md`)

## How to read this table

| Column | Meaning |
|---|---|
| Framework | NIS2 / DORA / GDPR / VSNFD |
| Code | Stable code from the seed file (e.g. `NIS2-01`) |
| Title | German short title from the seed (article reference inline) |
| OCI service | Primary OCI service that helps satisfy this control |
| Crossplane / manifest evidence | Path inside this repo that materialises that service |
| Cloud Guard recipe rule | Detector or Maximum-Security-Zone rule that asserts compliance |

## NIS2 - 12 controls (Directive (EU) 2022/2555)

| Framework | Code | Title | OCI service | Crossplane / manifest evidence | Cloud Guard recipe rule |
|---|---|---|---|---|---|
| NIS2 | NIS2-01 | Risikomanagement-Konzept (Art. 21 Abs. 2 lit. a) | Cloud Guard + OCI Console Risk Posture | `scripts/activate-cloud-guard.sh`, `docs/security-zone-overview.md` | All Configuration Detector rules (aggregate posture) |
| NIS2 | NIS2-02 | Behandlung von Sicherheitsvorfaellen (Art. 21 Abs. 2 lit. b) | OCI Events + ONS notification topic | `oci-devops/` (notification topic), `services/compliance/app/routers/live_checks.py` (Cloud Guard problems live) | `cloud-guard problemdetected` event rule |
| NIS2 | NIS2-03 | Geschaeftskontinuitaet und Krisenmanagement (Art. 21 Abs. 2 lit. c) | ADB Auto-Backup + Object Storage versioning | `crossplane/adb/sovdef26.yaml`, `crossplane/buckets/` | `BUCKET_VERSIONING_DISABLED`, `ADB_BACKUP_DISABLED` |
| NIS2 | NIS2-04 | Sicherheit der Lieferkette (Art. 21 Abs. 2 lit. d) | OCIR (signed images) + DevOps approval gates | `oci-devops/`, `k8s/` (image-pull-policy: signed) | `OCIR_IMAGE_NOT_SIGNED` |
| NIS2 | NIS2-05 | Sicherheit bei Erwerb, Entwicklung, Wartung (Art. 21 Abs. 2 lit. e) | OCI DevOps Build Pipelines + OCIR vulnerability scanning | `oci-devops/`, `scripts/setup-devops.sh` | `OCIR_VULNERABILITY_FOUND_HIGH` |
| NIS2 | NIS2-06 | Wirksamkeitspruefung der Massnahmen (Art. 21 Abs. 2 lit. f) | Cloud Guard problem catalogue + Audit Service | `services/compliance/app/routers/live_checks.py`, `db/schema/07_audit_compliance.sql` | All Configuration Detector rules (drives evidence) |
| NIS2 | NIS2-07 | Cyberhygiene und Schulung (Art. 21 Abs. 2 lit. g) | IAM Identity Domains (training/group attestation) | Out-of-band (HR system) | n/a (process control) |
| NIS2 | NIS2-08 | Kryptografie und Verschluesselung (Art. 21 Abs. 2 lit. h) | OCI Vault (HSM-backed, customer-managed AES-256) | `crossplane/vault/`, `crossplane/adb/sovdef26.yaml` (KMS key ref) | `ADB_NOT_USING_CMEK`, `BLOCK_VOLUME_NOT_USING_CMEK`, `BUCKET_NOT_USING_CMEK` |
| NIS2 | NIS2-09 | Personalsicherheit, Hintergrundpruefung (Art. 21 Abs. 2 lit. i) | IAM Identity Domains + SSO (process) | Out-of-band | n/a (process control) |
| NIS2 | NIS2-10 | Zugriffs- und Asset-Management (Art. 21 Abs. 2 lit. i) | IAM compartments + Resource tags | `crossplane/compartments/`, `crossplane/*/tags.yaml` | `IAM_POLICY_GRANTS_TENANCY_MANAGE_ALL` |
| NIS2 | NIS2-11 | Multi-Faktor-Authentifizierung (Art. 21 Abs. 2 lit. j) | IAM Identity Domains MFA policy | IAM (managed in console; tenancy-wide) | `IAM_USER_MFA_DISABLED` |
| NIS2 | NIS2-12 | Netzwerksicherheit und Segmentierung (Art. 21 Abs. 2 lit. j) | VCN + NSG + private subnets + NAT/Service GW | `crossplane/vcn/`, `k8s/overlays/prod/ingress.yaml` | `SL_INGRESS_FROM_INTERNET_TCP_22`, `SL_INGRESS_FROM_INTERNET_TCP_3389`, `VCN_PRIVATE_SUBNET_ROUTES_TO_IGW`, `INSTANCE_HAS_PUBLIC_IP` |

## DORA - 8 controls (Regulation (EU) 2022/2554)

| Framework | Code | Title | OCI service | Crossplane / manifest evidence | Cloud Guard recipe rule |
|---|---|---|---|---|---|
| DORA | DORA-01 | IKT-Risikomanagementrahmen (Art. 6) | Cloud Guard tenancy enablement + Security Zone | `scripts/activate-cloud-guard.sh`, `scripts/create-security-zone.sh` | All recipes (aggregate ICT-risk posture) |
| DORA | DORA-02 | Klassifizierung von IKT-Vorfaellen (Art. 18) | OCI Logging + Events severity routing | `services/compliance/app/routers/live_checks.py`, `db/schema/07_audit_compliance.sql` (DORA_INCIDENTS) | `cloud-guard problem riskLevel` (CRITICAL/HIGH/MEDIUM/MINOR) |
| DORA | DORA-03 | Meldung schwerwiegender IKT-Vorfaelle (Art. 19, RTS) | OCI Notifications (ONS) topic + Events rule | `oci-devops/`, `scripts/activate-cloud-guard.sh` (NEXT ACTIONS step 3) | `cloud-guard problemdetected` event rule |
| DORA | DORA-04 | Digitale operationale Resilienztests (Art. 24-26) | OCI Vulnerability Scanning + DevOps test stages | `oci-devops/`, `services/*/tests/` | `VSS_SCAN_FAILED`, `OCIR_VULNERABILITY_FOUND_HIGH` |
| DORA | DORA-05 | Threat-Led Penetration Testing (Art. 26-27) | Out-of-band (red-team provider) + OCI Audit | Out-of-band; audit retention via `db/schema/07_audit_compliance.sql` | n/a (external assessment) |
| DORA | DORA-06 | Risikomanagement IKT-Drittparteien (Art. 28-30) | OCI Marketplace listings + DevOps approvals | `oci-devops/` (approval gates), `crossplane/` (provider package pins) | `OCIR_IMAGE_NOT_SIGNED` (third-party image trust) |
| DORA | DORA-07 | Reaktion und Wiederherstellung (Art. 11-13) | ADB Auto-Backup + Object Storage CRR + DR region | `crossplane/adb/sovdef26.yaml`, `crossplane/buckets/` (cross-region replication) | `ADB_BACKUP_DISABLED`, `BUCKET_REPLICATION_DISABLED` |
| DORA | DORA-08 | Informationsaustausch zu Cyberbedrohungen (Art. 45) | Logging Analytics + Streaming (OSINT/STIX) | `crossplane/streaming/`, `services/osint/` | n/a (data-sharing process) |

## GDPR - 6 controls (Regulation (EU) 2016/679)

| Framework | Code | Title | OCI service | Crossplane / manifest evidence | Cloud Guard recipe rule |
|---|---|---|---|---|---|
| GDPR | GDPR-01 | Rechtmaessigkeit der Verarbeitung (Art. 6) | Oracle Label Security (OLS) + DICE_POLICY | `db/schema/01_tenants_and_security.sql`, `db/schema/07_audit_compliance.sql` | n/a (DB-level enforcement) |
| GDPR | GDPR-02 | Rechte der betroffenen Person (Art. 12-22) | ORDS REST endpoints (DSAR) + Audit Service | `db/schema/08_ords_endpoints.sql` (gdpr_requests AutoREST), `db/schema/07_audit_compliance.sql` | n/a |
| GDPR | GDPR-03 | Datenschutz-Folgenabschaetzung (Art. 35) | Out-of-band DPIA register + OCI Audit log | Out-of-band; evidence in `audit_events` | n/a |
| GDPR | GDPR-04 | Meldung von Datenschutzverletzungen (Art. 33-34) | OCI Events + ONS + 72h SLA timer | `services/compliance/app/routers/live_checks.py`, `oci-devops/` | `cloud-guard problemdetected` (PII-tagged resources) |
| GDPR | GDPR-05 | Verzeichnis der Verarbeitungstaetigkeiten (Art. 30) | Oracle 26ai Duality Views over `documents`, `tenants` | `db/schema/03_duality_views.sql` | n/a |
| GDPR | GDPR-06 | Benennung des Datenschutzbeauftragten (Art. 37) | IAM Identity Domains group `dpo` (process) | Out-of-band | n/a (process control) |

## VS-NfD - 5 controls (BMI VSA, Anlage III)

| Framework | Code | Title | OCI service | Crossplane / manifest evidence | Cloud Guard recipe rule |
|---|---|---|---|---|---|
| VSNFD | VSNFD-01 | Physische Handhabung (VSA Anlage III Nr. 2) | OCI EU Sovereign Region (eu-frankfurt-1) - data residency | `crossplane/vcn/region: eu-frankfurt-1`, `crossplane/adb/sovdef26.yaml` | `RESOURCE_NOT_IN_HOME_REGION` |
| VSNFD | VSNFD-02 | Aufbewahrung eingestufter Daten (VSA Anlage III Nr. 2.3) | ADB private endpoint + customer-managed Vault key + OLS label 50 (C) | `crossplane/adb/sovdef26.yaml` (privateEndpointId, kmsKeyId), `db/schema/01_tenants_and_security.sql` (DICE_POLICY) | `ADB_PUBLIC_ENDPOINT_ENABLED`, `ADB_NOT_USING_CMEK` |
| VSNFD | VSNFD-03 | Uebermittlung und Transport (VSA Anlage III Nr. 3) | TLS 1.3 ingress + IPSec/SINA out-of-band | `k8s/overlays/prod/ingress.yaml` (TLS 1.3 only), `crossplane/vcn/` (VCN local peering for SINA gateways) | `LB_TLS_VERSION_LOW`, `LB_NOT_USING_TLS` |
| VSNFD | VSNFD-04 | Kennzeichnung und Markierung (VSA Anlage III Nr. 1) | Resource tags + DB column `classification` (`U/R/C/S/VS-NFD`) | `db/schema/02_core_tables.sql` (classification column), `crossplane/*/tags.yaml` | n/a (DB- and tag-level) |
| VSNFD | VSNFD-05 | Vernichtung und Aussonderung (VSA Anlage III Nr. 4) | OCI Block Volume crypto-shred + Object Storage retention | `crossplane/buckets/` (lifecycle rules), `crossplane/vault/` (key destroy) | `BUCKET_LIFECYCLE_RULES_DISABLED`, `VAULT_KEY_DELETION_PROTECTED` |

## Notes on coverage

- Rows marked `n/a` are process-only controls (training, DPO appointment, TLPT
  red-team) where Cloud Guard cannot mechanically observe compliance. Evidence
  for these lives in `audit_events` (out-of-band ingestion via the Compliance
  Q TxEventQ from `db/schema/07_audit_compliance.sql`).
- Rules listed under "Cloud Guard recipe rule" are detector-rule names from
  the Oracle-managed Configuration Detector Recipe and the Maximum Security
  Recipe, not custom rules. The discovery is delegated to
  `scripts/activate-cloud-guard.sh` (it pulls Oracle-managed recipes by
  display-name match).
- `services/compliance/app/routers/live_checks.py` exposes four live OCI
  probes (Cloud Guard / ADB / Buckets / OLS) that produce real-time
  metrics for the per-framework score formula in
  `docs/compliance-architecture.md`.

## Provenance

Generated by the integration reviewer agent from a parse of
`db/seed/01_compliance_controls.sql`. To regenerate after a seed change,
re-run the parse: this matrix has exactly one row per `INTO compliance_controls`
statement in that SQL file.
