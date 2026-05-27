from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from src.core.types import WeatherDataDict

class WeatherTab(QWidget):
    """
    Dedicated tab for meteorological data.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Meteorological Data Station")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        placeholder = QLabel("Advanced weather widgets coming soon...")
        placeholder.setStyleSheet("font-size: 14px; color: #aaaaaa;")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(placeholder)

    def on_weather_update(self, data: WeatherDataDict):
        """Handle weather data updates (placeholder)."""
        pass
