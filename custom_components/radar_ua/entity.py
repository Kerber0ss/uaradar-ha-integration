"""Base entity for the Radar UA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ATTRIBUTION, ATTR_FETCH_OK, ATTR_SOURCE_AGE_S, DOMAIN
from .coordinator import RadarUaDataUpdateCoordinator


class RadarUaEntity(CoordinatorEntity[RadarUaDataUpdateCoordinator], Entity):
    """Common base: unique_id, device_info, attribution, availability by data age."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        key: str,
    ) -> None:
        """Initialize the entity.

        key is the entity slug (e.g. "level", "alert", "geo_<threat_id>").
        """
        super().__init__(coordinator)
        self.entry = entry
        self.region_key = region_key
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{region_key}_{key}"
        # Language-independent entity_id (e.g. sensor.radar_ua_sumska_level).
        self._attr_suggested_object_id = f"{DOMAIN}_{region_key}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Radar UA {region_key}",
            manufacturer="Radar UA",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://neptun.in.ua/",
        )

    @property
    def region_data(self) -> dict[str, Any]:
        """The region object from the latest coordinator data."""
        return self.coordinator.region(self.region_key)

    @property
    def attribution(self) -> str | None:
        """Attribution string from the API data."""
        if isinstance(self.coordinator.data, dict):
            return self.coordinator.data.get(ATTR_ATTRIBUTION)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Common diagnostic attributes."""
        attrs: dict[str, Any] = {}
        if isinstance(self.coordinator.data, dict):
            attrs[ATTR_FETCH_OK] = self.coordinator.data.get(ATTR_FETCH_OK)
            attrs[ATTR_SOURCE_AGE_S] = self.coordinator.data.get(ATTR_SOURCE_AGE_S)
            attribution = self.attribution
            if attribution:
                attrs[ATTR_ATTRIBUTION] = attribution
        return attrs

    @property
    def available(self) -> bool:
        """Available when the last update succeeded and data is fresh enough."""
        if not self.coordinator.last_update_success:
            return False
        return not self.coordinator.is_data_stale()
