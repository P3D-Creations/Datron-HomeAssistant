"""Data update coordinators for Datron NEXT integration."""

from __future__ import annotations

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
            machine_status = await self.client.get_machine_status()
            execution = await self.client.get_execution_durations()
            axes = await self.client.get_axis_positions()
            air = await self.client.get_compressed_air()
            vacuum = await self.client.get_vacuum()
            spray = await self.client.get_spray_system()
            feed = await self.client.get_feed_override()
            light = await self.client.get_status_light()
            notifications = await self.client.get_notifications()

            return {
                "machine_status": machine_status,
                "execution": execution,
                "axes": axes,
                "compressed_air": air,
                "vacuum": vacuum,
                "spray_system": spray,
                "feed_override": feed,
                "status_light": light,
                "notifications": notifications,
            }
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
            program = await self.client.get_current_program()
            tool_spindle = await self.client.get_tool_in_spindle()
            tools_changer = await self.client.get_tools_in_changer()
            tools_warehouse = await self.client.get_tools_in_warehouse()

            return {
                "program": program,
                "tool_spindle": tool_spindle,
                "tools_changer": tools_changer,
                "tools_warehouse": tools_warehouse,
            }
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
            machine_number = await self.client.get_machine_number()
            machine_type = await self.client.get_machine_type()
            software_version = await self.client.get_software_version()
            licenses = await self.client.get_licenses()
            runtime = await self.client.get_runtime()

            return {
                "machine_number": machine_number,
                "machine_type": machine_type,
                "software_version": software_version,
                "licenses": licenses,
                "runtime": runtime,
            }
        except DatronAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except DatronApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
