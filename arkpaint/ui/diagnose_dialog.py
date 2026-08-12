"""识别诊断结果对话框。"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from arkpaint.core.diagnose import DiagnoseReport


def show_diagnose_report(
    parent: QWidget | None,
    report: DiagnoseReport,
    *,
    extra: str | None = None,
) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("识别诊断")
    box.setIcon(QMessageBox.Icon.Information if report.ok else QMessageBox.Icon.Warning)
    header = report.summary
    if extra:
        header = f"{extra}\n\n{header}"
    box.setText(header)
    box.setInformativeText("可打开调试文件夹查看截图、白块蒙版与标注图。")
    box.setDetailedText(report.text())
    open_btn = box.addButton("打开调试文件夹", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
    if box.clickedButton() is open_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(report.debug_dir)))
