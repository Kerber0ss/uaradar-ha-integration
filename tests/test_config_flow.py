"""Config/options flow tests for the reference-city steps (plan-distance 2-3).

The harness here is plain pytest (no pytest-homeassistant-custom-component and
no running hass fixture), so the flow handlers are driven directly: each flow
instance gets a ``MagicMock`` hass, a flow id and a handler, and the
``async_step_*`` coroutines are awaited in the same order the flow manager
would call them. The raion/city datasets under test are the real bundled
``raions.py`` and ``geo/cities.json`` data.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import voluptuous as vol

from radar_ua.config_flow import RadarUaConfigFlow, RadarUaOptionsFlow
from radar_ua.const import (
    CONF_CITY,
    CONF_RAION,
    CONF_REFERENCE_CITY_ID,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from radar_ua.geo.cities import cities_for_raion, city_by_id
from radar_ua.raions import RAIONS

KONOTOP_ID = "UA59020070010054283"
KROLEVETS_ID = "UA59020090010081204"
SUMY_ID = "UA59080270010036634"  # valid dataset id, but in Сумський район
KONOTOP_RAION = "Конотопський район"
KURMANSKYI_RAION = "Курманський район"  # raion without cities in the dataset


def make_config_flow() -> RadarUaConfigFlow:
    """Bare config flow wired like the flow manager would (no real hass)."""
    flow = RadarUaConfigFlow()
    flow.hass = MagicMock()
    flow.flow_id = "test-flow"
    flow.handler = "radar_ua"
    return flow


def make_options_flow(entry: SimpleNamespace) -> RadarUaOptionsFlow:
    """Bare options flow for a fake config entry."""
    flow = RadarUaOptionsFlow(entry)
    flow.hass = MagicMock()
    flow.flow_id = "test-options-flow"
    flow.handler = "radar_ua"
    return flow


def config_flow_with_meta() -> RadarUaConfigFlow:
    """Config flow with the meta step already passed (regions loaded)."""
    flow = make_config_flow()
    # Pretend async_get_alerts() succeeded: every RAIONS key is a region.
    flow._meta_regions = list(RAIONS)
    return flow


def legacy_entry(**extra) -> SimpleNamespace:
    """A pre-2.2 config entry: region (+ optional legacy free-text city)."""
    data = {"region": "sumska", CONF_CITY: "Конотоп"}
    data.update(extra)
    return SimpleNamespace(
        entry_id="test-entry",
        options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        data=data,
    )


def schema_field(result: dict, key: str):
    """Return the schema marker of a form field, or None when absent."""
    for marker in result["data_schema"].schema:
        if marker.schema == key:
            return marker
    return None


class TestConfigFlowRegionToCity:
    async def test_full_flow_region_raion_city(self):
        flow = config_flow_with_meta()

        result = await flow.async_step_user({CONF_REGION: "sumska"})
        assert result["type"] == "form"
        assert result["step_id"] == "raions"

        result = await flow.async_step_raions({CONF_RAION: KONOTOP_RAION})
        assert result["type"] == "form"
        assert result["step_id"] == "city"

        result = await flow.async_step_city({CONF_REFERENCE_CITY_ID: KONOTOP_ID})
        assert result["type"] == "create_entry"
        assert result["title"] == "Radar UA Сумська область"
        assert result["data"] == {
            CONF_REGION: "sumska",
            CONF_RAION: KONOTOP_RAION,
            CONF_REFERENCE_CITY_ID: KONOTOP_ID,
        }
        # Options pre-filled so no second dialog pops up after creation.
        assert result["options"] == {CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL}

    async def test_city_step_lists_only_cities_of_chosen_raion(self):
        flow = config_flow_with_meta()
        await flow.async_step_user({CONF_REGION: "sumska"})
        result = await flow.async_step_raions({CONF_RAION: KONOTOP_RAION})

        marker = schema_field(result, CONF_REFERENCE_CITY_ID)
        validator = result["data_schema"].schema[marker]
        assert isinstance(validator, vol.In)
        raion_city_ids = {city["id"] for city in cities_for_raion("sumska", KONOTOP_RAION)}
        assert set(validator.container) == raion_city_ids | {""}  # "" = no-city choice

    async def test_raion_skipped_finishes_without_city_step(self):
        flow = config_flow_with_meta()
        await flow.async_step_user({CONF_REGION: "sumska"})

        result = await flow.async_step_raions({CONF_RAION: ""})

        assert result["type"] == "create_entry"
        assert result["data"][CONF_RAION] is None
        assert result["data"][CONF_REFERENCE_CITY_ID] is None

    async def test_raion_without_cities_finishes_without_city_step(self):
        # Курманський район (АР Крим) has no cities in the dataset: the flow
        # must finish without a city step and without a reference city.
        flow = config_flow_with_meta()
        await flow.async_step_user({CONF_REGION: "crimea"})

        result = await flow.async_step_raions({CONF_RAION: KURMANSKYI_RAION})

        assert result["type"] == "create_entry"
        assert result["data"][CONF_RAION] == KURMANSKYI_RAION
        assert result["data"][CONF_REFERENCE_CITY_ID] is None

    async def test_invalid_city_id_shows_invalid_city_error(self):
        # Sumy is a real dataset city, but belongs to Сумський район,
        # not the chosen Конотопський район.
        flow = config_flow_with_meta()
        await flow.async_step_user({CONF_REGION: "sumska"})
        await flow.async_step_raions({CONF_RAION: KONOTOP_RAION})

        result = await flow.async_step_city({CONF_REFERENCE_CITY_ID: SUMY_ID})

        assert result["type"] == "form"
        assert result["step_id"] == "city"
        assert result["errors"] == {"base": "invalid_city"}

    async def test_city_step_can_be_skipped(self):
        flow = config_flow_with_meta()
        await flow.async_step_user({CONF_REGION: "sumska"})
        await flow.async_step_raions({CONF_RAION: KONOTOP_RAION})

        result = await flow.async_step_city({CONF_REFERENCE_CITY_ID: ""})

        assert result["type"] == "create_entry"
        assert result["data"][CONF_RAION] == KONOTOP_RAION
        assert result["data"][CONF_REFERENCE_CITY_ID] is None


class TestOptionsFlowRaionCity:
    async def test_existing_install_adds_raion_and_city(self):
        entry = legacy_entry()
        flow = make_options_flow(entry)

        result = await flow.async_step_init(
            {CONF_SCAN_INTERVAL: 60, CONF_RAION: KONOTOP_RAION}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "city"

        result = await flow.async_step_city({CONF_REFERENCE_CITY_ID: KONOTOP_ID})
        assert result["type"] == "create_entry"
        assert result["data"] == {CONF_SCAN_INTERVAL: 60}

        # Raion and city are mirrored into entry.data (entities read data),
        # which fires the entry update listener -> the entry is reloaded.
        flow.hass.config_entries.async_update_entry.assert_called_once()
        args, kwargs = flow.hass.config_entries.async_update_entry.call_args
        assert args[0] is entry
        assert kwargs["data"][CONF_RAION] == KONOTOP_RAION
        assert kwargs["data"][CONF_REFERENCE_CITY_ID] == KONOTOP_ID

    async def test_legacy_city_field_left_untouched(self):
        entry = legacy_entry()
        flow = make_options_flow(entry)
        await flow.async_step_init({CONF_SCAN_INTERVAL: 30, CONF_RAION: KONOTOP_RAION})
        await flow.async_step_city({CONF_REFERENCE_CITY_ID: KONOTOP_ID})

        _, kwargs = flow.hass.config_entries.async_update_entry.call_args
        # Legacy free-text city stays for old entries; the new reference city
        # is stored under its own key.
        assert kwargs["data"][CONF_CITY] == "Конотоп"
        assert kwargs["data"][CONF_REFERENCE_CITY_ID] == KONOTOP_ID

    async def test_options_change_city_updates_entry_data(self):
        entry = legacy_entry(
            **{
                CONF_RAION: KONOTOP_RAION,
                CONF_REFERENCE_CITY_ID: KONOTOP_ID,
            }
        )
        flow = make_options_flow(entry)

        result = await flow.async_step_init(
            {CONF_SCAN_INTERVAL: 30, CONF_RAION: KONOTOP_RAION}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "city"
        # Current city is preselected in the dropdown (voluptuous wraps the
        # default value in a factory callable).
        marker = schema_field(result, CONF_REFERENCE_CITY_ID)
        assert marker.default() == KONOTOP_ID

        result = await flow.async_step_city({CONF_REFERENCE_CITY_ID: KROLEVETS_ID})
        assert result["type"] == "create_entry"
        _, kwargs = flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"][CONF_REFERENCE_CITY_ID] == KROLEVETS_ID

    async def test_options_raion_skip_clears_raion_and_city(self):
        entry = legacy_entry(
            **{CONF_RAION: KONOTOP_RAION, CONF_REFERENCE_CITY_ID: KONOTOP_ID}
        )
        flow = make_options_flow(entry)

        result = await flow.async_step_init({CONF_SCAN_INTERVAL: 30, CONF_RAION: ""})

        assert result["type"] == "create_entry"
        _, kwargs = flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"][CONF_RAION] is None
        assert kwargs["data"][CONF_REFERENCE_CITY_ID] is None

    async def test_options_raion_without_cities_finishes_without_city_step(self):
        entry = legacy_entry()
        flow = make_options_flow(entry)

        result = await flow.async_step_init(
            {CONF_SCAN_INTERVAL: 30, CONF_RAION: KURMANSKYI_RAION}
        )

        assert result["type"] == "create_entry"
        _, kwargs = flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"][CONF_RAION] == KURMANSKYI_RAION
        assert kwargs["data"][CONF_REFERENCE_CITY_ID] is None

    async def test_options_invalid_city_shows_invalid_city_error(self):
        entry = legacy_entry()
        flow = make_options_flow(entry)
        await flow.async_step_init({CONF_SCAN_INTERVAL: 30, CONF_RAION: KONOTOP_RAION})

        result = await flow.async_step_city({CONF_REFERENCE_CITY_ID: SUMY_ID})

        assert result["type"] == "form"
        assert result["step_id"] == "city"
        assert result["errors"] == {"base": "invalid_city"}


class TestOptionsFlowBasics:
    async def test_scan_interval_bounds_unchanged(self):
        entry = legacy_entry()
        flow = make_options_flow(entry)

        result = await flow.async_step_init({CONF_SCAN_INTERVAL: MIN_SCAN_INTERVAL - 1})
        assert result["errors"] == {"base": "invalid_scan_interval"}

        result = await flow.async_step_init({CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL})
        assert result["type"] == "create_entry"
