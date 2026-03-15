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
        import time
        poll_start = time.monotonic()
        try:
            _LOGGER.debug("[COORD] Fast poll: starting all endpoints")
            endpoints = [
                ("machine_status", self.client.get_machine_status),
                ("execution", self.client.get_execution_durations),
                ("axes", self.client.get_axis_positions),
                ("compressed_air", self.client.get_compressed_air),
                ("vacuum", self.client.get_vacuum),
                ("spray_system", self.client.get_spray_system),
                ("feed_override", self.client.get_feed_override),
                ("status_light", self.client.get_status_light),
                ("notifications", self.client.get_notifications),
            ]
            tasks = []
            for key, func in endpoints:
                _LOGGER.debug("[COORD] Fast poll: scheduling %s", key)
                tasks.append(func())
            results = await asyncio.gather(*tasks, return_exceptions=True)

            keys = [k for k, _ in endpoints]
            data: dict[str, Any] = {}
            for key, result in zip(keys, results):
                if isinstance(result, DatronAuthError):
                    _LOGGER.error("[COORD] Fast poll: Auth error for %s: %s", key, result)
                    raise UpdateFailed(f"Authentication error: {result}") from result
                if isinstance(result, Exception):
                    _LOGGER.warning("[COORD] Fast poll: Failed to fetch %s: %s", key, result)
                    data[key] = self.data.get(key) if self.data else None
                else:
                    _LOGGER.debug("[COORD] Fast poll: Success for %s", key)
                    data[key] = result

            # Log raw response structure on first successful fetch
            if not self.data:
                for key in keys:
                    val = data.get(key)
                    if isinstance(val, dict):
                        _LOGGER.debug("FAST %s keys: %s", key, list(val.keys()))
                    elif isinstance(val, list):
                        _LOGGER.debug("FAST %s: list[%d]", key, len(val))
                    else:
                        _LOGGER.debug("FAST %s: %s (%s)", key, val, type(val).__name__)

            elapsed = time.monotonic() - poll_start
            _LOGGER.debug("[COORD] Fast poll: finished all endpoints in %.3fs", elapsed)
            return data
        except DatronAuthError as err:
            _LOGGER.error("[COORD] Fast poll: Auth error: %s", err)
            raise UpdateFailed(f"Authentication error: {err}") from err
        except DatronApiError as err:
            _LOGGER.error("[COORD] Fast poll: API error: %s", err)
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

            # Log raw response structure on first successful fetch
            if not self.data:
                for key in keys:
                    val = data.get(key)
                    if isinstance(val, dict):
                        _LOGGER.debug("MEDIUM %s keys: %s", key, list(val.keys()))
                    elif isinstance(val, list):
                        _LOGGER.debug("MEDIUM %s: list[%d]", key, len(val))
                    else:
                        _LOGGER.debug("MEDIUM %s: %s (%s)", key, val, type(val).__name__)

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

            # Log raw response structure on first successful fetch
            if not self.data:
                for key in keys:
                    val = data.get(key)
                    if isinstance(val, dict):
                        _LOGGER.debug("SLOW %s keys: %s", key, list(val.keys()))
                    elif isinstance(val, list):
                        _LOGGER.debug("SLOW %s: list[%d]", key, len(val))
                    else:
                        _LOGGER.debug("SLOW %s: %s (%s)", key, val, type(val).__name__)

            return data
        except DatronAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except DatronApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
