"""Tests for the direct NEPTUN API client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import aiohttp
import pytest

from radar_ua import api
from radar_ua.api import RadarUaApiClient, RadarUaApiError


class FakeResponse:
    """Minimal aiohttp response async context manager."""

    def __init__(self, payload=None, status=200):
        self.status = status
        self.json = AsyncMock(return_value=payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Return a configured response per path and retain request details."""

    def __init__(self, responses=None, exc: Exception | None = None):
        self.responses = responses or {}
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.responses[url]


def _responses():
    return {
        f"{api.BASE_URL}/api/v1/threats": FakeResponse(
            {"serverTime": "2026-09-20T15:35:00Z", "threats": []}
        ),
        f"{api.BASE_URL}/api/v1/alerts": FakeResponse({"raions": [], "oblasts": []}),
    }


async def test_situation_reads_both_official_endpoints():
    session = FakeSession(_responses())

    data = await RadarUaApiClient(session).async_get_situation()

    assert data["threats"] == []
    assert data["raions"] == []
    assert data["oblasts"] == []
    assert data["fetch_ok"] is True
    assert {url for url, _ in session.calls} == {
        f"{api.BASE_URL}/api/v1/threats",
        f"{api.BASE_URL}/api/v1/alerts",
    }


async def test_alerts_reads_official_endpoint():
    session = FakeSession(_responses())

    assert await RadarUaApiClient(session).async_get_alerts() == {"raions": [], "oblasts": []}
    assert session.calls[0][0] == f"{api.BASE_URL}/api/v1/alerts"


async def test_situation_accepts_live_alert_shape():
    """Live alerts carry key/name/oblast/since/level/reasons records."""
    responses = _responses()
    responses[f"{api.BASE_URL}/api/v1/alerts"] = FakeResponse(
        {
            "version": 1789992000,
            "updatedAt": "2026-09-20T15:35:00Z",
            "raions": [
                {
                    "key": "бахмутський",
                    "name": "Бахмутський район",
                    "oblast": "Донецька область",
                    "since": "2026-09-20T10:00:00Z",
                    "level": "red",
                    "reasons": ["БпЛА"],
                }
            ],
            "oblasts": [
                {
                    "key": "donetska",
                    "name": "Донецька область",
                    "oblast": "Донецька область",
                    "since": "2026-09-20T10:00:00Z",
                    "level": "red",
                }
            ],
        }
    )

    data = await RadarUaApiClient(FakeSession(responses)).async_get_situation()

    assert data["raions"][0]["key"] == "бахмутський"
    assert data["raions"][0]["level"] == "red"
    assert data["oblasts"][0]["oblast"] == "Донецька область"
    assert data["attribution"] == api.ATTRIBUTION


async def test_user_agent_header_sent():
    session = FakeSession(_responses())

    await RadarUaApiClient(session).async_get_situation()

    assert all(kwargs["headers"] == {"User-Agent": api.USER_AGENT} for _, kwargs in session.calls)
    assert api.USER_AGENT == "radar_ua-ha/2.1.1"


async def test_invalid_official_payload_raises_api_error():
    responses = _responses()
    responses[f"{api.BASE_URL}/api/v1/alerts"] = FakeResponse({"raions": []})

    with pytest.raises(RadarUaApiError, match="Invalid alerts"):
        await RadarUaApiClient(FakeSession(responses)).async_get_situation()


async def test_network_error_raises_api_error():
    with pytest.raises(RadarUaApiError, match="connection refused"):
        await RadarUaApiClient(
            FakeSession(exc=aiohttp.ClientConnectionError("connection refused"))
        ).async_get_alerts()


async def test_timeout_raises_api_error():
    with pytest.raises(RadarUaApiError, match="Timeout fetching"):
        await RadarUaApiClient(FakeSession(exc=asyncio.TimeoutError())).async_get_alerts()
