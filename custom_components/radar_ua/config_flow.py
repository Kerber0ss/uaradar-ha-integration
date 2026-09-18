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
    CONF_RAION_CUSTOM,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_UKRAINE_OVERVIEW,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    RAION_FREE_CHOICE,
    REGION_OTHER,
)

_LOGGER = logging.getLogger(__name__)

# Ukrainian collation order for sorting dropdown options.
_UK_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя’'"


def _uk_sort_key(text: str) -> tuple[int, ...]:
    """Sort key that follows the Ukrainian alphabet order."""
    return tuple(
        _UK_ALPHABET.index(ch) if ch in _UK_ALPHABET else 1000 + ord(ch)
        for ch in text.lower()
    )


# Ukrainian display names for region keys (from API meta).
# Used both as dropdown labels (vol.In({key: label})) and for sorting.
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


def _region_options(meta_regions: list[str]) -> dict[str, str]:
    """Region key -> Ukrainian label, without "other", sorted by Ukrainian name."""
    options = {
        key: REGION_NAMES_UK.get(key, key)
        for key in meta_regions
        if key != REGION_OTHER
    }
    return dict(sorted(options.items(), key=lambda item: _uk_sort_key(item[1])))


def _extract_districts(situation: dict[str, Any]) -> list[str]:
    """Collect unique, non-empty district names from all threats.

    Threats may live in a top-level ``threats[]`` or under
    ``regions[key].threats[]`` — handle both shapes.
    """
    threats: list[Any] = list(situation.get("threats") or [])
    regions = situation.get("regions")
    if isinstance(regions, dict):
        for region_obj in regions.values():
            if isinstance(region_obj, dict):
                threats.extend(region_obj.get("threats") or [])
    districts: set[str] = set()
    for threat in threats:
        if isinstance(threat, dict):
            district = threat.get("district")
            if isinstance(district, str) and district.strip():
                districts.add(district.strip())
    return sorted(districts, key=_uk_sort_key)


def _region_schema(
    meta_regions: list[str], districts: list[str]
) -> dict[vol.Marker, Any]:
    """Build the user-step schema.

    Regions: dropdown with Ukrainian labels. Raions: dropdown of known
    district names (from the situation payload) plus a manual-entry choice;
    falls back to a plain text field when the district list is unavailable.
    """
    schema: dict[vol.Marker, Any] = {
        vol.Required(CONF_REGION): vol.In(_region_options(meta_regions))
    }
    if districts:
        raion_options = {district: district for district in districts}
        raion_options[RAION_FREE_CHOICE] = "Інший (ввести вручну)"
        schema[vol.Optional(CONF_RAION)] = vol.In(raion_options)
        schema[vol.Optional(CONF_RAION_CUSTOM)] = cv.string
    else:
        schema[vol.Optional(CONF_RAION)] = cv.string
    schema[vol.Optional(CONF_CITY)] = cv.string
    return schema


class RadarUaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Radar UA."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._meta_regions: list[str] = []
        self._districts: list[str] = []

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

        # Collect known raion (district) names from the situation payload.
        # Failure here only disables the dropdown; a text field is shown instead.
        if not self._districts:
            try:
                situation = await client.async_get_situation()
                self._districts = _extract_districts(situation)
            except RadarUaApiError as err:
                _LOGGER.debug("Could not load district list: %s", err)

        if user_input is not None and not errors:
            if user_input.get(CONF_REGION) not in meta_regions:
                errors["base"] = "invalid_region"
            else:
                region = user_input[CONF_REGION]
                raion = user_input.get(CONF_RAION)
                if raion == RAION_FREE_CHOICE:
                    raion = (user_input.get(CONF_RAION_CUSTOM) or "").strip() or None
                else:
                    raion = (raion or "").strip() or None
                return self.async_create_entry(
                    title=f"Radar UA {REGION_NAMES_UK.get(region, region)}",
                    data={
                        CONF_REGION: region,
                        CONF_RAION: raion,
                        CONF_CITY: (user_input.get(CONF_CITY) or "").strip() or None,
                    },
                )

        schema: dict[vol.Marker, Any] = {}
        if meta_regions:
            schema = _region_schema(meta_regions, self._districts)
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
