from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy
from PyQt6.QtCore import Qt, QPoint, QRect, QSize

class DynamicGridLayout(QLayout):
    """
    A responsive grid layout that recalculates the number of columns based on 
    the container's width and stretches items to fill the available width.
    
    Behaves similarly to CSS Grid `repeat(auto-fit, minmax(min_item_width, 1fr))`.
    """
    def __init__(self, parent=None, spacing=10, min_item_width=350, max_columns=None):
        super().__init__(parent)
        self.setSpacing(spacing)
        self._min_item_width = min_item_width
        self._max_columns = max_columns
        self._items = []

    def __del__(self):
        del self._items

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal | Qt.Orientation.Vertical

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool):
        """
        Calculates and applies the layout logic.
        """
        if not self._items:
            return 0

        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(+left, +top, -right, -bottom)
        full_width = effective_rect.width()
        
        # Calculate number of columns
        spacing = self.spacing()
        
        # Determine number of columns based on width thresholds
        if full_width > 1200:
            n_cols = 4
        elif full_width > 800:
            n_cols = 2
        else:
            n_cols = 1

        # Enforce max_columns if specified
        if self._max_columns:
            n_cols = min(n_cols, self._max_columns)

        # Calculate item width to perfectly fill the available space
        item_width = (full_width - (n_cols - 1) * spacing) // n_cols
        
        # Multi-pass layout to ensure equal heights in rows
        rows = []
        current_row = []
        for i, item in enumerate(self._items):
            current_row.append(item)
            if (i + 1) % n_cols == 0 or (i + 1) == len(self._items):
                rows.append(current_row)
                current_row = []

        y = effective_rect.y()
        total_height = 0
        
        for row_items in rows:
            # 1. Find max height for this row
            row_max_h = 0
            item_heights = []
            for item in row_items:
                h = item.heightForWidth(item_width) if item.hasHeightForWidth() else item.sizeHint().height()
                item_heights.append(h)
                row_max_h = max(row_max_h, h)
            
            # 2. Position items in the row
            if not test_only:
                x = effective_rect.x()
                for item in row_items:
                    # Force the item to take the full row height
                    item.setGeometry(QRect(x, y, item_width, row_max_h))
                    x += item_width + spacing
            
            y += row_max_h + spacing
            total_height += row_max_h + spacing

        return y - rect.y() + bottom - (spacing if rows else 0)
