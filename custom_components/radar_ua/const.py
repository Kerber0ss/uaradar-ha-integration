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
CONF_CITY = "city"  # свободный текст, опционально (legacy, не используется новыми записями)
CONF_REFERENCE_CITY_ID = "reference_city_id"  # устойчивый id города из справочника (опорная точка расстояния)
CONF_SCAN_INTERVAL = "scan_interval"  # seconds; REST-fallback poll interval, default 30, min 5
# CONF_UKRAINE_OVERVIEW удалён: обзорные сущности больше не создаются.

ATTR_FETCH_OK = "fetch_ok"
ATTR_SOURCE_AGE_S = "source_age_s"
ATTR_ATTRIBUTION = "attribution"
ATTR_UPDATED = "updated"  # ATTENTION: удалён из homeassistant.const в новых версиях HA
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

DEFAULT_SCAN_INTERVAL = 30  # REST fallback poll interval (WS stream is primary)
MIN_SCAN_INTERVAL = 5
DEFAULT_UNAVAILABLE_AFTER = 300  # 5 минут

# Ключ региона в ответе API, которого нет в meta
REGION_OTHER = "other"
