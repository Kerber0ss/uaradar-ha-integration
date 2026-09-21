"""Direct client for the public NEPTUN API."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

BASE_URL = "https://neptun.in.ua"
USER_AGENT = "radar_ua-ha/2.1.1"
TIMEOUT = 10  # seconds
ATTRIBUTION = "Дані: Карта повітряних тривог — NEPTUN (https://neptun.in.ua/)"


class RadarUaApiError(Exception):
    """Failure while reading the NEPTUN API."""


class RadarUaApiClient:
    """Read the public, read-only NEPTUN API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the client with a shared aiohttp session."""
        self._session = session
        self._headers = {"User-Agent": USER_AGENT}

    async def _get_json(self, path: str) -> dict[str, Any]:
        """GET one JSON document, converting transport failures to our error."""
        url = f"{BASE_URL}{path}"
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.get(url, headers=self._headers) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        raise RadarUaApiError(
                            f"Unexpected HTTP {resp.status} for {url}"
                        )
                    payload = await resp.json()
        except TimeoutError as err:
            raise RadarUaApiError(f"Timeout fetching {url}") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise RadarUaApiError(f"Error fetching {url}: {err}") from err
        except ValueError as err:
            raise RadarUaApiError(f"Invalid JSON from {url}: {err}") from err
        if not isinstance(payload, dict):
            raise RadarUaApiError(f"Invalid JSON object from {url}")
        return payload

    async def async_get_situation(self) -> dict[str, Any]:
        """Return direct NEPTUN threats and alert levels in one snapshot."""
        threats, alerts = await asyncio.gather(
            self._get_json("/api/v1/threats"),
            self._get_json("/api/v1/alerts"),
        )
        if not isinstance(threats.get("threats"), list):
            raise RadarUaApiError("Invalid threats payload from NEPTUN")
        if not isinstance(alerts.get("raions"), list) or not isinstance(
            alerts.get("oblasts"), list
        ):
            raise RadarUaApiError("Invalid alerts payload from NEPTUN")
        return {
            "updated": threats.get("serverTime"),
            "fetch_ok": True,
            "attribution": ATTRIBUTION,
            "threats": threats["threats"],
            "raions": alerts["raions"],
            "oblasts": alerts["oblasts"],
        }

    async def async_get_alerts(self) -> dict[str, Any]:
        """Read official oblast and raion alert levels from NEPTUN."""
        return await self._get_json("/api/v1/alerts")
