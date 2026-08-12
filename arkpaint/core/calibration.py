"""颜料栏与画布坐标校准数据。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from arkpaint.config import CALIBRATION_PATH, GRID_SIZE, PALETTE_COLUMNS, load_json, save_json


@dataclass
class CalibrationData:
    """一次手动校准的结果。

    颜料栏：以「第 1 色」中心为原点，按列数与单元格间距推算点击坐标；
    超出可见行时，用 swipe 上滑露出后续颜色。
    """

    # 画布左上角与右下角（屏幕坐标），用于精细覆盖自动检测
    canvas_tl: tuple[int, int] | None = None
    canvas_br: tuple[int, int] | None = None

    # 颜料：第 1 个色块中心
    palette_origin: tuple[int, int] | None = None
    # 相邻色块中心间距（列间距、行间距）
    palette_dx: float = 0.0
    palette_dy: float = 0.0
    palette_columns: int = PALETTE_COLUMNS
    # 当前可见行数（截图里大约 6 行）
    visible_rows: int = 6
    # 色盘总色数（可大于可见数量）
    total_colors: int = 40

    # 滑动校准：在颜料区域向上滑一次，大约翻过多少行
    scroll_from: tuple[int, int] | None = None
    scroll_to: tuple[int, int] | None = None
    scroll_duration_ms: int = 350
    rows_per_scroll: int = 3

    # 采样得到的 RGB 列表（可选，覆盖默认色盘）
    sampled_rgbs: list[list[int]] = field(default_factory=list)

    def canvas_rect(self) -> tuple[int, int, int, int] | None:
        if not self.canvas_tl or not self.canvas_br:
            return None
        x1, y1 = self.canvas_tl
        x2, y2 = self.canvas_br
        return (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def is_palette_ready(self) -> bool:
        return (
            self.palette_origin is not None
            and self.palette_dx > 0
            and self.palette_dy > 0
            and self.total_colors > 0
        )

    def is_canvas_ready(self) -> bool:
        return self.canvas_rect() is not None

    def color_center(self, color_index: int) -> tuple[int, int]:
        """色号（1-based）在「当前滚动到顶部」时的理论坐标。"""
        if not self.palette_origin:
            raise RuntimeError("颜料原点未校准")
        idx0 = color_index - 1
        col = idx0 % self.palette_columns
        row = idx0 // self.palette_columns
        ox, oy = self.palette_origin
        return int(ox + col * self.palette_dx), int(oy + row * self.palette_dy)

    def visible_slot_center(self, slot_row: int, slot_col: int) -> tuple[int, int]:
        if not self.palette_origin:
            raise RuntimeError("颜料原点未校准")
        ox, oy = self.palette_origin
        return int(ox + slot_col * self.palette_dx), int(oy + slot_row * self.palette_dy)

    def palette_tap_bounds(self) -> tuple[int, int, int, int] | None:
        """可见颜料网格的点击安全区域 (x0, y0, x1, y1)。"""
        if not self.is_palette_ready() or self.palette_origin is None:
            return None
        ox, oy = self.palette_origin
        dx, dy = self.palette_dx, self.palette_dy
        cols = self.palette_columns
        rows = min(self.visible_rows, 6)
        margin_x = max(4.0, dx * 0.28)
        margin_y = max(4.0, dy * 0.28)
        x0 = int(ox - margin_x)
        x1 = int(ox + (cols - 1) * dx + margin_x)
        y0 = int(oy - margin_y)
        # 底部留出滚动箭头区域，避免误点
        y1 = int(oy + (rows - 1) * dy + margin_y * 0.6)
        return x0, y0, x1, y1

    def clamp_palette_tap(self, x: int, y: int) -> tuple[int, int]:
        bounds = self.palette_tap_bounds()
        if bounds is None:
            return x, y
        x0, y0, x1, y1 = bounds
        return min(max(x, x0), x1), min(max(y, y0), y1)

    def clamp_canvas_tap(self, x: int, y: int) -> tuple[int, int]:
        rect = self.canvas_rect()
        if rect is None:
            return x, y
        cx, cy, cw, ch = rect
        margin = 2
        return (
            min(max(x, cx + margin), cx + cw - margin),
            min(max(y, cy + margin), cy + ch - margin),
        )

    def clamped_visible_slot_center(self, slot_row: int, slot_col: int) -> tuple[int, int]:
        x, y = self.visible_slot_center(slot_row, slot_col)
        return self.clamp_palette_tap(x, y)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationData:
        def tup(v: Any) -> tuple[int, int] | None:
            if v is None:
                return None
            return int(v[0]), int(v[1])

        return cls(
            canvas_tl=tup(data.get("canvas_tl")),
            canvas_br=tup(data.get("canvas_br")),
            palette_origin=tup(data.get("palette_origin")),
            palette_dx=float(data.get("palette_dx") or 0),
            palette_dy=float(data.get("palette_dy") or 0),
            palette_columns=int(data.get("palette_columns") or PALETTE_COLUMNS),
            visible_rows=int(data.get("visible_rows") or 6),
            total_colors=int(data.get("total_colors") or 40),
            scroll_from=tup(data.get("scroll_from")),
            scroll_to=tup(data.get("scroll_to")),
            scroll_duration_ms=int(data.get("scroll_duration_ms") or 350),
            rows_per_scroll=int(data.get("rows_per_scroll") or 3),
            sampled_rgbs=list(data.get("sampled_rgbs") or []),
        )


def load_calibration() -> CalibrationData:
    raw = load_json(CALIBRATION_PATH, {})
    if not isinstance(raw, dict) or not raw:
        return CalibrationData()
    return CalibrationData.from_dict(raw)


def save_calibration(data: CalibrationData) -> None:
    save_json(CALIBRATION_PATH, data.to_dict())


def cell_center_from_calibration(
    calib: CalibrationData,
    row: int,
    col: int,
    grid: int = GRID_SIZE,
) -> tuple[int, int]:
    rect = calib.canvas_rect()
    if rect is None:
        raise RuntimeError("画布未校准")
    x, y, w, h = rect
    cx = int(x + (col + 0.5) * (w / grid))
    cy = int(y + (row + 0.5) * (h / grid))
    return calib.clamp_canvas_tap(cx, cy)
