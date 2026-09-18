"""Binary sensors for the Radar UA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ATTRIBUTION,
    ATTR_FETCH_OK,
    ATTR_SOURCE_AGE_S,
    CONF_RAION,
    CONF_REGION,
    CONF_UKRAINE_OVERVIEW,
    DOMAIN,
    LEVEL_RED,
    THREAT_MIG31K,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity
from .filters import raion_alerts, region_threats

ICON_ALERT = "mdi:alert-rhombus"
ICON_ADVISORY = "mdi:fighter-jet"
ICON_RAION_ALERT = "mdi:alert-outline"


def region_device_info(
    entry: ConfigEntry, region_key: str, region_name: str
) -> DeviceInfo:
    """Device info for an overview region (separate per-region device)."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_region_{region_key}")},
        name=f"Radar UA {region_name}",
        manufacturer="Radar UA",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://neptun.in.ua/",
    )


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


class RadarUaOverviewAlertBinarySensor(
    CoordinatorEntity[RadarUaDataUpdateCoordinator], BinarySensorEntity
):
    """Overview alert for one region of Ukraine (disabled by default).

    Created for every key of situation.regions (including "other"), except
    the main region of the instance (which already has a primary sensor).
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False
    _attr_icon = ICON_ALERT
    _attr_translation_key = "overview_alert"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
        region_name: str,
    ) -> None:
        """Initialize the overview sensor for region_key."""
        super().__init__(coordinator)
        self._overview_region_key = region_key
        self._attr_unique_id = f"{entry.entry_id}_overview_{region_key}_alert"
        self._attr_suggested_object_id = f"{DOMAIN}_overview_{region_key}_alert"
        self._attr_device_info = region_device_info(entry, region_key, region_name)

    @property
    def region_data(self) -> dict[str, Any]:
        """The observed region object from the latest coordinator data."""
        return self.coordinator.region(self._overview_region_key)

    @property
    def is_on(self) -> bool | None:
        """True while the observed region has a red alert."""
        return self.region_data.get("level") == LEVEL_RED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Common diagnostic attributes."""
        attrs: dict[str, Any] = {}
        data = self.coordinator.data
        if isinstance(data, dict):
            attrs[ATTR_FETCH_OK] = data.get(ATTR_FETCH_OK)
            attrs[ATTR_SOURCE_AGE_S] = data.get(ATTR_SOURCE_AGE_S)
            attribution = data.get(ATTR_ATTRIBUTION)
            if attribution:
                attrs[ATTR_ATTRIBUTION] = attribution
        attrs["region_key"] = self._overview_region_key
        attrs["level"] = self.region_data.get("level")
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

    if entry.options.get(CONF_UKRAINE_OVERVIEW, True):
        region_names: dict[str, str] = {}
        data = coordinator.data
        if isinstance(data, dict):
            for key, obj in (data.get("regions") or {}).items():
                if isinstance(obj, dict):
                    region_names[key] = obj.get("name") or key
        # One overview sensor per region of the whole Ukraine (including
        # "other"), excluding the main region of this instance.
        for key in sorted(region_names):
            if key == region_key:
                continue
            entities.append(
                RadarUaOverviewAlertBinarySensor(
                    coordinator, entry, key, region_names[key]
                )
            )

    async_add_entities(entities)
