"""Image platform for Datron NEXT integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DatronApiClient, DatronApiError
from .const import COORD_MEDIUM, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT image entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: DatronApiClient = data["client"]

    entities: list[ImageEntity] = [
        DatronWorkpieceImage(hass=hass, entry=entry, client=client),
        DatronPreviewImage(hass=hass, entry=entry, client=client),
    ]
    async_add_entities(entities)


class DatronWorkpieceImage(ImageEntity):
    """Image entity for the workpiece picture."""

    _attr_has_entity_name = True
    _attr_name = "Workpiece Image"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: DatronApiClient) -> None:
        """Initialize the workpiece image entity."""
        super().__init__(hass)
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_workpiece_image"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )
        self._cached_image: bytes | None = None

    async def async_image(self) -> bytes | None:
        """Return the workpiece image bytes."""
        try:
            image_data = await self._client.get_workpiece_image()
            if isinstance(image_data, bytes) and len(image_data) > 0:
                self._cached_image = image_data
                self._attr_image_last_updated = datetime.now()
                return image_data
        except DatronApiError as err:
            _LOGGER.debug("Error fetching workpiece image: %s", err)
        return self._cached_image


class DatronPreviewImage(ImageEntity):
    """Image entity for the program preview picture."""

    _attr_has_entity_name = True
    _attr_name = "Program Preview Image"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: DatronApiClient) -> None:
        """Initialize the preview image entity."""
        super().__init__(hass)
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_preview_image"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Datron",
            model="M8Cube",
            sw_version="NEXT",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )
        self._cached_image: bytes | None = None

    async def async_image(self) -> bytes | None:
        """Return the program preview image bytes."""
        try:
            image_data = await self._client.get_program_preview_image()
            if isinstance(image_data, bytes) and len(image_data) > 0:
                self._cached_image = image_data
                self._attr_image_last_updated = datetime.now()
                return image_data
        except DatronApiError as err:
            _LOGGER.debug("Error fetching preview image: %s", err)
        return self._cached_image
