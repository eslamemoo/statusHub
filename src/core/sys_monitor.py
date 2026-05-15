"""
sys_monitor.py
==============
A QThread worker that continuously samples system resource metrics using psutil.
Emits a structured dictionary via a pyqtSignal on every polling interval so the
UI thread is never blocked.

Supported metrics
-----------------
- CPU usage (percent, per-interval)
- RAM usage (percent and absolute values)
- CPU temperature (cross-platform; returns 0.0 when sensors are unavailable)
"""

import time
from dataclasses import dataclass, asdict
from typing import Optional

import psutil
from PyQt6.QtCore import QThread, pyqtSignal


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class SystemStats:
    """Immutable snapshot of a single polling cycle's resource readings."""

    cpu_percent: float          # CPU usage as a percentage (0-100)
    ram_percent: float          # RAM usage as a percentage (0-100)
    ram_used_gb: float          # RAM currently in use (GiB)
    ram_total_gb: float         # Total installed RAM (GiB)
    cpu_temp_celsius: float     # CPU package temperature in °C; 0.0 if unavailable


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class SystemMonitorWorker(QThread):
    """
    Background thread that polls system statistics at a configurable interval.

    Signals
    -------
    stats_ready(dict)
        Emitted after every successful poll.  The payload is the dict
        representation of a :class:`SystemStats` instance.

    error_occurred(str)
        Emitted when a non-recoverable error is encountered.
    """

    stats_ready: pyqtSignal = pyqtSignal(dict)
    error_occurred: pyqtSignal = pyqtSignal(str)

    def __init__(self, poll_interval_seconds: float = 2.0, parent=None) -> None:
        """
        Parameters
        ----------
        poll_interval_seconds:
            How often (in seconds) to sample the system metrics.
        parent:
            Optional Qt parent object.
        """
        super().__init__(parent)
        self._poll_interval = poll_interval_seconds
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the polling loop to exit on its next iteration."""
        self._running = False

    # ------------------------------------------------------------------
    # QThread interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop executed in the background thread."""
        self._running = True

        # Prime psutil's per-interval CPU measurement (first call always returns 0.0)
        psutil.cpu_percent(interval=None)

        while self._running:
            try:
                stats = self._collect_stats()
                self.stats_ready.emit(asdict(stats))
            except Exception as exc:  # pragma: no cover – safety net
                self.error_occurred.emit(str(exc))

            # Use a sleep loop instead of a single long sleep so stop() is
            # responsive without requiring a full interval to elapse.
            elapsed = 0.0
            tick = 0.25  # seconds per sleep slice
            while self._running and elapsed < self._poll_interval:
                time.sleep(tick)
                elapsed += tick

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_stats(self) -> SystemStats:
        """Sample all metrics and return a populated :class:`SystemStats`."""
        cpu_pct = psutil.cpu_percent(interval=None)

        vm = psutil.virtual_memory()
        ram_pct = vm.percent
        ram_used_gb = vm.used / (1024 ** 3)
        ram_total_gb = vm.total / (1024 ** 3)

        cpu_temp = self._get_cpu_temperature()

        return SystemStats(
            cpu_percent=cpu_pct,
            ram_percent=ram_pct,
            ram_used_gb=round(ram_used_gb, 2),
            ram_total_gb=round(ram_total_gb, 2),
            cpu_temp_celsius=cpu_temp,
        )

    @staticmethod
    def _get_cpu_temperature() -> float:
        """
        Attempt to read the CPU package temperature.

        Returns 0.0 on any platform where sensor access fails (e.g. Windows
        without OpenHardwareMonitor, macOS without extra drivers, or Linux
        without coretemp/acpi module loaded).
        """
        try:
            if not hasattr(psutil, "sensors_temperatures"):
                # Windows ships psutil without this attribute unless compiled
                # with the correct optional dependencies.
                return 0.0

            temps = psutil.sensors_temperatures()
            if not temps:
                return 0.0

            # Priority order for common sensor names across distros / hardware
            priority_keys = ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal")
            for key in priority_keys:
                if key in temps:
                    entries = temps[key]
                    # Prefer the "Package id 0" / "Tdie" entry; fall back to first
                    for entry in entries:
                        label = entry.label.lower()
                        if "package" in label or "tdie" in label or "tctl" in label:
                            return round(entry.current, 1)
                    # Fall back to the first sensor in the matched group
                    return round(entries[0].current, 1)

            # Use the first available sensor as a last resort
            first_group = next(iter(temps.values()))
            return round(first_group[0].current, 1)

        except Exception:
            return 0.0
