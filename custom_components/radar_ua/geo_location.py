"""Geolocation entities (map targets) for the Radar UA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .binary_sensor import region_device_info
from .const import (
    CONF_REGION,
    CONF_UKRAINE_OVERVIEW,
    DOMAIN,
    THREAT_BALLISTIC,
    THREAT_KAB,
    THREAT_MIG31K,
    THREAT_MISSILE,
    THREAT_RECON,
    THREAT_UAV,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity
from .filters import region_threats

THREAT_ICONS = {
    THREAT_UAV: "mdi:quadcopter",
    THREAT_RECON: "mdi:drone",
    THREAT_MISSILE: "mdi:rocket-launch",
    THREAT_BALLISTIC: "mdi:rocket",
    THREAT_KAB: "mdi:airplane-bomb",
    THREAT_MIG31K: "mdi:fighter-jet",
    "fpv": "mdi:crosshairs-gps",
}
ICON_UNKNOWN_THREAT = "mdi:crosshairs-gps"


def threat_icon(threat_type: str | None) -> str:
    """Icon for a threat type."""
    return THREAT_ICONS.get(threat_type or "", ICON_UNKNOWN_THREAT)


class RadarUaGeolocationEvent(RadarUaEntity, GeolocationEvent):
    """One active threat on the map.

    Entities are created from the setup-time snapshot and for new threats
    arriving between updates (platform-level coordinator listener). A threat
    that disappears from the API keeps its entity but loses its coordinates
    (latitude/longitude -> None), so it automatically disappears from the HA
    map.
    """

    # The friendly name is the threat title (e.g. "БпЛА") shown on the map;
    # no device-name prefix.
    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        threat: dict[str, Any],
        overview: bool,
    ) -> None:
        """Initialize from a threat object of the latest snapshot."""
        threat_id = str(threat.get("id"))
        super().__init__(coordinator, entry, region_key, f"geo_{threat_id}")
        # Contract: unique_id = <entry_id>_geo_<threat_id>
        self._attr_unique_id = f"{entry.entry_id}_geo_{threat_id}"
        self._threat_id = threat_id
        self._overview = overview
        self._last_title: str | None = threat.get("title") or None
        self._threat: dict[str, Any] | None = threat
        self._attr_device_info = region_device_info(
            entry, region_key, self._region_display_name(region_key)
        )

    def _region_display_name(self, region_key: str) -> str:
        """Ukrainian display name of a region key from the current data."""
        obj = self.coordinator.region(region_key)
        name = obj.get("name")
        if isinstance(name, str) and name:
            return name
        return region_key

    @property
    def source(self) -> tuple[str, str]:
        """Source of the event (used by the map to group entities)."""
        return (DOMAIN, self.entry.entry_id)

    @property
    def name(self) -> str | None:
        """Threat title (kept after the threat disappears from the API)."""
        if self._threat is not None:
            title = self._threat.get("title")
            if title:
                return str(title)
        if self._last_title:
            return self._last_title
        return f"Threat {self._threat_id}"

    @property
    def latitude(self) -> float | None:
        """Latitude of the threat, None once it is gone from the API."""
        if self._threat is None:
            return None
        value = self._threat.get("lat")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def longitude(self) -> float | None:
        """Longitude of the threat, None once it is gone from the API."""
        if self._threat is None:
            return None
        value = self._threat.get("lon")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def icon(self) -> str | None:
        """Icon by threat type."""
        if self._threat is None:
            return ICON_UNKNOWN_THREAT
        return threat_icon(self._threat.get("type"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Threat details as attributes."""
        attrs = dict(super().extra_state_attributes)
        if self._threat is not None:
            attrs.update(
                {
                    "type": self._threat.get("type"),
                    "count": self._threat.get("count"),
                    "heading": self._threat.get("heading"),
                    "confidenceLevel": self._threat.get("confidenceLevel"),
                    "locality": self._threat.get("locality"),
                    "district": self._threat.get("district"),
                    "updatedAt": self._threat.get("updatedAt"),
                    "explanationShort": self._threat.get("explanationShort"),
                }
            )
        attrs["threat_id"] = self._threat_id
        return attrs

    def _find_threat(self) -> dict[str, Any] | None:
        """Locate this threat id in the current coordinator data."""
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        regions = data.get("regions") or {}
        keys = (
            list(regions.keys())
            if self._overview
            else [self.region_key]
        )
        for region_key in keys:
            for threat in region_threats(data, region_key):
                if str(threat.get("id")) == self._threat_id:
                    return threat
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-read the threat from the latest data."""
        self._threat = self._find_threat()
        if self._threat is not None:
            title = self._threat.get("title")
            if title:
                self._last_title = str(title)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up geolocation entities for all active threats.

    Entities for the snapshot available at setup are created immediately;
    threats that appear later are added via the platform callback from a
    coordinator listener. Disappeared threats keep their entity but lose
    their coordinates (hidden from the map).
    """
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    main_region: str = entry.data.get(CONF_REGION) or ""
    overview: bool = bool(entry.options.get(CONF_UKRAINE_OVERVIEW, True))

    # threat id -> entity; mirrored to hass.data for introspection.
    existing: dict[str, RadarUaGeolocationEvent] = {}

    def region_keys() -> list[str]:
        """Regions whose threats get a geolocation entity."""
        data = coordinator.data
        if not isinstance(data, dict):
            return []
        regions = data.get("regions") or {}
        if overview:
            return list(regions.keys())
        return [main_region] if main_region in regions else []

    def collect_threats() -> dict[str, tuple[dict[str, Any], str]]:
        """Active threats by id, with the region key they were found in."""
        found: dict[str, tuple[dict[str, Any], str]] = {}
        for region_key in region_keys():
            for threat in region_threats(coordinator.data, region_key):
                threat_id = threat.get("id")
                if threat_id is None:
                    continue
                key = str(threat_id)
                if key not in found:
                    found[key] = (threat, region_key)
        return found

    @callback
    def _add_new_entities() -> None:
        """Create entities for threats not seen before."""
        found = collect_threats()
        new_entities: list[RadarUaGeolocationEvent] = []
        for threat_id, (threat, region_key) in found.items():
            if threat_id in existing:
                continue
            entity = RadarUaGeolocationEvent(
                coordinator, entry, region_key, threat, overview
            )
            existing[threat_id] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})[
        "geo_entities"
    ] = existing
