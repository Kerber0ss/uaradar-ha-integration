"""Refresh button for the Radar UA integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry

from .const import CONF_REGION
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity


class RadarUaRefreshButton(RadarUaEntity, ButtonEntity):
    """Force an immediate coordinator refresh (button.radar_ua_<region>_refresh)."""

    # No device_class (RESTART would be misleading); simple refresh action.
    _attr_icon = "mdi:refresh"
    _attr_translation_key = "refresh"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, entry, region_key, "refresh")

    async def async_press(self) -> None:
        """Request an immediate coordinator refresh."""
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the refresh button for one config entry."""
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    region_key: str = entry.data.get(CONF_REGION) or ""
    async_add_entities([RadarUaRefreshButton(coordinator, entry, region_key)])
