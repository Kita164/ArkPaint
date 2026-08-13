"""根据拼豆编辑页截图，全自动生成画布与颜料栏校准数据。

布局约定（分辨率可变，结构固定）：
- 中央 24×24 白色网格画布
- 右侧「颜料」4 列色块，共 40 色，可上下滚动
- 左侧导航器忽略
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from arkpaint.config import GRID_SIZE, PALETTE_COLUMNS
from arkpaint.core.calibration import CalibrationData
from arkpaint.core.detector import detect_canvas
from arkpaint.core.palette_align import PALETTE_VISIBLE_ROWS


@dataclass
class AutoCalibrateResult:
    ok: bool
    calibration: CalibrationData | None
    message: str
    canvas_rect: tuple[int, int, int, int] | None = None
    palette_cells: int = 0


def _palette_roi_bounds(
    bgr: np.ndarray, canvas: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """颜料栏 ROI：画布右侧，覆盖完整 4 列色块。"""
    h, w = bgr.shape[:2]
    _cx, _cy, cw, _ch = canvas
    # 不用 detect_ui_panel_bounds 的右缘限 x1：末列色块常超出该边界
    canvas_right = canvas[0] + cw
    x0 = max(int(w * 0.68), canvas_right + max(8, cw // 40))
    x1 = min(w - 2, max(x0 + 120, int(w * 0.98)))
    y0 = int(h * 0.355)
    y1 = int(h * 0.92)
    if x1 - x0 < 40 or y1 - y0 < 80:
        x0, x1 = int(w * 0.68), int(w * 0.98)
        y0, y1 = int(h * 0.34), int(h * 0.94)
    return x0, y0, x1, y1


def detect_palette_cells(roi: np.ndarray) -> list[tuple[float, float]]:
    """在颜料 ROI 内检测色块中心（相对 ROI 坐标）。"""
    h, w = roi.shape[:2]
    if h < 40 or w < 40:
        return []

    # 面板底色约 #424242；与底色差异大的区域视为色块
    panel_ref = np.array([66.0, 66.0, 66.0])
    diff = np.linalg.norm(roi.astype(np.float32) - panel_ref, axis=2)
    content = (diff >= 22).astype(np.uint8) * 255
    content = cv2.morphologyEx(content, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    content = cv2.morphologyEx(content, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    exp_w = w / 4.5
    min_area = max(80.0, (exp_w * 0.35) ** 2)
    max_area = min(roi.size * 0.2, (exp_w * 1.45) ** 2)
    min_dim = max(10.0, exp_w * 0.30)
    max_dim = min(max(h, w) * 0.5, exp_w * 1.55)

    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(content, 8)
    cells: list[tuple[float, float]] = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area or area > max_area:
            continue
        ar = bw / max(bh, 1)
        if not (0.50 <= ar <= 2.0):
            continue
        if min(bw, bh) < min_dim or max(bw, bh) > max_dim:
            continue
        # 忽略贴边的滚动箭头等窄条
        if y < 2 or y + bh > h - 2:
            if bh < exp_w * 0.45:
                continue
        cells.append((float(centroids[i][0]), float(centroids[i][1])))
    return cells


def grid_from_cells(
    cells: list[tuple[float, float]], columns: int = PALETTE_COLUMNS
) -> tuple[float, float, float, float]:
    """由色块中心推算原点与列/行间距。"""
    if len(cells) < max(8, columns * 2):
        raise RuntimeError(f"色块太少（{len(cells)}），请确认色板已滚到顶部且界面完整")

    pts = np.array(cells, dtype=np.float64)
    # 粗估间距：用相邻中心差的中位数
    xs = np.sort(pts[:, 0])
    ys = np.sort(pts[:, 1])
    dxs = np.diff(xs)
    dys = np.diff(ys)
    # 过滤同列/同行的近零差
    span_x = max(1.0, float(xs.max() - xs.min()))
    span_y = max(1.0, float(ys.max() - ys.min()))
    min_pitch_x = span_x / (columns * 2.5)
    min_pitch_y = span_y / 20.0
    dxs = dxs[dxs > min_pitch_x]
    dys = dys[dys > min_pitch_y]
    pitch_x = float(np.median(dxs)) if len(dxs) else span_x / max(columns - 1, 1)
    pitch_y = float(np.median(dys)) if len(dys) else span_y / 5.0

    top_y = float(pts[:, 1].min())
    top = pts[np.abs(pts[:, 1] - top_y) < pitch_y * 0.45]
    if len(top) < 1:
        top = pts
    origin = top[np.argmin(top[:, 0])]
    ox, oy = float(origin[0]), float(origin[1])

    top_sorted = top[np.argsort(top[:, 0])]
    if len(top_sorted) >= 2:
        pitch_x = float(np.median(np.diff(top_sorted[:, 0])))

    left = pts[np.abs(pts[:, 0] - ox) < pitch_x * 0.45]
    left_sorted = left[np.argsort(left[:, 1])]
    if len(left_sorted) >= 2:
        pitch_y = float(np.median(np.diff(left_sorted[:, 1])))

    if pitch_x <= 1 or pitch_y <= 1:
        raise RuntimeError("未能估计色块间距")
    return ox, oy, pitch_x, pitch_y


def _count_visible_rows(
    cells: list[tuple[float, float]],
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    columns: int,
    roi_h: int,
) -> int:
    """根据检测到的色块与 ROI 高度估计完整可见行数。"""
    if dy <= 1:
        return 6
    pts = np.array(cells, dtype=np.float64)
    rows_hit: set[int] = set()
    for px, py in pts:
        col = int(round((px - ox) / dx))
        row = int(round((py - oy) / dy))
        if 0 <= col < columns and row >= 0:
            # 中心需落在色块理论区域内，避免半截行
            if abs(px - (ox + col * dx)) < dx * 0.35 and abs(py - (oy + row * dy)) < dy * 0.35:
                if oy + row * dy + dy * 0.35 < roi_h:
                    rows_hit.add(row)
    if rows_hit:
        return min(6, max(1, max(rows_hit) + 1))
    # 回退：几何推算；游戏 UI 固定约 6 行
    return min(6, max(1, int((roi_h - oy - dy * 0.35) / dy)))


def _sample_colors(
    bgr: np.ndarray,
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    columns: int,
    rows: int,
) -> list[list[int]]:
    h, w = bgr.shape[:2]
    rgbs: list[list[int]] = []
    for r in range(rows):
        for c in range(columns):
            x = int(round(ox + c * dx))
            y = int(round(oy + r * dy))
            if not (3 <= x < w - 3 and 3 <= y < h - 3):
                continue
            # 5×5 中值；若踩到选中描边（偏青），收紧采样
            patch = bgr[max(0, y - 2) : y + 3, max(0, x - 2) : x + 3]
            if patch.size == 0:
                continue
            b, g, rr = [int(v) for v in np.median(patch.reshape(-1, 3), axis=0)]
            if g > 180 and rr < 180 and b > 180:
                patch = bgr[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2]
                if patch.size:
                    b, g, rr = [int(v) for v in np.median(patch.reshape(-1, 3), axis=0)]
            rgbs.append([rr, g, b])
    return rgbs


def _build_scroll(
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    visible_rows: int,
    rows_per_scroll: int,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """在色板中部构造上滑起止点（屏幕坐标）。"""
    cx = int(round(ox + dx * 1.5))
    # 从偏下位置滑到偏上，幅度约 rows_per_scroll 行
    y_from = int(round(oy + dy * max(1.5, visible_rows - 1.5)))
    y_to = int(round(y_from - dy * rows_per_scroll))
    y_to = max(int(oy + dy * 0.5), y_to)
    return (cx, y_from), (cx, y_to)


def refresh_palette_layout(
    bgr: np.ndarray,
    calib: CalibrationData,
    *,
    columns: int = PALETTE_COLUMNS,
) -> bool:
    """在画布已校准的前提下，根据当前截图重测颜料原点与间距。

    用于滑动停稳后刷新槽位，避免「非顶部起步校准 → 回顶后仍用旧坐标」点偏 2 号色。
    """
    canvas = calib.canvas_rect()
    if canvas is None or bgr is None or bgr.size == 0:
        return False

    x, y, w, h = canvas
    img_h, img_w = bgr.shape[:2]
    roi_candidates: list[tuple[int, int, int, int]] = [
        _palette_roi_bounds(bgr, canvas),
        (int(img_w * 0.68), int(img_h * 0.34), int(img_w * 0.98), int(img_h * 0.94)),
        (int(img_w * 0.66), int(img_h * 0.30), int(img_w * 0.97), int(img_h * 0.96)),
    ]

    for x0, y0, x1, y1 in roi_candidates:
        x0 = max(0, min(x0, img_w - 2))
        x1 = max(x0 + 2, min(x1, img_w))
        y0 = max(0, min(y0, img_h - 2))
        y1 = max(y0 + 2, min(y1, img_h))
        roi = bgr[y0:y1, x0:x1]
        cells = detect_palette_cells(roi)
        if len(cells) < max(8, columns * 2):
            continue
        try:
            ox_r, oy_r, dx, dy = grid_from_cells(cells, columns=columns)
        except RuntimeError:
            continue
        ox = float(x0 + ox_r)
        oy = float(y0 + oy_r)
        if ox < x + w * 0.85:
            continue
        if dx < 20 or dy < 20:
            continue

        visible_rows = _count_visible_rows(cells, ox_r, oy_r, dx, dy, columns, roi.shape[0])
        # 游戏颜料栏固定 6 行完整可见；检测值易偏小导致 25+ 槽位错位
        visible_rows = PALETTE_VISIBLE_ROWS
        rps = max(1, min(calib.rows_per_scroll or 3, visible_rows - 1))
        scroll_from, scroll_to = _build_scroll(ox, oy, dx, dy, visible_rows, rps)

        calib.palette_origin = (int(round(ox)), int(round(oy)))
        calib.palette_dx = float(dx)
        calib.palette_dy = float(dy)
        calib.palette_columns = columns
        calib.visible_rows = visible_rows
        calib.scroll_from = scroll_from
        calib.scroll_to = scroll_to
        calib.rows_per_scroll = rps
        return True
    return False


def auto_calibrate(
    bgr: np.ndarray,
    *,
    total_colors: int = 40,
    columns: int = PALETTE_COLUMNS,
    rows_per_scroll: int = 3,
    grid_size: int = GRID_SIZE,
) -> AutoCalibrateResult:
    """从整屏截图自动生成 CalibrationData。"""
    del grid_size  # 格点由画布矩形均分
    if bgr is None or bgr.size == 0:
        return AutoCalibrateResult(False, None, "截图为空")

    canvas = detect_canvas(bgr)
    if canvas is None:
        return AutoCalibrateResult(
            False,
            None,
            "未找到中央画布，请确认已打开拼豆编辑页且画布可见",
        )

    x, y, w, h = canvas
    img_h, img_w = bgr.shape[:2]

    # 优先画布右侧 ROI；不足时回退到固定比例裁剪（与历史采样一致）
    roi_candidates: list[tuple[int, int, int, int]] = [
        _palette_roi_bounds(bgr, canvas),
        (int(img_w * 0.68), int(img_h * 0.34), int(img_w * 0.96), int(img_h * 0.94)),
        (int(img_w * 0.66), int(img_h * 0.30), int(img_w * 0.97), int(img_h * 0.96)),
    ]

    last_cells = 0
    last_err = "未能识别颜料色块"
    for x0, y0, x1, y1 in roi_candidates:
        x0 = max(0, min(x0, img_w - 2))
        x1 = max(x0 + 2, min(x1, img_w))
        y0 = max(0, min(y0, img_h - 2))
        y1 = max(y0 + 2, min(y1, img_h))
        roi = bgr[y0:y1, x0:x1]
        cells = detect_palette_cells(roi)
        last_cells = len(cells)
        if len(cells) < max(8, columns * 2):
            last_err = f"颜料色块识别不足（{len(cells)}），请将色板滚到顶部后重试"
            continue
        try:
            ox_r, oy_r, dx, dy = grid_from_cells(cells, columns=columns)
        except RuntimeError as exc:
            last_err = str(exc)
            continue

        ox = float(x0 + ox_r)
        oy = float(y0 + oy_r)
        # 原点应落在画布右侧，避免误检左侧导航预览
        if ox < x + w * 0.85:
            last_err = "色板位置异常（疑似误检），请重试或点「诊断识别」"
            continue

        visible_rows = _count_visible_rows(cells, ox_r, oy_r, dx, dy, columns, roi.shape[0])
        visible_rows = PALETTE_VISIBLE_ROWS
        rps = max(1, min(rows_per_scroll, visible_rows - 1))

        scroll_from, scroll_to = _build_scroll(ox, oy, dx, dy, visible_rows, rps)
        sampled = _sample_colors(bgr, ox, oy, dx, dy, columns, visible_rows)

        calib = CalibrationData(
            canvas_tl=(x, y),
            canvas_br=(x + w, y + h),
            palette_origin=(int(round(ox)), int(round(oy))),
            palette_dx=float(dx),
            palette_dy=float(dy),
            palette_columns=columns,
            visible_rows=visible_rows,
            total_colors=total_colors,
            scroll_from=scroll_from,
            scroll_to=scroll_to,
            scroll_duration_ms=350,
            rows_per_scroll=rps,
            sampled_rgbs=sampled,
            paint_verified=False,
            screen_size=(img_w, img_h),
            device_serial=None,
        )

        msg = (
            f"画布 {w}×{h} @ ({x},{y})；"
            f"色板原点 ({calib.palette_origin[0]},{calib.palette_origin[1]})，"
            f"间距 {dx:.1f}×{dy:.1f}，可见 {visible_rows} 行，"
            f"采样 {len(sampled)} 色"
        )
        return AutoCalibrateResult(
            ok=True,
            calibration=calib,
            message=msg,
            canvas_rect=canvas,
            palette_cells=len(cells),
        )

    return AutoCalibrateResult(
        False,
        None,
        last_err,
        canvas_rect=canvas,
        palette_cells=last_cells,
    )
