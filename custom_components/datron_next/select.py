"""Select platform for Datron NEXT integration.

Exposes a "Selected Program" dropdown populated from the machine's
filesystem (root + one level of subfolders). The selected SimPL path
is stored in the entry's shared ``selection`` dict so the
Load / Execute Selected Program buttons can act on it.

The program list is refreshed via the slow coordinator (10 min).
Hit the "Refresh Data" button after adding programs to the machine
to repopulate the dropdown without waiting.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import COORD_SLOW, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Datron",
        model="M8Cube",
        sw_version="NEXT",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    slow_coordinator: DataUpdateCoordinator = data[COORD_SLOW]
    selection_state: dict[str, Any] = data.setdefault("selection", {})

    async_add_entities(
        [DatronProgramSelect(entry, slow_coordinator, selection_state)]
    )


class DatronProgramSelect(CoordinatorEntity, SelectEntity):
    """Dropdown of available programs on the machine."""

    _attr_has_entity_name = True
    _attr_name = "Selected Program"
    _attr_icon = "mdi:file-code"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator,
        selection_state: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._selection_state = selection_state
        self._attr_unique_id = f"{entry.entry_id}_selected_program"
        self._attr_device_info = _device_info(entry)

    def _programs(self) -> list[dict[str, str]]:
        data = self.coordinator.data or {}
        progs = data.get("programs")
        return progs if isinstance(progs, list) else []

    def _format_option(self, program: dict[str, str]) -> str:
        """Human-readable dropdown label.

        Shows the folder as a prefix when the program isn't at the root,
        so users can distinguish identically-named files across folders.
        """
        folder = (program.get("folder") or "").strip("/")
        name = program.get("name") or ""
        return f"{folder}/{name}" if folder else name

    @property
    def options(self) -> list[str]:
        return [self._format_option(p) for p in self._programs()]

    @property
    def current_option(self) -> str | None:
        label = self._selection_state.get("label")
        # Only return a label that's still in the current options list,
        # otherwise HA logs warnings.
        return label if label in self.options else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "selected_path": self._selection_state.get("path"),
            "program_count": len(self._programs()),
        }

    async def async_select_option(self, option: str) -> None:
        for program in self._programs():
            if self._format_option(program) == option:
                self._selection_state["label"] = option
                self._selection_state["path"] = program.get("path")
                self.async_write_ha_state()
                return
        _LOGGER.warning("Selected program '%s' not found in current list", option)
