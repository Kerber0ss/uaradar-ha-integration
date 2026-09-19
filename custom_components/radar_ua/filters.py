"""Client-side filtering helpers for raion / city slices of the Radar UA data.

Semantics follow PLAN.md §4 and docs/api-notes.md:

- Threats live in ``regions[key].threats[]`` (no top-level ``threats``).
- Matching is case-insensitive substring over district / region / locality.
- A threat with ``status == "resolved"`` is never an active threat.
- ``regionKey`` on a threat is the *raion* key (e.g. "автозаводський"),
  not the oblast key — it must not be compared against region keys.
"""

from __future__ import annotations

from typing import Any

RESOLVED_STATUS = "resolved"


def substring_match(haystack: str | None, needle: str) -> bool:
    """Case-insensitive substring match; None/empty haystack or needle -> False."""
    if not haystack or not needle:
        return False
    return needle.casefold() in haystack.casefold()


def region(data: dict[str, Any], region_key: str) -> dict[str, Any]:
    """Return the region object for region_key, or an empty dict."""
    regions = data.get("regions") or {}
    if not isinstance(regions, dict):
        return {}
    obj = regions.get(region_key)
    return obj if isinstance(obj, dict) else {}


def raion_alerts(data: dict[str, Any], region_key: str, raion: str) -> list[dict[str, Any]]:
    """Raions under alert whose name matches `raion`.

    Returns the matched elements of regions[region_key].raions_under_alert[]
    (each has "key", "name", "since").
    """
    matched: list[dict[str, Any]] = []
    for entry in region(data, region_key).get("raions_under_alert") or []:
        if not isinstance(entry, dict):
            continue
        if substring_match(entry.get("name"), raion) or substring_match(
            entry.get("key"), raion
        ):
            matched.append(entry)
    return matched


def city_alerts(data: dict[str, Any], region_key: str, city: str) -> list[dict[str, Any]]:
    """Raions under alert matching the configured city (narrower slice)."""
    return raion_alerts(data, region_key, city)


def region_threats(data: dict[str, Any], region_key: str) -> list[dict[str, Any]]:
    """All active threats of a region (threats with status != resolved)."""
    threats = region(data, region_key).get("threats") or []
    return [
        t
        for t in threats
        if isinstance(t, dict) and t.get("status") != RESOLVED_STATUS
    ]


def filtered_threats(
    data: dict[str, Any],
    threats: list[dict[str, Any]],
    raion: str | None,
    city: str | None,
) -> list[dict[str, Any]]:
    """Filter threats by raion and/or city (case-insensitive substring).

    Raion: district ~ raion OR region ~ raion OR locality ~ raion.
    City (narrower slice): district|locality|region ~ city.
    Threats with status == resolved are dropped.
    """
    result: list[dict[str, Any]] = []
    for threat in threats:
        if not isinstance(threat, dict) or threat.get("status") == RESOLVED_STATUS:
            continue
        if raion:
            if not (
                substring_match(threat.get("district"), raion)
                or substring_match(threat.get("region"), raion)
                or substring_match(threat.get("locality"), raion)
                or substring_match(threat.get("regionKey"), raion)
            ):
                continue
        if city:
            if not (
                substring_match(threat.get("district"), city)
                or substring_match(threat.get("locality"), city)
                or substring_match(threat.get("region"), city)
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
    """Return active threats limited to the configured region slice."""
    return filtered_threats(
        data,
        region_threats(data, region_key),
        raion,
        city,
    )
