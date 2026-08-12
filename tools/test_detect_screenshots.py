"""用 data/1-24.jpg、data/16-40.jpg 测试画布/色板识别，结果写入 data/detect_test/。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arkpaint.core.auto_calibrate import (  # noqa: E402
    _palette_roi_bounds,
    auto_calibrate,
    detect_palette_cells,
)
from arkpaint.core.detector import canvas_white_mask, detect_canvas, detect_pindou_screen  # noqa: E402
from arkpaint.core.diagnose import _draw_overlay  # noqa: E402

from arkpaint.config import DETECT_TEST_DIR, ensure_dirs  # noqa: E402

DATA = ROOT / "data"
OUT = DETECT_TEST_DIR
SHOTS = [DATA / "1-24.jpg", DATA / "16-40.jpg"]


def _imread(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"无法读取图片：{path}")
    return img


def _imwrite(path: Path, bgr: np.ndarray) -> None:
    ok, buf = cv2.imencode(path.suffix, bgr)
    if not ok:
        raise RuntimeError(f"无法编码：{path}")
    path.write_bytes(buf.tobytes())


def analyze_one(path: Path) -> dict:
    bgr = _imread(path)
    h, w = bgr.shape[:2]
    stem = path.stem

    mask = canvas_white_mask(bgr)
    white_ratio = float(np.count_nonzero(mask)) / max(1, mask.size)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs = []
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 5000:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        blobs.append(
            {
                "x": int(x),
                "y": int(y),
                "w": int(bw),
                "h": int(bh),
                "area": int(area),
                "ratio": round(bw / max(bh, 1), 4),
            }
        )
    blobs.sort(key=lambda b: b["area"], reverse=True)
    canvas = detect_canvas(bgr)
    detected = detect_pindou_screen(bgr, min_confidence=0.72)
    calib = auto_calibrate(bgr)

    palette_roi = None
    cells: list[tuple[float, float]] = []
    if canvas is not None:
        palette_roi = _palette_roi_bounds(bgr, canvas)
        x0, y0, x1, y1 = palette_roi
        roi = bgr[y0:y1, x0:x1]
        cells = detect_palette_cells(roi) if roi.size else []

    overlay = _draw_overlay(bgr, canvas=canvas, palette_roi=palette_roi, cells=cells)
    _imwrite(OUT / f"{stem}_overlay.png", overlay)
    _imwrite(OUT / f"{stem}_mask.png", mask)
    if canvas is not None:
        x, y, cw, ch = canvas
        _imwrite(OUT / f"{stem}_canvas_crop.png", bgr[y : y + ch, x : x + cw])
    if palette_roi is not None:
        x0, y0, x1, y1 = palette_roi
        _imwrite(OUT / f"{stem}_palette_roi.png", bgr[y0:y1, x0:x1])

    record = {
        "file": path.name,
        "size": [w, h],
        "white_ratio": round(white_ratio, 4),
        "white_blobs_top5": blobs[:5],
        "canvas": None if canvas is None else {
            "x": int(canvas[0]),
            "y": int(canvas[1]),
            "w": int(canvas[2]),
            "h": int(canvas[3]),
            "ratio": round(canvas[2] / max(canvas[3], 1), 4),
        },
        "pindou_ok": detected.ok,
        "pindou_confidence": round(detected.confidence, 4),
        "pindou_message": detected.message,
        "palette_roi": None if palette_roi is None else list(map(int, palette_roi)),
        "palette_cells": len(cells),
        "auto_calibrate_ok": calib.ok,
        "auto_calibrate_message": calib.message,
        "outputs": {
            "overlay": f"{stem}_overlay.png",
            "mask": f"{stem}_mask.png",
            "canvas_crop": f"{stem}_canvas_crop.png" if canvas is not None else None,
            "palette_roi": f"{stem}_palette_roi.png" if palette_roi is not None else None,
        },
    }
    return record


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [p for p in SHOTS if not p.is_file()]
    if missing:
        print("缺少截图：")
        for p in missing:
            print(f"  {p}")
        return 1

    results = [analyze_one(p) for p in SHOTS]
    report = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "shots": results,
    }
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "ArkPaint 画布/色板识别测试",
        f"时间：{report['time']}",
        f"素材：{', '.join(p.name for p in SHOTS)}",
        "",
    ]
    all_ok = True
    for item in results:
        canvas_ok = item["canvas"] is not None
        pal_ok = item["palette_cells"] >= 8
        ok = canvas_ok and pal_ok and item["auto_calibrate_ok"]
        all_ok = all_ok and ok
        mark = "通过" if ok else "未完全通过"
        lines.append(f"=== {item['file']}（{item['size'][0]}×{item['size'][1]}）{mark} ===")
        if item["canvas"]:
            c = item["canvas"]
            lines.append(f"  画布：[OK] {c['w']}x{c['h']} @ ({c['x']},{c['y']})  宽高比 {c['ratio']}")
        else:
            lines.append("  画布：[FAIL] 未找到")
        lines.append(
            f"  拼豆页：[{'OK' if item['pindou_ok'] else 'FAIL'}] "
            f"置信度 {item['pindou_confidence']:.2f} — {item['pindou_message']}"
        )
        lines.append(f"  白块占比：{item['white_ratio']:.1%}")
        if item.get("white_blobs_top5"):
            lines.append("  最大白块（当前算法只接受宽高比 0.85–1.15 的正方形）：")
            for i, b in enumerate(item["white_blobs_top5"], 1):
                lines.append(
                    f"    #{i} {b['w']}x{b['h']} @ ({b['x']},{b['y']}) "
                    f"ratio={b['ratio']} area={b['area']}"
                )
        lines.append(f"  色块数：{item['palette_cells']}")
        lines.append(
            f"  自动校准：[{'OK' if item['auto_calibrate_ok'] else 'FAIL'}] {item['auto_calibrate_message']}"
        )
        lines.append(f"  标注图：{item['outputs']['overlay']}")
        lines.append("")

    lines.append("结论：" + ("两张截图均识别到画布与色板。" if all_ok else "至少一张未完全识别，请看 overlay / palette_roi。"))
    text = "\n".join(lines) + "\n"
    (OUT / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"结果目录：{OUT}")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
