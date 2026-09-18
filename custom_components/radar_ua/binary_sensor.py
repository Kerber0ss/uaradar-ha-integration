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
ICON_RAION_ALERT = "mdi:alert-outline"
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


class RadarUaUkraineAlertsBinarySensor(RadarUaEntity, BinarySensorEntity):
    """Compact Ukraine-wide overview: on when at least one oblast is red.

    One entity for the whole country (instead of per-region entities).
    Attributes carry the alert level of every oblast.
    """

    _attr_should_poll = False
    # Friendly name is the full string (no device-name prefix).
    # _attr_name takes precedence; translation_key is kept as a fallback.
    _attr_has_entity_name = False
    _attr_name = "Radar UA: тривоги по Україні"
    _attr_translation_key = "ukraine_alerts"
    _attr_icon = ICON_UKRAINE_ALERTS

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
    ) -> None:
        """Initialize the Ukraine overview sensor."""
        super().__init__(coordinator, entry, region_key, "ukraine_alerts")
        self._attr_unique_id = f"{entry.entry_id}_ukraine_alerts"
        # Deterministic object id: binary_sensor.radar_ua_ukraine_alerts
        self.entity_id = f"binary_sensor.{DOMAIN}_ukraine_alerts"
        self._attr_device_info = device_info_for(entry)

    async def async_added_to_hass(self) -> None:
        """Fix the friendly name in the registry (device prefix otherwise)."""
        await super().async_added_to_hass()
        ent_reg = entity_registry.async_get(self.hass)
        reg_entry = ent_reg.async_get(self.entity_id)
        if reg_entry is not None and reg_entry.name is None:
            ent_reg.async_update_entity(self.entity_id, name=self._attr_name)

    @property
    def is_on(self) -> bool | None:
        """True while at least one region of Ukraine has a red alert."""
        return self._count_red() > 0

    def _levels_by_region(self) -> dict[str, str | None]:
        """Ukrainian region name -> alert level for every region."""
        data = self.coordinator.data
        result: dict[str, str | None] = {}
        if not isinstance(data, dict):
            return result
        for key, obj in (data.get("regions") or {}).items():
            if not isinstance(obj, dict):
                continue
            name = REGION_NAMES_UK.get(key) or obj.get("name") or key
            level = obj.get("level")
            result[name] = level if isinstance(level, str) else None
        return result

    def _count_red(self) -> int:
        """Number of regions currently under a red alert."""
        return sum(1 for level in self._levels_by_region().values() if level == LEVEL_RED)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Alert levels by region and the count of red regions."""
        attrs = dict(super().extra_state_attributes)
        levels = self._levels_by_region()
        attrs["alerts_by_region"] = levels
        attrs["count_alerts"] = sum(1 for lv in levels.values() if lv == LEVEL_RED)
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

    # Compact Ukraine-wide overview (single entity for the whole country).
    entities.append(RadarUaUkraineAlertsBinarySensor(coordinator, entry, region_key))

    async_add_entities(entities)
