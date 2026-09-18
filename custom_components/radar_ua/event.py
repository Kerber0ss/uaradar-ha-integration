"""Event entity for Radar UA alerts and new threats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback

from .const import (
    CONF_CITY,
    CONF_RAION,
    CONF_REGION,
    DOMAIN,
    LEVEL_RED,
    THREAT_MIG31K,
)
from .coordinator import RadarUaDataUpdateCoordinator
from .entity import RadarUaEntity
from .filters import filtered_threats, region_threats

EVENT_ALERT_STARTED = "alert_started"
EVENT_ALERT_ENDED = "alert_ended"
EVENT_THREAT_NEW = "threat_new"


class RadarUaEventEntity(RadarUaEntity, EventEntity):
    """Events: alert_started / alert_ended / threat_new for the region.

    Level changes and new threat ids are detected here, in the coordinator
    listener callback (not in _async_update_data). The set of already seen
    threat ids lives in hass.data[DOMAIN][entry.entry_id]["seen_threats"]
    and is filled silently on the first update (no events on startup).
    """

    _attr_should_poll = False
    _attr_event_types = [EVENT_ALERT_STARTED, EVENT_ALERT_ENDED, EVENT_THREAT_NEW]
    _attr_translation_key = "events"

    def __init__(
        self,
        coordinator: RadarUaDataUpdateCoordinator,
        entry: ConfigEntry,
        region_key: str,
    ) -> None:
        """Initialize the event entity and the level-change tracker."""
        super().__init__(coordinator, entry, region_key, "events")
        self._prev_level: str | None = None
        self._primed = False

    @property
    def _seen_threats(self) -> set[str]:
        """The shared set of seen threat ids for this config entry."""
        store = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self.entry.entry_id, {}
        )
        seen = store.get("seen_threats")
        if seen is None:
            seen = set()
            store["seen_threats"] = seen
        return seen

    def _active_threats(self) -> list[dict[str, Any]]:
        """Active threats of the instance (region slice + raion/city filter)."""
        return filtered_threats(
            self.coordinator.data,
            region_threats(self.coordinator.data, self.region_key),
            self.entry.data.get(CONF_RAION),
            self.entry.data.get(CONF_CITY),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Process one coordinator update: level changes and new threats."""
        self._process_update()
        self.async_write_ha_state()

    def _process_update(self) -> None:
        """Detect alert transitions and new threats, triggering events."""
        if not self.coordinator.last_update_success:
            return  # keep the previous state on a failed fetch

        region_data = self.region_data
        level = region_data.get("level")

        if not self._primed:
            # First update: seed state without firing events.
            self._primed = True
            self._prev_level = level if isinstance(level, str) else None
            seen = self._seen_threats
            for threat in self._active_threats():
                threat_id = threat.get("id")
                if threat_id:
                    seen.add(str(threat_id))
            return

        # Alert level transitions.
        if isinstance(level, str) and level != self._prev_level:
            region_name = region_data.get("name") or self.region_key
            if level == LEVEL_RED:
                self._trigger_event(
                    EVENT_ALERT_STARTED,
                    {
                        "level": level,
                        "region": self.region_key,
                        "region_name": region_name,
                        "since": region_data.get("alert_since"),
                    },
                )
            elif self._prev_level == LEVEL_RED:
                self._trigger_event(
                    EVENT_ALERT_ENDED,
                    {
                        "level": level,
                        "region": self.region_key,
                        "region_name": region_name,
                    },
                )
            self._prev_level = level

        # New threats (id not seen before).
        seen = self._seen_threats
        for threat in self._active_threats():
            threat_id = threat.get("id")
            if not threat_id:
                continue
            key = str(threat_id)
            if key in seen:
                continue
            seen.add(key)
            self._trigger_event(
                EVENT_THREAT_NEW,
                {
                    "threat_id": key,
                    "type": threat.get("type"),
                    "title": threat.get("title"),
                    "locality": threat.get("locality"),
                    "district": threat.get("district"),
                    "region": self.region_key,
                    "is_mig31k": threat.get("type") == THREAT_MIG31K,
                },
            )


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the Radar UA event entity for one config entry."""
    coordinator: RadarUaDataUpdateCoordinator = entry.runtime_data
    region_key: str = entry.data.get(CONF_REGION) or ""
    async_add_entities([RadarUaEventEntity(coordinator, entry, region_key)])

