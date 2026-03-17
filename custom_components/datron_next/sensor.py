"""Sensor platform for Datron NEXT integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, PERCENTAGE, UnitOfLength, UnitOfPressure, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import COORD_FAST, COORD_MEDIUM, COORD_SLOW, DOMAIN


@dataclass(frozen=True, kw_only=True)
class DatronSensorEntityDescription(SensorEntityDescription):
    """Describes a Datron sensor entity."""

    coordinator_key: str
    value_fn: Callable[[dict[str, Any]], Any]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _get_geometry_value(tool_data: dict | None, geom_key: str, attribute: str) -> float | None:
    """Extract a raw value from a tool's geometry array by attribute name.

    NOTE: The Datron API returns all geometry *length* values in **microns**.
    Use ``_get_geometry_mm`` for length attributes (Diameter, FluteLength, etc.)
    so that the value is automatically converted to millimetres.
    """
    if not isinstance(tool_data, dict):
        return None
    geom_list = tool_data.get(geom_key)
    if not isinstance(geom_list, list):
        return None
    for item in geom_list:
        if isinstance(item, dict) and item.get("attribute") == attribute:
            return item.get("value")
    return None


def _get_geometry_mm(
    tool_data: dict | None,
    geom_key: str,
    attribute: str,
    precision: int = 4,
) -> float | None:
    """Return a geometry length value converted from microns to millimetres.

    The Datron API delivers all dimensional geometry values (Diameter,
    FluteLength, BodyLength, OverallLength, CornerRadius, etc.) in **microns**.
    This helper divides the raw value by 1000 and rounds to *precision*
    decimal places (default 4 → 0.1 µm resolution).

    Do **not** use this for dimensionless attributes such as NumberOfFlutes;
    use ``_get_geometry_value`` directly for those.
    """
    raw = _get_geometry_value(tool_data, geom_key, attribute)
    if raw is None:
        return None
    return round(raw / 1000.0, precision)


# ── Sensor descriptions ──────────────────────────────────────────

FAST_SENSORS: tuple[DatronSensorEntityDescription, ...] = (
    # Machine status
    DatronSensorEntityDescription(
        key="machine_execution_state",
        name="Status",
        icon="mdi:state-machine",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "machine_status", "executionState"),
    ),
    # Job progress
    DatronSensorEntityDescription(
        key="job_progress",
        name="Job Progress",
        icon="mdi:progress-clock",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: (
            round(_safe_get(d, "execution", "progress", default=0) * 100, 1)
        ),
    ),
    DatronSensorEntityDescription(
        key="job_elapsed_time",
        name="Job Elapsed Time",
        icon="mdi:timer-outline",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "execution", "programExecutionTime"),
    ),
    DatronSensorEntityDescription(
        key="job_remaining_time",
        name="Job Remaining Time",
        icon="mdi:timer-sand",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "execution", "programmLeftTime"),
    ),
    # Axis positions
    DatronSensorEntityDescription(
        key="axis_x",
        name="Axis X Position",
        icon="mdi:axis-x-arrow",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "axes", "x"),
    ),
    DatronSensorEntityDescription(
        key="axis_y",
        name="Axis Y Position",
        icon="mdi:axis-y-arrow",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "axes", "y"),
    ),
    DatronSensorEntityDescription(
        key="axis_z",
        name="Axis Z Position",
        icon="mdi:axis-z-arrow",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "axes", "z"),
    ),
    DatronSensorEntityDescription(
        key="axis_a",
        name="Axis A Position",
        icon="mdi:rotate-3d-variant",
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "axes", "a"),
    ),
    DatronSensorEntityDescription(
        key="axis_b",
        name="Axis B Position",
        icon="mdi:rotate-3d-variant",
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "axes", "b"),
    ),
    DatronSensorEntityDescription(
        key="axis_c",
        name="Axis C Position",
        icon="mdi:rotate-3d-variant",
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "axes", "c"),
    ),
    # Compressed air
    DatronSensorEntityDescription(
        key="compressed_air_input",
        name="Compressed Air Input Pressure",
        icon="mdi:air-filter",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "compressed_air", "analogSensorForCompressedAirInput", "status"
        ),
    ),
    DatronSensorEntityDescription(
        key="clamping_device_pressure",
        name="Clamping Device Pressure",
        icon="mdi:hydraulic-oil-level",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(
            d, "compressed_air", "analogSensorForClampingDevice", "status"
        ),
    ),
    # Vacuum
    DatronSensorEntityDescription(
        key="vacuum_pressure",
        name="Vacuum Pressure",
        icon="mdi:vacuum",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "vacuum", "analogSensor", "status"),
    ),
    # Feed overrides
    DatronSensorEntityDescription(
        key="feed_override_cutting",
        name="Feed Override Cutting",
        icon="mdi:speedometer",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "feed_override", "cuttingOverride"),
    ),
    DatronSensorEntityDescription(
        key="feed_override_positioning",
        name="Feed Override Positioning",
        icon="mdi:speedometer",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        coordinator_key=COORD_FAST,
        value_fn=lambda d: _safe_get(d, "feed_override", "positioningOverride"),
    ),
    # Status light
    DatronSensorEntityDescription(
        key="status_light",
        name="Status Light",
        icon="mdi:lightbulb",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: (
            f"({_safe_get(d, 'status_light', 'red', default=0)}, "
            f"{_safe_get(d, 'status_light', 'green', default=0)}, "
            f"{_safe_get(d, 'status_light', 'blue', default=0)})"
        ),
        attributes_fn=lambda d: {
            "red": _safe_get(d, "status_light", "red", default=0),
            "green": _safe_get(d, "status_light", "green", default=0),
            "blue": _safe_get(d, "status_light", "blue", default=0),
        },
    ),
    # Latest notification
    DatronSensorEntityDescription(
        key="latest_notification",
        name="Latest Notification",
        icon="mdi:bell-alert",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: (
            (
                next(
                    (n.get("message", "None") for n in reversed(_safe_get(d, "notifications", default=[]))
                     if isinstance(n, dict) and n.get("message", "").strip()),
                    "None"
                )
            )
            if isinstance(_safe_get(d, "notifications", default=[]), list)
            and len(_safe_get(d, "notifications", default=[])) > 0
            else "None"
        ),
        attributes_fn=lambda d: {
            "type": (
                next(
                    (n.get("type") for n in reversed(_safe_get(d, "notifications", default=[]))
                     if isinstance(n, dict) and n.get("message", "").strip()),
                    None
                )
                if isinstance(_safe_get(d, "notifications", default=[]), list)
                and len(_safe_get(d, "notifications", default=[])) > 0
                else None
            ),
            "total_count": (
                len(_safe_get(d, "notifications", default=[]))
                if isinstance(_safe_get(d, "notifications", default=[]), list)
                else 0
            ),
            "error_count": (
                sum(
                    1
                    for n in _safe_get(d, "notifications", default=[])
                    if isinstance(n, dict) and n.get("type") == "Error"
                )
                if isinstance(_safe_get(d, "notifications", default=[]), list)
                else 0
            ),
            "warning_count": (
                sum(
                    1
                    for n in _safe_get(d, "notifications", default=[])
                    if isinstance(n, dict) and n.get("type") == "Warning"
                )
                if isinstance(_safe_get(d, "notifications", default=[]), list)
                else 0
            ),
        },
    ),
    # Latest error (filtered)
    DatronSensorEntityDescription(
        key="latest_error",
        name="Latest Error",
        icon="mdi:alert-circle",
        coordinator_key=COORD_FAST,
        value_fn=lambda d: next(
            (
                n.get("message", "Unknown error")
                for n in (_safe_get(d, "notifications", default=[]) or [])
                if isinstance(n, dict) and n.get("type") == "Error"
            ),
            "None",
        ),
    ),
)

MEDIUM_SENSORS: tuple[DatronSensorEntityDescription, ...] = (
    # Current program
    DatronSensorEntityDescription(
        key="current_program",
        name="Current Program",
        icon="mdi:file-code",
        coordinator_key=COORD_MEDIUM,
        value_fn=lambda d: _safe_get(d, "program", "name"),
        attributes_fn=lambda d: {
            "directory": _safe_get(d, "program", "directory"),
            "full_name": _safe_get(d, "program", "fullName"),
        },
    ),
    # Tool in spindle
    DatronSensorEntityDescription(
        key="tool_in_spindle",
        name="Tool in Spindle",
        icon="mdi:screw-machine-flat-top",
        coordinator_key=COORD_MEDIUM,
        value_fn=lambda d: (
            f"T{_safe_get(d, 'tool_spindle', 'toolNumber', default='?')} \u2014 "
            f"{_safe_get(d, 'tool_spindle', 'name', default='Unknown')}"
            if _safe_get(d, "tool_spindle") else "Empty"
        ),
        attributes_fn=lambda d: {
            "tool_number": _safe_get(d, "tool_spindle", "toolNumber"),
            "article_number": _safe_get(d, "tool_spindle", "articleNumber"),
            "description": _safe_get(d, "tool_spindle", "description"),
            "category": _safe_get(d, "tool_spindle", "category"),
            "vendor": _safe_get(d, "tool_spindle", "vendor"),
            "holder_type": _safe_get(d, "tool_spindle", "holderType"),
            "comment": _safe_get(d, "tool_spindle", "comment"),
            "tool_image": _safe_get(d, "tool_spindle", "imageUrl"),
            # Geometry lengths — converted from API microns → mm
            "flute_length_mm": (
                _get_geometry_mm(_safe_get(d, "tool_spindle"), "realGeometry", "FluteLength")
                or _get_geometry_mm(_safe_get(d, "tool_spindle"), "nominalGeometry", "FluteLength")
            ),
            "tool_projection_mm": (
                _get_geometry_mm(_safe_get(d, "tool_spindle"), "realGeometry", "BodyLength")
                or _get_geometry_mm(_safe_get(d, "tool_spindle"), "nominalGeometry", "BodyLength")
            ),
            "overall_length_mm": (
                _get_geometry_mm(_safe_get(d, "tool_spindle"), "realGeometry", "OverallLength")
                or _get_geometry_mm(_safe_get(d, "tool_spindle"), "nominalGeometry", "OverallLength")
            ),
            "diameter_mm": (
                _get_geometry_mm(_safe_get(d, "tool_spindle"), "realGeometry", "Diameter")
                or _get_geometry_mm(_safe_get(d, "tool_spindle"), "nominalGeometry", "Diameter")
            ),
            # Dimensionless — no conversion needed
            "number_of_flutes": (
                _get_geometry_value(_safe_get(d, "tool_spindle"), "realGeometry", "NumberOfFlutes")
                or _get_geometry_value(_safe_get(d, "tool_spindle"), "nominalGeometry", "NumberOfFlutes")
            ),
            "current_life_minutes": _safe_get(d, "tool_spindle", "currentTotalLife"),
            "max_life_minutes": _safe_get(d, "tool_spindle", "maxToolLife"),
            "current_path_mm": _safe_get(d, "tool_spindle", "currentTotalPath"),
            "max_path_mm": _safe_get(d, "tool_spindle", "maxToolPath"),
        },
    ),
    # Tool counts
    DatronSensorEntityDescription(
        key="tools_in_changer_count",
        name="Tools in Magazine",
        icon="mdi:toolbox",
        state_class=SensorStateClass.MEASUREMENT,
        coordinator_key=COORD_MEDIUM,
        value_fn=lambda d: (
            len(_safe_get(d, "tools_changer", default=[]))
            if isinstance(_safe_get(d, "tools_changer", default=[]), list)
            else 0
        ),
    ),
    DatronSensorEntityDescription(
        key="tools_in_warehouse_count",
        name="Tools in Warehouse",
        icon="mdi:warehouse",
        state_class=SensorStateClass.MEASUREMENT,
        coordinator_key=COORD_MEDIUM,
        value_fn=lambda d: (
            len(_safe_get(d, "tools_warehouse", default=[]))
            if isinstance(_safe_get(d, "tools_warehouse", default=[]), list)
            else 0
        ),
    ),
)

SLOW_SENSORS: tuple[DatronSensorEntityDescription, ...] = (
    DatronSensorEntityDescription(
        key="machine_number",
        name="Machine Number",
        icon="mdi:identifier",
        coordinator_key=COORD_SLOW,
        value_fn=lambda d: _safe_get(d, "machine_number", "number"),
    ),
    DatronSensorEntityDescription(
        key="machine_type",
        name="Machine Type",
        icon="mdi:factory",
        coordinator_key=COORD_SLOW,
        value_fn=lambda d: _safe_get(d, "machine_type", "displayName"),
        attributes_fn=lambda d: {
            "technical_type": _safe_get(d, "machine_type", "type"),
        },
    ),
    DatronSensorEntityDescription(
        key="software_version",
        name="Software Version",
        icon="mdi:information-outline",
        coordinator_key=COORD_SLOW,
        value_fn=lambda d: _safe_get(d, "software_version", "softwareVersion"),
    ),
    DatronSensorEntityDescription(
        key="spindle_runtime",
        name="Spindle Runtime",
        icon="mdi:engine",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        coordinator_key=COORD_SLOW,
        value_fn=lambda d: _safe_get(d, "runtime", "spindleRuntimeHours"),
    ),
    DatronSensorEntityDescription(
        key="machine_runtime",
        name="Machine Runtime",
        icon="mdi:clock-outline",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        coordinator_key=COORD_SLOW,
        value_fn=lambda d: _safe_get(d, "runtime", "machineRuntimeHours"),
    ),
)

ALL_SENSORS = FAST_SENSORS + MEDIUM_SENSORS + SLOW_SENSORS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators = {
        COORD_FAST: data[COORD_FAST],
        COORD_MEDIUM: data[COORD_MEDIUM],
        COORD_SLOW: data[COORD_SLOW],
    }

    entities = [
        DatronSensor(
            coordinator=coordinators[desc.coordinator_key],
            description=desc,
            entry=entry,
        )
        for desc in ALL_SENSORS
    ]
    async_add_entities(entities)


class DatronSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Datron NEXT sensor."""

    entity_description: DatronSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: DatronSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.coordinator.data is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
