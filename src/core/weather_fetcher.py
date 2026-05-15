"""
weather_fetcher.py
==================
A QThread worker that fetches current weather data from the OpenWeatherMap
API (https://openweathermap.org/current).

When no API key is configured, the worker emits a clearly labelled *mock*
payload so the rest of the application can develop and test without network
access or a paid account.

API endpoint used
-----------------
GET https://api.openweathermap.org/data/2.5/weather
    ?q={city}&appid={api_key}&units=metric

Configuration keys (loaded from config.json via ConfigManager)
--------------------------------------------------------------
weather.api_key   : str  – OpenWeatherMap API key (empty string = mock mode)
weather.city      : str  – City name to query (default: "Cairo")
weather.interval  : int  – Poll interval in seconds (default: 600)
"""

import time
from dataclasses import dataclass, asdict
from typing import Optional

import requests
from PyQt6.QtCore import QThread, pyqtSignal


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class WeatherData:
    """Snapshot of weather conditions at the time of the last API call."""

    city: str                   # City name returned by the API
    temperature_c: float        # Current temperature in Celsius
    feels_like_c: float         # Feels-like temperature in Celsius
    humidity_percent: int       # Relative humidity (0-100)
    description: str            # Short human-readable condition (e.g. "clear sky")
    icon_code: str              # OWM icon code (e.g. "01d") – use for icon URL
    wind_speed_ms: float        # Wind speed in m/s
    is_mock: bool               # True when the payload was generated locally


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class WeatherFetcherWorker(QThread):
    """
    Background thread that periodically fetches weather from OpenWeatherMap.

    Signals
    -------
    weather_ready(dict)
        Emitted after a successful fetch.  Payload is the dict representation
        of a :class:`WeatherData` instance.

    fetch_error(str)
        Emitted when the HTTP request fails or the response is unexpected.
    """

    weather_ready: pyqtSignal = pyqtSignal(dict)
    fetch_error: pyqtSignal = pyqtSignal(str)

    _OWM_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
    _DEFAULT_TIMEOUT = 10  # seconds

    def __init__(
        self,
        api_key: str = "",
        city: str = "Cairo",
        poll_interval_seconds: int = 600,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self._city = city
        self._poll_interval = poll_interval_seconds
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_config(self, api_key: str, city: str) -> None:
        """Hot-update credentials without restarting the thread."""
        self._api_key = api_key
        self._city = city

    def stop(self) -> None:
        """Signal the polling loop to exit."""
        self._running = False

    # ------------------------------------------------------------------
    # QThread interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop: fetch immediately, then wait for the next interval."""
        self._running = True

        while self._running:
            self._fetch_and_emit()

            # Interruptible sleep
            elapsed = 0.0
            tick = 0.5
            while self._running and elapsed < self._poll_interval:
                time.sleep(tick)
                elapsed += tick

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_and_emit(self) -> None:
        """Perform a single fetch cycle and emit the appropriate signal."""
        if not self._api_key:
            self.weather_ready.emit(asdict(self._mock_weather()))
            return

        try:
            payload = self._call_api()
            self.weather_ready.emit(asdict(payload))
        except requests.exceptions.RequestException as exc:
            self.fetch_error.emit(f"Network error: {exc}")
        except (KeyError, ValueError) as exc:
            self.fetch_error.emit(f"Unexpected API response: {exc}")

    def _call_api(self) -> WeatherData:
        """
        Execute the OpenWeatherMap API request and parse the response.

        Raises
        ------
        requests.exceptions.RequestException
            On any network-level failure.
        KeyError, ValueError
            If the response JSON is missing expected fields.
        """
        params = {
            "q": self._city,
            "appid": self._api_key,
            "units": "metric",
        }
        response = requests.get(
            self._OWM_BASE_URL,
            params=params,
            timeout=self._DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        return WeatherData(
            city=data["name"],
            temperature_c=round(data["main"]["temp"], 1),
            feels_like_c=round(data["main"]["feels_like"], 1),
            humidity_percent=int(data["main"]["humidity"]),
            description=data["weather"][0]["description"].capitalize(),
            icon_code=data["weather"][0]["icon"],
            wind_speed_ms=round(data["wind"]["speed"], 1),
            is_mock=False,
        )

    @staticmethod
    def _mock_weather() -> WeatherData:
        """Return a plausible mock payload when no API key is configured."""
        return WeatherData(
            city="Cairo (mock)",
            temperature_c=32.5,
            feels_like_c=35.0,
            humidity_percent=42,
            description="Clear sky",
            icon_code="01d",
            wind_speed_ms=3.2,
            is_mock=True,
        )
