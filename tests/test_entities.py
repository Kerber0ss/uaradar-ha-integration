"""Tests for the restored entities: advisory, ukraine_alerts, mig31k, raid_size."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from radar_ua.binary_sensor import (
    RadarUaAdvisoryBinarySensor,
    RadarUaAlertBinarySensor,
    RadarUaUkraineAlertsBinarySensor,
    _has_ukraine_alerts_entity,
)
from radar_ua.sensor import RadarUaDataAgeSensor, RadarUaCountsSensor

NOW = datetime.now(timezone.utc).isoformat()


def make_data(threats, oblasts=None, raions=None):
    """Coordinator-shaped data with a fresh timestamp."""
    return {
        "updated": NOW,
        "fetch_ok": True,
        "attribution": "attr",
        "threats": threats,
        "raions": raions or [],
        "oblasts": oblasts or [],
    }


def make_entry():
    return SimpleNamespace(
        entry_id="test-entry", options={}, data={"region": "donetska"}
    )


THREATS = [
    {"id": "t1", "type": "mig31k", "region": "Донецька область", "status": "active", "count": 1},
    {"id": "t2", "type": "uav", "region": "Донецька область", "status": "active", "count": 3},
    {"id": "t3", "type": "uav", "region": "Донецька область", "status": "resolved", "count": 5},
    {
        "id": "t4",
        "type": "missile",
        "region": "Донецька область",
        "status": "active",
        "advisory": True,
    },
]


class TestAdvisoryBinarySensor:
    def test_on_for_mig31k_threat(self, make_coordinator):
        coordinator = make_coordinator(make_data(THREATS))
        sensor = RadarUaAdvisoryBinarySensor(coordinator, make_entry(), "donetska")
        assert sensor.is_on is True

    def test_on_for_explicit_advisory_flag(self, make_coordinator):
        coordinator = make_coordinator(make_data([THREATS[3]]))
        sensor = RadarUaAdvisoryBinarySensor(coordinator, make_entry(), "donetska")
        assert sensor.is_on is True

    def test_off_without_advisory_threats(self, make_coordinator):
        coordinator = make_coordinator(make_data([THREATS[1]]))
        sensor = RadarUaAdvisoryBinarySensor(coordinator, make_entry(), "donetska")
        assert sensor.is_on is False

    def test_attributes_mig31k_ids_and_count(self, make_coordinator):
        coordinator = make_coordinator(make_data(THREATS))
        sensor = RadarUaAdvisoryBinarySensor(coordinator, make_entry(), "donetska")
        attrs = sensor.extra_state_attributes
        assert attrs["mig31k_ids"] == ["t1"]
        # t1 (mig31k) + t4 (advisory flag)
        assert attrs["advisory_count"] == 2


class TestUkraineAlertsBinarySensor:
    def test_on_when_any_oblast_red(self, make_coordinator):
        oblasts = [
            {"key": "donetska", "name": "Донецька область", "oblast": "Донецька область", "level": "red"},
            {"key": "lvivska", "name": "Львівська область", "oblast": "Львівська область", "level": "green"},
        ]
        coordinator = make_coordinator(make_data([], oblasts=oblasts))
        sensor = RadarUaUkraineAlertsBinarySensor(coordinator, make_entry(), "donetska")
        assert sensor.is_on is True

    def test_off_when_no_oblast_red(self, make_coordinator):
        oblasts = [
            {"key": "lvivska", "name": "Львівська область", "oblast": "Львівська область", "level": "green"}
        ]
        coordinator = make_coordinator(make_data([], oblasts=oblasts))
        sensor = RadarUaUkraineAlertsBinarySensor(coordinator, make_entry(), "donetska")
        assert sensor.is_on is False

    def test_attributes_alerts_by_region_and_count(self, make_coordinator):
        oblasts = [
            {"key": "donetska", "name": "Донецька область", "oblast": "Донецька область", "level": "red"},
            {"key": "lvivska", "name": "Львівська область", "oblast": "Львівська область", "level": "yellow"},
        ]
        coordinator = make_coordinator(make_data([], oblasts=oblasts))
        sensor = RadarUaUkraineAlertsBinarySensor(coordinator, make_entry(), "donetska")
        attrs = sensor.extra_state_attributes
        assert attrs["alerts_by_region"] == {
            "Донецька область": "red",
            "Львівська область": "yellow",
        }
        assert attrs["count_alerts"] == 1

    def test_single_instance_guard_detects_existing_entity(self, monkeypatch):
        class FakeRegistry:
            entities = {
                "binary_sensor.radar_ua_ukraine_alerts": SimpleNamespace(
                    unique_id="other-entry_ukraine_alerts", platform="radar_ua"
                )
            }

        monkeypatch.setattr(
            "radar_ua.binary_sensor.entity_registry.async_get",
            lambda hass: FakeRegistry(),
        )
        assert _has_ukraine_alerts_entity(None, None) is True


class TestRestoredCountSensors:
    def _sensor(self, make_coordinator, threats, value_fn):
        coordinator = make_coordinator(make_data(threats))
        entry = make_entry()
        return RadarUaCountsSensor(
            coordinator, entry, "donetska", "test", "test", "mdi:test", value_fn
        )

    def test_mig31k_counts_only_mig31k_units(self, make_coordinator):
        from radar_ua.sensor import _counts_value

        sensor = self._sensor(make_coordinator, THREATS, lambda c, t: _counts_value(t, "mig31k"))
        assert sensor.native_value == 1

    def test_raid_size_sums_count_field(self, make_coordinator):
        from radar_ua.sensor import _raid_size_value

        sensor = self._sensor(make_coordinator, THREATS, lambda c, t: _raid_size_value(t))
        # t1 count=1 + t2 count=3 + t4 missing count -> 1; resolved t3 excluded
        assert sensor.native_value == 5

    def test_raid_size_defaults_missing_count_to_one(self, make_coordinator):
        from radar_ua.sensor import _raid_size_value

        threats = [{"id": "x", "type": "uav", "region": "Донецька область", "status": "active"}]
        sensor = self._sensor(make_coordinator, threats, lambda c, t: _raid_size_value(t))
        assert sensor.native_value == 1

    def test_total_excludes_resolved(self, make_coordinator):
        from radar_ua.sensor import _total_value

        sensor = self._sensor(make_coordinator, THREATS, lambda c, t: _total_value(t))
        # t1 count=1 + t2 count=3 + t4 missing count -> 1; resolved t3 excluded
        assert sensor.native_value == 5


class TestDataAgeTransportAttribute:
    def test_transport_attribute_rest(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        entry = make_entry()
        sensor = RadarUaDataAgeSensor(coordinator, entry, "donetska")
        assert sensor.extra_state_attributes["transport"] == "rest"

    def test_transport_attribute_websocket(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        stream = coordinator.stream
        stream._snapshot_received = True
        stream._alerts_received = True
        entry = make_entry()
        sensor = RadarUaDataAgeSensor(coordinator, entry, "donetska")
        assert sensor.extra_state_attributes["transport"] == "websocket"


class TestAlertBinarySensorStillWorks:
    def test_oblast_alert_on_red(self, make_coordinator):
        oblasts = [
            {"key": "donetska", "name": "Донецька область", "oblast": "Донецька область", "level": "red"}
        ]
        coordinator = make_coordinator(make_data([], oblasts=oblasts))
        sensor = RadarUaAlertBinarySensor(coordinator, make_entry(), "donetska")
        assert sensor.is_on is True
