# Crossplane OCI Provider — IAM Policy

The provider-oci-database + provider-family-oci Pods run in the
crossplane-system namespace with ServiceAccount `provider-family-oci-*`
and `provider-oci-database-*` (auto-generated per package).

To let them manage resources via OKE Workload Identity, create a
tenancy-level policy:

```
Allow any-user to manage database-family in compartment id <COMP_OCID> where all {
  request.principal.type='workload',
  request.principal.namespace='crossplane-system',
  request.principal.cluster_id='<OKE_CLUSTER_OCID>',
  request.principal.service_account in ('provider-family-oci-*','provider-oci-database-*')
}

Allow any-user to use virtual-network-family in compartment id <COMP_OCID> where all {
  request.principal.type='workload',
  request.principal.namespace='crossplane-system',
  request.principal.cluster_id='<OKE_CLUSTER_OCID>'
}
```

Create via CLI:

```bash
oci iam policy create --compartment-id <COMP_OCID> \
  --name sovdefence-crossplane-oci-policy \
  --description "Workload identity perms for Crossplane OCI provider" \
  --statements file:///tmp/crossplane-statements.json
```
