"""游戏颜料栏对齐：采样可见色块并与程序色盘比对。"""

from __future__ import annotations

import numpy as np

from arkpaint.core.calibration import CalibrationData

# 游戏 UI 固定展示 4 列 × 6 行 = 24 色
PALETTE_VISIBLE_ROWS = 6
PALETTE_VISIBLE_COLS = 4
FIRST_PAGE_COLORS = PALETTE_VISIBLE_ROWS * PALETTE_VISIBLE_COLS  # 24
# 从顶部滚到底部大约需要的上滑次数（露出 17–40）
PALETTE_BOTTOM_SCROLL_SWIPES = 4
PALETTE_TOP_SCROLL_SWIPES = 4
PALETTE_MATCH_MAX_DIST = 48.0


def bottom_view_top_row(
    total_colors: int,
    *,
    columns: int = PALETTE_VISIBLE_COLS,
    visible_rows: int = PALETTE_VISIBLE_ROWS,
) -> int:
    """滚到底部时，视口顶部对应的绝对行号（40 色 → 4，即 17 色在最上行）。"""
    total_rows = (total_colors + columns - 1) // columns
    return max(0, total_rows - visible_rows)


def rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32)))


def sample_visible_row(
    bgr: np.ndarray,
    calib: CalibrationData,
    row: int,
    *,
    columns: int = PALETTE_VISIBLE_COLS,
) -> list[tuple[int, int, int]]:
    """采样颜料栏某一可见行的色块 RGB（row=0 为当前视口最上一行）。"""
    if not calib.is_palette_ready() or calib.palette_origin is None:
        return []
    ox, oy = calib.palette_origin
    dx, dy = calib.palette_dx, calib.palette_dy
    h, w = bgr.shape[:2]
    rgbs: list[tuple[int, int, int]] = []
    for col in range(columns):
        x = int(round(ox + col * dx))
        y = int(round(oy + row * dy))
        if not (3 <= x < w - 3 and 3 <= y < h - 3):
            continue
        patch = bgr[max(0, y - 2) : y + 3, max(0, x - 2) : x + 3]
        if patch.size == 0:
            continue
        b, g, rr = [int(v) for v in np.median(patch.reshape(-1, 3), axis=0)]
        # 选中描边偏青，收紧采样
        if g > 180 and rr < 180 and b > 180:
            patch = bgr[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2]
            if patch.size:
                b, g, rr = [int(v) for v in np.median(patch.reshape(-1, 3), axis=0)]
        rgbs.append((rr, g, b))
    return rgbs


def top_row_matches(
    bgr: np.ndarray,
    calib: CalibrationData,
    expected: list[tuple[int, int, int]],
    *,
    max_dist: float = PALETTE_MATCH_MAX_DIST,
) -> bool:
    """当前视口最上一行 4 色是否与期望色号 1–4 一致。"""
    return row_matches(bgr, calib, 0, expected, max_dist=max_dist)


def row_matches(
    bgr: np.ndarray,
    calib: CalibrationData,
    row: int,
    expected: list[tuple[int, int, int]],
    *,
    max_dist: float = PALETTE_MATCH_MAX_DIST,
) -> bool:
    """当前视口第 row 行 4 色是否与 expected 一致。"""
    if len(expected) < PALETTE_VISIBLE_COLS:
        return False
    sampled = sample_visible_row(bgr, calib, row)
    if len(sampled) < PALETTE_VISIBLE_COLS:
        return False
    for got, exp in zip(sampled, expected[:PALETTE_VISIBLE_COLS], strict=False):
        if rgb_distance(got, exp) > max_dist:
            return False
    return True


def bottom_row_matches(
    bgr: np.ndarray,
    calib: CalibrationData,
    reference: list[tuple[int, int, int]],
    *,
    max_dist: float = PALETTE_MATCH_MAX_DIST,
) -> bool:
    """滚到底部后，最上一行应为色号 17–20。"""
    if len(reference) < 20:
        return False
    return row_matches(bgr, calib, 0, reference[16:20], max_dist=max_dist)
