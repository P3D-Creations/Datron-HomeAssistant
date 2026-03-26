"""Advanced execution sensors for Datron NEXT integration.

Provides three components:

KnownCycleTimeStore
    Persistent LRU store mapping program fullName → last completed cycle
    duration.  Survives HA restarts via ``homeassistant.helpers.storage.Store``.

DatronEstimatedRemainingSensor
    Corrects the Datron API's non-linear remaining-time value.  If a known
    cycle time exists for the current program, it is used as the estimate
    (``known_total – elapsed``).  Otherwise, a dynamic OLS regression on a
    rolling window of remaining-time samples is used.

DatronCycleHistorySensor
    Detects cycle start / complete / interrupted events from execution state
    transitions and persists a rolling log of the last N cycle records.
    On successful uninterrupted completion (≥ 2 min), the elapsed time is
    recorded in the ``KnownCycleTimeStore`` keyed by program name.
"""

from __future__ import annotations

import logging
import re
import time as _time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ── Time parsing ──────────────────────────────────────────────────────────────

# Matches .NET TimeSpan: [d.]hh:mm:ss[.fffffff]
_TIMESPAN_RE = re.compile(
    r"^(?:(?P<days>\d+)\.)?(?P<hours>\d{1,2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})"
    r"(?:\.(?P<frac>\d+))?$"
)


def _parse_timespan(ts: Any) -> float | None:
    """Parse a .NET-style TimeSpan (or plain number) to total seconds.

    Handles:
      - ``"00:01:23"``  →  83.0
      - ``"1.02:03:04.567"``  →  93784.567
      - plain int/float passed through as-is
    """
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    m = _TIMESPAN_RE.match(str(ts).strip())
    if not m:
        return None
    days = int(m.group("days") or 0)
    hours = int(m.group("hours"))
    minutes = int(m.group("minutes"))
    seconds = int(m.group("seconds"))
    frac = float(f"0.{m.group('frac')}") if m.group("frac") else 0.0
    return days * 86400 + hours * 3600 + minutes * 60 + seconds + frac


def _fmt_duration(seconds: float | None) -> str:
    """Format seconds as ``HH:MM:SS`` (or ``--:--:--`` if None)."""
    if seconds is None or seconds < 0:
        return "--:--:--"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Datron",
        model="M8Cube",
        sw_version="NEXT",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )


# ── Known Cycle Time Store ────────────────────────────────────────────────────

_KNOWN_TIMES_KEY = "datron_next_known_cycle_times"
_KNOWN_TIMES_VERSION = 1
_MAX_KNOWN_PROGRAMS = 12
_MIN_RECORDABLE_DURATION_S = 120.0  # 2 min — shorter runs are admin/probing


class KnownCycleTimeStore:
    """Persistent LRU store: program fullName → last completed cycle duration.

    Only stores times from **completed, uninterrupted** cycles that ran for
    at least ``_MIN_RECORDABLE_DURATION_S`` (2 min).  This excludes short
    administrative operations like probing, parking, tool checks, etc.

    When the store exceeds ``_MAX_KNOWN_PROGRAMS`` entries, the oldest
    (by ``recorded_at``) are evicted.

    Administrative / non-production cycles are excluded by:
    - Duration < 2 min (probing, tool checks, parking sequences)
    - Empty / null program name (no program loaded)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, _KNOWN_TIMES_VERSION, _KNOWN_TIMES_KEY)
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False

    async def async_load(self) -> None:
        """Load persisted known cycle times from HA storage."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._data = stored.get("programs", {})
        self._loaded = True
        _LOGGER.debug(
            "Known cycle times loaded: %d programs", len(self._data)
        )

    @property
    def loaded(self) -> bool:
        """Whether the store has been loaded from disk."""
        return self._loaded

    @property
    def programs(self) -> dict[str, dict[str, Any]]:
        """Return a copy of all stored programs and their known times."""
        return dict(self._data)

    def get(self, program_name: str) -> float | None:
        """Return the known cycle duration in seconds, or None."""
        entry = self._data.get(program_name)
        return entry["duration_s"] if entry else None

    def record(self, program_name: str, duration_s: float) -> None:
        """Record a completed cycle time for a program.

        Ignores calls where:
        - ``program_name`` is empty / None
        - ``duration_s`` < 2 min (admin / probing operations)
        """
        if not program_name or duration_s < _MIN_RECORDABLE_DURATION_S:
            _LOGGER.debug(
                "Skipping known-time record: program=%r, duration=%.0fs (min %.0fs)",
                program_name, duration_s, _MIN_RECORDABLE_DURATION_S,
            )
            return

        prev = self._data.get(program_name)
        cycle_count = (prev.get("cycle_count", 0) if prev else 0) + 1

        self._data[program_name] = {
            "duration_s": round(duration_s, 1),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "cycle_count": cycle_count,
        }

        # LRU eviction — remove oldest entries if over the limit
        while len(self._data) > _MAX_KNOWN_PROGRAMS:
            oldest_key = min(
                self._data,
                key=lambda k: self._data[k].get("recorded_at", ""),
            )
            _LOGGER.debug("Evicting oldest known time: '%s'", oldest_key)
            del self._data[oldest_key]

        self._hass.async_create_task(self._async_save())
        _LOGGER.info(
            "Known cycle time recorded: '%s' = %.0fs (%s) — cycle #%d",
            program_name, duration_s, _fmt_duration(duration_s), cycle_count,
        )

    async def _async_save(self) -> None:
        """Persist current data to HA storage."""
        await self._store.async_save({"programs": self._data})


# ── Solution 1 — Estimated Remaining Time ────────────────────────────────────


class DatronEstimatedRemainingSensor(CoordinatorEntity, SensorEntity):
    """Corrected remaining-time sensor using a rolling-window speed factor.

    The Datron API's ``programmLeftTime`` often counts down more slowly than
    wall-clock time (sometimes as low as 50–70% speed) and the factor is not
    constant.  This sensor:

    1. Collects (monotonic_timestamp, remaining_seconds) samples on every
       coordinator update.
    2. Prunes samples older than ``WINDOW_SECONDS``.
    3. With ≥ ``MIN_SAMPLES`` points, fits an ordinary least-squares line
       to estimate the *rate* at which remaining decreases per real second.
    4. Divides current remaining by |rate| to obtain a corrected estimate.
    5. Clamps the implied speed factor to (MIN_SPEED, 1.0] to avoid
       nonsensical results.

    Falls back to the raw API value when there is insufficient data, the
    program is paused, or the rate cannot be computed reliably.
    """

    _attr_has_entity_name = True
    _attr_name = "Estimated Remaining Time"
    _attr_icon = "mdi:timer-sand"
    # State is a human-readable HH:MM:SS string — no unit or numeric state class

    # Tunable parameters
    WINDOW_SECONDS: float = 300.0   # 5-minute rolling window
    MIN_SAMPLES: int = 15           # minimum points before regression is used
    MIN_SPEED: float = 0.05         # below this the machine is considered paused
    MAX_SPEED: float = 1.0          # remaining cannot shrink faster than elapsed

    # Known-time divergence detection
    DIVERGENCE_LOW: float = 0.3     # known < 30% of machine → program shortened
    DIVERGENCE_HIGH: float = 3.0    # known > 300% of machine → program lengthened
    DIVERGENCE_HOLD_S: float = 180.0  # 3 min sustained before invalidating

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        medium_coordinator: DataUpdateCoordinator | None = None,
        known_times: KnownCycleTimeStore | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_estimated_remaining"
        self._attr_device_info = _device_info(entry)

        self._medium_coordinator = medium_coordinator
        self._known_times = known_times

        # Rolling window: deque of (monotonic_time, remaining_seconds)
        self._samples: deque[tuple[float, float]] = deque()
        self._speed_factor: float | None = None
        self._estimated_s: float | None = None
        self._raw_remaining_s: float | None = None
        self._last_machine_state: str | None = None
        self._estimate_source: str | None = None  # "known", "dynamic", "raw"
        self._known_total_s: float | None = None

        # Divergence tracking: when known estimate strays far from machine
        # estimate for DIVERGENCE_HOLD_S, we invalidate the known time.
        self._divergence_start: float | None = None  # monotonic time divergence began
        self._known_invalidated: bool = False  # set True when divergence confirmed

    # ------------------------------------------------------------------
    # Internal helpers

    def _prune_window(self, now: float) -> None:
        """Remove samples older than WINDOW_SECONDS."""
        cutoff = now - self.WINDOW_SECONDS
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def _get_current_program_name(self) -> str | None:
        """Read the current program fullName from the medium coordinator."""
        if not self._medium_coordinator or not self._medium_coordinator.data:
            return None
        program = self._medium_coordinator.data.get("program")
        if not isinstance(program, dict):
            return None
        return program.get("fullName") or program.get("name") or None

    def _try_known_estimate(self, elapsed_s: float | None) -> float | None:
        """Return remaining seconds based on known cycle time, or None.

        Uses ``known_total_duration − elapsed`` for programs that have a
        stored cycle time in the ``KnownCycleTimeStore``.

        Returns ``None`` when:
        - No elapsed data / no store / no matching program
        - Known time has been invalidated for this cycle (divergence detected)
        - Elapsed exceeds the stored total (program ran longer than expected)
        """
        if elapsed_s is None or not self._known_times or not self._known_times.loaded:
            return None

        # Already invalidated for this cycle — skip
        if self._known_invalidated:
            return None

        program_name = self._get_current_program_name()
        if not program_name:
            return None

        known_total = self._known_times.get(program_name)
        if known_total is None:
            self._known_total_s = None
            return None

        self._known_total_s = known_total

        # Elapsed exceeded stored total → program is longer now
        if elapsed_s > known_total:
            _LOGGER.info(
                "Known cycle time exceeded (elapsed %.0fs > stored %.0fs) "
                "for '%s' — falling back to dynamic estimate",
                elapsed_s, known_total, program_name,
            )
            self._known_invalidated = True
            return None

        return known_total - elapsed_s

    def _check_known_divergence(
        self, known_remaining: float, raw_remaining_s: float | None,
    ) -> bool:
        """Return True if the known estimate has diverged from the machine.

        Compares known remaining to the machine's raw ``programmLeftTime``.
        If the ratio is outside (DIVERGENCE_LOW, DIVERGENCE_HIGH) for longer
        than DIVERGENCE_HOLD_S, the known time is considered stale (the
        program was likely edited) and should be abandoned.
        """
        if raw_remaining_s is None or raw_remaining_s < 30:
            # Machine estimate too small / unavailable — can't compare
            self._divergence_start = None
            return False

        if known_remaining < 30:
            # Our estimate is nearly zero — divergence check not meaningful;
            # the exceeded-total check in _try_known_estimate handles this.
            self._divergence_start = None
            return False

        ratio = known_remaining / raw_remaining_s

        if ratio < self.DIVERGENCE_LOW or ratio > self.DIVERGENCE_HIGH:
            now = _time.monotonic()
            if self._divergence_start is None:
                self._divergence_start = now
                _LOGGER.debug(
                    "Known-time divergence detected: ratio=%.2f "
                    "(known=%.0fs, machine=%.0fs) — watching",
                    ratio, known_remaining, raw_remaining_s,
                )
            elif now - self._divergence_start >= self.DIVERGENCE_HOLD_S:
                _LOGGER.info(
                    "Known-time divergence sustained for %.0fs "
                    "(ratio=%.2f, known=%.0fs, machine=%.0fs) "
                    "— invalidating stored time, falling back to dynamic",
                    now - self._divergence_start,
                    ratio, known_remaining, raw_remaining_s,
                )
                return True
        else:
            # Ratio within bounds — reset
            if self._divergence_start is not None:
                _LOGGER.debug("Known-time divergence resolved (ratio=%.2f)", ratio)
            self._divergence_start = None

        return False

    @staticmethod
    def _ols_slope(samples: list[tuple[float, float]]) -> float | None:
        """Ordinary least-squares slope for a list of (x, y) pairs.

        Returns None if the x-variance is effectively zero (all timestamps
        are identical — can happen on first few polls).
        """
        n = len(samples)
        if n < 2:
            return None
        sx = sum(x for x, _ in samples)
        sy = sum(y for _, y in samples)
        sxx = sum(x * x for x, _ in samples)
        sxy = sum(x * y for x, y in samples)
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-9:
            return None
        return (n * sxy - sx * sy) / denom

    def _compute_estimate(self, remaining_s: float, machine_state: str | None) -> None:
        """Recompute speed factor and estimated remaining from current samples."""

        # Don't update sample set when paused — it would corrupt the regression
        is_running = machine_state in ("Running",)

        now = _time.monotonic()
        if is_running:
            self._prune_window(now)
            self._samples.append((now, remaining_s))

        samples = list(self._samples)
        if len(samples) < self.MIN_SAMPLES:
            # Insufficient data — use raw value
            self._speed_factor = None
            self._estimated_s = remaining_s
            return

        slope = self._ols_slope(samples)

        # Slope should be negative (remaining decreasing).
        # Clamp the absolute value to (MIN_SPEED, MAX_SPEED].
        if slope is None or slope >= -self.MIN_SPEED * 0.5:
            # Non-negative or near-zero slope → machine paused or just started
            self._speed_factor = None
            self._estimated_s = remaining_s
            return

        speed = min(abs(slope), self.MAX_SPEED)
        speed = max(speed, self.MIN_SPEED)
        self._speed_factor = round(speed, 4)
        self._estimated_s = remaining_s / speed

    # ------------------------------------------------------------------
    # HA callbacks

    @callback
    def _handle_coordinator_update(self) -> None:
        data: dict[str, Any] = self.coordinator.data or {}
        exec_data: dict | None = data.get("execution")
        machine_status: dict | None = data.get("machine_status")

        remaining_raw = (
            exec_data.get("programmLeftTime") if isinstance(exec_data, dict) else None
        )
        elapsed_raw = (
            exec_data.get("programExecutionTime") if isinstance(exec_data, dict) else None
        )
        machine_state = (
            machine_status.get("executionState") if isinstance(machine_status, dict) else None
        )
        # executionState is an int enum — map to string name
        machine_state = _EXEC_STATE_MAP.get(machine_state, machine_state)

        remaining_s = _parse_timespan(remaining_raw)
        elapsed_s = _parse_timespan(elapsed_raw)
        self._raw_remaining_s = remaining_s

        # ── Strategy 1: Known cycle time (most accurate for repeated programs)
        known_remaining = self._try_known_estimate(elapsed_s)

        # Check whether the known estimate has been diverging from the
        # machine's own estimate long enough to suggest the program changed.
        if known_remaining is not None and self._check_known_divergence(
            known_remaining, remaining_s,
        ):
            self._known_invalidated = True
            known_remaining = None  # fall through to dynamic

        if known_remaining is not None:
            # Keep feeding the OLS window so a fallback is immediately ready
            # when/if the known time gets invalidated.
            if remaining_s is not None:
                self._compute_estimate(remaining_s, machine_state)
            # Override _estimated_s with the known-time value (compute_estimate
            # writes to _estimated_s as a side-effect, so this must come after).
            self._estimated_s = known_remaining
            self._estimate_source = "known"
        elif remaining_s is not None:
            # ── Strategy 2: Dynamic OLS estimate (for new/unknown programs)
            self._compute_estimate(remaining_s, machine_state)
            self._estimate_source = (
                "dynamic" if self._speed_factor is not None else "raw"
            )
        else:
            # No program running / no data
            self._samples.clear()
            self._speed_factor = None
            self._estimated_s = None
            self._estimate_source = None
            self._known_total_s = None
            self._divergence_start = None
            self._known_invalidated = False

        self._last_machine_state = machine_state
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Return estimated remaining time as HH:MM:SS, or None if no program is running."""
        if self._estimated_s is None:
            return None
        return _fmt_duration(self._estimated_s)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        program_name = self._get_current_program_name()
        return {
            "estimate_source": self._estimate_source,
            "estimated_remaining": _fmt_duration(self._estimated_s),
            "estimated_remaining_s": (
                round(self._estimated_s, 1) if self._estimated_s is not None else None
            ),
            "raw_remaining": _fmt_duration(self._raw_remaining_s),
            "raw_remaining_s": (
                round(self._raw_remaining_s, 1) if self._raw_remaining_s is not None else None
            ),
            "known_cycle_time": _fmt_duration(self._known_total_s),
            "known_cycle_time_s": (
                round(self._known_total_s, 1) if self._known_total_s is not None else None
            ),
            "known_invalidated": self._known_invalidated,
            "program_name": program_name,
            "speed_factor": self._speed_factor,
            "sample_count": len(self._samples),
            "window_seconds": self.WINDOW_SECONDS,
        }


# ── Solution 2 — Cycle History Log ───────────────────────────────────────────

_STORE_KEY = "datron_next_cycle_history"
_STORE_VERSION = 1
_MAX_CYCLES = 10

# .NET int enum → string for MachineExecutionState
_EXEC_STATE_MAP: dict[int, str] = {
    0: "Init",
    1: "Preparing",
    2: "Idle",
    3: "Running",
    4: "Pause",
    5: "Manual",
    6: "Aborting",
    7: "Aborted",
    8: "Transient",
    9: "WaitingForUserInput",
}

_TERMINAL_STATES = {"Idle", "Aborted", "Aborting", "Init", "Manual"}
_PAUSE_STATES = {"Pause", "WaitingForUserInput"}


class DatronCycleHistorySensor(CoordinatorEntity, SensorEntity):
    """Tracks machining cycle history with persistence across HA restarts.

    Lifecycle detection rules
    ─────────────────────────
    **Cycle start** — machine state transitions TO ``Running`` AND elapsed is
    small (< START_THRESHOLD_S), which identifies it as the beginning of a
    new cycle rather than a resume from pause.

    **Cycle complete** — machine state leaves ``Running`` (to a terminal state)
    AND progress ≥ COMPLETE_THRESHOLD (99%).

    **Cycle interrupted** — machine state leaves ``Running`` to a terminal
    state AND progress < COMPLETE_THRESHOLD.  Also fires if elapsed suddenly
    resets while Running (a new cycle was started before the old one ended).

    **Pause** — transitions to ``Pause``/``WaitingForUserInput`` do NOT end
    the cycle; elapsed continues to be tracked against the running total.

    Persistence
    ───────────
    History is written to ``<ha_config>/.storage/datron_next_cycle_history``
    via ``homeassistant.helpers.storage.Store`` on every cycle completion /
    interruption event.
    """

    _attr_has_entity_name = True
    _attr_name = "Cycle History"
    _attr_icon = "mdi:history"
    _attr_state_class = SensorStateClass.MEASUREMENT

    START_THRESHOLD_S: float = 15.0    # elapsed < this → fresh cycle start
    COMPLETE_THRESHOLD: float = 0.99   # progress fraction for "completed"
    MAX_CYCLES: int = _MAX_CYCLES

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        medium_coordinator: DataUpdateCoordinator | None = None,
        known_times: KnownCycleTimeStore | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._attr_unique_id = f"{entry.entry_id}_cycle_history"
        self._attr_device_info = _device_info(entry)

        self._medium_coordinator = medium_coordinator
        self._known_times = known_times

        self._store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
        self._history: list[dict[str, Any]] = []   # persisted records
        self._loaded: bool = False  # has the store been read yet?

        # In-progress cycle state
        self._cycle_active: bool = False
        self._cycle_start_wall: str | None = None  # ISO timestamp
        self._cycle_program_name: str | None = None  # snapshot at cycle start
        self._last_elapsed_s: float | None = None
        self._last_machine_state: str | None = None
        self._last_progress: float = 0.0

    # ------------------------------------------------------------------
    # Store helpers

    async def async_load_history(self) -> None:
        """Load persisted history from HA storage (call once at setup)."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._history = stored.get("cycles", [])
            _LOGGER.debug(
                "Cycle history loaded: %d records", len(self._history)
            )
        self._loaded = True

    async def _async_save_history(self) -> None:
        """Persist current history to HA storage."""
        await self._store.async_save({"cycles": self._history})

    def _get_program_name(self) -> str | None:
        """Read the current program fullName from the medium coordinator."""
        if not self._medium_coordinator or not self._medium_coordinator.data:
            return None
        program = self._medium_coordinator.data.get("program")
        if not isinstance(program, dict):
            return None
        return program.get("fullName") or program.get("name") or None

    def _record_cycle(self, elapsed_s: float, status: str) -> None:
        """Append a cycle record and trim to MAX_CYCLES."""
        program_name = self._cycle_program_name
        record: dict[str, Any] = {
            "status": status,  # "completed" | "interrupted"
            "duration_s": round(elapsed_s, 1),
            "duration": _fmt_duration(elapsed_s),
            "program": program_name,
            "started_at": self._cycle_start_wall,
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }
        self._history.append(record)
        if len(self._history) > self.MAX_CYCLES:
            self._history = self._history[-self.MAX_CYCLES :]
        self._hass.async_create_task(self._async_save_history())
        _LOGGER.info(
            "Cycle %s: %.0fs (%s) — program: %s",
            status,
            elapsed_s,
            record["duration"],
            program_name or "<unknown>",
        )

        # Record known cycle time on successful uninterrupted completion
        if status == "completed" and self._known_times and program_name:
            self._known_times.record(program_name, elapsed_s)

    # ------------------------------------------------------------------
    # Cycle state machine

    def _process_update(
        self,
        machine_state: str | None,
        elapsed_s: float | None,
        progress: float,
    ) -> None:
        """Core cycle detection logic — called on every coordinator update."""

        prev_state = self._last_machine_state

        # ── Detect elapsed reset while already Running ─────────────────
        # If elapsed jumps backwards significantly, a new cycle started
        # before the old one recorded its end.
        elapsed_reset = (
            self._cycle_active
            and machine_state == "Running"
            and elapsed_s is not None
            and self._last_elapsed_s is not None
            and elapsed_s < self._last_elapsed_s - 5.0
            and self._last_elapsed_s > self.START_THRESHOLD_S
        )

        if elapsed_reset:
            _LOGGER.debug(
                "Elapsed reset detected (%.0f→%.0f) — closing previous cycle as interrupted",
                self._last_elapsed_s,
                elapsed_s,
            )
            self._record_cycle(self._last_elapsed_s, "interrupted")
            self._cycle_active = False

        # ── Running → terminal state ────────────────────────────────────
        if (
            prev_state == "Running"
            and machine_state in _TERMINAL_STATES
            and self._cycle_active
        ):
            duration = elapsed_s if elapsed_s is not None else self._last_elapsed_s or 0.0
            if self._last_progress >= self.COMPLETE_THRESHOLD:
                self._record_cycle(duration, "completed")
            else:
                self._record_cycle(duration, "interrupted")
            self._cycle_active = False

        # ── New cycle start detection ───────────────────────────────────
        # Triggers when state enters Running with a small elapsed value,
        # coming from a non-Running, non-Pause state (i.e., not a resume).
        if (
            machine_state == "Running"
            and prev_state not in ("Running", "Pause", "WaitingForUserInput")
            and elapsed_s is not None
            and elapsed_s < self.START_THRESHOLD_S
            and not self._cycle_active
        ):
            self._cycle_active = True
            self._cycle_start_wall = datetime.now(timezone.utc).isoformat()
            self._cycle_program_name = self._get_program_name()
            _LOGGER.debug(
                "New cycle started at elapsed=%.1fs, progress=%.1f%%, program=%s",
                elapsed_s,
                progress * 100,
                self._cycle_program_name or "<unknown>",
            )

        # Keep a note of elapsed even through pauses so the final duration
        # is accurate (elapsed is a cumulative counter on the machine anyway).
        if elapsed_s is not None:
            self._last_elapsed_s = elapsed_s

        self._last_machine_state = machine_state
        self._last_progress = progress

    # ------------------------------------------------------------------
    # HA callbacks

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._loaded:
            # Storage not yet loaded (async — happens at setup); skip
            self.async_write_ha_state()
            return

        data: dict[str, Any] = self.coordinator.data or {}
        exec_data: dict | None = data.get("execution")
        machine_status: dict | None = data.get("machine_status")

        elapsed_s = _parse_timespan(
            exec_data.get("programExecutionTime") if isinstance(exec_data, dict) else None
        )
        progress = (
            float(exec_data.get("progress", 0.0)) if isinstance(exec_data, dict) else 0.0
        )
        machine_state_raw = (
            machine_status.get("executionState") if isinstance(machine_status, dict) else None
        )
        machine_state = _EXEC_STATE_MAP.get(machine_state_raw, machine_state_raw)

        self._process_update(machine_state, elapsed_s, progress)
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Derived statistics

    @property
    def _completed_cycles(self) -> list[dict[str, Any]]:
        return [r for r in self._history if r.get("status") == "completed"]

    @property
    def _interrupted_cycles(self) -> list[dict[str, Any]]:
        return [r for r in self._history if r.get("status") == "interrupted"]

    @property
    def native_value(self) -> int:
        """Return the total number of cycles in history."""
        return len(self._history)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        completed = self._completed_cycles
        interrupted = self._interrupted_cycles
        total = len(self._history)

        avg_s: float | None = None
        if completed:
            avg_s = sum(r["duration_s"] for r in completed) / len(completed)

        last_s: float | None = completed[-1]["duration_s"] if completed else None

        interruption_rate = (
            round(len(interrupted) / total * 100, 1) if total > 0 else 0.0
        )

        current_elapsed = (
            _fmt_duration(self._last_elapsed_s) if self._cycle_active else None
        )

        known_programs = (
            self._known_times.programs if self._known_times and self._known_times.loaded else {}
        )

        return {
            "is_cycle_active": self._cycle_active,
            "current_cycle_elapsed": current_elapsed,
            "current_cycle_program": self._cycle_program_name if self._cycle_active else None,
            "history": list(self._history),
            "completed_count": len(completed),
            "interrupted_count": len(interrupted),
            "avg_completed_duration": _fmt_duration(avg_s),
            "avg_completed_duration_s": round(avg_s, 1) if avg_s is not None else None,
            "last_completed_duration": _fmt_duration(last_s),
            "last_completed_duration_s": last_s,
            "interruption_rate_pct": interruption_rate,
            "known_cycle_times": {
                name: {
                    "duration": _fmt_duration(info["duration_s"]),
                    "duration_s": info["duration_s"],
                    "cycle_count": info.get("cycle_count", 0),
                }
                for name, info in known_programs.items()
            },
        }
