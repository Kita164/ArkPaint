"""主窗口：导入图片、编辑像素、ADB 连接与自动绘制。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from arkpaint.config import (
    DATA_DIR,
    DEFAULT_ADB_HOST,
    DEFAULT_ADB_PORT,
    DEFAULT_DETECT_CONFIDENCE,
    DEFAULT_TAP_DELAY_MS,
    MUMU_ADB_BASE_PORT,
    MUMU_ADB_PORT_STEP,
    MUMU_ADB_SCAN_INSTANCES,
    SETTINGS_PATH,
    ensure_dirs,
    load_json,
    save_json,
)
from arkpaint.core.adb import AdbController, AdbError
from arkpaint.core.calibration import CalibrationData, load_calibration
from arkpaint.core.image_processor import blank_grid, image_to_grid
from arkpaint.core.painter import AutoPainter, PaintOptions, PaintProgress
from arkpaint.core.palette import DEFAULT_PALETTE, PaletteColor, find_white_index, rebuild_palette
from arkpaint.paths import find_adb, mumu_instance_label
from arkpaint.ui.calibrate_dialog import CalibrateDialog
from arkpaint.ui.canvas_widget import PixelCanvas
from arkpaint.ui.palette_widget import PalettePanel
from arkpaint.ui.toggle_switch import LightToggleSwitch

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
_PREVIEW_EMPTY_STYLE = (
    "background:#e8eaed; border:1px dashed #b8bec8; border-radius:4px; color:#6b7280;"
)
_PREVIEW_FILLED_STYLE = (
    "background:#e8eaed; border:1px solid #c5c9d0; border-radius:4px; color:#6b7280;"
)


class ImagePreviewLabel(QLabel):
    """支持拖入图片的预览区。"""

    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in _IMAGE_SUFFIXES:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in _IMAGE_SUFFIXES:
                paths.append(path)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()


class PaintWorker(QThread):
    progress = Signal(object)  # PaintProgress
    color_changed = Signal(int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        adb: AdbController,
        calib: CalibrationData,
        grid: np.ndarray,
        options: PaintOptions,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._adb = adb
        self._calib = calib
        self._grid = grid
        self._options = options
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            painter = AutoPainter(self._adb, self._calib)
            painter.paint(
                self._grid,
                options=self._options,
                on_progress=lambda p: self.progress.emit(p),
                on_color=lambda c: self.color_changed.emit(c),
                should_stop=lambda: self._stop,
            )
            if not self._stop:
                self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001 - 传到 UI
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        self.setWindowTitle("ArkPaint · 拼豆自动绘图")
        self.resize(1180, 760)

        self.adb = AdbController()
        self.calib = load_calibration()
        self.palette: list[PaletteColor] = list(DEFAULT_PALETTE)
        self._apply_sampled_palette()
        self._worker: PaintWorker | None = None
        self._settings = load_json(SETTINGS_PATH, {})
        # 每次 ADB 连接后，首次「开始自动绘图」前必须完成一次校准
        self._needs_calib_before_paint = False
        self._source_image_path: str | None = None
        self._source_pixmap: QPixmap | None = None
        self._was_maximized = False

        self._build_ui()
        self._build_status()
        self._load_settings_to_ui()
        self._auto_detect_adb(silent=True)

        self.canvas.set_palette(self.palette)
        white = find_white_index(self.palette)
        self.canvas.set_grid(blank_grid(fill_index=white))
        self.palette_panel.set_palette(self.palette)
        self.palette_panel.set_active(white)
        self.canvas.set_active_color(white)

        undo_app = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_app.activated.connect(self.undo_canvas)
        self._update_pixel_thumb()

    def _apply_sampled_palette(self) -> None:
        if self.calib.sampled_rgbs:
            rgbs = [tuple(c) for c in self.calib.sampled_rgbs]  # type: ignore[misc]
            # 若采样色少于默认，用默认补齐编号靠后的色
            if len(rgbs) < len(DEFAULT_PALETTE):
                extra = [c.rgb for c in DEFAULT_PALETTE[len(rgbs) :]]
                rgbs = list(rgbs) + extra  # type: ignore[assignment]
            # 若校准声明更多色数，占位扩展
            while len(rgbs) < self.calib.total_colors:
                rgbs.append((200, 200, 200))
            self.palette = rebuild_palette(rgbs[: self.calib.total_colors])  # type: ignore[arg-type]

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        layout.addWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(280)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        # —— 导入图片 + 原图预览 ——
        lv.addWidget(self._section_title("导入图片"))
        import_row = QHBoxLayout()
        self.btn_import = QPushButton("选择图片…")
        self.btn_import.clicked.connect(self.import_image)
        self.btn_capture = QPushButton("截图")
        self.btn_capture.setToolTip("框选屏幕区域并转为 24×24 像素图")
        self.btn_capture.clicked.connect(self.capture_screen)
        import_row.addWidget(self.btn_import)
        import_row.addWidget(self.btn_capture)
        lv.addLayout(import_row)

        self.preview_label = ImagePreviewLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        self.preview_label.setMaximumHeight(160)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_label.setStyleSheet(_PREVIEW_EMPTY_STYLE)
        self.preview_label.setText("拖入图片到此处\n或点击上方按钮")
        self.preview_label.setScaledContents(False)
        self.preview_label.files_dropped.connect(self._on_files_dropped)
        lv.addWidget(self.preview_label)
        self.preview_name = QLabel("")
        self.preview_name.setWordWrap(True)
        self.preview_name.setStyleSheet("color:#9aa0a6; font-size:11px;")
        lv.addWidget(self.preview_name)

        lv.addSpacing(6)
        lv.addWidget(self._section_title("像素预览"))
        self.pixel_thumb = QLabel("尚无像素图")
        self.pixel_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pixel_thumb.setMinimumHeight(120)
        self.pixel_thumb.setMaximumHeight(160)
        self.pixel_thumb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pixel_thumb.setStyleSheet(_PREVIEW_EMPTY_STYLE)
        self.pixel_thumb.setToolTip("当前画板效果缩略图，随涂色实时更新")
        lv.addWidget(self.pixel_thumb)

        lv.addSpacing(8)
        # —— ADB 连接 ——
        lv.addWidget(self._section_title("连接设置"))
        self.host_edit = QLineEdit(DEFAULT_ADB_HOST)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_ADB_PORT)
        lv.addWidget(QLabel("主机"))
        lv.addWidget(self.host_edit)
        lv.addWidget(QLabel("ADB 端口"))
        lv.addWidget(self.port_spin)
        port_hint = QLabel(
            f"MuMu 多开端口：0号 {MUMU_ADB_BASE_PORT}，"
            f"之后每个 +{MUMU_ADB_PORT_STEP}"
            f"（1号 {MUMU_ADB_BASE_PORT + MUMU_ADB_PORT_STEP}，"
            f"2号 {MUMU_ADB_BASE_PORT + MUMU_ADB_PORT_STEP * 2}…）"
        )
        port_hint.setWordWrap(True)
        port_hint.setStyleSheet("color:#9aa0a6; font-size:11px;")
        lv.addWidget(port_hint)

        lv.addWidget(QLabel("adb.exe 路径"))
        adb_row = QHBoxLayout()
        self.adb_path_edit = QLineEdit()
        self.adb_path_edit.setPlaceholderText(r"~\Netease\MuMuPlayer-12.0\shell\adb.exe")
        btn_browse_adb = QPushButton("…")
        btn_browse_adb.setFixedWidth(32)
        btn_browse_adb.setToolTip("浏览选择 adb.exe")
        btn_browse_adb.clicked.connect(self.browse_adb)
        adb_row.addWidget(self.adb_path_edit, 1)
        adb_row.addWidget(btn_browse_adb)
        lv.addLayout(adb_row)

        adb_btn_row = QHBoxLayout()
        self.btn_detect_adb = QPushButton("自动检测")
        self.btn_detect_adb.clicked.connect(lambda: self._auto_detect_adb(silent=False))
        self.btn_connect = QPushButton("连接模拟器")
        self.btn_connect.clicked.connect(self.connect_adb)
        adb_btn_row.addWidget(self.btn_detect_adb)
        adb_btn_row.addWidget(self.btn_connect)
        lv.addLayout(adb_btn_row)

        self.device_label = QLabel("未连接")
        self.device_label.setWordWrap(True)
        self.device_label.setStyleSheet("color:#9aa0a6;")
        lv.addWidget(self.device_label)

        lv.addSpacing(8)
        lv.addWidget(self._section_title("绘制参数"))
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.3, 0.99)
        self.conf_spin.setSingleStep(0.01)
        self.conf_spin.setValue(DEFAULT_DETECT_CONFIDENCE)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(10, 500)
        self.delay_spin.setValue(DEFAULT_TAP_DELAY_MS)
        self.skip_white = QCheckBox("跳过白色格子（少点）")
        self.skip_white.setChecked(True)
        lv.addWidget(QLabel("识别置信度阈值"))
        lv.addWidget(self.conf_spin)
        lv.addWidget(QLabel("点击间隔 ms"))
        lv.addWidget(self.delay_spin)
        lv.addWidget(self.skip_white)

        lv.addSpacing(8)
        tip = QLabel(
            "使用说明：\n"
            "1. 导入/拖入/截图得到像素图\n"
            "2. 连接 MuMu ADB\n"
            "3. 打开游戏拼豆编辑页\n"
            "4. 右侧「校准并识别」后开始绘图"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#b0b4ba; font-size:12px;")
        lv.addWidget(tip)
        lv.addStretch(1)

        scroll.setWidget(left)
        return scroll

    def _build_center_panel(self) -> QWidget:
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(self._section_title("24×24 像素画布"), 1)

        tools = QWidget()
        tools_row = QHBoxLayout(tools)
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(10)

        self.btn_undo = QPushButton("撤回")
        self.btn_undo.setEnabled(False)
        self.btn_undo.setToolTip("撤回上一次涂色（Ctrl+Z）")
        self.btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_undo.setStyleSheet(self._tool_btn_style())
        self.btn_undo.clicked.connect(self.undo_canvas)
        tools_row.addWidget(self.btn_undo)

        self.btn_export = QPushButton("导出")
        self.btn_export.setToolTip("将当前像素图导出为 PNG 图片")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setStyleSheet(self._tool_btn_style())
        self.btn_export.clicked.connect(self.export_pixel_image)
        tools_row.addWidget(self.btn_export)

        num_lab = QLabel("编号")
        num_lab.setStyleSheet("color:#c8ccd2; font-size:12px;")
        tools_row.addWidget(num_lab)

        self.num_toggle = LightToggleSwitch(checked=True)
        self.num_toggle.toggled.connect(self._on_numbers_toggled)
        tools_row.addWidget(self.num_toggle)

        header.addWidget(tools, 0, Qt.AlignmentFlag.AlignRight)
        mv.addLayout(header)

        self.canvas = PixelCanvas()
        self.canvas.can_undo_changed.connect(self.btn_undo.setEnabled)
        self.canvas.grid_changed.connect(self._update_pixel_thumb)
        mv.addWidget(self.canvas, 1)
        help_row = QLabel("左键涂色 · 右键吸取 · 滚轮缩放 · 放大后移到边缘可平移 · Ctrl+Z 撤回")
        help_row.setStyleSheet("color:#9aa0a6;")
        mv.addWidget(help_row)
        return mid

    def _build_right_panel(self) -> QWidget:
        right = QWidget()
        right.setMinimumWidth(240)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 8)
        rv.setSpacing(8)

        self.palette_panel = PalettePanel()
        self.palette_panel.color_selected.connect(self.on_palette_selected)
        rv.addWidget(self.palette_panel, 1)

        # 进度区 + 校准识别 + 开始/停止
        progress_box = QWidget()
        pv = QVBoxLayout(progress_box)
        pv.setContentsMargins(8, 0, 8, 0)
        pv.setSpacing(6)

        self.paint_progress = QProgressBar()
        self.paint_progress.setRange(0, 1000)
        self.paint_progress.setValue(0)
        self.paint_progress.setTextVisible(True)
        self.paint_progress.setFormat("%p%")
        pv.addWidget(self.paint_progress)

        self.paint_detail = QLabel("就绪")
        self.paint_detail.setWordWrap(True)
        self.paint_detail.setStyleSheet("color:#b0b4ba; font-size:12px;")
        pv.addWidget(self.paint_detail)

        self.btn_prepare = QPushButton("校准并识别")
        self.btn_prepare.setToolTip("依次：校准颜料/画布 → 识别游戏画面")
        self.btn_prepare.setMinimumHeight(32)
        self.btn_prepare.clicked.connect(self.prepare_screen)
        pv.addWidget(self.btn_prepare)

        self.btn_paint = QPushButton("开始绘图")
        self.btn_paint.setMinimumHeight(36)
        self.btn_paint.setStyleSheet(
            "QPushButton { font-weight:700; background:#3d6ea8; color:#fff; border-radius:4px; }"
            "QPushButton:hover { background:#4a7fbc; }"
            "QPushButton:disabled { background:#555; color:#aaa; }"
        )
        self.btn_paint.clicked.connect(self.toggle_paint)
        pv.addWidget(self.btn_paint)

        rv.addWidget(progress_box, 0)
        return right

    def _section_title(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("font-size:14px; font-weight:700; color:#f2f2f2; padding:4px 0;")
        return lab

    @staticmethod
    def _tool_btn_style() -> str:
        return (
            "QPushButton {"
            "  background:#e8eaed; color:#3a3f48; border:1px solid #c5c9d0;"
            "  border-radius:4px; padding:4px 12px; font-size:12px;"
            "}"
            "QPushButton:hover { background:#f2f4f7; }"
            "QPushButton:disabled { color:#9aa0a6; background:#dfe3e8; }"
        )

    def _build_status(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.progress_label = QLabel("就绪")
        sb.addWidget(self.progress_label, 1)

    def _load_settings_to_ui(self) -> None:
        self.host_edit.setText(str(self._settings.get("adb_host", DEFAULT_ADB_HOST)))
        self.port_spin.setValue(int(self._settings.get("adb_port", DEFAULT_ADB_PORT)))
        self.conf_spin.setValue(float(self._settings.get("confidence", DEFAULT_DETECT_CONFIDENCE)))
        self.delay_spin.setValue(int(self._settings.get("tap_delay", DEFAULT_TAP_DELAY_MS)))
        saved_adb = str(self._settings.get("adb_path", "") or "")
        if saved_adb:
            self.adb_path_edit.setText(saved_adb)

    def _save_settings(self) -> None:
        save_json(
            SETTINGS_PATH,
            {
                "adb_host": self.host_edit.text().strip(),
                "adb_port": self.port_spin.value(),
                "adb_path": self.adb_path_edit.text().strip(),
                "confidence": self.conf_spin.value(),
                "tap_delay": self.delay_spin.value(),
            },
        )

    def on_palette_selected(self, index: int) -> None:
        self.canvas.set_active_color(index)
        self.palette_panel.set_active(index)
        self.progress_label.setText(f"当前颜色 #{index}")

    def _on_numbers_toggled(self, show: bool) -> None:
        self.canvas.set_show_numbers(show)
        self.palette_panel.set_show_numbers(show)

    def undo_canvas(self) -> None:
        if self.canvas.undo():
            self.progress_label.setText("已撤回一步")

    def export_pixel_image(self) -> None:
        """导出当前画板为放大后的 PNG 像素图（无编号）。"""
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出像素图",
            str(Path.home() / "arkpaint_pixel.png"),
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if not suffix:
            # 按过滤器补后缀
            path = path + (".jpg" if "JPEG" in selected or "jpg" in selected.lower() else ".png")
            suffix = Path(path).suffix.lower()

        # 每格 32 像素，24×24 → 768×768，清晰且仍是整格像素
        img = self.canvas.to_qimage(scale=32)
        pix = QPixmap.fromImage(img)
        fmt = "JPG" if suffix in {".jpg", ".jpeg"} else "PNG"
        if not pix.save(path, fmt):
            QMessageBox.warning(self, "导出失败", "无法写入文件，请检查路径与权限。")
            return
        self.progress_label.setText(f"已导出：{Path(path).name}")
        QMessageBox.information(self, "导出成功", f"已保存到：\n{path}")

    def _update_pixel_thumb(self) -> None:
        """左侧：当前像素图画板缩略图。"""
        if not hasattr(self, "pixel_thumb"):
            return
        img = self.canvas.to_qimage(scale=6)
        pix = QPixmap.fromImage(img)
        target_w = max(100, self.pixel_thumb.width() - 8)
        target_h = self.pixel_thumb.maximumHeight() - 8
        scaled = pix.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.pixel_thumb.setStyleSheet(_PREVIEW_FILLED_STYLE)
        self.pixel_thumb.setText("")
        self.pixel_thumb.setPixmap(scaled)

    def _on_files_dropped(self, paths: list) -> None:
        if paths:
            self._load_image_path(str(paths[0]))

    def _refresh_preview_display(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setStyleSheet(_PREVIEW_EMPTY_STYLE)
            self.preview_label.setText("拖入图片到此处\n或点击上方按钮")
            return
        target_w = max(120, self.preview_label.width() - 8)
        target_h = self.preview_label.maximumHeight() - 8
        scaled = self._source_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setStyleSheet(_PREVIEW_FILLED_STYLE)
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)

    def _set_preview_from_path(self, path: str) -> None:
        self._source_image_path = path
        pix = QPixmap(path)
        self._source_pixmap = None if pix.isNull() else pix
        if pix.isNull():
            self.preview_name.setText("")
            self._refresh_preview_display()
            self.preview_label.setText("预览失败")
            return
        self.preview_name.setText(Path(path).name)
        self._refresh_preview_display()

    def _apply_grid_from_path(self, path: str) -> None:
        grid, _preview = image_to_grid(path, self.palette)
        self.canvas.set_grid(grid)
        self._set_preview_from_path(path)

    def _load_image_path(self, path: str) -> None:
        try:
            self._apply_grid_from_path(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.progress_label.setText(f"已导入并转为 24×24：{Path(path).name}")

    def import_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)",
        )
        if path:
            self._load_image_path(path)

    def capture_screen(self) -> None:
        """隐藏本窗口后，让用户框选屏幕区域再转为像素图。"""
        self._was_maximized = self.isMaximized()
        self.hide()
        QApplication.processEvents()
        # 稍等窗口隐藏，避免框选层闪到本软件
        QTimer.singleShot(200, self._start_region_capture)

    def _start_region_capture(self) -> None:
        from arkpaint.ui.region_capture import start_region_capture

        try:
            self._capture_overlay = start_region_capture(
                on_captured=self._on_region_captured,
                on_cancelled=self._on_region_capture_cancelled,
            )
        except Exception as exc:  # noqa: BLE001
            self._restore_after_capture()
            QMessageBox.warning(self, "截图失败", str(exc))

    def _restore_after_capture(self) -> None:
        if self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_region_captured(self, pix: QPixmap) -> None:
        try:
            if pix.isNull():
                raise RuntimeError("截图为空")
            ensure_dirs()
            out = DATA_DIR / "_last_capture.png"
            if not pix.save(str(out), "PNG"):
                raise RuntimeError("截图保存失败")
            self._apply_grid_from_path(str(out))
            self.preview_name.setText("框选截图")
            self.progress_label.setText("已框选截图并转为 24×24")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "截图失败", str(exc))
        finally:
            self._restore_after_capture()

    def _on_region_capture_cancelled(self) -> None:
        self.progress_label.setText("已取消截图")
        self._restore_after_capture()

    def browse_adb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 adb.exe",
            str(Path.home()),
            "Executable (adb.exe);;All (*.*)",
        )
        if path:
            self.adb_path_edit.setText(path)
            self._save_settings()

    def _auto_detect_adb(self, silent: bool = True) -> str | None:
        preferred = self.adb_path_edit.text().strip() or None
        found = find_adb(preferred)
        # find_adb 在找不到时仍可能返回 "adb"
        resolved = Path(found)
        ok = resolved.exists() or found == "adb"
        if resolved.exists():
            self.adb_path_edit.setText(str(resolved))
            self.adb.adb_path = str(resolved)
            if not silent:
                self.progress_label.setText(f"已检测到 ADB：{resolved}")
                QMessageBox.information(self, "ADB", f"已找到：\n{resolved}")
            self._save_settings()
            return str(resolved)
        # PATH 中的 adb
        if found == "adb":
            self.adb.adb_path = "adb"
            if not silent:
                QMessageBox.information(self, "ADB", "已在 PATH 中找到 adb，将直接使用命令名 `adb`。")
            return "adb"
        if not silent:
            QMessageBox.warning(
                self,
                "ADB",
                "未找到 adb.exe。\n"
                "可手动选择，常见路径：\n"
                r"%USERPROFILE%\Netease\MuMuPlayer-12.0\shell\adb.exe",
            )
        return None if not ok else found

    def _candidate_ports(self) -> list[int]:
        """用户端口优先，再扫描 MuMu 多开端口。"""
        preferred = self.port_spin.value()
        ports: list[int] = [preferred]
        for i in range(MUMU_ADB_SCAN_INSTANCES):
            p = MUMU_ADB_BASE_PORT + i * MUMU_ADB_PORT_STEP
            if p not in ports:
                ports.append(p)
        # 旧版 MuMu 常见端口
        for legacy in (7555, 5555):
            if legacy not in ports:
                ports.append(legacy)
        return ports

    def connect_adb(self) -> None:
        host = self.host_edit.text().strip() or DEFAULT_ADB_HOST
        adb_path = self._auto_detect_adb(silent=True) or self.adb_path_edit.text().strip() or find_adb()
        self.adb.adb_path = adb_path

        self.device_label.setText("正在连接…")
        self.progress_label.setText("正在尝试连接模拟器…")

        last_err = ""
        for port in self._candidate_ports():
            try:
                msg = self.adb.connect(host, port)
                devices = self.adb.list_devices()
                target = f"{host}:{port}"
                online = [d for d in devices if d.state == "device"]
                matched = next((d for d in online if d.serial == target), None)
                chosen = matched or (online[0] if online else None)
                if not chosen:
                    last_err = msg or f"{target} 无在线设备"
                    continue

                self.adb.use_device(chosen.serial)
                # 从 serial 解析端口
                connected_port = port
                if ":" in chosen.serial:
                    try:
                        connected_port = int(chosen.serial.rsplit(":", 1)[-1])
                    except ValueError:
                        connected_port = port
                self.port_spin.setValue(connected_port)
                label = mumu_instance_label(connected_port)
                if label:
                    status = f"已连接：{label} 模拟器"
                else:
                    status = f"已连接：{chosen.serial}"
                self.device_label.setText(f"{status}\nADB：{self.adb.adb_path}")
                self._needs_calib_before_paint = True
                tip = f"连接成功 · {label or chosen.serial} · 打开拼豆页后点开始（将强制校准）"
                self.progress_label.setText(tip)
                self._save_settings()
                QMessageBox.information(
                    self,
                    "连接成功",
                    f"{status}\n\n请打开游戏拼豆编辑页后再开始绘图。",
                )
                return
            except AdbError as exc:
                last_err = str(exc)
                continue

        self.device_label.setText("连接失败")
        QMessageBox.warning(
            self,
            "ADB",
            "未能连接模拟器。已尝试用户端口及常见 MuMu 多开端口。\n\n"
            f"最后错误：{last_err or '未知'}",
        )

    def open_calibrate(self) -> bool:
        """打开校准对话框。成功保存返回 True。"""
        if not self.adb.is_ready():
            QMessageBox.information(self, "提示", "请先连接 ADB")
            return False
        dlg = CalibrateDialog(self.adb, self.calib, self)
        if dlg.exec():
            self.calib = dlg.result_calibration()
            self._apply_sampled_palette()
            self.palette_panel.set_palette(self.palette)
            self.canvas.set_palette(self.palette)
            self._update_pixel_thumb()
            self._needs_calib_before_paint = False
            self.progress_label.setText("校准已更新")
            return True
        return False

    def detect_screen(self, *, quiet: bool = False) -> bool:
        """识别拼豆画面。成功返回 True。"""
        if not self.adb.is_ready():
            if not quiet:
                QMessageBox.information(self, "提示", "请先连接 ADB")
            return False
        try:
            from arkpaint.core.detector import detect_pindou_screen

            shot = self.adb.screencap()
            result = detect_pindou_screen(shot, min_confidence=self.conf_spin.value())
        except AdbError as exc:
            if not quiet:
                QMessageBox.warning(self, "识别失败", str(exc))
            return False
        detail = f"置信度：{result.confidence:.3f}\n画布：{result.canvas_rect}"
        if quiet and result.ok:
            self.progress_label.setText(f"识别通过 · {result.message}")
            self.paint_detail.setText(f"识别通过 · 置信度 {result.confidence:.3f}")
            return True
        icon = QMessageBox.Icon.Information if result.ok else QMessageBox.Icon.Warning
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle("画面识别")
        box.setText(result.message)
        box.setInformativeText(detail)
        box.exec()
        return bool(result.ok)

    def prepare_screen(self) -> bool:
        """依次：校准颜料/画布 → 识别画面。"""
        if not self.adb.is_ready():
            QMessageBox.information(self, "提示", "请先连接 ADB")
            return False
        self.progress_label.setText("步骤 1/2：校准颜料/画布…")
        if not self.open_calibrate():
            self.progress_label.setText("已取消校准")
            return False
        self.progress_label.setText("步骤 2/2：识别画面…")
        ok = self.detect_screen(quiet=False)
        if ok:
            self.progress_label.setText("校准并识别完成，可以开始绘图")
            self.paint_detail.setText("校准并识别完成")
        return ok

    def toggle_paint(self) -> None:
        if self._worker and self._worker.isRunning():
            self.stop_paint()
        else:
            self.start_paint()

    def start_paint(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        if not self.adb.is_ready():
            QMessageBox.information(self, "提示", "请先连接 ADB")
            return

        # 每次 ADB 连接后的首次启动：强制校准+识别
        if self._needs_calib_before_paint:
            QMessageBox.information(
                self,
                "需要校准",
                "本次连接后首次绘图，请先完成画布与颜料校准，并确认识别通过。\n"
                "请确认游戏已打开拼豆编辑页，然后按提示操作。",
            )
            if not self.prepare_screen():
                self.progress_label.setText("已取消准备，未开始绘制")
                return

        if not self.calib.is_palette_ready() or not self.calib.is_canvas_ready():
            QMessageBox.information(self, "提示", "请先点击「校准并识别」")
            return

        options = PaintOptions(
            tap_delay_ms=self.delay_spin.value(),
            min_confidence=self.conf_spin.value(),
            skip_color_index=find_white_index(self.palette) if self.skip_white.isChecked() else None,
            skip_empty=self.skip_white.isChecked(),
        )
        self._save_settings()
        self._worker = PaintWorker(self.adb, self.calib, self.canvas.grid(), options, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.color_changed.connect(self._on_drawing_color)
        self._worker.finished_ok.connect(self._on_paint_done)
        self._worker.failed.connect(self._on_paint_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._set_paint_running(True)
        self.paint_progress.setValue(0)
        self.paint_detail.setText("开始绘制…")
        self.progress_label.setText("开始绘制…")
        self._worker.start()

    def stop_paint(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.paint_detail.setText("正在停止…")
            self.progress_label.setText("正在停止…")

    def _set_paint_running(self, running: bool) -> None:
        if running:
            self.btn_paint.setText("停止")
            self.btn_paint.setStyleSheet(
                "QPushButton { font-weight:700; background:#a85a3d; color:#fff; border-radius:4px; }"
                "QPushButton:hover { background:#bc6a4a; }"
            )
        else:
            self.btn_paint.setText("开始绘图")
            self.btn_paint.setStyleSheet(
                "QPushButton { font-weight:700; background:#3d6ea8; color:#fff; border-radius:4px; }"
                "QPushButton:hover { background:#4a7fbc; }"
                "QPushButton:disabled { background:#555; color:#aaa; }"
            )

    def _on_progress(self, info: object) -> None:
        if not isinstance(info, PaintProgress):
            return
        self.paint_progress.setValue(int(round(info.fraction * 1000)))
        parts: list[str] = [info.message]
        if info.color_index is not None and info.color_total:
            parts.append(f"色块 #{info.color_index}（{info.color_ord}/{info.color_total}）")
        if info.cells_total:
            parts.append(f"已填 {info.cells_done}/{info.cells_total}")
        if info.cells_in_color_total:
            parts.append(f"本色 {info.cells_in_color_done}/{info.cells_in_color_total}")
        detail = " · ".join(parts)
        self.paint_detail.setText(detail)
        self.progress_label.setText(detail)

    def _on_drawing_color(self, index: int) -> None:
        self.palette_panel.set_drawing_color(index)
        self.palette_panel.set_active(index)
        self.canvas.set_active_color(index)

    def _on_worker_finished(self) -> None:
        """线程结束时统一恢复开始/停止按钮（含用户中途停止）。"""
        self._set_paint_running(False)
        self.palette_panel.set_drawing_color(None)

    def _on_paint_done(self) -> None:
        self.paint_progress.setValue(1000)
        self.paint_detail.setText("绘制完成")
        self.progress_label.setText("绘制完成")
        QMessageBox.information(self, "完成", "自动绘图已结束")

    def _on_paint_failed(self, message: str) -> None:
        self.paint_detail.setText("绘制失败")
        self.progress_label.setText("绘制失败")
        QMessageBox.warning(self, "绘制失败", message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_preview_display()
        self._update_pixel_thumb()

    def closeEvent(self, event) -> None:
        self.stop_paint()
        if self._worker and self._worker.isRunning():
            self._worker.wait(1500)
        self._save_settings()
        super().closeEvent(event)
