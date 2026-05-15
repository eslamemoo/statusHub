"""
main_window.py
==============
The top-level QMainWindow for StatusHub.

Responsibilities
----------------
- Own and start all background worker threads (SystemMonitorWorker,
  WeatherFetcherWorker).
- Expose a SerialManager instance shared across tabs.
- Host a sidebar navigation (via QStackedWidget + QPushButton nav items)
  that switches between the Dashboard and Theme Builder views.
- Apply the global application stylesheet.
- Gracefully stop all threads on close.
"""

import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QLabel, QSizePolicy,
    QStatusBar, QFrame,
)
from PyQt6.QtCore import Qt, QSize, pyqtSlot
from PyQt6.QtGui import QIcon, QFont

from src.core.sys_monitor import SystemMonitorWorker
from src.core.weather_fetcher import WeatherFetcherWorker
from src.core.serial_manager import SerialManager
from src.ui.dashboard_tab import DashboardTab
from src.ui.theme_builder_tab import ThemeBuilderTab
from src.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sidebar navigation button
# ---------------------------------------------------------------------------

class NavButton(QPushButton):
    """A styled sidebar navigation button with an icon + label layout."""

    def __init__(self, icon_char: str, label: str, parent=None) -> None:
        super().__init__(f"  {icon_char}  {label}", parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("navButton")
        self.setMinimumHeight(48)
        self.setMinimumWidth(180)
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """
    Top-level application window.

    Parameters
    ----------
    config:
        A pre-initialised :class:`~src.utils.config_manager.ConfigManager`
        instance. The window reads initial settings (window size, weather
        credentials) from it.
    """

    APP_NAME = "StatusHub"
    APP_VERSION = "0.1.0"

    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._init_workers()
        self._build_ui()
        self._connect_signals()
        self._start_workers()
        logger.info("%s %s started.", self.APP_NAME, self.APP_VERSION)

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _init_workers(self) -> None:
        """Instantiate all background workers and shared services."""
        poll_sec = self._config.get("monitor.poll_interval_seconds", 2.0)
        self._monitor_worker = SystemMonitorWorker(poll_interval_seconds=poll_sec)

        api_key  = self._config.get("weather.api_key", "")
        city     = self._config.get("weather.city", "Cairo")
        w_poll   = self._config.get("weather.poll_interval_seconds", 600)
        self._weather_worker = WeatherFetcherWorker(
            api_key=api_key,
            city=city,
            poll_interval_seconds=w_poll,
        )

        self._serial_manager = SerialManager(parent=self)

    def _start_workers(self) -> None:
        """Start background threads after the UI is fully assembled."""
        self._monitor_worker.start()
        self._weather_worker.start()
        logger.debug("Background workers started.")

    def _stop_workers(self) -> None:
        """Cleanly stop all background threads."""
        self._monitor_worker.stop()
        self._weather_worker.stop()
        self._monitor_worker.wait(3000)   # max 3 s grace period
        self._weather_worker.wait(3000)
        logger.debug("Background workers stopped.")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Assemble the main window layout: sidebar + stacked content area."""
        self.setWindowTitle(f"{self.APP_NAME}  —  Control Center  v{self.APP_VERSION}")
        self.setMinimumSize(1000, 650)

        # Restore last window size from config
        w = self._config.get("app.window_width", 1200)
        h = self._config.get("app.window_height", 750)
        self.resize(w, h)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = self._build_sidebar()
        main_layout.addWidget(sidebar)

        # Vertical separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("sidebarSeparator")
        main_layout.addWidget(separator)

        # Stacked content pages
        self._stack = QStackedWidget()
        self._dashboard_tab = DashboardTab()
        self._theme_tab = ThemeBuilderTab()
        self._stack.addWidget(self._dashboard_tab)   # index 0
        self._stack.addWidget(self._theme_tab)        # index 1
        main_layout.addWidget(self._stack, stretch=1)

        # Status bar
        self._status_bar = QStatusBar()
        self._status_bar.setObjectName("appStatusBar")
        self.setStatusBar(self._status_bar)
        self._serial_status_lbl = QLabel("🔌  Serial: disconnected")
        self._status_bar.addPermanentWidget(self._serial_status_lbl)
        self._status_bar.showMessage("StatusHub ready.")

    def _build_sidebar(self) -> QWidget:
        """Build the left navigation sidebar."""
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # App logo / header
        header = QLabel(f"  🖥  {self.APP_NAME}")
        header.setObjectName("sidebarHeader")
        header.setFixedHeight(60)
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)

        # Navigation buttons
        self._nav_dashboard = NavButton("📊", "Dashboard")
        self._nav_theme     = NavButton("🎨", "Theme Builder")

        self._nav_dashboard.setChecked(True)   # default page
        self._nav_dashboard.clicked.connect(lambda: self._switch_page(0))
        self._nav_theme.clicked.connect(lambda: self._switch_page(1))

        layout.addWidget(self._nav_dashboard)
        layout.addWidget(self._nav_theme)
        layout.addStretch()

        # Version label at the bottom of the sidebar
        version_lbl = QLabel(f"  v{self.APP_VERSION}")
        version_lbl.setObjectName("sidebarVersion")
        version_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(version_lbl)

        return sidebar

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Wire all worker signals to the appropriate UI slots."""
        # System monitor → dashboard
        self._monitor_worker.stats_ready.connect(self._dashboard_tab.on_stats_update)
        self._monitor_worker.error_occurred.connect(self._dashboard_tab.on_monitor_error)

        # Weather → dashboard
        self._weather_worker.weather_ready.connect(self._dashboard_tab.on_weather_update)
        self._weather_worker.fetch_error.connect(self._dashboard_tab.on_weather_error)

        # Serial manager → status bar
        self._serial_manager.connected.connect(self._on_serial_connected)
        self._serial_manager.disconnected.connect(self._on_serial_disconnected)
        self._serial_manager.send_error.connect(self._on_serial_error)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _switch_page(self, index: int) -> None:
        """Switch the stacked widget and update nav button checked states."""
        self._stack.setCurrentIndex(index)
        self._nav_dashboard.setChecked(index == 0)
        self._nav_theme.setChecked(index == 1)

    @pyqtSlot(str)
    def _on_serial_connected(self, port: str) -> None:
        self._serial_status_lbl.setText(f"🔗  Serial: {port}")
        self._status_bar.showMessage(f"Connected to {port}.")

    @pyqtSlot()
    def _on_serial_disconnected(self) -> None:
        self._serial_status_lbl.setText("🔌  Serial: disconnected")
        self._status_bar.showMessage("Serial connection closed.")

    @pyqtSlot(str)
    def _on_serial_error(self, message: str) -> None:
        self._status_bar.showMessage(f"⚠️  Serial error: {message}", 5000)

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Save window geometry and stop workers before closing."""
        self._config.set("app.window_width", self.width())
        self._config.set("app.window_height", self.height())
        self._config.save()

        self._stop_workers()
        self._serial_manager.disconnect()
        super().closeEvent(event)
