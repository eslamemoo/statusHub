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
┌──────────────────────────────────────────────────────────────────────┐
│  System Resources                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  CPU USAGE   │  │  RAM USAGE   │  │       CPU TEMP           │  │
│  │    45.2 %    │  │   62.1 %     │  │      58.0 °C             │  │
│  │  ════════░░  │  │  ══════════░ │  │  ═══════░░░              │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────┤
│  Live Weather                                                        │
│  [icon]  City | Temp | Feels | Humidity | Wind | Condition          │
└──────────────────────────────────────────────────────────────────────┘

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
    QProgressBar,
    QGroupBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot, QEvent, QUrl
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

logger = logging.getLogger(__name__)

# OWM icon endpoint — {code} is a two-char code + 'd'/'n', e.g. "01d".
_OWM_ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"
_ICON_SIZE = 56   # px — display size of the weather icon label


# ---------------------------------------------------------------------------
# MetricCard
# ---------------------------------------------------------------------------

class MetricCard(QWidget):
    """
    A self-contained card showing a title, a large value label, and a
    styled QProgressBar acting as a sleek gauge.

    Parameters
    ----------
    title:
        Human-readable metric name (e.g. "CPU Usage"). Rendered uppercased.
    unit:
        Unit suffix appended to the numeric value (e.g. "%" or "°C").
    bar_object_name:
        objectName for the inner QProgressBar — used by the global QSS to
        apply distinct accent colours per resource.
    bar_max:
        Maximum value for the progress bar.  Defaults to 100 (percent).
    parent:
        Optional Qt parent widget.
    """

    def __init__(
        self,
        title: str,
        unit: str = "%",
        bar_object_name: str = "metricBar",
        bar_max: int = 100,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._unit = unit
        self._bar_max = bar_max
        self._bar_object_name = bar_object_name
        self._build_ui(title)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self, title: str) -> None:
        """Build the internal layout: title → value → gauge bar."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(12)

        # ── Title label ────────────────────────────────────────────────
        title_lbl = QLabel(title.upper())
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setObjectName("cardTitle")

        # ── Large numeric value ────────────────────────────────────────
        self._value_lbl = QLabel(f"0 {self._unit}")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setObjectName("cardValue")
        val_font = QFont()
        val_font.setPointSize(28)
        val_font.setWeight(QFont.Weight.ExtraBold)
        self._value_lbl.setFont(val_font)

        # ── Sleek rounded gauge bar ────────────────────────────────────
        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(self._bar_max)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(12)
        self._bar.setObjectName(self._bar_object_name)

        layout.addWidget(title_lbl)
        layout.addWidget(self._value_lbl)
        layout.addWidget(self._bar)

        self.setObjectName("metricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # Ensure cards have a minimum comfortable height.
        self.setMinimumHeight(140)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_value(self, value: float) -> None:
        """
        Update the value label and the gauge bar.

        Thread-safe: the ``sip.isdeleted`` guard and ``RuntimeError`` catch
        ensure a silent no-op if the C++ widget is being destroyed.
        """
        if sip.isdeleted(self):
            return
        try:
            self._value_lbl.setText(f"{value:.1f} {self._unit}")
            self._bar.setValue(min(int(value), self._bar_max))
        except RuntimeError:
            logger.debug("MetricCard.update_value: widget deleted, skipping.")


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

    def __init__(self, parent=None) -> None:
        super().__init__("🌤  Live Weather", parent)
        # One shared network manager — reused across icon fetches.
        self._nam = QNetworkAccessManager(self)
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
# DashboardTab
# ---------------------------------------------------------------------------

class DashboardTab(QWidget):
    """
    The main Live Dashboard composite widget.

    Wire up worker signals externally after instantiation::

        tab = DashboardTab()
        monitor_worker.stats_ready.connect(tab.on_stats_update)
        weather_worker.weather_ready.connect(tab.on_weather_update)

    Cards
    -----
    - ``_cpu_card``  → objectName ``metricBarCpu``   (vibrant blue gradient)
    - ``_ram_card``  → objectName ``metricBarRam``   (vivid purple gradient)
    - ``_temp_card`` → objectName ``metricBarTemp``  (rich green gradient, max 110 °C)

    The RAM card also shows a secondary "X.XX GB / Y.YY GB" detail label
    rendered inside its own card layout.

    Thread-safety
    -------------
    Every public slot starts with ``sip.isdeleted(self)`` so that queued
    deliveries arriving after the widget is destroyed are silently dropped.
    A ``try/except RuntimeError`` block covers the narrow race window between
    the guard check and the actual Qt API call.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        root.addWidget(self._build_resources_group())
        root.addWidget(self._build_weather_group())
        root.addStretch()

        # Live status label (bottom of the tab)
        self._status_lbl = QLabel("⏳  Waiting for first data…")
        self._status_lbl.setObjectName("statusLabel")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self._status_lbl)

    def _build_resources_group(self) -> QGroupBox:
        """Build the 'System Resources' group containing three metric cards."""
        group = QGroupBox("💻  System Resources")
        layout = QHBoxLayout(group)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 24, 16, 16)

        # CPU card — vibrant blue bar
        self._cpu_card = MetricCard(
            title="CPU Usage",
            unit="%",
            bar_object_name="metricBarCpu",
        )

        # RAM card — vivid purple bar + GB detail label
        self._ram_card = MetricCard(
            title="RAM Usage",
            unit="%",
            bar_object_name="metricBarRam",
        )
        self._ram_detail_lbl = QLabel("— GB / — GB")
        self._ram_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ram_detail_lbl.setObjectName("ramDetail")
        # Append the detail label below the gauge bar inside the card layout.
        self._ram_card.layout().addWidget(self._ram_detail_lbl)

        # Temp card — rich green bar, scale 0–110 °C
        self._temp_card = MetricCard(
            title="CPU Temp",
            unit="°C",
            bar_object_name="metricBarTemp",
            bar_max=110,
        )

        for card in (self._cpu_card, self._ram_card, self._temp_card):
            layout.addWidget(card)

        return group

    def _build_weather_group(self) -> QWidget:
        """Return the WeatherPanel (already a QGroupBox subclass)."""
        self._weather_panel = WeatherPanel()
        return self._weather_panel

    # ------------------------------------------------------------------
    # Slots – connected to worker signals from MainWindow
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def on_stats_update(self, stats: dict) -> None:
        """
        Receive a system stats dict from :class:`SystemMonitorWorker` and
        update all metric cards.

        Expected keys: ``cpu_percent``, ``ram_percent``, ``ram_used_gb``,
        ``ram_total_gb``, ``cpu_temp_celsius``.
        """
        if sip.isdeleted(self):
            return
        try:
            self._cpu_card.update_value(stats.get("cpu_percent", 0.0))
            self._ram_card.update_value(stats.get("ram_percent", 0.0))

            ram_used  = stats.get("ram_used_gb", 0.0)
            ram_total = stats.get("ram_total_gb", 0.0)
            self._ram_detail_lbl.setText(f"{ram_used:.2f} GB / {ram_total:.2f} GB")

            self._temp_card.update_value(stats.get("cpu_temp_celsius", 0.0))

            self._status_lbl.setText("✅  Live – receiving system data")
        except RuntimeError:
            logger.debug("on_stats_update: widget deleted during update, skipping.")

    @pyqtSlot(dict)
    def on_weather_update(self, data: dict) -> None:
        """Receive a weather dict from :class:`WeatherFetcherWorker` and refresh the panel."""
        if sip.isdeleted(self):
            return
        try:
            self._weather_panel.update_weather(data)
        except RuntimeError:
            logger.debug("on_weather_update: widget deleted during update, skipping.")

    @pyqtSlot(str)
    def on_monitor_error(self, message: str) -> None:
        """Display an error emitted by the system monitor worker."""
        if sip.isdeleted(self):
            return
        try:
            self._status_lbl.setText(f"⚠️  Monitor error: {message}")
        except RuntimeError:
            logger.debug("on_monitor_error: widget deleted during update, skipping.")

    @pyqtSlot(str)
    def on_weather_error(self, message: str) -> None:
        """Display an error emitted by the weather fetcher worker."""
        if sip.isdeleted(self):
            return
        try:
            self._weather_panel.setTitle(f"🌤  Live Weather  ⚠️  {message}")
        except RuntimeError:
            logger.debug("on_weather_error: widget deleted during update, skipping.")

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
