"""
Pytest fixtures for live-LB integration tests.

Targets the public OCI Native Ingress Controller LB by default. Override
with ``SOVDEFENCE_BASE_URL`` (e.g. ``http://localhost:8080``) when running
against a port-forward.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any

import httpx
import pytest

DEFAULT_BASE_URL = "http://152.70.18.236"
DEFAULT_TENANT = "T001"


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("SOVDEFENCE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def tenant() -> str:
    return os.environ.get("SOVDEFENCE_TENANT", DEFAULT_TENANT)


@pytest.fixture(scope="session")
def client(base_url: str, tenant: str) -> httpx.Client:
    """Single shared client; per-test latency is captured via the timings dict."""
    headers = {"X-Tenant-Id": tenant, "User-Agent": "sovdefence-integration-tests/1.0"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=15.0) as c:
        yield c


@pytest.fixture(scope="session")
def timings() -> dict[str, list[float]]:
    """Per-endpoint list of wall-clock millis. Aggregated in the report fixture."""
    return defaultdict(list)


@pytest.fixture
def timed(client: httpx.Client, timings: dict[str, list[float]]):
    """Wrap an httpx GET/POST call; record millis under the path key."""

    def _call(method: str, path: str, **kw: Any) -> httpx.Response:
        t0 = time.perf_counter()
        resp = client.request(method, path, **kw)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings[path].append(elapsed_ms)
        return resp

    return _call


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


@pytest.fixture(scope="session", autouse=True)
def report_latencies(timings: dict[str, list[float]]):
    """At the end of the session, print a markdown table with p50/p95/p99."""
    yield
    if not timings:
        return
    lines = [
        "",
        "## Latency report",
        "",
        "| Endpoint | N | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for path in sorted(timings.keys()):
        v = timings[path]
        lines.append(
            f"| `{path}` | {len(v)} | {_percentile(v, 50):.0f} | "
            f"{_percentile(v, 95):.0f} | {_percentile(v, 99):.0f} | {max(v):.0f} |"
        )
    print("\n".join(lines))
