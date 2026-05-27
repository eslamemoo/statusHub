"""
custom_widgets.py
=================
Reusable, premium custom PyQt6 widgets for StatusHub.

Contents
--------
CircularGauge
    A paint-based circular progress gauge inspired by hardware monitors such
    as NZXT CAM.  It renders a background track arc, a coloured active-value
    arc with ``RoundCap`` pen ends, and a two-line text block centred inside
    the circle showing the current value + unit (large, bold) and a muted
    resource sub-label below it.

Usage example
-------------
    gauge = CircularGauge(color=QColor("#4f8ef7"), label="CPU", unit="%")
    gauge.set_value(62.5)   # animate gauge to 62.5
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_dynamic_color(percentage: float) -> str:
    """
    Return a hex color string based on the percentage value:
    - 0% to 59%: Vibrant Green (#10b981)
    - 60% to 79%: Warning Orange/Yellow (#f59e0b)
    - 80% to 100%: Danger Red (#ef4444)
    """
    if percentage < 60:
        return "#10b981"  # Green
    elif percentage < 80:
        return "#f59e0b"  # Orange
    else:
        return "#ef4444"  # Red


# ---------------------------------------------------------------------------
# CircularGauge
# ---------------------------------------------------------------------------

class CircularGauge(QWidget):
    """
    A circular progress gauge widget rendered entirely via ``QPainter``.

    Arc geometry (Qt coordinate system)
    ------------------------------------
    ``QPainter.drawArc`` measures angles in **1/16ths of a degree**,
    counter-clockwise from the 3-o'clock position.

    Horseshoe gauge layout:
    - Start angle  = 225 ° CCW from 3 o'clock  →  bottom-left of circle.
      Qt value: ``225 * 16 = 3600`` units.
    - Total sweep  = 270 °  (horseshoe covers ¾ of the circle).
      Qt value at 100 %: ``270 * 16 = 4320`` units.
    - Direction    = **clockwise**, so the Qt span is **negative**
      (Qt's positive span sweeps counter-clockwise).

    Typography inside the circle
    ----------------------------
    Three text elements are painted in a single vertically-centred block:

    ┌──────────────────┐
    │                  │
    │   **63**         │  ← large bold value (e.g. "63")
    │    **%**         │  ← slightly smaller unit, right-aligned to value
    │   ── LOAD ──     │  ← small muted sub-label
    │                  │
    └──────────────────┘

    In practice the value + unit are drawn on the same baseline via two
    adjacent ``drawText`` calls; the sub-label is drawn below with a gap.

    Parameters
    ----------
    color:
        Accent ``QColor`` for the active track arc.
    label:
        Short muted sub-label inside the circle (e.g. ``"CPU"``).
    unit:
        Unit string appended to the numeric value (e.g. ``"%"`` or ``"°C"``).
    max_value:
        Maximum representable value.  Defaults to ``100.0``.
    parent:
        Optional Qt parent widget.
    """

    # Total sweep of the horseshoe arc in degrees.
    _SWEEP_DEGREES: float = 270.0

    # Qt start angle in 1/16-degree units.
    # 225 ° CCW from 3 o'clock lands at the bottom-left of the circle.
    _START_ANGLE_QT: int = int(225 * 16)   # = 3600

    def __init__(
        self,
        color: QColor | None = None,
        label: str = "LOAD",
        unit: str = "%",
        max_value: float = 100.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color: QColor = color or QColor("#4f8ef7")
        self._label: str = label
        self._unit: str = unit
        self._max_value: float = max(max_value, 1.0)  # guard against zero division
        self._value: float = 0.0

        # Animated intermediate value driven by QPropertyAnimation.
        self._animated_value: float = 0.0
        self._animation = QPropertyAnimation(self, b"animated_value", self)
        self._animation.setDuration(500)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Expand squarely; the paintEvent keeps drawing square regardless of
        # the actual allocated rectangle.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(180, 180)
        self.setMaximumSize(280, 280)

        # Prevent global QSS from painting a coloured background on this widget.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent; border: none;")

    # ------------------------------------------------------------------
    # Qt animated property — the animation ticks drive continuous repaints.
    # ------------------------------------------------------------------

    def _get_animated_value(self) -> float:
        return self._animated_value

    def _set_animated_value(self, value: float) -> None:
        self._animated_value = value
        self.update()   # schedule a repaint on every animation tick

    # Exposed as a Qt property so QPropertyAnimation can drive it.
    animated_value = pyqtProperty(float, _get_animated_value, _set_animated_value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_value(self, value: float) -> None:
        """
        Animate the gauge to *value*.

        The value is clamped to ``[0, max_value]`` before the animation
        target is set.

        Parameters
        ----------
        value:
            New metric reading (e.g. 63.4 for 63.4 %).
        """
        self._value = max(0.0, min(value, self._max_value))
        self._animation.stop()
        self._animation.setStartValue(self._animated_value)
        self._animation.setEndValue(self._value)
        self._animation.start()

    def set_color(self, color: QColor) -> None:
        """Replace the accent color and trigger an immediate repaint."""
        self._color = color
        self.update()

    # ------------------------------------------------------------------
    # Qt paint event
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        """
        Render the gauge in three ordered passes.

        Pass 1 — Background track arc (dark gray, full 270 °).
        Pass 2 — Active value arc (accent color, proportional span, clockwise).
        Pass 3 — Typography: large value + unit on one baseline, small muted
                 sub-label below, all geometrically centred inside the circle.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # The gauge always renders inside the largest centred square that fits
        # within the widget's current allocation.
        side = min(self.width(), self.height())
        pen_width = max(10, int(side * 0.12))   # track thickness ≈ 12 % of side

        # Centre the square bounding rect, adding half the pen width as margin
        # so the thick stroke is never clipped by the widget edge.
        # Minimal margin to maximize drawing area.
        margin = pen_width / 2 + 1.0
        cx = self.width()  / 2.0
        cy = self.height() / 2.0
        arc_rect = QRectF(
            cx - side / 2.0 + margin,
            cy - side / 2.0 + margin,
            side - 2.0 * margin,
            side - 2.0 * margin,
        )

        # ── Pass 1: full background track ─────────────────────────────
        track_pen = QPen(QColor("#2a2a3e"))
        track_pen.setWidth(pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(arc_rect, self._START_ANGLE_QT, -int(self._SWEEP_DEGREES * 16))

        # ── Pass 2: active value arc ───────────────────────────────────
        fraction  = self._animated_value / self._max_value
        span_deg  = fraction * self._SWEEP_DEGREES
        if span_deg > 0.5:   # skip sub-pixel arcs that would look like noise
            # Dynamic color coding
            percentage = (self._animated_value / self._max_value) * 100
            current_color = QColor(get_dynamic_color(percentage))
            
            arc_pen = QPen(current_color)
            arc_pen.setWidth(pen_width)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(arc_rect, self._START_ANGLE_QT, -int(span_deg * 16))

        # ── Pass 3: centred typography ─────────────────────────────────
        # The text block consists of two rows:
        #   Row A — value (large bold) + unit (medium, slightly smaller)
        #   Row B — sub-label (small, muted gray)
        # We compute the combined block height first, then offset both rows
        # so the block is perfectly centred inside arc_rect.

        # --- Font sizes (proportional to widget side) ---
        value_pt = max(12, int(side * 0.22))   # large bold numeral
        unit_pt  = max(9, int(side * 0.11))    # smaller unit symbol
        label_pt = max(8, int(side * 0.10))    # muted sub-label

        value_font = QFont("Inter", value_pt, QFont.Weight.Bold)
        unit_font  = QFont("Inter", unit_pt,  QFont.Weight.Medium)
        label_font = QFont("Inter", label_pt, QFont.Weight.Normal)

        # Measure the value string width/height (used for baseline alignment).
        painter.setFont(value_font)
        value_fm   = painter.fontMetrics()
        value_str  = f"{self._animated_value:.0f}"
        value_w    = value_fm.horizontalAdvance(value_str)
        value_asc  = value_fm.ascent()    # height above baseline
        value_desc = value_fm.descent()   # height below baseline

        # Measure the unit string.
        painter.setFont(unit_font)
        unit_fm  = painter.fontMetrics()
        unit_str = self._unit
        unit_w   = unit_fm.horizontalAdvance(unit_str)
        unit_asc = unit_fm.ascent()

        # Measure the sub-label.
        painter.setFont(label_font)
        label_fm  = painter.fontMetrics()
        label_w   = label_fm.horizontalAdvance(self._label)
        label_h   = label_fm.height()

        # Vertical gap between the value row and the sub-label row.
        row_gap = max(3, int(side * 0.035))

        # Total height of the text block (from value ascent to label bottom).
        block_h = value_asc + value_desc + row_gap + label_h

        # Y-coordinate of the shared value+unit baseline, measured from top.
        # Centering: place the block midpoint at cy.
        baseline_y = cy - block_h / 2.0 + value_asc

        # Combined width of value + unit on the same baseline.
        gap_vu = max(1, int(side * 0.015))   # tiny gap between numeral and unit
        row_a_w = value_w + gap_vu + unit_w

        # X origin for the value string (left-aligned within the combined width,
        # the whole row is centred on cx).
        value_x = cx - row_a_w / 2.0
        unit_x  = value_x + value_w + gap_vu

        # Y for sub-label (top of label bounding box).
        label_y = baseline_y + value_desc + row_gap

        # Draw value numeral.
        painter.setFont(value_font)
        painter.setPen(QColor("#e8eaf0"))
        painter.drawText(
            QRectF(value_x, baseline_y - value_asc, value_w + 2, value_asc + value_desc + 2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            value_str,
        )

        # Draw unit symbol — baseline-aligned with the value numeral, but
        # shifted up slightly so its cap-height visually aligns with the
        # value's cap-height (compensates for the smaller font size).
        unit_offset_y = value_asc - unit_asc   # shift upward to align caps
        painter.setFont(unit_font)
        painter.setPen(QColor("#9ca3af"))       # slightly muted to de-emphasise unit
        painter.drawText(
            QRectF(unit_x, baseline_y - value_asc + unit_offset_y,
                   unit_w + 2, unit_asc + unit_fm.descent() + 2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            unit_str,
        )

        # Draw sub-label (e.g. "CPU", "RAM", "TEMP") — muted gray, centred.
        painter.setFont(label_font)
        painter.setPen(QColor("#4b5563"))
        painter.drawText(
            QRectF(cx - label_w / 2.0 - 1, label_y, label_w + 4, label_h + 2),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )

        painter.end()
