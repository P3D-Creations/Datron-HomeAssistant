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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .api import DatronApiClient, DatronApiError, DatronStateError
from .const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_LIVE,
    CONNECTION_NEXT,
    COORD_FAST,
    COORD_MEDIUM,
    COORD_SLOW,
    DOMAIN,
    IDLE_STATES,
    PAUSED_STATES,
    RUNNING_STATES,
)
from .coordinator import _directory_to_simpl_root
from .entity import build_device_info

_LOGGER = logging.getLogger(__name__)

# Size of the dynamic dialog-button pool. Datron dialogs have at most a handful
# of buttons; extra slots go unavailable when the open dialog has fewer.
DIALOG_BUTTON_POOL_SIZE = 4

# Button keys kept for Datron Live entries. Everything else (Start / Abort /
# Park / Reload / Load-Selected / Execute-Selected) has no Live backing.
LIVE_BUTTON_KEYS = {
    "refresh_data",
    "pause_program",
    "resume_program",
    "activate_machine",
    *{f"dialog_button_{i}" for i in range(1, DIALOG_BUTTON_POOL_SIZE + 1)},
}


def _device_info(entry: ConfigEntry):
    return build_device_info(entry)


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

    connection_type = data.get(CONF_CONNECTION_TYPE, CONNECTION_NEXT)
    is_live = connection_type == CONNECTION_LIVE

    # (key, factory) pairs — the key drives Live gating.
    button_specs: list[tuple[str, ButtonEntity]] = [
        # ── Data management ──────────────────────────────────
        ("refresh_data", DatronRefreshButton(entry=entry, coordinators=data)),

        # ── Program execution control (Automation API) ───────
        ("start_program", DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="start_program",
            name="Start Program",
            icon="mdi:play",
            action=client.execute_loaded_program,
            allowed_states=IDLE_STATES,
        )),
        ("pause_program", DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="pause_program",
            name="Pause Program",
            icon="mdi:pause-circle",
            action=client.pause_execution,
            allowed_states=RUNNING_STATES,
        )),
        ("resume_program", DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="resume_program",
            name="Resume Program",
            icon="mdi:play-circle",
            action=client.resume_execution,
            allowed_states=PAUSED_STATES,
        )),
        ("abort_program", DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="abort_program",
            name="Abort Program",
            icon="mdi:stop-circle",
            device_class=ButtonDeviceClass.RESTART,
            action=client.abort_execution,
            allowed_states=RUNNING_STATES | PAUSED_STATES,
        )),
        ("move_to_park_position", DatronStateGatedActionButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="move_to_park_position",
            name="Move to Park Position",
            icon="mdi:home-circle",
            action=client.move_to_park_position,
            # Park should only fire when the machine isn't actively running.
            allowed_states=IDLE_STATES | PAUSED_STATES,
        )),

        # ── Program management ───────────────────────────────
        ("reload_program", DatronReloadProgramButton(
            entry=entry,
            client=client,
            medium_coordinator=medium_coordinator,
            slow_coordinator=slow_coordinator,
            fast_coordinator=fast_coordinator,
        )),
        ("load_selected_program", DatronSelectedProgramActionButton(
            entry=entry,
            client=client,
            fast_coordinator=fast_coordinator,
            slow_coordinator=slow_coordinator,
            selection_state=selection_state,
            key="load_selected_program",
            name="Load Selected Program",
            icon="mdi:file-upload",
            execute=False,
        )),
        ("execute_selected_program", DatronSelectedProgramActionButton(
            entry=entry,
            client=client,
            fast_coordinator=fast_coordinator,
            slow_coordinator=slow_coordinator,
            selection_state=selection_state,
            key="execute_selected_program",
            name="Execute Selected Program",
            icon="mdi:rocket-launch",
            execute=True,
        )),

        # ── Dialog control — dynamic pool mirroring the live dialog ──
        # Each slot's label and action track the machine's ACTUAL dialog
        # buttons (exact match, no per-dialog entity churn). Slots beyond the
        # current dialog's button count report unavailable.
        *[
            (
                f"dialog_button_{i}",
                DatronDynamicDialogButton(
                    entry=entry,
                    client=client,
                    coordinator=fast_coordinator,
                    index=i - 1,
                    key=f"dialog_button_{i}",
                ),
            )
            for i in range(1, DIALOG_BUTTON_POOL_SIZE + 1)
        ],
        ("activate_machine", DatronDialogLabelButton(
            entry=entry,
            client=client,
            coordinator=fast_coordinator,
            key="activate_machine",
            name="Activate Machine",
            icon="mdi:shield-check",
            match_label="Activate",
        )),
    ]

    entities: list[ButtonEntity] = [
        button
        for key, button in button_specs
        if not is_live or key in LIVE_BUTTON_KEYS
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
        slow_coordinator: DataUpdateCoordinator,
        fast_coordinator: DataUpdateCoordinator,
    ) -> None:
        # Track the medium coordinator so we re-evaluate availability
        # when the currently-loaded program changes.
        super().__init__(medium_coordinator)
        self._client = client
        self._slow_coordinator = slow_coordinator
        self._fast_coordinator = fast_coordinator
        self._attr_unique_id = f"{entry.entry_id}_reload_program"
        self._attr_device_info = _device_info(entry)

    def _match_via_enumeration(
        self, filename: str, directory_hint: str
    ) -> str | None:
        """Look up the program's SimPL path from the enumerated programs list.

        Network-drive programs often report a raw UNC in ``directory``
        while the machine's SimPL alias uses a different server name
        (e.g. ``\\\\P3D_NAS\\Machines\\Datron`` internally → SimPL
        ``network:\\\\Datron``). We can't reverse that mapping, but the
        slow coordinator's ``network:`` enumeration has already returned
        the alias-correct path. Match by filename; if the filename
        collides across folders, disambiguate via a substring of the
        raw directory.
        """
        slow_data = self._slow_coordinator.data or {}
        programs = slow_data.get("programs")
        if not isinstance(programs, list):
            return None

        target = filename.lower()
        matches = [
            p for p in programs
            if isinstance(p, dict) and str(p.get("name", "")).lower() == target
        ]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0].get("path")

        # Multiple matches — prefer one whose path shares a component
        # with the raw directory (e.g. "Programs" appearing in both).
        hint_parts = [
            part for part in directory_hint.replace("\\", "/").split("/") if part
        ]
        for p in matches:
            path = str(p.get("path", ""))
            if any(part and part in path for part in hint_parts):
                return path
        return matches[0].get("path")

    def _current_program_path(self) -> str | None:
        """Build a SimPL path acceptable to LoadProgram.

        Strategy (in order):
          1. If the enumerated programs list contains an entry with the
             same filename, use that path — it comes directly from the
             machine's own enumeration so aliasing is already resolved.
          2. Otherwise derive a path from the Program payload's
             ``directory`` field via ``_directory_to_simpl_root``.
          3. Last-resort fallback: ``machine:<name>``.
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
        enumerated = self._match_via_enumeration(filename, directory)
        if enumerated:
            return enumerated

        root = _directory_to_simpl_root(directory) if isinstance(directory, str) else None
        if root:
            if root.endswith(":") or root.endswith("\\") or root.endswith("/"):
                return f"{root}{filename}"
            sep = "\\" if "\\" in root else "/"
            return f"{root}{sep}{filename}"

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


class DatronDynamicDialogButton(CoordinatorEntity, ButtonEntity):
    """One slot in a dynamic pool that mirrors the machine's open dialog.

    The slot's displayed label AND its action track the actual button at
    ``index`` in the currently open dialog (``leftButtons`` then
    ``rightButtons``), so the buttons always match exactly what the machine is
    showing — with no per-dialog entity creation/removal. Slots past the
    dialog's button count report unavailable, as do all slots when no dialog is
    open.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(
        self,
        entry: ConfigEntry,
        client: DatronApiClient,
        coordinator: DataUpdateCoordinator,
        index: int,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # Stable fallback name → stable entity_id (…_dialog_button_N). The
        # ``name`` property below overrides the *displayed* label live.
        self._attr_name = f"Dialog Button {index + 1}"
        self._attr_device_info = _device_info(entry)

    def _open_dialog(self) -> dict[str, Any] | None:
        coord_data: dict[str, Any] = self.coordinator.data or {}
        dialog = coord_data.get("open_dialog")
        return dialog if isinstance(dialog, dict) else None

    @staticmethod
    def _dialog_buttons(dialog: dict[str, Any]) -> list[str]:
        left = dialog.get("leftButtons") or []
        right = dialog.get("rightButtons") or []
        return [b for b in (*left, *right) if isinstance(b, str)]

    def _label(self) -> str | None:
        dialog = self._open_dialog()
        if not dialog:
            return None
        buttons = self._dialog_buttons(dialog)
        if 0 <= self._index < len(buttons):
            return buttons[self._index]
        return None

    def _apply_label(self) -> None:
        """Point the displayed name at the live button label (or the fallback).

        We update ``_attr_name`` rather than override the ``name`` property so
        the entity_id is generated once from the stable "Dialog Button N" name
        at registration (the coordinator already holds data by then, so a
        property would risk baking a live label into the entity_id).
        """
        self._attr_name = self._label() or f"Dialog Button {self._index + 1}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # entity_id is registered now; safe to reflect the live label.
        self._apply_label()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._apply_label()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self._label() is not None

    async def async_press(self) -> None:
        dialog = self._open_dialog()
        dialog_id: str | None = dialog.get("id") if dialog else None
        label = self._label()
        if not dialog_id or not label:
            raise HomeAssistantError(
                f"No dialog button #{self._index + 1} to press"
            )
        _LOGGER.debug(
            "Pressing dialog button '%s' on '%s'",
            label,
            dialog.get("caption", "") if dialog else "",
        )
        try:
            await self._client.confirm_dialog(dialog_id, label)
        except DatronApiError as err:
            raise HomeAssistantError(f"Dialog button failed: {err}") from err


class DatronDialogLabelButton(CoordinatorEntity, ButtonEntity):
    """Click a dialog button by exact label match (case-insensitive).

    Only available when the currently open dialog exposes a button whose
    label matches ``match_label``. Useful for recurring recovery prompts
    like "Activate" where a one-click entity is clearer than chaining
    through the generic Confirm Dialog button.
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
        match_label: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._match_label = match_label
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    def _open_dialog(self) -> dict[str, Any] | None:
        coord_data: dict[str, Any] = self.coordinator.data or {}
        dialog = coord_data.get("open_dialog")
        return dialog if isinstance(dialog, dict) else None

    def _matching_button(self, dialog: dict[str, Any]) -> str | None:
        target = self._match_label.strip().lower()
        for key in ("leftButtons", "rightButtons"):
            for label in dialog.get(key) or []:
                if isinstance(label, str) and label.strip().lower() == target:
                    return label
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        dialog = self._open_dialog()
        if not dialog:
            return False
        return self._matching_button(dialog) is not None

    async def async_press(self) -> None:
        dialog = self._open_dialog()
        if not dialog:
            raise HomeAssistantError(
                f"No open dialog — '{self._match_label}' button not available"
            )
        dialog_id: str | None = dialog.get("id")
        if not dialog_id:
            raise HomeAssistantError("Open dialog has no ID field")
        button_label = self._matching_button(dialog)
        if not button_label:
            raise HomeAssistantError(
                f"Open dialog has no '{self._match_label}' button "
                f"(available: {dialog.get('leftButtons') or []} / "
                f"{dialog.get('rightButtons') or []})"
            )
        _LOGGER.debug(
            "Clicking '%s' on dialog '%s'",
            button_label,
            dialog.get("caption", ""),
        )
        try:
            await self._client.confirm_dialog(dialog_id, button_label)
        except DatronApiError as err:
            raise HomeAssistantError(
                f"{self._attr_name} failed: {err}"
            ) from err
