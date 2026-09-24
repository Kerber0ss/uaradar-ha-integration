"""Межі районів: перевірка точки через локальний знімок NEPTUN (``raions.geojson``).

Знімок кладеться в пакет (``geo/raions.geojson``), тому сенсор відстані не
залежить від окремого завантаження меж під час події. Модуль використовує
лише стандартну бібліотеку (як ``parsing.py``), щоб його можна було
тестувати без Home Assistant.

Призначення: для цілей без достовірного районного ключа NEPTUN (порожні
``district``/``regionKey``), але з коректними координатами, визначати
належність району геометрично (ray casting). Маркери ``areaOnly`` і цілі без
координат геометрично не перевіряються; назва ``locality`` позицією не
вважається — вона може означати напрямок або пункт призначення.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "raions.geojson"

# Середній радіус Землі, км (IUGG mean radius).
EARTH_RADIUS_KM = 6371.0088

# ключ району -> список полігонів; полігон = список кілець; кільце = [(lon, lat), ...]
_RING_INDEX: dict[str, list[list[list[tuple[float, float]]]]] | None = None


def raion_key(value: Any) -> str:
    """Canonical raion key from a display name or a NEPTUN key.

    Same normalization as the config side: casefold, drop any
    ``"<oblast>:"`` prefix, strip the ``" район"`` suffix and whitespace.
    """
    if not isinstance(value, str):
        return ""
    return value.casefold().rsplit(":", 1)[-1].removesuffix(" район").strip()


def _load_rings() -> dict[str, list[list[list[tuple[float, float]]]]]:
    """Load and cache the raion boundary snapshot (once per process)."""
    global _RING_INDEX
    if _RING_INDEX is None:
        with _DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        index: dict[str, list[list[list[tuple[float, float]]]]] = {}
        for feature in data.get("features") or []:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            key = raion_key(properties.get("key") or properties.get("rayon"))
            polygons = _normalize_geometry(feature.get("geometry"))
            if key and polygons:
                # Назви районів унікальні в межах країни (реформа 2020 року).
                index.setdefault(key, polygons)
        _RING_INDEX = index
    return _RING_INDEX


def _normalize_geometry(
    geometry: Any,
) -> list[list[list[tuple[float, float]]]]:
    """Convert a GeoJSON Polygon/MultiPolygon to ring tuples; [] if invalid."""
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Polygon" and isinstance(coordinates, list):
        polygons = [coordinates]
    elif geometry.get("type") == "MultiPolygon" and isinstance(coordinates, list):
        polygons = coordinates
    else:
        return []
    result: list[list[list[tuple[float, float]]]] = []
    for polygon in polygons:
        if not isinstance(polygon, list):
            continue
        rings: list[list[tuple[float, float]]] = []
        for ring in polygon:
            if not isinstance(ring, list):
                continue
            points: list[tuple[float, float]] = []
            for position in ring:
                try:
                    lon, lat = float(position[0]), float(position[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if math.isfinite(lat) and math.isfinite(lon):
                    points.append((lon, lat))
            if len(points) >= 4:  # замкнене кільце
                rings.append(points)
        if rings:
            result.append(rings)
    return result


def point_in_raion(lat: float, lon: float, raion_display_name: str | None) -> bool:
    """Whether the point lies inside the raion's boundary (ray casting).

    ``raion_display_name`` — назва району у формі ``"<Назва> район"`` (як у
    ``RAIONS``) або його ключ. Повертає False, якщо знімок не містить
    такого району або геометрія нечитабельна. Антимеридіан не
    підтримується (Україна його не перетинає).
    """
    expected = raion_key(raion_display_name)
    if not expected or not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    polygons = _load_rings().get(expected)
    if not polygons:
        return False
    return any(_point_in_polygon(lat, lon, rings) for rings in polygons)


def _point_in_polygon(lat: float, lon: float, rings: list[list[tuple[float, float]]]) -> bool:
    """Even-odd ray casting over the polygon rings (outer + holes)."""
    inside = False
    for ring in rings:
        if _point_in_ring(lon, lat, ring):
            inside = not inside
    return inside


def _point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Even-odd containment test for one ring of ``(lon, lat)`` points."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        lon_i, lat_i = ring[i]
        lon_j, lat_j = ring[j]
        if (lat_i > lat) != (lat_j > lat):
            lon_cross = (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
            if lon < lon_cross:
                inside = not inside
        j = i
    return inside


def great_circle_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in km (haversine formula, mean Earth radius)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
