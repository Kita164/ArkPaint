"""模板匹配：ROI 搜索、阈值过滤、与 MAA TemplateMatch 对齐的 TM_CCOEFF_NORMED。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_MATCH_METHOD = cv2.TM_CCOEFF_NORMED


@dataclass(frozen=True)
class MatchResult:
    score: float
    center: tuple[int, int]
    rect: tuple[int, int, int, int]  # x, y, w, h（全图坐标）


def _to_gray(bgr: np.ndarray) -> np.ndarray:
    if bgr.ndim == 2:
        return bgr
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _resolve_roi(
    image: np.ndarray,
    roi: tuple[int, int, int, int] | None,
) -> tuple[np.ndarray, int, int]:
    if roi is None:
        return image, 0, 0
    x, y, w, h = roi
    ih, iw = image.shape[:2]
    x0 = max(0, min(int(x), iw - 1))
    y0 = max(0, min(int(y), ih - 1))
    x1 = max(x0 + 1, min(int(x + w), iw))
    y1 = max(y0 + 1, min(int(y + h), ih))
    return image[y0:y1, x0:x1], x0, y0


def _load_template(template: np.ndarray | Path | str) -> np.ndarray | None:
    if isinstance(template, np.ndarray):
        return template
    path = Path(template)
    if not path.is_file():
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def match_template(
    image_bgr: np.ndarray,
    template: np.ndarray | Path | str,
    *,
    roi: tuple[int, int, int, int] | None = None,
    threshold: float = 0.8,
    grayscale: bool = True,
    mask: np.ndarray | None = None,
) -> MatchResult | None:
    """在 ROI 内做单模板匹配，返回最高分且超过阈值的结果。"""
    tpl = _load_template(template)
    if tpl is None or image_bgr is None or image_bgr.size == 0:
        return None

    search, ox, oy = _resolve_roi(image_bgr, roi)
    if search.size == 0:
        return None

    if grayscale:
        search_m = _to_gray(search)
        tpl_m = _to_gray(tpl)
        mask_m = mask
    else:
        search_m = search
        tpl_m = tpl
        mask_m = mask

    th, tw = tpl_m.shape[:2]
    sh, sw = search_m.shape[:2]
    if th < 1 or tw < 1 or sh < th or sw < tw:
        return None

    if mask_m is not None and mask_m.shape[:2] == tpl_m.shape[:2]:
        matched = cv2.matchTemplate(search_m, tpl_m, _MATCH_METHOD, mask=mask_m)
    else:
        matched = cv2.matchTemplate(search_m, tpl_m, _MATCH_METHOD)

    if matched.size == 0:
        return None

    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(matched)
    if float(max_val) < threshold:
        return None

    x, y = max_loc
    rect = (ox + int(x), oy + int(y), int(tw), int(th))
    cx = rect[0] + rect[2] // 2
    cy = rect[1] + rect[3] // 2
    return MatchResult(score=float(max_val), center=(cx, cy), rect=rect)


def match_templates(
    image_bgr: np.ndarray,
    templates: list[np.ndarray | Path | str],
    *,
    roi: tuple[int, int, int, int] | None = None,
    threshold: float = 0.8,
    grayscale: bool = True,
) -> MatchResult | None:
    """多模板取最高分（任一通过阈值即有效）。"""
    best: MatchResult | None = None
    for tpl in templates:
        hit = match_template(
            image_bgr,
            tpl,
            roi=roi,
            threshold=threshold,
            grayscale=grayscale,
        )
        if hit is None:
            continue
        if best is None or hit.score > best.score:
            best = hit
    return best
