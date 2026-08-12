"""ADB 封装：连接 MuMu、截图、点击、滑动。

截图策略参考 MaaFramework：按速度依次尝试 MuMu IPC → exec-out PNG → 落盘 pull。
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

from arkpaint.core.mumu_extras import MumuExtras
from arkpaint.paths import mumu_instance_from_port


class AdbError(RuntimeError):
    pass


class ScreencapMethod(str, Enum):
  MUMU_EXTRAS = "mumu_extras"
  EXEC_OUT = "exec_out"
  FILE_PULL = "file_pull"


@dataclass
class AdbDevice:
    serial: str
    state: str


class AdbController:
    def __init__(self, adb_path: str | None = None) -> None:
        from arkpaint.paths import find_adb

        self.adb_path = adb_path or find_adb()
        self.serial: str | None = None
        self._screencap_method: ScreencapMethod | None = None
        self._mumu_extras: MumuExtras | None = None

    @property
    def screencap_method(self) -> ScreencapMethod | None:
        return self._screencap_method

    def _run(
        self,
        *args: str,
        timeout: float = 30.0,
        binary: bool = False,
    ) -> str | bytes:
        cmd = [self.adb_path, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                encoding=None if binary else "utf-8",
                text=not binary,
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except FileNotFoundError as exc:
            raise AdbError("未找到 adb，请安装 Android Platform Tools 并加入 PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB 命令超时: {' '.join(cmd)}") from exc
        if proc.returncode != 0:
            raw_err = proc.stderr or proc.stdout or b""
            if isinstance(raw_err, bytes):
                err = raw_err.decode("utf-8", errors="replace").strip()
            else:
                err = str(raw_err).strip()
            raise AdbError(err or f"ADB 失败: {' '.join(cmd)}")
        return proc.stdout if proc.stdout is not None else (b"" if binary else "")

    def version(self) -> str:
        out = self._run("version")
        return out if isinstance(out, str) else out.decode("utf-8", errors="replace")

    def connect(self, host: str, port: int) -> str:
        target = f"{host}:{port}"
        out = self._run("connect", target)
        devices = self.list_devices()
        for d in devices:
            if d.serial == target and d.state == "device":
                self.serial = target
                break
        else:
            online = [d for d in devices if d.state == "device"]
            if online:
                self.serial = online[0].serial
            else:
                raise AdbError(f"连接失败: {out}")
        self._reset_screencap_cache()
        return out if isinstance(out, str) else str(out)

    def list_devices(self) -> list[AdbDevice]:
        out = self._run("devices")
        text = out if isinstance(out, str) else out.decode("utf-8", errors="replace")
        result: list[AdbDevice] = []
        for line in text.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\s+", line)
            if len(parts) >= 2:
                result.append(AdbDevice(serial=parts[0], state=parts[1]))
        return result

    def use_device(self, serial: str) -> None:
        self.serial = serial
        self._reset_screencap_cache()

    def _device_args(self) -> list[str]:
        if self.serial:
            return ["-s", self.serial]
        return []

    def _adb_port(self) -> int | None:
        if not self.serial or ":" not in self.serial:
            return None
        try:
            return int(self.serial.rsplit(":", 1)[-1])
        except ValueError:
            return None

    def _reset_screencap_cache(self) -> None:
        self._screencap_method = None
        if self._mumu_extras is not None:
            self._mumu_extras.close()
            self._mumu_extras = None

    def _ensure_mumu_extras(self) -> MumuExtras | None:
        if self._mumu_extras is not None:
            return self._mumu_extras
        port = self._adb_port()
        idx = mumu_instance_from_port(port) if port is not None else None
        extra = MumuExtras.try_create(adb_port=port, instance_index=idx)
        self._mumu_extras = extra
        return extra

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
        if self._screencap_method is not None:
            return self._screencap_once(self._screencap_method)

        errors: list[str] = []
        for method in (ScreencapMethod.MUMU_EXTRAS, ScreencapMethod.EXEC_OUT, ScreencapMethod.FILE_PULL):
            try:
                img = self._screencap_once(method)
            except AdbError as exc:
                errors.append(f"{method.value}: {exc}")
                continue
            self._screencap_method = method
            return img

        detail = "；".join(errors) if errors else "未知错误"
        raise AdbError(f"所有截图方式均失败：{detail}")

    def _screencap_once(self, method: ScreencapMethod) -> np.ndarray:
        if method is ScreencapMethod.MUMU_EXTRAS:
            extra = self._ensure_mumu_extras()
            if extra is None:
                raise AdbError("MuMu IPC 不可用")
            return extra.screencap_bgr()
        if method is ScreencapMethod.EXEC_OUT:
            return self._screencap_exec_out()
        return self._screencap_file_pull()

    def _screencap_exec_out(self) -> np.ndarray:
        data = self._run(
            *self._device_args(),
            "exec-out",
            "screencap",
            "-p",
            timeout=15.0,
            binary=True,
        )
        if not isinstance(data, bytes) or len(data) < 8:
            raise AdbError("exec-out 截图为空")
        return _decode_png(data)

    def _screencap_file_pull(self) -> np.ndarray:
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
        try:
            devices = self.list_devices()
        except AdbError:
            return False
        if self.serial:
            return any(d.serial == self.serial and d.state == "device" for d in devices)
        return any(d.state == "device" for d in devices)


def _decode_png(data: bytes) -> np.ndarray:
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise AdbError("截图解码失败")
    return img
