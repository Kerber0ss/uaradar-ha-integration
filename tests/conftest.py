"""Shared pytest fixtures and import bootstrap for the Radar UA tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# The integration is a namespace package under custom_components/.
sys.path.insert(0, str(REPO_ROOT / "custom_components"))


@pytest.fixture()
def situation() -> dict:
    """Realistic /v1/situation payload (see tests/fixtures/situation.json)."""
    return load_situation()


def load_situation() -> dict:
    path = REPO_ROOT / "tests" / "fixtures" / "situation.json"
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Keep the legacy region shape for parsing tests, while exposing the direct
    # NEPTUN endpoints' shape to filtering tests.
    data["threats"] = [
        threat
        for region in data["regions"].values()
        for threat in region["threats"]
    ]
    data["raions"] = [
        {**alert, "oblast": region["name"], "level": "yellow"}
        for region in data["regions"].values()
        for alert in region["raions_under_alert"]
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
