"""Unit tests for custom_components/radar_ua/api.py with a mocked HTTP session."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import aiohttp
import pytest

from radar_ua import api
from radar_ua.api import RadarUaApiClient, RadarUaApiError

from .conftest import load_situation


class FakeResponse:
    """Minimal stand-in for aiohttp.ClientResponse (async context manager)."""

    def __init__(self, payload=None, status=200, exc: Exception | None = None):
        self._payload = payload
        self.status = status
        self._exc = exc
        self.json = AsyncMock(return_value=payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Records every get() call; returns a preconfigured response or raises."""

    def __init__(self, response: FakeResponse | None = None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.response


@pytest.fixture()
def client_factory():
    def _make(session):
        return RadarUaApiClient(session)

    return _make


class TestSuccessfulRequests:
    async def test_situation_returns_parsed_json(self, client_factory):
        payload = load_situation()
        session = FakeSession(FakeResponse(payload))
        client = client_factory(session)

        data = await client.async_get_situation()

        assert data["fetch_ok"] is True
        assert "sumska" in data["regions"]
        url, kwargs = session.calls[0]
        assert url == f"{api.BASE_URL}/v1/situation"

    async def test_meta(self, client_factory):
        payload = {"regions": ["sumska", "poltavska"], "poll_interval_s": 10}
        session = FakeSession(FakeResponse(payload))
        client = client_factory(session)

        assert await client.async_get_meta() == payload
        assert session.calls[0][0] == f"{api.BASE_URL}/v1/meta"

    async def test_health(self, client_factory):
        payload = {"ok": True, "source_age_s": 4.2}
        session = FakeSession(FakeResponse(payload))
        client = client_factory(session)

        assert (await client.async_get_health())["ok"] is True
        assert session.calls[0][0] == f"{api.BASE_URL}/health"


class TestUserAgent:
    async def test_user_agent_header_sent(self, client_factory):
        session = FakeSession(FakeResponse(load_situation()))
        client = client_factory(session)

        await client.async_get_situation()

        _, kwargs = session.calls[0]
        assert kwargs["headers"] == {"User-Agent": api.USER_AGENT}
        assert api.USER_AGENT.startswith("radar_ua-ha/")


class TestErrors:
    async def test_http_500_raises_api_error(self, client_factory):
        session = FakeSession(FakeResponse(status=500))
        client = client_factory(session)

        with pytest.raises(RadarUaApiError, match="500"):
            await client.async_get_situation()

    async def test_http_404_raises_api_error(self, client_factory):
        session = FakeSession(FakeResponse(status=404))
        client = client_factory(session)

        with pytest.raises(RadarUaApiError):
            await client.async_get_meta()

    async def test_network_error_raises_api_error(self, client_factory):
        session = FakeSession(exc=aiohttp.ClientConnectionError("connection refused"))
        client = client_factory(session)

        with pytest.raises(RadarUaApiError, match="connection refused"):
            await client.async_get_situation()

    async def test_timeout_raises_api_error(self, client_factory):
        session = FakeSession(exc=asyncio.TimeoutError())
        client = client_factory(session)

        with pytest.raises(RadarUaApiError, match="Timeout fetching"):
            await client.async_get_health()

    async def test_invalid_json_raises_api_error(self, client_factory):
        resp = FakeResponse(status=200)
        resp.json = AsyncMock(side_effect=ValueError("bad json"))
        session = FakeSession(resp)
        client = client_factory(session)

        with pytest.raises(RadarUaApiError, match="Invalid JSON"):
            await client.async_get_situation()

    async def test_api_error_is_exception_subclass(self):
        assert issubclass(RadarUaApiError, Exception)
