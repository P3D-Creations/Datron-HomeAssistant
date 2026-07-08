"""API client for the Datron Live (Cockpit) web-UI backend.

``DatronLiveClient`` is a **duck-typed sibling** of ``DatronApiClient`` — it
exposes the same public method *names* that the coordinators, platforms and
services call, so the rest of the integration does not care which client it
holds. Where Datron Live has no equivalent endpoint the method raises
``DatronApiError("... not available on Datron Live")`` so the shared
coordinators simply drop that key.

Key differences from the NEXT client:

* ``https://`` base with ``ssl=False`` (self-signed LAN certificate).
* JWT login via username/password (``/api/User/CreateToken``) with transparent
  re-login + retry on 401.
* Mixed URL versioning — most paths are un-versioned (``/api/…``); a couple are
  versioned (``/api/v1.0/…``, ``/api/v2.0/…``). Paths are given absolute here.
* ``Content-Type: application/json; v=1.0`` on every request.
* MJPEG camera instead of the NEXT token-per-frame snapshot camera.

Read-only except for pause / confirm-dialog / resume.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

# Reuse the exception hierarchy from the NEXT client — do NOT redefine.
from .api import (
    DatronApiError,
    DatronAuthError,
    DatronLicenseError,
    DatronStateError,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=15)

# The embedded Cockpit server, like NEXT's Kestrel server, only tolerates a
# small number of concurrent connections. Serialise polling through one
# semaphore.
MAX_CONCURRENT_REQUESTS = 1

# The warehouse tool list is ~440 KB and the medium coordinator polls every 6 s.
# Cache it internally so the frequent poll doesn't hammer the embedded server.
_WAREHOUSE_TTL_S = 300.0
_CHANGER_TTL_S = 60.0

# Case-insensitive substrings that identify a "continue / resume" dialog button.
# NOTE: "start" is deliberately NOT here — it matches "Restart"/"Start program",
# which on a CNC would re-run the program from the beginning (destructive), not
# resume. Resume in DE/EN is "Continue"/"Fortsetzen"/"Weiter".
_RESUME_BUTTON_HINTS = ("continue", "resume", "fortsetzen", "weiter", "fortfahren")

# Labels that must NEVER be pressed by the resume heuristic even if they happen
# to contain a resume hint. Guards against destructive actions on ambiguous
# dialogs (e.g. an error dialog offering "Restart" while the machine is paused).
_RESUME_EXCLUDE_HINTS = (
    "restart",
    "neustart",
    "neu start",
    "neu starten",
    "abort",
    "stop",
    "cancel",
    "abbrechen",
    "reset",
)


class DatronLiveClient:
    """Client for the Datron Live (Cockpit) REST API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the Live API client."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._session = session
        self._base_url = f"https://{host}:{port}"
        self._token: str | None = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        # Guards concurrent logins so a burst of 401s triggers only one
        # re-login.
        self._login_lock = asyncio.Lock()

        # Internal TTL caches for the large tool lists.
        self._warehouse_cache: list[dict[str, Any]] | None = None
        self._warehouse_cache_ts: float = 0.0
        self._changer_cache: list[dict[str, Any]] | None = None
        self._changer_cache_ts: float = 0.0

    def set_session(self, session: aiohttp.ClientSession) -> None:
        """Set the aiohttp session."""
        self._session = session

    # ── Headers ──────────────────────────────────────────────

    @property
    def _base_headers(self) -> dict[str, str]:
        """Return the version-negotiation header sent on every request."""
        return {"Content-Type": "application/json; v=1.0"}

    def _auth_headers(self) -> dict[str, str]:
        """Return headers with the current bearer token attached."""
        headers = dict(self._base_headers)
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # ── Auth ─────────────────────────────────────────────────

    async def login(self) -> None:
        """Log in and capture the JWT bearer token.

        POSTs ``/api/User/CreateToken`` with ``{"Username":.., "Password":..}``
        (capitalized keys). The response is ``{"username","token"}`` (lowercase).
        A 400 means bad credentials → ``DatronAuthError``.

        This is the background token-capture utility reused by the config flow.
        """
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")

        url = f"{self._base_url}/api/User/CreateToken"
        body = {"Username": self._username, "Password": self._password}
        try:
            async with self._session.post(
                url,
                json=body,
                headers=self._base_headers,
                timeout=REQUEST_TIMEOUT,
                ssl=False,
            ) as resp:
                if resp.status == 400:
                    raise DatronAuthError(
                        "Login failed — invalid username or password"
                    )
                if resp.status == 401:
                    raise DatronAuthError("Login failed — unauthorized")
                if resp.status >= 400:
                    text = await resp.text()
                    raise DatronApiError(
                        f"Login error {resp.status}: {text}"
                    )
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DatronApiError(f"Connection error during login: {err}") from err
        except TimeoutError as err:
            raise DatronApiError("Timeout during login") from err

        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise DatronApiError("Login response did not contain a token")
        self._token = token
        _LOGGER.debug("[LIVE] Login successful, token captured")

    async def _ensure_login(self) -> None:
        """Log in if we don't yet hold a token (guarded)."""
        if self._token:
            return
        async with self._login_lock:
            if self._token:
                return
            await self.login()

    async def _relogin(self, stale_token: str | None) -> None:
        """Re-login once after a 401, deduplicating bursts.

        If several requests 401 at the same time they all call this, but only
        the first one actually re-logs-in — the rest see that the token has
        already changed from the one their failed request used and return
        immediately to retry with the fresh token.
        """
        async with self._login_lock:
            if self._token is not None and self._token != stale_token:
                # Someone else already refreshed the token.
                return
            await self.login()

    # ── Core request ─────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated request (serialised through the semaphore).

        On a 401 the token is transparently re-captured via ``login()`` once
        and the request is retried a single time; a second 401 raises
        ``DatronAuthError``.
        """
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")

        await self._ensure_login()

        url = f"{self._base_url}{path}"
        # Two attempts max: the original request and one retry after re-login.
        # The retry happens OUTSIDE the semaphore context of the first attempt
        # (the semaphore is not reentrant).
        for attempt in (1, 2):
            token_used = self._token
            async with self._semaphore:
                start = time.monotonic()
                try:
                    async with self._session.request(
                        method,
                        url,
                        headers=self._auth_headers(),
                        timeout=REQUEST_TIMEOUT,
                        ssl=False,
                        **kwargs,
                    ) as resp:
                        if resp.status == 401:
                            if attempt == 1:
                                unauthorized = True
                            else:
                                raise DatronAuthError(
                                    "Authentication failed — re-login did not help"
                                )
                        else:
                            unauthorized = False
                            if resp.status == 403:
                                body = (await resp.text()).strip()
                                raise DatronLicenseError(
                                    f"Forbidden for {path}: "
                                    f"{body or 'insufficient license tier'}"
                                )
                            if resp.status == 204:
                                return None
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
                        "[LIVE] ClientError after %.3fs for %s %s: %s",
                        elapsed, method, url, err,
                    )
                    raise DatronApiError(
                        f"Connection error for {path}: {err}"
                    ) from err
                except TimeoutError as err:
                    raise DatronApiError(f"Timeout requesting {path}") from err

            if unauthorized:
                # Token likely expired — re-login once (deduplicated) and let
                # the loop retry with the fresh token.
                _LOGGER.debug("[LIVE] 401 for %s — re-logging in and retrying", path)
                await self._relogin(token_used)

        # Unreachable — attempt 2 either returns or raises — but keeps type
        # checkers happy.
        raise DatronAuthError("Authentication failed")

    async def _get(self, path: str, **kwargs: Any) -> Any:
        """Authenticated GET."""
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> Any:
        """Authenticated POST."""
        return await self._request("POST", path, **kwargs)

    # ── Validation / user ────────────────────────────────────

    async def validate_connection(self) -> dict[str, Any]:
        """Validate connectivity + auth. Returns user info (``/User/Info``)."""
        return await self.get_user_info()

    async def get_user_info(self) -> dict[str, Any]:
        """Get current user claims/licenses."""
        return await self._get("/api/User/Info")

    # ── Machine identity & status ────────────────────────────

    async def get_machine_status(self) -> dict[str, Any]:
        """Get machine execution state. Returns ``{"executionState": str}``."""
        return await self._get("/api/Machine/MachineStatus")

    async def get_machine_number(self) -> dict[str, Any]:
        """Get the machine serial number."""
        return await self._get("/api/Machine/MachineNumber")

    async def get_machine_type(self) -> dict[str, Any]:
        """Get the machine type."""
        return await self._get("/api/Machine/MachineType")

    async def get_licenses(self) -> dict[str, Any]:
        """Get activated licenses / feature gating."""
        return await self._get("/api/Machine/Licenses")

    async def ping(self) -> bool:
        """Health check. Returns True if the machine responds."""
        try:
            result = await self._get("/api/Machine/Ping")
        except DatronApiError:
            return False
        if isinstance(result, bool):
            return result
        return result is not None

    # ── Machine components (sensors) ─────────────────────────

    async def get_compressed_air(self) -> dict[str, Any]:
        """Get compressed air sensor data."""
        return await self._get("/api/MachineComponents/CompressedAir")

    async def get_vacuum(self) -> dict[str, Any]:
        """Get vacuum sensor data."""
        return await self._get("/api/MachineComponents/Vacuum")

    async def get_spray_system(self) -> dict[str, Any]:
        """Get spray system (EKD/Microjet) status."""
        return await self._get("/api/MachineComponents/SpraySystem")

    async def get_status_light(self) -> dict[str, Any]:
        """Get RGB status light values."""
        return await self._get("/api/MachineComponents/StatusLight")

    # ── Runtime (program execution) ──────────────────────────

    async def get_current_program(self) -> dict[str, Any]:
        """Get currently loaded program info."""
        return await self._get("/api/Runtime/CurrentlyLoadedProgram")

    async def get_execution_durations(self) -> dict[str, Any]:
        """Get execution timing (elapsed, remaining, progress)."""
        return await self._get("/api/Runtime/ExecutionDurations")

    async def get_notifications(self) -> list[dict[str, Any]]:
        """Get the notifications list."""
        return await self._get("/api/Runtime/Notifications")

    async def get_preview_image_url(self) -> dict[str, Any]:
        """Get URL for preview image of loaded program.

        Returns ``{"url": "/api/v1.0/Image/ProgramPreviewImage?token=.."}``.
        """
        return await self._get("/api/Runtime/PreviewImage")

    # ── Tools ────────────────────────────────────────────────

    async def get_tool_in_spindle(self) -> dict[str, Any]:
        """Get the tool currently in the spindle."""
        return await self._get("/api/Tool/ToolInSpindle")

    async def get_tools_in_program(self) -> list[dict[str, Any]]:
        """Get tools needed for the currently loaded program."""
        return await self._get("/api/Tool/ToolsInProgram")

    async def get_tools_in_changer(self) -> list[dict[str, Any]]:
        """Get tools in the changer (magazine).

        Live path differs from NEXT's ``ToolsInEmbeddedToolChanger``. Cached for
        a short TTL to keep the frequent medium poll cheap.
        """
        now = time.monotonic()
        if (
            self._changer_cache is not None
            and (now - self._changer_cache_ts) < _CHANGER_TTL_S
        ):
            return self._changer_cache
        result = await self._get("/api/Tool/ToolsInChanger")
        # Normalise to a list and cache the outcome (including an empty 204/None
        # response) so the TTL is honoured instead of re-fetching every poll.
        result = result if isinstance(result, list) else []
        self._changer_cache = result
        self._changer_cache_ts = now
        return result

    async def get_tools_in_warehouse(self) -> list[dict[str, Any]]:
        """Get tools in the warehouse.

        The response is ~440 KB and the medium coordinator polls every 6 s, so
        this method keeps an internal ~300 s TTL cache and serves cached data to
        the frequent poll instead of hammering the embedded server.
        """
        now = time.monotonic()
        if (
            self._warehouse_cache is not None
            and (now - self._warehouse_cache_ts) < _WAREHOUSE_TTL_S
        ):
            return self._warehouse_cache
        result = await self._get("/api/Tool/ToolsInWarehouse")
        # Normalise to a list and cache the outcome (including an empty 204/None
        # response) so the TTL is honoured instead of re-fetching 440 KB every
        # 6 s poll.
        result = result if isinstance(result, list) else []
        self._warehouse_cache = result
        self._warehouse_cache_ts = now
        return result

    async def get_tool_image(
        self,
        token: str | None = None,
        width: int = 400,
        height: int = 400,
        up_right: bool = True,
    ) -> bytes | None:
        """Get a tool image from ``/api/v1.0/Image/Tool``.

        If *token* is provided it is passed as the query-string token; otherwise
        bearer auth is used.
        """
        params: dict[str, Any] = {
            "widthInPixel": width,
            "heightInPixel": height,
            "upRight": str(up_right).lower(),
            "withSpindle": "true",
        }
        if token:
            params["token"] = token
        return await self._get("/api/v1.0/Image/Tool", params=params)

    # ── Images ───────────────────────────────────────────────

    async def fetch_image_url(self, url: str) -> bytes | None:
        """Fetch image bytes from a URL whose token is embedded in the query.

        No bearer auth is sent — the query-string token is the authentication
        mechanism. Relative URLs are prepended with ``https://{host}:{port}``.
        """
        if self._session is None:
            raise DatronApiError("No aiohttp session configured")

        if not url.startswith("http"):
            # Ensure a leading slash so a relative path without one
            # ("api/v1.0/…") doesn't concatenate into "https://host:443api/…".
            if not url.startswith("/"):
                url = f"/{url}"
            url = f"{self._base_url}{url}"

        _LOGGER.debug("[LIVE] Fetching image from URL: %s", url)
        async with self._semaphore:
            try:
                async with self._session.get(
                    url, timeout=IMAGE_TIMEOUT, ssl=False
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
                raise DatronApiError(f"Image connection error: {err}") from err
            except TimeoutError as err:
                raise DatronApiError("Timeout fetching image") from err

    async def get_program_preview_image(self) -> bytes | None:
        """Fetch the program preview image bytes (two-step: url then fetch)."""
        url_info = await self.get_preview_image_url()
        if url_info is None:
            return None
        image_url: str | None = None
        if isinstance(url_info, dict):
            image_url = (
                url_info.get("url")
                or url_info.get("imageUrl")
                or url_info.get("fullName")
            )
        elif isinstance(url_info, str) and url_info:
            image_url = url_info
        if not image_url:
            return None
        return await self.fetch_image_url(image_url)

    # ── Camera ───────────────────────────────────────────────

    async def get_camera_configuration(self) -> list[dict[str, Any]]:
        """Get camera configuration.

        Returns a list ``[{url, port, isAuthenticationRequired, userName,
        passWord}]``.
        """
        result = await self._get("/api/v2.0/Camera/Configuration")
        if isinstance(result, list):
            return result
        return []

    async def get_camera_stream_url(self, index: int = 0) -> str | None:
        """Return the MJPEG stream URL for a configured camera.

        The SPA builds the URL as ``http://{host}:{port}{url}`` where *port* and
        *url* come from the configuration. Scheme is **http** (not https). The
        configured port (e.g. 44347) differs from the API port. Returns None if
        no camera is configured.
        """
        configs = await self.get_camera_configuration()
        if not configs or index >= len(configs):
            return None
        cfg = configs[index]
        if not isinstance(cfg, dict):
            return None
        url = cfg.get("url")
        port = cfg.get("port")
        if not url or port is None:
            return None
        return f"http://{self._host}:{port}{url}"

    # ── Dialog ───────────────────────────────────────────────

    async def get_open_dialog(self) -> dict[str, Any] | None:
        """Get the currently open dialog.

        Returns None on 204 (no dialog). Otherwise a dict with
        ``{id, severity, caption, text, details, rightButtons:[label,..]}``.
        """
        return await self._get("/api/Dialog/OpenDialog")

    async def confirm_dialog(self, dialog_id: str, button: str) -> None:
        """Confirm an open dialog by echoing the chosen button label."""
        await self._post(
            "/api/Dialog/ConfirmDialog",
            json={"id": dialog_id, "button": button},
        )

    # ── Execution control ────────────────────────────────────

    async def pause_execution(self) -> Any:
        """Pause the current program execution.

        POSTs ``/api/Execution/Pause`` with an empty body. Only meaningful when
        the machine is Running.
        """
        return await self._post("/api/Execution/Pause", json={})

    async def resume_execution(self) -> Any:
        """Resume a paused program — **best-effort, provisional**.

        Datron Live has **no dedicated resume endpoint** in the Cockpit bundle.
        When a program is paused the machine raises a dialog with a
        continue/resume button. This method fetches the open dialog and, if one
        of its ``rightButtons`` labels matches a continue/resume pattern
        (case-insensitive contains any of: "continue", "resume", "fortsetzen",
        "weiter", "start"), confirms that button. If no dialog is open or no
        matching button is found it raises ``DatronStateError``.

        NOTE: this heuristic has NOT been verified against a live paused machine
        (the machine was active / read-only during development). The exact
        continue-button label must be confirmed live.
        """
        dialog = await self.get_open_dialog()
        if not isinstance(dialog, dict):
            raise DatronStateError(
                "Cannot resume: no open dialog with a continue/resume button. "
                "Datron Live has no dedicated resume endpoint; resume is only "
                "possible via the machine's pause dialog."
            )
        dialog_id = dialog.get("id")
        buttons = dialog.get("rightButtons") or []
        match: str | None = None
        for label in buttons:
            if not isinstance(label, str):
                continue
            low = label.strip().lower()
            # Never press an excluded (destructive) label, even if it also
            # contains a resume hint (e.g. "Restart").
            if any(bad in low for bad in _RESUME_EXCLUDE_HINTS):
                continue
            if any(hint in low for hint in _RESUME_BUTTON_HINTS):
                match = label
                break
        if not dialog_id or not match:
            raise DatronStateError(
                "Cannot resume: open dialog has no continue/resume button "
                f"(available buttons: {buttons})."
            )
        await self.confirm_dialog(dialog_id, match)
        return {"resultCode": "Success"}

    # ── RemoteLink (license-gated) ───────────────────────────

    async def get_remote_link_programs(self) -> dict[str, Any]:
        """Get the RemoteLink program list.

        License-gated — may 403 (``DatronLicenseError`` propagates).
        """
        return await self._get("/api/RemoteLink/RemoteLinkPrograms")

    async def execute_remote_link(self, name: str) -> Any:
        """Execute a RemoteLink program by name.

        Body key is capital ``Name`` — differs from the NEXT client's ``name``.
        """
        return await self._post("/api/RemoteLink/Execute", json={"Name": name})

    # ── Methods with no Live backing ─────────────────────────
    #
    # Two flavours:
    #  * Endpoints the shared coordinators POLL every cycle return an empty
    #    value so the coordinator stores an empty key WITHOUT logging a warning
    #    on every poll. The entities that would consume these keys are not
    #    created for Live, so the empty value is never surfaced.
    #  * Action endpoints (only reachable via a user button/service) RAISE, so
    #    the user gets a clear "not available on Datron Live" error instead of a
    #    silent no-op.

    @staticmethod
    def _not_available(name: str) -> DatronApiError:
        return DatronApiError(f"{name} not available on Datron Live")

    # -- polled by coordinators → return empty (no per-poll log spam) --

    async def get_axis_positions_direct(self) -> dict[str, Any]:
        """Not available on Datron Live — empty so the axis poll stays quiet."""
        return {}

    async def get_axis_positions(self) -> dict[str, Any]:
        """Not available on Datron Live."""
        return {}

    async def get_feed_override(self) -> dict[str, Any]:
        """Not available on Datron Live — empty so the fast poll stays quiet."""
        return {}

    async def get_runtime(self) -> dict[str, Any]:
        """Not available on Datron Live."""
        return {}

    async def get_software_version(self) -> dict[str, Any]:
        """Not available on Datron Live."""
        return {}

    async def get_workpieces(self) -> list[dict[str, Any]]:
        """Not available on Datron Live."""
        return []

    async def enumerate_programs(
        self, roots: list[str] | None = None, max_depth: int = 1
    ) -> list[dict[str, str]]:
        """Not available on Datron Live (no SimPL filesystem)."""
        return []

    # -- reachable only via user action → raise a clear error --

    async def get_workpiece_image(self) -> bytes | None:
        """Not available on Datron Live."""
        raise self._not_available("get_workpiece_image")

    async def enumerate_folder_contents(self, path: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("enumerate_folder_contents")

    async def get_program_file_info(self, path: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("get_program_file_info")

    async def load_program(self, path: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("load_program")

    async def execute_program_async(self, path: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("execute_program_async")

    async def execute_loaded_program(self) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("execute_loaded_program")

    async def abort_execution(self) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("abort_execution")

    async def move_to_park_position(self) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("move_to_park_position")

    async def reference_machine(self) -> bool:
        """Not available on Datron Live."""
        raise self._not_available("reference_machine")

    async def activate_workpiece(self, workpiece_name: str) -> bool:
        """Not available on Datron Live."""
        raise self._not_available("activate_workpiece")

    async def get_bool_variable(self, name: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("get_bool_variable")

    async def set_bool_variable(self, name: str, value: bool) -> Any:
        """Not available on Datron Live."""
        raise self._not_available("set_bool_variable")

    async def get_number_variable(self, name: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("get_number_variable")

    async def set_number_variable(self, name: str, value: float) -> Any:
        """Not available on Datron Live."""
        raise self._not_available("set_number_variable")

    async def get_string_variable(self, name: str) -> dict[str, Any]:
        """Not available on Datron Live."""
        raise self._not_available("get_string_variable")

    async def set_string_variable(self, name: str, value: str) -> Any:
        """Not available on Datron Live."""
        raise self._not_available("set_string_variable")
