"""Radar UA API client."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import DOMAIN

_HOST_B64 = "cmFkYXIuc3lzbG9nLnBwLnVh"
BASE_URL = f"https://{__import__('base64').b64decode(_HOST_B64).decode()}"
USER_AGENT = "radar_ua-ha/1.0.0"
TIMEOUT = 10  # seconds


class RadarUaApiError(Exception):
    """Base error for the Radar UA API."""


class RadarUaApiClient:
    """Client for the aggregator API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the client with a shared aiohttp session."""
        self._session = session
        self._headers = {"User-Agent": USER_AGENT}

    async def _get_json(self, path: str) -> dict[str, Any]:
        """GET a JSON document, raising RadarUaApiError on any failure."""
        url = f"{BASE_URL}{path}"
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.get(url, headers=self._headers) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        raise RadarUaApiError(
                            f"Unexpected HTTP {resp.status} for {url}"
                        )
                    return await resp.json()
        except TimeoutError as err:
            raise RadarUaApiError(f"Timeout fetching {url}") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise RadarUaApiError(f"Error fetching {url}: {err}") from err
        except ValueError as err:
            raise RadarUaApiError(f"Invalid JSON from {url}: {err}") from err

    async def async_get_situation(self) -> dict[str, Any]:
        """GET situation — full Ukraine situation payload."""
        return await self._get_json("/v1/situation")

    async def async_get_meta(self) -> dict[str, Any]:
        """GET meta — list of region keys and source metadata."""
        return await self._get_json("/v1/meta")

    async def async_get_health(self) -> dict[str, Any]:
        """GET /health — service health check."""
        return await self._get_json("/health")
