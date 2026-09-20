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
from .filters import alert_for_scope
from .raions import REGION_NAMES_UK

ICON_ALERT = "mdi:alert-rhombus"
ICON_ADVISORY = "mdi:airplane-alert"
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


class RadarUaAdvisoryBinarySensor(RadarUaBinarySensor):
    """Advisory proxy: a MiG-31K threat is active in the configured scope.

    A threat with ``type == "mig31k"`` (or an explicit ``advisory`` flag)
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
        """True when any active threat in scope is advisory/MiG-31K."""
        return any(self._is_advisory(threat) for threat in self.active_threats)

    @staticmethod
    def _is_advisory(threat: dict[str, Any]) -> bool:
        """Advisory flag or the MiG-31K type marks an advisory threat."""
        return threat.get("advisory") is True or threat.get("type") == THREAT_MIG31K

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the ids of currently detected MiG-31K threats."""
        attrs = dict(super().extra_state_attributes)
        advisory = [threat for threat in self.active_threats if self._is_advisory(threat)]
        attrs["mig31k_ids"] = [
            threat.get("id")
            for threat in advisory
            if threat.get("type") == THREAT_MIG31K
        ]
        attrs["advisory_count"] = len(advisory)
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


class RadarUaUkraineAlertsBinarySensor(RadarUaEntity, BinarySensorEntity):
    """Compact Ukraine-wide overview: on when at least one oblast is red.

    One entity for the whole country (instead of per-region entities).
    Attributes carry the alert level of every oblast.
    """

    _attr_has_entity_name = False
    # Friendly name is the full string (no device-name prefix).
    # _attr_name takes precedence; translation_key is kept as a fallback.
    _attr_name = "Тривоги по Україні"
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

    @property
    def is_on(self) -> bool | None:
        """True while at least one oblast of Ukraine has a red alert."""
        return self._count_red() > 0

    def _levels_by_region(self) -> dict[str, str | None]:
        """Oblast display name -> alert level for every oblast."""
        data = self.coordinator.data
        result: dict[str, str | None] = {}
        if not isinstance(data, dict):
            return result
        for item in data.get("oblasts") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or REGION_NAMES_UK.get(item.get("key"), "")
            if not name:
                continue
            level = item.get("level")
            result[name] = level if isinstance(level, str) else None
        return result

    def _count_red(self) -> int:
        """Number of oblasts currently under a red alert."""
        return sum(1 for level in self._levels_by_region().values() if level == LEVEL_RED)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Alert levels by region and the count of red regions."""
        attrs = dict(super().extra_state_attributes)
        levels = self._levels_by_region()
        attrs["alerts_by_region"] = levels
        attrs["count_alerts"] = sum(1 for lv in levels.values() if lv == LEVEL_RED)
        return attrs


def _has_ukraine_alerts_entity(hass, entry: ConfigEntry) -> bool:
    """Whether the single Ukraine overview entity already exists."""
    registry = entity_registry.async_get(hass)
    return any(
        registry_entity.unique_id.endswith("ukraine_alerts")
        and registry_entity.platform == DOMAIN
        for registry_entity in registry.entities.values()
    )


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

    # Single Ukraine-wide overview entity shared by all config entries.
    if not _has_ukraine_alerts_entity(hass, entry):
        entities.append(
            RadarUaUkraineAlertsBinarySensor(coordinator, entry, region_key)
        )

    async_add_entities(entities)
