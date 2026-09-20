"""Per-region sensors for the Radar UA integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime

from .const import ATTR_UPDATED
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CITY,
    CONF_RAION,
    LEVEL_GREEN,
    LEVEL_RED,
    LEVEL_YELLOW,
)
from .filters import alert_for_scope
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity
from .parsing import counts_for_threats, sum_threat_units

ICON_LEVEL = {
    LEVEL_RED: "mdi:alert-octagon",
    LEVEL_YELLOW: "mdi:alert",
    LEVEL_GREEN: "mdi:check-circle",
}


class RadarUaSensor(RadarUaEntity, SensorEntity):
    """Base sensor with common diagnostic attributes (counts / updated)."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Common attributes plus the full counts dict and update time."""
        attrs = dict(super().extra_state_attributes)
        data = self.coordinator.data
        if isinstance(data, dict):
            attrs[ATTR_UPDATED] = data.get(ATTR_UPDATED)
        attrs["counts"] = counts_for_threats(self.active_threats)
        return attrs

    @property
    def _is_scoped(self) -> bool:
        """Whether this entry has a configured raion or legacy city slice."""
        return bool(
            self.entry.data.get(CONF_RAION) or self.entry.data.get(CONF_CITY)
        )


class RadarUaLevelSensor(RadarUaSensor):
    """The direct NEPTUN level of the configured oblast or raion."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [LEVEL_RED, LEVEL_YELLOW, LEVEL_GREEN]
    _attr_translation_key = "level"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        raion: str | None = None,
    ) -> None:
        """Initialize the level sensor for region_key (optionally raion-scoped)."""
        super().__init__(coordinator, entry, region_key, "level")
        self._raion = raion

    @property
    def native_value(self) -> str | None:
        """Use NEPTUN's level verbatim; no local threat-level calculation."""
        alert = alert_for_scope(self.coordinator.data, self.region_key, self._raion)
        return alert.get("level") if alert else LEVEL_GREEN

    @property
    def icon(self) -> str | None:
        """Level-dependent icon."""
        return ICON_LEVEL.get(self.native_value, "mdi:radar")


class RadarUaAlertSinceSensor(RadarUaSensor):
    """When the current alert started (device_class: timestamp)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "alert_since"
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        raion: str | None = None,
    ) -> None:
        """Initialize the alert_since sensor for region_key (optionally raion-scoped)."""
        super().__init__(coordinator, entry, region_key, "alert_since")
        self._raion = raion

    @property
    def native_value(self) -> datetime | None:
        """Return the parsed alert_since timestamp, or None."""
        alert = alert_for_scope(self.coordinator.data, self.region_key, self._raion)
        raw = alert.get("since") if alert else None
        if not isinstance(raw, str):
            return None
        parsed = dt_util.parse_datetime(raw)
        return parsed if parsed is not None else None


class RadarUaCountsSensor(RadarUaSensor):
    """Generic integer counter derived from region data."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        key: str,
        translation_key: str,
        icon: str,
        value_fn,
    ) -> None:
        """Initialize with a value function over (coordinator, region_data)."""
        super().__init__(coordinator, entry, region_key, key)
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._value_fn = value_fn

    @property
    def native_value(self) -> float | None:
        """Return the computed counter value (None -> unknown)."""
        return self._value_fn(self.coordinator, self.active_threats)


class RadarUaDataAgeSensor(RadarUaSensor):
    """Age of the source data in seconds (diagnostic)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:clock-outline"
    _attr_translation_key = "data_age"
    # Diagnostic entity: no state_class (excluded from statistics).

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
    ) -> None:
        """Initialize the data age sensor for region_key."""
        super().__init__(coordinator, entry, region_key, "data_age")


    @property
    def native_value(self) -> float | None:
        """Return the source data age in seconds."""
        return self.coordinator.data_age_s()


def _counts_value(source: list[dict[str, Any]] | None, *types: str) -> int:
    """Sum direct-API threat units by type."""
    return sum_threat_units(source, *types)


def _total_value(source: list[dict[str, Any]]) -> int:
    """Return the total number of concrete threats in the configured scope."""
    return sum_threat_units(source)


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Radar UA sensors for one region (config entry)."""
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    region_key: str = entry.data["region"]

    async_add_entities(
        [
            RadarUaLevelSensor(coordinator, entry, region_key, entry.data.get(CONF_RAION)),
            RadarUaAlertSinceSensor(coordinator, entry, region_key, entry.data.get(CONF_RAION)),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "drones",
                "drones",
                "mdi:quadcopter",
                lambda coordinator_, threats: _counts_value(
                    threats, "uav", "fpv"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "recon",
                "recon",
                "mdi:drone",
                lambda coordinator_, threats: _counts_value(
                    threats, "recon"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "missiles",
                "missiles",
                "mdi:rocket-launch",
                lambda coordinator_, threats: _counts_value(
                    threats, "missile", "ballistic"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "kab",
                "kab",
                "mdi:bomb",
                lambda coordinator_, threats: _counts_value(
                    threats, "kab"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "total",
                "total",
                "mdi:crosshairs-gps",
                lambda coordinator_, source: _total_value(source),
            ),
            RadarUaDataAgeSensor(coordinator, entry, region_key),
        ]
    )
