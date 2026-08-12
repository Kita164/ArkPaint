"""识别诊断：逐步检查 ADB / 截图 / 画布 / 色板，并保存调试图。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from arkpaint.config import DEBUG_DIR, REFERENCE_IMAGE, ensure_dirs
from arkpaint.core.adb import AdbController, AdbError
from arkpaint.core.auto_calibrate import (
    _palette_roi_bounds,
    auto_calibrate,
    detect_palette_cells,
)
from arkpaint.core.calibration import CalibrationData
from arkpaint.core.detector import canvas_white_mask, detect_canvas, detect_pindou_screen


@dataclass
class DiagnoseStep:
    name: str
    ok: bool | None  # True 通过 / False 失败 / None 跳过
    detail: str


@dataclass
class DiagnoseReport:
    ok: bool
    summary: str
    steps: list[DiagnoseStep] = field(default_factory=list)
    debug_dir: Path = DEBUG_DIR
    screenshot_path: Path | None = None
    overlay_path: Path | None = None
    mask_path: Path | None = None
    report_path: Path | None = None
    calibration: CalibrationData | None = None

    def text(self) -> str:
        lines = [self.summary, ""]
        for step in self.steps:
            if step.ok is True:
                mark = "✓"
            elif step.ok is False:
                mark = "✗"
            else:
                mark = "—"
            lines.append(f"{mark} {step.name}：{step.detail}")
        lines.append("")
        lines.append(f"调试目录：{self.debug_dir}")
        if self.screenshot_path:
            lines.append(f"  截图：{self.screenshot_path.name}")
        if self.mask_path:
            lines.append(f"  白块蒙版：{self.mask_path.name}")
        if self.overlay_path:
            lines.append(f"  标注图：{self.overlay_path.name}")
        if self.report_path:
            lines.append(f"  报告：{self.report_path.name}")
        return "\n".join(lines)


def _hint_for_screenshot(bgr: np.ndarray, white_ratio: float) -> str:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    h, w = gray.shape
    if mean < 18:
        return "画面几乎全黑，可能截到了熄屏/错误设备"
    if mean < 40 and white_ratio < 0.02:
        return "画面偏暗且几乎没有白块，多半不在拼豆编辑页"
    if white_ratio < 0.03:
        return "白色区域太少，请打开拼豆编辑页并让中央画布完整可见"
    if white_ratio > 0.45:
        return "白块很多但不是正方形画布，可能开了别的界面或系统桌面"
    if w < 400 or h < 400:
        return f"分辨率偏低（{w}×{h}），识别可能不稳定"
    return ""


def _draw_overlay(
    bgr: np.ndarray,
    *,
    canvas: tuple[int, int, int, int] | None,
    palette_roi: tuple[int, int, int, int] | None,
    cells: list[tuple[float, float]] | None,
) -> np.ndarray:
    vis = bgr.copy()
    h, w = vis.shape[:2]
    cv2.line(vis, (w // 2, 0), (w // 2, h), (80, 80, 80), 1)
    cv2.line(vis, (0, h // 2), (w, h // 2), (80, 80, 80), 1)
    if canvas is not None:
        x, y, cw, ch = canvas
        cv2.rectangle(vis, (x, y), (x + cw, y + ch), (0, 220, 0), 3)
        cv2.putText(
            vis,
            f"canvas {cw}x{ch}",
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 220, 0),
            2,
            cv2.LINE_AA,
        )
    if palette_roi is not None:
        x0, y0, x1, y1 = palette_roi
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 200, 255), 2)
        cv2.putText(
            vis,
            "palette ROI",
            (x0, max(20, y0 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 200, 255),
            2,
            cv2.LINE_AA,
        )
        if cells:
            for cx, cy in cells:
                cv2.circle(vis, (int(x0 + cx), int(y0 + cy)), 6, (0, 200, 255), 2)
    return vis


def run_diagnose(
    adb: AdbController,
    *,
    min_confidence: float = 0.72,
    bgr: np.ndarray | None = None,
) -> DiagnoseReport:
    """逐步诊断；始终尝试落盘截图/蒙版/标注/报告。"""
    ensure_dirs()
    debug_dir = DEBUG_DIR
    debug_dir.mkdir(parents=True, exist_ok=True)
    steps: list[DiagnoseStep] = []
    shot: np.ndarray | None = None
    canvas = None
    palette_roi = None
    cells: list[tuple[float, float]] = []
    calibration: CalibrationData | None = None
    screenshot_path = debug_dir / "screencap.png"
    mask_path = debug_dir / "mask.png"
    overlay_path = debug_dir / "overlay.png"
    report_path = debug_dir / "report.txt"

    # 1. ADB
    ready = adb.is_ready()
    serial = adb.serial or "（未选定设备）"
    steps.append(
        DiagnoseStep(
            "ADB 连接",
            ready,
            f"设备 {serial}；adb={adb.adb_path}" if ready else f"未就绪；adb={adb.adb_path}",
        )
    )
    if not ready:
        report = DiagnoseReport(
            ok=False,
            summary="ADB 未连接，无法截取模拟器画面。",
            steps=steps,
            debug_dir=debug_dir,
            report_path=report_path,
        )
        report_path.write_text(_report_file_text(report), encoding="utf-8")
        return report

    # 2. 截图
    try:
        shot = bgr if bgr is not None else adb.screencap()
    except AdbError as exc:
        steps.append(DiagnoseStep("截取屏幕", False, str(exc)))
        report = DiagnoseReport(
            ok=False,
            summary="截图失败。ADB 已连上，但无法拿到模拟器画面。",
            steps=steps,
            debug_dir=debug_dir,
            report_path=report_path,
        )
        report_path.write_text(_report_file_text(report), encoding="utf-8")
        return report

    h, w = shot.shape[:2]
    gray_mean = float(cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY).mean())
    cv2.imwrite(str(screenshot_path), shot)
    steps.append(
        DiagnoseStep(
            "截取屏幕",
            True,
            f"{w}×{h}，平均亮度 {gray_mean:.0f}（0–255）"
            + (
                f"；方式 {adb.screencap_method.value}"
                if adb.screencap_method is not None
                else ""
            ),
        )
    )

    # 3. 白块蒙版
    mask = canvas_white_mask(shot)
    white_ratio = float(np.count_nonzero(mask)) / max(1, mask.size)
    cv2.imwrite(str(mask_path), mask)
    hint = _hint_for_screenshot(shot, white_ratio)
    mask_ok = white_ratio >= 0.03
    mask_detail = f"偏白像素占比 {white_ratio:.1%}"
    if hint:
        mask_detail += f"；{hint}"
    steps.append(DiagnoseStep("白块蒙版", mask_ok, mask_detail))

    # 4. 画布
    canvas = detect_canvas(shot)
    if canvas is None:
        steps.append(
            DiagnoseStep(
                "中央画布",
                False,
                "未找到接近正方形的白色画布。请打开拼豆编辑页，保证中央网格完整可见。",
            )
        )
    else:
        x, y, cw, ch = canvas
        steps.append(
            DiagnoseStep("中央画布", True, f"{cw}×{ch} @ ({x},{y})")
        )

    # 5. 拼豆页综合识别
    detected = detect_pindou_screen(shot, min_confidence=min_confidence)
    ref_note = "有参考图" if REFERENCE_IMAGE.is_file() else "无参考图（仅结构检测）"
    steps.append(
        DiagnoseStep(
            "拼豆页判断",
            detected.ok,
            f"{detected.message}；置信度 {detected.confidence:.2f}（阈值 {min_confidence:.2f}，{ref_note}）",
        )
    )

    # 6. 色板 + 自动校准
    if canvas is None:
        steps.append(DiagnoseStep("颜料栏", None, "无画布，已跳过"))
        steps.append(DiagnoseStep("自动校准", False, "因未找到画布而失败"))
    else:
        palette_roi = _palette_roi_bounds(shot, canvas)
        x0, y0, x1, y1 = palette_roi
        roi = shot[y0:y1, x0:x1]
        cells = detect_palette_cells(roi) if roi.size else []
        pal_ok = len(cells) >= 8
        steps.append(
            DiagnoseStep(
                "颜料栏",
                pal_ok,
                f"检测到 {len(cells)} 个色块" + ("" if pal_ok else "（偏少，请把色板滚到顶部）"),
            )
        )
        calib_result = auto_calibrate(shot)
        steps.append(
            DiagnoseStep("自动校准", calib_result.ok, calib_result.message)
        )
        if calib_result.ok:
            calibration = calib_result.calibration

    overlay = _draw_overlay(shot, canvas=canvas, palette_roi=palette_roi, cells=cells)
    cv2.imwrite(str(overlay_path), overlay)

    ok = bool(detected.ok and calibration is not None)
    if ok:
        summary = "诊断通过：已识别画布与颜料栏，可以开始绘图。"
    elif canvas is None:
        summary = "诊断未通过：卡在「中央画布」——模拟器画面里没找到拼豆网格。"
    elif not detected.ok:
        summary = "诊断未通过：找到了类似画布，但拼豆页置信度不足。"
    else:
        summary = "诊断未通过：画布有了，但颜料栏/自动校准失败。"

    report = DiagnoseReport(
        ok=ok,
        summary=summary,
        steps=steps,
        debug_dir=debug_dir,
        screenshot_path=screenshot_path,
        overlay_path=overlay_path,
        mask_path=mask_path,
        report_path=report_path,
        calibration=calibration,
    )
    report_path.write_text(_report_file_text(report), encoding="utf-8")
    return report


def _report_file_text(report: DiagnoseReport) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"ArkPaint 识别诊断\n时间：{now}\n\n{report.text()}\n"
