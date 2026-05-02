"""
TokenManager unit tests — directly exercise the OAuth refresh path without
the FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


def test_token_manager_initial_fetch_and_refresh(mock_db: Any) -> None:  # noqa: ARG001
    """Two consecutive _refresh_once() calls update _token + refresh_count."""
    import respx
    from httpx import Response

    from app.token_manager import TokenManager
    from app.settings import get_settings

    settings = get_settings()

    async def _scenario() -> None:
        with respx.mock(assert_all_called=False) as router:
            router.post(settings.sentinel_token_url).mock(
                return_value=Response(
                    200,
                    json={
                        "access_token": "tok-A" + "x" * 200,
                        "expires_in": 1800,
                        "token_type": "Bearer",
                    },
                )
            )
            tm = TokenManager(settings)
            await tm._refresh_once()
            assert tm.has_token
            assert tm.refresh_count == 1
            t1 = tm.get_token()

            router.post(settings.sentinel_token_url).mock(
                return_value=Response(
                    200,
                    json={
                        "access_token": "tok-B" + "x" * 200,
                        "expires_in": 1800,
                        "token_type": "Bearer",
                    },
                )
            )
            await tm._refresh_once()
            assert tm.refresh_count == 2
            assert tm.get_token() != t1

    asyncio.run(_scenario())


def test_token_manager_failure_does_not_clear_token(mock_db: Any) -> None:  # noqa: ARG001
    """A 500 from upstream increments refresh_failures but keeps the cached token."""
    import respx
    from httpx import Response

    from app.token_manager import TokenManager
    from app.settings import get_settings

    settings = get_settings()

    async def _scenario() -> None:
        with respx.mock(assert_all_called=False) as router:
            router.post(settings.sentinel_token_url).mock(
                return_value=Response(
                    200,
                    json={"access_token": "good-token-" + "y" * 200, "expires_in": 1800},
                )
            )
            tm = TokenManager(settings)
            await tm._refresh_once()
            cached = tm.get_token()

            router.post(settings.sentinel_token_url).mock(
                return_value=Response(500, text="upstream down")
            )
            await tm._refresh_once()
            assert tm.refresh_failures == 1
            # Cached token still present.
            assert tm.get_token() == cached

    asyncio.run(_scenario())


def test_token_manager_cold_start_get_token_raises(mock_db: Any) -> None:  # noqa: ARG001
    from app.token_manager import TokenManager, TokenError
    from app.settings import get_settings

    tm = TokenManager(get_settings())
    with pytest.raises(TokenError):
        tm.get_token()
