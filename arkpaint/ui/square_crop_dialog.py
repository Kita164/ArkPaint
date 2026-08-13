"""正方形裁剪：导入/截图后二次框选，保证转化区域比例为 1:1。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from arkpaint.ui.theme import app_icon

_HANDLE = 14  # 角点热区半宽（显示坐标）
_MIN_SIDE = 16  # 原图像素最小边长


class _SquareCropView(QWidget):
    """在缩放后的图上拖动/缩放正方形选框。"""

    selection_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._src = QPixmap()
        self._scale = 1.0
        self._offset = QPoint(0, 0)  # 图在控件内的左上角
        # 选区相对原图像素（正方形：x,y,side）
        self._sx = 0
        self._sy = 0
        self._side = 0
        self._drag: str | None = None  # move | tl|tr|bl|br | None
        self._press_pos = QPoint()
        self._press_sel = (0, 0, 0)
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_image(self, pix: QPixmap) -> None:
        self._src = QPixmap(pix)
        self._init_selection()
        self._recompute_layout()
        self.update()
        self.selection_changed.emit()

    def selection_rect(self) -> QRect:
        """原图像素坐标下的正方形选区。"""
        return QRect(self._sx, self._sy, self._side, self._side)

    def cropped_pixmap(self) -> QPixmap:
        if self._src.isNull() or self._side < 1:
            return QPixmap()
        return self._src.copy(self.selection_rect())

    def _init_selection(self) -> None:
        if self._src.isNull():
            self._sx = self._sy = self._side = 0
            return
        w, h = self._src.width(), self._src.height()
        side = min(w, h)
        self._side = max(_MIN_SIDE, side)
        self._sx = max(0, (w - self._side) // 2)
        self._sy = max(0, (h - self._side) // 2)

    def _recompute_layout(self) -> None:
        if self._src.isNull() or self.width() < 2 or self.height() < 2:
            self._scale = 1.0
            self._offset = QPoint(0, 0)
            return
        margin = 12
        aw = max(1, self.width() - margin * 2)
        ah = max(1, self.height() - margin * 2)
        sw, sh = self._src.width(), self._src.height()
        self._scale = min(aw / sw, ah / sh)
        dw = int(sw * self._scale)
        dh = int(sh * self._scale)
        self._offset = QPoint((self.width() - dw) // 2, (self.height() - dh) // 2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._recompute_layout()

    def _image_to_view(self, x: float, y: float) -> QPoint:
        return QPoint(
            int(round(self._offset.x() + x * self._scale)),
            int(round(self._offset.y() + y * self._scale)),
        )

    def _view_to_image(self, pos: QPoint) -> tuple[float, float]:
        if self._scale <= 0:
            return 0.0, 0.0
        return (
            (pos.x() - self._offset.x()) / self._scale,
            (pos.y() - self._offset.y()) / self._scale,
        )

    def _sel_view_rect(self) -> QRect:
        tl = self._image_to_view(self._sx, self._sy)
        br = self._image_to_view(self._sx + self._side, self._sy + self._side)
        return QRect(tl, br).normalized()

    def _hit_handle(self, pos: QPoint) -> str | None:
        r = self._sel_view_rect()
        if r.width() < 4:
            return None
        corners = {
            "tl": r.topLeft(),
            "tr": r.topRight(),
            "bl": r.bottomLeft(),
            "br": r.bottomRight(),
        }
        for name, pt in corners.items():
            if abs(pos.x() - pt.x()) <= _HANDLE and abs(pos.y() - pt.y()) <= _HANDLE:
                return name
        if r.contains(pos):
            return "move"
        return None

    def _clamp_selection(self, sx: int, sy: int, side: int) -> tuple[int, int, int]:
        if self._src.isNull():
            return 0, 0, 0
        w, h = self._src.width(), self._src.height()
        side = max(_MIN_SIDE, min(side, w, h))
        sx = max(0, min(sx, w - side))
        sy = max(0, min(sy, h - side))
        return sx, sy, side

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(26, 26, 26))
        if self._src.isNull():
            p.setPen(QColor(180, 180, 180))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "无图像")
            return

        dw = int(self._src.width() * self._scale)
        dh = int(self._src.height() * self._scale)
        dest = QRect(self._offset.x(), self._offset.y(), dw, dh)
        p.drawPixmap(dest, self._src)

        # 遮罩挖空选区（更深，突出边界）
        p.fillRect(self.rect(), QColor(8, 10, 14, 160))
        sel = self._sel_view_rect()
        if sel.width() > 2 and sel.height() > 2:
            src_rect = self.selection_rect()
            p.drawPixmap(sel, self._src, src_rect)
            # 外描边（深色）+ 内描边（亮青），边界更醒目
            outer = sel.adjusted(0, 0, -1, -1)
            p.setPen(QPen(QColor(20, 28, 36), 5))
            p.drawRect(outer)
            p.setPen(QPen(QColor(80, 240, 220), 3))
            p.drawRect(outer)
            # 角点更大、对比更强
            p.setBrush(QColor(255, 214, 10))
            p.setPen(QPen(QColor(20, 28, 36), 2))
            for pt in (sel.topLeft(), sel.topRight(), sel.bottomLeft(), sel.bottomRight()):
                p.drawRect(QRect(pt.x() - 6, pt.y() - 6, 12, 12))

            tip = f"{self._side} × {self._side}"
            p.setPen(QColor(255, 255, 255))
            p.drawText(sel.left() + 8, max(18, sel.top() - 8), tip)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._src.isNull():
            return
        pos = event.position().toPoint()
        hit = self._hit_handle(pos)
        if hit is None:
            # 在图内点击：以该点为中心放置当前大小的方框（或新建）
            ix, iy = self._view_to_image(pos)
            if 0 <= ix < self._src.width() and 0 <= iy < self._src.height():
                side = self._side if self._side > 0 else min(self._src.width(), self._src.height())
                sx = int(round(ix - side / 2))
                sy = int(round(iy - side / 2))
                self._sx, self._sy, self._side = self._clamp_selection(sx, sy, side)
                self._drag = "move"
                self._press_pos = pos
                self._press_sel = (self._sx, self._sy, self._side)
                self.update()
                self.selection_changed.emit()
            return
        self._drag = hit
        self._press_pos = pos
        self._press_sel = (self._sx, self._sy, self._side)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._drag is None:
            hit = self._hit_handle(pos)
            if hit in ("tl", "br"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif hit in ("tr", "bl"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif hit == "move":
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        dx = (pos.x() - self._press_pos.x()) / max(self._scale, 1e-6)
        dy = (pos.y() - self._press_pos.y()) / max(self._scale, 1e-6)
        ox, oy, os = self._press_sel

        if self._drag == "move":
            self._sx, self._sy, self._side = self._clamp_selection(
                int(round(ox + dx)), int(round(oy + dy)), os
            )
        else:
            # 以对角为锚，按拖动距离取较大分量保持正方形
            if self._drag == "br":
                anchor_x, anchor_y = ox, oy
                nx = ox + os + dx
                ny = oy + os + dy
                side = max(_MIN_SIDE, int(round(max(nx - anchor_x, ny - anchor_y))))
                self._sx, self._sy, self._side = self._clamp_selection(anchor_x, anchor_y, side)
            elif self._drag == "tl":
                anchor_x, anchor_y = ox + os, oy + os
                nx = ox + dx
                ny = oy + dy
                side = max(_MIN_SIDE, int(round(max(anchor_x - nx, anchor_y - ny))))
                self._sx, self._sy, self._side = self._clamp_selection(
                    anchor_x - side, anchor_y - side, side
                )
            elif self._drag == "tr":
                anchor_x, anchor_y = ox, oy + os
                nx = ox + os + dx
                ny = oy + dy
                side = max(_MIN_SIDE, int(round(max(nx - anchor_x, anchor_y - ny))))
                self._sx, self._sy, self._side = self._clamp_selection(
                    anchor_x, anchor_y - side, side
                )
            elif self._drag == "bl":
                anchor_x, anchor_y = ox + os, oy
                nx = ox + dx
                ny = oy + os + dy
                side = max(_MIN_SIDE, int(round(max(anchor_x - nx, ny - anchor_y))))
                self._sx, self._sy, self._side = self._clamp_selection(
                    anchor_x - side, anchor_y, side
                )

        self.update()
        self.selection_changed.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None


class SquareCropDialog(QDialog):
    """让用户拖动正方形框选择要转化为 24×24 的区域。"""

    def __init__(self, pixmap: QPixmap, parent=None, *, title: str = "选择正方形转化区域") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.resize(720, 560)
        self._result = QPixmap()

        root = QVBoxLayout(self)
        hint = QLabel("拖动方框移动 · 拖四角缩放（保持正方形）· 确认后转为 24×24")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.view = _SquareCropView()
        self.view.set_image(pixmap)
        root.addWidget(self.view, 1)

        self.info = QLabel()
        self.info.setObjectName("hint")
        root.addWidget(self.info)
        self.view.selection_changed.connect(self._update_info)
        self._update_info()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_btn.setText("确认转化")
        ok_btn.setObjectName("primaryButton")
        ok_btn.setMinimumHeight(36)
        ok_btn.setMinimumWidth(120)
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        cancel_btn.setText("取消")
        cancel_btn.setMinimumHeight(36)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _update_info(self) -> None:
        r = self.view.selection_rect()
        self.info.setText(f"选区：{r.width()} × {r.height()} 像素（将缩放为 24×24）")

    def _accept(self) -> None:
        cropped = self.view.cropped_pixmap()
        if cropped.isNull() or cropped.width() < 4:
            return
        self._result = cropped
        self.accept()

    def cropped_pixmap(self) -> QPixmap:
        return self._result


def crop_square_interactive(pixmap: QPixmap, parent=None, *, title: str | None = None) -> QPixmap | None:
    """弹出正方形裁剪；确认返回裁切图，取消返回 None。"""
    if pixmap.isNull():
        return None
    kwargs = {}
    if title:
        kwargs["title"] = title
    dlg = SquareCropDialog(pixmap, parent, **kwargs)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    out = dlg.cropped_pixmap()
    return None if out.isNull() else out
