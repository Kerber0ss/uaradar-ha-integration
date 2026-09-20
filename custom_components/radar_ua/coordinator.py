"""Data update coordinator for the Radar UA integration."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RadarUaApiClient, RadarUaApiError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .stream import NEPTUNStreamClient

_LOGGER = logging.getLogger(__name__)


class RadarUaDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the situation once and share it with all entities of an entry.

    Primary transport is the live NEPTUN WebSocket stream (one per hass,
    shared across entries); REST polling remains as the fallback and the
    poll keeps the coordinator refresh alive while the stream is down.
    """

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
        session = hass.data[DOMAIN][entry.entry_id]["session"]
        self.client = RadarUaApiClient(session)
        self.stream = self._get_or_create_stream(hass, session)

    def _get_or_create_stream(
        self, hass: HomeAssistant, session: Any
    ) -> NEPTUNStreamClient:
        """Reuse the shared stream client, or create and start a new one."""
        store = hass.data.setdefault(DOMAIN, {})
        stream: NEPTUNStreamClient | None = store.get("stream")
        if stream is None:
            stream = NEPTUNStreamClient(
                hass,
                session,
                on_update_cb=self._async_handle_stream_update,
                on_status_cb=self._async_handle_stream_status,
            )
            store["stream"] = stream
            stream.async_start()
        return stream

    @callback
    def _async_handle_stream_update(self, data: dict[str, Any]) -> None:
        """Push a fresh stream snapshot to all coordinator listeners."""
        self.async_set_updated_data(data)

    @callback
    def _async_handle_stream_status(self, connected: bool) -> None:
        """Log stream connection state changes."""
        _LOGGER.debug("NEPTUN stream %s", "connected" if connected else "disconnected")

    @property
    def transport(self) -> str:
        """Active transport for diagnostics: "websocket" or "rest"."""
        return "websocket" if self.stream.snapshot() is not None else "rest"

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the live stream snapshot, or fall back to the REST API.

        Retries with exponential backoff are handled by the coordinator's
        default behaviour (UpdateFailed + scheduled refresh).
        """
        snapshot = self.stream.snapshot()
        if snapshot is not None:
            return snapshot
        try:
            return await self.client.async_get_situation()
        except RadarUaApiError as err:
            raise UpdateFailed(f"Error communicating with NEPTUN API: {err}") from err

    def data_age_s(self) -> float | None:
        """Age of the source data in seconds.

        Uses the direct API ``serverTime`` copied to ``updated`` (REST) or the
        WS frame ``ts`` (ISO 8601 string). Returns None when it cannot be
        determined.
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
