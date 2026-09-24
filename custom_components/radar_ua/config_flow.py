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
from .geo.cities import cities_for_raion
from .raions import RAIONS, REGION_NAMES_UK  # noqa: F401  (re-exported)
from .const import (
    CONF_RAION,
    CONF_REFERENCE_CITY_ID,
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

# City dropdown value meaning "no reference city" (no distance sensor).
CITY_SKIP_CHOICE = ""

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


def _city_options(cities: list[dict[str, Any]]) -> dict[str, str]:
    """Build the city-step dropdown: no-city choice, then city names by id."""
    options: dict[str, str] = {
        CITY_SKIP_CHOICE: "— Без міста —",
    }
    options.update(
        {
            city["id"]: city["name"]
            for city in sorted(cities, key=lambda c: _uk_sort_key(c["name"]))
        }
    )
    return options


class RadarUaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Radar UA."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._meta_regions: list[str] = []
        self._region: str | None = None
        self._raion: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the first step: oblast selection."""
        errors: dict[str, str] = {}

        if not self._meta_regions:
            session = async_get_clientsession(self.hass)
            client = RadarUaApiClient(session)
            try:
                await client.async_get_alerts()
                self._meta_regions = list(REGION_NAMES_UK)
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
        """Handle the second step: raion for the chosen oblast."""
        region = self._region or ""
        raions = RAIONS.get(region, [])

        if user_input is not None:
            raion: str | None = None
            if raions:
                raion = user_input.get(CONF_RAION)
                raion = (raion or "").strip() or None
                if raion == RAION_SKIP_CHOICE:
                    raion = None
            self._raion = raion
            if raion is not None and cities_for_raion(region, raion):
                # Raion with known cities: show the reference-city step.
                return await self.async_step_city()
            # Raion skipped, or a raion without cities in the dataset:
            # finish without a reference city (no distance sensor).
            return self._async_finish_entry(None)

        schema: dict[vol.Marker, Any] = {}
        if raions:
            # Static raion list: dropdown with a skip choice.
            schema[vol.Optional(CONF_RAION, default=RAION_SKIP_CHOICE)] = vol.In(
                _raion_options(raions)
            )
        # Kyiv and Sevastopol have no raions: nothing else is shown.

        return self.async_show_form(
            step_id="raions",
            data_schema=vol.Schema(schema),
            description_placeholders={"region": REGION_NAMES_UK.get(region, region)},
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None):
        """Handle the third step: reference city within the chosen raion."""
        region = self._region or ""
        cities = cities_for_raion(region, self._raion or "")
        errors: dict[str, str] = {}

        if user_input is not None:
            city_id = user_input.get(CONF_REFERENCE_CITY_ID)
            city_id = (city_id or "").strip() or None
            if city_id == CITY_SKIP_CHOICE:
                city_id = None
            elif city_id is not None and city_id not in {
                city["id"] for city in cities
            }:
                # Defense in depth: the dropdown already limits the choices,
                # but we still validate the id against the chosen raion.
                errors["base"] = "invalid_city"
            if not errors:
                return self._async_finish_entry(city_id)

        schema: dict[vol.Marker, Any] = {
            vol.Optional(
                CONF_REFERENCE_CITY_ID, default=CITY_SKIP_CHOICE
            ): vol.In(_city_options(cities))
        }
        return self.async_show_form(
            step_id="city",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "region": REGION_NAMES_UK.get(region, region),
                "raion": self._raion or "",
            },
        )

    def _async_finish_entry(self, city_id: str | None) -> FlowResult:
        """Create the config entry with the collected region/raion/city."""
        region = self._region or ""
        return self.async_create_entry(
            title=f"Radar UA {REGION_NAMES_UK.get(region, region)}",
            data={
                CONF_REGION: region,
                CONF_RAION: self._raion,
                CONF_REFERENCE_CITY_ID: city_id,
            },
            # Defaults for the options flow: without them HA opens the
            # options dialog right after the config entry is created
            # (second unwanted popup). With options pre-filled the
            # entry is complete and no extra dialog is shown.
            options={
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            },
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
        self._new_scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._new_raion: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options: scan interval and raion for the entry region."""
        errors: dict[str, str] = {}
        region = self.config_entry.data.get(CONF_REGION) or ""
        raions = RAIONS.get(region, [])

        if user_input is not None:
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if not isinstance(scan_interval, int) or not (
                MIN_SCAN_INTERVAL <= scan_interval <= 3600
            ):
                errors["base"] = "invalid_scan_interval"
            else:
                self._new_scan_interval = scan_interval
                raion: str | None = None
                if raions:
                    raion = (user_input.get(CONF_RAION) or "").strip() or None
                    if raion == RAION_SKIP_CHOICE:
                        raion = None
                self._new_raion = raion
                if raion is not None and cities_for_raion(region, raion):
                    # Raion with known cities: ask for the reference city.
                    return await self.async_step_city()
                # Raion skipped, or a raion without cities in the dataset:
                # finish without a reference city (no distance sensor).
                return self._async_finish_options(None)

        current = self.config_entry.options
        schema_fields: dict[vol.Marker, Any] = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
        }
        if raions:
            # Preselect the raion currently stored in the entry (if any).
            current_raion = self.config_entry.data.get(CONF_RAION)
            if current_raion not in raions:
                current_raion = RAION_SKIP_CHOICE
            schema_fields[vol.Optional(CONF_RAION, default=current_raion)] = vol.In(
                _raion_options(raions)
            )
        # Kyiv and Sevastopol have no raions: only the scan interval is shown.

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema_fields), errors=errors,
            description_placeholders={
                "unavailable_after": str(DEFAULT_UNAVAILABLE_AFTER),
            },
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None):
        """Manage the reference city within the chosen raion."""
        region = self.config_entry.data.get(CONF_REGION) or ""
        cities = cities_for_raion(region, self._new_raion or "")
        errors: dict[str, str] = {}

        if user_input is not None:
            city_id = user_input.get(CONF_REFERENCE_CITY_ID)
            city_id = (city_id or "").strip() or None
            if city_id == CITY_SKIP_CHOICE:
                city_id = None
            elif city_id is not None and city_id not in {
                city["id"] for city in cities
            }:
                # Defense in depth: validate the id against the chosen raion
                # (the user could change the raion on the previous step).
                errors["base"] = "invalid_city"
            if not errors:
                return self._async_finish_options(city_id)

        current_city = self.config_entry.data.get(CONF_REFERENCE_CITY_ID)
        if current_city not in {city["id"] for city in cities}:
            current_city = CITY_SKIP_CHOICE
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_REFERENCE_CITY_ID, default=current_city
                ): vol.In(_city_options(cities)),
            }
        )
        return self.async_show_form(
            step_id="city", data_schema=schema, errors=errors,
            description_placeholders={
                "region": REGION_NAMES_UK.get(region, region),
                "raion": self._new_raion or "",
            },
        )

    def _async_finish_options(self, city_id: str | None) -> FlowResult:
        """Save the options and mirror raion/city into entry.data.

        Entities read ``entry.data`` (not options), so the changed raion and
        reference city are written to the entry data before the reload;
        ``entry.async_on_unload(entry.add_update_listener(...))`` in
        :mod:`.__init__` reloads the entry on every update (options or data).
        Legacy ``CONF_CITY`` in entry.data is intentionally left untouched.
        """
        new_data = dict(self.config_entry.data)
        new_data[CONF_RAION] = self._new_raion
        new_data[CONF_REFERENCE_CITY_ID] = city_id
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        return self.async_create_entry(
            title="",
            data={
                CONF_SCAN_INTERVAL: self._new_scan_interval,
            },
        )
