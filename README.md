# Radar UA

Home Assistant integration: air raid alerts & airborne threat tracking for Ukraine (one instance = one oblast, optional raion/city).

> ⚠️ **NOT an official alerting system.** For safety rely on official sirens and the [Air Alert](https://alert.military.in.ua/) app.

Data source: [NEPTUN](https://neptun.in.ua/).

## Install (HACS)

**HACS → ⋮ → Custom repositories** → `Kerber0ss/uaradar-ha-integration` (Integration) → install → restart HA → **Settings → Devices & Services → Add Integration → Radar UA**.

## Entities

- `sensor.radar_ua_<region>_level` — red / yellow / green
- `sensor.radar_ua_<region>_alert_since` — alert start (timestamp)
- `sensor.radar_ua_<region>_drones` / `_recon` / `_missiles` / `_kab` / `_mig31k` / `_total` / `_raid_size`
- `sensor.radar_ua_<region>_data_age` — diagnostics
- `binary_sensor.radar_ua_<region>_alert` — alert in the oblast
- `binary_sensor.radar_ua_<region>_advisory` — MiG-31K takeoff
- `binary_sensor.radar_ua_<region>_raion_alert` — alert in configured raion
- `binary_sensor.radar_ua_overview_*` — all-oblast alert overview (disabled by default)
- `geo_location.radar_ua_*` — active threats on the map
- `button.radar_ua_<region>_refresh` — force refresh

Events: `radar_ua_alert_started`, `radar_ua_alert_ended`, `radar_ua_threat_new`.

## Map

```yaml
type: map
geo_location_sources:
  - radar_ua
default_zoom: 6
```

## Dev

```bash
pip install -r requirements_test.txt
pytest
```

MIT — see [LICENSE](LICENSE).
