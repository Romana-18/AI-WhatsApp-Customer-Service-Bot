"""Shared pytest safeguards."""

import os

import httpx
import pytest


@pytest.fixture(autouse=True)
def block_external_http(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deny real HTTP by default while preserving MockTransport and ASGI transports."""

    live_requested = request.node.get_closest_marker("live") is not None
    if live_requested and os.getenv("RUN_LIVE_TESTS") == "1":
        return

    def blocked_sync(*args: object, **kwargs: object) -> httpx.Response:
        raise RuntimeError(
            "Outbound HTTP is disabled in tests; use HTTPX MockTransport or an opt-in live test"
        )

    async def blocked_async(*args: object, **kwargs: object) -> httpx.Response:
        raise RuntimeError(
            "Outbound HTTP is disabled in tests; use HTTPX MockTransport or an opt-in live test"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked_async)
