"""
main.py
=======
Entry point for the StatusHub desktop application.

Responsibilities
----------------
1. Initialise the Python logging subsystem.
2. Instantiate the :class:`~src.utils.config_manager.ConfigManager`.
3. Create the :class:`QApplication` and apply the dark-mode stylesheet.
4. Instantiate and show :class:`~src.ui.main_window.MainWindow`.
5. Start the Qt event loop and exit cleanly.

Usage
-----
    python main.py
"""

import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from src.ui.main_window import MainWindow
from src.ui.splash_screen import SplashScreen
from src.utils.config_manager import ConfigManager


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    """Set up a human-readable console + file log handler."""
    log_format = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("statushub.log", encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
# Global stylesheet — premium dark theme
# ---------------------------------------------------------------------------

DARK_STYLESHEET = """
/* ════════════════════════════════════════════════════════════════════
   STATUShub — Premium Dark Theme
   Palette
     base ............... #121212   deepest background layer
     surface ............ #1e1e2a   card / panel surfaces
     surface-raised ..... #252535   elevated elements (group titles, inputs)
     border ............. #2d2d42   subtle border
     border-focus ....... #4f8ef7   accent blue for focus glow
     accent-blue ........ #4f8ef7
     accent-purple ...... #a371f7
     accent-green ....... #3fb950
     text-primary ....... #e8eaf0
     text-muted ......... #6b7280
   ════════════════════════════════════════════════════════════════════ */

/* ── 1. Global reset ────────────────────────────────────────────────── */
* {
    font-family: "Inter", "Segoe UI", "SF Pro Display", sans-serif;
    color: #e8eaf0;
    outline: none;
}

QMainWindow, QDialog {
    background-color: #121212;
}

QWidget {
    background-color: #121212;
}

/* ── 2. Sidebar ─────────────────────────────────────────────────────── */
QWidget#sidebar {
    background-color: #0c0c14;
    border-right: 1px solid #2d2d42;
}

QLabel#sidebarHeader {
    background-color: transparent;
    color: #4f8ef7;
    padding-left: 0px;
    border: none;
    font-size: 15px;
    font-weight: bold;
}

QLabel#sidebarVersion {
    color: #3d3d55;
    font-size: 10px;
    padding: 10px 12px;
}

QFrame#sidebarSeparator {
    color: #2d2d42;
    max-width: 1px;
}

/* ── 3. Nav buttons ─────────────────────────────────────────────────── */
QPushButton#navButton {
    background-color: transparent;
    border: none;
    color: #6b7280;
    text-align: left;
    padding: 12px 18px;
    font-size: 12px;
}

QPushButton#navButton:hover {
    background-color: #1e1e2a;
    color: #e8eaf0;
}

QPushButton#navButton:checked {
    background-color: #1e1e2a;
    color: #4f8ef7;
    font-weight: bold;
}

/* ── 4. Group boxes ─────────────────────────────────────────────────── */
QGroupBox {
    background-color: transparent;
    border: 1px solid #2d2d42;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 12px 12px 12px;
    font-weight: bold;
    font-size: 18px;
    color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    color: #ffffff;
    font-size: 18px;
    font-weight: bold;
    background-color: transparent;
}

/* ── 5. Metric cards ────────────────────────────────────────────────── */
QWidget#metricCard {
    background-color: #252535;
    border: 1px solid #2d2d42;
    border-radius: 14px;
}

QLabel#cardTitle {
    color: #6b7280;
    font-size: 10px;
    font-weight: 600;
}

QLabel#cardValue {
    color: #e8eaf0;
    font-weight: 700;
}

/* ── 6. Progress bars — per-resource accent colours ────────────────── */
QProgressBar#metricBarCpu,
QProgressBar#metricBarRam,
QProgressBar#metricBarTemp {
    background-color: #2d2d42;
    border: none;
    border-radius: 6px;
}

/* CPU — vibrant blue */
QProgressBar#metricBarCpu::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1a5fc8, stop:0.6 #4f8ef7, stop:1 #7fb3ff
    );
    border-radius: 6px;
}

/* RAM — vivid purple */
QProgressBar#metricBarRam::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #5a2da0, stop:0.6 #a371f7, stop:1 #c49dff
    );
    border-radius: 6px;
}

/* CPU Temp — rich green */
QProgressBar#metricBarTemp::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1a6e30, stop:0.6 #3fb950, stop:1 #6dda82
    );
    border-radius: 6px;
}

/* ── 7. Weather panel ───────────────────────────────────────────────── */
QLabel#weatherCaption {
    color: #4a4a62;
    font-size: 10px;
    font-weight: 500;
}

QLabel#weatherValue {
    color: #e8eaf0;
    font-weight: 600;
}

QLabel#weatherIcon {
    background-color: transparent;
}

/* ── 8. Status / detail labels ──────────────────────────────────────── */
QLabel#statusLabel {
    color: #4a4a62;
    font-size: 11px;
    padding: 4px 0;
}

QLabel#ramDetail {
    color: #4a4a62;
    font-size: 10px;
    padding: 1px 0;
}

/* ── 9. Form inputs ─────────────────────────────────────────────────── */
QLineEdit, QComboBox {
    background-color: #252535;
    border: 1px solid #2d2d42;
    border-radius: 8px;
    padding: 7px 12px;
    color: #e8eaf0;
    font-size: 12px;
    selection-background-color: #4f8ef7;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #4f8ef7;
    background-color: #2a2a3e;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1e1e2a;
    border: 1px solid #2d2d42;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #4f8ef7;
    selection-color: #ffffff;
    outline: none;
}

/* ── 10. Buttons ────────────────────────────────────────────────────── */
QPushButton {
    background-color: #252535;
    border: 1px solid #2d2d42;
    border-radius: 8px;
    padding: 8px 18px;
    color: #e8eaf0;
    font-size: 12px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #2d2d42;
    border-color: #4a4a62;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #1e1e2a;
    border-color: #4f8ef7;
}

QPushButton#primaryButton {
    background-color: #4f8ef7;
    border: 1px solid #6aa3ff;
    color: #ffffff;
    font-weight: 700;
    border-radius: 8px;
}

QPushButton#primaryButton:hover {
    background-color: #6aa3ff;
    border-color: #88bbff;
}

QPushButton#primaryButton:pressed {
    background-color: #3570d4;
}

/* ── 11. Hex label (colour token readout) ───────────────────────────── */
QLabel#hexLabel {
    color: #4a4a62;
    font-size: 11px;
    font-family: "Consolas", "Courier New", monospace;
}

/* ── 12. Preview hint label ─────────────────────────────────────────── */
QLabel#previewPlaceholder {
    color: #3d3d55;
    font-size: 11px;
}

/* ── 13. Status bar ─────────────────────────────────────────────────── */
QStatusBar#appStatusBar {
    background-color: #0c0c14;
    border-top: 1px solid #2d2d42;
    color: #6b7280;
    font-size: 11px;
}

/* ── 14. Scrollbars ─────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #1e1e2a;
    width: 6px;
    border-radius: 3px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #2d2d42;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #4a4a62;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #1e1e2a;
    height: 6px;
    border-radius: 3px;
}

QScrollBar::handle:horizontal {
    background: #2d2d42;
    border-radius: 3px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background: #4a4a62;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Initialise and run the StatusHub Qt application.

    Returns the exit code from the Qt event loop (0 = success).
    """
    _configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting StatusHub …")

    # Resolve config path relative to this file so the app works regardless of
    # the current working directory.
    project_root = Path(__file__).parent
    config_path = project_root / "config.json"
    config = ConfigManager(config_path)

    app = QApplication(sys.argv)
    app.setApplicationName("StatusHub")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("StatusHub Project")

    # Apply a clean default font before the stylesheet takes over.
    default_font = QFont("Inter", 10)
    default_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(default_font)

    # Apply the global dark stylesheet.
    app.setStyleSheet(DARK_STYLESHEET)

    splash = SplashScreen()
    splash.show()
    window = MainWindow(config=config, splash=splash)

    exit_code = app.exec()
    logger.info("StatusHub exited with code %d.", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
