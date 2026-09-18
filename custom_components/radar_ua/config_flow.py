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
from .const import (
    CONF_CITY,
    CONF_RAION,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_UKRAINE_OVERVIEW,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    REGION_OTHER,
)

_LOGGER = logging.getLogger(__name__)

# Ukrainian display names for region keys (from API meta).
# Used for sorting the dropdown; Ukrainian names are shown in strings/translations.
REGION_NAMES_UK: dict[str, str] = {
    "cherkaska": "Черкаська область",
    "chernihivska": "Чернігівська область",
    "chernivetska": "Чернівецька область",
    "crimea": "АР Крим",
    "dnipropetrovska": "Дніпропетровська область",
    "donetska": "Донецька область",
    "ivano-frankivska": "Івано-Франківська область",
    "kharkivska": "Харківська область",
    "khersonska": "Херсонська область",
    "khmelnytska": "Хмельницька область",
    "kirovohradska": "Кіровоградська область",
    "kyiv-city": "Київ",
    "kyivska": "Київська область",
    "luhanska": "Луганська область",
    "lvivska": "Львівська область",
    "mykolaivska": "Миколаївська область",
    "odeska": "Одеська область",
    "poltavska": "Полтавська область",
    "rivnenska": "Рівненська область",
    "sevastopol": "Севастополь",
    "sumska": "Сумська область",
    "ternopilska": "Тернопільська область",
    "vinnytska": "Вінницька область",
    "volynska": "Волинська область",
    "zakarpatska": "Закарпатська область",
    "zaporizka": "Запорізька область",
    "zhytomyrska": "Житомирська область",
}


def _sorted_region_keys(meta_regions: list[str]) -> list[str]:
    """Region keys without "other", sorted by Ukrainian name."""
    keys = [k for k in meta_regions if k != REGION_OTHER]
    return sorted(keys, key=lambda k: REGION_NAMES_UK.get(k, k))


def _region_schema(meta_regions: list[str]) -> dict[vol.Marker, Any]:
    keys = _sorted_region_keys(meta_regions)
    return {
        vol.Required(CONF_REGION): vol.In(keys),
        vol.Optional(CONF_RAION): cv.string,
        vol.Optional(CONF_CITY): cv.string,
    }


class RadarUaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Radar UA."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._meta_regions: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step: region / raion / city."""
        errors: dict[str, str] = {}

        session = async_get_clientsession(self.hass)
        client = RadarUaApiClient(session)
        meta_regions: list[str] = []
        try:
            meta = await client.async_get_meta()
            meta_regions = meta.get("regions") or []
            if not isinstance(meta_regions, list) or not meta_regions:
                raise RadarUaApiError("empty regions list")
        except RadarUaApiError:
            errors["base"] = "cannot_connect"

        if user_input is not None and not errors:
            if user_input.get(CONF_REGION) not in meta_regions:
                errors["base"] = "invalid_region"
            else:
                return self.async_create_entry(
                    title=f"Radar UA {user_input[CONF_REGION]}",
                    data={
                        CONF_REGION: user_input[CONF_REGION],
                        CONF_RAION: user_input.get(CONF_RAION) or None,
                        CONF_CITY: user_input.get(CONF_CITY) or None,
                    },
                )

        schema: dict[vol.Marker, Any] = {}
        if meta_regions:
            schema = _region_schema(meta_regions)
        else:
            # Could not load meta: keep a text field so the user can retry
            # with manual input; validation against meta will fail politely.
            schema = {
                vol.Required(CONF_REGION): cv.string,
                vol.Optional(CONF_RAION): cv.string,
                vol.Optional(CONF_CITY): cv.string,
            }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
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
                vol.Required(
                    CONF_UKRAINE_OVERVIEW,
                    default=current.get(CONF_UKRAINE_OVERVIEW, True),
                ): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors,
            description_placeholders={
                "unavailable_after": str(DEFAULT_UNAVAILABLE_AFTER),
            },
        )
