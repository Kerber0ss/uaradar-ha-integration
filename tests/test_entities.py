"""Tests for the restored entities: advisory, ukraine_alerts, mig31k, raid_size."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength

from radar_ua.binary_sensor import (
    RadarUaAdvisoryBinarySensor,
    RadarUaAlertBinarySensor,
    RadarUaUkraineAlertsBinarySensor,
    _has_ukraine_alerts_entity,
)
from radar_ua.sensor import (
    RadarUaDataAgeSensor,
    RadarUaCountsSensor,
    RadarUaDistanceSensor,
)


def make_entry_with_city(region="sumska", raion="Конотопський район", city_id="UA59020070010054283"):
    """Entry with a reference city: the only shape that gets a distance sensor."""
    return SimpleNamespace(
        entry_id="test-entry",
        options={},
        data={"region": region, "raion": raion, "reference_city_id": city_id},
    )


def make_distance_sensor(coordinator, entry):
    """Distance sensor built the way async_setup_entry does it."""
    from radar_ua.geo.cities import city_by_id

    city = city_by_id(entry.data["reference_city_id"])
    return RadarUaDistanceSensor(coordinator, entry, entry.data["region"], city)

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


def distance_threat(threat_id, lat, lon, **overrides):
    """Active Сумська threat with coordinates, shaped like the live API."""
    threat = {
        "id": threat_id,
        "type": "uav",
        "region": "Сумська область",
        "district": "Конотопський район",
        "regionKey": "конотопський",
        "locality": "",
        "lat": lat,
        "lon": lon,
        "status": "active",
        "count": 1,
    }
    threat.update(overrides)
    return threat


class TestDistanceSensorSetup:
    async def test_created_only_with_resolvable_reference_city(self, make_coordinator):
        import radar_ua.sensor as sensor_module

        coordinator = make_coordinator(make_data([]))
        added: list = []

        def fake_add_entities(new_entities, update_before_add=False):
            added.extend(new_entities)

        entry = make_entry()
        entry.runtime_data = coordinator
        # Coordinator of a legacy entry (donetska, no reference city).
        await sensor_module.async_setup_entry(None, entry, fake_add_entities)
        assert not any(
            isinstance(entity, RadarUaDistanceSensor) for entity in added
        )

    async def test_created_for_entry_with_reference_city(self, make_coordinator):
        import radar_ua.sensor as sensor_module

        coordinator = make_coordinator(make_data([]))
        added: list = []

        def fake_add_entities(new_entities, update_before_add=False):
            added.extend(new_entities)

        entry = make_entry_with_city()
        entry.runtime_data = coordinator
        await sensor_module.async_setup_entry(None, entry, fake_add_entities)
        distance = [
            entity
            for entity in added
            if isinstance(entity, RadarUaDistanceSensor)
        ]
        assert len(distance) == 1
        assert distance[0].unique_id == "test-entry_sumska_distance"

    async def test_not_created_for_unresolvable_city_id(self, make_coordinator):
        import radar_ua.sensor as sensor_module

        coordinator = make_coordinator(make_data([]))
        added: list = []

        async def fake_add_entities(new_entities, update_before_add=False):
            added.extend(new_entities)

        entry = make_entry_with_city(city_id="no-such-city")
        entry.runtime_data = coordinator
        await sensor_module.async_setup_entry(None, entry, fake_add_entities)
        assert not any(
            isinstance(entity, RadarUaDistanceSensor) for entity in added
        )


class TestDistanceSensorNearest:
    def test_nearest_of_two_threats(self, make_coordinator):
        # Krolevets ~37 km from Konotop; the other point ~2 km.
        threats = [
            distance_threat("trk_far", 51.5548, 33.3875),
            distance_threat("trk_near", 51.26, 33.22),
        ]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())

        assert 2.0 < sensor.native_value < 3.0
        attrs = sensor.extra_state_attributes
        assert attrs["threat_id"] == "trk_near"

    def test_tie_broken_by_threat_id(self, make_coordinator):
        # Two threats at exactly the same spot: the lower id wins.
        threats = [
            distance_threat("trk_b", 51.3, 33.25),
            distance_threat("trk_a", 51.3, 33.25),
        ]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.native_value == round(sensor._candidates[0][0], 1)
        assert sensor._nearest[1]["id"] == "trk_a"
        assert sensor.extra_state_attributes["threat_id"] == "trk_a"

    def test_area_only_excluded(self, make_coordinator):
        threats = [distance_threat("trk_area", 51.24, 33.21, areaOnly=True)]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.native_value is None

    def test_missing_and_non_finite_coordinates_excluded(self, make_coordinator):
        threats = [
            distance_threat("trk_noloc", lat=None, lon=None),
            distance_threat("trk_nan", lat=float("nan"), lon=33.4),
        ]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.native_value is None

    def test_resolved_excluded(self, make_coordinator):
        threats = [distance_threat("trk_old", 51.24, 33.21, status="resolved")]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.native_value is None

    def test_krolevets_target_seen_from_konotop(self, make_coordinator):
        # The plan-distance acceptance scenario: a target over Krolevets
        # (empty district -> geometric raion membership) yields a non-zero
        # distance for a Konotop-based entry.
        threats = [distance_threat("trk_far", 51.5548, 33.3875, district="", regionKey=None)]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert 36.0 < sensor.native_value < 38.5
        assert sensor.extra_state_attributes["threat_id"] == "trk_far"


class TestDistanceSensorStates:
    def test_no_candidates_state_unknown(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.native_value is None  # None -> unknown, never 0

    def test_unavailable_on_stale_coordinator(self, make_coordinator):
        # Data older than DEFAULT_UNAVAILABLE_AFTER (300 s).
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        data = make_data([distance_threat("trk_near", 51.24, 33.21)])
        data["updated"] = stale_time
        coordinator = make_coordinator(data)
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.available is False

    def test_available_on_fresh_data(self, make_coordinator):
        coordinator = make_coordinator(make_data([distance_threat("trk_near", 51.24, 33.21)]))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.available is True

    def test_unavailable_after_failed_update(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        coordinator.last_update_success = False
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.available is False


class TestDistanceSensorAttributes:
    def test_reference_city_attributes_present(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        attrs = sensor.extra_state_attributes
        assert attrs["reference_city_id"] == "UA59020070010054283"
        assert attrs["reference_city"] == "Конотоп"

    def test_nearest_threat_attributes_present(self, make_coordinator):
        threats = [
            distance_threat(
                "trk_near",
                51.2397,
                33.2067,
                locality="Конотоп",
                uncertaintyKm=3,
            )
        ]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        attrs = sensor.extra_state_attributes
        assert attrs["threat_id"] == "trk_near"
        assert attrs["threat_type"] == "uav"
        assert attrs["locality"] == "Конотоп"
        assert attrs["uncertaintyKm"] == 3

    def test_no_threat_attributes_without_candidates(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        attrs = sensor.extra_state_attributes
        assert "threat_id" not in attrs
        assert "threat_type" not in attrs

    def test_unit_and_device_class(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        sensor = make_distance_sensor(coordinator, make_entry_with_city())
        assert sensor.native_unit_of_measurement == UnitOfLength.KILOMETERS
        assert sensor.device_class == SensorDeviceClass.DISTANCE
        assert sensor.state_class == SensorStateClass.MEASUREMENT

    def test_unique_id_contains_distance_key(self, make_coordinator):
        coordinator = make_coordinator(make_data([]))
        entry = make_entry_with_city()
        sensor = make_distance_sensor(coordinator, entry)
        assert sensor.unique_id == "test-entry_sumska_distance"


class TestDistanceSensorScoping:
    def test_legacy_city_entry_has_no_reference_city_sensor_data(self, make_coordinator):
        # Entry without reference_city_id: scoped threats keep legacy city
        # narrowing; the sensor itself is simply never created for it
        # (guarded in async_setup_entry).
        entry = SimpleNamespace(
            entry_id="test-entry",
            options={},
            data={"region": "sumska", "raion": "Конотопський район", "city": "Конотоп"},
        )
        threats = [
            distance_threat("trk_konotop", 51.2387, 33.1986, locality="Конотоп"),
            distance_threat("trk_krolevets", 51.5548, 33.3875, district="", regionKey=None),
        ]
        coordinator = make_coordinator(make_data(threats))
        from radar_ua.sensor import RadarUaDistanceSensor
        from radar_ua.geo.cities import city_by_id

        city = city_by_id("UA59020070010054283")
        sensor = RadarUaDistanceSensor(coordinator, entry, "sumska", city)
        # Legacy entries (free-text city, no reference_city_id) keep the old
        # name narrowing: only the threat mentioning Конотоп survives.
        assert 0.3 < sensor.native_value < 1.0
        assert sensor.extra_state_attributes["threat_id"] == "trk_konotop"
        candidate_ids = {t["id"] for _, t in sensor._candidates}
        assert candidate_ids == {"trk_konotop"}

    def test_reference_city_entry_sees_whole_raion(self, make_coordinator):
        # Adding a reference city (via the options flow) removes the name
        # narrowing: the Krolevets-area target now counts too.
        entry = SimpleNamespace(
            entry_id="test-entry",
            options={},
            data={
                "region": "sumska",
                "raion": "Конотопський район",
                "city": "Конотоп",
                "reference_city_id": "UA59020070010054283",
            },
        )
        threats = [
            distance_threat("trk_konotop", 51.2387, 33.1986, locality="Конотоп"),
            distance_threat("trk_krolevets", 51.5548, 33.3875, district="", regionKey=None),
        ]
        coordinator = make_coordinator(make_data(threats))
        from radar_ua.sensor import RadarUaDistanceSensor
        from radar_ua.geo.cities import city_by_id

        city = city_by_id("UA59020070010054283")
        sensor = RadarUaDistanceSensor(coordinator, entry, "sumska", city)
        assert 0.3 < sensor.native_value < 1.0
        candidate_ids = {t["id"] for _, t in sensor._candidates}
        assert candidate_ids == {"trk_konotop", "trk_krolevets"}

    def test_scope_excludes_other_raion_threat(self, make_coordinator):
        # A threat assigned by NEPTUN to Сумський район must not feed the
        # Konotopskyi sensor.
        entry = make_entry_with_city()
        threats = [
            distance_threat(
                "trk_sumy", 50.9119, 34.8027,
                district="Сумський район", regionKey="сумський",
            )
        ]
        coordinator = make_coordinator(make_data(threats))
        sensor = make_distance_sensor(coordinator, entry)
        assert sensor.native_value is None
