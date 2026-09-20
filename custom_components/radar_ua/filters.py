"""Filtering helpers for direct NEPTUN threat and alert snapshots."""

from __future__ import annotations

from typing import Any

from .raions import REGION_NAMES_UK

RESOLVED_STATUS = "resolved"


def substring_match(haystack: str | None, needle: str | None) -> bool:
    """Case-insensitive substring match; empty values never match."""
    return bool(haystack and needle and needle.casefold() in haystack.casefold())


def _raion_key(value: str | None) -> str:
    """Return NEPTUN's canonical raion key from a displayed raion name."""
    if not isinstance(value, str):
        return ""
    return value.casefold().rsplit(":", 1)[-1].removesuffix(" район").strip()


def region_name(region_key: str) -> str:
    """Return the official NEPTUN oblast name for an existing config key."""
    return REGION_NAMES_UK.get(region_key, region_key)


def _matches_region(item: dict[str, Any], region_key: str) -> bool:
    """Whether a NEPTUN record belongs to the configured oblast."""
    expected = region_name(region_key)
    return item.get("region") == expected or item.get("oblast") == expected


def _matches_raion(item: dict[str, Any], raion: str) -> bool:
    """Match the live NEPTUN raion key before display-name fallbacks.

    Alert raions carry ``key`` (e.g. "бахмутський"), threats carry the same
    key in ``regionKey``; both are normalized the same way as the config
    value (casefold, strip " район", strip whitespace).
    """
    expected_key = _raion_key(raion)
    if expected_key:
        actual_key = _raion_key(item.get("key")) or _raion_key(item.get("regionKey"))
        if actual_key == expected_key:
            return True
    return any(
        substring_match(item.get(field), raion)
        for field in ("district", "name")
    )


def raion_alerts(data: dict[str, Any], region_key: str, raion: str) -> list[dict[str, Any]]:
    """Direct NEPTUN alert records for the configured raion."""
    return [
        item
        for item in data.get("raions") or []
        if isinstance(item, dict)
        and _matches_region(item, region_key)
        and _matches_raion(item, raion)
    ]


def city_alerts(data: dict[str, Any], region_key: str, city: str) -> list[dict[str, Any]]:
    """Compatibility alias for legacy entries that saved a city as a raion match."""
    return raion_alerts(data, region_key, city)


def oblast_alerts(data: dict[str, Any], region_key: str) -> list[dict[str, Any]]:
    """Direct NEPTUN alert records for a whole oblast."""
    return [
        item
        for item in data.get("oblasts") or []
        if isinstance(item, dict) and _matches_region(item, region_key)
    ]


def alert_for_scope(
    data: dict[str, Any], region_key: str, raion: str | None
) -> dict[str, Any] | None:
    """Return the API record whose level applies to this entry's scope."""
    matches = raion_alerts(data, region_key, raion) if raion else oblast_alerts(data, region_key)
    return next((item for item in matches if isinstance(item.get("level"), str)), None)


def region_threats(data: dict[str, Any], region_key: str) -> list[dict[str, Any]]:
    """All active NEPTUN threats assigned to the configured oblast."""
    return [
        threat
        for threat in data.get("threats") or []
        if isinstance(threat, dict)
        and threat.get("status") != RESOLVED_STATUS
        and _matches_region(threat, region_key)
    ]


def filtered_threats(
    data: dict[str, Any],
    threats: list[dict[str, Any]],
    raion: str | None,
    city: str | None,
) -> list[dict[str, Any]]:
    """Limit active threats to the configured raion; city remains a legacy fallback."""
    result: list[dict[str, Any]] = []
    for threat in threats:
        if not isinstance(threat, dict) or threat.get("status") == RESOLVED_STATUS:
            continue
        if raion and not _matches_raion(threat, raion):
            continue
        if city and not any(
            substring_match(threat.get(field), city)
            for field in ("district", "locality", "region")
        ):
            continue
        result.append(threat)
    return result


def scoped_region_threats(
    data: dict[str, Any],
    region_key: str,
    raion: str | None,
    city: str | None = None,
) -> list[dict[str, Any]]:
    """Return active direct-API threats limited to this integration entry."""
    return filtered_threats(data, region_threats(data, region_key), raion, city)
