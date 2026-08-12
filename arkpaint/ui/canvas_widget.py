"""中央 24×24 像素画布：展示、点选改色、滚轮缩放与边缘平移。"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from arkpaint.config import GRID_SIZE
from arkpaint.core.palette import PaletteColor

_MIN_ZOOM = 1.0
_MAX_ZOOM = 8.0
_ZOOM_STEP = 1.15
_EDGE_PX = 32
_EDGE_PAN_SPEED = 14  # 每帧平移像素


class PixelCanvas(QWidget):
    cell_clicked = Signal(int, int)  # row, col
    grid_changed = Signal()
    can_undo_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 420)
        self._grid = np.ones((GRID_SIZE, GRID_SIZE), dtype=np.int32)
        self._palette: list[PaletteColor] = []
        self._show_numbers = True
        self._active_color = 1
        self._hover: tuple[int, int] | None = None
        self._undo_stack: list[np.ndarray] = []
        self._max_undo = 60
        self._stroke_open = False
        # 缩放：1.0 = 默认铺满（最小，不可再缩小）；平移相对「居中」位置
        self._zoom = _MIN_ZOOM
        self._pan = QPointF(0.0, 0.0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.activated.connect(self.undo)

        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(16)
        self._edge_timer.timeout.connect(self._edge_pan_tick)
        self._edge_timer.start()

    def set_palette(self, palette: list[PaletteColor]) -> None:
        self._palette = list(palette)
        self.update()

    def set_grid(self, grid: np.ndarray, *, clear_history: bool = True) -> None:
        self._grid = np.array(grid, dtype=np.int32, copy=True)
        if clear_history:
            self._undo_stack.clear()
            self.can_undo_changed.emit(False)
        self.update()
        self.grid_changed.emit()

    def grid(self) -> np.ndarray:
        return self._grid.copy()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._grid = self._undo_stack.pop()
        self.can_undo_changed.emit(bool(self._undo_stack))
        self.grid_changed.emit()
        self.update()
        return True

    def _push_undo(self) -> None:
        self._undo_stack.append(self._grid.copy())
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self.can_undo_changed.emit(True)

    def _begin_stroke(self) -> None:
        if not self._stroke_open:
            self._push_undo()
            self._stroke_open = True

    def set_show_numbers(self, show: bool) -> None:
        self._show_numbers = show
        self.update()

    def show_numbers(self) -> bool:
        return self._show_numbers

    def set_active_color(self, index: int) -> None:
        self._active_color = index

    def active_color(self) -> int:
        return self._active_color

    def zoom(self) -> float:
        return self._zoom

    def _fit_side(self) -> int:
        side = min(self.width(), self.height()) - 16
        return max(side, 48)

    def _board_side(self) -> float:
        return self._fit_side() * self._zoom

    def _board_rect(self) -> QRect:
        side = self._board_side()
        x = (self.width() - side) / 2.0 + self._pan.x()
        y = (self.height() - side) / 2.0 + self._pan.y()
        # 用整像素绘制，避免网格缝隙闪烁
        return QRect(int(round(x)), int(round(y)), int(round(side)), int(round(side)))

    def _max_pan(self) -> tuple[float, float]:
        """允许的平移半幅（使放大后仍能移到四角）。"""
        side = self._board_side()
        # 至少留 40px 画板仍在视口内，同时保证能看清边角
        overflow_x = max(0.0, (side - self.width()) / 2.0 + 8.0)
        overflow_y = max(0.0, (side - self.height()) / 2.0 + 8.0)
        return overflow_x, overflow_y

    def _clamp_pan(self) -> None:
        if self._zoom <= _MIN_ZOOM + 1e-6:
            self._pan = QPointF(0.0, 0.0)
            return
        mx, my = self._max_pan()
        self._pan.setX(max(-mx, min(mx, self._pan.x())))
        self._pan.setY(max(-my, min(my, self._pan.y())))

    def _cell_at(self, pos: QPoint) -> tuple[int, int] | None:
        rect = self._board_rect()
        if not rect.contains(pos):
            return None
        col = int((pos.x() - rect.x()) / rect.width() * GRID_SIZE)
        row = int((pos.y() - rect.y()) / rect.height() * GRID_SIZE)
        if 0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE:
            return row, col
        return None

    def _rgb_for(self, index: int) -> tuple[int, int, int]:
        for c in self._palette:
            if c.index == index:
                return c.rgb
        return (255, 255, 255)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        old_zoom = self._zoom
        if delta > 0:
            new_zoom = min(_MAX_ZOOM, old_zoom * _ZOOM_STEP)
        else:
            new_zoom = max(_MIN_ZOOM, old_zoom / _ZOOM_STEP)
        if abs(new_zoom - old_zoom) < 1e-6:
            event.accept()
            return

        # 以光标下的画板点为锚点缩放
        pos = event.position()
        board = self._board_rect()
        if board.width() > 0 and board.height() > 0:
            fx = (pos.x() - board.x()) / board.width()
            fy = (pos.y() - board.y()) / board.height()
        else:
            fx = fy = 0.5

        self._zoom = new_zoom
        new_side = self._board_side()
        # 新 board 左上角，使锚点仍在光标下
        new_x = pos.x() - fx * new_side
        new_y = pos.y() - fy * new_side
        self._pan = QPointF(
            new_x - (self.width() - new_side) / 2.0,
            new_y - (self.height() - new_side) / 2.0,
        )
        self._clamp_pan()
        self.update()
        event.accept()

    def _edge_pan_tick(self) -> None:
        if self._zoom <= _MIN_ZOOM + 1e-6:
            return
        if not self.underMouse():
            return
        pos = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(pos):
            return
        dx = dy = 0.0
        # 鼠标靠左 → 画板右移（露出左侧内容）
        if pos.x() <= _EDGE_PX:
            dx = _EDGE_PAN_SPEED
        elif pos.x() >= self.width() - _EDGE_PX:
            dx = -_EDGE_PAN_SPEED
        if pos.y() <= _EDGE_PX:
            dy = _EDGE_PAN_SPEED
        elif pos.y() >= self.height() - _EDGE_PX:
            dy = -_EDGE_PAN_SPEED
        if dx == 0 and dy == 0:
            return
        self._pan += QPointF(dx, dy)
        self._clamp_pan()
        # 平移时同步刷新悬停格（便于边缘继续涂色）
        self._hover = self._cell_at(pos)
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton and self._hover:
            r, c = self._hover
            if self._grid[r, c] != self._active_color:
                self._begin_stroke()
                self._grid[r, c] = self._active_color
                self.grid_changed.emit()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            if cell:
                r, c = cell
                if int(self._grid[r, c]) != self._active_color:
                    self._begin_stroke()
                    self._grid[r, c] = self._active_color
                    self.grid_changed.emit()
                    self.update()
                self.cell_clicked.emit(r, c)
        elif event.button() == Qt.MouseButton.RightButton:
            cell = self._cell_at(event.position().toPoint())
            if cell:
                r, c = cell
                self._active_color = int(self._grid[r, c])
                self.cell_clicked.emit(r, c)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._hover = self._cell_at(event.position().toPoint())
        if event.buttons() & Qt.MouseButton.LeftButton and self._hover:
            r, c = self._hover
            if self._grid[r, c] != self._active_color:
                self._begin_stroke()
                self._grid[r, c] = self._active_color
                self.grid_changed.emit()
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._stroke_open = False
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        self._clamp_pan()
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        board = self._board_rect()
        cell_w = board.width() / GRID_SIZE
        cell_h = board.height() / GRID_SIZE

        painter.fillRect(self.rect(), QColor(32, 34, 38))
        painter.fillRect(board, QColor(245, 245, 245))

        # 放大时编号字号随格子变大，但设上限以免糊成一团
        font_px = max(7, min(22, int(min(cell_w, cell_h) * 0.32)))
        font = QFont("Segoe UI", font_px)
        font.setBold(True)
        painter.setFont(font)

        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                idx = int(self._grid[r, c])
                rgb = self._rgb_for(idx)
                rect = QRect(
                    int(board.x() + c * cell_w),
                    int(board.y() + r * cell_h),
                    int(cell_w) + 1,
                    int(cell_h) + 1,
                )
                painter.fillRect(rect, QColor(*rgb))
                if self._show_numbers and cell_w >= 12 and cell_h >= 12:
                    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                    painter.setPen(QColor(255, 255, 255) if lum < 140 else QColor(20, 20, 20))
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(idx))

        painter.setPen(QPen(QColor(60, 60, 60, 90), 1))
        for i in range(GRID_SIZE + 1):
            x = int(board.x() + i * cell_w)
            y = int(board.y() + i * cell_h)
            painter.drawLine(x, board.y(), x, board.y() + board.height())
            painter.drawLine(board.x(), y, board.x() + board.width(), y)

        painter.setPen(QPen(QColor(20, 20, 20), 2))
        mid = GRID_SIZE // 2
        mx = int(board.x() + mid * cell_w)
        my = int(board.y() + mid * cell_h)
        painter.drawLine(mx, board.y(), mx, board.y() + board.height())
        painter.drawLine(board.x(), my, board.x() + board.width(), my)

        painter.setPen(QPen(QColor(30, 30, 30), 2))
        painter.drawRect(board.adjusted(0, 0, -1, -1))

        # 边缘感应提示条（仅放大时）
        if self._zoom > _MIN_ZOOM + 1e-6:
            hint = QColor(90, 160, 255, 35)
            painter.fillRect(0, 0, _EDGE_PX, self.height(), hint)
            painter.fillRect(self.width() - _EDGE_PX, 0, _EDGE_PX, self.height(), hint)
            painter.fillRect(0, 0, self.width(), _EDGE_PX, hint)
            painter.fillRect(0, self.height() - _EDGE_PX, self.width(), _EDGE_PX, hint)

        if self._hover:
            hr, hc = self._hover
            rect = QRect(
                int(board.x() + hc * cell_w),
                int(board.y() + hr * cell_h),
                int(cell_w),
                int(cell_h),
            )
            painter.setPen(QPen(QColor(0, 200, 255), 2))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def to_qimage(self, scale: int = 16) -> QImage:
        h, w = self._grid.shape
        img = QImage(w * scale, h * scale, QImage.Format.Format_RGB32)
        for r in range(h):
            for c in range(w):
                rgb = self._rgb_for(int(self._grid[r, c]))
                color = QColor(*rgb)
                for dy in range(scale):
                    for dx in range(scale):
                        img.setPixelColor(c * scale + dx, r * scale + dy, color)
        return img
