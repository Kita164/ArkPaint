"""MuMu 12 EmulatorExtras：通过 external_renderer_ipc.dll 无损快截（参考 MAA）。"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from arkpaint.paths import find_mumu_install_dir, mumu_instance_from_port


class MumuExtrasError(RuntimeError):
    pass


@dataclass
class MumuExtras:
    """MuMu IPC 截图；失败时由 AdbController 回退到 ADB 截图。"""

    install_dir: Path
    instance_index: int
    display_id: int = 0

    _lib: ctypes.CDLL | None = None
    _handle: int = 0
    _width: int = 0
    _height: int = 0
    _buffer: ctypes.Array | None = None

    @classmethod
    def try_create(cls, adb_port: int | None = None, instance_index: int | None = None) -> MumuExtras | None:
        if sys.platform != "win32":
            return None
        install = find_mumu_install_dir()
        if install is None:
            return None
        idx = instance_index
        if idx is None and adb_port is not None:
            idx = mumu_instance_from_port(adb_port)
        if idx is None:
            idx = 0
        try:
            extra = cls(install_dir=install, instance_index=idx)
            extra._ensure_connected()
            return extra
        except (MumuExtrasError, OSError):
            return None

    def _dll_candidates(self) -> list[Path]:
        root = self.install_dir
        rels = (
            Path("nx_device") / "15.0" / "shell" / "sdk" / "external_renderer_ipc.dll",
            Path("nx_device") / "12.0" / "shell" / "sdk" / "external_renderer_ipc.dll",
            Path("shell") / "sdk" / "external_renderer_ipc.dll",
        )
        return [root / rel for rel in rels]

    def _load_dll(self) -> ctypes.CDLL:
        if self._lib is not None:
            return self._lib
        last_err: Exception | None = None
        for dll_path in self._dll_candidates():
            if not dll_path.is_file():
                continue
            try:
                lib = ctypes.CDLL(str(dll_path))
            except OSError as exc:
                last_err = exc
                continue
            self._lib = lib
            return lib
        raise MumuExtrasError(f"未找到 MuMu IPC DLL：{self.install_dir}") from last_err

    def _ensure_connected(self) -> None:
        if self._handle > 0:
            return
        lib = self._load_dll()
        nemu_folder = str(self.install_dir)
        handle = int(lib.nemu_connect(nemu_folder, int(self.instance_index)))
        if handle <= 0:
            raise MumuExtrasError("nemu_connect 失败，请确认 MuMu 已启动且实例编号正确")
        self._handle = handle

        width = ctypes.c_int(0)
        height = ctypes.c_int(0)
        ret = int(
            lib.nemu_capture_display(
                self._handle,
                int(self.display_id),
                0,
                ctypes.byref(width),
                ctypes.byref(height),
                None,
            )
        )
        if ret != 0:
            self.close()
            raise MumuExtrasError(f"nemu_capture_display 初始化失败：{ret}")
        self._width = int(width.value)
        self._height = int(height.value)
        if self._width <= 0 or self._height <= 0:
            self.close()
            raise MumuExtrasError("MuMu 截图分辨率无效")
        length = self._width * self._height * 4
        self._buffer = (ctypes.c_ubyte * length)()

    def screencap_bgr(self) -> np.ndarray:
        self._ensure_connected()
        assert self._lib is not None and self._buffer is not None

        width = ctypes.c_int(self._width)
        height = ctypes.c_int(self._height)
        length = self._width * self._height * 4
        ret = int(
            self._lib.nemu_capture_display(
                self._handle,
                int(self.display_id),
                length,
                ctypes.byref(width),
                ctypes.byref(height),
                ctypes.cast(self._buffer, ctypes.POINTER(ctypes.c_ubyte)),
            )
        )
        if ret != 0:
            raise MumuExtrasError(f"nemu_capture_display 失败：{ret}")

        rgba = np.ctypeslib.as_array(self._buffer).reshape((self._height, self._width, 4))
        bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        return cv2.flip(bgr, 0)

    def close(self) -> None:
        if self._lib is not None and self._handle > 0:
            try:
                self._lib.nemu_disconnect(self._handle)
            except Exception:
                pass
        self._handle = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
