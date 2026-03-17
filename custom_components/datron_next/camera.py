"""Camera platform for Datron NEXT integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
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
    """Camera entity for the Datron machine camera stream."""

    _attr_has_entity_name = True
    _attr_name = "Machine Camera"
    _attr_supported_features = CameraEntityFeature.STREAM

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
        self._stream_url: str | None = None

    async def async_camera_stream(self) -> str | None:
        """Return the camera stream URL (RTSP or MJPEG), always absolute."""
        try:
            info = await self._client.get_camera_image_url()
            for key in ("url", "streamUrl", "rtspUrl", "mjpegUrl"):
                url = info.get(key)
                if url and isinstance(url, str):
                    # If the URL is not absolute, prefix with machine IP
                    if url.startswith("http://") or url.startswith("https://"):
                        self._stream_url = url
                        return url
                    else:
                        full_url = f"http://{self._client._host}:{self._client._port}{url}" if url.startswith("/") else f"http://{self._client._host}:{self._client._port}/{url}"
                        self._stream_url = full_url
                        return full_url
            token = info.get("token")
            if token:
                url = f"http://{self._client._host}:{self._client._port}/api/v2.0/Image/Camera?token={token}"
                self._stream_url = url
                return url
        except DatronApiError as err:
            _LOGGER.warning("Error fetching camera stream URL: %s", err)
        return self._stream_url

    async def async_stream_source(self) -> str | None:
        """Return the stream source URL for Home Assistant's stream component."""
        return await self.async_camera_stream()

    async def async_camera_image(self) -> bytes | None:
        """Return a still image from the camera (if available)."""
        # Try to get a token-based image URL
        try:
            info = await self._client.get_camera_image_url()
            token = info.get("token")
            if token:
                return await self._client.get_camera_image(token)
        except DatronApiError as err:
            _LOGGER.debug("Error fetching camera still image: %s", err)
        return None
