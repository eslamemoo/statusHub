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

from PyQt6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QSize, Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QResizeEvent
from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from src.core.serial_manager import SerialManager
from src.core.sys_monitor import SystemMonitorWorker
from src.core.weather_fetcher import WeatherFetcherWorker
from src.ui.dashboard_tab import DashboardTab
from src.ui.splash_screen import SplashScreen
from src.ui.theme_builder_tab import ThemeBuilderTab
from src.ui.weather_tab import WeatherTab
from src.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sidebar navigation button
# ---------------------------------------------------------------------------

class NavButton(QPushButton):
    """A styled sidebar navigation button with an icon + label layout."""

    def __init__(self, icon_name: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self._label_text = label
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("navButton")
        self.setMinimumHeight(50)
        
        # Initialise icon and text visibility
        self._icon = qta.icon(icon_name, color="#89b4fa", color_active="#ffffff")
        self.setIcon(self._icon)
        self.setIconSize(QSize(22, 22))
        self.setText(f"  {label}")
        
        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Medium)
        self.setFont(font)
        
        # Default style for expanded state
        self._expanded_qss = """
            QPushButton {
                text-align: left;
                padding-left: 20px;
                border: none;
                background: transparent;
                color: #a6adc8;
                border-radius: 10px;
                margin: 4px 12px;
            }
            QPushButton:hover {
                background-color: #1e1e2e;
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: #313244;
                color: #3b82f6;
                font-weight: bold;
            }
        """
        # Style for centered icon when text is hidden
        self._collapsed_qss = """
            QPushButton {
                text-align: center;
                padding: 0px;
                margin: 4px 8px;
                border: none;
                background: transparent;
                color: #a6adc8;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #1e1e2e;
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: #313244;
                color: #3b82f6;
            }
        """
        self.setStyleSheet(self._expanded_qss)

    def set_collapsed(self, collapsed: bool) -> None:
        """Update the button appearance for collapsed or expanded state."""
        if collapsed:
            self.setText("")
            self.setToolTip(self._label_text)
            self.setStyleSheet(self._collapsed_qss)
        else:
            self.setText(f"  {self._label_text}")
            self.setToolTip("")
            self.setStyleSheet(self._expanded_qss)


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

    def __init__(self, config: ConfigManager, splash: SplashScreen = None, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._splash = splash
        self._is_collapsed = False
        self._sidebar_animation = None

        # Tracks whether the sidebar was collapsed automatically by the
        # responsive resize logic (as opposed to a manual user toggle).
        # Keeping this separate from _is_collapsed prevents the auto-collapse
        # from fighting user-initiated expand/collapse actions.
        self._sidebar_auto_collapsed = False

        # Hybrid initialization flags
        self._min_time_elapsed = False
        self._first_data_received = False
        self._init_complete_triggered = False

        self._init_workers()
        self._build_ui()
        self._connect_signals()
        self._start_workers()

        if self._splash:
            self._splash.start_progress_animation(3500)
            self._splash.animation_finished.connect(self._on_min_time_elapsed)
            QTimer.singleShot(6000, self._force_initialization)

        logger.info("%s %s started.", self.APP_NAME, self.APP_VERSION)

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _init_workers(self) -> None:
        """Instantiate all background workers and shared services."""
        self._nam = QNetworkAccessManager(self)

        self._monitor_thread = QThread()
        poll_sec = self._config.get("monitor.poll_interval_seconds", 2.0)
        self._monitor_worker = SystemMonitorWorker(poll_interval_seconds=poll_sec)
        self._monitor_worker.moveToThread(self._monitor_thread)
        self._monitor_thread.started.connect(self._monitor_worker.start_monitoring)

        self._weather_thread = QThread()
        api_key  = self._config.get("weather.api_key", "")
        city     = self._config.get("weather.city", "Cairo")
        w_poll   = self._config.get("weather.poll_interval_seconds", 600)
        self._weather_worker = WeatherFetcherWorker(
            api_key=api_key,
            city=city,
            poll_interval_seconds=w_poll,
        )
        self._weather_worker.moveToThread(self._weather_thread)
        self._weather_thread.started.connect(self._weather_worker.start_fetching)

        self._serial_manager = SerialManager(parent=self)

    def _start_workers(self) -> None:
        """Start background threads after the UI is fully assembled."""
        self._monitor_thread.start()
        self._weather_thread.start()
        logger.debug("Background worker threads started.")

    def _stop_workers(self) -> None:
        """Cleanly stop all background threads."""
        self._monitor_worker.stop()
        self._weather_worker.stop()

        self._monitor_thread.quit()
        self._weather_thread.quit()

        self._monitor_thread.wait(3000)
        self._weather_thread.wait(3000)
        logger.debug("Background worker threads stopped.")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Assemble the main window layout: sidebar + stacked content area."""
        self.setWindowTitle(f"{self.APP_NAME}  —  Control Center  v{self.APP_VERSION}")
        # Hard minimum: 840 px wide ensures the collapsed mini-sidebar (65 px)
        # plus the 2-column detail-card layout (≈775 px of content space) all
        # render fully with zero right-edge clipping at the narrowest allowed size.
        self.setMinimumSize(840, 550)

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
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("sidebarSeparator")
        main_layout.addWidget(separator)

        # Right-side content layout
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        main_layout.addLayout(content_layout, stretch=1)

        # Stacked content pages
        self._stack = QStackedWidget()
        self._dashboard_tab = DashboardTab(nam=self._nam)
        self._weather_tab = WeatherTab()
        self._theme_tab = ThemeBuilderTab()
        self._stack.addWidget(self._dashboard_tab)   # index 0
        self._stack.addWidget(self._weather_tab)     # index 1
        self._stack.addWidget(self._theme_tab)       # index 2
        content_layout.addWidget(self._stack, stretch=1)

        self._build_status_bar()

    def _build_status_bar(self) -> None:
        """Footer status bar — compact, fixed-height, unified typography."""
        self._status_bar = QStatusBar()
        self._status_bar.setObjectName("appStatusBar")
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setStyleSheet("""
            QStatusBar {
                background: transparent;
                border-top: 1px solid #2a2a3e;
                min-height: 28px;
                max-height: 28px;
            }
            QStatusBar::item {
                border: none;
            }
            QLabel {
                color: #b0b0b0;
                font-size: 13px;
                font-weight: 400;
                padding: 0px;
                background: transparent;
            }
        """)
        self.setStatusBar(self._status_bar)

        self._live_status_lbl = QLabel("●  Live — receiving system data")
        self._live_status_lbl.setStyleSheet(
            "color: #b0b0b0; font-size: 13px; font-weight: 400;"
            "margin-left: 8px; background: transparent;"
        )
        self._status_bar.addWidget(self._live_status_lbl, 1)

        self._serial_status_lbl = QLabel("🔌  Serial: disconnected")
        self._serial_status_lbl.setStyleSheet(
            "color: #b0b0b0; font-size: 13px; font-weight: 400;"
            "margin-right: 8px; background: transparent;"
        )
        self._status_bar.addPermanentWidget(self._serial_status_lbl)

    def _build_sidebar(self) -> QWidget:
        """Build the left navigation sidebar."""
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        # Use explicit min/max instead of setFixedWidth so the slide animation
        # can freely adjust both constraints without fighting a fixed size.
        self._sidebar.setMinimumWidth(220)
        self._sidebar.setMaximumWidth(220)

        layout = QVBoxLayout(self._sidebar)
        layout.setContentsMargins(0, 15, 0, 8)
        layout.setSpacing(4)

        # ── Sidebar Header (Menu + Logo) ───────────────────────────
        header_container = QWidget()
        header_container.setObjectName("sidebarHeaderContainer")
        header_container.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(5, 0, 5, 0)
        header_layout.setSpacing(2)

        # Toggle Button (Hamburger)
        self._toggle_btn = QPushButton()
        self._toggle_btn.setIcon(qta.icon("mdi.menu", color="#89b4fa"))
        self._toggle_btn.setIconSize(QSize(24, 24))
        self._toggle_btn.setFixedSize(55, 50)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet("border: none; background: transparent;")
        self._toggle_btn.clicked.connect(self._on_toggle_btn_clicked)
        header_layout.addWidget(self._toggle_btn)

        # App logo / header label
        self._header_label = QLabel()
        self._header_label.setObjectName("sidebarHeader")
        self._header_label.setText("<span style='color: #ffffff;'>Status</span><span style='color: #3b82f6;'>Hub</span>")
        header_font = QFont()
        header_font.setPointSize(18)
        header_font.setBold(True)
        self._header_label.setFont(header_font)
        self._header_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._header_label.setStyleSheet("QLabel { background: transparent; border: none; font-weight: bold; }")
        header_layout.addWidget(self._header_label)
        header_layout.addStretch()

        layout.addWidget(header_container)
        # ───────────────────────────────────────────────────────────

        # Navigation buttons
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self._nav_dashboard = NavButton("mdi.view-dashboard", "Dashboard")
        self._nav_weather   = NavButton("mdi.weather-partly-cloudy", "Weather")
        self._nav_theme     = NavButton("mdi.palette", "Theme Builder")

        self._nav_group.addButton(self._nav_dashboard, 0)
        self._nav_group.addButton(self._nav_weather, 1)
        self._nav_group.addButton(self._nav_theme, 2)

        self._nav_dashboard.setChecked(True)   # default page
        
        self._nav_group.idClicked.connect(self._switch_page)

        layout.addWidget(self._nav_dashboard)
        layout.addWidget(self._nav_weather)
        layout.addWidget(self._nav_theme)
        layout.addStretch()

        return self._sidebar

    def _animate_sidebar(self, collapse: bool) -> None:
        """Smoothly animate sidebar width and update its content state."""
        if self._is_collapsed == collapse:
            return
        
        self._is_collapsed = collapse
        
        # Determine target width
        start_w = 220 if collapse else 65
        end_w = 65 if collapse else 220
        
        # Cleanly update text/icons before/after animation starts
        for btn in (self._nav_dashboard, self._nav_weather, self._nav_theme):
            btn.set_collapsed(collapse)
            
        if collapse:
            self._header_label.hide()
        else:
            self._header_label.show()

        # Setup animation
        if self._sidebar_animation and self._sidebar_animation.state() == QPropertyAnimation.State.Running:
            self._sidebar_animation.stop()

        self._sidebar_animation = QPropertyAnimation(self._sidebar, b"minimumWidth")
        self._sidebar_animation.setDuration(250)
        self._sidebar_animation.setStartValue(start_w)
        self._sidebar_animation.setEndValue(end_w)
        self._sidebar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Sync maximumWidth to minimumWidth during animation to force resize
        self._sidebar_animation.valueChanged.connect(lambda v: self._sidebar.setMaximumWidth(v))
        
        self._sidebar_animation.start()

    def _on_toggle_btn_clicked(self) -> None:
        """
        Handle a manual hamburger-button click.

        When the user explicitly expands the sidebar at a width that would
        normally keep it collapsed, clear the auto-collapse flag so the
        resize logic does not immediately re-collapse it.
        When the user manually collapses it, mark it as a manual collapse so
        the resize logic does not try to re-expand it at wide widths.
        """
        target_collapsed = not self._is_collapsed

        if not target_collapsed:
            # User is manually expanding — clear the auto flag so resizeEvent
            # does not override this action until the window goes narrow again.
            self._sidebar_auto_collapsed = False

        self._animate_sidebar(target_collapsed)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """
        Automatically collapse or expand the sidebar based on the window width.

        Two separate thresholds create a hysteresis band that prevents rapid
        oscillation when the window is resized near the boundary:

        - Collapse trigger : width drops below 850 px
        - Expand  trigger  : width rises above 900 px

        The auto flag (``_sidebar_auto_collapsed``) is kept entirely separate
        from the manual toggle flag (``_is_collapsed``) so that user-initiated
        collapse/expand actions are never overridden by resize events.
        """
        super().resizeEvent(event)
        width = event.size().width()

        # ── Collapse threshold ───────────────────────────────────────────
        # Fires when the window narrows below 900 px, freeing ~835 px of
        # content space for the 2-column card layout before it can clip.
        if width < 900 and not self._sidebar_auto_collapsed and not self._is_collapsed:
            self._sidebar_auto_collapsed = True
            self._animate_sidebar(True)

        # ── Expand threshold (80 px hysteresis buffer) ───────────────────
        # Only restores the sidebar when this logic originally collapsed it
        # AND the window has grown wide enough to comfortably host it again.
        elif width > 980 and self._sidebar_auto_collapsed:
            self._sidebar_auto_collapsed = False
            self._animate_sidebar(False)

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Wire all worker signals to the appropriate UI slots."""
        # System monitor → dashboard
        self._monitor_worker.stats_ready.connect(self._dashboard_tab.on_stats_update)
        self._monitor_worker.stats_ready.connect(self._on_stats_ready)
        self._monitor_worker.error_occurred.connect(self._dashboard_tab.on_monitor_error)
        self._monitor_worker.error_occurred.connect(self._on_monitor_error)

        # Weather → dashboard & weather tab
        self._weather_worker.weather_ready.connect(self._dashboard_tab.on_weather_update)
        self._weather_worker.weather_ready.connect(self._weather_tab.on_weather_update)
        self._weather_worker.fetch_error.connect(self._dashboard_tab.on_weather_error)

        # Serial manager → status bar
        self._serial_manager.connected.connect(self._on_serial_connected)
        self._serial_manager.disconnected.connect(self._on_serial_disconnected)
        self._serial_manager.send_error.connect(self._on_serial_error)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def _on_stats_ready(self, stats: dict) -> None:
        """Handle the first successful data packet from the monitor worker."""
        if not self._first_data_received:
            self._first_data_received = True
            self._check_initialization_complete()

    def _on_min_time_elapsed(self) -> None:
        """Called when the 3.5s minimum splash animation has finished."""
        self._min_time_elapsed = True
        self._check_initialization_complete()

    def _force_initialization(self) -> None:
        """Safety timeout to prevent permanent lockup if sensors fail."""
        if not self._init_complete_triggered:
            logger.warning("Initialization safety timeout reached. Forcing UI display.")
            self._min_time_elapsed = True
            self._first_data_received = True
            self._check_initialization_complete()

    def _check_initialization_complete(self) -> None:
        """
        Evaluate initialization conditions.
        Triggers UI display only when both minimum time and data handshake are met.
        """
        if self._init_complete_triggered:
            return

        if self._min_time_elapsed and self._first_data_received:
            self._init_complete_triggered = True
            if self._splash:
                self._splash.fade_out(self._show_main_window)
            else:
                self._show_main_window()

    def _show_main_window(self) -> None:
        """Final step of initialization: close splash and show main window."""
        if self._splash:
            self._splash.close()
        self.show()

    @pyqtSlot(dict)
    def _on_monitor_error(self, error: dict) -> None:
        """Show a transient monitor error in the left footer label, then revert."""
        msg = error.get("message", "Unknown error")
        self._live_status_lbl.setText(f"⚠️  Monitor error: {msg}")
        # Revert to the default live indicator after 5 seconds.
        QTimer.singleShot(5000, lambda: self._live_status_lbl.setText("●  Live — receiving system data"))

    @pyqtSlot(int)
    def _switch_page(self, index: int) -> None:
        """Switch the stacked widget page with a smooth crossfade transition."""
        # Task 2: Prevent unchecking the already active button
        clicked_button = self._nav_group.button(index)
        if clicked_button and not clicked_button.isChecked():
            clicked_button.setChecked(True)

        if self._stack.currentIndex() == index:
            return

        old_widget = self._stack.currentWidget()
        new_widget = self._stack.widget(index)
        
        # Prepare effects
        old_eff = QGraphicsOpacityEffect(old_widget)
        new_eff = QGraphicsOpacityEffect(new_widget)
        old_widget.setGraphicsEffect(old_eff)
        new_widget.setGraphicsEffect(new_eff)
        
        # Animations
        duration = 180 # Snappy 180ms
        
        # Fade out old
        anim_out = QPropertyAnimation(old_eff, b"opacity")
        anim_out.setDuration(duration)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Fade in new
        anim_in = QPropertyAnimation(new_eff, b"opacity")
        anim_in.setDuration(duration)
        anim_in.setStartValue(0.0)
        anim_in.setEndValue(1.0)
        anim_in.setEasingCurve(QEasingCurve.Type.InCubic)
        
        self._transition_group = QParallelAnimationGroup()
        self._transition_group.addAnimation(anim_out)
        self._transition_group.addAnimation(anim_in)
        
        def on_finished():
            self._stack.setCurrentIndex(index)
            old_widget.setGraphicsEffect(None)
            new_widget.setGraphicsEffect(None)
            # Ensure the new widget is fully opaque after transition
            new_widget.show()
            
        self._transition_group.finished.connect(on_finished)
        
        # We need to make sure the new widget is visible during transition
        # QStackedWidget only shows one at a time, so we might need a trick
        # or just switch index and fade in. 
        # Better: Switch index immediately, but keep old widget rendered? 
        # Actually, for a simple crossfade in QStackedWidget:
        # 1. Show new widget (it will overlap if we are careful, but QStackedWidget doesn't)
        # Standard QStackedWidget transition:
        self._stack.setCurrentIndex(index)
        new_widget.setGraphicsEffect(new_eff) # Re-apply because setCurrentIndex might reset
        self._transition_group.start()

    @pyqtSlot(str)
    def _on_serial_connected(self, port: str) -> None:
        """Update both footer labels when a serial port connects."""
        self._serial_status_lbl.setText(f"🔗  Serial: {port}")
        self._live_status_lbl.setText(f"Connected to {port}.")
        QTimer.singleShot(4000, lambda: self._live_status_lbl.setText("●  Live — receiving system data"))

    @pyqtSlot()
    def _on_serial_disconnected(self) -> None:
        """Reset the serial label and show a brief notification on the left."""
        self._serial_status_lbl.setText("🔌  Serial: disconnected")
        self._live_status_lbl.setText("Serial connection closed.")
        QTimer.singleShot(4000, lambda: self._live_status_lbl.setText("●  Live — receiving system data"))

    @pyqtSlot(str)
    def _on_serial_error(self, message: str) -> None:
        """Show a transient serial error in the left footer label, then revert."""
        self._live_status_lbl.setText(f"⚠️  Serial error: {message}")
        QTimer.singleShot(5000, lambda: self._live_status_lbl.setText("●  Live — receiving system data"))

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
