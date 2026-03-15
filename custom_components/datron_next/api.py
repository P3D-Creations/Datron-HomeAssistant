"""API client for the Datron NEXT REST API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_VERSION

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Datron's embedded HTTP server can only handle a small number of
# concurrent connections. We serialise all requests through a semaphore.
MAX_CONCURRENT_REQUESTS = 1


class DatronApiError(Exception):
    """Exception for Datron API errors."""


class DatronAuthError(DatronApiError):
    """Exception for authentication errors."""


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
        _LOGGER.debug("API request: %s %s", method, url)
        async with self._semaphore:
            try:
                async with self._session.request(
                    method, url, headers=self._headers, timeout=REQUEST_TIMEOUT, **kwargs
                ) as resp:
                    if resp.status == 401:
                        raise DatronAuthError("Authentication failed — invalid or expired token")
                    if resp.status == 403:
                        raise DatronAuthError("Forbidden — insufficient API license tier")
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
                raise DatronApiError(f"Connection error for {path}: {err}") from err
            except TimeoutError as err:
                raise DatronApiError(f"Timeout requesting {path}") from err

    async def _get(self, path: str, **kwargs: Any) -> Any:
        """HTTP GET request."""
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> Any:
        """HTTP POST request."""
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

    # ── User ─────────────────────────────────────────────────

    async def get_user_info(self) -> dict[str, Any]:
        """Get current user permissions/claims."""
        return await self._get("/User/Info")

    # ── Validation ───────────────────────────────────────────

    async def validate_connection(self) -> dict[str, Any]:
        """Validate connectivity and authentication. Returns user info."""
        return await self.get_user_info()
