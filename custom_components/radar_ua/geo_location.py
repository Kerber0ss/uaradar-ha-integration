"""Geolocation entities (map targets) for the Radar UA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry

from .const import (
    CONF_REGION,
    DOMAIN,
    THREAT_BALLISTIC,
    THREAT_KAB,
    THREAT_MIG31K,
    THREAT_MISSILE,
    THREAT_RECON,
    THREAT_UAV,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity, device_info_for
from .filters import region_threats

THREAT_ICONS = {
    THREAT_UAV: "mdi:quadcopter",
    THREAT_RECON: "mdi:drone",
    THREAT_MISSILE: "mdi:rocket-launch",
    THREAT_BALLISTIC: "mdi:rocket",
    THREAT_KAB: "mdi:bomb",
    THREAT_MIG31K: "mdi:airplane-alert",
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
    that disappears from the API gets its entity REMOVED (state and entity
    registry entry), so the device page and the map stay clean.
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
    ) -> None:
        """Initialize from a threat object of the latest snapshot."""
        threat_id = str(threat.get("id"))
        super().__init__(coordinator, entry, region_key, f"geo_{threat_id}")
        # Contract: unique_id = <entry_id>_geo_<threat_id>
        self._attr_unique_id = f"{entry.entry_id}_geo_{threat_id}"
        self._threat_id = threat_id
        self._last_title: str | None = threat.get("title") or None
        self._threat: dict[str, Any] | None = threat
        self._attr_device_info = device_info_for(entry)

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
        """Locate this threat id in the configured region of the current data."""
        return next(
            (
                threat
                for threat in region_threats(self.coordinator.data, self.region_key)
                if str(threat.get("id")) == self._threat_id
            ),
            None,
        )

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
    """Set up geolocation entities for the active threats of the configured
    oblast (regions[<region_key>].threats).

    Entities for the snapshot available at setup are created immediately;
    threats that appear later are added via the platform callback from a
    coordinator listener. When a threat disappears from the API, its entity
    and entity-registry entry are removed, so nothing accumulates on the
    device page.
    """
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    main_region: str = entry.data.get(CONF_REGION) or ""
    ent_reg = entity_registry.async_get(hass)

    # threat id -> entity; mirrored to hass.data for introspection.
    existing: dict[str, RadarUaGeolocationEvent] = {}

    def region_keys() -> list[str]:
        """Regions whose threats get a geolocation entity (main region only)."""
        data = coordinator.data
        if not isinstance(data, dict):
            return []
        regions = data.get("regions") or {}
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
    def _remove_gone_entities(found_ids: set[str]) -> None:
        """Remove entities (and registry entries) of threats that are gone."""
        for threat_id, entity in list(existing.items()):
            if threat_id in found_ids:
                continue
            del existing[threat_id]
            if entity.entity_id:
                ent_reg.async_remove(entity.entity_id)

    def _prune_stale_registry_entries(found_ids: set[str]) -> None:
        """Drop registry entries of this entry's geo entities with no live threat.

        Covers leftovers from a previous run (e.g. after an HA restart with a
        different set of active threats).
        """
        prefix = f"{entry.entry_id}_geo_"
        for reg_entry in entity_registry.async_entries_for_config_entry(
            ent_reg, entry.entry_id
        ):
            if not reg_entry.unique_id.startswith(prefix):
                continue
            if reg_entry.unique_id[len(prefix):] not in found_ids:
                ent_reg.async_remove(reg_entry.entity_id)

    @callback
    def _sync_entities() -> None:
        """Add entities for new threats, remove entities for gone threats."""
        found = collect_threats()
        _remove_gone_entities(set(found))
        _prune_stale_registry_entries(set(found))
        new_entities: list[RadarUaGeolocationEvent] = []
        for threat_id, (threat, region_key) in found.items():
            if threat_id in existing:
                continue
            entity = RadarUaGeolocationEvent(
                coordinator, entry, region_key, threat
            )
            existing[threat_id] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})[
        "geo_entities"
    ] = existing
