import time
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize, pyqtProperty
from PyQt6.QtGui import QFont, QColor

class SplashScreen(QWidget):
    """
    A premium, frameless splash screen for StatusHub.
    Features a dark theme, centered logo/name, and an animated progress bar.
    """
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setFixedSize(500, 320)  # Increased height slightly for better spacing
        
        # Define sequential loading messages
        self._status_messages = [
            "Loading system configurations and preferences...",
            "Initializing core hardware background monitors...",
            "Establishing synchronization with background workers...",
            "Optimizing responsive dashboard layouts...",
            "Ready."
        ]
        
        self._build_ui()
        
        self._progress_anim = QPropertyAnimation(self, b"progress_value", self)
        self._progress_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
    def _build_ui(self):
        # Main container with rounded corners and dark background
        self.container = QWidget(self)
        self.container.setObjectName("splashContainer")
        self.container.setFixedSize(self.size())
        self.container.setStyleSheet("""
            QWidget#splashContainer {
                background-color: #121212;
                border: 1px solid #2d2d42;
                border-radius: 15px;
            }
        """)
        
        layout = QVBoxLayout(self.container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(40, 50, 40, 30)
        
        # Logo/Name
        self.title_label = QLabel("StatusHub")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #4f8ef7;
                font-size: 42px;
                font-weight: bold;
                letter-spacing: 2px;
                background: transparent;
                margin-bottom: 0px;
            }
        """)
        layout.addWidget(self.title_label)
        
        self.subtitle_label = QLabel("PREMIUM SYSTEM MONITOR")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 4px;
                margin-top: 0px;
                background: transparent;
            }
        """)
        layout.addWidget(self.subtitle_label)
        
        layout.addStretch()
        
        # Progress bar container for better spacing
        progress_container = QWidget()
        progress_container.setStyleSheet("background: transparent;")
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(12) # Task 3: Spacing between bar and text
        
        # Progress bar
        self.progress = QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setStyleSheet("""
            QProgressBar {
                background-color: #1e1e2a;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                                  stop:0 #4f8ef7, stop:1 #a371f7);
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self.progress)
        
        # Loading text
        self.loading_label = QLabel("Initializing systems...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setWordWrap(True)
        self.loading_label.setMinimumHeight(40)  # Reserve space to prevent layout jumps
        self.loading_label.setStyleSheet("""
            QLabel {
                color: #a0a0a0;
                font-size: 11px;
                font-weight: 500;
                background: transparent;
                margin-top: 5px;
            }
        """)
        progress_layout.addWidget(self.loading_label)
        
        layout.addWidget(progress_container)

    # ------------------------------------------------------------------
    # Animation Property
    # ------------------------------------------------------------------

    def _get_progress_value(self) -> int:
        return self.progress.value()

    def _set_progress_value(self, value: int):
        self.progress.setValue(value)
        self._update_status_text(value)

    progress_value = pyqtProperty(int, _get_progress_value, _set_progress_value)

    # ------------------------------------------------------------------
    # Internal Logic
    # ------------------------------------------------------------------

    def _update_status_text(self, percentage: int):
        """Update the loading label based on the current progress percentage."""
        if percentage <= 30:
            msg = self._status_messages[0]
        elif percentage <= 60:
            msg = self._status_messages[1]
        elif percentage <= 85:
            msg = self._status_messages[2]
        elif percentage < 100:
            msg = self._status_messages[3]
        else:
            msg = self._status_messages[4]
            
        if self.loading_label.text() != msg:
            self.loading_label.setText(msg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_progress_animation(self, duration_ms: int):
        """Task 1: Start smooth continuous progress bar animation."""
        self._progress_anim.stop()
        self._progress_anim.setDuration(duration_ms)
        self._progress_anim.setStartValue(0)
        self._progress_anim.setEndValue(100)
        self._progress_anim.start()

    def set_message(self, message: str):
        """Update only the loading message."""
        self.loading_label.setText(message)

    @property
    def animation_finished(self):
        """Expose the animation finished signal."""
        return self._progress_anim.finished

    def set_progress(self, value: int, message: str = None):
        """Legacy support for manual steps if needed, though we prefer animation now."""
        if not self._progress_anim.state() == QPropertyAnimation.State.Running:
            self.progress.setValue(value)
        if message:
            self.loading_label.setText(message)
            
    def fade_out(self, callback):
        """Smoothly fade out the splash screen then execute callback."""
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(500)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(callback)
        self.animation.start()
