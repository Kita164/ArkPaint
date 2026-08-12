"""ArkPaint - 拼豆自动绘图工具入口。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from arkpaint.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ArkPaint")
    app.setOrganizationName("ArkPaint")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
