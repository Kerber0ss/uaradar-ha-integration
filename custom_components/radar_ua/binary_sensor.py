"""Binary sensors for the Radar UA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry

from .const import (
    CONF_RAION,
    CONF_REGION,
    DOMAIN,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity
from .filters import alert_for_scope
from .raions import REGION_NAMES_UK

ICON_ALERT = "mdi:alert-rhombus"
ICON_RAION_ALERT = "mdi:map-marker-alert-outline"
ICON_UKRAINE_ALERTS = "mdi:map-marker-alert"


class RadarUaBinarySensor(RadarUaEntity, BinarySensorEntity):
    """Base binary sensor for the configured region."""


class RadarUaAlertBinarySensor(RadarUaBinarySensor):
    """Alert of the whole configured region (level == red)."""

    # No device_class on purpose: "safety" would change semantics in automations.
    _attr_icon = ICON_ALERT
    _attr_translation_key = "alert"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
    ) -> None:
        """Initialize the alert binary sensor for region_key."""
        super().__init__(coordinator, entry, region_key, "alert")

    @property
    def is_on(self) -> bool | None:
        """True only when NEPTUN reports an oblast-wide alert."""
        return alert_for_scope(self.coordinator.data, self.region_key, None) is not None


class RadarUaRaionAlertBinarySensor(RadarUaBinarySensor):
    """Alert in the configured raion (case-insensitive substring match)."""

    _attr_icon = ICON_RAION_ALERT
    _attr_translation_key = "raion_alert"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        raion: str,
    ) -> None:
        """Initialize with the raion name from the config entry."""
        super().__init__(coordinator, entry, region_key, "raion_alert")
        self._raion = raion

    @property
    def is_on(self) -> bool | None:
        """True when NEPTUN reports an alert in the configured raion."""
        return alert_for_scope(self.coordinator.data, self.region_key, self._raion) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Matched raions under alert (name + since)."""
        attrs = dict(super().extra_state_attributes)
        alert = alert_for_scope(self.coordinator.data, self.region_key, self._raion)
        attrs["matched_raions"] = [
            {"name": alert.get("name"), "since": alert.get("since"), "level": alert.get("level")}
        ] if alert else []
        return attrs



async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Radar UA binary sensors for one config entry."""
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    region_key: str = entry.data.get(CONF_REGION) or ""

    entities: list = [
        RadarUaAlertBinarySensor(coordinator, entry, region_key),
    ]

    raion = entry.data.get(CONF_RAION)
    if raion:
        entities.append(
            RadarUaRaionAlertBinarySensor(coordinator, entry, region_key, raion)
        )

    async_add_entities(entities)
