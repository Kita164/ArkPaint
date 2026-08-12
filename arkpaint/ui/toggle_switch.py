"""轻量 UI 控件。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QWidget


class LightToggleSwitch(QWidget):
    """浅色胶囊开关（开：浅蓝轨道；关：浅灰轨道）。"""

    toggled = Signal(bool)

    def __init__(self, parent=None, *, checked: bool = True) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.setToolTip("显示 / 隐藏编号")

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(self._checked)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = QRectF(1.5, 3.5, self.width() - 3, self.height() - 7)
        radius = track.height() / 2

        # 浅色主题：开=柔和蓝，关=浅灰
        if self._checked:
            track_color = QColor(155, 186, 230)  # soft blue
            border = QColor(130, 165, 215)
        else:
            track_color = QColor(220, 224, 230)
            border = QColor(190, 196, 205)

        path = QPainterPath()
        path.addRoundedRect(track, radius, radius)
        p.fillPath(path, track_color)
        p.setPen(border)
        p.drawPath(path)

        # 圆形滑块（偏白，带轻微阴影感）
        margin = 3.0
        thumb_d = track.height() - margin * 2
        if self._checked:
            cx = track.right() - margin - thumb_d / 2
        else:
            cx = track.left() + margin + thumb_d / 2
        cy = track.center().y()
        thumb = QRectF(cx - thumb_d / 2, cy - thumb_d / 2, thumb_d, thumb_d)

        # 轻阴影
        shadow = QRectF(thumb).translated(0.6, 0.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(80, 90, 110, 45))
        p.drawEllipse(shadow)

        grad = QRadialGradient(QPointF(cx - 1, cy - 2), thumb_d * 0.75)
        grad.setColorAt(0.0, QColor(255, 255, 255))
        grad.setColorAt(1.0, QColor(236, 239, 244))
        p.setBrush(grad)
        p.setPen(QColor(200, 206, 216))
        p.drawEllipse(thumb)
