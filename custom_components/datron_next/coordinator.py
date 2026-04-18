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
    SCAN_INTERVAL_AXIS,
    SCAN_INTERVAL_FAST,
    SCAN_INTERVAL_MEDIUM,
    SCAN_INTERVAL_SLOW,
)

_LOGGER = logging.getLogger(__name__)


def _directory_to_simpl_root(directory: str) -> str | None:
    """Convert a directory string from the Program payload to a SimPL root.

    Datron firmware returns network-share programs with ``directory`` as
    a raw UNC path (``\\\\SERVER\\share``). The SimPL-path equivalent
    uses the ``network:`` prefix and keeps the UNC double-backslash
    exactly as-is — e.g. ``\\\\SERVER\\share`` becomes
    ``network:\\\\SERVER\\share``. (Note: the machine may alias the
    server internally — ``\\\\REAL_NAS`` in ``directory`` can map to a
    different SimPL alias such as ``network:\\\\AliasName``. When that
    happens the derived path won't match; enumerating ``network:`` in
    the slow-coordinator defaults covers that case.)

    Already-SimPL paths are returned unchanged; Windows drive-letter
    paths return ``None``.
    """
    if not isinstance(directory, str) or not directory:
        return None

    if directory.startswith("\\\\"):
        return "network:" + directory

    head = directory.split("/", 1)[0].split("\\", 1)[0]
    if ":" in head and not (len(head) == 2 and head[0].isalpha()):
        return directory

    return None


def _derive_simpl_root(program: Any) -> str | None:
    """Given a CurrentlyLoadedProgram payload, return a SimPL folder to scan."""
    if not isinstance(program, dict):
        return None

    directory = program.get("directory")
    root = _directory_to_simpl_root(directory) if isinstance(directory, str) else None
    if root:
        return root

    # Fall back to fullName if it happens to be a full SimPL path.
    full = program.get("fullName")
    if isinstance(full, str) and full.lower().endswith(".simpl"):
        folder_part = full.rsplit("/", 1)[0].rsplit("\\", 1)[0]
        if folder_part != full:
            return _directory_to_simpl_root(folder_part)
    return None


class DatronFastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for fast-polling data (4s).

    Machine status, execution durations, sensors, notifications.
    Axis positions are handled by DatronAxisCoordinator to avoid
    blocking the fast poll — the AxisPositions endpoint is very slow
    on some Datron machines.
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
                ("compressed_air", self.client.get_compressed_air),
                ("vacuum", self.client.get_vacuum),
                ("spray_system", self.client.get_spray_system),
                ("feed_override", self.client.get_feed_override),
                ("status_light", self.client.get_status_light),
                ("notifications", self.client.get_notifications),
                ("open_dialog", self.client.get_open_dialog),
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


class DatronAxisCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for axis positions with exponential back-off.

    Dedicated coordinator because the ``AxisPositions`` endpoint on many
    Datron machines takes 15-20+ seconds during program execution, which
    would block the entire fast-poll cycle if it shared the same semaphore.

    Uses ``get_axis_positions_direct()`` which bypasses the API-client
    polling semaphore and has its own 30 s timeout.

    Back-off strategy:
    - Starts at ``SCAN_INTERVAL_AXIS`` (10 s).
    - After each consecutive failure the interval doubles, up to 5 min.
    - A single success resets the interval and failure counter.
    - Log spam is reduced: failures are logged on the 1st, 5th, and
      then every 10th consecutive failure.
    """

    _MAX_INTERVAL = 300  # 5 minutes

    _DEFAULT_AXES: dict[str, Any] = {
        "axes": {"x": 0.0, "y": 0.0, "z": 0.0, "a": 0.0, "b": 0.0, "c": 0.0}
    }

    def __init__(self, hass: HomeAssistant, client: DatronApiClient) -> None:
        """Initialize the axis coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_axis",
            update_interval=timedelta(seconds=SCAN_INTERVAL_AXIS),
        )
        self.client = client
        self._consecutive_failures: int = 0

    def _backoff_interval(self) -> timedelta:
        """Return the next poll interval based on consecutive failures."""
        secs = min(
            SCAN_INTERVAL_AXIS * (2 ** self._consecutive_failures),
            self._MAX_INTERVAL,
        )
        return timedelta(seconds=secs)

    def _should_log_failure(self) -> bool:
        """Only log on 1st, 5th, and every 10th consecutive failure."""
        n = self._consecutive_failures
        return n == 1 or n == 5 or n % 10 == 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch axis positions from the API (bypasses polling semaphore).

        Never raises ``UpdateFailed`` so the integration can always load
        even when the AxisPositions endpoint is unreachable or slow.
        Sensors will show 0.0 until a successful poll returns real data.
        """
        try:
            axes = await self.client.get_axis_positions_direct()
            if isinstance(axes, dict):
                _LOGGER.debug(
                    "[COORD] Axes: X=%.3f Y=%.3f Z=%.3f A=%.3f B=%.3f C=%.3f",
                    axes.get("x", 0), axes.get("y", 0), axes.get("z", 0),
                    axes.get("a", 0), axes.get("b", 0), axes.get("c", 0),
                )
            # Success — reset back-off
            if self._consecutive_failures > 0:
                _LOGGER.info(
                    "[COORD] Axis poll recovered after %d consecutive failures",
                    self._consecutive_failures,
                )
            self._consecutive_failures = 0
            self.update_interval = timedelta(seconds=SCAN_INTERVAL_AXIS)
            return {"axes": axes}
        except DatronAuthError as err:
            self._consecutive_failures += 1
            if self._should_log_failure():
                _LOGGER.warning("[COORD] Axis poll auth error (%d): %s", self._consecutive_failures, err)
        except DatronApiError as err:
            self._consecutive_failures += 1
            if self._should_log_failure():
                _LOGGER.warning(
                    "[COORD] Axis poll failed (%d, next retry in %ds): %s",
                    self._consecutive_failures,
                    min(SCAN_INTERVAL_AXIS * (2 ** self._consecutive_failures), self._MAX_INTERVAL),
                    err,
                )
        except Exception as err:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._should_log_failure():
                _LOGGER.warning("[COORD] Axis poll unexpected error (%d): %s", self._consecutive_failures, err)

        # Apply back-off for next cycle
        self.update_interval = self._backoff_interval()

        # Return stale data or default zeros — never raise UpdateFailed
        return self.data if self.data else self._DEFAULT_AXES


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

    def __init__(
        self,
        hass: HomeAssistant,
        client: DatronApiClient,
        extra_roots: list[str] | None = None,
    ) -> None:
        """Initialize the slow coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_slow",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SLOW),
        )
        self.client = client
        self._user_extra_roots: list[str] = list(extra_roots or [])

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch slow-polling data from the API.

        For the program list we enumerate ``machine:`` plus the root
        derived from the currently-loaded program, if any — that way the
        dropdown includes sibling programs on network shares / USB /
        samples folders without requiring the user to pre-configure
        every SimPL root prefix.
        """
        # Default roots to scan. Any that don't exist on this machine
        # will fail cleanly in enumerate_programs and be skipped.
        #   machine:  – on-machine storage
        #   network:  – network drives (one level deep lets us discover
        #               each share alias and its root .simpl files)
        #   samples:  – bundled Datron samples (if licensed)
        #   usb:      – USB-drive storage (when plugged in)
        default_roots = ["machine:", "network:", "samples:", "usb:"]

        extra_roots: list[str] = []
        try:
            current_program = await self.client.get_current_program()
            extra = _derive_simpl_root(current_program)
            if extra:
                extra_roots.append(extra)
        except DatronApiError as err:
            _LOGGER.debug("[COORD-SLOW] Could not derive current-program root: %s", err)

        seen_roots: set[str] = set()
        roots: list[str] = []
        for r in default_roots + extra_roots + self._user_extra_roots:
            if r not in seen_roots:
                seen_roots.add(r)
                roots.append(r)

        try:
            results = await asyncio.gather(
                self.client.get_machine_number(),
                self.client.get_machine_type(),
                self.client.get_software_version(),
                self.client.get_licenses(),
                self.client.get_runtime(),
                self.client.enumerate_programs(roots=roots),
                self.client.get_workpieces(),
                return_exceptions=True,
            )

            keys = [
                "machine_number", "machine_type", "software_version",
                "licenses", "runtime", "programs", "workpieces",
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
