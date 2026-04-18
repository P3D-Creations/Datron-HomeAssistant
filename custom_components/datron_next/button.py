"""Button platform for Datron NEXT integration.

Execution-control buttons (Pause / Resume / Abort / Park / Start /
Reload / Load-Selected / Execute-Selected) and dialog confirmation
buttons require the Automation API license tier.

Buttons that are meaningless in the current machine state disable
themselves via ``available`` so the user gets immediate feedback
instead of a 403 from the machine.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .api import DatronApiClient, DatronApiError, DatronStateError
from .const import (
    COORD_FAST,
    COORD_MEDIUM,
    COORD_SLOW,
    DOMAIN,
    IDLE_STATES,
    PAUSED_STATES,
    RUNNING_STATES,
)
from .coordinator import _directory_to_simpl_root

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


def _execution_state(fast_data: dict[str, Any] | None) -> str | None:
    if not isinstance(fast_data, dict):
        return None
    ms = fast_data.get("machine_status")
    if isinstance(ms, dict):
        return ms.get("executionState")
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT button entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: DatronApiClient = data["client"]
    fast_coordinator: DataUpdateCoordinator = data[COORD_FAST]
    medium_coordinator: DataUpdateCoordinator = data[COORD_MEDIUM]
    slow_coordinator: DataUpdateCoordinator = data[COORD_SLOW]
    selection_state: dict[str, Any] = data.setdefault("selection", {})

    entities: list[ButtonEntity] = [
        # ── Data management ──────────────────────────────────
        DatronRefreshButton(entry=entry, coordinators=data),

        # ── Program execution control (Automation API) ───────
        DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="start_program",
            name="Start Program",
            icon="mdi:play",
            action=client.execute_loaded_program,
            allowed_states=IDLE_STATES,
        ),
        DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="pause_program",
            name="Pause Program",
            icon="mdi:pause-circle",
            action=client.pause_execution,
            allowed_states=RUNNING_STATES,
        ),
        DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="resume_program",
            name="Resume Program",
            icon="mdi:play-circle",
            action=client.resume_execution,
            allowed_states=PAUSED_STATES,
        ),
        DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="abort_program",
            name="Abort Program",
            icon="mdi:stop-circle",
            device_class=ButtonDeviceClass.RESTART,
            action=client.abort_execution,
            allowed_states=RUNNING_STATES | PAUSED_STATES,
        ),
        DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="move_to_park_position",
            name="Move to Park Position",
            icon="mdi:home-circle",
            action=client.move_to_park_position,
            # Park should only fire when the machine isn't actively running.
            allowed_states=IDLE_STATES | PAUSED_STATES,
        ),

        # ── Program management ───────────────────────────────
        DatronReloadProgramButton(
            entry=entry,
            client=client,
            medium_coordinator=medium_coordinator,
            fast_coordinator=fast_coordinator,
        ),
        DatronSelectedProgramActionButton(
            entry=entry,
            client=client,
            fast_coordinator=fast_coordinator,
            slow_coordinator=slow_coordinator,
            selection_state=selection_state,
            key="load_selected_program",
            name="Load Selected Program",
            icon="mdi:file-upload",
            execute=False,
        ),
        DatronSelectedProgramActionButton(
            entry=entry,
            client=client,
            fast_coordinator=fast_coordinator,
            slow_coordinator=slow_coordinator,
            selection_state=selection_state,
            key="execute_selected_program",
            name="Execute Selected Program",
            icon="mdi:rocket-launch",
            execute=True,
        ),

        # ── Dialog control (Automation API) ──────────────────
        DatronConfirmDialogButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="confirm_dialog_ok",
            name="Confirm Dialog (OK)",
            icon="mdi:check-circle",
            pick_left=False,
        ),
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
        from .const import COORD_AXIS
        for key in (COORD_FAST, COORD_MEDIUM, COORD_SLOW, COORD_AXIS):
            coordinator = self._coordinators.get(key)
            if coordinator is not None:
                tasks.append(coordinator.async_request_refresh())
        if tasks:
            await asyncio.gather(*tasks)


def _run_action_result_handling(name: str, result: Any) -> None:
    """Common result handling for Datron execution endpoints.

    ExecutionResult returns {resultCode: str}. Raises HomeAssistantError
    on a non-Success resultCode so the HA UI surfaces the failure.
    """
    if isinstance(result, dict):
        code = result.get("resultCode")
        if code and code != "Success":
            raise HomeAssistantError(f"{name}: machine returned '{code}'")


class DatronStateGatedActionButton(CoordinatorEntity, ButtonEntity):
    """An action button that is only available in certain machine states."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        client: DatronApiClient,
        coordinator: DataUpdateCoordinator,
        key: str,
        name: str,
        icon: str,
        action: Callable[[], Awaitable[Any]],
        allowed_states: set[str],
        device_class: ButtonDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._action = action
        self._allowed_states = allowed_states
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        if device_class is not None:
            self._attr_device_class = device_class
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        state = _execution_state(self.coordinator.data)
        # If we can't read the state yet, leave the button available so
        # the user can still try — better than a blank dashboard.
        if state is None:
            return True
        return state in self._allowed_states

    async def async_press(self) -> None:
        try:
            result = await self._action()
        except DatronStateError as err:
            raise HomeAssistantError(
                f"{self._attr_name} rejected by machine: {err}"
            ) from err
        except DatronApiError as err:
            raise HomeAssistantError(
                f"{self._attr_name} failed: {err}"
            ) from err
        _run_action_result_handling(self._attr_name or "action", result)


class DatronReloadProgramButton(CoordinatorEntity, ButtonEntity):
    """Reload the currently loaded program (re-issue LoadProgram on same path)."""

    _attr_has_entity_name = True
    _attr_name = "Reload Program"
    _attr_icon = "mdi:restore"

    def __init__(
        self,
        entry: ConfigEntry,
        client: DatronApiClient,
        medium_coordinator: DataUpdateCoordinator,
        fast_coordinator: DataUpdateCoordinator,
    ) -> None:
        # Track the medium coordinator so we re-evaluate availability
        # when the currently-loaded program changes.
        super().__init__(medium_coordinator)
        self._client = client
        self._fast_coordinator = fast_coordinator
        self._attr_unique_id = f"{entry.entry_id}_reload_program"
        self._attr_device_info = _device_info(entry)

    def _current_program_path(self) -> str | None:
        """Build a SimPL path acceptable to LoadProgram.

        LoadProgram expects ``machine:program.simpl`` (or
        ``device:DEVICENAME\\share\\program.simpl``). Datron firmware
        variants return ``directory`` in three shapes — SimPL, UNC
        (``\\\\SERVER\\share``), or Windows drive-letter — and we
        normalise those via ``_directory_to_simpl_root`` so we always
        build a valid SimPL path where possible.
        """
        data = self.coordinator.data or {}
        program = data.get("program")
        if not isinstance(program, dict):
            return None

        name = program.get("name")
        if not isinstance(name, str) or not name:
            return None
        filename = name if name.lower().endswith(".simpl") else f"{name}.simpl"

        directory = program.get("directory") or ""
        root = _directory_to_simpl_root(directory) if isinstance(directory, str) else None
        if root:
            # UNC and device: paths use backslash separators; machine:
            # paths use forward slashes. Match whichever the root uses.
            if root.endswith(":") or root.endswith("\\") or root.endswith("/"):
                return f"{root}{filename}"
            sep = "\\" if "\\" in root else "/"
            return f"{root}{sep}{filename}"

        # Last resort: assume machine root.
        return f"machine:{filename}"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self._current_program_path() is None:
            return False
        # Only reload when not actively running.
        state = _execution_state(self._fast_coordinator.data)
        if state is None:
            return True
        return state in IDLE_STATES | PAUSED_STATES

    async def async_press(self) -> None:
        data = self.coordinator.data or {}
        program = data.get("program")
        path = self._current_program_path()
        _LOGGER.debug(
            "Reload Program: raw program=%r, derived path=%r",
            program, path,
        )
        if not path:
            raise HomeAssistantError("No program is currently loaded")
        try:
            result = await self._client.load_program(path)
        except DatronApiError as err:
            raise HomeAssistantError(
                f"Reload Program failed for path '{path}': {err}"
            ) from err
        if isinstance(result, dict):
            code = result.get("resultCode")
            if code and code != "Success":
                raise HomeAssistantError(
                    f"Reload Program: machine returned '{code}' for path '{path}' "
                    f"(raw program object: {program})"
                )


class DatronSelectedProgramActionButton(ButtonEntity):
    """Load or Execute the program chosen in the Selected Program select entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        client: DatronApiClient,
        fast_coordinator: DataUpdateCoordinator,
        slow_coordinator: DataUpdateCoordinator,
        selection_state: dict[str, Any],
        key: str,
        name: str,
        icon: str,
        execute: bool,
    ) -> None:
        self._client = client
        self._fast_coordinator = fast_coordinator
        self._slow_coordinator = slow_coordinator
        self._selection_state = selection_state
        self._execute = execute
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        if not self._selection_state.get("path"):
            return False
        # Executing requires an idle machine; loading also requires idle.
        state = _execution_state(self._fast_coordinator.data)
        if state is None:
            return True
        return state in IDLE_STATES

    async def async_press(self) -> None:
        path = self._selection_state.get("path")
        if not path:
            raise HomeAssistantError("No program selected")
        try:
            if self._execute:
                result = await self._client.execute_program_async(path)
                _run_action_result_handling("Execute Selected Program", result)
            else:
                result = await self._client.load_program(path)
                _run_action_result_handling("Load Selected Program", result)
        except DatronApiError as err:
            raise HomeAssistantError(
                f"{self._attr_name} failed: {err}"
            ) from err


class DatronConfirmDialogButton(CoordinatorEntity, ButtonEntity):
    """Confirm (or cancel) the currently open machine dialog."""

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

    def _open_dialog(self) -> dict[str, Any] | None:
        coord_data: dict[str, Any] = self.coordinator.data or {}
        dialog = coord_data.get("open_dialog")
        return dialog if isinstance(dialog, dict) else None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self._open_dialog() is not None

    async def async_press(self) -> None:
        dialog = self._open_dialog()
        if not dialog:
            raise HomeAssistantError("No open dialog to confirm/cancel")

        dialog_id: str | None = dialog.get("id")
        if not dialog_id:
            raise HomeAssistantError("Open dialog has no ID field")

        primary_key = "leftButtons" if self._pick_left else "rightButtons"
        fallback_key = "rightButtons" if self._pick_left else "leftButtons"
        buttons: list[str] = dialog.get(primary_key) or dialog.get(fallback_key) or []
        if not buttons:
            raise HomeAssistantError(
                f"Dialog '{dialog.get('caption', '')}' has no buttons to click"
            )

        button_label = buttons[0]
        _LOGGER.debug(
            "Confirming dialog '%s' with button '%s'",
            dialog.get("caption", ""),
            button_label,
        )
        try:
            await self._client.confirm_dialog(dialog_id, button_label)
        except DatronApiError as err:
            raise HomeAssistantError(f"Confirm dialog failed: {err}") from err
