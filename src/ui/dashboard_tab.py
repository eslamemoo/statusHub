"""
dashboard_tab.py
================
The "Live Dashboard" tab widget.

Displays real-time system metrics (CPU, RAM, Temperature) by connecting to
:class:`~src.core.sys_monitor.SystemMonitorWorker` signals, and also shows
the latest weather snapshot (including a live OWM icon) by connecting to
:class:`~src.core.weather_fetcher.WeatherFetcherWorker` signals.

Layout overview
---------------
┌──────────────────────────────────────────────────────────────────────────┐
│  System Resources                                                        │
│                                                                          │
│      ┌────────────┐      ┌────────────┐      ┌────────────┐             │
│      │  ◯ gauge   │      │  ◯ gauge   │      │  ◯ gauge   │             │
│      │  CPU USAGE │      │  RAM USAGE │      │  CPU TEMP  │             │
│      │  45 %      │      │  62 %      │      │  58 °C     │             │
│      │            │      │  4.1/16 GB │      │            │             │
│      └────────────┘      └────────────┘      └────────────┘             │
├──────────────────────────────────────────────────────────────────────────┤
│  Live Weather                                                            │
│  [icon]  City | Temp | Feels | Humidity | Wind | Condition              │
└──────────────────────────────────────────────────────────────────────────┘

Thread-safety notes
-------------------
All public slots guard against C++ object deletion (which can happen when a
queued signal is delivered just after the widget is destroyed during Qt
teardown). Each slot begins with a ``sip.isdeleted`` check and wraps all Qt
API calls in a ``try/except RuntimeError`` so stale deliveries are silently
discarded rather than crashing the application.

OWM icon loading
----------------
Weather data dicts may contain an ``icon`` key with an OWM icon code such as
``"01d"``. The :class:`WeatherPanel` fetches the corresponding PNG from
``https://openweathermap.org/img/wn/{code}@2x.png`` via
:class:`PyQt6.QtNetwork.QNetworkAccessManager` (async, non-blocking) and
displays it in a dedicated :class:`QLabel`.
"""

import logging

from PyQt6 import sip
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QSizePolicy,
    QSpacerItem,
    QScrollArea,
    QProgressBar,
    QFrame,
    QGridLayout,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSlot, QEvent, QUrl, QSize
from PyQt6.QtGui import QFont, QPixmap, QColor
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

import qtawesome as qta

from src.ui.custom_widgets import CircularGauge, get_dynamic_color
from src.ui.utils.flow_layout import FlowLayout
from src.ui.utils.dynamic_grid_layout import DynamicGridLayout
from src.core.types import SystemStatsDict, WeatherDataDict, ErrorInfo

logger = logging.getLogger(__name__)

# OWM icon endpoint — {code} is a two-char code + 'd'/'n', e.g. "01d".
_OWM_ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"
_ICON_SIZE = 56   # px — display size of the weather icon label


# ---------------------------------------------------------------------------
# GaugeCard
# ---------------------------------------------------------------------------

class GaugeCard(QWidget):
    """
    A self-contained card showing a :class:`CircularGauge`, a title label,
    and an optional secondary detail label below the gauge.

    Parameters
    ----------
    title:
        Human-readable metric name rendered above the gauge (e.g. "CPU USAGE").
    color:
        Accent ``QColor`` for the gauge's active arc.
    label:
        Short inner label drawn inside the gauge circle (e.g. ``"CPU"``).
    max_value:
        Maximum value for the gauge.  Defaults to 100.
    unit:
        Unit suffix used for any secondary text display.  Defaults to ``"%"``.
    parent:
        Optional Qt parent widget.
    """

    def __init__(
        self,
        title: str,
        color: QColor,
        label: str = "LOAD",
        max_value: float = 100.0,
        unit: str = "%",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._unit = unit
        self._max_value = max_value
        self._build_ui(title, color, label, max_value)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(
        self, title: str, color: QColor, label: str, max_value: float
    ) -> None:
        """Build the internal layout: circular gauge → optional detail."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ── Circular gauge ───────────────────────────────────────────────
        # Pass the unit string so the gauge can render it inside the circle.
        self._gauge = CircularGauge(
            color=color,
            label=label,
            unit=self._unit,
            max_value=max_value,
        )

        # Use a plain QWidget row to centre the gauge horizontally.
        # Apply transparent background explicitly to prevent the global
        # QWidget { background-color: … } QSS rule from painting a dark box.
        gauge_container = QWidget()
        gauge_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        gauge_container.setStyleSheet("background: transparent; border: none;")
        gauge_row = QVBoxLayout(gauge_container) # Changed to QVBoxLayout
        gauge_row.setContentsMargins(0, 0, 0, 0)
        gauge_row.setSpacing(0)
        gauge_row.addWidget(self._gauge, 0, Qt.AlignmentFlag.AlignCenter) # Center gauge
        layout.addWidget(gauge_container)

        # ── Optional detail label (initially hidden) ─────────────────────
        # Light gray so it is readable but does not compete with the gauge.
        self._detail_lbl = QLabel("")
        self._detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_lbl.setObjectName("ramDetail")
        self._detail_lbl.setStyleSheet(
            "color: #9ca3af;"
            "font-size: 11px;"
            "font-weight: 500;"
            "background: transparent;"
            "border: none;"
        )
        self._detail_lbl.setVisible(False)
        layout.addWidget(self._detail_lbl)

        self.setObjectName("metricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(150) # Reduced from 200 to be more flexible

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_value(self, value: float) -> None:
        """
        Animate the gauge to *value*.

        Thread-safe: the ``sip.isdeleted`` guard and ``RuntimeError`` catch
        ensure a silent no-op if the C++ widget is being destroyed.
        """
        if sip.isdeleted(self):
            return
        try:
            self._gauge.set_value(value)
        except RuntimeError:
            logger.debug("GaugeCard.update_value: widget deleted, skipping.")

    def set_detail(self, text: str) -> None:
        """Show or update the secondary detail label below the gauge."""
        if sip.isdeleted(self):
            return
        try:
            self._detail_lbl.setText(text)
            self._detail_lbl.setVisible(True)
        except RuntimeError:
            logger.debug("GaugeCard.set_detail: widget deleted, skipping.")


class ResponsiveGaugeContainer(QWidget):
    """
    A container for 4 circular gauges that dynamically changes its grid layout
    based on the available width.
    - Large (> 1100px): 1 row, 4 columns
    - Medium (> 650px): 2 rows, 2 columns
    - Small (<= 650px): 4 rows, 1 column
    """
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setSpacing(20)
        self._layout.setContentsMargins(5, 5, 5, 5)
        self._widgets: list[QWidget] = []
        self._current_state: int = 0  # 0: None, 1: Large, 2: Medium, 3: Small

    def add_widget(self, widget: QWidget) -> None:
        """Add a widget to be managed by the responsive grid."""
        self._widgets.append(widget)
        self._update_grid(force=True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Handle resize events to switch between grid states."""
        super().resizeEvent(event)
        width = event.size().width()

        new_state = 1
        if width > 1100:
            new_state = 1
        elif width > 650:
            new_state = 2
        else:
            new_state = 3

        if new_state != self._current_state:
            self._current_state = new_state
            self._update_grid()

    def _update_grid(self, force: bool = False) -> None:
        """Clear and rebuild the grid layout based on the current state."""
        if not self._widgets:
            return

        # Clear existing items from layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(self)

        # Re-add widgets based on state
        if self._current_state == 1:  # 1x4
            for i, widget in enumerate(self._widgets):
                self._layout.addWidget(widget, 0, i)
        elif self._current_state == 2:  # 2x2
            for i, widget in enumerate(self._widgets):
                row, col = divmod(i, 2)
                self._layout.addWidget(widget, row, col)
        else:  # 4x1 (State 3)
            for i, widget in enumerate(self._widgets):
                self._layout.addWidget(widget, i, 0)


# ---------------------------------------------------------------------------
# WeatherPanel
# ---------------------------------------------------------------------------

class WeatherPanel(QGroupBox):
    """
    Horizontally-arranged info panel showing the latest weather snapshot.

    Includes a ``QLabel`` (``_icon_lbl``) that asynchronously fetches and
    displays the OWM weather icon when ``update_weather`` receives an
    ``icon`` code.
    """

    def __init__(self, nam: QNetworkAccessManager, parent=None) -> None:
        super().__init__("Live Weather", parent)
        self._nam = nam
        self._build_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(12, 12, 12, 12)

        # Weather icon (loaded async from OWM CDN)
        self._icon_lbl = QLabel()
        self._icon_lbl.setObjectName("weatherIcon")
        self._icon_lbl.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setText("🌡")  # Unicode fallback until the real icon loads
        layout.addWidget(self._icon_lbl)
        layout.addSpacing(8)

        # Thin vertical divider
        divider = QWidget()
        divider.setFixedWidth(1)
        divider.setStyleSheet("background-color: #2d2d42;")
        layout.addWidget(divider)
        layout.addSpacing(8)

        # Data columns
        self._city_lbl     = self._make_info_pair("City", "—")
        self._temp_lbl     = self._make_info_pair("Temperature", "—")
        self._feels_lbl    = self._make_info_pair("Feels Like", "—")
        self._humidity_lbl = self._make_info_pair("Humidity", "—")
        self._wind_lbl     = self._make_info_pair("Wind", "—")
        self._desc_lbl     = self._make_info_pair("Condition", "—")

        for i, widget in enumerate((
            self._city_lbl, self._temp_lbl, self._feels_lbl,
            self._humidity_lbl, self._wind_lbl, self._desc_lbl,
        )):
            layout.addWidget(widget, stretch=1)
            # Add thin separator between data columns (not after the last one)
            if i < 5:
                sep = QWidget()
                sep.setFixedWidth(1)
                sep.setStyleSheet("background-color: #2d2d42;")
                layout.addWidget(sep)

    @staticmethod
    def _make_info_pair(caption: str, initial_value: str) -> QWidget:
        """Return a QWidget with a muted caption label above a bold value label."""
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(8, 4, 8, 4)
        vbox.setSpacing(4)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setObjectName("weatherCaption")

        val = QLabel(initial_value)
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val.setObjectName("weatherValue")
        val_font = QFont()
        val_font.setPointSize(13)
        val_font.setWeight(QFont.Weight.DemiBold)
        val.setFont(val_font)

        vbox.addWidget(cap)
        vbox.addWidget(val)
        # Attach value label as a dynamic attribute for update_weather access.
        container._value_label = val  # type: ignore[attr-defined]
        return container

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_weather(self, data: dict) -> None:
        """Populate all weather fields and trigger an async icon fetch."""
        prefix = "🔵 " if data.get("is_mock", False) else ""

        self._city_lbl._value_label.setText(f"{prefix}{data.get('city', '—')}")  # type: ignore[attr-defined]
        self._temp_lbl._value_label.setText(f"{data.get('temperature_c', '—')} °C")  # type: ignore[attr-defined]
        self._feels_lbl._value_label.setText(f"{data.get('feels_like_c', '—')} °C")  # type: ignore[attr-defined]
        self._humidity_lbl._value_label.setText(f"{data.get('humidity_percent', '—')} %")  # type: ignore[attr-defined]
        self._wind_lbl._value_label.setText(f"{data.get('wind_speed_ms', '—')} m/s")  # type: ignore[attr-defined]
        self._desc_lbl._value_label.setText(data.get("description", "—"))  # type: ignore[attr-defined]

        # Fetch the OWM icon if an icon code is present and the connection is real.
        icon_code = data.get("icon", "")
        if icon_code and not data.get("is_mock", False):
            self._fetch_icon(icon_code)

    def _fetch_icon(self, code: str) -> None:
        """
        Asynchronously fetch the OWM weather icon PNG and display it.

        The network request is completely non-blocking; the icon label is
        updated via a lambda connected to QNetworkReply.finished.
        """
        url = _OWM_ICON_URL.format(code=code)
        request = QNetworkRequest(QUrl(url))
        reply: QNetworkReply = self._nam.get(request)

        def _on_finished() -> None:
            if sip.isdeleted(self):
                reply.deleteLater()
                return
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll()
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    scaled = pixmap.scaled(
                        _ICON_SIZE, _ICON_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    try:
                        self._icon_lbl.setPixmap(scaled)
                        self._icon_lbl.setText("")
                    except RuntimeError:
                        pass
            reply.deleteLater()

        reply.finished.connect(_on_finished)


# ---------------------------------------------------------------------------
# Detailed Cards
# ---------------------------------------------------------------------------

class DetailCard(QFrame):
    """
    A styled card for detailed metrics.
    """
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("detailCard")
        self.setMinimumWidth(350)
        # Ensure they expand vertically and horizontally
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("""
            QFrame#detailCard {
                background-color: #1e1e2e;
                border-radius: 12px;
                border: 1px solid #2d2d42;
            }
            QLabel {
                color: #ffffff;
                background: transparent;
            }
            QLabel#cardTitle {
                font-size: 16px;
                font-weight: bold;
                color: #89b4fa;
            }
            QProgressBar {
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #313244;
                text-align: center;
                color: white;
                height: 12px;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
            QPushButton#headerBtn {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        
        # Header layout with Title and optional toggle button
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 8)
        
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("cardTitle")
        self.header_layout.addWidget(self.title_lbl)
        self.header_layout.addStretch()
        
        self.main_layout.addLayout(self.header_layout)

class CPUDetailCard(DetailCard):
    def __init__(self, parent=None):
        super().__init__("CPU DETAILS", parent)
        
        # Core grid
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self.main_layout.addLayout(self.grid)
        self.bars = []
        
        # Bottom info: Active Processes & Fan Speed
        self.main_layout.addSpacing(12)
        
        self.footer_layout = QHBoxLayout()
        
        # Task 3: Add Icons before "Active Processes" and "Fan Speed"
        self.proc_icon = QLabel()
        self.proc_icon.setPixmap(qta.icon("mdi.text-box-multiple-outline", color="#a0a0a0").pixmap(16, 16))
        self.footer_layout.addWidget(self.proc_icon)
        
        self.proc_lbl = QLabel("Active Processes: —")
        self.proc_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        self.footer_layout.addWidget(self.proc_lbl)
        
        self.footer_layout.addStretch()
        
        self.fan_icon = QLabel()
        self.fan_icon.setPixmap(qta.icon("mdi.fan", color="#ffffff").pixmap(16, 16))
        self.footer_layout.addWidget(self.fan_icon)
        
        self.fan_lbl = QLabel("Fan Speed: — RPM")
        self.fan_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        self.footer_layout.addWidget(self.fan_lbl)
        
        self.main_layout.addLayout(self.footer_layout)

    def update_stats(self, stats: SystemStatsDict):
        cores_pct = stats.get("cpu_cores_percent", [])
        cores_freq = stats.get("cpu_cores_freq", [])
        
        # Dynamically create bars if needed
        if not self.bars:
            for i, pct in enumerate(cores_pct):
                lbl = QLabel(f"Core {i}")
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(int(pct))
                
                row = i // 2
                col = (i % 2) * 2
                self.grid.addWidget(lbl, row, col)
                self.grid.addWidget(bar, row, col + 1)
                
                self.bars.append(bar)
        
        # Update values
        for i, (bar, pct) in enumerate(zip(self.bars, cores_pct)):
            bar.setValue(int(pct))
            color = get_dynamic_color(pct)
            bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")
                
        # Update Footer
        proc_count = stats.get('process_count', 0)
        fan_rpm = stats.get('cpu_fan_rpm', 0)
        
        self.proc_lbl.setText(f"Active Processes: {proc_count}")
        self.fan_lbl.setText(f"Fan Speed: {fan_rpm} RPM" if fan_rpm > 0 else "Fan Speed: N/A")

class RAMDetailCard(DetailCard):
    def __init__(self, parent=None):
        super().__init__("MEMORY DETAILS", parent)
        
        # Toggle button for Cache/Buffers
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("headerBtn")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setIcon(qta.icon("mdi.chevron-down", color="#89b4fa"))
        self.toggle_btn.setIconSize(QSize(20, 20))
        self.toggle_btn.clicked.connect(self._toggle_extra)
        self.header_layout.addWidget(self.toggle_btn)
        
        # Physical RAM
        self.ram_lbl = QLabel("Physical RAM:")
        self.ram_bar = QProgressBar()
        self.ram_info = QLabel("— / — GB")
        
        # Collapsible Cache & Buffers container
        self.extra_container = QWidget()
        self.extra_container.setVisible(False)
        extra_mem_layout = QHBoxLayout(self.extra_container)
        extra_mem_layout.setContentsMargins(0, 5, 0, 5)
        
        self.cache_vbox = QWidget()
        cache_layout = QVBoxLayout(self.cache_vbox)
        cache_layout.setContentsMargins(0, 0, 0, 0)
        self.cache_lbl = QLabel("Cache:")
        self.cache_lbl.setStyleSheet("font-size: 11px; color: #a0a0a0;")
        self.cache_bar = QProgressBar()
        # Task 2: Enlarge progress bars
        self.cache_bar.setMinimumHeight(18)
        self.cache_bar.setTextVisible(True)
        self.cache_bar.setStyleSheet("""
            QProgressBar {
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #313244;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
        """)
        self.cache_val = QLabel("0.00 GB")
        self.cache_val.setStyleSheet("font-size: 10px; color: #a0a0a0;")
        cache_layout.addWidget(self.cache_lbl)
        cache_layout.addWidget(self.cache_bar)
        cache_layout.addWidget(self.cache_val)
        
        self.buffers_vbox = QWidget()
        buffers_layout = QVBoxLayout(self.buffers_vbox)
        buffers_layout.setContentsMargins(0, 0, 0, 0)
        self.buffers_lbl = QLabel("Buffers:")
        self.buffers_lbl.setStyleSheet("font-size: 11px; color: #a0a0a0;")
        self.buffers_bar = QProgressBar()
        # Task 2: Enlarge progress bars
        self.buffers_bar.setMinimumHeight(18)
        self.buffers_bar.setTextVisible(True)
        self.buffers_bar.setStyleSheet("""
            QProgressBar {
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #313244;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
        """)
        self.buffers_val = QLabel("0.00 GB")
        self.buffers_val.setStyleSheet("font-size: 10px; color: #a0a0a0;")
        buffers_layout.addWidget(self.buffers_lbl)
        buffers_layout.addWidget(self.buffers_bar)
        buffers_layout.addWidget(self.buffers_val)
        
        extra_mem_layout.addWidget(self.cache_vbox)
        extra_mem_layout.addWidget(self.buffers_vbox)

        # Swap
        self.swap_lbl = QLabel("Swap Memory:")
        self.swap_bar = QProgressBar()
        self.swap_info = QLabel("— / — GB")
        
        self.main_layout.addWidget(self.ram_lbl)
        self.main_layout.addWidget(self.ram_bar)
        self.main_layout.addWidget(self.ram_info)
        self.main_layout.addSpacing(5)
        self.main_layout.addWidget(self.extra_container)
        self.main_layout.addSpacing(5)
        self.main_layout.addWidget(self.swap_lbl)
        self.main_layout.addWidget(self.swap_bar)
        self.main_layout.addWidget(self.swap_info)

    def _toggle_extra(self):
        is_visible = self.extra_container.isVisible()
        self.extra_container.setVisible(not is_visible)
        icon_name = "mdi.chevron-down" if is_visible else "mdi.chevron-up"
        self.toggle_btn.setIcon(qta.icon(icon_name, color="#89b4fa"))

    def update_stats(self, stats: SystemStatsDict):
        ram_pct = stats['ram_percent']
        total_ram = stats['ram_total_gb']
        self.ram_bar.setValue(int(ram_pct))
        self.ram_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {get_dynamic_color(ram_pct)}; }}")
        self.ram_info.setText(f"{stats['ram_used_gb']} / {total_ram} GB ({ram_pct}%)")
        
        # Cache & Buffers
        cached = stats.get('ram_cached_gb', 0)
        buffers = stats.get('ram_buffers_gb', 0)
        
        if total_ram > 0:
            self.cache_bar.setValue(int((cached / total_ram) * 100))
            self.buffers_bar.setValue(int((buffers / total_ram) * 100))
        
        self.cache_val.setText(f"{cached:.2f} GB")
        self.buffers_val.setText(f"{buffers:.2f} GB")

        swap_pct = stats['swap_percent']
        self.swap_bar.setValue(int(swap_pct))
        self.swap_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {get_dynamic_color(swap_pct)}; }}")
        self.swap_info.setText(f"{stats['swap_used_gb']} / {stats['swap_total_gb']} GB ({swap_pct}%)")

class GPUDetailCard(DetailCard):
    def __init__(self, parent=None):
        super().__init__("GPU DETAILS", parent)
        
        self.model_lbl = QLabel("Model: —")
        self.model_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #a855f7; margin-bottom: 5px;")
        
        self.vram_lbl = QLabel("VRAM Usage:")
        self.vram_bar = QProgressBar()
        self.vram_info = QLabel("— / — GB (—%)")
        
        # Task 3: Add icon before "GPU Fan Speed"
        fan_layout = QHBoxLayout()
        fan_layout.setSpacing(5)
        self.fan_icon = QLabel()
        self.fan_icon.setPixmap(qta.icon("mdi.fan", color="#ffffff").pixmap(16, 16))
        self.fan_lbl = QLabel("GPU Fan Speed: — RPM")
        self.fan_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        fan_layout.addWidget(self.fan_icon)
        fan_layout.addWidget(self.fan_lbl)
        fan_layout.addStretch()
        
        self.main_layout.addWidget(self.model_lbl)
        self.main_layout.addWidget(self.vram_lbl)
        self.main_layout.addWidget(self.vram_bar)
        self.main_layout.addWidget(self.vram_info)
        self.main_layout.addLayout(fan_layout)

    def update_stats(self, stats: SystemStatsDict):
        self.model_lbl.setText(f"Model: {stats.get('gpu_name', 'N/A')}")
        
        vram_pct = stats.get('gpu_vram_percent', 0.0)
        total = stats.get('gpu_vram_total_gb', 0.0)
        used = stats.get('gpu_vram_used_gb', 0.0)
        
        self.vram_bar.setValue(int(vram_pct))
        self.vram_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {get_dynamic_color(vram_pct)}; }}")
        self.vram_info.setText(f"{used:.2f} / {total:.2f} GB ({vram_pct}%)")
        
        fan_rpm = stats.get('gpu_fan_rpm', 0)
        self.fan_lbl.setText(f"GPU Fan Speed: {fan_rpm} RPM" if fan_rpm > 0 else "GPU Fan Speed: N/A")

class BatteryUptimeCard(DetailCard):
    def __init__(self, parent=None):
        super().__init__("BATTERY & UPTIME", parent)
        
        # Battery Section
        self.bat_lbl = QLabel("Battery Level:")
        self.bat_bar = QProgressBar()
        self.bat_status = QLabel("—% [—]")
        
        # Uptime Section
        self.uptime_header = QLabel("System Uptime:")
        self.uptime_header.setStyleSheet("margin-top: 15px; font-size: 14px; font-weight: bold; color: #ffffff;")
        self.uptime_val = QLabel("— Days, — Hours")
        self.uptime_val.setStyleSheet("font-size: 18px; font-weight: bold; color: #3fb950;")
        self.uptime_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.main_layout.addWidget(self.bat_lbl)
        self.main_layout.addWidget(self.bat_bar)
        self.main_layout.addWidget(self.bat_status)
        self.main_layout.addWidget(self.uptime_header)
        self.main_layout.addWidget(self.uptime_val)

    def update_stats(self, stats: SystemStatsDict):
        bat_pct = stats.get('battery_percent', 0.0)
        is_plugged = stats.get('battery_is_plugged', False)
        status_text = "Charging" if is_plugged else "Discharging"
        
        self.bat_bar.setValue(int(bat_pct))
        # Green to Red for battery
        color = "#3fb950" if bat_pct > 20 else "#f85149"
        self.bat_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")
        
        self.bat_status.setText(f"{bat_pct:.0f}% [{status_text}]")
        
        uptime = stats.get('uptime_str', '—')
        # Format "Xd Xh Xm" to a more friendly "X Days, X Hours"
        try:
            parts = uptime.split(' ')
            d = parts[0].replace('d', ' Days')
            h = parts[1].replace('h', ' Hours')
            self.uptime_val.setText(f"{d}, {h}")
        except Exception:
            self.uptime_val.setText(uptime)

class NetworkDetailCard(DetailCard):
    def __init__(self, parent=None):
        super().__init__("NETWORK TRAFFIC", parent)
        
        grid = QGridLayout()
        grid.setSpacing(10)
        
        # Task 3: Add icons before "Download" and "Upload"
        self.dl_icon = QLabel()
        self.dl_icon.setPixmap(qta.icon("mdi.download-network", color="#4f8ef7").pixmap(18, 18))
        self.dl_speed_lbl = QLabel("Download:")
        self.dl_speed_val = QLabel("0.00 MB/s")
        self.dl_speed_val.setStyleSheet("font-weight: bold; color: #4f8ef7; font-size: 13px;")
        
        self.ul_icon = QLabel()
        self.ul_icon.setPixmap(qta.icon("mdi.upload-network", color="#a371f7").pixmap(18, 18))
        self.ul_speed_lbl = QLabel("Upload:")
        self.ul_speed_val = QLabel("0.00 MB/s")
        self.ul_speed_val.setStyleSheet("font-weight: bold; color: #a371f7; font-size: 13px;")
        
        self.total_recv_lbl = QLabel("Total Received:")
        self.total_recv_val = QLabel("0.00 GB")
        self.total_sent_lbl = QLabel("Total Sent:")
        self.total_sent_val = QLabel("0.00 GB")
        
        # Layout arrangement
        dl_layout = QHBoxLayout()
        dl_layout.setSpacing(5)
        dl_layout.addWidget(self.dl_icon)
        dl_layout.addWidget(self.dl_speed_lbl)
        dl_layout.addWidget(self.dl_speed_val)
        dl_layout.addStretch()
        
        ul_layout = QHBoxLayout()
        ul_layout.setSpacing(5)
        ul_layout.addWidget(self.ul_icon)
        ul_layout.addWidget(self.ul_speed_lbl)
        ul_layout.addWidget(self.ul_speed_val)
        ul_layout.addStretch()
        
        grid.addLayout(dl_layout, 0, 0)
        grid.addLayout(ul_layout, 1, 0)
        grid.addWidget(self.total_recv_lbl, 0, 1)
        grid.addWidget(self.total_recv_val, 0, 2)
        grid.addWidget(self.total_sent_lbl, 1, 1)
        grid.addWidget(self.total_sent_val, 1, 2)
        
        self.main_layout.addLayout(grid)
        self.main_layout.addStretch()

    def update_stats(self, stats: SystemStatsDict):
        self.dl_speed_val.setText(f"{stats['net_download_speed']} MB/s")
        self.ul_speed_val.setText(f"{stats['net_upload_speed']} MB/s")
        self.total_recv_val.setText(f"{stats['net_total_recv']} GB")
        self.total_sent_val.setText(f"{stats['net_total_sent']} GB")

class StorageDetailCard(DetailCard):
    def __init__(self, parent=None):
        super().__init__("STORAGE USAGE", parent)
        
        self.bar = QProgressBar()
        self.info = QLabel("— / — GB (— Free)")
        
        # Disk speeds section
        speed_layout = QHBoxLayout()
        speed_layout.setSpacing(8)
        
        # Task 3: Add icons before "Disk Read" and "Disk Write", increase font size
        self.read_icon = QLabel()
        self.read_icon.setPixmap(qta.icon("mdi.download", color="#4f8ef7").pixmap(16, 16))
        self.read_speed_lbl = QLabel("Disk Read:")
        self.read_speed_lbl.setStyleSheet("font-size: 11px; color: #a0a0a0;")
        self.read_speed_val = QLabel("0.00 MB/s")
        self.read_speed_val.setStyleSheet("font-size: 13px; font-weight: bold; color: #4f8ef7;")
        
        self.write_icon = QLabel()
        self.write_icon.setPixmap(qta.icon("mdi.upload", color="#a371f7").pixmap(16, 16))
        self.write_speed_lbl = QLabel("Disk Write:")
        self.write_speed_lbl.setStyleSheet("font-size: 11px; color: #a0a0a0;")
        self.write_speed_val = QLabel("0.00 MB/s")
        self.write_speed_val.setStyleSheet("font-size: 13px; font-weight: bold; color: #a371f7;")
        
        speed_layout.addWidget(self.read_icon)
        speed_layout.addWidget(self.read_speed_lbl)
        speed_layout.addWidget(self.read_speed_val)
        speed_layout.addSpacing(10)
        speed_layout.addWidget(self.write_icon)
        speed_layout.addWidget(self.write_speed_lbl)
        speed_layout.addWidget(self.write_speed_val)
        speed_layout.addStretch()

        self.main_layout.addWidget(self.bar)
        self.main_layout.addWidget(self.info)
        self.main_layout.addSpacing(10)
        self.main_layout.addLayout(speed_layout)
        self.main_layout.addStretch()

    def update_stats(self, stats: SystemStatsDict):
        storage_pct = stats['storage_percent']
        self.bar.setValue(int(storage_pct))
        self.bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {get_dynamic_color(storage_pct)}; }}")
        self.info.setText(
            f"{stats['storage_used_gb']} GB used of {stats['storage_total_gb']} GB "
            f"({stats['storage_free_gb']} GB free)"
        )
        self.read_speed_val.setText(f"{stats.get('disk_read_speed', 0.0):.2f} MB/s")
        self.write_speed_val.setText(f"{stats.get('disk_write_speed', 0.0):.2f} MB/s")

# ---------------------------------------------------------------------------
# DashboardTab
# ---------------------------------------------------------------------------

class DashboardTab(QWidget):
    """
    The main Live Dashboard composite widget.

    Wire up worker signals externally after instantiation::

        tab = DashboardTab()
        monitor_worker.stats_ready.connect(tab.on_stats_update)
        weather_worker.weather_ready.connect(tab.on_weather_update)

    Gauge cards
    -----------
    - ``_cpu_card``  → blue accent  (#4f8ef7) — CPU utilisation %
    - ``_ram_card``  → purple accent (#a371f7) — RAM utilisation % + GB detail
    - ``_temp_card`` → green accent  (#3fb950) — CPU temperature °C (max 110)

    Thread-safety
    -------------
    Every public slot starts with ``sip.isdeleted(self)`` so that queued
    deliveries arriving after the widget is destroyed are silently dropped.
    A ``try/except RuntimeError`` block covers the narrow race window between
    the guard check and the actual Qt API call.
    """

    def __init__(self, nam: QNetworkAccessManager, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # The ENTIRE DashboardTab must consist of a SINGLE QScrollArea.
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background-color: transparent; border: none;")
        self.scroll_area.viewport().setStyleSheet("background-color: transparent;")
        
        # Master widget inside the scroll area
        master_widget = QWidget()
        master_widget.setStyleSheet("background-color: transparent;")
        master_layout = QVBoxLayout(master_widget)
        master_layout.setContentsMargins(10, 10, 10, 10)
        master_layout.setSpacing(12) # Reduced from 20 to use explicit spacing below gauges

        # 1. Top Section (Quick Overview)
        self.resources_group = self._build_resources_group()
        # Set QSizePolicy to Expanding so it can grow if needed
        self.resources_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Ensure it has a minimum height to prevent clipping
        self.resources_group.setMinimumHeight(280)
        master_layout.addWidget(self.resources_group)
        
        # Task 1: Fix Top Gauges Vertical Clipping & Add Breathing Room
        master_layout.addSpacerItem(QSpacerItem(20, 30, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        # 2. Bottom Section (Detailed Drill-down)
        detail_container = QWidget()
        detail_container.setStyleSheet("background-color: transparent;")
        
        # Grid for detailed cards with equal height rows
        self.detail_grid = QGridLayout(detail_container)
        self.detail_grid.setSpacing(20)
        self.detail_grid.setContentsMargins(0, 0, 0, 0)
        
        # Add Detailed Cards
        self.cpu_card = CPUDetailCard()
        self.ram_card = RAMDetailCard()
        self.gpu_card = GPUDetailCard()
        self.bat_card = BatteryUptimeCard()
        self.net_card = NetworkDetailCard()
        self.storage_card = StorageDetailCard()
        
        # Arrange in 2 columns
        self.detail_grid.addWidget(self.cpu_card, 0, 0)
        self.detail_grid.addWidget(self.ram_card, 0, 1)
        self.detail_grid.addWidget(self.gpu_card, 1, 0)
        self.detail_grid.addWidget(self.bat_card, 1, 1)
        self.detail_grid.addWidget(self.net_card, 2, 0)
        self.detail_grid.addWidget(self.storage_card, 2, 1)
        
        # Force equal row stretching
        self.detail_grid.setRowStretch(0, 1)
        self.detail_grid.setRowStretch(1, 1)
        self.detail_grid.setRowStretch(2, 1)
        
        master_layout.addWidget(detail_container)
        
        self.scroll_area.setWidget(master_widget)
        root.addWidget(self.scroll_area)

    def _build_resources_group(self) -> QGroupBox:
        """
        Build the 'System Resources' group containing four circular gauge cards
        inside a ResponsiveGaugeContainer.
        """
        group = QGroupBox("System Resources")
        
        # Main layout for the group - just contains the responsive container
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)
        
        self.responsive_container = ResponsiveGaugeContainer()

        # CPU card
        self._cpu_card = GaugeCard(
            title="CPU Usage",
            color=QColor("#4f8ef7"),
            label="CPU",
            max_value=100.0,
            unit="%",
        )
        
        # RAM card
        self._ram_card = GaugeCard(
            title="RAM Usage",
            color=QColor("#a371f7"),
            label="RAM",
            max_value=100.0,
            unit="%",
        )

        # CPU Temp card
        self._temp_card = GaugeCard(
            title="CPU Temp",
            color=QColor("#3fb950"),
            label="TEMP",
            max_value=110.0,
            unit="°C",
        )

        # GPU card (Replaced Storage)
        self._gpu_card = GaugeCard(
            title="GPU Usage",
            color=QColor("#a855f7"), # Neon Purple
            label="GPU",
            max_value=100.0,
            unit="%",
        )

        for card in (self._cpu_card, self._ram_card, self._temp_card, self._gpu_card):
            self.responsive_container.add_widget(card)

        layout.addWidget(self.responsive_container, 1)

        return group


    # ------------------------------------------------------------------
    # Slots – connected to worker signals from MainWindow
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def on_stats_update(self, stats: SystemStatsDict) -> None:
        """
        Receive a system stats dict from :class:`SystemMonitorWorker` and
        update all gauge cards and detailed cards.
        """
        if sip.isdeleted(self):
            return
        try:
            # Update Gauges
            self._cpu_card.update_value(stats.get("cpu_percent", 0.0))
            self._ram_card.update_value(stats.get("ram_percent", 0.0))

            self._temp_card.update_value(stats.get("cpu_temp_celsius", 0.0))
            self._gpu_card.update_value(stats.get("gpu_utilization", 0.0))

            # Update Detailed Cards
            self.cpu_card.update_stats(stats)
            self.ram_card.update_stats(stats)
            self.gpu_card.update_stats(stats)
            self.bat_card.update_stats(stats)
            self.net_card.update_stats(stats)
            self.storage_card.update_stats(stats)
        except RuntimeError:
            logger.debug("on_stats_update: widget deleted during update, skipping.")

    @pyqtSlot(dict)
    def on_weather_update(self, data: WeatherDataDict) -> None:
        """Receive a weather dict (ignored in dashboard)."""
        pass

    @pyqtSlot(dict)
    def on_monitor_error(self, error: ErrorInfo) -> None:
        """Display an error emitted by the system monitor worker."""
        if sip.isdeleted(self):
            return
        logger.error("Monitor error [%s]: %s", error.get("source"), error.get("message"))

    @pyqtSlot(dict)
    def on_weather_error(self, error: ErrorInfo) -> None:
        """Receive a weather error (ignored in dashboard)."""
        pass

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event: QEvent) -> None:
        """
        Pass the close event up the hierarchy.

        Worker threads are owned and managed by :class:`MainWindow`; this tab
        does not stop them directly.  The sip guards in the slots above ensure
        that any in-flight signal deliveries after this point are silently
        discarded.
        """
        logger.debug("DashboardTab.closeEvent: tab is closing.")
        super().closeEvent(event)
