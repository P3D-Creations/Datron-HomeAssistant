"""Button platform for Datron NEXT integration.

Control buttons for program execution (requires Automation API tier).
These are defined now but will only function once the Automation API
license is activated on the machine.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Placeholder button descriptions for future Automation API tier.
# These buttons are created in a disabled-by-default state since the
# Automation API is not yet available.
BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="refresh_data",
        name="Refresh Data",
        icon="mdi:refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT buttons from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    entities = [
        DatronRefreshButton(
            entry=entry,
            description=BUTTON_DESCRIPTIONS[0],
            coordinators=data,
        ),
    ]
    async_add_entities(entities)


class DatronRefreshButton(ButtonEntity):
    """Button to trigger a manual data refresh across all coordinators."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        description: ButtonEntityDescription,
        coordinators: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        self.entity_description = description
        self._coordinators = coordinators
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"https://{entry.data[CONF_HOST]}",
        )

    async def async_press(self) -> None:
        """Handle the button press — refresh all coordinators."""
        from .const import COORD_FAST, COORD_MEDIUM, COORD_SLOW

        for key in (COORD_FAST, COORD_MEDIUM, COORD_SLOW):
            coordinator = self._coordinators.get(key)
            if coordinator is not None:
                await coordinator.async_request_refresh()
