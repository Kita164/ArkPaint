"""全局配置与路径。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arkpaint.paths import app_base_dir, resource_dir

GRID_SIZE = 24
PALETTE_COLUMNS = 4

# MuMu 常见 ADB 端口（可在 UI 中修改）
# MuMu 12 多开：0 号 16384，之后每个实例 +32（1→16416，2→16448 …）
DEFAULT_ADB_HOST = "127.0.0.1"
DEFAULT_ADB_PORT = 16384  # MuMu 12 默认；旧版常见 7555
MUMU_ADB_BASE_PORT = 16384
MUMU_ADB_PORT_STEP = 32
MUMU_ADB_SCAN_INSTANCES = 8  # 自动连接时尝试 0..(N-1) 号

# 画面识别最低置信度
DEFAULT_DETECT_CONFIDENCE = 0.72

# 绘制间隔（毫秒），过快可能导致游戏丢点
DEFAULT_TAP_DELAY_MS = 45
DEFAULT_COLOR_SWITCH_DELAY_MS = 180

ROOT_DIR = app_base_dir()
ASSETS_DIR = resource_dir() / "assets"
# 校准/设置写到 exe 旁，避免打包只读目录
DATA_DIR = ROOT_DIR / "data"
SCRATCH_DIR = DATA_DIR / "scratch"
CALIBRATION_PATH = DATA_DIR / "calibration.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
DEBUG_DIR = DATA_DIR / "debug"
DETECT_TEST_DIR = DATA_DIR / "detect_test"
REFERENCE_IMAGE = ASSETS_DIR / "reference.png"
LOGO_PATH = ASSETS_DIR / "logo" / "ArkPaint.png"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    # 开发态可写 assets；打包态 assets 在只读资源里
    writable_assets = ROOT_DIR / "assets"
    writable_assets.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    ensure_dirs()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
