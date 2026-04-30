"""
Read-only smoke tests against the deployed Sovereign Defence platform.

Targets:
  * Public OCI Native Ingress Controller LB (default ``http://152.70.18.236``).
  * Live Oracle 26ai (``sovdef26``) ADB behind the FastAPI services.

Each endpoint is hit once per run so the suite stays safe to ship in CI.
Skip with ``SKIP_LIVE=1 pytest tests/integration``.

Path source-of-truth:
  * Ingress (``k8s/base/ingress.yaml``) forwards ``/api/<svc>/*`` to the
    matching service. Internal ``/health`` endpoints are *not* exposed
    through the LB — they're pod-local for kubelet probes.
  * FastAPI routers in ``services/*/app/main.py`` mount under
    ``/api/{geoint, documents, osint, sc, compliance}``.
"""
from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_LIVE") == "1",
    reason="SKIP_LIVE=1 — live integration tests opted out",
)


# ---------------------------------------------------------------------------
# 1) Frontend (HTML)
# ---------------------------------------------------------------------------

def test_frontend_root_returns_html(timed):
    resp = timed("GET", "/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 2) GEOINT
# ---------------------------------------------------------------------------

def test_geoint_list_scenes(timed):
    resp = timed("GET", "/api/geoint/scenes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    if body:
        row = body[0]
        for key in ("scene_id", "captured_at", "sensor"):
            assert key in row, f"missing {key} in {row}"
        # image_uri added by db/migrations/01_add_image_uri.sql; null is OK
        # but the key must be present in the response shape.
        assert "image_uri" in row, "frontend contract requires image_uri key"


# ---------------------------------------------------------------------------
# 3) Document Intelligence (RAG — both endpoints are POST-only)
# ---------------------------------------------------------------------------

def test_doc_intel_search_returns_hits_or_empty(timed):
    resp = timed("POST", "/api/documents/search", json={"query": "NIS2", "k": 3})
    assert resp.status_code in (200, 422), resp.text
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body, list)


# ---------------------------------------------------------------------------
# 4) Collaboration (multi-tenant — exposed under /api/compliance/collab-shares)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tenant_id", ["T001", "T002", "T003"])
def test_compliance_collab_shares_per_tenant(timed, tenant_id: str):
    resp = timed("GET", "/api/compliance/collab-shares",
                 headers={"X-Tenant-Id": tenant_id})
    assert resp.status_code == 200, f"{tenant_id}: {resp.text}"
    body = resp.json()
    assert isinstance(body, list)


# ---------------------------------------------------------------------------
# 5) OSINT
# ---------------------------------------------------------------------------

def test_osint_entities(timed):
    # /entities is a search endpoint and requires ``q``; an empty-result
    # query is a valid 200 with [].
    resp = timed("GET", "/api/osint/entities", params={"q": "a"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)


def test_osint_query_graph(timed):
    # query-graph is POST; an empty filter returns the whole tenant graph.
    resp = timed("POST", "/api/osint/query-graph", json={})
    assert resp.status_code in (200, 422), resp.text
    if resp.status_code == 200:
        body = resp.json()
        assert "nodes" in body and "edges" in body


# ---------------------------------------------------------------------------
# 6) Supply Chain
# ---------------------------------------------------------------------------

def test_supply_chain_nodes(timed):
    resp = timed("GET", "/api/sc/nodes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)


def test_supply_chain_edges(timed):
    resp = timed("GET", "/api/sc/edges")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 7) Compliance — DB-backed score + 4 live OCI tiles
# ---------------------------------------------------------------------------

def test_compliance_score(timed):
    resp = timed("GET", "/api/compliance/score")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    frameworks = {row["framework"] for row in body}
    # All four frameworks seeded by db/seed/01_compliance_controls.sql.
    assert frameworks >= {"NIS2", "DORA", "GDPR", "VSNFD"}


@pytest.mark.parametrize("framework,expected_min", [
    ("NIS2", 12), ("DORA", 8), ("GDPR", 6), ("VSNFD", 5),
])
def test_compliance_controls_per_framework(timed, framework: str,
                                           expected_min: int):
    resp = timed("GET", f"/api/compliance/controls/{framework}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    # The response is path-scoped — rows omit ``framework`` because it's
    # implicit. We assert the count seeded by db/seed/01_compliance_controls.sql.
    assert len(body) >= expected_min, (
        f"{framework}: expected ≥{expected_min} rows, got {len(body)}"
    )
    for row in body:
        assert "control_id" in row and "code" in row and "title" in row


@pytest.mark.parametrize("tile", [
    "cloud-guard",
    "adb-encryption",
    "bucket-public-access",
    "ols-status",
])
def test_compliance_live_tile(timed, tile: str):
    """
    The four live OCI compliance tiles wired by ``live_checks.py``.

    The currently deployed compliance image predates that router, so the
    live tiles return 404. Rebuild + redeploy through OCI DevOps to flip
    these green; until then the test xfails so CI stays informative
    without hiding the gap.
    """
    resp = timed("GET", f"/api/compliance/live/{tile}")
    if resp.status_code == 404:
        pytest.xfail("live_checks router not in deployed image yet — "
                     "rebuild compliance via OCI DevOps")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert "as_of" in body
