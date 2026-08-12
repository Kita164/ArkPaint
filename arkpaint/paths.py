"""路径与资源定位（开发态 / PyInstaller 打包态）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_base_dir() -> Path:
    """可写根目录：exe 旁（打包）或项目根（开发）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """只读资源目录：_MEIPASS（打包）或项目根（开发）。"""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def default_adb_path() -> Path:
    """默认 adb：项目根 / exe 旁的 tools/adb.exe。"""
    return app_base_dir() / "tools" / "adb.exe"


def bundled_adb_candidates() -> list[Path]:
    """本程序自带的 adb 候选（开发态项目目录 / 打包 exe 旁 / _MEIPASS）。"""
    base = app_base_dir()
    res = resource_dir()
    seen: set[Path] = set()
    out: list[Path] = []
    for c in (
        base / "tools" / "adb.exe",
        base / "adb.exe",
        base / "platform-tools" / "adb.exe",
        res / "tools" / "adb.exe",
        res / "adb.exe",
        res / "platform-tools" / "adb.exe",
    ):
        key = c.resolve() if c.exists() else c
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def default_mumu_adb_candidates() -> list[Path]:
    """MuMu 12 常见 adb 安装路径（自带 adb 找不到时的后备）。"""
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    rel = Path("Netease") / "MuMuPlayer-12.0" / "shell" / "adb.exe"
    return [
        home / rel,
        Path(local) / rel if local else Path(),
        Path(program_files) / rel,
        Path(program_files_x86) / rel,
        Path(r"D:\Program Files") / rel,
        Path(r"D:\Program Files (x86)") / rel,
    ]


def find_adb(preferred: str | None = None) -> str:
    """按优先级查找 adb：指定路径 → 环境变量 → 本程序 tools → MuMu → PATH。"""
    import shutil

    if preferred:
        p = Path(preferred).expanduser()
        if p.exists():
            return str(p.resolve())

    env = os.environ.get("ARKPAINT_ADB") or os.environ.get("ADB_PATH")
    if env and Path(env).exists():
        return str(Path(env).resolve())

    candidates: list[Path] = []
    candidates.extend(bundled_adb_candidates())
    candidates.extend(c for c in default_mumu_adb_candidates() if str(c))
    for c in candidates:
        if c.exists():
            return str(c.resolve())

    which = shutil.which("adb")
    if which:
        return which
    return "adb"


def mumu_instance_label(port: int) -> str | None:
    """将端口映射为 MuMu 多开实例说明，如「0号 16384」。"""
    idx = mumu_instance_from_port(port)
    if idx is None:
        return None
    return f"{idx}号 {port}"


def mumu_instance_from_port(port: int) -> int | None:
    """MuMu 12 多开端口 → 实例编号（0 号 16384，之后 +32）。"""
    from arkpaint.config import MUMU_ADB_BASE_PORT, MUMU_ADB_PORT_STEP

    if port < MUMU_ADB_BASE_PORT:
        return None
    delta = port - MUMU_ADB_BASE_PORT
    if delta % MUMU_ADB_PORT_STEP != 0:
        return None
    return delta // MUMU_ADB_PORT_STEP


def find_mumu_install_dir() -> Path | None:
    """从注册表或常见路径定位 MuMu 12 安装根目录（含 shell/）。"""
    if os.name != "nt":
        return None

    names = (
        "MuMuPlayer-12.0",
        "MuMuPlayer",
        "MuMuPlayerGlobal-12.0",
        "MuMuPlayerGlobal",
        "YXArkNights-12.0",
    )
    try:
        import winreg

        for name in names:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{name}",
                )
            except OSError:
                continue
            try:
                icon, _ = winreg.QueryValueEx(key, "DisplayIcon")
            finally:
                winreg.CloseKey(key)
            root = Path(str(icon).strip('"')).resolve().parent
            if (root / "shell").is_dir() or (root / "nx_device").is_dir():
                return root
    except Exception:
        pass

    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    rel = Path("Netease") / "MuMuPlayer-12.0"
    for base in (home, Path(local) if local else None):
        if base is None:
            continue
        candidate = base / rel
        if (candidate / "shell").is_dir():
            return candidate.resolve()
    return None
