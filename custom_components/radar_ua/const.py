"""Constants for the Radar UA integration."""

from homeassistant.const import Platform

DOMAIN = "radar_ua"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.GEO_LOCATION,
    Platform.BUTTON,
    Platform.EVENT,
]

CONF_REGION = "region"  # ключ региона из API meta
CONF_RAION = "raion"  # район из статического списка (или None)
CONF_CITY = "city"  # свободный текст, опционально
CONF_SCAN_INTERVAL = "scan_interval"  # секунд, default 10, min 5
CONF_UKRAINE_OVERVIEW = "ukraine_overview"  # bool, default True

ATTR_FETCH_OK = "fetch_ok"
ATTR_SOURCE_AGE_S = "source_age_s"
ATTR_ATTRIBUTION = "attribution"
ATTR_UNAVAILABLE_AFTER = "unavailable_after_s"

LEVEL_RED = "red"
LEVEL_YELLOW = "yellow"
LEVEL_GREEN = "green"

# типы целей
THREAT_UAV = "uav"
THREAT_RECON = "recon"
THREAT_MISSILE = "missile"
THREAT_BALLISTIC = "ballistic"
THREAT_KAB = "kab"
THREAT_MIG31K = "mig31k"

DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
DEFAULT_UNAVAILABLE_AFTER = 300  # 5 минут

# Ключ региона в ответе API, которого нет в meta
REGION_OTHER = "other"
