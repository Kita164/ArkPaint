"""识别诊断结果对话框：展示 verify_grid 标注效果。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from arkpaint.core.diagnose import DiagnoseReport
from arkpaint.ui.theme import app_icon


def show_diagnose_report(
    parent: QWidget | None,
    report: DiagnoseReport,
    *,
    extra: str | None = None,
) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("识别诊断")
    dlg.setWindowIcon(app_icon())
    dlg.resize(980, 720)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(14, 14, 14, 14)
    root.setSpacing(10)

    header = report.summary
    if extra:
        header = f"{extra}\n\n{header}"
    title = QLabel(header)
    title.setWordWrap(True)
    title.setStyleSheet(
        f"color: {'#7ddea8' if report.ok else '#f0a0a0'}; font-size: 14px; font-weight: 600;"
    )
    root.addWidget(title)

    hint = QLabel("下图为识别效果（绿框=画布 24×24 网格，红点=色号 1–4，橙框=颜料 ROI）")
    hint.setObjectName("hint")
    hint.setWordWrap(True)
    root.addWidget(hint)

    image_path = _best_preview_path(report)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
    img_label = QLabel()
    img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if image_path and image_path.is_file():
        pix = QPixmap(str(image_path))
        if not pix.isNull():
            # 先按窗口宽度缩放，完整图仍可滚动查看
            scaled = pix.scaled(
                920,
                560,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            img_label.setPixmap(scaled)
            img_label.setToolTip(str(image_path))
        else:
            img_label.setText("无法加载标注图")
    else:
        img_label.setText("暂无标注图（连接或截图失败时不会生成）")
    scroll.setWidget(img_label)
    root.addWidget(scroll, 1)

    detail = QTextEdit()
    detail.setReadOnly(True)
    detail.setMaximumHeight(140)
    detail.setPlainText(report.text())
    root.addWidget(detail)

    row = QHBoxLayout()
    row.addStretch(1)
    btn_folder = QPushButton("打开调试文件夹")
    btn_folder.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(report.debug_dir)))
    )
    btn_ok = QPushButton("确定")
    btn_ok.setObjectName("primaryButton")
    btn_ok.setMinimumWidth(100)
    btn_ok.clicked.connect(dlg.accept)
    row.addWidget(btn_folder)
    row.addWidget(btn_ok)
    root.addLayout(row)

    dlg.exec()


def _best_preview_path(report: DiagnoseReport) -> Path | None:
    for path in (report.verify_grid_path, report.overlay_path, report.screenshot_path):
        if path is not None and path.is_file():
            return path
    return None
