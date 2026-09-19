"""Unit tests for custom_components/radar_ua/filters.py.

Cases follow PLAN.md §4 and the jq examples (Конотоп, Сумська область).
Real data structures come from tests/fixtures/situation.json.
"""

from __future__ import annotations

import pytest

from radar_ua import filters


class TestSubstringMatch:
    def test_case_insensitive_ukrainian(self):
        assert filters.substring_match("Конотопський район", "конотоп") is True
        assert filters.substring_match("КОНОТОП", "Конотоп") is True
        assert filters.substring_match("Кременчук", "кременчук") is True

    def test_substring_inside(self):
        assert filters.substring_match("Автозаводський район", "завод") is True

    def test_no_match(self):
        assert filters.substring_match("Конотопський район", "ніжин") is False

    def test_none_haystack(self):
        assert filters.substring_match(None, "конотоп") is False

    def test_empty_haystack(self):
        assert filters.substring_match("", "конотоп") is False

    def test_empty_needle(self):
        assert filters.substring_match("Конотоп", "") is False

    def test_none_needle(self):
        assert filters.substring_match("Конотоп", None) is False


class TestRaionAlerts:
    def test_konotop_in_sumska(self, situation):
        matched = filters.raion_alerts(situation, "sumska", "конотоп")
        assert len(matched) == 1
        assert matched[0]["name"] == "Конотопський район"
        assert matched[0]["since"] == "2026-09-18T13:05:12Z"

    def test_no_match_returns_empty(self, situation):
        assert filters.raion_alerts(situation, "sumska", "ніжинський") == []

    def test_region_without_alerts(self, situation):
        assert filters.raion_alerts(situation, "lvivska", "конотоп") == []

    def test_unknown_region(self, situation):
        assert filters.raion_alerts(situation, "nonexistent", "конотоп") == []


class TestCityAlerts:
    def test_city_matching_raion_name(self, situation):
        # "Конотоп" matches "Конотопський район" (substring).
        matched = filters.city_alerts(situation, "sumska", "Конотоп")
        assert len(matched) == 1
        assert matched[0]["key"] == "konotopskyi"

    def test_no_match(self, situation):
        assert filters.city_alerts(situation, "poltavska", "Кременчук") == []


class TestRegionThreats:
    def test_resolved_excluded(self, situation):
        threats = filters.region_threats(situation, "sumska")
        ids = {t["id"] for t in threats}
        # trk_00196640 has status "resolved" in the fixture.
        assert "trk_00196640" not in ids
        assert "trk_00197710" in ids
        assert "trk_00197702" in ids

    def test_all_active_returned(self, situation):
        assert len(filters.region_threats(situation, "poltavska")) == 2

    def test_empty_threats(self, situation):
        assert filters.region_threats(situation, "lvivska") == []

    def test_unknown_region(self, situation):
        assert filters.region_threats(situation, "nonexistent") == []


class TestScopedRegionThreats:
    def test_konotop_only(self, situation):
        threats = filters.scoped_region_threats(
            situation, "sumska", "Конотопський район"
        )
        assert [threat["id"] for threat in threats] == ["trk_00197710"]

    def test_without_raion_keeps_all_active_threats(self, situation):
        threats = filters.scoped_region_threats(situation, "sumska", None)
        assert {threat["id"] for threat in threats} == {
            "trk_00197710",
            "trk_00197702",
        }


class TestFilteredThreats:
    def test_match_by_district(self, situation):
        threats = filters.region_threats(situation, "sumska")
        result = filters.filtered_threats(situation, threats, "конотопський", None)
        assert [t["id"] for t in result] == ["trk_00197710"]

    def test_match_by_locality(self, situation):
        threats = filters.region_threats(situation, "sumska")
        result = filters.filtered_threats(situation, threats, None, "Конотоп")
        assert [t["id"] for t in result] == ["trk_00197710"]

    def test_match_by_region_field(self, situation):
        threats = filters.region_threats(situation, "poltavska")
        result = filters.filtered_threats(situation, threats, "Полтавська", None)
        assert len(result) == 2

    def test_combination_raion_and_city(self, situation):
        threats = filters.region_threats(situation, "sumska")
        # Raion matches two threats (district + regionKey), city narrows to one.
        result = filters.filtered_threats(situation, threats, "конотоп", "Конотоп")
        assert [t["id"] for t in result] == ["trk_00197710"]

    def test_city_narrower_than_raion(self, situation):
        threats = filters.region_threats(situation, "sumska")
        raion_only = filters.filtered_threats(situation, threats, "Конотоп", None)
        assert len(raion_only) == 1

    def test_no_filters_returns_active(self, situation):
        threats = filters.region_threats(situation, "sumska")
        result = filters.filtered_threats(situation, threats, None, None)
        assert len(result) == 2

    def test_resolved_never_returned(self, situation):
        threats = filters.region_threats(situation, "sumska") + [
            t for t in situation["regions"]["sumska"]["threats"]
            if t["status"] == "resolved"
        ]
        result = filters.filtered_threats(situation, threats, "Охтирський", None)
        assert result == []

    def test_case_insensitive(self, situation):
        threats = filters.region_threats(situation, "sumska")
        upper = filters.filtered_threats(situation, threats, "КОНОП", None)  # no match
        assert upper == []
        result = filters.filtered_threats(situation, threats, "КОНОТОП", None)
        assert len(result) == 1


@pytest.mark.parametrize(
    ("haystack", "needle", "expected"),
    [
        ("Київ", "київ", True),
        (None, "x", False),
        ("x", None, False),
        ("", "", False),
    ],
)
def test_substring_match_table(haystack, needle, expected):
    assert filters.substring_match(haystack, needle) is expected
