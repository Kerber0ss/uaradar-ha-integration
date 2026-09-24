"""Локальний довідник міст: область → район → місто (``geo/cities.json``).

JSON зчитується синхронно один раз при першому зверненні та кешується на
рівні модуля (~90 КБ, тому читання при першому виклику прийнятне). Всі
функції синхронні: довідник статичний і не потребує await.

Ключі зовнішнього словника збігаються з ключами ``RAIONS``
(:mod:`..raions`), внутрішні ключі — ті самі назви районів, що використовуються
у значеннях ``RAIONS`` (форма ``"<Назва> район"``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "cities.json"

# Лінива кеш-змінна: dict.region_key -> {raion_display -> [city, ...]}
_CITY_DATA: dict[str, dict[str, list[dict[str, Any]]]] | None = None


def _load() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Load and cache the cities dataset (once per process)."""
    global _CITY_DATA
    if _CITY_DATA is None:
        with _DATA_PATH.open("r", encoding="utf-8") as f:
            _CITY_DATA = json.load(f)
    return _CITY_DATA


def cities_for_raion(region_key: str, raion_display: str) -> list[dict[str, Any]]:
    """Return the cities of one raion (empty list if none are known).

    ``region_key`` — ключ області (як у ``RAIONS``), ``raion_display`` —
    назва району у формі ``"<Назва> район"``.
    """
    return _load().get(region_key, {}).get(raion_display, [])


def city_by_id(city_id: str) -> dict[str, Any] | None:
    """Find a city by its stable KATOTTG id across all regions/raions."""
    if not city_id:
        return None
    for raions in _load().values():
        for cities in raions.values():
            for city in cities:
                if city.get("id") == city_id:
                    return city
    return None


def city_coordinates(city_id: str) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` for a city id, or ``None`` if unknown."""
    city = city_by_id(city_id)
    if city is None or city.get("lat") is None or city.get("lon") is None:
        return None
    return (city["lat"], city["lon"])