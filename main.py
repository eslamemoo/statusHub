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
# Global stylesheet (dark theme)
# ---------------------------------------------------------------------------

DARK_STYLESHEET = """
/* ── Application-wide reset ───────────────────────────────────────── */
* {
    font-family: "Segoe UI", "Inter", "SF Pro Display", sans-serif;
    color: #e6edf3;
    box-sizing: border-box;
}

QMainWindow, QWidget {
    background-color: #0d1117;
}

/* ── Sidebar ───────────────────────────────────────────────────────── */
QWidget#sidebar {
    background-color: #010409;
    border-right: 1px solid #21262d;
}

QLabel#sidebarHeader {
    background-color: #010409;
    color: #58a6ff;
    padding-left: 8px;
    border-bottom: 1px solid #21262d;
}

QLabel#sidebarVersion {
    color: #484f58;
    font-size: 11px;
    padding: 8px;
}

QFrame#sidebarSeparator {
    color: #21262d;
    max-width: 1px;
}

/* ── Nav buttons ───────────────────────────────────────────────────── */
QPushButton#navButton {
    background-color: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: #8b949e;
    text-align: left;
    padding: 10px 16px;
}

QPushButton#navButton:hover {
    background-color: #161b22;
    color: #e6edf3;
}

QPushButton#navButton:checked {
    background-color: #161b22;
    border-left: 3px solid #58a6ff;
    color: #58a6ff;
    font-weight: bold;
}

/* ── Group boxes ───────────────────────────────────────────────────── */
QGroupBox {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: bold;
    font-size: 13px;
    color: #8b949e;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #8b949e;
}

/* ── Metric cards ──────────────────────────────────────────────────── */
QWidget#metricCard {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
}

QLabel#cardTitle {
    color: #8b949e;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QLabel#cardValue {
    color: #e6edf3;
}

/* ── Progress bars ─────────────────────────────────────────────────── */
QProgressBar#metricBar {
    background-color: #21262d;
    border: none;
    border-radius: 7px;
}

QProgressBar#metricBar::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1f6feb, stop:1 #58a6ff
    );
    border-radius: 7px;
}

/* ── Weather labels ────────────────────────────────────────────────── */
QLabel#weatherCaption {
    color: #484f58;
    font-size: 10px;
}

QLabel#weatherValue {
    color: #e6edf3;
}

/* ── Status / detail labels ────────────────────────────────────────── */
QLabel#statusLabel, QLabel#ramDetail {
    color: #484f58;
    font-size: 11px;
    padding: 2px 0;
}

/* ── Form inputs ───────────────────────────────────────────────────── */
QLineEdit, QComboBox {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #e6edf3;
    selection-background-color: #1f6feb;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #58a6ff;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
}

/* ── Buttons ───────────────────────────────────────────────────────── */
QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 16px;
    color: #e6edf3;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
}

QPushButton:pressed {
    background-color: #161b22;
}

QPushButton#primaryButton {
    background-color: #1f6feb;
    border: 1px solid #388bfd;
    color: #ffffff;
    font-weight: bold;
}

QPushButton#primaryButton:hover {
    background-color: #388bfd;
}

QPushButton#primaryButton:pressed {
    background-color: #1158c7;
}

/* ── Display preview frame ─────────────────────────────────────────── */
QFrame#displayPreview {
    background-color: #010409;
    border: 2px solid #21262d;
    border-radius: 8px;
}

QLabel#previewPlaceholder {
    color: #484f58;
    font-size: 13px;
}

QLabel#hexLabel {
    color: #484f58;
    font-size: 11px;
    font-family: monospace;
}

/* ── Status bar ────────────────────────────────────────────────────── */
QStatusBar#appStatusBar {
    background-color: #010409;
    border-top: 1px solid #21262d;
    color: #8b949e;
    font-size: 11px;
}

/* ── Scrollbars ────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #161b22;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
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

    # Apply a clean default font before the stylesheet takes over
    default_font = QFont("Segoe UI", 10)
    app.setFont(default_font)

    # Apply the global dark stylesheet
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow(config=config)
    window.show()

    exit_code = app.exec()
    logger.info("StatusHub exited with code %d.", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
