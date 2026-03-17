"""The Datron NEXT integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DatronApiClient
from .const import CONF_TOKEN, COORD_FAST, COORD_MEDIUM, COORD_SLOW, DEFAULT_PORT, DOMAIN
from .coordinator import (
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
]

type DatronConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Set up Datron NEXT from a config entry."""
    host = entry.data[CONF_HOST]
    token = entry.data[CONF_TOKEN]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    session = async_get_clientsession(hass)
    client = DatronApiClient(host=host, token=token, port=port, session=session)

    # Create coordinators
    fast_coordinator = DatronFastCoordinator(hass, client)
    medium_coordinator = DatronMediumCoordinator(hass, client)
    slow_coordinator = DatronSlowCoordinator(hass, client)

    # Fetch initial data
    await fast_coordinator.async_config_entry_first_refresh()
    await medium_coordinator.async_config_entry_first_refresh()
    await slow_coordinator.async_config_entry_first_refresh()

    # Store coordinators and client in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        COORD_FAST: fast_coordinator,
        COORD_MEDIUM: medium_coordinator,
        COORD_SLOW: slow_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
