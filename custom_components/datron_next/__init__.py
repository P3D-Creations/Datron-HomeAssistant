"""The Datron NEXT integration."""

from __future__ import annotations

import logging
import os

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import DatronApiClient, DatronApiError, DatronAuthError
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_EXTRA_SIMPL_ROOTS,
    CONF_HAS_ROTARY_AXES,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    CONNECTION_LIVE,
    CONNECTION_NEXT,
    COORD_AXIS,
    COORD_FAST,
    COORD_MEDIUM,
    COORD_SLOW,
    DEFAULT_HAS_ROTARY_AXES,
    DEFAULT_LIVE_PORT,
    DEFAULT_PORT,
    DOMAIN,
)
from .live_api import DatronLiveClient
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

# ── Bundled Lovelace card ─────────────────────────────────────────────────────
# The integration serves the cockpit card at a stable URL so users only add a
# single Lovelace resource (module) instead of copying files into config/www.
CARD_URL = "/datron_next/datron-cockpit-card.js"
CARD_PATH = os.path.join(os.path.dirname(__file__), "www", "datron-cockpit-card.js")
_CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Serve the bundled cockpit card and auto-load it into the frontend.

    Registering a static path only *serves* the file — the frontend still has to
    *load* the module for the custom element to be defined and to appear in the
    card picker. ``add_extra_js_url`` injects it on every dashboard, so the card
    works with no manual resource setup. A version query busts the browser cache
    on integration updates. Runs once per HA start.
    """
    if hass.data.get(_CARD_REGISTERED_KEY):
        return
    if not os.path.isfile(CARD_PATH):
        _LOGGER.debug("Cockpit card file not found at %s; skipping", CARD_PATH)
        return
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, CARD_PATH, False)]
        )
    except Exception as err:  # noqa: BLE001 — never block setup on the card
        _LOGGER.debug("Could not register cockpit card static path: %s", err)
        return

    # Cache-bust by integration version so updates load fresh.
    version = ""
    try:
        from homeassistant.loader import async_get_integration

        integration = await async_get_integration(hass, DOMAIN)
        version = str(integration.version or "")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not resolve integration version: %s", err)
    url = f"{CARD_URL}?v={version}" if version else CARD_URL

    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)
    except Exception as err:  # noqa: BLE001 — card is optional, never block setup
        _LOGGER.debug("Could not auto-load cockpit card JS (%s); a manual "
                      "Lovelace resource for %s still works", err, CARD_URL)

    hass.data[_CARD_REGISTERED_KEY] = True
    _LOGGER.debug("Cockpit card served and auto-loaded from %s", url)

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
SVC_DIAGNOSTICS = "diagnostics"
SVC_GET_TOOLS = "get_tools"

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
_GET_TOOLS_SCHEMA = vol.Schema(
    {
        vol.Required("storage"): vol.In(
            ["magazine", "warehouse", "program", "spindle"]
        ),
        vol.Optional("device_id"): cv.string,
    }
)

type DatronConfigEntry = ConfigEntry


def _entry_data(hass: HomeAssistant) -> dict[str, Any]:
    """Return the hass.data dict of the first loaded config entry."""
    entries = hass.data.get(DOMAIN, {})
    # Only config-entry values are dicts with a "client"; skip bookkeeping keys.
    for data in entries.values():
        if isinstance(data, dict) and "client" in data:
            return data
    raise ValueError("No Datron NEXT entry loaded")


def _get_client(hass: HomeAssistant) -> DatronApiClient:
    """Return the API client for the first loaded config entry."""
    return _entry_data(hass)["client"]


def _client_for_device(hass: HomeAssistant, device_id: str | None) -> DatronApiClient:
    """Return the client for *device_id*'s entry, or the first entry's client.

    Lets a service target a specific machine when several Datron entries exist;
    falls back to the first entry (single-machine setups need not pass one).
    """
    if device_id:
        from homeassistant.helpers import device_registry as dr

        device = dr.async_get(hass).async_get(device_id)
        if device:
            for entry_id in device.config_entries:
                data = hass.data.get(DOMAIN, {}).get(entry_id)
                if isinstance(data, dict) and "client" in data:
                    return data["client"]
    return _get_client(hass)


def _get_fast_coordinator(hass: HomeAssistant) -> DatronFastCoordinator:
    """Return the fast coordinator for the first loaded config entry."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("No Datron NEXT entry loaded")
    first_entry_data = next(iter(entries.values()))
    return first_entry_data[COORD_FAST]


async def async_setup_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Set up Datron NEXT / Datron Live from a config entry."""
    # Entries created before the Live feature have no connection_type key, so
    # default to NEXT — those entries keep behaving exactly as before.
    connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_NEXT)
    host = entry.data[CONF_HOST]

    session = async_get_clientsession(hass)

    extra_roots: list[str] = list(entry.options.get(CONF_EXTRA_SIMPL_ROOTS) or [])

    if connection_type == CONNECTION_LIVE:
        port = entry.data.get(CONF_PORT, DEFAULT_LIVE_PORT)
        client = DatronLiveClient(
            host=host,
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            port=port,
            session=session,
        )
        # Capture the JWT token before the first coordinator refresh so the
        # first poll cycle is already authenticated. Map failures to the HA
        # setup-retry exceptions so a powered-off machine or wrong password is
        # retried / surfaced for reauth instead of permanently failing the entry.
        try:
            await client.login()
        except DatronAuthError as err:
            _LOGGER.warning("Datron Live login rejected credentials: %s", err)
            raise ConfigEntryAuthFailed(str(err)) from err
        except DatronApiError as err:
            _LOGGER.warning(
                "Datron Live login failed during setup (will retry): %s", err
            )
            raise ConfigEntryNotReady(str(err)) from err
        # Live has no rotary-axis data source.
        has_rotary_axes = False
    else:
        port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        token = entry.data[CONF_TOKEN]
        client = DatronApiClient(host=host, token=token, port=port, session=session)
        has_rotary_axes = bool(
            entry.options.get(CONF_HAS_ROTARY_AXES, DEFAULT_HAS_ROTARY_AXES)
        )

    # Create coordinators.  All four are created for both connection types so
    # platform code stays unchanged.  On Live the axis/feed/runtime/etc. client
    # methods raise, so those coordinators simply yield empty/None values (the
    # axis coordinator never raises UpdateFailed by design).
    fast_coordinator = DatronFastCoordinator(hass, client)
    axis_coordinator = DatronAxisCoordinator(hass, client)
    medium_coordinator = DatronMediumCoordinator(hass, client)
    slow_coordinator = DatronSlowCoordinator(hass, client, extra_roots=extra_roots)

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
        "has_rotary_axes": has_rotary_axes,
        CONF_CONNECTION_TYPE: connection_type,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Serve the bundled cockpit Lovelace card (best-effort, never blocks setup).
    await _async_register_frontend_card(hass)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # ── Register services (only once, on first entry setup) ──────────────────
    if not hass.services.has_service(DOMAIN, SVC_EXECUTE_PROGRAM):
        _register_services(hass)

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: DatronConfigEntry
) -> None:
    """Reload the entry when options change so new values take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


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

    async def handle_diagnostics(call: ServiceCall) -> dict:
        """Return user claims + machine licenses. Use to debug 403 errors.

        Call with ``response_variable`` in a script / dev-tools to inspect:
          - ``user_claims.apiAutomation`` must be True for POST commands.
          - ``licenses.apiAutomation`` must be True for the machine to
            accept Automation API calls at all.
        """
        client = _get_client(hass)
        out: dict[str, Any] = {}
        try:
            out["user_claims"] = await client.get_user_info()
        except DatronApiError as err:
            out["user_claims_error"] = str(err)
        try:
            out["licenses"] = await client.get_licenses()
        except DatronApiError as err:
            out["licenses_error"] = str(err)
        return out

    hass.services.async_register(
        DOMAIN,
        SVC_DIAGNOSTICS,
        handle_diagnostics,
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_get_tools(call: ServiceCall) -> dict:
        """Return the tool list for a storage location (for the card's browser).

        storage: magazine | warehouse | program | spindle. Read-only; returns
        ``{storage, count, tools: [...]}``. device_id (optional) targets a
        specific machine when several are configured.
        """
        client = _client_for_device(hass, call.data.get("device_id"))
        storage: str = call.data["storage"]
        try:
            if storage == "magazine":
                tools = await client.get_tools_in_changer()
            elif storage == "warehouse":
                tools = await client.get_tools_in_warehouse()
            elif storage == "program":
                tools = await client.get_tools_in_program()
            else:  # spindle
                spindle = await client.get_tool_in_spindle()
                tools = [spindle] if isinstance(spindle, dict) else []
        except DatronApiError as err:
            _LOGGER.error("get_tools(%s) error: %s", storage, err)
            raise
        tool_list = tools if isinstance(tools, list) else []
        return {"storage": storage, "count": len(tool_list), "tools": tool_list}

    hass.services.async_register(
        DOMAIN,
        SVC_GET_TOOLS,
        handle_get_tools,
        schema=_GET_TOOLS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
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
                SVC_DIAGNOSTICS,
                SVC_GET_TOOLS,
            ):
                hass.services.async_remove(DOMAIN, svc)

    return unload_ok
