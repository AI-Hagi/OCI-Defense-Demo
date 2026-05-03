"""
Live OCI compliance checks router.

Endpoints (mounted under /api/compliance/live/):
    GET /live/cloud-guard          -> Cloud Guard open-problem counts.
    GET /live/adb-encryption       -> Autonomous DB encryption posture.
    GET /live/bucket-public-access -> Object Storage public-access posture.
    GET /live/ols-status           -> Oracle Label Security policy status.

Auth strategy
-------------
The first three endpoints use the OCI Python SDK with an
``InstancePrincipalsSecurityTokenSigner``. On OKE *virtual nodes* the
instance metadata service (IMDS) is **not** exposed, so the signer cannot
mint a token at runtime. Each call is therefore wrapped in a try/except
that returns a degraded payload of the form

    {"...counts...": -1, "as_of": "<iso>", "error": "instance_principal_unavailable"}

so the frontend can render a placeholder ("—") instead of receiving a 500.
The fourth endpoint (``/live/ols-status``) is a pure DB query and never
depends on OCI SDK availability.

Header contract
---------------
All endpoints accept an optional ``X-Tenant-Id`` header (default ``T001``)
and propagate the tenant identifier into the Oracle session via
``DBMS_SESSION.SET_IDENTIFIER`` so Label Security policies bind correctly.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live-checks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenancy_ocid() -> str | None:
    """Best-effort tenancy OCID from environment for SDK list calls."""
    return (
        os.environ.get("OCI_TENANCY_OCID")
        or os.environ.get("OCI_TENANCY")
        or os.environ.get("TF_VAR_tenancy_ocid")
    )


def _compartment_ocid() -> str | None:
    """Best-effort compartment OCID; falls back to tenancy."""
    return (
        os.environ.get("OCI_COMPARTMENT_OCID")
        or os.environ.get("OCI_COMPARTMENT_ID")
        or _tenancy_ocid()
    )


def _imds_reachable(timeout_s: float = 1.0) -> bool:
    """Quick socket probe of the OCI Instance Metadata Service.

    On OKE *virtual nodes* IMDS isn't exposed, but the OCI SDK's
    ``InstancePrincipalsSecurityTokenSigner`` constructor *blocks* (not
    raises) for ~30–60s before giving up — long enough to trip the
    ingress 30s timeout and surface a 504 to the client. Probing
    ``169.254.169.254:80`` first lets us short-circuit to a degraded
    response in <1s.
    """
    import socket

    try:
        with socket.create_connection(("169.254.169.254", 80), timeout=timeout_s):
            return True
    except OSError:
        return False


def _instance_principal_signer() -> Any:
    """Construct an OCI InstancePrincipalsSecurityTokenSigner.

    Imported lazily so the FastAPI app stays importable in test environments
    where the ``oci`` SDK is not installed. Callers must guard with
    :func:`_imds_reachable` first — otherwise this can block ~60s on
    virtual nodes that lack IMDS.
    """
    import oci  # type: ignore[import-not-found]

    return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()


def _degraded(extra: dict[str, Any]) -> dict[str, Any]:
    """Standard degraded-response shape when OCI SDK access fails."""
    payload: dict[str, Any] = {"as_of": now_iso(), "error": "instance_principal_unavailable"}
    payload.update(extra)
    return payload


def _demo_mode() -> bool:
    """Return True when the synthetic-data path should replace the degraded
    fallback. Gated by ``COMPLIANCE_DEMO_MODE`` (default off in production)."""
    return os.environ.get("COMPLIANCE_DEMO_MODE", "false").lower() in ("1", "true", "yes")


# Hand-curated synthetic Cloud Guard problems for the demo. Stable IDs so the
# UI's React-Query cache keys don't churn between renders. Counts here drive
# the score-tile penalty too (-5 % per open, capped at -25 %).
_DEMO_CLOUD_GUARD_PROBLEMS: list[dict[str, Any]] = [
    {
        "id": "ocid1.cloudguardproblem.oc1.eu-frankfurt-1.demo.aaaaaaaa1",
        "risk_level": "HIGH",
        "detector_rule": "OBJECT_STORAGE_BUCKET_PUBLIC",
        "resource_name": "osint-tile-cache (test)",
        "resource_type": "ObjectStorageBucket",
        "first_detected": "2026-04-29T08:14:11+00:00",
        "compartment": "oci-defence-demo",
    },
    {
        "id": "ocid1.cloudguardproblem.oc1.eu-frankfurt-1.demo.aaaaaaaa2",
        "risk_level": "MEDIUM",
        "detector_rule": "ATP_NO_NETWORK_ACL",
        "resource_name": "sovdef26",
        "resource_type": "AutonomousDatabase",
        "first_detected": "2026-05-01T17:33:02+00:00",
        "compartment": "oci-defence-demo",
    },
]
_DEMO_CG_OPEN = len(_DEMO_CLOUD_GUARD_PROBLEMS)
_DEMO_CG_HIGH = sum(1 for p in _DEMO_CLOUD_GUARD_PROBLEMS if p["risk_level"] in ("HIGH", "CRITICAL"))


# ---------------------------------------------------------------------------
# 1) Cloud Guard problems
# ---------------------------------------------------------------------------

@router.get("/live/cloud-guard")
def cloud_guard(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """Count open Cloud Guard problems and a high-risk subset.

    Uses ``ListProblems`` with ``lifecycle_state=OPEN``. ``high_risk`` counts
    problems whose ``risk_level`` is ``CRITICAL`` or ``HIGH``.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    logger.debug("cloud_guard: tenant=%s", tenant_id)

    if not _imds_reachable():
        if _demo_mode():
            return {
                "open_problems": _DEMO_CG_OPEN,
                "high_risk": _DEMO_CG_HIGH,
                "as_of": now_iso(),
                "demo": True,
            }
        return _degraded({"open_problems": -1, "high_risk": -1})

    try:
        import oci  # type: ignore[import-not-found]

        signer = _instance_principal_signer()
        client = oci.cloud_guard.CloudGuardClient(config={}, signer=signer)
        compartment_id = _tenancy_ocid()
        if not compartment_id:
            return _degraded({"open_problems": -1, "high_risk": -1,
                              "error": "tenancy_ocid_not_set"})

        open_problems = 0
        high_risk = 0
        page: str | None = None
        while True:
            # ACTIVE = currently open lifecycle state in Cloud Guard.
            kwargs: dict[str, Any] = {
                "compartment_id": compartment_id,
                "lifecycle_state": "ACTIVE",
                "compartment_id_in_subtree": True,
            }
            if page:
                kwargs["page"] = page
            resp = client.list_problems(**kwargs)
            for p in resp.data or []:
                open_problems += 1
                risk = (getattr(p, "risk_level", "") or "").upper()
                if risk in ("CRITICAL", "HIGH"):
                    high_risk += 1
            page = getattr(resp, "next_page", None)
            if not page:
                break

        return {
            "open_problems": int(open_problems),
            "high_risk": int(high_risk),
            "as_of": now_iso(),
        }
    except Exception:  # pragma: no cover — depends on OCI runtime
        logger.exception("OCI Cloud Guard call failed (likely no IMDS on virtual node)")
        return _degraded({"open_problems": -1, "high_risk": -1})


@router.get("/live/cloud-guard/problems")
def cloud_guard_problems(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """List individual Cloud Guard problems for the detail view.

    Returns a list under ``problems`` plus a ``demo`` flag when the response
    is synthetic. When IMDS is unreachable AND ``COMPLIANCE_DEMO_MODE`` is
    off, returns the same degraded sentinel shape as the summary endpoint
    so the detail view can render a clear empty state.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    logger.debug("cloud_guard_problems: tenant=%s", tenant_id)

    if not _imds_reachable():
        if _demo_mode():
            return {"problems": _DEMO_CLOUD_GUARD_PROBLEMS, "as_of": now_iso(), "demo": True}
        return _degraded({"problems": []})

    try:
        import oci  # type: ignore[import-not-found]

        signer = _instance_principal_signer()
        client = oci.cloud_guard.CloudGuardClient(config={}, signer=signer)
        compartment_id = _tenancy_ocid()
        if not compartment_id:
            return _degraded({"problems": [], "error": "tenancy_ocid_not_set"})

        problems: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "compartment_id": compartment_id,
                "lifecycle_state": "ACTIVE",
                "compartment_id_in_subtree": True,
            }
            if page:
                kwargs["page"] = page
            resp = client.list_problems(**kwargs)
            for p in resp.data or []:
                problems.append({
                    "id": getattr(p, "id", None),
                    "risk_level": (getattr(p, "risk_level", "") or "").upper() or "UNKNOWN",
                    "detector_rule": getattr(p, "detector_rule_id", None) or
                                     getattr(p, "labels", None) or "n/a",
                    "resource_name": getattr(p, "resource_name", None) or "n/a",
                    "resource_type": getattr(p, "resource_type", None) or "n/a",
                    "first_detected": (
                        p.time_first_detected.isoformat()
                        if getattr(p, "time_first_detected", None) else None
                    ),
                    "compartment": getattr(p, "compartment_id", None) or "n/a",
                })
            page = getattr(resp, "next_page", None)
            if not page:
                break

        return {"problems": problems, "as_of": now_iso()}
    except Exception:  # pragma: no cover
        logger.exception("OCI Cloud Guard list_problems failed")
        return _degraded({"problems": []})


# ---------------------------------------------------------------------------
# 2) Autonomous DB encryption posture
# ---------------------------------------------------------------------------

@router.get("/live/adb-encryption")
def adb_encryption(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """Inspect Autonomous Databases for encryption posture.

    A database is considered ``encrypted_count``-eligible if it carries a
    KMS key reference (customer-managed) **or** has Data Guard enabled,
    indicating an active managed encryption surface beyond the default
    Oracle-managed key.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    logger.debug("adb_encryption: tenant=%s", tenant_id)

    if not _imds_reachable():
        return _degraded({"adb_count": -1, "encrypted_count": -1, "compliant": False})

    try:
        import oci  # type: ignore[import-not-found]

        signer = _instance_principal_signer()
        client = oci.database.DatabaseClient(config={}, signer=signer)
        compartment_id = _compartment_ocid()
        if not compartment_id:
            return _degraded({"adb_count": -1, "encrypted_count": -1, "compliant": False,
                              "error": "compartment_ocid_not_set"})

        adb_count = 0
        encrypted_count = 0
        page: str | None = None
        while True:
            kwargs: dict[str, Any] = {"compartment_id": compartment_id}
            if page:
                kwargs["page"] = page
            resp = client.list_autonomous_databases(**kwargs)
            for db in resp.data or []:
                adb_count += 1
                kms_key = getattr(db, "kms_key_id", None) or getattr(db, "vault_id", None)
                dg = bool(getattr(db, "is_data_guard_enabled", False))
                if kms_key or dg:
                    encrypted_count += 1
            page = getattr(resp, "next_page", None)
            if not page:
                break

        compliant = adb_count > 0 and encrypted_count == adb_count
        return {
            "adb_count": int(adb_count),
            "encrypted_count": int(encrypted_count),
            "compliant": bool(compliant),
            "as_of": now_iso(),
        }
    except Exception:  # pragma: no cover — depends on OCI runtime
        logger.exception("OCI Database list_autonomous_databases failed")
        return _degraded({"adb_count": -1, "encrypted_count": -1, "compliant": False})


# ---------------------------------------------------------------------------
# 3) Object Storage public-access posture
# ---------------------------------------------------------------------------

@router.get("/live/bucket-public-access")
def bucket_public_access(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """Inventory buckets and count those with non-private public-access type.

    A bucket is considered "public" when ``public_access_type`` is anything
    other than ``NoPublicAccess``.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    logger.debug("bucket_public_access: tenant=%s", tenant_id)

    if not _imds_reachable():
        return _degraded({"bucket_count": -1, "public_count": -1, "compliant": False})

    try:
        import oci  # type: ignore[import-not-found]

        signer = _instance_principal_signer()
        client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
        compartment_id = _compartment_ocid()
        if not compartment_id:
            return _degraded({"bucket_count": -1, "public_count": -1, "compliant": False,
                              "error": "compartment_ocid_not_set"})

        ns_resp = client.get_namespace()
        namespace = ns_resp.data

        bucket_count = 0
        public_count = 0
        page: str | None = None
        while True:
            kwargs: dict[str, Any] = {"namespace_name": namespace,
                                      "compartment_id": compartment_id}
            if page:
                kwargs["page"] = page
            resp = client.list_buckets(**kwargs)
            for summary in resp.data or []:
                bucket_count += 1
                # The summary may not carry public_access_type; do a head call.
                try:
                    head = client.get_bucket(namespace_name=namespace,
                                             bucket_name=summary.name)
                    pat = getattr(head.data, "public_access_type", "NoPublicAccess")
                except Exception:
                    pat = getattr(summary, "public_access_type", "NoPublicAccess")
                if pat and str(pat) != "NoPublicAccess":
                    public_count += 1
            page = getattr(resp, "next_page", None)
            if not page:
                break

        compliant = public_count == 0
        return {
            "bucket_count": int(bucket_count),
            "public_count": int(public_count),
            "compliant": bool(compliant),
            "as_of": now_iso(),
        }
    except Exception:  # pragma: no cover — depends on OCI runtime
        logger.exception("OCI Object Storage list_buckets failed")
        return _degraded({"bucket_count": -1, "public_count": -1, "compliant": False})


# ---------------------------------------------------------------------------
# 4) Oracle Label Security policy status (pure DB)
# ---------------------------------------------------------------------------

@router.get("/live/ols-status")
def ols_status(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Report whether DICE_POLICY is applied to the expected tables.

    Tries the DBA view first (``dba_sa_table_policies``) and falls back to
    the user view (``user_sa_table_policies``) if the calling role lacks
    SELECT privilege on the DBA view.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    policy_name = "DICE_POLICY"
    applied: int = 0
    active: bool = False

    queries = (
        "SELECT COUNT(*) FROM dba_sa_table_policies WHERE policy_name = :p",
        "SELECT COUNT(*) FROM user_sa_table_policies WHERE policy_name = :p",
    )
    last_err: Exception | None = None
    for q in queries:
        try:
            with conn.cursor() as cur:
                cur.execute(q, {"p": policy_name})
                row = cur.fetchone()
                applied = int(row[0]) if row and row[0] is not None else 0
                active = applied > 0
                last_err = None
                break
        except Exception as exc:  # pragma: no cover — view-availability dependent
            last_err = exc
            logger.debug("OLS query failed (%s): %s", q, exc)

    out: dict[str, Any] = {
        "policy_name": policy_name,
        "applied_to_tables": int(applied),
        "active": bool(active),
        "as_of": now_iso(),
    }
    if last_err is not None and applied == 0:
        out["error"] = "ols_views_unavailable"
    return out
