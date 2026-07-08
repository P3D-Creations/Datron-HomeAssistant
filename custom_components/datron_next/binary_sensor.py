"""Binary sensor platform for Datron NEXT integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_LIVE,
    CONNECTION_NEXT,
    COORD_FAST,
    DOMAIN,
)
from .entity import build_device_info

# Binary sensors backed by an optional hardware field. On Datron Live the
# digital compressed-air / vacuum sensors are structurally absent, and a given
# machine may lack an EKD tank or a 2nd Microjet tank — those fields come back
# null. For Live entries we skip a sensor when its source field is null in the
# initial poll so the device page and history stay clean. Any Live machine that
# DOES have the hardware reports a non-null field and keeps the sensor.
_LIVE_OPTIONAL_BINARY_FIELDS: dict[str, tuple[str, ...]] = {
    "compressed_air_input_ok": ("compressed_air", "digitalSensorForCompressedAirInput"),
    "vacuum_sensor": ("vacuum", "digitalSensor"),
    "ekd_tank_empty": ("spray_system", "datronEkd"),
    "microjet_tank2_empty": ("spray_system", "microjet", "tank2IsEmpty"),
}


def _field_present(data: dict[str, Any] | None, path: tuple[str, ...]) -> bool:
    """Return True if the nested field at *path* is present and non-null."""
    current: Any = data or {}
    for key in path:
        if not isinstance(current, dict):
            return False
        current = current.get(key)
    return current is not None


@dataclass(frozen=True, kw_only=True)
class DatronBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Datron binary sensor entity."""

    coordinator_key: str
    value_fn: Callable[[dict[str, Any]], bool | None]


def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


BINARY_SENSORS: tuple[DatronBinarySensorEntityDescription, ...] = (
    # Machine running
    DatronBinarySensorEntityDescription(
        key="machine_running",
        name="Machine Running",
        icon="mdi:play-circle",
        device_class=BinarySensorDeviceClass.RUNNING,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: (
            _safe_get(d, "machine_status", "executionState") == "Running"
        ),
    ),
    # Machine has error — fires on an Error-type notification, an open dialog
    # whose severity is Error (e.g. a fault/tool-breakage prompt the machine
    # raises interactively), or an empty Microjet tank. Gives a single
    # PROBLEM-class sensor to alert / automate off of.
    DatronBinarySensorEntityDescription(
        key="machine_error",
        name="Machine Error",
        icon="mdi:alert-circle",
        device_class=BinarySensorDeviceClass.PROBLEM,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: (
            any(
                isinstance(n, dict) and n.get("type") == "Error"
                for n in (_safe_get(d, "notifications", default=[]) or [])
            )
            or _safe_get(d, "open_dialog", "severity") == "Error"
            or _safe_get(d, "spray_system", "microjet", "tank1IsEmpty", "status") is True
        ),
    ),
    # Compressed air input OK (digital sensor)
    DatronBinarySensorEntityDescription(
        key="compressed_air_input_ok",
        name="Compressed Air Input",
        icon="mdi:air-filter",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "compressed_air", "digitalSensorForCompressedAirInput", "status"
        ),
    ),
    # Compressed air software monitor enabled
    DatronBinarySensorEntityDescription(
        key="compressed_air_monitor",
        name="Compressed Air Monitor",
        icon="mdi:shield-check",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "compressed_air", "compressedAirSoftwareMonitorEnabled"
        ),
    ),
    # Vacuum active
    DatronBinarySensorEntityDescription(
        key="vacuum_active",
        name="Vacuum Active",
        icon="mdi:vacuum",
        device_class=BinarySensorDeviceClass.RUNNING,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "vacuum", "isActivated"),
    ),
    # Vacuum digital sensor
    DatronBinarySensorEntityDescription(
        key="vacuum_sensor",
        name="Vacuum Sensor",
        icon="mdi:vacuum",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "vacuum", "digitalSensor", "status"),
    ),
    # EKD tank empty
    DatronBinarySensorEntityDescription(
        key="ekd_tank_empty",
        name="EKD Tank Empty",
        icon="mdi:cup-water",
        device_class=BinarySensorDeviceClass.PROBLEM,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "spray_system", "datronEkd", "tankIsEmpty", "status"
        ),
    ),
    # Microjet tank 1 empty
    DatronBinarySensorEntityDescription(
        key="microjet_tank1_empty",
        name="Microjet Tank 1 Empty",
        icon="mdi:cup-water",
        device_class=BinarySensorDeviceClass.PROBLEM,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "spray_system", "microjet", "tank1IsEmpty", "status"
        ),
    ),
    # Microjet tank 2 empty
    DatronBinarySensorEntityDescription(
        key="microjet_tank2_empty",
        name="Microjet Tank 2 Empty",
        icon="mdi:cup-water",
        device_class=BinarySensorDeviceClass.PROBLEM,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "spray_system", "microjet", "tank2IsEmpty", "status"
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    is_live = data.get(CONF_CONNECTION_TYPE, CONNECTION_NEXT) == CONNECTION_LIVE
    fast_data = data[COORD_FAST].data if data.get(COORD_FAST) else None

    def _include(desc: DatronBinarySensorEntityDescription) -> bool:
        # For Live, drop optional-hardware sensors whose source field is null
        # (keeps the device page clean); NEXT is unaffected.
        if is_live and desc.key in _LIVE_OPTIONAL_BINARY_FIELDS:
            return _field_present(fast_data, _LIVE_OPTIONAL_BINARY_FIELDS[desc.key])
        return True

    entities = [
        DatronBinarySensor(
            coordinator=data[desc.coordinator_key],
            description=desc,
            entry=entry,
        )
        for desc in BINARY_SENSORS
        if _include(desc)
    ]
    async_add_entities(entities)


class DatronBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Datron NEXT binary sensor."""

    entity_description: DatronBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: DatronBinarySensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = build_device_info(entry)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
