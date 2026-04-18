"""API client for the Datron NEXT REST API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_VERSION

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
AXIS_TIMEOUT = aiohttp.ClientTimeout(total=30)
COMMAND_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Datron's embedded HTTP server can only handle a small number of
# concurrent connections.  Background polling is serialised through one
# semaphore; user-initiated commands get their own independent lane so
# they are never queued behind an in-flight poll cycle.
MAX_CONCURRENT_REQUESTS = 1
MAX_CONCURRENT_COMMANDS = 1


class DatronApiError(Exception):
    """Exception for Datron API errors."""


class DatronAuthError(DatronApiError):
    """Exception for authentication errors (401)."""


class DatronLicenseError(DatronApiError):
    """403 on an endpoint that requires a higher API license tier."""


class DatronStateError(DatronApiError):
    """403 on a command that is invalid in the current machine state.

    Datron returns 403 both for genuine license-tier problems *and* for
    commands that are illegal in the current state (e.g. Resume when the
    machine is not paused, ConfirmDialog when no dialog is open).
    Use this to disambiguate at the call site when context allows.
    """


class DatronApiClient:
    """Client to interact with the Datron NEXT REST API."""

    def __init__(
        self,
        host: str,
        token: str,
        port: int = 80,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client."""
        self._host = host
        self._port = port
        self._token = token
        self._session = session
        self._base_url = f"http://{host}:{port}/api/v{API_VERSION}"
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        # Separate semaphore so commands never queue behind polling requests
        self._cmd_semaphore = asyncio.Semaphore(MAX_CONCURRENT_COMMANDS)

    def set_session(self, session: aiohttp.ClientSession) -> None:
        """Set the aiohttp session."""
        self._session = session

    @property
    def _headers(self) -> dict[str, str]:
        """Return auth headers."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json; v=2.0",
        }

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        """Make an API request (serialised through semaphore)."""
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")

        url = f"{self._base_url}{path}"
        _LOGGER.debug("[API] Waiting for semaphore: %s %s", method, url)
        async with self._semaphore:
            _LOGGER.debug("[API] Acquired semaphore: %s %s", method, url)
            import time
            start = time.monotonic()
            try:
                _LOGGER.debug("API request: %s %s (START)", method, url)
                async with self._session.request(
                    method, url, headers=self._headers, timeout=REQUEST_TIMEOUT, **kwargs
                ) as resp:
                    elapsed = time.monotonic() - start
                    _LOGGER.debug("API request: %s %s (RESPONSE in %.3fs)", method, url, elapsed)
                    if resp.status == 401:
                        raise DatronAuthError("Authentication failed — invalid or expired token")
                    if resp.status == 403:
                        body = (await resp.text()).strip()
                        raise DatronLicenseError(
                            f"Forbidden for {path}: "
                            f"{body or 'insufficient API license tier'}"
                        )
                    if resp.status >= 400:
                        text = await resp.text()
                        raise DatronApiError(
                            f"API error {resp.status} for {path}: {text}"
                        )
                    # Some endpoints may return empty body
                    if resp.content_length == 0:
                        return None
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" in content_type or "text/plain" in content_type:
                        return await resp.json(content_type=None)
                    return await resp.read()
            except aiohttp.ClientError as err:
                elapsed = time.monotonic() - start
                _LOGGER.error("[API] ClientError after %.3fs for %s %s: %s", elapsed, method, url, err)
                raise DatronApiError(f"Connection error for {path}: {err}") from err
            except TimeoutError as err:
                elapsed = time.monotonic() - start
                _LOGGER.error("[API] Timeout after %.3fs for %s %s", elapsed, method, url)
                raise DatronApiError(f"Timeout requesting {path}") from err
            finally:
                elapsed = time.monotonic() - start
                _LOGGER.debug("[API] Released semaphore: %s %s (total %.3fs)", method, url, elapsed)

    async def _command_request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        """Fire a user-initiated command through the dedicated command lane.

        Uses ``_cmd_semaphore`` (independent of ``_semaphore``) so the
        request is never held back by in-flight polling calls.
        """
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")

        url = f"{self._base_url}{path}"
        async with self._cmd_semaphore:
            import time
            start = time.monotonic()
            try:
                async with self._session.request(
                    method, url, headers=self._headers,
                    timeout=COMMAND_TIMEOUT, **kwargs
                ) as resp:
                    if resp.status == 401:
                        raise DatronAuthError(
                            "Authentication failed — invalid or expired token"
                        )
                    if resp.status == 403:
                        body = (await resp.text()).strip()
                        # 403 on a command most commonly means the action
                        # is illegal in the current machine state (Resume
                        # while not paused, etc.). License-tier 403s from
                        # the machine typically include a body message.
                        detail = body or (
                            "action not allowed in current machine state "
                            "(or Automation API license required)"
                        )
                        raise DatronStateError(
                            f"Command {path} rejected (403): {detail}"
                        )
                    if resp.status >= 400:
                        text = await resp.text()
                        raise DatronApiError(
                            f"API error {resp.status} for {path}: {text}"
                        )
                    if resp.content_length == 0:
                        return None
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" in content_type or "text/plain" in content_type:
                        return await resp.json(content_type=None)
                    return await resp.read()
            except aiohttp.ClientError as err:
                elapsed = time.monotonic() - start
                _LOGGER.error(
                    "[CMD] ClientError after %.3fs for %s %s: %s",
                    elapsed, method, url, err,
                )
                raise DatronApiError(f"Connection error for {path}: {err}") from err
            except TimeoutError as err:
                raise DatronApiError(f"Timeout requesting {path}") from err

    async def _command_post(self, path: str, **kwargs: Any) -> Any:
        """POST via the command lane (bypasses polling queue)."""
        return await self._command_request("POST", path, **kwargs)

    async def _get(self, path: str, **kwargs: Any) -> Any:
        """HTTP GET request (polling lane)."""
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> Any:
        """HTTP POST request (polling lane)."""
        return await self._request("POST", path, **kwargs)

    # ── Machine ──────────────────────────────────────────────

    async def get_machine_status(self) -> dict[str, Any]:
        """Get machine execution state."""
        return await self._get("/Machine/MachineStatus")

    async def get_machine_number(self) -> dict[str, Any]:
        """Get the unique machine number."""
        return await self._get("/Machine/MachineNumber")

    async def get_machine_type(self) -> dict[str, Any]:
        """Get the machine type."""
        return await self._get("/Machine/MachineType")

    async def get_licenses(self) -> dict[str, Any]:
        """Get activated license options."""
        return await self._get("/Machine/Licenses")

    async def get_software_version(self) -> dict[str, Any]:
        """Get NEXT software version."""
        return await self._get("/Machine/NextSoftwareVersion")

    async def ping(self) -> bool:
        """Test connectivity to the machine."""
        try:
            await self._get("/Machine/Ping")
            return True
        except DatronApiError:
            return False

    # ── Machine Components (sensors) ─────────────────────────

    async def get_axis_positions(self) -> dict[str, Any]:
        """Get current axis positions (X, Y, Z, A, B, C) in RCS."""
        return await self._get("/MachineComponents/AxisPositions")

    async def get_axis_positions_direct(self) -> dict[str, Any]:
        """Get axis positions bypassing the polling semaphore.

        The AxisPositions endpoint on some Datron machines is
        significantly slower than all other endpoints (often > 15 s).
        This method uses a dedicated HTTP call with a longer timeout
        and does NOT go through ``_semaphore``, so it cannot block
        the fast-poll cycle.
        """
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")
        url = f"{self._base_url}/MachineComponents/AxisPositions"
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=AXIS_TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise DatronAuthError(
                        "Authentication failed — invalid or expired token"
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise DatronApiError(
                        f"API error {resp.status} for AxisPositions: {text}"
                    )
                if resp.content_length == 0:
                    return {}
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DatronApiError(
                f"Connection error for AxisPositions: {err}"
            ) from err
        except TimeoutError as err:
            raise DatronApiError("Timeout requesting AxisPositions (30s)") from err

    async def get_compressed_air(self) -> dict[str, Any]:
        """Get compressed air sensor data."""
        return await self._get("/MachineComponents/CompressedAir")

    async def get_vacuum(self) -> dict[str, Any]:
        """Get vacuum sensor data."""
        return await self._get("/MachineComponents/Vacuum")

    async def get_spray_system(self) -> dict[str, Any]:
        """Get spray system (EKD/Microjet) status."""
        return await self._get("/MachineComponents/SpraySystem")

    async def get_feed_override(self) -> dict[str, Any]:
        """Get feed override dial positions."""
        return await self._get("/MachineComponents/FeedOverride")

    async def get_status_light(self) -> dict[str, Any]:
        """Get RGB status light values."""
        return await self._get("/MachineComponents/StatusLight")

    async def get_runtime(self) -> dict[str, Any]:
        """Get spindle and machine runtime hours."""
        return await self._get("/MachineComponents/Runtime")

    # ── Runtime (job / program execution) ────────────────────

    async def get_current_program(self) -> dict[str, Any]:
        """Get currently loaded program info."""
        return await self._get("/Runtime/CurrentlyLoadedProgram")

    async def get_execution_durations(self) -> dict[str, Any]:
        """Get execution timing (elapsed, remaining, progress)."""
        return await self._get("/Runtime/ExecutionDurations")

    async def get_notifications(self) -> list[dict[str, Any]]:
        """Get last 100 notifications."""
        return await self._get("/Runtime/Notifications")

    async def get_preview_image_url(self) -> dict[str, Any]:
        """Get URL for preview image of loaded program."""
        return await self._get("/Runtime/PreviewImage")

    # ── Tools ────────────────────────────────────────────────

    async def get_tool_in_spindle(self) -> dict[str, Any]:
        """Get the tool currently in the spindle."""
        return await self._get("/Tool/ToolInSpindle")

    async def get_tools_in_changer(self) -> list[dict[str, Any]]:
        """Get tools in the embedded tool changer."""
        return await self._get("/Tool/ToolsInEmbeddedToolChanger")

    async def get_tools_in_warehouse(self) -> list[dict[str, Any]]:
        """Get tools in the warehouse."""
        return await self._get("/Tool/ToolsInWarehouse")

    async def get_tools_in_program(self) -> list[dict[str, Any]]:
        """Get tools needed for the currently loaded program."""
        return await self._get("/Tool/ToolsInProgram")

    # ── Workpiece ────────────────────────────────────────────

    async def get_workpieces(self) -> list[dict[str, Any]]:
        """Get all saved workpiece setups."""
        return await self._get("/Workpiece/GetWorkpieces")

    async def get_workpiece_image(self) -> bytes | None:
        """Get workpiece image as bytes."""
        return await self._get("/Workpiece/WorkpieceImage")

    # ── Camera ───────────────────────────────────────────────

    async def get_camera_image_url(self, stream_id: int = 0) -> dict[str, Any]:
        """Get camera image URL for a given stream."""
        return await self._get(
            "/Camera/CreateCameraImageUrl", params={"streamId": stream_id}
        )

    # ── Image (public endpoints) ─────────────────────────────

    async def fetch_image_url(self, url: str) -> bytes | None:
        """Fetch image bytes from a public URL (with token in query string).

        Handles both relative and absolute URLs. Does not send bearer auth –
        the token embedded in the URL is the authentication mechanism.
        """
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")

        # Handle relative URLs
        if not url.startswith("http"):
            url = f"http://{self._host}:{self._port}{url}"

        _LOGGER.debug("Fetching image from URL: %s", url)
        async with self._semaphore:
            try:
                async with self._session.get(
                    url, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status == 204:
                        return None
                    if resp.status >= 400:
                        text = await resp.text()
                        raise DatronApiError(
                            f"Image fetch error {resp.status}: {text}"
                        )
                    data = await resp.read()
                    return data if data else None
            except aiohttp.ClientError as err:
                raise DatronApiError(
                    f"Image connection error: {err}"
                ) from err
            except TimeoutError as err:
                raise DatronApiError("Timeout fetching image") from err

    async def get_camera_image(self, token: str) -> bytes | None:
        """Get camera image bytes (token-based, public endpoint)."""
        return await self._get("/Image/Camera", params={"token": token})

    async def get_machine_image(self) -> bytes | None:
        """Get machine image."""
        return await self._get("/Image/Machine")

    async def get_program_preview_image(self) -> bytes | None:
        """Get simulated preview image of current program."""
        return await self._get("/Image/ProgramPreviewImage")

    async def get_tool_image(
        self,
        token: str | None = None,
        width: int = 400,
        height: int = 400,
        up_right: bool = True,
    ) -> bytes | None:
        """Get tool image from the public Image/Tool endpoint.

        If *token* is provided it is passed as the query-string token
        (preferred – no bearer auth needed).  Otherwise bearer auth is used.
        """
        params: dict[str, Any] = {
            "widthInPixel": width,
            "heightInPixel": height,
            "upRight": str(up_right).lower(),
            "withSpindle": "true",
        }
        if token:
            params["token"] = token
        return await self._get("/Image/Tool", params=params)

    # ── Dialog ───────────────────────────────────────────────

    async def get_open_dialog(self) -> dict[str, Any] | None:
        """Get the currently open dialog.

        Returns None (204) when no dialog is open.
        Response schema: {id, caption, text, details, severity,
                          leftButtons: [], rightButtons: []}
        """
        return await self._get("/Dialog/OpenDialog")

    async def confirm_dialog(self, dialog_id: str, button: str) -> None:
        """Confirm an open dialog by clicking the specified button label.

        Args:
            dialog_id: UUID from the Dialog response.
            button: Exact label of the button to click (from leftButtons/rightButtons).
        """
        await self._command_post(
            "/Dialog/ConfirmDialog",
            json={"id": dialog_id, "button": button},
        )

    # ── Execution control (Automation API) ───────────────────

    async def pause_execution(self) -> dict[str, Any]:
        """Pause the current program execution."""
        return await self._command_post("/Execution/Pause")

    async def resume_execution(self) -> dict[str, Any]:
        """Resume a paused program execution."""
        return await self._command_post("/Execution/Resume")

    async def abort_execution(self) -> dict[str, Any]:
        """Abort the currently running program."""
        return await self._command_post("/Execution/Abort")

    async def move_to_park_position(self) -> dict[str, Any]:
        """Move the spindle to the park position."""
        return await self._command_post("/Execution/MoveToParkPosition")

    async def load_program(self, path: str) -> dict[str, Any]:
        """Load a program without executing it.

        Path format: ``machine:program.simpl`` or
        ``device:DEVICENAME\\\\program.simpl``.
        Returns ExecutionResult {resultCode: str}.
        """
        return await self._command_post("/Execution/LoadProgram", json={"path": path})

    async def execute_program_async(self, path: str) -> dict[str, Any]:
        """Execute a program asynchronously.

        Returns immediately after the program is loaded; execution continues
        in the background. Returns ExecutionResult {resultCode: str}.
        """
        return await self._command_post(
            "/Execution/ExecuteProgramAsync", json={"path": path}
        )

    async def execute_loaded_program(self) -> dict[str, Any]:
        """Run the program that is already loaded (the "Start" action)."""
        return await self._command_post("/Execution/ExecuteLoadedProgram")

    async def reference_machine(self) -> bool:
        """Home / reference the machine axes. Returns True if referencing started."""
        result = await self._command_post("/Machine/Reference")
        # The Reference endpoint returns a bare bool per the API spec.
        if isinstance(result, bool):
            return result
        return bool(result)

    async def activate_workpiece(self, workpiece_name: str) -> bool:
        """Activate (select) a saved workpiece setup by name."""
        result = await self._command_post(
            "/Workpiece/Activate", params={"workpieceName": workpiece_name}
        )
        return bool(result) if result is not None else True

    async def get_remote_link_programs(self) -> dict[str, Any]:
        """Get the list of RemoteLink programs."""
        return await self._get("/RemoteLink/RemoteLinkPrograms")

    async def execute_remote_link(self, name: str) -> dict[str, Any]:
        """Execute a RemoteLink program by name."""
        return await self._command_post("/RemoteLink/Execute", json={"name": name})

    # ── SimPL variables ──────────────────────────────────────

    async def get_bool_variable(self, name: str) -> dict[str, Any]:
        """Read a SimPL boolean variable by name."""
        return await self._get("/Variable/BooleanVariable", params={"name": name})

    async def set_bool_variable(self, name: str, value: bool) -> Any:
        """Create / overwrite a SimPL boolean variable."""
        return await self._command_post(
            "/Variable/BooleanVariable", json={"name": name, "value": bool(value)}
        )

    async def get_number_variable(self, name: str) -> dict[str, Any]:
        """Read a SimPL numeric variable by name."""
        return await self._get("/Variable/NumberVariable", params={"name": name})

    async def set_number_variable(self, name: str, value: float) -> Any:
        """Create / overwrite a SimPL numeric variable."""
        return await self._command_post(
            "/Variable/NumberVariable", json={"name": name, "value": float(value)}
        )

    async def get_string_variable(self, name: str) -> dict[str, Any]:
        """Read a SimPL string variable by name."""
        return await self._get("/Variable/StringVariable", params={"name": name})

    async def set_string_variable(self, name: str, value: str) -> Any:
        """Create / overwrite a SimPL string variable."""
        return await self._command_post(
            "/Variable/StringVariable", json={"name": name, "value": str(value)}
        )

    async def get_program_file_info(self, path: str) -> dict[str, Any]:
        """Return metadata for a program file.

        Returns ProgramFileInfo:
          {latestChangeTime, expectedExecutionDuration,
           hasValidToolCheckAnalysis, md5ChecksumAsHex, md5ChecksumAsBase64}
        """
        return await self._get("/Execution/ProgramFileInfo", params={"path": path})

    # ── File system ──────────────────────────────────────────

    async def enumerate_folder_contents(self, path: str) -> dict[str, Any]:
        """List files and subfolders at a SimPL-format path.

        Path syntax: ``machine:folder/subfolder`` or ``machine:`` for root.
        Returns FolderContentNames: {files: [], subfolders: []}.
        """
        return await self._get(
            "/FileSystem/EnumerateFolderContents", params={"path": path}
        )

    async def enumerate_programs(
        self, root: str = "machine:", max_depth: int = 1
    ) -> list[dict[str, str]]:
        """Walk the machine filesystem and return a flat list of programs.

        Only files ending in ``.simpl`` are included. Traverses ``root``
        plus *max_depth* levels of subfolders (default 1). Each entry is
        ``{"name": str, "path": str, "folder": str}`` where ``path`` is
        the SimPL path usable with ``LoadProgram`` / ``ExecuteProgramAsync``.
        """
        results: list[dict[str, str]] = []

        async def _walk(folder: str, depth: int) -> None:
            try:
                data = await self.enumerate_folder_contents(folder)
            except DatronApiError as err:
                _LOGGER.debug("enumerate_programs: skipping %s: %s", folder, err)
                return
            if not isinstance(data, dict):
                return
            files = data.get("files") or []
            for f in files:
                if not isinstance(f, str) or not f.lower().endswith(".simpl"):
                    continue
                # Root path looks like "machine:" (trailing colon, no slash)
                separator = "" if folder.endswith(":") else "/"
                full_path = f"{folder}{separator}{f}"
                # Display folder: "" for root, else strip "machine:" prefix
                display_folder = (
                    "" if folder.endswith(":") else folder.split(":", 1)[-1]
                )
                results.append(
                    {"name": f, "path": full_path, "folder": display_folder}
                )
            if depth <= 0:
                return
            for sub in data.get("subfolders") or []:
                if not isinstance(sub, str):
                    continue
                separator = "" if folder.endswith(":") else "/"
                await _walk(f"{folder}{separator}{sub}", depth - 1)

        await _walk(root, max_depth)
        return results

    # ── User ─────────────────────────────────────────────────

    async def get_user_info(self) -> dict[str, Any]:
        """Get current user permissions/claims."""
        return await self._get("/User/Info")

    # ── Validation ───────────────────────────────────────────

    async def validate_connection(self) -> dict[str, Any]:
        """Validate connectivity and authentication. Returns user info."""
        return await self.get_user_info()
