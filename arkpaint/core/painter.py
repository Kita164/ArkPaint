"""自动绘制编排：选色 → 填格。"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import numpy as np

from arkpaint.config import DEFAULT_COLOR_SWITCH_DELAY_MS, DEFAULT_TAP_DELAY_MS
from arkpaint.core.adb import AdbController
from arkpaint.core.calibration import (
    CalibrationData,
    cell_center_from_calibration,
)
from arkpaint.core.detector import DetectResult, cell_center, detect_pindou_screen


@dataclass
class PaintProgress:
    """绘制进度，供 UI 进度条与文案使用。"""

    message: str
    fraction: float  # 0~1 总体进度
    color_index: int | None = None  # 当前色号（游戏编号）
    color_ord: int = 0  # 正在处理第几个色块（1-based）
    color_total: int = 0  # 本次用到的色块总数
    cells_done: int = 0
    cells_total: int = 0
    cells_in_color_done: int = 0
    cells_in_color_total: int = 0


ProgressCallback = Callable[[PaintProgress], None]
ColorCallback = Callable[[int], None]  # current color index 1-based
StopCheck = Callable[[], bool]


@dataclass
class PaintOptions:
    tap_delay_ms: int = DEFAULT_TAP_DELAY_MS
    color_switch_delay_ms: int = DEFAULT_COLOR_SWITCH_DELAY_MS
    min_confidence: float = 0.72
    skip_color_index: int | None = 4  # 默认跳过白色（色号 4）
    skip_empty: bool = True


class AutoPainter:
    def __init__(self, adb: AdbController, calib: CalibrationData) -> None:
        self.adb = adb
        self.calib = calib

    def ensure_screen(self, min_confidence: float) -> DetectResult:
        shot = self.adb.screencap()
        return detect_pindou_screen(shot, min_confidence=min_confidence)

    def _reset_palette_scroll(self) -> None:
        """尽量滚回顶部：多次向下滑（手指从上往下）。"""
        if not self.calib.scroll_from or not self.calib.scroll_to:
            return
        # scroll_from -> scroll_to 定义为「上滑露出更多」；反向则回顶
        x1, y1 = self.calib.scroll_to
        x2, y2 = self.calib.scroll_from
        for _ in range(8):
            self.adb.swipe(x1, y1, x2, y2, self.calib.scroll_duration_ms)
            time.sleep(0.12)

    def _scroll_down_once(self) -> None:
        if not self.calib.scroll_from or not self.calib.scroll_to:
            raise RuntimeError("未校准颜料滑动手势，请先完成校准")
        x1, y1 = self.calib.scroll_from
        x2, y2 = self.calib.scroll_to
        self.adb.swipe(x1, y1, x2, y2, self.calib.scroll_duration_ms)
        time.sleep(0.15)

    def _select_color(self, color_index: int) -> None:
        """选择指定色号：滚到可见后点击对应槽位。"""
        if not self.calib.is_palette_ready():
            raise RuntimeError("颜料栏未校准")

        idx0 = color_index - 1
        abs_row = idx0 // self.calib.palette_columns
        col = idx0 % self.calib.palette_columns
        visible = max(1, self.calib.visible_rows)
        rps = max(1, self.calib.rows_per_scroll)

        self._reset_palette_scroll()

        if abs_row < visible:
            x, y = self.calib.visible_slot_center(abs_row, col)
            self.adb.tap(x, y)
            return

        # 滚到使 abs_row 落在可见窗口内：view_top = steps * rps
        steps = int(np.ceil((abs_row - visible + 1) / rps))
        steps = max(1, steps)
        for _ in range(steps):
            self._scroll_down_once()

        view_top = steps * rps
        slot_row = int(abs_row - view_top)
        slot_row = min(max(slot_row, 0), visible - 1)
        x, y = self.calib.visible_slot_center(slot_row, col)
        self.adb.tap(x, y)

    def paint(
        self,
        grid: np.ndarray,
        options: PaintOptions | None = None,
        on_progress: ProgressCallback | None = None,
        on_color: ColorCallback | None = None,
        should_stop: StopCheck | None = None,
        canvas_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        options = options or PaintOptions()
        if should_stop is None:
            should_stop = lambda: False

        def emit(
            msg: str,
            *,
            fraction: float,
            color_index: int | None = None,
            color_ord: int = 0,
            color_total: int = 0,
            cells_done: int = 0,
            cells_total: int = 0,
            cells_in_color_done: int = 0,
            cells_in_color_total: int = 0,
        ) -> None:
            if on_progress:
                on_progress(
                    PaintProgress(
                        message=msg,
                        fraction=fraction,
                        color_index=color_index,
                        color_ord=color_ord,
                        color_total=color_total,
                        cells_done=cells_done,
                        cells_total=cells_total,
                        cells_in_color_done=cells_in_color_done,
                        cells_in_color_total=cells_in_color_total,
                    )
                )

        emit("识别游戏画面…", fraction=0.0)
        detected = self.ensure_screen(options.min_confidence)
        if not detected.ok:
            raise RuntimeError(detected.message)

        rect = canvas_rect or self.calib.canvas_rect() or detected.canvas_rect
        if rect is None:
            raise RuntimeError("无法确定画布坐标，请先校准画布")

        # 按颜色分组，减少切色次数
        groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
        h, w = grid.shape
        for r in range(h):
            for c in range(w):
                color = int(grid[r, c])
                if options.skip_empty and options.skip_color_index and color == options.skip_color_index:
                    continue
                groups[color].append((r, c))

        colors = sorted(groups.keys())
        color_total = len(colors)
        total_cells = sum(len(v) for v in groups.values()) or 1
        done_cells = 0

        for ci, color in enumerate(colors):
            color_ord = ci + 1
            in_total = len(groups[color])
            if should_stop():
                emit(
                    "已停止",
                    fraction=done_cells / total_cells,
                    color_index=color,
                    color_ord=color_ord,
                    color_total=color_total,
                    cells_done=done_cells,
                    cells_total=total_cells,
                    cells_in_color_done=0,
                    cells_in_color_total=in_total,
                )
                return

            if on_color:
                on_color(color)
            emit(
                f"选择颜色 #{color}（{color_ord}/{color_total}）",
                fraction=done_cells / total_cells,
                color_index=color,
                color_ord=color_ord,
                color_total=color_total,
                cells_done=done_cells,
                cells_total=total_cells,
                cells_in_color_done=0,
                cells_in_color_total=in_total,
            )
            self._select_color(color)
            time.sleep(options.color_switch_delay_ms / 1000.0)

            in_done = 0
            for r, c in groups[color]:
                if should_stop():
                    emit(
                        "已停止",
                        fraction=done_cells / total_cells,
                        color_index=color,
                        color_ord=color_ord,
                        color_total=color_total,
                        cells_done=done_cells,
                        cells_total=total_cells,
                        cells_in_color_done=in_done,
                        cells_in_color_total=in_total,
                    )
                    return
                if self.calib.is_canvas_ready():
                    x, y = cell_center_from_calibration(self.calib, r, c)
                else:
                    x, y = cell_center(rect, r, c)
                self.adb.tap(x, y)
                done_cells += 1
                in_done += 1
                if in_done == 1 or in_done == in_total or done_cells % 4 == 0:
                    emit(
                        f"绘制中 #{color} · {done_cells}/{total_cells}",
                        fraction=done_cells / total_cells,
                        color_index=color,
                        color_ord=color_ord,
                        color_total=color_total,
                        cells_done=done_cells,
                        cells_total=total_cells,
                        cells_in_color_done=in_done,
                        cells_in_color_total=in_total,
                    )
                time.sleep(options.tap_delay_ms / 1000.0)

        emit(
            "绘制完成",
            fraction=1.0,
            color_ord=color_total,
            color_total=color_total,
            cells_done=total_cells,
            cells_total=total_cells,
        )
