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

import logging
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import List

import psutil
from PyQt6.QtCore import QObject, pyqtSignal

try:
    import pynvml
    HAS_NVML = True
except ImportError:
    HAS_NVML = False

from src.core.types import ErrorInfo


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class SystemStats:
    """Immutable snapshot of a single polling cycle's resource readings."""

    cpu_percent: float          # CPU usage as a percentage (0-100)
    cpu_cores_percent: List[float] # Usage per core
    ram_percent: float          # RAM usage as a percentage (0-100)
    ram_used_gb: float          # RAM currently in use (GiB)
    ram_total_gb: float         # Total installed RAM (GiB)
    ram_cached_gb: float        # Cached memory (GiB)
    ram_buffers_gb: float       # Buffers memory (GiB)
    swap_percent: float         # Swap usage as a percentage
    swap_used_gb: float         # Swap currently in use (GiB)
    swap_total_gb: float        # Total swap space (GiB)
    net_download_speed: float   # Download speed in MB/s
    net_upload_speed: float     # Upload speed in MB/s
    net_total_sent: float       # Total GB sent today (or since boot)
    net_total_recv: float       # Total GB received today (or since boot)
    storage_percent: float      # Storage usage percentage of the primary drive
    storage_used_gb: float      # Storage used in GB
    storage_total_gb: float     # Storage total in GB
    storage_free_gb: float      # Storage free in GB
    disk_read_speed: float      # Disk read speed in MB/s
    disk_write_speed: float     # Disk write speed in MB/s
    cpu_temp_celsius: float     # CPU package temperature in °C; 0.0 if unavailable
    gpu_utilization: float      # GPU utilization as a percentage (0-100)
    uptime_str: str             # Formatted uptime "Xd Xh Xm"
    process_count: int          # Total number of processes
    battery_percent: float      # Battery percentage
    battery_is_plugged: bool    # Whether battery is charging
    battery_time_left: str      # Battery time remaining
    cpu_cores_freq: List[float]  # Frequency per core (GHz)
    cpu_fan_rpm: int            # CPU fan speed (RPM)
    gpu_name: str               # GPU model name
    gpu_vram_total_gb: float    # Total VRAM (GB)
    gpu_vram_used_gb: float     # Used VRAM (GB)
    gpu_vram_free_gb: float     # Free VRAM (GB)
    gpu_vram_percent: float     # VRAM utilization percentage
    gpu_fan_rpm: int            # GPU fan speed (RPM)
    gpu_is_dedicated: bool      # True when an active NVIDIA GPU is queried via NVML


# ---------------------------------------------------------------------------
# Worker object
# ---------------------------------------------------------------------------

class SystemMonitorWorker(QObject):
    """
    Background worker that polls system statistics at a configurable interval.

    Signals
    -------
    stats_ready(dict)
        Emitted after every successful poll.  The payload is the dict
        representation of a :class:`SystemStats` instance.

    error_occurred(str)
        Emitted when a non-recoverable error is encountered.

    finished()
        Emitted when the worker has stopped its main loop.
    """

    stats_ready: pyqtSignal = pyqtSignal(dict)  # SystemStatsDict
    error_occurred: pyqtSignal = pyqtSignal(dict)  # ErrorInfo
    finished: pyqtSignal = pyqtSignal()

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

        # For network speed calculations
        self._last_net_io = psutil.net_io_counters()
        # For disk speed calculations
        self._last_disk_io = psutil.disk_io_counters()
        self._last_poll_time = time.time()

        # Initialize NVML
        self._nvml_initialized = False
        if HAS_NVML:
            try:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            except Exception as e:
                logging.warning(f"Failed to initialize NVML: {e}")

    # ------------------------------------------------------------------
    # Public Slots
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the polling loop to exit on its next iteration."""
        self._running = False

    def start_monitoring(self) -> None:
        """Main loop executed in the background thread."""
        self._running = True

        # Prime psutil's per-interval CPU measurement (first call always returns 0.0)
        psutil.cpu_percent(interval=None)

        while self._running:
            try:
                stats = self._collect_stats()
                self.stats_ready.emit(asdict(stats))
            except Exception as exc:  # pragma: no cover – safety net
                self.error_occurred.emit(ErrorInfo(
                    source="SystemMonitor",
                    message=str(exc),
                    timestamp=time.time()
                ))

            # Use a sleep loop instead of a single long sleep so stop() is
            # responsive without requiring a full interval to elapse.
            elapsed = 0.0
            tick = 0.25  # seconds per sleep slice
            while self._running and elapsed < self._poll_interval:
                time.sleep(tick)
                elapsed += tick
        
        # Shutdown NVML
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
                
        self.finished.emit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_stats(self) -> SystemStats:
        """Sample all metrics and return a populated :class:`SystemStats`."""
        # CPU
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_cores_pct = psutil.cpu_percent(interval=None, percpu=True)

        # RAM & Swap
        vm = psutil.virtual_memory()
        ram_pct = vm.percent
        ram_used_gb = vm.used / (1024 ** 3)
        ram_total_gb = vm.total / (1024 ** 3)
        
        # Linux specific memory
        ram_cached_gb = 0.0
        ram_buffers_gb = 0.0
        if platform.system() == "Linux":
            ram_cached_gb = getattr(vm, 'cached', 0) / (1024 ** 3)
            ram_buffers_gb = getattr(vm, 'buffers', 0) / (1024 ** 3)

        swap = psutil.swap_memory()
        swap_pct = swap.percent
        swap_used_gb = swap.used / (1024 ** 3)
        swap_total_gb = swap.total / (1024 ** 3)

        # IO calculations
        now = time.time()
        dt = now - self._last_poll_time
        if dt <= 0:
            dt = 0.001 # prevent div by zero
            
        # Network
        net_io = psutil.net_io_counters()
        dl_speed = (net_io.bytes_recv - self._last_net_io.bytes_recv) / dt / (1024 * 1024) # MB/s
        ul_speed = (net_io.bytes_sent - self._last_net_io.bytes_sent) / dt / (1024 * 1024) # MB/s
        self._last_net_io = net_io

        # Disk IO
        disk_io = psutil.disk_io_counters()
        disk_read_speed = (disk_io.read_bytes - self._last_disk_io.read_bytes) / dt / (1024 * 1024) # MB/s
        disk_write_speed = (disk_io.write_bytes - self._last_disk_io.write_bytes) / dt / (1024 * 1024) # MB/s
        self._last_disk_io = disk_io
        
        self._last_poll_time = now

        net_total_sent = net_io.bytes_sent / (1024 ** 3) # GB
        net_total_recv = net_io.bytes_recv / (1024 ** 3) # GB

        # GPU Details — two-tier hybrid detection
        gpu_data = self._collect_gpu_data()

        # Global stats
        uptime_sec = time.time() - psutil.boot_time()
        days, rem = divmod(int(uptime_sec), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        uptime_str = f"{days}d {hours}h {minutes}m"
        
        process_count = len(psutil.pids())
        
        battery = psutil.sensors_battery()
        bat_percent = 0.0
        bat_plugged = False
        bat_time_str = "N/A"
        if battery:
            bat_percent = battery.percent
            bat_plugged = battery.power_plugged
            if battery.secsleft == psutil.POWER_TIME_UNLIMITED:
                bat_time_str = "Unlimited"
            elif battery.secsleft == psutil.POWER_TIME_UNKNOWN:
                bat_time_str = "Unknown"
            else:
                h, m = divmod(battery.secsleft // 60, 60)
                bat_time_str = f"{h}h {m}m"

        # Frequencies, Fan and Temperature
        cpu_temp, _ = self._get_cpu_temperatures()
        
        cpu_fan_rpm = 0
        try:
            fans = psutil.sensors_fans()
            if fans:
                # Common labels for CPU fan: 'cpu_fan', 'fan1', etc.
                # We'll take the first one that seems like a CPU fan or just the first available
                for fan_label, fan_list in fans.items():
                    if fan_list:
                        cpu_fan_rpm = fan_list[0].current
                        break
        except Exception:
            cpu_fan_rpm = 0

        cpu_cores_freq = []
        try:
            freqs = psutil.cpu_freq(percpu=True)
            for f in freqs:
                # Use current frequency and convert MHz to GHz
                cpu_cores_freq.append(round(f.current / 1000.0, 2))
        except Exception:
            cpu_cores_freq = []

        # Primary drive usage
        try:
            storage = psutil.disk_usage('/')
            storage_pct = storage.percent
            storage_used = storage.used / (1024 ** 3)
            storage_total = storage.total / (1024 ** 3)
            storage_free = storage.free / (1024 ** 3)
        except Exception:
            storage_pct = 0.0
            storage_used = 0.0
            storage_total = 0.0
            storage_free = 0.0

        return SystemStats(
            cpu_percent=cpu_pct,
            cpu_cores_percent=cpu_cores_pct,
            ram_percent=ram_pct,
            ram_used_gb=round(ram_used_gb, 2),
            ram_total_gb=round(ram_total_gb, 2),
            ram_cached_gb=round(ram_cached_gb, 2),
            ram_buffers_gb=round(ram_buffers_gb, 2),
            swap_percent=swap_pct,
            swap_used_gb=round(swap_used_gb, 2),
            swap_total_gb=round(swap_total_gb, 2),
            net_download_speed=round(dl_speed, 2),
            net_upload_speed=round(ul_speed, 2),
            net_total_sent=round(net_total_sent, 2),
            net_total_recv=round(net_total_recv, 2),
            storage_percent=storage_pct,
            storage_used_gb=round(storage_used, 2),
            storage_total_gb=round(storage_total, 2),
            storage_free_gb=round(storage_free, 2),
            disk_read_speed=round(disk_read_speed, 2),
            disk_write_speed=round(disk_write_speed, 2),
            cpu_temp_celsius=cpu_temp,
            gpu_utilization=gpu_data["gpu_utilization"],
            gpu_name=gpu_data["gpu_name"],
            gpu_vram_total_gb=gpu_data["gpu_vram_total_gb"],
            gpu_vram_used_gb=gpu_data["gpu_vram_used_gb"],
            gpu_vram_free_gb=gpu_data["gpu_vram_free_gb"],
            gpu_vram_percent=gpu_data["gpu_vram_percent"],
            gpu_fan_rpm=gpu_data["gpu_fan_rpm"],
            gpu_is_dedicated=gpu_data["gpu_is_dedicated"],
            uptime_str=uptime_str,
            process_count=process_count,
            battery_percent=bat_percent,
            battery_is_plugged=bat_plugged,
            battery_time_left=bat_time_str,
            cpu_cores_freq=cpu_cores_freq,
            cpu_fan_rpm=cpu_fan_rpm,
        )

    # ------------------------------------------------------------------
    # GPU data collection — two-tier hybrid strategy
    # ------------------------------------------------------------------

    def _collect_gpu_data(self) -> dict:
        """
        Collect GPU metrics using a two-tier fallback strategy.

        Tier 1 — NVIDIA via pynvml:
            Attempt a full NVML query (utilization, VRAM, fan speed, model name).
            On any exception (GPU suspended / driver unavailable), fall through
            to Tier 2 rather than returning empty data.

        Tier 2 — Linux lspci fallback:
            Execute ``lspci -mm`` and parse VGA / 3D class entries to extract
            the active graphics controller name (e.g. Intel Iris Xe Graphics).
            All numeric fields default to 0.0 to prevent UI crashes.

        Returns
        -------
        dict
            Keys: gpu_name, gpu_utilization, gpu_vram_total_gb,
                  gpu_vram_used_gb, gpu_vram_free_gb, gpu_vram_percent,
                  gpu_fan_rpm, gpu_is_dedicated.
        """
        result = {
            "gpu_name": "N/A",
            "gpu_utilization": 0.0,
            "gpu_vram_total_gb": 0.0,
            "gpu_vram_used_gb": 0.0,
            "gpu_vram_free_gb": 0.0,
            "gpu_vram_percent": 0.0,
            "gpu_fan_rpm": 0,
            "gpu_is_dedicated": False,
        }

        # ── Tier 1: NVIDIA NVML ──────────────────────────────────────────
        if self._nvml_initialized:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                # Utilization percentage
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                result["gpu_utilization"] = float(util.gpu)

                # Model name (bytes on older pynvml versions)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8")
                result["gpu_name"] = name

                # VRAM — convert bytes to GB
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_gb = mem.total / (1024 ** 3)
                used_gb = mem.used / (1024 ** 3)
                free_gb = mem.free / (1024 ** 3)
                result["gpu_vram_total_gb"] = round(total_gb, 2)
                result["gpu_vram_used_gb"] = round(used_gb, 2)
                result["gpu_vram_free_gb"] = round(free_gb, 2)
                if total_gb > 0:
                    result["gpu_vram_percent"] = round((used_gb / total_gb) * 100, 1)

                # Fan speed (not available on all NVIDIA cards)
                try:
                    result["gpu_fan_rpm"] = pynvml.nvmlDeviceGetFanSpeed(handle)
                except Exception:
                    result["gpu_fan_rpm"] = 0

                result["gpu_is_dedicated"] = True
                return result

            except Exception as nvml_err:
                # GPU is likely suspended (D3cold) — fall through to Tier 2
                logging.debug("NVML query failed (%s); falling back to lspci.", nvml_err)

        # ── Tier 2: Linux lspci fallback ─────────────────────────────────
        if platform.system() == "Linux":
            try:
                proc = subprocess.run(
                    ["lspci", "-mm"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                for line in proc.stdout.splitlines():
                    lower = line.lower()
                    # Match VGA compatible controller or 3D controller class entries
                    if "vga" in lower or "3d" in lower or "display" in lower:
                        # lspci -mm format: "<slot> "<class>" "<vendor>" "<device>" ..."
                        # Split on '"' to extract quoted fields
                        parts = [p.strip() for p in line.split('"') if p.strip()]
                        if len(parts) >= 3:
                            # parts[0] = slot, parts[1] = class, parts[2] = vendor,
                            # parts[3] = device (model name)
                            vendor = parts[2] if len(parts) > 2 else ""
                            device = parts[3] if len(parts) > 3 else ""
                            gpu_name = f"{vendor} {device}".strip()
                            if gpu_name:
                                result["gpu_name"] = gpu_name
                                break
            except Exception as lspci_err:
                logging.debug("lspci fallback failed: %s", lspci_err)

        return result

    @staticmethod
    def _get_cpu_temperatures() -> tuple[float, list[float]]:
        """
        Attempt to read the CPU package and per-core temperatures.

        Returns (package_temp, [core1_temp, core2_temp, ...]).
        Returns (0.0, []) if unavailable.
        """
        try:
            if not hasattr(psutil, "sensors_temperatures"):
                return 0.0, []

            temps = psutil.sensors_temperatures()
            if not temps:
                return 0.0, []

            package_temp = 0.0
            core_temps = []

            # Priority order for common sensor names across distros / hardware
            priority_keys = ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal")
            for key in priority_keys:
                if key in temps:
                    entries = temps[key]
                    
                    # For coretemp, entries usually look like:
                    # Package id 0, Core 0, Core 1, ...
                    for entry in entries:
                        label = entry.label.lower()
                        if "package" in label or "tdie" in label or "tctl" in label:
                            package_temp = round(entry.current, 1)
                        elif "core" in label:
                            core_temps.append(round(entry.current, 1))
                    
                    if package_temp == 0.0 and entries:
                         package_temp = round(entries[0].current, 1)
                    
                    return package_temp, core_temps

            # Use the first available sensor as a last resort
            first_group = next(iter(temps.values()))
            return round(first_group[0].current, 1), []

        except Exception:
            return 0.0, []
