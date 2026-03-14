"""The Datron NEXT integration."""

from __future__ import annotations

import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

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
]

type DatronConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Set up Datron NEXT from a config entry."""
    host = entry.data[CONF_HOST]
    token = entry.data[CONF_TOKEN]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    # Create a dedicated aiohttp session for the Datron machine.
    # The embedded HTTP server has very limited connection capacity,
    # so we restrict to 2 simultaneous TCP connections to this host.
    connector = aiohttp.TCPConnector(limit_per_host=2, force_close=True)
    session = aiohttp.ClientSession(connector=connector)
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
        "session": session,
        COORD_FAST: fast_coordinator,
        COORD_MEDIUM: medium_coordinator,
        COORD_SLOW: slow_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DatronConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        # Close the dedicated aiohttp session
        session: aiohttp.ClientSession | None = data.get("session")
        if session and not session.closed:
            await session.close()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
