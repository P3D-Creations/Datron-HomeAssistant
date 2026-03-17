"""Image platform for Datron NEXT integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import DatronApiClient, DatronApiError
from .const import COORD_MEDIUM, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return shared DeviceInfo for all image entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Datron",
        model="M8Cube",
        sw_version="NEXT",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Datron NEXT image entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: DatronApiClient = data["client"]
    medium_coordinator: DataUpdateCoordinator = data[COORD_MEDIUM]

    entities: list[ImageEntity] = [
        DatronWorkpieceImage(hass=hass, entry=entry, client=client),
        DatronPreviewImage(hass=hass, entry=entry, client=client),
        DatronToolImage(
            hass=hass,
            entry=entry,
            client=client,
            coordinator=medium_coordinator,
        ),
    ]
    async_add_entities(entities)


# ── Workpiece Image ──────────────────────────────────────────


class DatronWorkpieceImage(ImageEntity):
    """Image entity for the workpiece picture."""

    _attr_has_entity_name = True
    _attr_name = "Workpiece Image"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DatronApiClient,
    ) -> None:
        """Initialize the workpiece image entity."""
        super().__init__(hass)
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_workpiece_image"
        self._attr_device_info = _device_info(entry)
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


# ── Program Preview Image ────────────────────────────────────


class DatronPreviewImage(ImageEntity):
    """Image entity for the program preview picture.

    Tries the authenticated /Image/ProgramPreviewImage endpoint first.
    If the API returns a URL (from /Runtime/PreviewImage) with a public
    token, that path will also be attempted as a fallback.
    """

    _attr_has_entity_name = True
    _attr_name = "Program Preview Image"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DatronApiClient,
    ) -> None:
        """Initialize the preview image entity."""
        super().__init__(hass)
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_preview_image"
        self._attr_device_info = _device_info(entry)
        self._cached_image: bytes | None = None

    def _make_absolute(self, url: str) -> str:
        """Ensure a URL is absolute by prepending the machine host if needed."""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        prefix = f"http://{self._client._host}:{self._client._port}"
        return f"{prefix}{url}" if url.startswith("/") else f"{prefix}/{url}"

    async def async_image(self) -> bytes | None:
        """Return the program preview image bytes.

        Two-step flow:
          1. GET /Runtime/PreviewImage (bearer auth) → {"url": "/api/v2.0/Image/ProgramPreviewImage?token=..."}
          2. GET <absolute url> (no auth, token in query string) → JPEG bytes

        The /Image/ProgramPreviewImage endpoint requires a token query param
        (it is a public endpoint) so we never call it without one.
        Returns None / cached image if no program is loaded (API returns 204).
        """
        try:
            # Step 1: get the token-based URL from the runtime endpoint
            url_info = await self._client.get_preview_image_url()
            if url_info is None:
                # 204 — no program loaded
                _LOGGER.debug("No preview image available (no program loaded)")
                return self._cached_image

            image_url: str | None = None
            if isinstance(url_info, dict):
                # Confirmed response key: {"url": "..."}
                image_url = url_info.get("url") or url_info.get("imageUrl") or url_info.get("fullName")
            elif isinstance(url_info, str) and url_info:
                image_url = url_info

            if not image_url:
                _LOGGER.debug("Unexpected preview image URL response: %s", url_info)
                return self._cached_image

            # Step 2: fetch the image bytes via the absolute public URL
            abs_url = self._make_absolute(image_url)
            _LOGGER.debug("Fetching preview image from: %s", abs_url)
            image_data = await self._client.fetch_image_url(abs_url)
            if isinstance(image_data, bytes) and len(image_data) > 0:
                self._cached_image = image_data
                self._attr_image_last_updated = datetime.now()
                return image_data

        except DatronApiError as err:
            _LOGGER.debug("Error fetching preview image: %s", err)
        return self._cached_image


# ── Tool In Spindle Image ────────────────────────────────────


class DatronToolImage(CoordinatorEntity, ImageEntity):
    """Image entity for the tool currently loaded in the spindle.

    The medium coordinator already polls /Tool/ToolInSpindle and returns
    a response that includes an ``imageUrl`` field.  This entity extracts
    the URL (which contains a public-access token) and fetches the actual
    image binary from the /Image/Tool endpoint.
    """

    _attr_has_entity_name = True
    _attr_name = "Tool In Spindle Image"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DatronApiClient,
        coordinator: DataUpdateCoordinator,
    ) -> None:
        """Initialize the tool image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_tool_spindle_image"
        self._attr_device_info = _device_info(entry)
        self._cached_image: bytes | None = None
        self._last_image_url: str | None = None

    # -- helpers --

    def _get_image_url(self) -> str | None:
        """Extract imageUrl from the coordinator's tool_spindle data."""
        if not self.coordinator.data:
            return None
        tool_data = self.coordinator.data.get("tool_spindle")
        if isinstance(tool_data, dict):
            return tool_data.get("imageUrl")
        return None

    @staticmethod
    def _extract_token(image_url: str) -> str | None:
        """Parse the ``token`` query param from an imageUrl."""
        try:
            parsed = urlparse(image_url)
            tokens = parse_qs(parsed.query).get("token")
            return tokens[0] if tokens else None
        except Exception:  # noqa: BLE001
            return None

    # -- HA callbacks --

    @callback
    def _handle_coordinator_update(self) -> None:
        """React to coordinator data updates — mark image stale if URL changed."""
        new_url = self._get_image_url()
        if new_url and new_url != self._last_image_url:
            self._last_image_url = new_url
            self._attr_image_last_updated = datetime.now()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return the tool image bytes."""
        def _make_absolute(url: str) -> str:
            if url.startswith("http://") or url.startswith("https://"):
                return url
            host = getattr(self._client, "_host", None)
            port = getattr(self._client, "_port", 80)
            if url.startswith("/"):
                return f"http://{host}:{port}{url}"
            return f"http://{host}:{port}/{url}"

        image_url = self._get_image_url()
        if not image_url:
            _LOGGER.debug("No imageUrl in tool spindle data — trying direct fetch")
            return await self._fetch_direct()

        try:
            abs_url = _make_absolute(image_url)
            image_data = await self._client.fetch_image_url(abs_url)
            if isinstance(image_data, bytes) and len(image_data) > 0:
                self._cached_image = image_data
                self._last_image_url = image_url
                self._attr_image_last_updated = datetime.now()
                return image_data
        except DatronApiError as err:
            _LOGGER.debug("Public imageUrl fetch failed: %s — trying direct", err)

        # Fallback: extract token and call get_tool_image()
        token = self._extract_token(image_url) if image_url else None
        return await self._fetch_direct(token)

    async def _fetch_direct(self, token: str | None = None) -> bytes | None:
        """Fetch tool image via the API (bearer auth + optional token)."""
        try:
            image_data = await self._client.get_tool_image(token=token)
            if isinstance(image_data, bytes) and len(image_data) > 0:
                self._cached_image = image_data
                self._attr_image_last_updated = datetime.now()
                return image_data
        except DatronApiError as err:
            _LOGGER.debug("Error fetching tool image: %s", err)
        return self._cached_image
