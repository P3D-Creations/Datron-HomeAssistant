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
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import COORD_FAST, DOMAIN


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
    # Machine has error
    DatronBinarySensorEntityDescription(
        key="machine_error",
        name="Machine Error",
        icon="mdi:alert-circle",
        device_class=BinarySensorDeviceClass.PROBLEM,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: any(
            isinstance(n, dict) and n.get("type") == "Error"
            for n in (_safe_get(d, "notifications", default=[]) or [])
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

    entities = [
        DatronBinarySensor(
            coordinator=data[desc.coordinator_key],
            description=desc,
            entry=entry,
        )
        for desc in BINARY_SENSORS
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"https://{entry.data[CONF_HOST]}",
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
