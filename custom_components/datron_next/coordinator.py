"""Data update coordinators for Datron NEXT integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DatronApiClient, DatronApiError, DatronAuthError
from .const import (
    DOMAIN,
    SCAN_INTERVAL_FAST,
    SCAN_INTERVAL_MEDIUM,
    SCAN_INTERVAL_SLOW,
)

_LOGGER = logging.getLogger(__name__)


class DatronFastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for fast-polling data (10s).

    Machine status, execution durations, axis positions, sensors, notifications.
    """

    def __init__(self, hass: HomeAssistant, client: DatronApiClient) -> None:
        """Initialize the fast coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_fast",
            update_interval=timedelta(seconds=SCAN_INTERVAL_FAST),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch fast-polling data from the API."""
        try:
            results = await asyncio.gather(
                self.client.get_machine_status(),
                self.client.get_execution_durations(),
                self.client.get_axis_positions(),
                self.client.get_compressed_air(),
                self.client.get_vacuum(),
                self.client.get_spray_system(),
                self.client.get_feed_override(),
                self.client.get_status_light(),
                self.client.get_notifications(),
                return_exceptions=True,
            )

            keys = [
                "machine_status", "execution", "axes", "compressed_air",
                "vacuum", "spray_system", "feed_override", "status_light",
                "notifications",
            ]
            data: dict[str, Any] = {}
            for key, result in zip(keys, results):
                if isinstance(result, DatronAuthError):
                    raise UpdateFailed(f"Authentication error: {result}") from result
                if isinstance(result, Exception):
                    _LOGGER.warning("Failed to fetch %s: %s", key, result)
                    data[key] = self.data.get(key) if self.data else None
                else:
                    data[key] = result
            return data
        except DatronAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except DatronApiError as err:
            raise UpdateFailed(f"API error: {err}") from err


class DatronMediumCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for medium-polling data (60s).

    Tool info, current program, workpiece info.
    """

    def __init__(self, hass: HomeAssistant, client: DatronApiClient) -> None:
        """Initialize the medium coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_medium",
            update_interval=timedelta(seconds=SCAN_INTERVAL_MEDIUM),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch medium-polling data from the API."""
        try:
            results = await asyncio.gather(
                self.client.get_current_program(),
                self.client.get_tool_in_spindle(),
                self.client.get_tools_in_changer(),
                self.client.get_tools_in_warehouse(),
                return_exceptions=True,
            )

            keys = ["program", "tool_spindle", "tools_changer", "tools_warehouse"]
            data: dict[str, Any] = {}
            for key, result in zip(keys, results):
                if isinstance(result, DatronAuthError):
                    raise UpdateFailed(f"Authentication error: {result}") from result
                if isinstance(result, Exception):
                    _LOGGER.warning("Failed to fetch %s: %s", key, result)
                    data[key] = self.data.get(key) if self.data else None
                else:
                    data[key] = result
            return data
        except DatronAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except DatronApiError as err:
            raise UpdateFailed(f"API error: {err}") from err


class DatronSlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for slow-polling data (1hr).

    Machine number, type, software version, licenses, runtime hours.
    """

    def __init__(self, hass: HomeAssistant, client: DatronApiClient) -> None:
        """Initialize the slow coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_slow",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SLOW),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch slow-polling data from the API."""
        try:
            results = await asyncio.gather(
                self.client.get_machine_number(),
                self.client.get_machine_type(),
                self.client.get_software_version(),
                self.client.get_licenses(),
                self.client.get_runtime(),
                return_exceptions=True,
            )

            keys = [
                "machine_number", "machine_type", "software_version",
                "licenses", "runtime",
            ]
            data: dict[str, Any] = {}
            for key, result in zip(keys, results):
                if isinstance(result, DatronAuthError):
                    raise UpdateFailed(f"Authentication error: {result}") from result
                if isinstance(result, Exception):
                    _LOGGER.warning("Failed to fetch %s: %s", key, result)
                    data[key] = self.data.get(key) if self.data else None
                else:
                    data[key] = result
            return data
        except DatronAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except DatronApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
