"""Camera platform for Datron NEXT integration."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DatronApiClient
from .const import (
    API_VERSION,
    CONF_CONNECTION_TYPE,
    CONNECTION_LIVE,
    CONNECTION_NEXT,
    DOMAIN,
)
from .entity import build_device_info
from .live_api import DatronLiveClient

_LOGGER = logging.getLogger(__name__)

# Token is refreshed at most once per interval; image bytes are fetched
# directly from the public endpoint without touching the API-client semaphore.
_IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=5)
_TOKEN_MAX_AGE_S = 120  # seconds before forcing a token refresh

# Live MJPEG helpers
_MJPEG_TIMEOUT = aiohttp.ClientTimeout(total=15)
_STREAM_URL_MAX_AGE_S = 300  # re-resolve the stream URL periodically


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron camera entities from a config entry.

    NEXT entries get a token-per-frame snapshot camera; Datron Live entries get
    an MJPEG stream camera.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]

    if data.get(CONF_CONNECTION_TYPE, CONNECTION_NEXT) == CONNECTION_LIVE:
        entities = [DatronLiveMachineCamera(hass=hass, entry=entry, client=client)]
    else:
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
        self._attr_device_info = build_device_info(entry)

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


class DatronLiveMachineCamera(Camera):
    """MJPEG camera entity for Datron Live entries.

    Datron Live exposes a standard MJPEG stream. The stream URL is resolved
    from ``GET /api/v2.0/Camera/Configuration`` →
    ``[{url, port, isAuthenticationRequired, userName, passWord}]`` and built as
    ``http://{host}:{port}{url}`` (scheme is **http**, port from the config,
    e.g. 44347). The URL is cached and re-resolved periodically and on error
    (the port can change across machine restarts).

    ``isAuthenticationRequired`` was false on the reference machine; when true,
    the configured userName/passWord are honoured as HTTP basic auth.
    """

    _attr_has_entity_name = True
    _attr_name = "Machine Camera"
    # Intentionally NOT declaring CameraEntityFeature.STREAM: the source is a
    # multipart/x-mixed-replace MJPEG stream, which HA's stream (HLS/PyAV)
    # worker cannot ingest. Declaring STREAM would route the frontend to the
    # stream worker and break the live view; instead we serve frames via
    # async_camera_image and proxy the live view via handle_async_mjpeg_stream,
    # exactly as HA's own mjpeg integration does.

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DatronLiveClient,
    ) -> None:
        super().__init__()
        self._entry = entry
        self._client = client

        self._attr_unique_id = f"{entry.entry_id}_machine_camera"
        self._attr_device_info = build_device_info(entry)
        self._attr_is_streaming = True

        # Cached stream configuration
        self._stream_url: str | None = None
        self._stream_auth: aiohttp.BasicAuth | None = None
        self._stream_ts: float = 0.0
        self._stream_lock = asyncio.Lock()
        self._cached_image: bytes | None = None

    # ── internal helpers ──────────────────────────────────────

    async def _resolve_stream(self, force: bool = False) -> str | None:
        """Resolve (and cache) the MJPEG stream URL + optional basic auth."""
        now = time.monotonic()
        if (
            not force
            and self._stream_url
            and (now - self._stream_ts) < _STREAM_URL_MAX_AGE_S
        ):
            return self._stream_url

        async with self._stream_lock:
            now = time.monotonic()
            if (
                not force
                and self._stream_url
                and (now - self._stream_ts) < _STREAM_URL_MAX_AGE_S
            ):
                return self._stream_url

            try:
                configs = await self._client.get_camera_configuration()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Live camera configuration fetch failed: %s", err)
                return self._stream_url  # keep whatever we had

            url: str | None = None
            auth: aiohttp.BasicAuth | None = None
            if configs:
                cfg = configs[0]
                if isinstance(cfg, dict):
                    raw_url = cfg.get("url")
                    port = cfg.get("port")
                    if raw_url and port is not None:
                        url = f"http://{self._client._host}:{port}{raw_url}"
                    if cfg.get("isAuthenticationRequired"):
                        user = cfg.get("userName") or ""
                        pwd = cfg.get("passWord") or ""
                        if user:
                            auth = aiohttp.BasicAuth(user, pwd)

            if url:
                self._stream_url = url
                self._stream_auth = auth
                self._stream_ts = time.monotonic()
                _LOGGER.debug("Live camera stream URL resolved: %s", url)
            return self._stream_url

    async def _read_one_frame(self, url: str) -> bytes | None:
        """Read a single JPEG frame from the MJPEG multipart stream.

        Reads from the stream until one complete JPEG (SOI ``\\xff\\xd8`` …
        EOI ``\\xff\\xd9``) has been captured, then closes the connection.
        """
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                url, timeout=_MJPEG_TIMEOUT, auth=self._stream_auth
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Live camera stream HTTP %s", resp.status)
                    return None
                buffer = b""
                # Cap total read at ~2 MB so a malformed stream can't spin.
                while len(buffer) < 2 * 1024 * 1024:
                    chunk = await resp.content.read(16384)
                    if not chunk:
                        break
                    buffer += chunk
                    start = buffer.find(b"\xff\xd8")
                    if start == -1:
                        continue
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if end == -1:
                        continue
                    return buffer[start : end + 2]
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Live camera frame read error: %s", err)
        return None

    # ── HA Camera interface ───────────────────────────────────

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a single JPEG frame extracted from the MJPEG stream."""
        url = await self._resolve_stream()
        if not url:
            return self._cached_image

        data = await self._read_one_frame(url)
        if data:
            self._cached_image = data
            return data

        # The stream URL / port may have changed — force a re-resolve and
        # retry once.
        _LOGGER.debug("Live camera frame failed; re-resolving stream URL")
        url = await self._resolve_stream(force=True)
        if url:
            data = await self._read_one_frame(url)
            if data:
                self._cached_image = data
                return data

        return self._cached_image

    async def handle_async_mjpeg_stream(self, request):
        """Serve the MJPEG stream through HA (proxied to the machine)."""
        from homeassistant.helpers.aiohttp_client import (
            async_aiohttp_proxy_web,
        )

        url = await self._resolve_stream()
        if not url:
            return await super().handle_async_mjpeg_stream(request)

        session = async_get_clientsession(self.hass)
        try:
            stream = await session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
                auth=self._stream_auth,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Live camera MJPEG proxy connect failed: %s", err)
            # Port may have changed — re-resolve once for next time.
            await self._resolve_stream(force=True)
            return await super().handle_async_mjpeg_stream(request)

        return await async_aiohttp_proxy_web(self.hass, request, stream)
