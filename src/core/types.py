from typing import TypedDict, List

class SystemStatsDict(TypedDict):
    """Type definition for the system stats dictionary payload."""
    cpu_percent: float
    cpu_cores_percent: List[float]
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    ram_cached_gb: float
    ram_buffers_gb: float
    swap_percent: float
    swap_used_gb: float
    swap_total_gb: float
    net_download_speed: float  # MB/s
    net_upload_speed: float    # MB/s
    net_total_sent: float      # GB
    net_total_recv: float      # GB
    storage_percent: float
    storage_used_gb: float
    storage_total_gb: float
    storage_free_gb: float
    disk_read_speed: float     # MB/s
    disk_write_speed: float    # MB/s
    cpu_temp_celsius: float
    gpu_utilization: float     # %
    uptime_str: str            # "Xd Xh Xm"
    process_count: int
    battery_percent: float
    battery_is_plugged: bool
    battery_time_left: str     # "H:M" or "N/A"
    cpu_cores_freq: List[float]
    cpu_fan_rpm: int
    gpu_name: str
    gpu_vram_total_gb: float
    gpu_vram_used_gb: float
    gpu_vram_free_gb: float
    gpu_vram_percent: float
    gpu_fan_rpm: int

class WeatherDataDict(TypedDict):
    """Type definition for the weather data dictionary payload."""
    city: str
    temperature_c: float
    feels_like_c: float
    humidity_percent: int
    description: str
    icon_code: str
    wind_speed_ms: float
    is_mock: bool

class ErrorInfo(TypedDict):
    """Type definition for structured error information."""
    source: str
    message: str
    timestamp: float
