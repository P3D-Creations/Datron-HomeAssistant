"""The Datron NEXT integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DatronApiClient, DatronApiError
from .const import CONF_TOKEN, COORD_AXIS, COORD_FAST, COORD_MEDIUM, COORD_SLOW, DEFAULT_PORT, DOMAIN
from .coordinator import (
    DatronAxisCoordinator,
    DatronFastCoordinator,
    DatronMediumCoordinator,
    DatronSlowCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.CAMERA,
    Platform.SELECT,
]

# ── Service names ─────────────────────────────────────────────────────────────
SVC_EXECUTE_PROGRAM = "execute_program_async"
SVC_LOAD_PROGRAM = "load_program"
SVC_ENUMERATE_FOLDER = "enumerate_folder_contents"
SVC_PROGRAM_FILE_INFO = "get_program_file_info"
SVC_CONFIRM_DIALOG = "confirm_dialog"
SVC_ACTIVATE_WORKPIECE = "activate_workpiece"
SVC_EXECUTE_REMOTE_LINK = "execute_remote_link"
SVC_SET_VARIABLE = "set_variable"
SVC_GET_VARIABLE = "get_variable"

# ── Service schemas ───────────────────────────────────────────────────────────
_PATH_SCHEMA = vol.Schema({vol.Required("path"): cv.string})
_CONFIRM_DIALOG_SCHEMA = vol.Schema(
    {
        vol.Required("button"): cv.string,
        vol.Optional("dialog_id"): cv.string,
    }
)
_WORKPIECE_SCHEMA = vol.Schema({vol.Required("name"): cv.string})
_REMOTE_LINK_SCHEMA = vol.Schema({vol.Required("name"): cv.string})
_VARIABLE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("type"): vol.In(["bool", "number", "string"]),
        vol.Required("value"): vol.Any(bool, int, float, str),
    }
)
_VARIABLE_GET_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("type"): vol.In(["bool", "number", "string"]),
    }
)

type DatronConfigEntry = ConfigEntry


def _get_client(hass: HomeAssistant) -> DatronApiClient:
    """Return the API client for the first loaded config entry."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("No Datron NEXT entry loaded")
    first_entry_data = next(iter(entries.values()))
    return first_entry_data["client"]


def _get_fast_coordinator(hass: HomeAssistant) -> DatronFastCoordinator:
    """Return the fast coordinator for the first loaded config entry."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("No Datron NEXT entry loaded")
    first_entry_data = next(iter(entries.values()))
    return first_entry_data[COORD_FAST]


async def async_setup_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Set up Datron NEXT from a config entry."""
    host = entry.data[CONF_HOST]
    token = entry.data[CONF_TOKEN]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    session = async_get_clientsession(hass)
    client = DatronApiClient(host=host, token=token, port=port, session=session)

    # Create coordinators
    fast_coordinator = DatronFastCoordinator(hass, client)
    axis_coordinator = DatronAxisCoordinator(hass, client)
    medium_coordinator = DatronMediumCoordinator(hass, client)
    slow_coordinator = DatronSlowCoordinator(hass, client)

    # Fetch initial data
    await fast_coordinator.async_config_entry_first_refresh()
    await axis_coordinator.async_config_entry_first_refresh()
    await medium_coordinator.async_config_entry_first_refresh()
    await slow_coordinator.async_config_entry_first_refresh()

    # Store coordinators and client in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        COORD_FAST: fast_coordinator,
        COORD_AXIS: axis_coordinator,
        COORD_MEDIUM: medium_coordinator,
        COORD_SLOW: slow_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Register services (only once, on first entry setup) ──────────────────
    if not hass.services.has_service(DOMAIN, SVC_EXECUTE_PROGRAM):
        _register_services(hass)

    return True


def _register_services(hass: HomeAssistant) -> None:
    """Register all Datron NEXT services."""

    async def handle_execute_program_async(call: ServiceCall) -> None:
        """Execute a program asynchronously on the machine.

        path: SimPL path string, e.g. ``machine:MyProgram.simpl``
        """
        client = _get_client(hass)
        path: str = call.data["path"]
        try:
            result = await client.execute_program_async(path)
            code = (result or {}).get("resultCode", "Unknown")
            if code != "Success":
                _LOGGER.warning("execute_program_async('%s') → %s", path, code)
            else:
                _LOGGER.info("execute_program_async('%s') → %s", path, code)
        except DatronApiError as err:
            _LOGGER.error("execute_program_async error: %s", err)
            raise

    async def handle_load_program(call: ServiceCall) -> None:
        """Load (but do not execute) a program on the machine.

        path: SimPL path string, e.g. ``machine:MyProgram.simpl``
        """
        client = _get_client(hass)
        path: str = call.data["path"]
        try:
            result = await client.load_program(path)
            code = (result or {}).get("resultCode", "Unknown")
            if code != "Success":
                _LOGGER.warning("load_program('%s') → %s", path, code)
            else:
                _LOGGER.info("load_program('%s') → %s", path, code)
        except DatronApiError as err:
            _LOGGER.error("load_program error: %s", err)
            raise

    async def handle_enumerate_folder_contents(call: ServiceCall) -> dict:
        """Return the files and subfolders at a given machine path.

        path: SimPL path, e.g. ``machine:`` (root) or ``machine:programs``
        Returns: {files: [...], subfolders: [...]}
        """
        client = _get_client(hass)
        path: str = call.data["path"]
        try:
            result = await client.enumerate_folder_contents(path)
            return {
                "files": (result or {}).get("files") or [],
                "subfolders": (result or {}).get("subfolders") or [],
            }
        except DatronApiError as err:
            _LOGGER.error("enumerate_folder_contents error: %s", err)
            raise

    async def handle_get_program_file_info(call: ServiceCall) -> dict:
        """Return metadata about a program file.

        path: SimPL path to the program, e.g. ``machine:MyProgram.simpl``
        Returns: {last_changed, expected_duration_seconds,
                  has_valid_tool_check, checksum_hex, checksum_base64}
        """
        client = _get_client(hass)
        path: str = call.data["path"]
        try:
            result = await client.get_program_file_info(path)
            info = result or {}
            # Convert duration (ISO 8601 timespan) to seconds if present
            duration = info.get("expectedExecutionDuration")
            return {
                "last_changed": info.get("latestChangeTime"),
                "expected_duration": duration,
                "has_valid_tool_check": info.get("hasValidToolCheckAnalysis"),
                "checksum_hex": info.get("md5ChecksumAsHex"),
                "checksum_base64": info.get("md5ChecksumAsBase64"),
            }
        except DatronApiError as err:
            _LOGGER.error("get_program_file_info error: %s", err)
            raise

    async def handle_confirm_dialog(call: ServiceCall) -> None:
        """Confirm the currently open machine dialog with a specific button.

        button: Exact button label to press (obtain from the open_dialog sensor attributes).
        dialog_id (optional): UUID of the dialog. If omitted, the current open dialog is used.
        """
        client = _get_client(hass)
        button: str = call.data["button"]
        dialog_id: str | None = call.data.get("dialog_id")

        if not dialog_id:
            # Look up the current dialog from the fast coordinator
            try:
                coordinator = _get_fast_coordinator(hass)
                coord_data = coordinator.data or {}
                dialog = coord_data.get("open_dialog")
                if isinstance(dialog, dict):
                    dialog_id = dialog.get("id")
            except ValueError:
                pass

        if not dialog_id:
            _LOGGER.error("confirm_dialog: no open dialog found and no dialog_id provided")
            return

        try:
            await client.confirm_dialog(dialog_id, button)
        except DatronApiError as err:
            _LOGGER.error("confirm_dialog error: %s", err)
            raise

    hass.services.async_register(
        DOMAIN, SVC_EXECUTE_PROGRAM, handle_execute_program_async, schema=_PATH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SVC_LOAD_PROGRAM, handle_load_program, schema=_PATH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SVC_ENUMERATE_FOLDER,
        handle_enumerate_folder_contents,
        schema=_PATH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SVC_PROGRAM_FILE_INFO,
        handle_get_program_file_info,
        schema=_PATH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SVC_CONFIRM_DIALOG, handle_confirm_dialog, schema=_CONFIRM_DIALOG_SCHEMA
    )

    async def handle_activate_workpiece(call: ServiceCall) -> None:
        client = _get_client(hass)
        name: str = call.data["name"]
        try:
            await client.activate_workpiece(name)
        except DatronApiError as err:
            _LOGGER.error("activate_workpiece error: %s", err)
            raise

    async def handle_execute_remote_link(call: ServiceCall) -> None:
        client = _get_client(hass)
        name: str = call.data["name"]
        try:
            await client.execute_remote_link(name)
        except DatronApiError as err:
            _LOGGER.error("execute_remote_link error: %s", err)
            raise

    async def handle_set_variable(call: ServiceCall) -> None:
        client = _get_client(hass)
        name: str = call.data["name"]
        var_type: str = call.data["type"]
        value = call.data["value"]
        try:
            if var_type == "bool":
                await client.set_bool_variable(name, bool(value))
            elif var_type == "number":
                await client.set_number_variable(name, float(value))
            else:
                await client.set_string_variable(name, str(value))
        except DatronApiError as err:
            _LOGGER.error("set_variable error: %s", err)
            raise

    async def handle_get_variable(call: ServiceCall) -> dict:
        client = _get_client(hass)
        name: str = call.data["name"]
        var_type: str = call.data["type"]
        try:
            if var_type == "bool":
                result = await client.get_bool_variable(name)
            elif var_type == "number":
                result = await client.get_number_variable(name)
            else:
                result = await client.get_string_variable(name)
            return {"name": name, "type": var_type, "value": (result or {}).get("value")}
        except DatronApiError as err:
            _LOGGER.error("get_variable error: %s", err)
            raise

    hass.services.async_register(
        DOMAIN, SVC_ACTIVATE_WORKPIECE, handle_activate_workpiece, schema=_WORKPIECE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SVC_EXECUTE_REMOTE_LINK, handle_execute_remote_link,
        schema=_REMOTE_LINK_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SVC_SET_VARIABLE, handle_set_variable, schema=_VARIABLE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SVC_GET_VARIABLE,
        handle_get_variable,
        schema=_VARIABLE_GET_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_unload_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            # Remove services when the last entry is unloaded
            for svc in (
                SVC_EXECUTE_PROGRAM,
                SVC_LOAD_PROGRAM,
                SVC_ENUMERATE_FOLDER,
                SVC_PROGRAM_FILE_INFO,
                SVC_CONFIRM_DIALOG,
                SVC_ACTIVATE_WORKPIECE,
                SVC_EXECUTE_REMOTE_LINK,
                SVC_SET_VARIABLE,
                SVC_GET_VARIABLE,
            ):
                hass.services.async_remove(DOMAIN, svc)

    return unload_ok
