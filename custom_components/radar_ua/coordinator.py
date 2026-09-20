"""Data update coordinator for the Radar UA integration."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RadarUaApiClient, RadarUaApiError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class RadarUaDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the situation once and share it with all entities of an entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator from the config entry options."""
        try:
            interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        except (TypeError, ValueError):
            interval = DEFAULT_SCAN_INTERVAL
        update_interval = max(MIN_SCAN_INTERVAL, interval)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=update_interval),
        )
        self.entry = entry
        self.client = RadarUaApiClient(hass.data[DOMAIN][entry.entry_id]["session"])

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the direct NEPTUN snapshot; raise UpdateFailed on error.

        Retries with exponential backoff are handled by the coordinator's
        default behaviour (UpdateFailed + scheduled refresh).
        """
        try:
            return await self.client.async_get_situation()
        except RadarUaApiError as err:
            raise UpdateFailed(f"Error communicating with NEPTUN API: {err}") from err

    def data_age_s(self) -> float | None:
        """Age of the source data in seconds.

        Uses the direct API ``serverTime`` copied to ``updated``. Returns None
        when it cannot be determined.
        """
        data = self.data
        if not isinstance(data, dict):
            return None
        updated = data.get("updated")
        if isinstance(updated, (int, float)):
            return max(0.0, time.time() - float(updated))
        if isinstance(updated, str):
            try:
                parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except ValueError:
                return None
            return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
        return None

    def region(self, region_key: str) -> dict[str, Any]:
        """Return legacy display metadata for a configured region key."""
        return {"key": region_key}

    @property
    def unavailable_after(self) -> int:
        """Seconds of data age after which entities should become unavailable."""
        return DEFAULT_UNAVAILABLE_AFTER

    def is_data_stale(self) -> bool:
        """True when data is older than the unavailability threshold."""
        age = self.data_age_s()
        return age is None or age > self.unavailable_after
