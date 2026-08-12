"""校准：优先一键自动识别；必要时可手动点选画布/颜料。"""

from __future__ import annotations

from enum import Enum, auto

import cv2
import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from arkpaint.core.adb import AdbController, AdbError
from arkpaint.core.auto_calibrate import auto_calibrate
from arkpaint.core.calibration import CalibrationData, save_calibration
from arkpaint.core.detector import detect_canvas_region
from arkpaint.ui.theme import app_icon


class CalibStep(Enum):
    CANVAS_TL = auto()
    CANVAS_BR = auto()
    COLOR_FIRST = auto()
    COLOR_RIGHT = auto()  # 第一行第 2 个色，用于 dx
    COLOR_BELOW = auto()  # 第二行第 1 个色，用于 dy
    SCROLL_START = auto()
    SCROLL_END = auto()
    DONE = auto()


STEP_HINTS = {
    CalibStep.CANVAS_TL: "点击画布【左上角】格子外缘",
    CalibStep.CANVAS_BR: "点击画布【右下角】格子外缘",
    CalibStep.COLOR_FIRST: "点击右侧颜料【第 1 色】中心",
    CalibStep.COLOR_RIGHT: "点击右侧颜料【第 2 色】中心（同排右侧）",
    CalibStep.COLOR_BELOW: "点击右侧颜料【第 5 色】中心（下一排第一个，4 列布局）",
    CalibStep.SCROLL_START: "在颜料区域中部点击【上滑起点】",
    CalibStep.SCROLL_END: "再点击【上滑终点】（起点上方一点，用于翻出色盘下部）",
    CalibStep.DONE: "校准完成，可保存",
}


class _ShotView(QWidget):
    clicked = Signal(int, int)  # 原图像素坐标

    def __init__(self) -> None:
        super().__init__()
        self._bgr: np.ndarray | None = None
        self._marks: list[tuple[int, int, str]] = []
        self.setMinimumSize(640, 360)
        self.setStyleSheet("background:#1a1a1a;")

    def set_image(self, bgr: np.ndarray) -> None:
        self._bgr = bgr
        self.update()

    def clear_marks(self) -> None:
        self._marks.clear()
        self.update()

    def add_mark(self, x: int, y: int, label: str) -> None:
        self._marks.append((x, y, label))
        self.update()

    def _scale(self) -> tuple[float, int, int]:
        if self._bgr is None:
            return 1.0, 0, 0
        h, w = self._bgr.shape[:2]
        sx = self.width() / w
        sy = self.height() / h
        scale = min(sx, sy)
        ow = int(w * scale)
        oh = int(h * scale)
        ox = (self.width() - ow) // 2
        oy = (self.height() - oh) // 2
        return scale, ox, oy

    def mousePressEvent(self, event) -> None:
        if self._bgr is None or event.button() != Qt.MouseButton.LeftButton:
            return
        scale, ox, oy = self._scale()
        px = int((event.position().x() - ox) / scale)
        py = int((event.position().y() - oy) / scale)
        h, w = self._bgr.shape[:2]
        if 0 <= px < w and 0 <= py < h:
            self.clicked.emit(px, py)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(26, 26, 26))
        if self._bgr is None:
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "点击「刷新截图」获取模拟器画面")
            return
        rgb = cv2.cvtColor(self._bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        scale, ox, oy = self._scale()
        pix = QPixmap.fromImage(qimg).scaled(
            int(w * scale),
            int(h * scale),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(ox, oy, pix)
        for x, y, label in self._marks:
            sx = int(ox + x * scale)
            sy = int(oy + y * scale)
            painter.setPen(QPen(QColor(0, 220, 255), 2))
            painter.drawEllipse(QPoint(sx, sy), 8, 8)
            painter.drawText(sx + 10, sy - 6, label)


class CalibrateDialog(QDialog):
    def __init__(self, adb: AdbController, calib: CalibrationData, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("校准 · 画布与颜料栏")
        self.setWindowIcon(app_icon())
        self.resize(980, 640)
        self.adb = adb
        self.calib = CalibrationData.from_dict(calib.to_dict())
        self.step = CalibStep.CANVAS_TL
        self._pending: dict[str, tuple[int, int]] = {}

        root = QVBoxLayout(self)
        self.hint = QLabel(STEP_HINTS[self.step])
        self.hint.setStyleSheet(
            "font-size:13px; font-weight:700; color:#5EC8C0; padding:6px;"
            "border-bottom:2px solid #2A82F4;"
        )
        root.addWidget(self.hint)

        self.view = _ShotView()
        self.view.clicked.connect(self._on_click)
        root.addWidget(self.view, 1)

        form = QFormLayout()
        self.spin_visible = QSpinBox()
        self.spin_visible.setRange(1, 20)
        self.spin_visible.setValue(self.calib.visible_rows)
        self.spin_total = QSpinBox()
        self.spin_total.setRange(1, 128)
        self.spin_total.setValue(self.calib.total_colors)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 8)
        self.spin_cols.setValue(self.calib.palette_columns)
        self.spin_rps = QSpinBox()
        self.spin_rps.setRange(1, 12)
        self.spin_rps.setValue(self.calib.rows_per_scroll)
        form.addRow("颜料列数", self.spin_cols)
        form.addRow("可见行数", self.spin_visible)
        form.addRow("总色数", self.spin_total)
        form.addRow("每次上滑约翻行数", self.spin_rps)
        root.addLayout(form)

        btns = QHBoxLayout()
        self.btn_shot = QPushButton("刷新截图")
        self.btn_auto_all = QPushButton("一键自动校准")
        self.btn_auto_all.setObjectName("primaryButton")
        self.btn_auto_all.setToolTip("识别中央画布与右侧 4 列颜料栏（分辨率自适应）")
        self.btn_auto = QPushButton("仅检测画布")
        self.btn_restart = QPushButton("重新开始")
        self.btn_save = QPushButton("保存校准")
        self.btn_close = QPushButton("关闭")
        for b in (
            self.btn_shot,
            self.btn_auto_all,
            self.btn_auto,
            self.btn_restart,
            self.btn_save,
            self.btn_close,
        ):
            btns.addWidget(b)
        root.addLayout(btns)

        self.btn_shot.clicked.connect(self.refresh_shot)
        self.btn_auto_all.clicked.connect(lambda: self.run_auto_calibrate(False))
        self.btn_auto.clicked.connect(self.auto_canvas)
        self.btn_restart.clicked.connect(self.restart)
        self.btn_save.clicked.connect(self.save)
        self.btn_close.clicked.connect(self.reject)

        self.refresh_shot()
        # 打开即尝试自动校准，失败则保留手动步骤提示
        self.run_auto_calibrate(silent_if_fail=True)

    def refresh_shot(self) -> None:
        try:
            img = self.adb.screencap()
        except AdbError as exc:
            QMessageBox.warning(self, "截图失败", str(exc))
            return
        self.view.set_image(img)
        self._redraw_marks()

    def run_auto_calibrate(self, silent_if_fail: bool = False) -> bool:
        """全自动识别画布+颜料+滑动。成功返回 True。"""
        if self.view._bgr is None:
            self.refresh_shot()
        if self.view._bgr is None:
            if not silent_if_fail:
                QMessageBox.warning(self, "自动校准", "没有可用截图")
            return False
        result = auto_calibrate(
            self.view._bgr,
            total_colors=self.spin_total.value(),
            columns=self.spin_cols.value(),
            rows_per_scroll=self.spin_rps.value(),
        )
        if not result.ok or result.calibration is None:
            if not silent_if_fail:
                QMessageBox.warning(
                    self,
                    "自动校准失败",
                    f"{result.message}\n\n请确认色板滚到顶部，或改用手动点选。",
                )
            return False

        self.calib = result.calibration
        self.spin_visible.setValue(self.calib.visible_rows)
        self.spin_total.setValue(self.calib.total_colors)
        self.spin_cols.setValue(self.calib.palette_columns)
        self.spin_rps.setValue(self.calib.rows_per_scroll)
        self.step = CalibStep.DONE
        self.hint.setText(f"自动校准完成 — {result.message}")
        self._redraw_marks()
        if not silent_if_fail:
            QMessageBox.information(
                self,
                "自动校准",
                f"{result.message}\n\n请核对截图上的标记，确认后点「保存校准」。",
            )
        return True

    def auto_canvas(self) -> None:
        if self.view._bgr is None:
            return
        rect = detect_canvas_region(self.view._bgr)
        if not rect:
            QMessageBox.information(self, "提示", "未能自动找到画布，请手动点选两角")
            return
        x, y, w, h = rect
        self.calib.canvas_tl = (x, y)
        self.calib.canvas_br = (x + w, y + h)
        self._pending["canvas_tl"] = self.calib.canvas_tl
        self._pending["canvas_br"] = self.calib.canvas_br
        self.step = CalibStep.COLOR_FIRST
        self.hint.setText(STEP_HINTS[self.step])
        self._redraw_marks()
        QMessageBox.information(self, "画布", f"已检测画布区域 {rect}，请继续校准颜料")

    def restart(self) -> None:
        self.step = CalibStep.CANVAS_TL
        self._pending.clear()
        self.view.clear_marks()
        self.hint.setText(STEP_HINTS[self.step])

    def _redraw_marks(self) -> None:
        self.view.clear_marks()
        if self.calib.canvas_tl:
            self.view.add_mark(*self.calib.canvas_tl, "画布TL")
        if self.calib.canvas_br:
            self.view.add_mark(*self.calib.canvas_br, "画布BR")
        if self.calib.palette_origin:
            ox, oy = self.calib.palette_origin
            self.view.add_mark(ox, oy, "色1")
            if self.calib.palette_dx > 0:
                self.view.add_mark(int(ox + self.calib.palette_dx), oy, "色2")
            if self.calib.palette_dy > 0:
                self.view.add_mark(ox, int(oy + self.calib.palette_dy), "色5")
        if self.calib.scroll_from:
            self.view.add_mark(*self.calib.scroll_from, "滑起")
        if self.calib.scroll_to:
            self.view.add_mark(*self.calib.scroll_to, "滑终")

    def _on_click(self, x: int, y: int) -> None:
        if self.step == CalibStep.CANVAS_TL:
            self.calib.canvas_tl = (x, y)
            self.step = CalibStep.CANVAS_BR
        elif self.step == CalibStep.CANVAS_BR:
            self.calib.canvas_br = (x, y)
            self.step = CalibStep.COLOR_FIRST
        elif self.step == CalibStep.COLOR_FIRST:
            self._pending["c1"] = (x, y)
            self.calib.palette_origin = (x, y)
            self.step = CalibStep.COLOR_RIGHT
        elif self.step == CalibStep.COLOR_RIGHT:
            self._pending["c2"] = (x, y)
            self.step = CalibStep.COLOR_BELOW
        elif self.step == CalibStep.COLOR_BELOW:
            self._pending["c5"] = (x, y)
            c1 = self._pending["c1"]
            c2 = self._pending["c2"]
            c5 = self._pending["c5"]
            self.calib.palette_origin = c1
            self.calib.palette_dx = float(c2[0] - c1[0])
            self.calib.palette_dy = float(c5[1] - c1[1])
            self.step = CalibStep.SCROLL_START
        elif self.step == CalibStep.SCROLL_START:
            self.calib.scroll_from = (x, y)
            self.step = CalibStep.SCROLL_END
        elif self.step == CalibStep.SCROLL_END:
            self.calib.scroll_to = (x, y)
            self.step = CalibStep.DONE
        self.hint.setText(STEP_HINTS[self.step])
        self._redraw_marks()

    def _sample_visible_colors(self) -> list[list[int]]:
        if self.view._bgr is None or not self.calib.is_palette_ready():
            return []
        bgr = self.view._bgr
        rgbs: list[list[int]] = []
        count = min(self.spin_total.value(), self.spin_cols.value() * self.spin_visible.value())
        for i in range(count):
            row, col = divmod(i, self.spin_cols.value())
            # 临时用当前参数
            ox, oy = self.calib.palette_origin  # type: ignore[misc]
            dx, dy = self.calib.palette_dx, self.calib.palette_dy
            cx, cy = int(ox + col * dx), int(oy + row * dy)
            cy = min(max(cy, 0), bgr.shape[0] - 1)
            cx = min(max(cx, 0), bgr.shape[1] - 1)
            # 取 5x5 中值，抗锯齿
            patch = bgr[max(0, cy - 2) : cy + 3, max(0, cx - 2) : cx + 3]
            if patch.size == 0:
                continue
            b, g, r = [int(v) for v in np.median(patch.reshape(-1, 3), axis=0)]
            rgbs.append([r, g, b])
        return rgbs

    def save(self) -> None:
        self.calib.visible_rows = self.spin_visible.value()
        self.calib.total_colors = self.spin_total.value()
        self.calib.palette_columns = self.spin_cols.value()
        self.calib.rows_per_scroll = self.spin_rps.value()
        if not self.calib.is_canvas_ready() or not self.calib.is_palette_ready():
            QMessageBox.warning(self, "未完成", "请完成画布与颜料关键步骤后再保存")
            return
        if not self.calib.scroll_from or not self.calib.scroll_to:
            QMessageBox.warning(self, "未完成", "请完成滑动起止点校准（色盘可滚动）")
            return
        sampled = self._sample_visible_colors()
        if sampled:
            self.calib.sampled_rgbs = sampled
        save_calibration(self.calib)
        QMessageBox.information(self, "已保存", f"校准已写入\n可见色已采样 {len(sampled)} 个")
        self.accept()

    def result_calibration(self) -> CalibrationData:
        return self.calib
