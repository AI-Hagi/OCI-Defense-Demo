"""
Tests for JammingPoller — fetch_once() lifecycle, HTTP error paths,
cache write, audit logging, and poller statistics.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.poller import JammingPoller
from app.settings import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    defaults = dict(
        adsb_api_base="http://fake-adsb.local",
        adsb_center_lat=54.0,
        adsb_center_lon=10.0,
        adsb_radius_nm=250,
        refresh_minutes=5,
        window_samples=3,
        h3_resolution=4,
        nacp_low_threshold=3,
        nacp_high_threshold=20,
        band_step=50,
        cache_ttl_hours=6,
    )
    defaults.update(overrides)
    s = MagicMock(spec=Settings)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _fake_aircraft(count: int = 10) -> list[dict]:
    return [
        {"lat": 54.0 + i * 0.01, "lon": 10.0 + i * 0.01, "NACp": 8}
        for i in range(count)
    ]


def _make_poller(settings=None, cache=None, audit=None):
    s = settings or _settings()
    c = cache or AsyncMock()
    a = audit or AsyncMock()
    return JammingPoller(settings=s, cache=c, audit=a)


def _http_response(status: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=body or {"ac": _fake_aircraft()})
    return resp


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def test_build_url_format():
    s = _settings(adsb_api_base="https://api.adsb.lol", adsb_center_lat=54.0,
                  adsb_center_lon=10.0, adsb_radius_nm=250)
    poller = _make_poller(settings=s)
    url = poller._build_url()
    assert url == "https://api.adsb.lol/v2/lat/54.0/lon/10.0/dist/250"


def test_build_url_strips_trailing_slash():
    s = _settings(adsb_api_base="https://api.adsb.lol/")
    poller = _make_poller(settings=s)
    url = poller._build_url()
    assert "/v2/lat/" in url
    assert "//" not in url.split("://")[1]


# ---------------------------------------------------------------------------
# fetch_once — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_once_ok_increments_fetches_ok():
    cache = AsyncMock()
    audit = AsyncMock()
    poller = _make_poller(cache=cache, audit=audit)

    resp = _http_response(200, {"ac": _fake_aircraft(15)})
    fake_payload = {"features": [{"type": "Feature"}], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=fake_payload):
            await poller.fetch_once()

    assert poller.fetches_ok == 1
    assert poller.fetches_failed == 0
    assert poller.fetches_total == 1


@pytest.mark.asyncio
async def test_fetch_once_writes_to_cache():
    cache = AsyncMock()
    audit = AsyncMock()
    poller = _make_poller(cache=cache, audit=audit)

    resp = _http_response(200, {"ac": _fake_aircraft(10)})
    fake_payload = {"features": [{"type": "Feature"}], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=fake_payload):
            await poller.fetch_once()

    cache.write_payload.assert_awaited_once()
    call_kwargs = cache.write_payload.await_args.kwargs
    assert call_kwargs["layer"] == "jamming"
    assert call_kwargs["classification"] == "OPEN"


@pytest.mark.asyncio
async def test_fetch_once_records_audit_row():
    cache = AsyncMock()
    audit = AsyncMock()
    poller = _make_poller(cache=cache, audit=audit)

    resp = _http_response(200, {"ac": _fake_aircraft(10)})
    fake_payload = {"features": [{"type": "Feature"}], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=fake_payload):
            await poller.fetch_once()

    audit.record_fetch.assert_awaited_once()


# ---------------------------------------------------------------------------
# fetch_once — failure paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_once_network_error_increments_failed():
    import httpx
    poller = _make_poller()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("unreachable"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller.fetch_once()

    assert poller.fetches_failed == 1
    assert poller.fetches_ok == 0


@pytest.mark.asyncio
async def test_fetch_once_non_200_status_increments_failed():
    poller = _make_poller()
    resp = _http_response(status=503)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller.fetch_once()

    assert poller.fetches_failed == 1


@pytest.mark.asyncio
async def test_fetch_once_empty_aircraft_list_increments_failed():
    poller = _make_poller()
    resp = _http_response(200, {"ac": []})

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller.fetch_once()

    assert poller.fetches_failed == 1


@pytest.mark.asyncio
async def test_fetch_once_non_json_body_increments_failed():
    poller = _make_poller()
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(side_effect=ValueError("not json"))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller.fetch_once()

    assert poller.fetches_failed == 1


@pytest.mark.asyncio
async def test_fetch_once_empty_features_does_not_overwrite_cache():
    cache = AsyncMock()
    poller = _make_poller(cache=cache)

    resp = _http_response(200, {"ac": _fake_aircraft(10)})
    # Aggregate returns empty FeatureCollection — should not write cache
    empty_payload = {"features": [], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=empty_payload):
            await poller.fetch_once()

    cache.write_payload.assert_not_awaited()
    assert poller.fetches_failed == 1


@pytest.mark.asyncio
async def test_fetch_once_accepts_aircraft_key_alias():
    """Some ADS-B providers use 'aircraft' instead of 'ac'."""
    cache = AsyncMock()
    poller = _make_poller(cache=cache)

    resp = _http_response(200, {"aircraft": _fake_aircraft(5)})
    fake_payload = {"features": [{"type": "Feature"}], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=fake_payload):
            await poller.fetch_once()

    assert poller.fetches_ok == 1


# ---------------------------------------------------------------------------
# Window stats injected into payload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_once_injects_window_stats():
    cache = AsyncMock()
    poller = _make_poller(cache=cache)

    resp = _http_response(200, {"ac": _fake_aircraft(10)})
    base_payload: dict = {"features": [{"type": "Feature"}]}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=base_payload):
            await poller.fetch_once()

    written_payload = cache.write_payload.await_args.kwargs["payload"]
    stats = written_payload.get("stats", {})
    assert "window_samples" in stats
    assert "window_max_samples" in stats
