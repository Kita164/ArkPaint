"""右侧颜料栏：编号展示、当前色高亮。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from arkpaint.config import PALETTE_COLUMNS
from arkpaint.core.palette import PaletteColor

_CELL = 52
_GAP = 6
_PAD = 4


def _grid_content_width(columns: int = PALETTE_COLUMNS) -> int:
    """色块网格内容所需宽度（含左右内边距）。"""
    if columns <= 0:
        return _PAD * 2
    return _PAD * 2 + columns * _CELL + (columns - 1) * _GAP


class PalettePanel(QWidget):
    color_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._palette: list[PaletteColor] = []
        self._active = 1
        self._drawing_color: int | None = None
        self._show_numbers = True
        # 左右 layout 边距 8+8，需能放下全部列，避免第 4 列被裁切
        self.setMinimumWidth(_grid_content_width() + 16)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("颜料")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel("点击选色 · 编号与游戏色盘顺序对应")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._grid = _PaletteGrid()
        self._grid.color_selected.connect(self._on_select)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self._grid)
        layout.addWidget(scroll, 1)

    def set_palette(self, palette: list[PaletteColor]) -> None:
        self._palette = list(palette)
        self._grid.set_palette(self._palette)
        self._grid.set_active(self._active)
        self._grid.set_drawing_color(self._drawing_color)
        self._grid.set_show_numbers(self._show_numbers)

    def set_active(self, index: int) -> None:
        self._active = index
        self._grid.set_active(index)

    def active(self) -> int:
        return self._active

    def set_drawing_color(self, index: int | None) -> None:
        self._drawing_color = index
        self._grid.set_drawing_color(index)

    def set_show_numbers(self, show: bool) -> None:
        self._show_numbers = show
        self._grid.set_show_numbers(show)

    def _on_select(self, index: int) -> None:
        self._active = index
        self._grid.set_active(index)
        self.color_selected.emit(index)


class _PaletteGrid(QWidget):
    color_selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._palette: list[PaletteColor] = []
        self._active = 1
        self._drawing: int | None = None
        self._show_numbers = True
        self._cell = _CELL
        self._gap = _GAP
        self.setMouseTracking(True)
        self.setMinimumWidth(_grid_content_width())
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        rows = max(1, (len(self._palette) + PALETTE_COLUMNS - 1) // PALETTE_COLUMNS)
        h = max(120, _PAD * 2 + rows * self._cell + max(0, rows - 1) * self._gap)
        return QSize(_grid_content_width(), h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_palette(self, palette: list[PaletteColor]) -> None:
        self._palette = list(palette)
        hint = self.sizeHint()
        self.setMinimumWidth(hint.width())
        self.setMinimumHeight(hint.height())
        self.updateGeometry()
        self.update()

    def set_active(self, index: int) -> None:
        self._active = index
        self.update()

    def set_drawing_color(self, index: int | None) -> None:
        self._drawing = index
        self.update()

    def set_show_numbers(self, show: bool) -> None:
        self._show_numbers = show
        self.update()

    def _index_at(self, x: int, y: int) -> int | None:
        stride = self._cell + self._gap
        col = (x - _PAD) // stride
        row = (y - _PAD) // stride
        if col < 0 or col >= PALETTE_COLUMNS or row < 0:
            return None
        idx = row * PALETTE_COLUMNS + col
        if 0 <= idx < len(self._palette):
            return self._palette[idx].index
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._index_at(int(event.position().x()), int(event.position().y()))
            if idx is not None:
                self.color_selected.emit(idx)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(42, 42, 42))
        font = QFont("Consolas", 10)
        font.setBold(True)
        p.setFont(font)
        stride = self._cell + self._gap

        for i, color in enumerate(self._palette):
            row, col = divmod(i, PALETTE_COLUMNS)
            rect_x = _PAD + col * stride
            rect_y = _PAD + row * stride
            p.fillRect(rect_x, rect_y, self._cell, self._cell, QColor(*color.rgb))

            # 当前绘制色：青绿粗框；选中：亮黄框（呼应 logo）
            if self._drawing == color.index:
                p.setPen(QPen(QColor(0x5E, 0xC8, 0xC0), 3))
                p.drawRect(rect_x + 1, rect_y + 1, self._cell - 3, self._cell - 3)
            elif self._active == color.index:
                p.setPen(QPen(QColor(0xFF, 0xD7, 0x00), 2))
                p.drawRect(rect_x + 1, rect_y + 1, self._cell - 3, self._cell - 3)
            else:
                p.setPen(QPen(QColor(0x1A, 0x1A, 0x1A), 2))
                p.drawRect(rect_x, rect_y, self._cell - 1, self._cell - 1)

            if self._show_numbers:
                lum = 0.299 * color.rgb[0] + 0.587 * color.rgb[1] + 0.114 * color.rgb[2]
                p.setPen(QColor(255, 255, 255) if lum < 140 else QColor(25, 25, 25))
                p.drawText(
                    rect_x,
                    rect_y,
                    self._cell,
                    self._cell,
                    Qt.AlignmentFlag.AlignCenter,
                    str(color.index),
                )
