# Radar UA

Home Assistant integration for direct [NEPTUN](https://neptun.in.ua/developers) alert levels and airborne threats (one instance = one oblast, optional raion).

Data is streamed live over the NEPTUN **WebSocket** (`wss://neptun.in.ua/api/v1/stream`, one connection for all entries, sub-second event latency). If the stream is down, the integration automatically falls back to **REST polling** (default every 30 s, configurable) until the stream reconnects.

> ⚠️ **NOT an official alerting system.** For safety rely on official sirens and the [Air Alert](https://alert.military.in.ua/) app.

Data source: [NEPTUN](https://neptun.in.ua/).

## Install (HACS)

**HACS → ⋮ → Custom repositories** → `Kerber0ss/uaradar-ha-integration` (Integration) → install → restart HA → **Settings → Devices & Services → Add Integration → Radar UA**.

## Entities

- `sensor.radar_ua_<region>_level` — direct `red` / `yellow` / `green` level from NEPTUN for the configured oblast or raion
- `sensor.radar_ua_<region>_alert_since` — alert start (timestamp)
- `sensor.radar_ua_<region>_drones` / `_recon` / `_missiles` / `_kab` / `_mig31k` / `_total` / `_raid_size` — threat counters in the configured raion (`_raid_size` sums the `count` field of active threats)
- `sensor.radar_ua_<region>_distance` — straight-line distance to the nearest threat in the configured raion (see [Distance sensor](#distance-sensor), v2.2.0+; requires a reference city)
- `sensor.radar_ua_<region>_data_age` — diagnostics (also exposes the active `transport`: `websocket` or `rest`)
- `binary_sensor.radar_ua_<region>_alert` — alert in the oblast
- `binary_sensor.radar_ua_<region>_advisory` — MiG-31K takeoff / advisory threat in scope
- `binary_sensor.radar_ua_<region>_raion_alert` — alert in configured raion
- `binary_sensor.radar_ua_ukraine_alerts` — Ukraine-wide overview (single entity; attributes carry every oblast level)
- `geo_location.radar_ua_*` — active threats on the map
- `button.radar_ua_<region>_refresh` — force refresh

Events: `radar_ua_alert_started`, `radar_ua_alert_ended`, `radar_ua_threat_new`.

## Distance sensor

Since **v2.2.0**, an entry with a raion and a **reference city** (a city of that raion picked during setup) gets one extra sensor: `sensor.radar_ua_<region>_distance`.

- **State** — approximate great-circle ("as the crow flies") distance in **km** from the selected city to the nearest reliably located threat **in the selected raion**. Example: with Сумська область → Конотопський район → Конотоп configured, a target over Кролевець is counted too, even when NEPTUN does not mention Konotop itself — the threat is matched to the raion by its NEPTUN raion key or, when the message carries no district, by falling the target's coordinates against a local snapshot of NEPTUN raion boundaries.
- **`unknown`** — when no matching target currently qualifies (it is never `0 km` in that case). Area-only area markers and threats without valid coordinates are ignored.
- **`unavailable`** — when the coordinator data is stale (beyond the unavailability threshold) or the last update failed, per the shared rule of all Radar UA entities.
- **Not** a direction of flight, an arrival-time forecast, or a re-computed alert level: the alert level always comes from NEPTUN as-is.
- Attributes: `reference_city_id`, `reference_city`, and for the nearest target `threat_id`, `threat_type`, `locality` (when present) and `uncertaintyKm` (when present), plus the common NEPTUN attribution/diagnostics attributes.

The distance is approximate by design — great-circle distance, rounded to 0.1 km — and says nothing about where the target is heading.

## Configuration

Setup walks **region → raion → city**:

1. **Region** — pick your oblast.
2. **Raion** — pick the raion within that oblast, or skip it to follow the whole oblast. Kyiv and Sevastopol have no raion step.
3. **City** — for raions that have cities in the bundled catalog, pick the reference city (used as the distance anchor). Choose "— Без міста —" to finish without the distance sensor. The chosen city is validated against the selected raion; a mismatch shows an *invalid city* error. Raions without catalog cities finish without this step.

The reference city is stored in the entry as `reference_city_id` and **never filters threats by name** — it is only the point the distance is measured from.

## Options flow

Reopen the integration (**Configure**) to change:

- **Scan interval** — REST-fallback polling interval in seconds.
- **Raion** — change the raion, or select "— Пропустити —" to clear it.
- **City** — when the chosen raion has catalog cities, a second step offers the reference city of that raion (your current one is preselected).

Saving mirrors the raion/city into the entry and **reloads the entry**, so entities update immediately. **Existing installs can add a raion and a reference city via the options flow without re-adding the integration.** The old free-text city setting of pre-2.2 entries keeps working unchanged; entries without a reference city simply don't get the distance sensor.

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
