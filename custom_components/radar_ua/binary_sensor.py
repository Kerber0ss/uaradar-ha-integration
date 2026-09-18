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
    LEVEL_RED,
    THREAT_MIG31K,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity, device_info_for
from .filters import raion_alerts, region_threats
from .raions import REGION_NAMES_UK

ICON_ALERT = "mdi:alert-rhombus"
ICON_ADVISORY = "mdi:fighter-jet"
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
        """True while the region is under a red alert."""
        return self.region_data.get("level") == LEVEL_RED


class RadarUaAdvisoryBinarySensor(RadarUaBinarySensor):
    """Advisory proxy: a MiG-31K threat is present in the region.

    The API has no ``advisory`` flag; a threat with ``type == "mig31k"``
    means a MiG-31K has taken off (Kinzhal carrier) — warn without sirens.
    """

    _attr_icon = ICON_ADVISORY
    _attr_translation_key = "advisory"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
    ) -> None:
        """Initialize the advisory binary sensor for region_key."""
        super().__init__(coordinator, entry, region_key, "advisory")

    @property
    def is_on(self) -> bool | None:
        """True when any active threat in the region is of type mig31k."""
        return any(
            threat.get("type") == THREAT_MIG31K
            for threat in region_threats(self.coordinator.data, self.region_key)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the ids of currently detected MiG-31K threats."""
        attrs = dict(super().extra_state_attributes)
        attrs["mig31k_ids"] = [
            threat.get("id")
            for threat in region_threats(self.coordinator.data, self.region_key)
            if threat.get("type") == THREAT_MIG31K
        ]
        return attrs


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
        """True when a raion under alert matches the configured raion."""
        return bool(raion_alerts(self.coordinator.data, self.region_key, self._raion))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Matched raions under alert (name + since)."""
        attrs = dict(super().extra_state_attributes)
        matched = raion_alerts(self.coordinator.data, self.region_key, self._raion)
        attrs["matched_raions"] = [
            {"name": item.get("name"), "since": item.get("since")} for item in matched
        ]
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
        RadarUaAdvisoryBinarySensor(coordinator, entry, region_key),
    ]

    raion = entry.data.get(CONF_RAION)
    if raion:
        entities.append(
            RadarUaRaionAlertBinarySensor(coordinator, entry, region_key, raion)
        )

    async_add_entities(entities)
