"""ADB 封装：连接 MuMu、截图、点击、滑动。"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class AdbError(RuntimeError):
    pass


@dataclass
class AdbDevice:
    serial: str
    state: str


class AdbController:
    def __init__(self, adb_path: str | None = None) -> None:
        from arkpaint.paths import find_adb

        self.adb_path = adb_path or find_adb()
        self.serial: str | None = None

    def _run(self, *args: str, timeout: float = 30.0) -> str:
        cmd = [self.adb_path, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except FileNotFoundError as exc:
            raise AdbError("未找到 adb，请安装 Android Platform Tools 并加入 PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB 命令超时: {' '.join(cmd)}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise AdbError(err or f"ADB 失败: {' '.join(cmd)}")
        return (proc.stdout or "").strip()

    def version(self) -> str:
        return self._run("version")

    def connect(self, host: str, port: int) -> str:
        target = f"{host}:{port}"
        out = self._run("connect", target)
        # 连接成功后默认使用该设备
        devices = self.list_devices()
        for d in devices:
            if d.serial == target and d.state == "device":
                self.serial = target
                break
        else:
            # 有时 connect 返回已连接，但 devices 需再查
            online = [d for d in devices if d.state == "device"]
            if online:
                self.serial = online[0].serial
            else:
                raise AdbError(f"连接失败: {out}")
        return out

    def list_devices(self) -> list[AdbDevice]:
        out = self._run("devices")
        result: list[AdbDevice] = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\s+", line)
            if len(parts) >= 2:
                result.append(AdbDevice(serial=parts[0], state=parts[1]))
        return result

    def use_device(self, serial: str) -> None:
        self.serial = serial

    def _device_args(self) -> list[str]:
        if self.serial:
            return ["-s", self.serial]
        return []

    def tap(self, x: int, y: int) -> None:
        self._run(*self._device_args(), "shell", "input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run(
            *self._device_args(),
            "shell",
            "input",
            "swipe",
            str(int(x1)),
            str(int(y1)),
            str(int(x2)),
            str(int(y2)),
            str(int(duration_ms)),
        )

    def screencap(self) -> np.ndarray:
        """返回 BGR numpy 图像（OpenCV 格式）。"""
        with tempfile.TemporaryDirectory() as tmp:
            remote = "/sdcard/arkpaint_cap.png"
            local = Path(tmp) / "cap.png"
            self._run(*self._device_args(), "shell", "screencap", "-p", remote)
            self._run(*self._device_args(), "pull", remote, str(local))
            try:
                self._run(*self._device_args(), "shell", "rm", remote)
            except AdbError:
                pass
            data = local.read_bytes()
        return _decode_png(data)

    def is_ready(self) -> bool:
        """是否已选定可用设备（必须绑定 serial，避免多设备时裸 adb 报错）。"""
        try:
            devices = self.list_devices()
        except AdbError:
            return False
        online = [d for d in devices if d.state == "device"]
        if not online:
            return False
        if self.serial:
            return any(d.serial == self.serial for d in online)
        # 仅一台设备时自动绑定，便于「开始绘图」直接用
        if len(online) == 1:
            self.serial = online[0].serial
            return True
        return False

    def ensure_serial(self) -> bool:
        """若尚未选定设备：唯一在线则绑定；多设备则返回 False（需显式 connect）。"""
        if self.is_ready():
            return True
        try:
            devices = self.list_devices()
        except AdbError:
            return False
        online = [d for d in devices if d.state == "device"]
        if len(online) == 1:
            self.serial = online[0].serial
            return True
        return False


def _decode_png(data: bytes) -> np.ndarray:
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise AdbError("截图解码失败")
    return img
