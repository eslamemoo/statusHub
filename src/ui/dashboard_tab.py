"""
dashboard_tab.py
================
The "Live Dashboard" tab widget.

Displays real-time system metrics (CPU, RAM, Temperature) by connecting to
:class:`~src.core.sys_monitor.SystemMonitorWorker` signals, and also shows
the latest weather snapshot by connecting to
:class:`~src.core.weather_fetcher.WeatherFetcherWorker` signals.

Layout overview
---------------
┌─────────────────────────────────────────────────────┐
│  System Resources                                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐ │
│  │   CPU    │  │   RAM    │  │  CPU Temperature  │ │
│  │  [bar]   │  │  [bar]   │  │     [label]       │ │
│  └──────────┘  └──────────┘  └───────────────────┘ │
├─────────────────────────────────────────────────────│
│  Weather                                            │
│  City | Temp | Feels-Like | Humidity | Wind | Desc  │
└─────────────────────────────────────────────────────┘
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QGroupBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont


class MetricCard(QWidget):
    """
    A self-contained card that shows a labelled progress bar and a value label.

    Used for CPU%, RAM%, and any other percentage-based metric.
    """

    def __init__(self, title: str, unit: str = "%", parent=None) -> None:
        super().__init__(parent)
        self._unit = unit
        self._build_ui(title)

    def _build_ui(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setObjectName("cardTitle")

        # Value label
        self._value_lbl = QLabel(f"0 {self._unit}")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setObjectName("cardValue")
        font = QFont()
        font.setPointSize(22)
        font.setBold(True)
        self._value_lbl.setFont(font)

        # Progress bar
        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(14)
        self._bar.setObjectName("metricBar")

        layout.addWidget(title_lbl)
        layout.addWidget(self._value_lbl)
        layout.addWidget(self._bar)
        self.setObjectName("metricCard")

    def update_value(self, value: float) -> None:
        """Update both the label text and the progress bar position."""
        display = f"{value:.1f} {self._unit}"
        self._value_lbl.setText(display)
        # Progress bar only makes sense for percentage values
        if self._unit == "%":
            self._bar.setValue(int(value))


class WeatherPanel(QGroupBox):
    """A horizontally-arranged info panel showing the latest weather data."""

    def __init__(self, parent=None) -> None:
        super().__init__("🌤  Live Weather", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setSpacing(24)

        self._city_lbl = self._make_info_label("City", "—")
        self._temp_lbl = self._make_info_label("Temperature", "—")
        self._feels_lbl = self._make_info_label("Feels Like", "—")
        self._humidity_lbl = self._make_info_label("Humidity", "—")
        self._wind_lbl = self._make_info_label("Wind", "—")
        self._desc_lbl = self._make_info_label("Condition", "—")

        for widget in (
            self._city_lbl,
            self._temp_lbl,
            self._feels_lbl,
            self._humidity_lbl,
            self._wind_lbl,
            self._desc_lbl,
        ):
            layout.addWidget(widget)

    @staticmethod
    def _make_info_label(caption: str, initial_value: str) -> QWidget:
        """Create a vertical pair: small caption + larger value."""
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)

        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setObjectName("weatherCaption")

        val = QLabel(initial_value)
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val.setObjectName("weatherValue")
        val_font = QFont()
        val_font.setPointSize(13)
        val_font.setBold(True)
        val.setFont(val_font)

        vbox.addWidget(cap)
        vbox.addWidget(val)
        # Store value label as child attribute so we can update it later
        container._value_label = val  # type: ignore[attr-defined]
        return container

    def update_weather(self, data: dict) -> None:
        """Populate all weather fields from the emitted data dict."""
        is_mock = data.get("is_mock", False)
        prefix = "🔵 " if is_mock else ""

        self._city_lbl._value_label.setText(f"{prefix}{data.get('city', '—')}")  # type: ignore
        self._temp_lbl._value_label.setText(f"{data.get('temperature_c', '—')} °C")  # type: ignore
        self._feels_lbl._value_label.setText(f"{data.get('feels_like_c', '—')} °C")  # type: ignore
        self._humidity_lbl._value_label.setText(f"{data.get('humidity_percent', '—')} %")  # type: ignore
        self._wind_lbl._value_label.setText(f"{data.get('wind_speed_ms', '—')} m/s")  # type: ignore
        self._desc_lbl._value_label.setText(data.get("description", "—"))  # type: ignore


class DashboardTab(QWidget):
    """
    The main Live Dashboard composite widget.

    Wire up the worker signals externally after instantiation:

    >>> tab = DashboardTab()
    >>> monitor_worker.stats_ready.connect(tab.on_stats_update)
    >>> weather_worker.weather_ready.connect(tab.on_weather_update)
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # -- System Resources group -----------------------------------
        resources_group = QGroupBox("💻  System Resources")
        res_layout = QHBoxLayout(resources_group)
        res_layout.setSpacing(16)

        self._cpu_card = MetricCard("CPU Usage", "%")
        self._ram_card = MetricCard("RAM Usage", "%")
        self._temp_card = MetricCard("CPU Temp", "°C")

        # Override the progress bar behaviour for temperature (not a %)
        self._temp_card._bar.setMaximum(110)  # typical CPU max before throttle

        for card in (self._cpu_card, self._ram_card, self._temp_card):
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            res_layout.addWidget(card)

        # RAM secondary info (used / total)
        self._ram_detail_lbl = QLabel("— GB / — GB")
        self._ram_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ram_detail_lbl.setObjectName("ramDetail")

        ram_extra_layout = QVBoxLayout()
        ram_extra_layout.addWidget(self._ram_card)
        ram_extra_layout.addWidget(self._ram_detail_lbl)

        # Replace the plain ram_card in the layout with the composite
        res_layout.removeWidget(self._ram_card)
        self._ram_card.setParent(None)

        # Rebuild layout with RAM composite
        res_layout_final = QHBoxLayout()
        res_layout_final.setSpacing(16)
        res_layout_final.addWidget(self._cpu_card)

        ram_container = QWidget()
        QVBoxLayout(ram_container).addWidget(self._ram_card)
        QVBoxLayout(ram_container).addWidget(self._ram_detail_lbl)

        # Simpler approach: keep cards flat, add detail label below bar
        self._ram_card.layout().addWidget(self._ram_detail_lbl)

        res_layout_clean = QHBoxLayout()
        res_layout_clean.setSpacing(16)
        res_layout_clean.addWidget(self._cpu_card)
        res_layout_clean.addWidget(self._ram_card)
        res_layout_clean.addWidget(self._temp_card)
        resources_group.setLayout(res_layout_clean)

        # -- Weather panel --------------------------------------------
        self._weather_panel = WeatherPanel()

        # -- Status bar label (connection info, errors, etc.) ---------
        self._status_lbl = QLabel("⏳  Waiting for first data…")
        self._status_lbl.setObjectName("statusLabel")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)

        root.addWidget(resources_group)
        root.addWidget(self._weather_panel)
        root.addStretch()
        root.addWidget(self._status_lbl)

    # ------------------------------------------------------------------
    # Slots – connected to worker signals from main_window
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def on_stats_update(self, stats: dict) -> None:
        """
        Receive a system stats dict from :class:`SystemMonitorWorker` and
        update all metric cards.
        """
        self._cpu_card.update_value(stats.get("cpu_percent", 0.0))
        self._ram_card.update_value(stats.get("ram_percent", 0.0))

        ram_used = stats.get("ram_used_gb", 0.0)
        ram_total = stats.get("ram_total_gb", 0.0)
        self._ram_detail_lbl.setText(f"{ram_used:.2f} GB / {ram_total:.2f} GB")

        temp = stats.get("cpu_temp_celsius", 0.0)
        self._temp_card.update_value(temp)
        self._temp_card._bar.setValue(int(temp))

        self._status_lbl.setText("✅  Live – receiving system data")

    @pyqtSlot(dict)
    def on_weather_update(self, data: dict) -> None:
        """
        Receive a weather data dict from :class:`WeatherFetcherWorker` and
        refresh the weather panel.
        """
        self._weather_panel.update_weather(data)

    @pyqtSlot(str)
    def on_monitor_error(self, message: str) -> None:
        """Display an error from the system monitor worker."""
        self._status_lbl.setText(f"⚠️  Monitor error: {message}")

    @pyqtSlot(str)
    def on_weather_error(self, message: str) -> None:
        """Display an error from the weather fetcher worker."""
        self._weather_panel.setTitle(f"🌤  Live Weather  ⚠️  {message}")
