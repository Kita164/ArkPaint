"""自动绘制编排：选色 → 填格。"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from arkpaint.config import DEFAULT_COLOR_SWITCH_DELAY_MS, DEFAULT_TAP_DELAY_MS
from arkpaint.core.adb import AdbController
from arkpaint.core.calibration import (
    CalibrationData,
    cell_center_from_calibration,
)
from arkpaint.core.detector import DetectResult, cell_center, detect_pindou_screen
from arkpaint.core.palette import DEFAULT_PALETTE, PaletteColor, palette_to_rgb_list
from arkpaint.core.palette_align import (
    FIRST_PAGE_COLORS,
    PALETTE_BOTTOM_SCROLL_SWIPES,
    PALETTE_TOP_SCROLL_SWIPES,
    PALETTE_VISIBLE_ROWS,
    bottom_row_matches,
    bottom_view_top_row,
    top_row_matches,
)


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
        # 当前视口顶部对应的绝对行号（0 = 色号 1 在最上行）
        self._view_top_row = 0
        self._reference_rgbs: list[tuple[int, int, int]] = []

    def ensure_screen(self, min_confidence: float) -> DetectResult:
        shot = self.adb.screencap()
        return detect_pindou_screen(shot, min_confidence=min_confidence)

    def _swipe_palette_reset_step(self) -> None:
        """在颜料区从上往下滑一步，使色板回到顶部。"""
        if not self.calib.scroll_from or not self.calib.scroll_to:
            return
        x1, y1 = self.calib.scroll_to
        x2, y2 = self.calib.scroll_from
        self.adb.swipe(x1, y1, x2, y2, self.calib.scroll_duration_ms)

    def _swipe_palette_reveal_step(self) -> None:
        """在颜料区从下往上滑一步，露出下方更多色块。"""
        if not self.calib.scroll_from or not self.calib.scroll_to:
            raise RuntimeError("未校准颜料滑动手势，请先完成校准")
        x1, y1 = self.calib.scroll_from
        x2, y2 = self.calib.scroll_to
        self.adb.swipe(x1, y1, x2, y2, self.calib.scroll_duration_ms)

    def _ensure_palette_at_top(
        self,
        reference_rgbs: list[tuple[int, int, int]],
        *,
        should_stop: StopCheck | None = None,
    ) -> None:
        """将游戏颜料栏滚回顶部，并与程序前 4 色比对确认对齐。"""
        if not self.calib.is_palette_ready():
            raise RuntimeError("颜料栏未校准")
        if not reference_rgbs:
            return

        expected = reference_rgbs[:4]
        max_attempts = 4

        for attempt in range(max_attempts + 1):
            if should_stop and should_stop():
                return
            shot = self.adb.screencap()
            if top_row_matches(shot, self.calib, expected):
                time.sleep(0.5)
                self._view_top_row = 0
                return
            if attempt >= max_attempts:
                break
            self._swipe_palette_reset_step()
            time.sleep(0.35)

        # 兜底：再滑几次并等待动画结束
        for _ in range(2):
            if should_stop and should_stop():
                return
            self._swipe_palette_reset_step()
            time.sleep(0.2)
        time.sleep(0.5)
        self._view_top_row = 0

    def _bottom_view_top(self) -> int:
        cols = self.calib.palette_columns
        visible = min(PALETTE_VISIBLE_ROWS, max(1, self.calib.visible_rows))
        return bottom_view_top_row(self.calib.total_colors, columns=cols, visible_rows=visible)

    def _scroll_palette_to_top(self, *, should_stop: StopCheck | None = None) -> None:
        """快速滚回顶部（色号 1–24 区域）。"""
        if self._view_top_row == 0:
            return
        for _ in range(PALETTE_TOP_SCROLL_SWIPES):
            if should_stop and should_stop():
                return
            self._swipe_palette_reset_step()
            time.sleep(0.15)
        time.sleep(0.35)
        self._view_top_row = 0

    def _scroll_palette_to_bottom(self, *, should_stop: StopCheck | None = None) -> None:
        """从顶部一次性滑到底，展示约 17–40 号色（顶部略露 13–16）。"""
        bottom = self._bottom_view_top()
        if self._view_top_row == bottom:
            return
        # 若当前不在顶部，先回顶再一次性上滑到底
        if self._view_top_row > 0:
            self._scroll_palette_to_top(should_stop=should_stop)
        for i in range(PALETTE_BOTTOM_SCROLL_SWIPES):
            if should_stop and should_stop():
                return
            self._swipe_palette_reveal_step()
            time.sleep(0.15)
            if self._reference_rgbs:
                shot = self.adb.screencap()
                if bottom_row_matches(shot, self.calib, self._reference_rgbs):
                    break
        time.sleep(0.5)
        self._view_top_row = bottom

    def _ensure_palette_zone(self, color_index: int, *, should_stop: StopCheck | None = None) -> None:
        """按色号切换颜料栏区域：1–24 在顶部，25+ 在底部。"""
        if color_index <= FIRST_PAGE_COLORS:
            self._scroll_palette_to_top(should_stop=should_stop)
        else:
            self._scroll_palette_to_bottom(should_stop=should_stop)

    def _select_color(self, color_index: int, *, should_stop: StopCheck | None = None) -> None:
        """选择指定色号：切换到对应颜料区域后点击槽位。"""
        if not self.calib.is_palette_ready():
            raise RuntimeError("颜料栏未校准")

        self._ensure_palette_zone(color_index, should_stop=should_stop)

        idx0 = color_index - 1
        abs_row = idx0 // self.calib.palette_columns
        col = idx0 % self.calib.palette_columns
        visible = min(PALETTE_VISIBLE_ROWS, max(1, self.calib.visible_rows))

        slot_row = abs_row - self._view_top_row
        slot_row = min(max(slot_row, 0), visible - 1)
        x, y = self.calib.clamped_visible_slot_center(slot_row, col)
        self.adb.tap(x, y)

    def paint(
        self,
        grid: np.ndarray,
        options: PaintOptions | None = None,
        on_progress: ProgressCallback | None = None,
        on_color: ColorCallback | None = None,
        should_stop: StopCheck | None = None,
        canvas_rect: tuple[int, int, int, int] | None = None,
        reference_palette: list[PaletteColor] | None = None,
    ) -> None:
        options = options or PaintOptions()
        if should_stop is None:
            should_stop = lambda: False

        ref_palette = reference_palette or DEFAULT_PALETTE
        ref_rgbs = palette_to_rgb_list(ref_palette)
        self._reference_rgbs = ref_rgbs

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

        emit("对齐游戏颜料栏…", fraction=0.0)
        self._ensure_palette_at_top(ref_rgbs, should_stop=should_stop)
        if should_stop():
            emit("已停止", fraction=0.0)
            return

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
            self._select_color(color, should_stop=should_stop)
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
                    cx, cy = cell_center(rect, r, c)
                    x, y = self.calib.clamp_canvas_tap(cx, cy)
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
