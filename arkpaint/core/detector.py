"""游戏画面识别：判断当前是否在拼豆编辑页。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from arkpaint.config import GRID_SIZE, REFERENCE_IMAGE


@dataclass
class DetectResult:
    ok: bool
    confidence: float
    canvas_rect: tuple[int, int, int, int] | None  # x, y, w, h
    message: str


def _largest_near_square(contours, min_area: float) -> tuple[int, int, int, int] | None:
    best = None
    best_score = 0.0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 100 or h < 100:
            continue
        ratio = w / float(h)
        if ratio < 0.85 or ratio > 1.15:
            continue
        score = area * (1.0 - abs(1.0 - ratio))
        if score > best_score:
            best_score = score
            best = (x, y, w, h)
    return best


def detect_ui_panel_bounds(bgr: np.ndarray) -> tuple[int, int]:
    """检测左右深色 UI 面板，返回 (左面板右缘 x, 右面板左缘 x)。"""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    dark = gray < 95
    col_ratio = dark.mean(axis=0)

    left_region = col_ratio[: max(1, int(w * 0.30))]
    left_cols = np.where(left_region > 0.35)[0]
    left_end = int(left_cols[-1]) + 1 if len(left_cols) else max(80, int(w * 0.12))

    right_start_idx = w // 2
    right_region = col_ratio[right_start_idx:]
    right_cols = np.where(right_region > 0.35)[0]
    if len(right_cols):
        right_start = right_start_idx + int(right_cols[0])
    else:
        right_start = int(w * 0.68)

    left_end = max(0, min(left_end, w - 200))
    right_start = max(left_end + 200, min(right_start, w - 80))
    return left_end, right_start


def canvas_white_mask(bgr: np.ndarray) -> np.ndarray:
    """画布检测用的偏白二值图（调试时可保存对照）。"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def detect_canvas_region(bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """在截图中寻找中央接近正方形的白色画布区域（旧：整图白块，浅色背景易失败）。"""
    h, w = bgr.shape[:2]
    mask = canvas_white_mask(bgr)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = (w * h) * 0.08
    return _largest_near_square(contours, min_area)


def _refine_canvas_rect(
    bgr: np.ndarray, rect: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """在粗定位的白块内，用边缘投影收紧到网格外缘。"""
    x, y, w, h = rect
    ratio = w / float(h)
    if 0.92 <= ratio <= 1.08 and 200 <= w <= int(bgr.shape[1] * 0.48):
        return rect

    pad = max(2, min(w, h) // 80)
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(bgr.shape[1], x + w + pad)
    y1 = min(bgr.shape[0], y + h + pad)
    roi = bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return rect

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    k = max(3, min(roi.shape[0], roi.shape[1]) // 60)
    if k % 2 == 0:
        k += 1
    kernel = np.ones((k, k), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    ys, xs = np.where(mask > 0)
    if len(xs) < 100:
        return rect
    rx0, rx1 = int(xs.min()), int(xs.max()) + 1
    ry0, ry1 = int(ys.min()), int(ys.max()) + 1
    rw, rh = rx1 - rx0, ry1 - ry0
    if rw < 80 or rh < 80:
        return rect
    ratio = rw / float(rh)
    if ratio < 0.85 or ratio > 1.15:
        return rect
    return (x0 + rx0, y0 + ry0, rw, rh)


def _merge_canvas_quadrants(
    rects: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """拼豆画布常因中线被分成 2×2 象限，合并为外接矩形。"""
    if not rects:
        return None
    if len(rects) == 1:
        return rects[0]

    # 只合并尺寸接近的正方形（象限）
    sizes = [min(r[2], r[3]) for r in rects]
    med = float(np.median(sizes))
    tiles = [
        r
        for r in rects
        if med * 0.82 <= min(r[2], r[3]) <= med * 1.18
        and 0.88 <= r[2] / max(r[3], 1) <= 1.12
    ]
    if len(tiles) >= 2:
        x0 = min(r[0] for r in tiles)
        y0 = min(r[1] for r in tiles)
        x1 = max(r[0] + r[2] for r in tiles)
        y1 = max(r[1] + r[3] for r in tiles)
        return (x0, y0, x1 - x0, y1 - y0)
    return max(rects, key=lambda r: r[2] * r[3])


def _detect_canvas_in_workspace(
    bgr: np.ndarray, left_x: int, right_x: int
) -> tuple[int, int, int, int] | None:
    """在左右面板之间，用网格白底 + 边缘密度定位正方形画布。"""
    h, w = bgr.shape[:2]
    ws_w = max(1, right_x - left_x)
    ws = bgr[:, left_x:right_x]
    gray = cv2.cvtColor(ws, cv2.COLOR_BGR2GRAY)

    _, mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
    k = 7
    kernel = np.ones((k, k), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_side = max(160, int(min(h, ws_w) * 0.22))
    max_side = int(min(h, ws_w) * 0.52)
    min_area = min_side * min_side
    ws_cx = ws_w / 2.0
    img_cy = h / 2.0

    candidates: list[tuple[int, int, int, int, float]] = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        if area < min_area or bw < min_side or bh < min_side:
            continue
        if bw > max_side or bh > max_side:
            continue
        ratio = bw / float(bh)
        if ratio < 0.88 or ratio > 1.12:
            continue
        roi = gray[y : y + bh, x : x + bw]
        edge_ratio = float(cv2.Canny(roi, 40, 120).mean())
        if edge_ratio < 7.0:
            continue
        cx = x + bw / 2.0
        cy = y + bh / 2.0
        center_penalty = abs(cx - ws_cx) / ws_w + abs(cy - img_cy) / h
        score = area * (1.0 - abs(1.0 - ratio)) * (1.0 - center_penalty * 0.65)
        score *= 1.0 + edge_ratio / 25.0
        candidates.append((left_x + x, y, bw, bh, score))

    if not candidates:
        return None

    merged = _merge_canvas_quadrants([(c[0], c[1], c[2], c[3]) for c in candidates])
    if merged is not None:
        return merged

    best = max(candidates, key=lambda c: c[4])
    return (best[0], best[1], best[2], best[3])


def detect_canvas(bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """定位中央画布，返回 (x, y, w, h)。"""
    left_x, right_x = detect_ui_panel_bounds(bgr)
    rough = _detect_canvas_in_workspace(bgr, left_x, right_x)
    if rough is not None:
        return rough

    # 回退：中部裁剪 + 旧白块法
    h, w = bgr.shape[:2]
    x0, x1 = int(w * 0.18), int(w * 0.72)
    cropped = bgr[:, x0:x1]
    rough = detect_canvas_region(cropped)
    if rough is None:
        return None
    rx, ry, rw, rh = rough
    return _refine_canvas_rect(bgr, (rx + x0, ry, rw, rh))


def _template_score(bgr: np.ndarray, template_path: Path) -> float:
    if not template_path.exists():
        return 0.0
    tpl = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if tpl is None:
        return 0.0
    th, tw = tpl.shape[:2]
    sh, sw = bgr.shape[:2]
    scale = sw / float(tw)
    new_w = sw
    new_h = max(1, int(th * scale))
    resized = cv2.resize(tpl, (new_w, new_h))
    oh = min(sh, resized.shape[0])
    ow = min(sw, resized.shape[1])
    a = bgr[:oh, :ow]
    b = resized[:oh, :ow]
    a_small = cv2.resize(a, (320, 180))
    b_small = cv2.resize(b, (320, 180))
    res = cv2.matchTemplate(
        cv2.cvtColor(a_small, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(b_small, cv2.COLOR_BGR2GRAY),
        cv2.TM_CCOEFF_NORMED,
    )
    return float(res.max()) if res.size else 0.0


def detect_pindou_screen(
    bgr: np.ndarray,
    min_confidence: float = 0.72,
    reference_path: Path | None = None,
) -> DetectResult:
    """综合模板相似度 + 画布/网格检测，判断是否在拼豆页。"""
    ref = reference_path or REFERENCE_IMAGE
    template_conf = _template_score(bgr, ref)
    canvas = detect_canvas(bgr)

    structure_conf = 0.0
    if canvas is not None:
        x, y, cw, ch = canvas
        structure_conf = 0.55
        if min(cw, ch) >= 600:
            structure_conf += 0.08
        img_cx = bgr.shape[1] / 2
        canvas_cx = x + cw / 2
        if abs(canvas_cx - img_cx) < bgr.shape[1] * 0.18:
            structure_conf += 0.15
        roi = bgr[y : y + ch, x : x + cw]
        if roi.size:
            edges = cv2.Canny(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 50, 150)
            edge_ratio = float(np.count_nonzero(edges)) / edges.size
            if 0.02 < edge_ratio < 0.25:
                structure_conf += 0.2

    confidence = max(template_conf, structure_conf)
    if template_conf > 0 and structure_conf > 0:
        confidence = 0.45 * template_conf + 0.55 * structure_conf

    if canvas is None:
        return DetectResult(
            ok=False,
            confidence=confidence,
            canvas_rect=None,
            message="未找到中央画布，请确认已打开拼豆编辑页",
        )

    ok = confidence >= min_confidence
    msg = "识别通过，可以开始绘制" if ok else f"置信度不足 ({confidence:.2f} < {min_confidence:.2f})"
    return DetectResult(ok=ok, confidence=confidence, canvas_rect=canvas, message=msg)


def cell_center(canvas_rect: tuple[int, int, int, int], row: int, col: int, grid: int = GRID_SIZE) -> tuple[int, int]:
    x, y, w, h = canvas_rect
    cell_w = w / grid
    cell_h = h / grid
    cx = int(x + (col + 0.5) * cell_w)
    cy = int(y + (row + 0.5) * cell_h)
    return cx, cy
