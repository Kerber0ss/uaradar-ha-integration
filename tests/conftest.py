"""Shared pytest fixtures and import bootstrap for the Radar UA tests."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# The integration is a namespace package under custom_components/.
sys.path.insert(0, str(REPO_ROOT / "custom_components"))

from radar_ua.const import DOMAIN  # noqa: E402
from radar_ua.coordinator import RadarUaDataUpdateCoordinator  # noqa: E402


@pytest.fixture()
def make_coordinator():
    """Build a RadarUaDataUpdateCoordinator without a real hass instance.

    The shared stream client is created but its task coroutine is closed
    immediately, so no network activity happens in tests.
    """

    def _factory(data: dict | None = None, session=None) -> RadarUaDataUpdateCoordinator:
        hass = MagicMock()
        hass.data = {DOMAIN: {"test-entry": {"session": session or MagicMock()}}}

        def _close_coro(coro):
            coro.close()
            return MagicMock()

        hass.async_create_task = _close_coro
        entry = SimpleNamespace(entry_id="test-entry", options={}, data={"region": "sumska"})
        coordinator = RadarUaDataUpdateCoordinator(hass, entry)
        if data is not None:
            coordinator.data = data
            coordinator.last_update_success = True
        return coordinator

    return _factory


@pytest.fixture()
def situation() -> dict:
    """Realistic /v1/situation payload (see tests/fixtures/situation.json)."""
    return load_situation()


def live_raions(region: dict) -> list[dict]:
    """Live NEPTUN alerts.raions[] records for one legacy region block.

    Live schema (docs/ws-notes.md): items are
    ``{key, name, oblast, since, level, reasons[]}`` where ``key`` is the
    lowercased raion name without the " район" suffix (e.g. "бахмутський").
    """
    raions = []
    for alert in region["raions_under_alert"]:
        raions.append(
            {
                "key": alert["name"].removesuffix(" район").casefold(),
                "name": alert["name"],
                "oblast": region["name"],
                "since": alert["since"],
                "level": "red",
                "reasons": ["Виявлено загрозу"],
            }
        )
    return raions


def load_situation() -> dict:
    path = REPO_ROOT / "tests" / "fixtures" / "situation.json"
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Keep the legacy region shape for parsing tests, while exposing the
    # live NEPTUN endpoints' shape (threats + alerts) to filtering tests.
    data["threats"] = [
        threat
        for region in data["regions"].values()
        for threat in region["threats"]
    ]
    data["raions"] = [
        record
        for region in data["regions"].values()
        for record in live_raions(region)
    ]
    data["oblasts"] = [
        {
            "key": "sumska",
            "name": "Сумська область",
            "oblast": "Сумська область",
            "since": "2026-09-18T13:05:12Z",
            "level": "red",
        }
    ]
    return data
