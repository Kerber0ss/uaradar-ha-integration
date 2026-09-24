"""Per-region sensors for the Radar UA integration."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTime

from .const import ATTR_UPDATED
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CITY,
    CONF_RAION,
    CONF_REFERENCE_CITY_ID,
    LEVEL_GREEN,
    LEVEL_RED,
    LEVEL_YELLOW,
    THREAT_MIG31K,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity
from .filters import alert_for_scope
from .geo.boundaries import great_circle_distance_km
from .geo.cities import city_by_id
from .parsing import counts_for_threats, is_area_only, sum_threat_units, threat_coordinates

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Diagnostics: active transport (websocket or rest fallback)."""
        attrs = dict(super().extra_state_attributes)
        attrs["transport"] = self.coordinator.transport
        return attrs


class RadarUaDistanceSensor(RadarUaSensor):
    """Distance from the reference city to the nearest located threat.

    Created only for entries with a resolvable ``reference_city_id``. The
    city is a distance anchor only: it never narrows threats by name. Only
    threats with valid finite coordinates count; ``areaOnly`` centroid
    markers and destination points are excluded. No suitable threat ->
    ``unknown`` (None); stale data -> ``unavailable`` via the shared base.
    """

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_translation_key = "distance"
    _attr_icon = "mdi:map-marker-distance"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        city: dict[str, Any],
    ) -> None:
        """Initialize with the resolved reference city (id/name/coords)."""
        super().__init__(coordinator, entry, region_key, "distance")
        self._city = city
        self._city_id = str(city.get("id") or "")
        self._city_lat = float(city["lat"])
        self._city_lon = float(city["lon"])

    @property
    def _candidates(self) -> list[tuple[float, dict[str, Any]]]:
        """(distance_km, threat) for located, non-areaOnly active threats."""
        candidates: list[tuple[float, dict[str, Any]]] = []
        for threat in self.active_threats:
            if not isinstance(threat, dict) or is_area_only(threat):
                continue
            coordinates = threat_coordinates(threat)
            if coordinates is None:
                continue
            lat, lon = coordinates
            if not (math.isfinite(lat) and math.isfinite(lon)):
                continue
            distance = great_circle_distance_km(
                self._city_lat, self._city_lon, lat, lon
            )
            candidates.append((distance, threat))
        return candidates

    @property
    def native_value(self) -> float | None:
        """Nearest great-circle distance in km, or None (unknown)."""
        nearest = self._nearest
        return round(nearest[0], 1) if nearest else None

    @property
    def _nearest(self) -> tuple[float, dict[str, Any]] | None:
        """Nearest candidate; ties broken by stable threat id."""
        best: tuple[float, dict[str, Any]] | None = None
        for candidate in self._candidates:
            if (
                best is None
                or candidate[0] < best[0]
                or (
                    candidate[0] == best[0]
                    and str(candidate[1].get("id")) < str(best[1].get("id"))
                )
            ):
                best = candidate
        return best

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Reference city and details of the nearest threat."""
        attrs = dict(super().extra_state_attributes)
        attrs["reference_city_id"] = self._city_id
        attrs["reference_city"] = self._city.get("name")
        nearest = self._nearest
        if nearest is not None:
            distance, threat = nearest
            attrs["threat_id"] = threat.get("id")
            attrs["threat_type"] = threat.get("type")
            locality = threat.get("locality")
            if locality:
                attrs["locality"] = locality
            uncertainty = threat.get("uncertaintyKm")
            if isinstance(uncertainty, (int, float)):
                attrs["uncertaintyKm"] = uncertainty
        return attrs


def _counts_value(source: list[dict[str, Any]] | None, *types: str) -> int:
    """Sum direct-API threat units by type."""
    return sum_threat_units(source, *types)


def _total_value(source: list[dict[str, Any]]) -> int:
    """Return the total number of concrete threats in the configured scope."""
    return sum_threat_units(source)


def _raid_size_value(source: list[dict[str, Any]]) -> int:
    """Raid size: sum of the ``count`` field (missing count counts as one)."""
    return sum_threat_units(source)


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Radar UA sensors for one region (config entry)."""
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    region_key: str = entry.data["region"]

    entities: list[RadarUaSensor] = [
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
            "mig31k",
            "mig31k",
            "mdi:airplane-alert",
            lambda coordinator_, threats: _counts_value(
                threats, THREAT_MIG31K
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
        RadarUaCountsSensor(
            coordinator,
            entry,
            region_key,
            "raid_size",
            "raid_size",
            "mdi:chart-bell-curve",
            lambda coordinator_, source: _raid_size_value(source),
        ),
        RadarUaDataAgeSensor(coordinator, entry, region_key),
    ]
    # Distance sensor: only for entries with a resolvable reference city.
    city_id = entry.data.get(CONF_REFERENCE_CITY_ID)
    city = city_by_id(city_id) if isinstance(city_id, str) else None
    if (
        city is not None
        and isinstance(city.get("lat"), (int, float))
        and isinstance(city.get("lon"), (int, float))
    ):
        entities.append(
            RadarUaDistanceSensor(coordinator, entry, region_key, city)
        )
    async_add_entities(entities)
