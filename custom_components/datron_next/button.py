"""Button platform for Datron NEXT integration.

Execution-control buttons (Pause / Resume / Abort / Park) and dialog
confirmation buttons require the Automation API license tier.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .api import DatronApiClient, DatronApiError
from .const import COORD_FAST, COORD_MEDIUM, COORD_SLOW, DOMAIN

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
    """Set up Datron NEXT button entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: DatronApiClient = data["client"]
    fast_coordinator: DataUpdateCoordinator = data[COORD_FAST]

    entities: list[ButtonEntity] = [
        # ── Data management ──────────────────────────────────
        DatronRefreshButton(entry=entry, coordinators=data),

        # ── Program execution control (Automation API) ───────
        DatronSimpleActionButton(
            entry=entry,
            client=client,
            key="pause_program",
            name="Pause Program",
            icon="mdi:pause-circle",
            action=client.pause_execution,
        ),
        DatronSimpleActionButton(
            entry=entry,
            client=client,
            key="resume_program",
            name="Resume Program",
            icon="mdi:play-circle",
            action=client.resume_execution,
        ),
        DatronSimpleActionButton(
            entry=entry,
            client=client,
            key="abort_program",
            name="Abort Program",
            icon="mdi:stop-circle",
            device_class=ButtonDeviceClass.RESTART,
            action=client.abort_execution,
        ),
        DatronSimpleActionButton(
            entry=entry,
            client=client,
            key="move_to_park_position",
            name="Move to Park Position",
            icon="mdi:home-circle",
            action=client.move_to_park_position,
        ),

        # ── Dialog control (Automation API) ──────────────────
        # "OK" presses the first right-side button (positive / accept action)
        DatronConfirmDialogButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="confirm_dialog_ok",
            name="Confirm Dialog (OK)",
            icon="mdi:check-circle",
            pick_left=False,
        ),
        # "Cancel" presses the first left-side button (negative / dismiss action)
        DatronConfirmDialogButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="confirm_dialog_cancel",
            name="Confirm Dialog (Cancel)",
            icon="mdi:cancel",
            pick_left=True,
        ),
    ]
    async_add_entities(entities)


# ── Button implementations ────────────────────────────────────────────────────


class DatronRefreshButton(ButtonEntity):
    """Force a manual refresh of all coordinator data."""

    _attr_has_entity_name = True
    _attr_name = "Refresh Data"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, coordinators: dict[str, Any]) -> None:
        self._coordinators = coordinators
        self._attr_unique_id = f"{entry.entry_id}_refresh_data"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        """Refresh all coordinators in parallel."""
        import asyncio
        tasks = []
        for key in (COORD_FAST, COORD_MEDIUM, COORD_SLOW):
            coordinator = self._coordinators.get(key)
            if coordinator is not None:
                tasks.append(coordinator.async_request_refresh())
        if tasks:
            await asyncio.gather(*tasks)


class DatronSimpleActionButton(ButtonEntity):
    """A button that triggers a single no-argument API action."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        client: DatronApiClient,
        key: str,
        name: str,
        icon: str,
        action: Callable[[], Awaitable[Any]],
        device_class: ButtonDeviceClass | None = None,
    ) -> None:
        self._client = client
        self._action = action
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        if device_class is not None:
            self._attr_device_class = device_class
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        """Execute the API action."""
        try:
            result = await self._action()
            if isinstance(result, dict):
                code = result.get("resultCode")
                if code and code != "Success":
                    _LOGGER.warning(
                        "Action '%s' returned non-success code: %s",
                        self._attr_name,
                        code,
                    )
        except DatronApiError as err:
            _LOGGER.error("Error pressing '%s': %s", self._attr_name, err)


class DatronConfirmDialogButton(CoordinatorEntity, ButtonEntity):
    """Confirm (or cancel) the currently open machine dialog.

    Reads the open dialog from the fast coordinator data and presses
    either the first right-side button (OK) or the first left-side
    button (Cancel), falling back to the other side if empty.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        client: DatronApiClient,
        coordinator: DataUpdateCoordinator,
        key: str,
        name: str,
        icon: str,
        pick_left: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._pick_left = pick_left
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        """Click the appropriate dialog button."""
        coord_data: dict[str, Any] = self.coordinator.data or {}
        dialog = coord_data.get("open_dialog")

        if not isinstance(dialog, dict):
            _LOGGER.warning("No open dialog to confirm/cancel")
            return

        dialog_id: str | None = dialog.get("id")
        if not dialog_id:
            _LOGGER.warning("Open dialog has no ID field")
            return

        # Determine which side's button list to use, falling back to the other
        primary_key = "leftButtons" if self._pick_left else "rightButtons"
        fallback_key = "rightButtons" if self._pick_left else "leftButtons"
        buttons: list[str] = dialog.get(primary_key) or dialog.get(fallback_key) or []

        if not buttons:
            _LOGGER.warning(
                "Dialog '%s' has no buttons to click", dialog.get("caption", "")
            )
            return

        button_label = buttons[0]
        _LOGGER.debug(
            "Confirming dialog '%s' with button '%s'",
            dialog.get("caption", ""),
            button_label,
        )
        try:
            await self._client.confirm_dialog(dialog_id, button_label)
        except DatronApiError as err:
            _LOGGER.error("Error confirming dialog: %s", err)
