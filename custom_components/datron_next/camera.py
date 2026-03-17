"""Camera platform for Datron NEXT integration."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DatronApiClient, DatronApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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

    The Datron camera API works as a single-frame (snapshot) endpoint:
      1. GET /Camera/CreateCameraImageUrl  →  {"streamId": N, "imageUrl": "/api/v2.0/Image/Camera?token=..."}
      2. GET <absolute imageUrl>           →  JPEG image bytes

    A fresh token is fetched on every snapshot request.
    The STREAM feature is intentionally NOT advertised — this endpoint
    is snapshot-based, not a continuous RTSP/HLS stream.
    """

    _attr_has_entity_name = True
    _attr_name = "Machine Camera"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: DatronApiClient) -> None:
        super().__init__()
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_machine_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )
        self._cached_image: bytes | None = None

    def _make_absolute(self, url: str) -> str:
        """Ensure a URL is absolute by prepending the machine host if needed."""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        prefix = f"http://{self._client._host}:{self._client._port}"
        return f"{prefix}{url}" if url.startswith("/") else f"{prefix}/{url}"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a current snapshot from the machine camera."""
        try:
            # Step 1: obtain a fresh token-based image URL
            info = await self._client.get_camera_image_url()
            if not isinstance(info, dict):
                _LOGGER.debug("Unexpected camera URL response type: %s", type(info))
                return self._cached_image

            # CameraImageUrl schema: {"streamId": int, "imageUrl": "..."}
            image_url = info.get("imageUrl")
            if not image_url:
                _LOGGER.debug("No imageUrl in camera response: %s", info)
                return self._cached_image

            # Step 2: fetch the image bytes from the absolute URL
            abs_url = self._make_absolute(image_url)
            _LOGGER.debug("Fetching camera snapshot from: %s", abs_url)
            image_data = await self._client.fetch_image_url(abs_url)
            if isinstance(image_data, bytes) and len(image_data) > 0:
                self._cached_image = image_data
                return image_data

        except DatronApiError as err:
            _LOGGER.debug("Error fetching camera image: %s", err)

        return self._cached_image
