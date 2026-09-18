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
    CONF_RAION,
    LEVEL_GREEN,
    LEVEL_RED,
    LEVEL_YELLOW,
)
from .filters import raion_alerts
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity

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
        counts = self.region_data.get("counts")
        if isinstance(counts, dict):
            attrs["counts"] = counts
        return attrs


class RadarUaLevelSensor(RadarUaSensor):
    """Alert level of the region: red / yellow / green.

    If a raion is configured in the entry, the level reflects the raion only:
    red while the raion is under alert, green otherwise.
    """

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
        """Return the machine level value (translated via options)."""
        if self._raion:
            # Raion-scoped: red only while the raion itself is under alert.
            return (
                LEVEL_RED
                if raion_alerts(self.coordinator.data, self.region_key, self._raion)
                else LEVEL_GREEN
            )
        return self.region_data.get("level")

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
        if self._raion:
            matched = raion_alerts(self.coordinator.data, self.region_key, self._raion)
            raw = matched[0].get("since") if matched else None
        else:
            raw = self.region_data.get("alert_since")
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
        return self._value_fn(self.coordinator, self.region_data)


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


def _counts_value(counts: dict[str, Any] | None, *types: str) -> int | None:
    """Sum of counts for the given threat types; None when no data."""
    if not isinstance(counts, dict):
        return None
    return sum(int(counts.get(t) or 0) for t in types)


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
                lambda coordinator_, region: _counts_value(
                    region.get("counts"), "uav"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "recon",
                "recon",
                "mdi:drone",
                lambda coordinator_, region: _counts_value(
                    region.get("counts"), "recon"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "missiles",
                "missiles",
                "mdi:rocket-launch",
                lambda coordinator_, region: _counts_value(
                    region.get("counts"), "missile", "ballistic"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "kab",
                "kab",
                "mdi:bomb",
                lambda coordinator_, region: _counts_value(
                    region.get("counts"), "kab"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "mig31k",
                "mig31k",
                "mdi:airplane-alert",
                lambda coordinator_, region: _counts_value(
                    region.get("counts"), "mig31k"
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "total",
                "total",
                "mdi:crosshairs-gps",
                lambda coordinator_, region: (
                    region.get("threat_count")
                    if isinstance(region.get("threat_count"), int)
                    else None
                ),
            ),
            RadarUaCountsSensor(
                coordinator,
                entry,
                region_key,
                "raid_size",
                "raid_size",
                "mdi:chart-bell-curve",
                lambda coordinator_, region: (
                    region.get("group_size")
                    if isinstance(region.get("group_size"), int)
                    else None
                ),
            ),
            RadarUaDataAgeSensor(coordinator, entry, region_key),
        ]
    )
