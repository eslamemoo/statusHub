"""
theme_builder_tab.py
====================
The "Theme Builder" tab widget — placeholder implementation.

Provides a scaffold for custom theme management: selecting base presets,
picking colour tokens, previewing, saving to config.json, and pushing themes
to the ESP32-S3 via SerialManager.

Current state: UI skeleton with wired-up placeholder handlers.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QColorDialog, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor


# ---------------------------------------------------------------------------
# ColorSwatch helper widget
# ---------------------------------------------------------------------------

class ColorSwatch(QWidget):
    """A clickable coloured button that opens a QColorDialog on click."""

    def __init__(self, initial_color: str = "#1e90ff", label: str = "", parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(initial_color)
        self._label_text = label
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if self._label_text:
            lbl = QLabel(self._label_text)
            lbl.setFixedWidth(140)
            layout.addWidget(lbl)

        self._swatch_btn = QPushButton()
        self._swatch_btn.setFixedSize(80, 32)
        self._swatch_btn.setToolTip("Click to change colour")
        self._swatch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch_btn.clicked.connect(self._open_picker)
        self._apply_color()
        layout.addWidget(self._swatch_btn)

        self._hex_lbl = QLabel(self._color.name())
        self._hex_lbl.setObjectName("hexLabel")
        layout.addWidget(self._hex_lbl)
        layout.addStretch()

    def _open_picker(self) -> None:
        chosen = QColorDialog.getColor(
            self._color, self,
            f"Select colour — {self._label_text or 'token'}",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if chosen.isValid():
            self._color = chosen
            self._apply_color()
            self._hex_lbl.setText(chosen.name())

    def _apply_color(self) -> None:
        self._swatch_btn.setStyleSheet(
            f"background-color: {self._color.name()};"
            f"border: 2px solid rgba(255,255,255,0.3);"
            f"border-radius: 4px;"
        )

    @property
    def color(self) -> QColor:
        return self._color

    @property
    def hex(self) -> str:
        return self._color.name()


# ---------------------------------------------------------------------------
# Main tab widget
# ---------------------------------------------------------------------------

class ThemeBuilderTab(QWidget):
    """
    Placeholder tab for building and managing display themes.

    Integration points
    ------------------
    - ``_save_btn`` → config_manager.set / config_manager.save()
    - ``_push_btn`` → serial_manager.send_json(theme_payload)
    - ``_theme_combo`` changed → load preset colour tokens
    """

    _PRESET_THEMES = [
        "Dark Midnight", "Cyber Neon", "Ocean Breeze",
        "Desert Sand", "Forest Green", "Custom",
    ]

    _PRESET_COLORS: dict[str, dict] = {
        "Dark Midnight": {"background": "#0d1117", "surface": "#161b22",
                          "primary": "#1e90ff", "secondary": "#7ee787"},
        "Cyber Neon":    {"background": "#050510", "surface": "#0a0a1f",
                          "primary": "#ff007f", "secondary": "#00ffcc"},
        "Ocean Breeze":  {"background": "#001f3f", "surface": "#003366",
                          "primary": "#00b4d8", "secondary": "#90e0ef"},
        "Desert Sand":   {"background": "#1a1200", "surface": "#2e2000",
                          "primary": "#e8a045", "secondary": "#f4d58d"},
        "Forest Green":  {"background": "#0a1a0a", "surface": "#122412",
                          "primary": "#3fb950", "secondary": "#a3e4a8"},
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(16)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._build_preset_group())
        left_layout.addWidget(self._build_colors_group())
        left_layout.addWidget(self._build_actions_group())
        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._build_preview_pane())
        right_layout.addStretch()

        left_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        right_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root.addWidget(left_panel, stretch=0)
        root.addWidget(right_panel, stretch=1)

    def _build_preset_group(self) -> QGroupBox:
        group = QGroupBox("🎨  Theme Preset")
        form = QFormLayout(group)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(self._PRESET_THEMES)
        self._theme_combo.setToolTip("Select a base theme to customise")
        self._theme_combo.currentTextChanged.connect(self._on_preset_changed)

        self._theme_name_edit = QLineEdit()
        self._theme_name_edit.setPlaceholderText("Enter a name for your custom theme…")

        form.addRow("Base preset:", self._theme_combo)
        form.addRow("Theme name:", self._theme_name_edit)
        return group

    def _build_colors_group(self) -> QGroupBox:
        group = QGroupBox("🖌  Colour Tokens")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        self._color_background  = ColorSwatch("#0d1117", "Background")
        self._color_surface     = ColorSwatch("#161b22", "Surface / Card")
        self._color_primary     = ColorSwatch("#1e90ff", "Primary Accent")
        self._color_secondary   = ColorSwatch("#7ee787", "Secondary Accent")
        self._color_text        = ColorSwatch("#e6edf3", "Primary Text")
        self._color_muted       = ColorSwatch("#8b949e", "Muted Text")
        self._color_warning     = ColorSwatch("#d29922", "Warning")
        self._color_danger      = ColorSwatch("#f85149", "Danger / High Temp")

        for swatch in (
            self._color_background, self._color_surface,
            self._color_primary, self._color_secondary,
            self._color_text, self._color_muted,
            self._color_warning, self._color_danger,
        ):
            layout.addWidget(swatch)

        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("⚡  Actions")
        layout = QHBoxLayout(group)
        layout.setSpacing(10)

        self._save_btn  = QPushButton("💾  Save Theme")
        self._save_btn.setToolTip("Save theme to config.json")
        self._save_btn.clicked.connect(self._on_save)

        self._reset_btn = QPushButton("↩  Reset")
        self._reset_btn.setToolTip("Reset to preset defaults")
        self._reset_btn.clicked.connect(self._on_reset)

        self._push_btn  = QPushButton("📡  Push to Display")
        self._push_btn.setObjectName("primaryButton")
        self._push_btn.setToolTip("Send theme to ESP32-S3 via serial")
        self._push_btn.clicked.connect(self._on_push_to_device)

        for btn in (self._save_btn, self._reset_btn, self._push_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(btn)

        return group

    def _build_preview_pane(self) -> QGroupBox:
        """Mock preview representing the NV3041A 480×272 display."""
        group = QGroupBox("👁  Display Preview  (480 × 272 px)")
        layout = QVBoxLayout(group)

        frame = QFrame()
        frame.setObjectName("displayPreview")
        frame.setFixedSize(480, 272)
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        inner = QVBoxLayout(frame)
        placeholder = QLabel(
            "🖥  Live preview coming in a future sprint.\n\n"
            "Theme colours will be rendered here in real-time."
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setObjectName("previewPlaceholder")
        inner.addWidget(placeholder)

        layout.addWidget(frame, alignment=Qt.AlignmentFlag.AlignCenter)
        return group

    # ------------------------------------------------------------------
    # Slots / handlers
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def _on_preset_changed(self, preset_name: str) -> None:
        """Load colour tokens from the selected preset dictionary."""
        preset = self._PRESET_COLORS.get(preset_name)
        if not preset:
            return

        mapping = {
            "background": self._color_background,
            "surface":    self._color_surface,
            "primary":    self._color_primary,
            "secondary":  self._color_secondary,
        }
        for token, swatch in mapping.items():
            if token in preset:
                swatch._color = QColor(preset[token])
                swatch._apply_color()
                swatch._hex_lbl.setText(preset[token])

    @pyqtSlot()
    def _on_save(self) -> None:
        """Placeholder: persist colour tokens to config.json."""
        name = self._theme_name_edit.text().strip() or "Untitled"
        payload = self._build_theme_payload(name)
        # TODO: config_manager.set(f"themes.custom_themes.{name}", payload)
        # TODO: config_manager.save()
        print(f"[ThemeBuilder] Save → {payload}")  # noqa: T201

    @pyqtSlot()
    def _on_reset(self) -> None:
        """Re-apply the currently selected preset."""
        self._on_preset_changed(self._theme_combo.currentText())

    @pyqtSlot()
    def _on_push_to_device(self) -> None:
        """Placeholder: send the active theme to the ESP32-S3."""
        name = self._theme_name_edit.text().strip() or "Untitled"
        payload = self._build_theme_payload(name)
        # TODO: serial_manager.send_json({"cmd": "set_theme", "data": payload})
        print(f"[ThemeBuilder] Push to device → {payload}")  # noqa: T201

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_theme_payload(self, name: str) -> dict:
        """Serialise all colour token values into a JSON-ready dictionary."""
        return {
            "name": name,
            "colors": {
                "background": self._color_background.hex,
                "surface":    self._color_surface.hex,
                "primary":    self._color_primary.hex,
                "secondary":  self._color_secondary.hex,
                "text":       self._color_text.hex,
                "muted":      self._color_muted.hex,
                "warning":    self._color_warning.hex,
                "danger":     self._color_danger.hex,
            },
        }
