"""
Mock-first endpoint tests for the live_checks router.

The OCI SDK is patched so tests do not require ``oci`` to be installed.
The pure-DB endpoint (``/live/ols-status``) goes through the same Oracle
mock fixtures used by ``test_endpoints.py``.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake OCI module — only what live_checks imports lazily.
# ---------------------------------------------------------------------------

class _FakeProblem:
    def __init__(self, lifecycle_detail: str = "OPEN", risk_level: str = "LOW") -> None:
        self.lifecycle_detail = lifecycle_detail
        self.risk_level = risk_level
        self.detector_id = "X"


class _FakeBucketSummary:
    def __init__(self, name: str, public_access_type: str = "NoPublicAccess") -> None:
        self.name = name
        self.public_access_type = public_access_type


class _FakeBucket:
    def __init__(self, public_access_type: str = "NoPublicAccess") -> None:
        self.public_access_type = public_access_type


class _FakeADB:
    def __init__(self, kms_key_id: str | None = None,
                 is_data_guard_enabled: bool = False) -> None:
        self.kms_key_id = kms_key_id
        self.vault_id = None
        self.is_data_guard_enabled = is_data_guard_enabled


class _Resp:
    def __init__(self, data) -> None:
        self.data = data
        self.next_page = None


def _build_fake_oci(
    problems: list[_FakeProblem] | None = None,
    adbs: list[_FakeADB] | None = None,
    buckets: list[_FakeBucketSummary] | None = None,
    bucket_details: dict[str, _FakeBucket] | None = None,
    raise_signer: bool = False,
) -> types.ModuleType:
    """Construct a minimal stand-in for the ``oci`` package."""
    oci = types.ModuleType("oci")

    # auth.signers.InstancePrincipalsSecurityTokenSigner
    auth = types.ModuleType("oci.auth")
    signers = types.ModuleType("oci.auth.signers")

    class InstancePrincipalsSecurityTokenSigner:  # noqa: N801 — match SDK casing
        def __init__(self, *a, **kw) -> None:
            if raise_signer:
                raise RuntimeError("no IMDS on virtual node")

    signers.InstancePrincipalsSecurityTokenSigner = InstancePrincipalsSecurityTokenSigner
    auth.signers = signers
    oci.auth = auth

    # cloud_guard.CloudGuardClient
    cg = types.ModuleType("oci.cloud_guard")

    class CloudGuardClient:
        def __init__(self, *a, **kw) -> None:
            pass

        def list_problems(self, **kwargs):
            return _Resp(list(problems or []))

    cg.CloudGuardClient = CloudGuardClient
    oci.cloud_guard = cg

    # database.DatabaseClient
    db = types.ModuleType("oci.database")

    class DatabaseClient:
        def __init__(self, *a, **kw) -> None:
            pass

        def list_autonomous_databases(self, **kwargs):
            return _Resp(list(adbs or []))

    db.DatabaseClient = DatabaseClient
    oci.database = db

    # object_storage.ObjectStorageClient
    osm = types.ModuleType("oci.object_storage")

    class ObjectStorageClient:
        def __init__(self, *a, **kw) -> None:
            pass

        def get_namespace(self):
            return _Resp("ns-test")

        def list_buckets(self, **kwargs):
            return _Resp(list(buckets or []))

        def get_bucket(self, namespace_name, bucket_name):
            details = (bucket_details or {}).get(bucket_name, _FakeBucket())
            return _Resp(details)

    osm.ObjectStorageClient = ObjectStorageClient
    oci.object_storage = osm

    return oci


def _install_fake_oci(monkeypatch: pytest.MonkeyPatch, fake: types.ModuleType) -> None:
    monkeypatch.setitem(sys.modules, "oci", fake)
    monkeypatch.setitem(sys.modules, "oci.auth", fake.auth)
    monkeypatch.setitem(sys.modules, "oci.auth.signers", fake.auth.signers)
    monkeypatch.setitem(sys.modules, "oci.cloud_guard", fake.cloud_guard)
    monkeypatch.setitem(sys.modules, "oci.database", fake.database)
    monkeypatch.setitem(sys.modules, "oci.object_storage", fake.object_storage)


# ---------------------------------------------------------------------------
# Cloud Guard
# ---------------------------------------------------------------------------

def test_cloud_guard_counts_open_problems(client, monkeypatch):
    monkeypatch.setenv("OCI_TENANCY_OCID", "ocid1.tenancy.oc1..test")
    fake = _build_fake_oci(problems=[
        _FakeProblem(risk_level="LOW"),
        _FakeProblem(risk_level="HIGH"),
        _FakeProblem(risk_level="CRITICAL"),
    ])
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/cloud-guard",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["open_problems"] == 3
    assert body["high_risk"] == 2
    assert "as_of" in body


def test_cloud_guard_degrades_when_no_imds(client, monkeypatch):
    monkeypatch.setenv("OCI_TENANCY_OCID", "ocid1.tenancy.oc1..test")
    fake = _build_fake_oci(raise_signer=True)
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/cloud-guard",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["open_problems"] == -1
    assert body["high_risk"] == -1
    assert body.get("error") == "instance_principal_unavailable"


def test_cloud_guard_missing_tenancy_returns_degraded(client, monkeypatch):
    monkeypatch.delenv("OCI_TENANCY_OCID", raising=False)
    monkeypatch.delenv("OCI_TENANCY", raising=False)
    monkeypatch.delenv("TF_VAR_tenancy_ocid", raising=False)
    fake = _build_fake_oci()
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/cloud-guard",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["open_problems"] == -1


# ---------------------------------------------------------------------------
# ADB encryption
# ---------------------------------------------------------------------------

def test_adb_encryption_compliant(client, monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..test")
    fake = _build_fake_oci(adbs=[
        _FakeADB(kms_key_id="ocid1.key.oc1..a"),
        _FakeADB(is_data_guard_enabled=True),
    ])
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/adb-encryption",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["adb_count"] == 2
    assert body["encrypted_count"] == 2
    assert body["compliant"] is True


def test_adb_encryption_non_compliant(client, monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..test")
    fake = _build_fake_oci(adbs=[
        _FakeADB(kms_key_id="ocid1.key.oc1..a"),
        _FakeADB(),  # no kms, no DG
    ])
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/adb-encryption",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["adb_count"] == 2
    assert body["encrypted_count"] == 1
    assert body["compliant"] is False


def test_adb_encryption_degrades(client, monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..test")
    fake = _build_fake_oci(raise_signer=True)
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/adb-encryption",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["adb_count"] == -1
    assert body["compliant"] is False


# ---------------------------------------------------------------------------
# Bucket public access
# ---------------------------------------------------------------------------

def test_bucket_public_access_compliant(client, monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..test")
    fake = _build_fake_oci(
        buckets=[_FakeBucketSummary("a"), _FakeBucketSummary("b")],
        bucket_details={
            "a": _FakeBucket("NoPublicAccess"),
            "b": _FakeBucket("NoPublicAccess"),
        },
    )
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/bucket-public-access",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket_count"] == 2
    assert body["public_count"] == 0
    assert body["compliant"] is True


def test_bucket_public_access_non_compliant(client, monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..test")
    fake = _build_fake_oci(
        buckets=[_FakeBucketSummary("a"), _FakeBucketSummary("b")],
        bucket_details={
            "a": _FakeBucket("ObjectRead"),
            "b": _FakeBucket("NoPublicAccess"),
        },
    )
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/bucket-public-access",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket_count"] == 2
    assert body["public_count"] == 1
    assert body["compliant"] is False


def test_bucket_public_access_degrades(client, monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..test")
    fake = _build_fake_oci(raise_signer=True)
    _install_fake_oci(monkeypatch, fake)

    resp = client.get("/api/compliance/live/bucket-public-access",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket_count"] == -1
    assert body["compliant"] is False


# ---------------------------------------------------------------------------
# OLS status — pure DB query
# ---------------------------------------------------------------------------

def test_ols_status_active(client, mock_cursor):
    mock_cursor.fetchone.return_value = (17,)
    resp = client.get("/api/compliance/live/ols-status",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_name"] == "DICE_POLICY"
    assert body["applied_to_tables"] == 17
    assert body["active"] is True
    assert "as_of" in body


def test_ols_status_inactive_when_zero(client, mock_cursor):
    mock_cursor.fetchone.return_value = (0,)
    resp = client.get("/api/compliance/live/ols-status",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied_to_tables"] == 0
    assert body["active"] is False


def test_ols_status_falls_back_to_user_view(client, mock_cursor):
    """First execute (set_identifier) ok; DBA view raises; user view succeeds."""

    def _exec(sql, *args, **kwargs):
        sql_str = str(sql)
        if "dba_sa_table_policies" in sql_str:
            raise Exception("ORA-00942: dba_sa_table_policies")
        return None

    mock_cursor.execute.side_effect = _exec
    mock_cursor.fetchone.return_value = (5,)
    resp = client.get("/api/compliance/live/ols-status",
                      headers={"X-Tenant-Id": "T001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied_to_tables"] == 5
    assert body["active"] is True


# ---------------------------------------------------------------------------
# Tenant header propagation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tenant", ["T001", "T002", "T003"])
def test_ols_status_tenant_header_sets_identifier(client, mock_cursor, tenant):
    mock_cursor.execute.reset_mock()
    mock_cursor.fetchone.return_value = (1,)
    client.get("/api/compliance/live/ols-status", headers={"X-Tenant-Id": tenant})
    # The first execute call is DBMS_SESSION.SET_IDENTIFIER(:1) with [tenant].
    found = False
    for call in mock_cursor.execute.mock_calls:
        for arg in call.args:
            if isinstance(arg, list) and arg == [tenant]:
                found = True
    assert found, f"DBMS_SESSION.SET_IDENTIFIER not invoked with tenant {tenant}"
