"""Pure parsing helpers for the Radar UA data.

These functions are intentionally free of Home Assistant imports so they can
be unit-tested with plain pytest (see tests/test_parsing.py). Platform modules
(sensor.py, binary_sensor.py, geo_location.py) build on top of them.

Data shape per docs/api-notes.md:

- ``counts`` has ``missile`` and ``ballistic`` keys; "ракети" = missile+ballistic.
- There is no ``advisory`` field in the real API: advisory (МиГ-31К взлетів)
  is derived from a threat with ``type == "mig31k"``.
- Coordinates are ``lat`` / ``lon`` (not latitude/longitude).
- There is no ``areaOnly`` field in the real API; the field may appear in the
  future (area centroid markers must not be drawn as points), so we honour it
  defensively: missing field -> not area-only.
"""

from __future__ import annotations

from typing import Any

# Mirrors const.THREAT_MIG31K; duplicated here to keep this module HA-free.
MIG31K_TYPE = "mig31k"


def missiles_count(counts: dict[str, Any] | None) -> int:
    """Number of missiles: ``counts.missile + counts.ballistic``."""
    if not isinstance(counts, dict):
        return 0
    total = 0
    for key in ("missile", "ballistic"):
        value = counts.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def threat_advisory(threat: dict[str, Any]) -> bool:
    """True when the threat is a MiG-31K launch warning (type == mig31k)."""
    if not isinstance(threat, dict):
        return False
    return threat.get("type") == MIG31K_TYPE


def region_advisory(region: dict[str, Any]) -> bool:
    """True when any active threat of the region is an advisory (MiG-31K)."""
    if not isinstance(region, dict):
        return False
    for threat in region.get("threats") or []:
        if not isinstance(threat, dict):
            continue
        if threat.get("status") == "resolved":
            continue
        if threat_advisory(threat):
            return True
    return False


def threat_coordinates(threat: dict[str, Any]) -> tuple[float, float] | None:
    """Return (lat, lon) of a threat, or None when missing/invalid."""
    if not isinstance(threat, dict):
        return None
    lat = threat.get("lat")
    lon = threat.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return (float(lat), float(lon))
    return None


def is_area_only(threat: dict[str, Any]) -> bool:
    """True for area-centroid markers that must not be drawn as map points.

    The real API response does not contain ``areaOnly`` (docs/api-notes.md);
    treat a missing field as False so real threats are always drawn.
    """
    if not isinstance(threat, dict):
        return False
    return threat.get("areaOnly") is True
