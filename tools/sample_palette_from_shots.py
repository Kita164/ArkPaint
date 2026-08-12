"""从游戏截图采样 4×6 颜料格，合并 1-24 与续页为固定色盘。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

DATA = Path(__file__).resolve().parents[1] / "data"
SCRATCH = DATA / "scratch"
COLS, ROWS = 4, 6


def detect_cells(roi: np.ndarray) -> list[tuple[float, float]]:
    panel_ref = np.array([66.0, 66.0, 66.0])
    diff = np.linalg.norm(roi.astype(float) - panel_ref, axis=2)
    content = (diff >= 22).astype(np.uint8) * 255
    content = cv2.morphologyEx(content, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    content = cv2.morphologyEx(content, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(content, 8)
    cells: list[tuple[float, float]] = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 300 or area > 12000:
            continue
        ar = bw / max(bh, 1)
        if not (0.55 <= ar <= 1.8):
            continue
        if min(bw, bh) < 18 or max(bw, bh) > 140:
            continue
        cells.append((float(centroids[i][0]), float(centroids[i][1])))
    return cells


def grid_from_cells(cells: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    if len(cells) < 12:
        raise RuntimeError(f"色块太少: {len(cells)}")
    pts = np.array(cells)
    xs = np.sort(np.unique(np.round(pts[:, 0] / 5) * 5))
    ys = np.sort(np.unique(np.round(pts[:, 1] / 5) * 5))
    dxs = np.diff(xs)
    dys = np.diff(ys)
    dxs = dxs[dxs > 40]
    dys = dys[dys > 40]
    pitch_x = float(np.median(dxs)) if len(dxs) else 105.0
    pitch_y = float(np.median(dys)) if len(dys) else 105.0

    top_y = pts[:, 1].min()
    top = pts[np.abs(pts[:, 1] - top_y) < pitch_y * 0.4]
    origin = top[np.argmin(top[:, 0])]
    ox, oy = float(origin[0]), float(origin[1])

    top_sorted = top[np.argsort(top[:, 0])]
    if len(top_sorted) >= 2:
        pitch_x = float(np.median(np.diff(top_sorted[:, 0])))

    left = pts[np.abs(pts[:, 0] - ox) < pitch_x * 0.4]
    left_sorted = left[np.argsort(left[:, 1])]
    if len(left_sorted) >= 2:
        pitch_y = float(np.median(np.diff(left_sorted[:, 1])))

    return ox, oy, pitch_x, pitch_y


def sample_grid(bgr: np.ndarray, ox: float, oy: float, dx: float, dy: float):
    colors = []
    h, w = bgr.shape[:2]
    for r in range(ROWS):
        for c in range(COLS):
            x = int(round(ox + c * dx))
            y = int(round(oy + r * dy))
            if not (5 <= x < w - 5 and 5 <= y < h - 5):
                colors.append((200, 200, 200))
                continue
            patch = bgr[y - 5 : y + 6, x - 5 : x + 6]
            b, g, rr = np.median(patch.reshape(-1, 3), axis=0)
            if g > 180 and rr < 180 and b > 180:
                patch = bgr[y - 2 : y + 3, x - 2 : x + 3]
                b, g, rr = np.median(patch.reshape(-1, 3), axis=0)
            colors.append((int(rr), int(g), int(b)))
    return colors


def process(
    path: Path, y0_frac: float = 0.355, pitch: tuple[float, float] | None = None
):
    bgr = cv2.imread(str(path))
    assert bgr is not None, path
    h, w = bgr.shape[:2]
    x0, x1 = int(w * 0.68), int(w * 0.905)
    y0, y1 = int(h * y0_frac), int(h * 0.92)
    roi = bgr[y0:y1, x0:x1]
    SCRATCH.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(SCRATCH / f"_roi_{path.stem}.png"), roi)

    cells = detect_cells(roi)
    print(f"{path.name}: detected {len(cells)} cells")
    ox_r, oy_r, dx, dy = grid_from_cells(cells)
    if pitch is not None:
        dx, dy = pitch
        pts = np.array(cells)
        top_y = pts[:, 1].min()
        top = pts[np.abs(pts[:, 1] - top_y) < dy * 0.45]
        origin = top[np.argmin(top[:, 0])]
        ox_r, oy_r = float(origin[0]), float(origin[1])
    ox, oy = x0 + ox_r, y0 + oy_r
    print(f"  origin=({ox:.1f},{oy:.1f}) pitch=({dx:.1f},{dy:.1f})")

    colors = sample_grid(bgr, ox, oy, dx, dy)

    vis = bgr.copy()
    for i in range(len(colors)):
        row, col = divmod(i, COLS)
        x = int(round(ox + col * dx))
        y = int(round(oy + row * dy))
        cv2.circle(vis, (x, y), 8, (0, 255, 255), 2)
        cv2.putText(vis, str(i + 1), (x - 10, y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    cv2.imwrite(str(SCRATCH / f"_marked_{path.stem}.png"), vis[:, x0:x1])

    strip = np.zeros((90, 52 * len(colors), 3), np.uint8)
    for i, (r, g, b) in enumerate(colors):
        strip[:, i * 52 : (i + 1) * 52] = (b, g, r)
        cv2.putText(strip, str(i + 1), (i * 52 + 8, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.imwrite(str(SCRATCH / f"_strip_{path.stem}.png"), strip)

    for i, c in enumerate(colors, 1):
        print(f"  {i:2d} #{c[0]:02x}{c[1]:02x}{c[2]:02x} {c}")
    return colors, (dx, dy)


def merge(c1, c2):
    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    best = None
    for start in range(13, 21):
        for off in range(0, 6):
            score, n = 0.0, 0
            for i in range(min(10, len(c2) - off)):
                fi = start - 1 + i
                if fi >= len(c1):
                    break
                score += dist(c1[fi], c2[off + i])
                n += 1
            if n >= 4 and (best is None or score / n < best[0]):
                best = (score / n, start, off, n)
    mean, start, off, n = best  # type: ignore
    print(f"align: second[0+{off}] ≈ color {start}, mean_dist={mean:.2f} (n={n})")
    idx25 = off + (24 - start + 1)
    merged = list(c1) + list(c2[idx25:])
    return merged


def main():
    c1, pitch = process(DATA / "1-24.jpg", y0_frac=0.355)
    c2, _ = process(DATA / "16-40.jpg", y0_frac=0.355, pitch=pitch)
    merged = merge(c1, c2)

    strip = np.zeros((90, 52 * len(merged), 3), np.uint8)
    for i, (r, g, b) in enumerate(merged):
        strip[:, i * 52 : (i + 1) * 52] = (b, g, r)
        cv2.putText(strip, str(i + 1), (i * 52 + 6, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    cv2.imwrite(str(SCRATCH / "_strip_merged.png"), strip)

    print(f"=== MERGED {len(merged)} ===")
    for i, c in enumerate(merged, 1):
        print(f"{i:2d} #{c[0]:02x}{c[1]:02x}{c[2]:02x} {c}")

    payload = {
        "source": ["1-24.jpg", "16-40.jpg"],
        "columns": 4,
        "total": len(merged),
        "colors": [
            {"index": i, "rgb": list(c), "hex": f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"}
            for i, c in enumerate(merged, 1)
        ],
    }
    (DATA / "palette_from_game.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote data/palette_from_game.json")


if __name__ == "__main__":
    main()
