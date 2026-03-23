"""Camera platform for Datron NEXT integration."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DatronApiClient
from .const import API_VERSION, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Token is refreshed at most once per interval; image bytes are fetched
# directly from the public endpoint without touching the API-client semaphore.
_IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=5)
_TOKEN_MAX_AGE_S = 120  # seconds before forcing a token refresh


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT camera entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: DatronApiClient = data["client"]

    entities = [DatronMachineCamera(hass=hass, entry=entry, client=client)]
    async_add_entities(entities)


class DatronMachineCamera(Camera):
    """Camera entity for the Datron machine camera.

    Image delivery is two-step:
      1. ``GET /Camera/CreateCameraImageUrl`` → ``{imageUrl: "…?token=…"}``
      2. ``GET <imageUrl>`` → JPEG bytes  (public endpoint, no bearer auth)

    To keep latency low the token URL is cached and re-used until it
    expires (auto-detected) or ``_TOKEN_MAX_AGE_S`` elapses.  **All HTTP
    traffic in this entity bypasses the API-client semaphores** so the
    camera feed is never blocked by coordinator polling.

    Compatible with the standard HA camera proxy stream endpoint
    (``/api/camera_proxy_stream/<entity_id>``) used by Advanced Camera Card.
    """

    _attr_has_entity_name = True
    _attr_name = "Machine Camera"
    _attr_frame_interval = 1.0  # target ~1 fps when HA streams via proxy

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DatronApiClient,
    ) -> None:
        super().__init__()
        self._entry = entry
        # Connection details — used for direct HTTP calls that bypass the
        # API-client semaphore.  The bearer token is only needed for the
        # CreateCameraImageUrl endpoint; the actual image fetch uses the
        # short-lived query-string token returned by that endpoint.
        self._base_url = f"http://{client._host}:{client._port}/api/v{API_VERSION}"
        self._auth_headers: dict[str, str] = {
            "Authorization": f"Bearer {client._token}",
            "Accept": "application/json; v=2.0",
        }
        self._host_prefix = f"http://{client._host}:{client._port}"

        self._attr_unique_id = f"{entry.entry_id}_machine_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

        # Cached state
        self._token_url: str | None = None
        self._token_ts: float = 0.0  # monotonic time of last successful refresh
        self._cached_image: bytes | None = None
        self._token_lock = asyncio.Lock()

    # ── internal helpers ──────────────────────────────────────

    def _make_absolute(self, url: str) -> str:
        """Ensure *url* is absolute."""
        if url.startswith(("http://", "https://")):
            return url
        return (
            f"{self._host_prefix}{url}"
            if url.startswith("/")
            else f"{self._host_prefix}/{url}"
        )

    async def _refresh_token(self) -> None:
        """Fetch a fresh image-token URL (direct HTTP — no semaphore)."""
        session = async_get_clientsession(self.hass)
        url = f"{self._base_url}/Camera/CreateCameraImageUrl?streamId=0"
        try:
            async with session.get(
                url, headers=self._auth_headers, timeout=_IMAGE_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    info = await resp.json(content_type=None)
                    raw = info.get("imageUrl") if isinstance(info, dict) else None
                    if raw:
                        self._token_url = self._make_absolute(raw)
                        self._token_ts = time.monotonic()
                        _LOGGER.debug("Camera token refreshed: %s", self._token_url)
                        return
                _LOGGER.debug("Camera token refresh HTTP %s", resp.status)
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Camera token refresh error: %s", err)

    async def _ensure_token(self) -> None:
        """Ensure we hold a usable token URL, refreshing if stale."""
        now = time.monotonic()
        if self._token_url and (now - self._token_ts) < _TOKEN_MAX_AGE_S:
            return
        async with self._token_lock:
            # Double-check after acquiring the lock
            now = time.monotonic()
            if self._token_url and (now - self._token_ts) < _TOKEN_MAX_AGE_S:
                return
            await self._refresh_token()

    async def _fetch_snapshot(self, url: str) -> bytes | None:
        """GET image bytes from the public image endpoint (no auth needed)."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=_IMAGE_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return data if data else None
                _LOGGER.debug("Camera snapshot HTTP %s", resp.status)
                return None
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Camera snapshot error: %s", err)
            return None

    # ── HA Camera interface ───────────────────────────────────

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a JPEG snapshot from the machine camera.

        Called by HA's camera proxy (including the MJPEG proxy-stream
        endpoint used by Advanced Camera Card).
        """
        await self._ensure_token()

        if not self._token_url:
            return self._cached_image

        # Fast path — use cached token URL
        data = await self._fetch_snapshot(self._token_url)
        if data:
            self._cached_image = data
            return data

        # Token may have expired — force a refresh and retry once
        _LOGGER.debug("Snapshot failed; refreshing camera token")
        self._token_url = None
        self._token_ts = 0.0
        await self._refresh_token()
        if self._token_url:
            data = await self._fetch_snapshot(self._token_url)
            if data:
                self._cached_image = data
                return data

        return self._cached_image
