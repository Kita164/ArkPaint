"""屏幕区域框选截图。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def grab_virtual_desktop() -> tuple[QPixmap, QRect]:
    """截取全部显示器组成的虚拟桌面，返回 (像素图, 虚拟桌面几何)。"""
    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("无法获取屏幕")
    # 虚拟桌面原点可能为负（副屏在左/上）
    geo = screens[0].virtualGeometry()
    canvas = QPixmap(geo.size())
    canvas.fill(QColor(0, 0, 0))
    painter = QPainter(canvas)
    for screen in screens:
        g = screen.geometry()
        part = screen.grabWindow(0)
        painter.drawPixmap(g.topLeft() - geo.topLeft(), part)
    painter.end()
    return canvas, geo


class RegionCaptureOverlay(QWidget):
    """全屏半透明遮罩，拖拽框选后裁切背景图。"""

    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, background: QPixmap, desktop_geo: QRect, parent=None) -> None:
        super().__init__(parent)
        self._bg = background
        self._desktop_geo = QRect(desktop_geo)
        self._origin: QPoint | None = None
        self._current = QPoint()
        self._selecting = False
        self._finished = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(desktop_geo)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _selection_rect(self) -> QRect:
        if self._origin is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # 背景为冻结的桌面截图（相对本窗口左上角绘制）
        p.drawPixmap(0, 0, self._bg)

        # 半透明遮罩
        p.fillRect(self.rect(), QColor(20, 24, 30, 110))

        sel = self._selection_rect()
        if sel.width() > 2 and sel.height() > 2:
            # 挖空选区：重画清晰背景
            p.drawPixmap(sel, self._bg, sel)
            p.setPen(QPen(QColor(90, 160, 255), 2))
            p.drawRect(sel.adjusted(0, 0, -1, -1))
            # 尺寸提示
            tip = f"{sel.width()} × {sel.height()}"
            p.setPen(QColor(255, 255, 255))
            p.drawText(sel.left() + 6, max(16, sel.top() - 6), tip)

        p.setPen(QColor(240, 244, 250))
        p.drawText(
            QRect(20, 12, 640, 48),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            "拖拽框选大致区域 · 松开确认 · Esc 取消\n（随后可再拖正方形框精确裁切）",
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._selecting = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event) -> None:
        self._current = event.position().toPoint()
        if self._selecting:
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            sel = self._selection_rect()
            if sel.width() >= 4 and sel.height() >= 4:
                cropped = self._bg.copy(sel)
                self._finished = True
                # 先隐藏遮罩，再发信号，避免接收方同步弹模态窗时被本层挡住
                self.hide()
                self.captured.emit(cropped)
                self.close()
            else:
                self._origin = None
                self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if not self._finished:
            self._finished = True
            self.cancelled.emit()
        super().closeEvent(event)

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancelled.emit()
        self.close()


def start_region_capture(*, on_captured, on_cancelled=None) -> RegionCaptureOverlay:
    """弹出框选层。调用前建议先隐藏主窗口。"""
    QApplication.processEvents()
    bg, geo = grab_virtual_desktop()
    overlay = RegionCaptureOverlay(bg, geo)
    overlay.captured.connect(on_captured)
    if on_cancelled:
        overlay.cancelled.connect(on_cancelled)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()
    overlay.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    return overlay
