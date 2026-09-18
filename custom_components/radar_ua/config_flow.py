"""Config and options flow for the Radar UA integration."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RadarUaApiClient, RadarUaApiError
from .raions import RAIONS, REGION_NAMES_UK  # noqa: F401  (re-exported)
from .const import (
    CONF_CITY,
    CONF_RAION,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    REGION_OTHER,
)

_LOGGER = logging.getLogger(__name__)

# Raion dropdown value meaning "skip" (no raion filtering).
RAION_SKIP_CHOICE = ""

# Ukrainian collation order for sorting dropdown options.
_UK_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя’'"


def _uk_sort_key(text: str) -> tuple[int, ...]:
    """Sort key that follows the Ukrainian alphabet order."""
    return tuple(
        _UK_ALPHABET.index(ch) if ch in _UK_ALPHABET else 1000 + ord(ch)
        for ch in text.lower()
    )


def _region_options(meta_regions: list[str]) -> dict[str, str]:
    """Region key -> Ukrainian label, without "other", sorted by Ukrainian name."""
    options = {
        key: REGION_NAMES_UK.get(key, key)
        for key in meta_regions
        if key != REGION_OTHER
    }
    return dict(sorted(options.items(), key=lambda item: _uk_sort_key(item[1])))


def _raion_options(raions: list[str]) -> dict[str, str]:
    """Build the raion-step dropdown: skip choice, then raions."""
    options: dict[str, str] = {
        RAION_SKIP_CHOICE: "— Пропустити —",
    }
    options.update({raion: raion for raion in sorted(raions, key=_uk_sort_key)})
    return options


class RadarUaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Radar UA."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._meta_regions: list[str] = []
        self._region: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the first step: oblast selection."""
        errors: dict[str, str] = {}

        if not self._meta_regions:
            session = async_get_clientsession(self.hass)
            client = RadarUaApiClient(session)
            try:
                meta = await client.async_get_meta()
                meta_regions = meta.get("regions") or []
                if not isinstance(meta_regions, list) or not meta_regions:
                    raise RadarUaApiError("empty regions list")
                self._meta_regions = meta_regions
            except RadarUaApiError:
                errors["base"] = "cannot_connect"

        if user_input is not None and not errors:
            region = user_input.get(CONF_REGION)
            if region not in self._meta_regions:
                errors["base"] = "invalid_region"
            else:
                self._region = region
                return await self.async_step_raions()

        if self._meta_regions:
            schema: dict[vol.Marker, Any] = {
                vol.Required(CONF_REGION): vol.In(
                    _region_options(self._meta_regions)
                )
            }
        else:
            # Could not load meta: keep a text field so the user can retry
            # with manual input; validation against meta will fail politely.
            schema = {vol.Required(CONF_REGION): cv.string}

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_raions(self, user_input: dict[str, Any] | None = None):
        """Handle the second step: raion / city for the chosen oblast."""
        region = self._region or ""
        raions = RAIONS.get(region, [])

        if user_input is not None:
            raion: str | None = None
            if raions:
                raion = user_input.get(CONF_RAION)
                raion = (raion or "").strip() or None
                if raion == RAION_SKIP_CHOICE:
                    raion = None
            return self.async_create_entry(
                title=f"Radar UA {REGION_NAMES_UK.get(region, region)}",
                data={
                    CONF_REGION: region,
                    CONF_RAION: raion,
                    CONF_CITY: (user_input.get(CONF_CITY) or "").strip() or None,
                },
                # Defaults for the options flow: without them HA opens the
                # options dialog right after the config entry is created
                # (second unwanted popup). With options pre-filled the
                # entry is complete and no extra dialog is shown.
                options={
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                },
            )

        schema: dict[vol.Marker, Any] = {}
        if raions:
            # Static raion list: dropdown with a skip choice.
            schema[vol.Optional(CONF_RAION, default=RAION_SKIP_CHOICE)] = vol.In(
                _raion_options(raions)
            )
        # Kyiv and Sevastopol have no raions: only the city field is shown.
        schema[vol.Optional(CONF_CITY)] = cv.string

        return self.async_show_form(
            step_id="raions",
            data_schema=vol.Schema(schema),
            description_placeholders={"region": REGION_NAMES_UK.get(region, region)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> RadarUaOptionsFlow:
        """Return the options flow handler."""
        return RadarUaOptionsFlow(config_entry)


class RadarUaOptionsFlow(config_entries.OptionsFlow):
    """Handle the options flow for Radar UA."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Store the config entry being edited."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if not isinstance(scan_interval, int) or not (
                MIN_SCAN_INTERVAL <= scan_interval <= 3600
            ):
                errors["base"] = "invalid_scan_interval"
            else:
                return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors,
            description_placeholders={
                "unavailable_after": str(DEFAULT_UNAVAILABLE_AFTER),
            },
        )
