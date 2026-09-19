"""Unit tests for custom_components/radar_ua/parsing.py (pure helpers).

Covers the contract from docs/api-notes.md:

- "ракети" = counts.missile + counts.ballistic
- advisory = threat with type == "mig31k" (no `advisory` field in the real API)
- coordinates are lat / lon
- `areaOnly` is absent in the real API -> must not be required
"""

from __future__ import annotations

import pytest

from radar_ua import parsing


class TestMissilesCount:
    def test_missile_plus_ballistic(self, situation):
        counts = situation["regions"]["poltavska"]["counts"]
        # fixture: missile=4, ballistic=2
        assert parsing.missiles_count(counts) == 6

    def test_zero_when_both_zero(self, situation):
        counts = situation["regions"]["lvivska"]["counts"]
        assert parsing.missiles_count(counts) == 0

    def test_missing_keys(self):
        assert parsing.missiles_count({}) == 0

    def test_none_counts(self):
        assert parsing.missiles_count(None) == 0

    def test_ignores_other_types(self):
        counts = {"uav": 10, "missile": 1, "ballistic": 2, "kab": 5, "mig31k": 3}
        assert parsing.missiles_count(counts) == 3


class TestThreatCounts:
    def test_filtered_threat_units(self, situation):
        threats = [situation["regions"]["sumska"]["threats"][0]]
        assert parsing.sum_threat_units(threats) == 2
        assert parsing.sum_threat_units(threats, "uav") == 2
        assert parsing.sum_threat_units(threats, "mig31k") == 0

    def test_counts_for_filtered_threats(self, situation):
        threats = [situation["regions"]["sumska"]["threats"][0]]
        assert parsing.counts_for_threats(threats) == {
            "uav": 2,
            "recon": 0,
            "missile": 0,
            "ballistic": 0,
            "kab": 0,
            "mig31k": 0,
            "unknown": 0,
        }


class TestAdvisory:
    def test_mig31k_threat_is_advisory(self, situation):
        threat = next(
            t for t in situation["regions"]["sumska"]["threats"] if t["id"] == "trk_00197702"
        )
        assert threat["type"] == "mig31k"
        assert parsing.threat_advisory(threat) is True

    def test_uav_threat_is_not_advisory(self, situation):
        threat = next(
            t for t in situation["regions"]["sumska"]["threats"] if t["id"] == "trk_00197710"
        )
        assert parsing.threat_advisory(threat) is False

    def test_region_advisory_true(self, situation):
        assert parsing.region_advisory(situation["regions"]["sumska"]) is True

    def test_region_advisory_false(self, situation):
        assert parsing.region_advisory(situation["regions"]["poltavska"]) is False

    def test_resolved_mig31k_does_not_trigger(self):
        region = {"threats": [{"id": "x", "type": "mig31k", "status": "resolved"}]}
        assert parsing.region_advisory(region) is False


class TestCoordinates:
    def test_lat_lon(self, situation):
        threat = situation["regions"]["poltavska"]["threats"][0]
        lat, lon = parsing.threat_coordinates(threat)
        assert lat == pytest.approx(48.82036841062527)
        assert lon == pytest.approx(33.58679191791975)

    def test_missing_coordinates(self):
        assert parsing.threat_coordinates({"id": "x"}) is None

    def test_null_coordinates(self):
        assert parsing.threat_coordinates({"lat": None, "lon": None}) is None

    def test_all_fixture_threats_have_coordinates(self, situation):
        for key, region in situation["regions"].items():
            for threat in region["threats"]:
                coords = parsing.threat_coordinates(threat)
                assert coords is not None, f"{key}/{threat['id']} has no lat/lon"


class TestAreaOnly:
    def test_absent_field_is_not_area_only(self, situation):
        # The real API has no `areaOnly` field (docs/api-notes.md).
        for region in situation["regions"].values():
            for threat in region["threats"]:
                assert "areaOnly" not in threat
                assert parsing.is_area_only(threat) is False

    def test_area_only_true_when_present(self):
        assert parsing.is_area_only({"id": "x", "areaOnly": True}) is True

    def test_area_only_false_when_present(self):
        assert parsing.is_area_only({"id": "x", "areaOnly": False}) is False

    def test_none_threat(self):
        assert parsing.is_area_only(None) is False
