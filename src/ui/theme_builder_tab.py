"""
theme_builder_tab.py
====================
The "Theme Builder" tab widget.

Classes
-------
ColorSwatch       — Pill-shaped colour picker row; emits color_changed(QColor).
DisplayCanvas     — QPainter-based 480×272 live preview with rounded-corner
                    bezel simulation of the NV3041A ESP32 display.
ThemeBuilderTab   — Top-level tab composite widget.
"""

import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QColorDialog, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QRect, QRectF
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QLinearGradient,
    QPaintEvent, QRadialGradient, QPainterPath,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ColorSwatch
# ---------------------------------------------------------------------------

class ColorSwatch(QWidget):
    """
    A horizontal row: label | pill button | hex readout.

    Signals
    -------
    color_changed(QColor)
        Emitted when the user confirms a new colour.
    """

    color_changed: pyqtSignal = pyqtSignal(QColor)

    def __init__(self, initial_color: str = "#1e90ff", label: str = "", parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(initial_color)
        self._label_text = label
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)

        if self._label_text:
            lbl = QLabel(self._label_text)
            lbl.setFixedWidth(138)
            lbl.setStyleSheet("font-size: 12px; color: #9ca3af;")
            layout.addWidget(lbl)

        # Pill-shaped colour button
        self._swatch_btn = QPushButton()
        self._swatch_btn.setFixedSize(44, 28)
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
        """Open QColorDialog; emit color_changed on confirmation."""
        chosen = QColorDialog.getColor(
            self._color, self,
            f"Select colour — {self._label_text or 'token'}",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if chosen.isValid():
            self._color = chosen
            self._apply_color()
            self._hex_lbl.setText(chosen.name())
            self.color_changed.emit(chosen)

    def _apply_color(self) -> None:
        """Repaint the pill button to reflect the current colour."""
        self._swatch_btn.setStyleSheet(
            f"background-color: {self._color.name()};"
            f"border: 2px solid rgba(255,255,255,0.18);"
            f"border-radius: 14px;"
        )

    @property
    def color(self) -> QColor:
        return self._color

    @property
    def hex(self) -> str:
        return self._color.name()

    def set_color(self, color: "QColor | str") -> None:
        """Set colour programmatically (no picker dialog)."""
        if isinstance(color, str):
            color = QColor(color)
        self._color = color
        self._apply_color()
        self._hex_lbl.setText(color.name())


# ---------------------------------------------------------------------------
# DisplayCanvas
# ---------------------------------------------------------------------------

class DisplayCanvas(QWidget):
    """
    Fixed-size (480×272) QPainter widget simulating the NV3041A ESP32 display.

    Draws a realistic mock layout:
    - Outer bezel (dark rounded rect simulating hardware frame)
    - Screen area (rounded inner rect)
    - Top bar: StatusHub logo text + clock
    - Three metric rows: label, gradient gauge bar, value
    - Weather strip at the bottom

    Call :meth:`apply_theme` with a colour dict to update colours and
    trigger an immediate repaint.
    """

    CANVAS_W = 480
    CANVAS_H = 272
    # Extra pixels around screen simulating the physical bezel
    BEZEL = 10

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Total widget size includes the bezel margin on all sides
        total_w = self.CANVAS_W + self.BEZEL * 2
        total_h = self.CANVAS_H + self.BEZEL * 2
        self.setFixedSize(total_w, total_h)

        # Default palette — "Dark Midnight"
        self._bg       = QColor("#0d1117")
        self._surface  = QColor("#161b22")
        self._primary  = QColor("#4f8ef7")
        self._secondary = QColor("#3fb950")
        self._text     = QColor("#e8eaf0")
        self._muted    = QColor("#6b7280")
        self._warning  = QColor("#d29922")
        self._danger   = QColor("#f85149")

    def apply_theme(self, colors: dict) -> None:
        """Update palette from a colour dict and request a repaint."""
        def _c(key: str, fallback: QColor) -> QColor:
            val = colors.get(key)
            return QColor(val) if val else fallback

        self._bg        = _c("background", self._bg)
        self._surface   = _c("surface",    self._surface)
        self._primary   = _c("primary",    self._primary)
        self._secondary = _c("secondary",  self._secondary)
        self._text      = _c("text",       self._text)
        self._muted     = _c("muted",      self._muted)
        self._warning   = _c("warning",    self._warning)
        self._danger    = _c("danger",     self._danger)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Paint the full bezel + screen mock."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        B  = self.BEZEL
        SW = self.CANVAS_W   # screen width
        SH = self.CANVAS_H   # screen height
        TW = SW + B * 2      # total widget width
        TH = SH + B * 2      # total widget height

        # ── 1. Outer bezel ─────────────────────────────────────────────
        bezel_color = QColor("#1a1a2e")
        bezel_path = QPainterPath()
        bezel_path.addRoundedRect(QRectF(0, 0, TW, TH), 16, 16)
        p.fillPath(bezel_path, QBrush(bezel_color))

        # Subtle bezel highlight ring
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, TW - 1, TH - 1), 15.5, 15.5)

        # ── 2. Screen area (clipped rounded rect) ─────────────────────
        screen_rect = QRectF(B, B, SW, SH)
        screen_path = QPainterPath()
        screen_path.addRoundedRect(screen_rect, 8, 8)
        p.setClipPath(screen_path)
        p.fillRect(screen_rect.toRect(), self._bg)

        # ── 3. Top bar ─────────────────────────────────────────────────
        bar_h = 38
        bar_rect = QRect(B, B, SW, bar_h)
        p.fillRect(bar_rect, self._surface)

        # Separator below top bar
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(B, B + bar_h, B + SW, B + bar_h)

        # Logo glyph "S" circle
        logo_cx, logo_cy = B + 18, B + bar_h // 2
        p.setBrush(QBrush(self._primary))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(logo_cx - 9, logo_cy - 9, 18, 18)
        logo_lbl_font = QFont("Segoe UI", 7, QFont.Weight.Black)
        p.setFont(logo_lbl_font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(logo_cx - 9, logo_cy - 9, 18, 18),
                   Qt.AlignmentFlag.AlignCenter, "S")

        # "StatusHub" title
        title_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        p.setFont(title_font)
        p.setPen(self._text)
        p.drawText(QRect(B + 32, B, 140, bar_h), Qt.AlignmentFlag.AlignVCenter, "StatusHub")

        # Clock placeholder
        clock_font = QFont("Segoe UI", 9)
        p.setFont(clock_font)
        p.setPen(self._muted)
        p.drawText(QRect(B + SW - 76, B, 68, bar_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "12:34:56")

        # ── 4. Metric rows ─────────────────────────────────────────────
        metrics = [
            ("CPU",  45, "%",  self._primary,   QColor("#1a5fc8")),
            ("RAM",  62, "%",  QColor("#a371f7"), QColor("#5a2da0")),
            ("TEMP", 58, "°C", self._secondary,  QColor("#1a6e30")),
        ]

        row_y    = B + bar_h + 6
        row_h    = 46
        lx       = B + 10         # label x
        bx       = B + 64         # bar x
        bw       = SW - 64 - 72   # bar width
        bh       = 9              # bar height
        vx       = B + SW - 70    # value x

        lbl_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        val_font = QFont("Segoe UI", 10, QFont.Weight.Bold)

        for label, value, unit, hi_color, lo_color in metrics:
            cy = row_y + (row_h - bh) // 2

            # Alternating row tint
            if metrics.index((label, value, unit, hi_color, lo_color)) % 2 == 0:
                p.fillRect(QRect(B, row_y, SW, row_h), QColor(255, 255, 255, 5))

            # Metric label
            p.setFont(lbl_font)
            p.setPen(self._muted)
            p.drawText(QRect(lx, row_y, bx - lx - 4, row_h),
                       Qt.AlignmentFlag.AlignVCenter, label)

            # Track
            p.setBrush(QBrush(QColor(255, 255, 255, 14)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRect(bx, cy, bw, bh), 4, 4)

            # Filled chunk
            fw = max(8, int(bw * value / 100))
            grad = QLinearGradient(bx, 0, bx + bw, 0)
            grad.setColorAt(0.0, lo_color)
            grad.setColorAt(0.6, hi_color)
            grad.setColorAt(1.0, hi_color.lighter(130))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRect(bx, cy, fw, bh), 4, 4)

            # Value
            p.setFont(val_font)
            p.setPen(self._text)
            p.drawText(QRect(vx, row_y, 62, row_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{value} {unit}")

            row_y += row_h

        # ── 5. Divider ─────────────────────────────────────────────────
        div_y = row_y + 3
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawLine(B + 12, div_y, B + SW - 12, div_y)

        # ── 6. Weather strip ───────────────────────────────────────────
        strip_y = div_y + 5
        strip_h = (B + SH) - strip_y - 2
        p.fillRect(QRect(B, strip_y, SW, strip_h), self._surface)

        # Sun icon
        sun_r  = 7
        sun_cx = B + 18
        sun_cy = strip_y + strip_h // 2
        p.setBrush(QBrush(self._warning))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(sun_cx - sun_r, sun_cy - sun_r, sun_r * 2, sun_r * 2)

        weather_items = ["Cairo", "28 °C", "Feels 26°C", "Humidity 65%", "Wind 3.2", "Clear"]
        item_w = (SW - 38) // len(weather_items)
        item_x = B + 38
        w_font = QFont("Segoe UI", 8)
        p.setFont(w_font)
        for i, item in enumerate(weather_items):
            p.setPen(self._text)
            p.drawText(QRect(item_x, strip_y, item_w, strip_h),
                       Qt.AlignmentFlag.AlignCenter, item)
            if i < len(weather_items) - 1:
                sx = item_x + item_w
                p.setPen(QPen(QColor(255, 255, 255, 14), 1))
                p.drawLine(sx, strip_y + 4, sx, strip_y + strip_h - 4)
            item_x += item_w

        # ── 7. Remove clip, draw inner screen border ───────────────────
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(screen_rect.adjusted(0, 0, -1, -1), 8, 8)

        p.end()


# ---------------------------------------------------------------------------
# ThemeBuilderTab
# ---------------------------------------------------------------------------

class ThemeBuilderTab(QWidget):
    """
    Tab for building and managing display themes.

    Left panel  — Preset selector, Colour Tokens, Action buttons.
    Right panel — Live DisplayCanvas that repaints on every swatch change.
    """

    _PRESET_THEMES = [
        "Dark Midnight", "Cyber Neon", "Ocean Breeze",
        "Desert Sand", "Forest Green", "Custom",
    ]

    _PRESET_COLORS: dict[str, dict] = {
        "Dark Midnight": {
            "background": "#0d1117", "surface": "#161b22",
            "primary": "#4f8ef7",   "secondary": "#3fb950",
            "text": "#e8eaf0",      "muted": "#6b7280",
            "warning": "#d29922",   "danger": "#f85149",
        },
        "Cyber Neon": {
            "background": "#050510", "surface": "#0a0a1f",
            "primary": "#ff007f",    "secondary": "#00ffcc",
            "text": "#f0f0ff",       "muted": "#6060a0",
            "warning": "#ffbb00",    "danger": "#ff3030",
        },
        "Ocean Breeze": {
            "background": "#001f3f", "surface": "#003366",
            "primary": "#00b4d8",    "secondary": "#90e0ef",
            "text": "#caf0f8",       "muted": "#4a8fa8",
            "warning": "#f4a261",    "danger": "#e63946",
        },
        "Desert Sand": {
            "background": "#1a1200", "surface": "#2e2000",
            "primary": "#e8a045",    "secondary": "#f4d58d",
            "text": "#f5e6c8",       "muted": "#8a7055",
            "warning": "#e07020",    "danger": "#c0392b",
        },
        "Forest Green": {
            "background": "#0a1a0a", "surface": "#122412",
            "primary": "#3fb950",    "secondary": "#a3e4a8",
            "text": "#d4f1d8",       "muted": "#527a55",
            "warning": "#c9a227",    "danger": "#d62828",
        },
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._connect_swatches()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # Left panel
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setSpacing(12)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self._build_preset_group())
        ll.addWidget(self._build_colors_group())
        ll.addWidget(self._build_actions_group())
        ll.addStretch()
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # Right panel
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(self._build_preview_group())
        rl.addStretch()
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root.addWidget(left, stretch=0)
        root.addWidget(right, stretch=1)

    def _build_preset_group(self) -> QGroupBox:
        group = QGroupBox("🎨  Theme Preset")
        form = QFormLayout(group)
        form.setSpacing(10)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(self._PRESET_THEMES)
        self._theme_combo.setToolTip("Select a base theme to customise")
        self._theme_combo.currentTextChanged.connect(self._on_preset_changed)

        self._theme_name_edit = QLineEdit()
        self._theme_name_edit.setPlaceholderText("Enter a name for your custom theme…")

        form.addRow("Base preset:", self._theme_combo)
        form.addRow("Theme name:",  self._theme_name_edit)
        return group

    def _build_colors_group(self) -> QGroupBox:
        """Build the scrollable colour-token list."""
        group = QGroupBox("🖌  Colour Tokens")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(inner)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        self._color_background = ColorSwatch("#0d1117", "Background")
        self._color_surface    = ColorSwatch("#161b22", "Surface / Card")
        self._color_primary    = ColorSwatch("#4f8ef7", "Primary Accent")
        self._color_secondary  = ColorSwatch("#3fb950", "Secondary Accent")
        self._color_text       = ColorSwatch("#e8eaf0", "Primary Text")
        self._color_muted      = ColorSwatch("#6b7280", "Muted Text")
        self._color_warning    = ColorSwatch("#d29922", "Warning")
        self._color_danger     = ColorSwatch("#f85149", "Danger / High Temp")

        for swatch in self._all_swatches():
            layout.addWidget(swatch)

        scroll.setWidget(inner)
        gl = QVBoxLayout(group)
        gl.setContentsMargins(4, 4, 4, 4)
        gl.addWidget(scroll)
        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("⚡  Actions")
        layout = QHBoxLayout(group)
        layout.setSpacing(10)

        self._save_btn  = QPushButton("💾  Save")
        self._save_btn.setToolTip("Save theme to config.json")
        self._save_btn.clicked.connect(self._on_save)

        self._reset_btn = QPushButton("↩  Reset")
        self._reset_btn.setToolTip("Reset to preset defaults")
        self._reset_btn.clicked.connect(self._on_reset)

        self._push_btn = QPushButton("📡  Push to Display")
        self._push_btn.setObjectName("primaryButton")
        self._push_btn.setToolTip("Send theme to ESP32-S3 via serial")
        self._push_btn.clicked.connect(self._on_push_to_device)

        for btn in (self._save_btn, self._reset_btn, self._push_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(btn)
        return group

    def _build_preview_group(self) -> QGroupBox:
        """Wrap the DisplayCanvas in a titled group box."""
        group = QGroupBox("👁  Display Preview  (480 × 272 px — NV3041A)")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(10)

        self._canvas = DisplayCanvas()
        layout.addWidget(self._canvas, alignment=Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Colours update instantly as you change the tokens on the left.")
        hint.setObjectName("previewPlaceholder")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return group

    # ------------------------------------------------------------------
    # Swatch helpers
    # ------------------------------------------------------------------

    def _all_swatches(self) -> list[ColorSwatch]:
        return [
            self._color_background, self._color_surface,
            self._color_primary,    self._color_secondary,
            self._color_text,       self._color_muted,
            self._color_warning,    self._color_danger,
        ]

    def _connect_swatches(self) -> None:
        """Wire every swatch to the canvas so it repaints in real time."""
        for swatch in self._all_swatches():
            swatch.color_changed.connect(self._on_any_color_changed)

    @pyqtSlot(QColor)
    def _on_any_color_changed(self, _: QColor) -> None:
        self._canvas.apply_theme(self._current_color_dict())

    def _current_color_dict(self) -> dict:
        return {
            "background": self._color_background.hex,
            "surface":    self._color_surface.hex,
            "primary":    self._color_primary.hex,
            "secondary":  self._color_secondary.hex,
            "text":       self._color_text.hex,
            "muted":      self._color_muted.hex,
            "warning":    self._color_warning.hex,
            "danger":     self._color_danger.hex,
        }

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def _on_preset_changed(self, preset_name: str) -> None:
        """Load colour tokens from the selected preset and refresh the canvas."""
        preset = self._PRESET_COLORS.get(preset_name)
        if not preset:
            return
        token_map = {
            "background": self._color_background,
            "surface":    self._color_surface,
            "primary":    self._color_primary,
            "secondary":  self._color_secondary,
            "text":       self._color_text,
            "muted":      self._color_muted,
            "warning":    self._color_warning,
            "danger":     self._color_danger,
        }
        for key, swatch in token_map.items():
            if key in preset:
                swatch.set_color(preset[key])
        self._canvas.apply_theme(self._current_color_dict())

    @pyqtSlot()
    def _on_save(self) -> None:
        """Placeholder: persist colour tokens to config.json."""
        name = self._theme_name_edit.text().strip() or "Untitled"
        logger.info("[ThemeBuilder] Save → %s", self._build_theme_payload(name))

    @pyqtSlot()
    def _on_reset(self) -> None:
        """Re-apply the currently selected preset."""
        self._on_preset_changed(self._theme_combo.currentText())

    @pyqtSlot()
    def _on_push_to_device(self) -> None:
        """Placeholder: send the active theme to the ESP32-S3."""
        name = self._theme_name_edit.text().strip() or "Untitled"
        logger.info("[ThemeBuilder] Push to device → %s", self._build_theme_payload(name))

    def _build_theme_payload(self, name: str) -> dict:
        """Serialise all colour token values into a JSON-ready dictionary."""
        return {"name": name, "colors": self._current_color_dict()}
