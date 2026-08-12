"""ArkPaint 像素风主题：配色与全局样式表。

配色取自 assets/logo/ArkPaint.png（青绿格纹、品牌蓝、亮黄、炭灰）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from arkpaint.config import DATA_DIR, LOGO_PATH, ensure_dirs

# —— 品牌色 ——
TEAL = "#5EC8C0"
TEAL_LIGHT = "#E0F7F7"
BLUE = "#2A82F4"
BLUE_HOVER = "#3D94FF"
BLUE_DARK = "#1E6AD0"
YELLOW = "#FFD700"
YELLOW_DIM = "#E6C200"
CHARCOAL = "#3C3C3C"
CHARCOAL_DEEP = "#2A2A2A"
PANEL = "#323232"
BORDER = "#1A1A1A"
TEXT = "#F2F2F2"
TEXT_MUTED = "#A8B0B8"
DANGER = "#C45A3A"
DANGER_HOVER = "#D46A4A"
PREVIEW_BG = "#E8F4F4"

# 像素感字体栈（有像素字体则优先，否则等宽）
FONT_UI = '"Cascadia Mono", "Consolas", "Courier New", monospace'
FONT_TITLE = '"Press Start 2P", "Cascadia Mono", "Consolas", monospace'

APP_STYLESHEET = ""


def logo_path() -> Path:
    return LOGO_PATH


def app_icon() -> QIcon:
    path = logo_path()
    if path.is_file():
        return QIcon(str(path))
    return QIcon()


def _qss_url(path: Path) -> str:
    return path.resolve().as_posix()


def _ensure_checkbox_icons() -> tuple[Path, Path]:
    """生成带勾的复选框图标（写入可写 data 目录）。"""
    ensure_dirs()
    ui_dir = DATA_DIR / "_ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    off_path = ui_dir / "checkbox_off.png"
    on_path = ui_dir / "checkbox_on.png"
    size = 16

    def _base(checked: bool) -> QPixmap:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        bg = QColor(0x2A, 0x82, 0xF4) if checked else QColor(0x3C, 0x3C, 0x3C)
        p.fillRect(0, 0, size, size, bg)
        p.setPen(QPen(QColor(0x1A, 0x1A, 0x1A), 2))
        p.drawRect(1, 1, size - 3, size - 3)
        if checked:
            p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2))
            # 打勾：左下 → 中下 → 右上
            p.drawLine(3, 8, 6, 12)
            p.drawLine(6, 12, 12, 4)
        p.end()
        return pix

    _base(False).save(str(off_path), "PNG")
    _base(True).save(str(on_path), "PNG")
    return off_path, on_path


def build_stylesheet() -> str:
    off_path, on_path = _ensure_checkbox_icons()
    off_url = _qss_url(off_path)
    on_url = _qss_url(on_path)
    return f"""
/* —— 全局 —— */
QWidget {{
    background-color: {CHARCOAL_DEEP};
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 12px;
}}
QMainWindow, QDialog {{
    background-color: {CHARCOAL_DEEP};
}}
QToolTip {{
    background-color: {CHARCOAL};
    color: {TEXT};
    border: 2px solid {BLUE};
    padding: 4px;
}}

/* —— 分区标题 —— */
QLabel#sectionTitle {{
    font-size: 13px;
    font-weight: 700;
    color: {TEAL};
    padding: 6px 0 2px 0;
    border-bottom: 2px solid {BLUE};
    margin-bottom: 2px;
}}
QLabel#brandTitle {{
    font-family: {FONT_TITLE};
    font-size: 14px;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 1px;
}}
QLabel#muted {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QLabel#hint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#numberLabel {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 700;
    padding: 0 2px;
}}

/* —— 按钮：直角厚边 —— */
QPushButton {{
    background-color: {CHARCOAL};
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0;
    padding: 5px 10px;
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: {PANEL};
    border-color: {BLUE};
    color: {TEAL_LIGHT};
}}
QPushButton:pressed {{
    background-color: {BLUE_DARK};
    border-color: {YELLOW};
}}
QPushButton:disabled {{
    background-color: #3a3a3a;
    color: #777;
    border-color: #2a2a2a;
}}
QPushButton#primaryButton {{
    background-color: {BLUE};
    color: #ffffff;
    border: 2px solid {BORDER};
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{
    background-color: {BLUE_HOVER};
    border-color: {YELLOW};
}}
QPushButton#primaryButton:disabled {{
    background-color: #555;
    color: #aaa;
}}
QPushButton#dangerButton {{
    background-color: {DANGER};
    color: #ffffff;
    border: 2px solid {BORDER};
    font-weight: 700;
}}
QPushButton#dangerButton:hover {{
    background-color: {DANGER_HOVER};
    border-color: {YELLOW};
}}
QPushButton#toolButton {{
    background-color: {TEAL_LIGHT};
    color: {CHARCOAL};
    border: 2px solid {CHARCOAL};
    padding: 4px 12px;
}}
QPushButton#toolButton:hover {{
    background-color: #ffffff;
    border-color: {BLUE};
}}
QPushButton#toolButton:disabled {{
    color: #9aa0a6;
    background-color: #c8d0d0;
}}

/* —— 输入 —— */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {CHARCOAL};
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0;
    padding: 4px 6px;
    selection-background-color: {BLUE};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {TEAL};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {CHARCOAL};
    color: {TEXT};
    border: 2px solid {BORDER};
    selection-background-color: {BLUE};
    selection-color: #ffffff;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {PANEL};
    border: 1px solid {BORDER};
    width: 16px;
}}

/* —— 复选框（打勾框） —— */
QCheckBox {{
    spacing: 8px;
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: none;
}}
QCheckBox::indicator:unchecked {{
    image: url("{off_url}");
}}
QCheckBox::indicator:checked {{
    image: url("{on_url}");
}}

/* —— 进度条 —— */
QProgressBar {{
    background-color: {CHARCOAL};
    border: 2px solid {BORDER};
    border-radius: 0;
    text-align: center;
    color: {TEXT};
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {BLUE};
    border: none;
}}

/* —— 滚动 / 分割 —— */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: {CHARCOAL_DEEP};
    width: 12px;
    margin: 0;
    border: 2px solid {BORDER};
}}
QScrollBar::handle:vertical {{
    background: {BLUE};
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {CHARCOAL_DEEP};
    height: 12px;
    border: 2px solid {BORDER};
}}
QScrollBar::handle:horizontal {{
    background: {BLUE};
    min-width: 24px;
}}
QSplitter::handle {{
    background: {BORDER};
    width: 3px;
}}

/* —— 状态栏 —— */
QStatusBar {{
    background: {CHARCOAL};
    border-top: 2px solid {BLUE};
    color: {TEXT_MUTED};
}}
QStatusBar QLabel {{
    color: {TEXT_MUTED};
}}

/* —— 预览框（空 / 有图） —— */
QLabel#previewEmpty {{
    background: {PREVIEW_BG};
    border: 2px dashed {TEAL};
    border-radius: 0;
    color: #5a6a6a;
}}
QLabel#previewFilled {{
    background: {PREVIEW_BG};
    border: 2px solid {CHARCOAL};
    border-radius: 0;
    color: #5a6a6a;
}}
"""


def apply_app_theme(app: QApplication) -> None:
    """设置应用图标、默认字体与全局 QSS。"""
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    font = QFont("Consolas", 10)
    if not font.exactMatch():
        font = QFont("Cascadia Mono", 10)
    app.setFont(font)
    global APP_STYLESHEET
    APP_STYLESHEET = build_stylesheet()
    app.setStyleSheet(APP_STYLESHEET)
