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
        # 面积大且更接近正方形优先
        score = area * (1.0 - abs(1.0 - ratio))
        if score > best_score:
            best_score = score
            best = (x, y, w, h)
    return best


def detect_canvas_region(bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """在截图中寻找中央接近正方形的白色画布区域。"""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # 偏白区域
    _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = (w * h) * 0.08
    return _largest_near_square(contours, min_area)


def _template_score(bgr: np.ndarray, template_path: Path) -> float:
    if not template_path.exists():
        return 0.0
    tpl = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if tpl is None:
        return 0.0
    # 缩放到相近宽度再匹配
    th, tw = tpl.shape[:2]
    sh, sw = bgr.shape[:2]
    scale = sw / float(tw)
    new_w = sw
    new_h = max(1, int(th * scale))
    resized = cv2.resize(tpl, (new_w, new_h))
    # 若高度仍不一致，裁剪重叠区
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
    """综合模板相似度 + 白色画布检测，判断是否在拼豆页。"""
    ref = reference_path or REFERENCE_IMAGE
    template_conf = _template_score(bgr, ref)
    canvas = detect_canvas_region(bgr)

    structure_conf = 0.0
    if canvas is not None:
        x, y, cw, ch = canvas
        structure_conf = 0.55
        # 画布大致居中加分
        img_cx = bgr.shape[1] / 2
        canvas_cx = x + cw / 2
        if abs(canvas_cx - img_cx) < bgr.shape[1] * 0.18:
            structure_conf += 0.15
        # 画布内有网格线痕迹
        roi = bgr[y : y + ch, x : x + cw]
        if roi.size:
            edges = cv2.Canny(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 50, 150)
            edge_ratio = float(np.count_nonzero(edges)) / edges.size
            if 0.02 < edge_ratio < 0.25:
                structure_conf += 0.2

    confidence = max(template_conf, structure_conf)
    # 两者都有时加权
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
