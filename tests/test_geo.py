"""Geo tests: raion membership, geometric fallback and distance (plan-distance 4-5).

Covers the Krolevets-in-Konotopskyi scenario from plan-distance.md: a target
with an empty ``district`` but valid coordinates must be assigned to the
raion geometrically, so the distance sensor sees it.
"""

from __future__ import annotations

import math

from radar_ua.filters import scoped_threats, threat_in_raion
from radar_ua.geo.boundaries import great_circle_distance_km, point_in_raion
from radar_ua.geo.cities import city_by_id

KONOTOP_RAION = "Конотопський район"
SUMY_RAION = "Сумський район"
KONOTOP_ID = "UA59020070010054283"
KONOTOP = city_by_id(KONOTOP_ID)  # 51.2397495, 33.206675


def make_threat(**overrides) -> dict:
    """Threat over Krolevets with an empty district (the plan scenario)."""
    threat = {
        "id": "trk_krolevets",
        "type": "uav",
        "region": "Сумська область",
        "district": "",
        "regionKey": None,
        "locality": "",
        "lat": 51.5548,
        "lon": 33.3875,  # near Krolevets, inside Konotopskyi raion
        "status": "active",
        "count": 1,
    }
    threat.update(overrides)
    return threat


def make_data(threats: list[dict]) -> dict:
    """Coordinator-shaped data scoped to Сумська область."""
    return {
        "updated": "2026-09-24T09:00:00Z",
        "fetch_ok": True,
        "threats": threats,
        "raions": [],
        "oblasts": [],
    }


class TestThreatInRaion:
    def test_key_match_region_key(self):
        threat = {"regionKey": "конотопський", "district": "", "region": "Сумська область"}
        assert threat_in_raion(threat, KONOTOP_RAION) is True

    def test_key_match_alert_key_field(self):
        threat = {"key": "конотопський"}
        assert threat_in_raion(threat, KONOTOP_RAION) is True

    def test_display_name_fallback(self):
        threat = {"district": "Конотопський район", "region": "Сумська область"}
        assert threat_in_raion(threat, KONOTOP_RAION) is True

    def test_geometric_fallback_with_empty_district(self):
        # Krolevets-area target: no raion key/district text at all, but the
        # coordinates fall inside the Konotopskyi boundary snapshot.
        threat = make_threat()
        assert threat["district"] == ""
        assert threat_in_raion(threat, KONOTOP_RAION) is True

    def test_geometric_fallback_point_near_konotop_city(self):
        threat = make_threat(lat=51.2397, lon=33.2067)  # near Konotop itself
        assert threat_in_raion(threat, KONOTOP_RAION) is True

    def test_point_in_another_raion_fails(self):
        # Sumy city center: geometrically in Сумський, not Конотопський.
        threat = make_threat(lat=50.9119, lon=34.8027)
        assert threat_in_raion(threat, KONOTOP_RAION) is False
        assert threat_in_raion(threat, SUMY_RAION) is True

    def test_area_only_excluded_from_geometric_match(self):
        # Coordinates inside Konotopskyi but marked as an area centroid:
        # must NOT count as a raion member via geometry.
        threat = make_threat(areaOnly=True)
        assert threat_in_raion(threat, KONOTOP_RAION) is False

    def test_area_only_still_matches_by_key(self):
        # Geometry is skipped, but a reliable NEPTUN raion key still matches.
        threat = make_threat(areaOnly=True, regionKey="конотопський")
        assert threat_in_raion(threat, KONOTOP_RAION) is True

    def test_missing_coordinates_no_geometric_match(self):
        threat = make_threat(lat=None, lon=None)
        assert threat_in_raion(threat, KONOTOP_RAION) is False

    def test_non_finite_coordinates_no_geometric_match(self):
        threat = make_threat(lat=float("nan"), lon=33.38)
        assert threat_in_raion(threat, KONOTOP_RAION) is False

    def test_no_raion_configured(self):
        assert threat_in_raion(make_threat(), None) is False

    def test_not_a_dict(self):
        assert threat_in_raion(None, KONOTOP_RAION) is False


class TestPointInRaion:
    def test_konotop_city_center_inside(self):
        assert point_in_raion(51.2397, 33.2067, KONOTOP_RAION) is True

    def test_outside_boundary(self):
        # Kyiv is far outside Konotopskyi raion.
        assert point_in_raion(50.4501, 30.5234, KONOTOP_RAION) is False

    def test_unknown_raion(self):
        assert point_in_raion(51.2397, 33.2067, "Неіснуючий район") is False

    def test_accepts_bare_key_and_display_name(self):
        assert point_in_raion(51.2397, 33.2067, "конотопський") is True

    def test_out_of_range_coordinates(self):
        assert point_in_raion(999.0, 33.2067, KONOTOP_RAION) is False


class TestGreatCircleDistanceKm:
    def test_konotop_to_krolevets_about_37_km(self):
        krolevets = city_by_id("UA59020090010081204")
        distance = great_circle_distance_km(
            KONOTOP["lat"], KONOTOP["lon"], krolevets["lat"], krolevets["lon"]
        )
        assert math.isclose(distance, 37.2, abs_tol=1.0)

    def test_known_reference_distance(self):
        # London -> Paris is ~344 km by air.
        distance = great_circle_distance_km(51.5074, -0.1278, 48.8566, 2.3522)
        assert math.isclose(distance, 343.6, abs_tol=1.0)

    def test_zero_distance_for_same_point(self):
        assert great_circle_distance_km(51.0, 33.0, 51.0, 33.0) == 0.0

    def test_symmetry(self):
        a = great_circle_distance_km(51.2397, 33.2067, 51.5548, 33.3875)
        b = great_circle_distance_km(51.5548, 33.3875, 51.2397, 33.2067)
        assert math.isclose(a, b)

    def test_returns_float_km(self):
        distance = great_circle_distance_km(51.2397, 33.2067, 50.9119, 34.8027)
        assert isinstance(distance, float)
        assert 100 < distance < 130  # Konotop -> Sumy ~117 km


class TestScopedThreats:
    def test_reference_city_does_not_narrow_by_name(self):
        # The legacy name filter would drop the Krolevets-area threat
        # (its locality is empty); with a reference city it must survive:
        # the reference city is a distance anchor, never a name filter.
        threat = make_threat(locality="північніше Кролевця")
        data = make_data([threat])

        legacy = scoped_threats(data, "sumska", KONOTOP_RAION, city="Конотоп")
        with_reference = scoped_threats(
            data, "sumska", KONOTOP_RAION, city="Конотоп",
            reference_city_id=KONOTOP_ID,
        )
        assert legacy == []
        assert [t["id"] for t in with_reference] == ["trk_krolevets"]

    def test_legacy_city_still_narrows_without_reference_city(self):
        konotop = make_threat(
            id="trk_konotop", lat=51.2387, lon=33.1986, locality="Конотоп"
        )
        krolevets = make_threat()
        data = make_data([konotop, krolevets])

        threats = scoped_threats(data, "sumska", KONOTOP_RAION, city="Конотоп")
        assert [t["id"] for t in threats] == ["trk_konotop"]

    def test_reference_city_alone_keeps_whole_raion(self):
        data = make_data([make_threat()])
        threats = scoped_threats(
            data, "sumska", KONOTOP_RAION, reference_city_id=KONOTOP_ID
        )
        assert [t["id"] for t in threats] == ["trk_krolevets"]

    def test_geometric_membership_used_for_raion_scope(self):
        data = make_data([make_threat()])
        threats = scoped_threats(data, "sumska", KONOTOP_RAION)
        assert [t["id"] for t in threats] == ["trk_krolevets"]

    def test_other_raion_excluded(self):
        data = make_data([make_threat()])
        assert scoped_threats(data, "sumska", SUMY_RAION) == []

    def test_resolved_excluded(self):
        data = make_data([make_threat(status="resolved")])
        assert scoped_threats(data, "sumska", KONOTOP_RAION) == []

    def test_other_oblast_excluded(self):
        data = make_data([make_threat(region="Полтавська область")])
        assert scoped_threats(data, "sumska", KONOTOP_RAION) == []
