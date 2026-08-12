"""图片转 24×24 像素并映射到游戏色盘（固定约 40 色）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from arkpaint.config import GRID_SIZE
from arkpaint.core.palette import PaletteColor, palette_to_rgb_list

# —— 转换算法（均只使用传入色盘，不会发明新色）——
ALG_RGB = "rgb"
ALG_LAB = "lab"
ALG_DITHER = "dither"
DEFAULT_PIXEL_ALGORITHM = ALG_RGB

# (id, 短名称, 说明)
PIXEL_ALGORITHMS: tuple[tuple[str, str, str], ...] = (
    (
        ALG_RGB,
        "标准 · RGB最近邻",
        "区域平均缩小后，按 RGB 距离贴到最近游戏色。色块干净，适合图标、平涂、高对比。",
    ),
    (
        ALG_LAB,
        "感知 · Lab色差",
        "同样缩小，但用 Lab 感知色差选色。肤色、灰阶、相近红通常更准。",
    ),
    (
        ALG_DITHER,
        "抖动 · Floyd–Steinberg",
        "误差扩散抖动，用现有 40 色模拟中间色。照片/渐变更有层次，24×24 会略噪。",
    ),
)

_ALG_IDS = {item[0] for item in PIXEL_ALGORITHMS}


def normalize_algorithm(algorithm: str | None) -> str:
    if algorithm in _ALG_IDS:
        return algorithm  # type: ignore[return-value]
    return DEFAULT_PIXEL_ALGORITHM


def algorithm_label(algorithm: str | None) -> str:
    alg = normalize_algorithm(algorithm)
    for aid, name, _hint in PIXEL_ALGORITHMS:
        if aid == alg:
            return name
    return PIXEL_ALGORITHMS[0][1]


def load_image(path: str | Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    # 透明底合成到白底，避免透明像素干扰量化
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, img).convert("RGB")


def resize_to_grid(img: Image.Image, size: int = GRID_SIZE) -> Image.Image:
    """缩放到 size×size，使用平均采样保持整体色块感。"""
    return img.resize((size, size), Image.Resampling.BOX)


def _color_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a.astype(np.float32) - b.astype(np.float32)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def rgb_uint8_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8 → CIE Lab（D65），形状与输入一致。"""
    rgb = np.asarray(rgb, dtype=np.uint8)
    single = rgb.ndim == 1
    if single:
        rgb = rgb.reshape(1, 3)

    x = rgb.astype(np.float64) / 255.0
    lin = np.empty_like(x)
    mask = x <= 0.04045
    lin[mask] = x[mask] / 12.92
    lin[~mask] = ((x[~mask] + 0.055) / 1.055) ** 2.4

    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    X = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    Y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    Z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    # D65 白点
    xn, yn, zn = 0.95047, 1.00000, 1.08883
    delta = 6.0 / 29.0
    delta3 = delta**3

    def _f(t: np.ndarray) -> np.ndarray:
        out = np.empty_like(t)
        m = t > delta3
        out[m] = np.cbrt(t[m])
        out[~m] = t[~m] / (3.0 * delta * delta) + 4.0 / 29.0
        return out

    fx, fy, fz = _f(X / xn), _f(Y / yn), _f(Z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_ = 200.0 * (fy - fz)
    out = np.stack([L, a, b_], axis=-1).astype(np.float32)
    return out[0] if single else out


def _palette_arrays(
    palette: list[PaletteColor],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (RGB uint8, Lab float32, 色号 int32)，顺序与 palette 一致。"""
    rgb = np.asarray(palette_to_rgb_list(palette), dtype=np.uint8)
    lab = rgb_uint8_to_lab(rgb)
    indices = np.asarray([c.index for c in palette], dtype=np.int32)
    return rgb, lab, indices


def quantize_to_palette(
    img: Image.Image,
    palette: list[PaletteColor],
    *,
    space: str = "rgb",
) -> np.ndarray:
    """将 RGB 图映射为色盘编号矩阵（1-based），形状 (H, W)。

    space: ``rgb`` 欧氏距离；``lab`` 为 CIE Lab ΔE76（感知更接近）。
    """
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    h, w, _ = arr.shape
    flat = arr.reshape(-1, 3)
    pal_rgb, pal_lab, pal_indices = _palette_arrays(palette)

    if space == "lab":
        dists = _color_distance(rgb_uint8_to_lab(flat)[:, None, :], pal_lab[None, :, :])
    else:
        dists = _color_distance(flat[:, None, :], pal_rgb[None, :, :])
    chosen = pal_indices[np.argmin(dists, axis=1)]
    return chosen.reshape(h, w)


def quantize_floyd_steinberg(
    img: Image.Image,
    palette: list[PaletteColor],
) -> np.ndarray:
    """Floyd–Steinberg 误差扩散（蛇形扫描），选色用 Lab，误差在 RGB 中扩散。

    每个格子仍只落在传入色盘上，不会产生新颜色。
    """
    src = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w, _ = src.shape
    pal_rgb_u8, pal_lab, pal_indices = _palette_arrays(palette)
    pal_rgb = pal_rgb_u8.astype(np.float32)
    work = src.copy()
    out = np.empty((h, w), dtype=np.int32)

    for y in range(h):
        left_to_right = y % 2 == 0
        xs = range(w) if left_to_right else range(w - 1, -1, -1)
        for x in xs:
            old = work[y, x]
            clip = np.clip(old, 0.0, 255.0)
            pix_lab = rgb_uint8_to_lab(clip.astype(np.uint8))
            k = int(np.argmin(np.sum((pal_lab - pix_lab) ** 2, axis=1)))
            new = pal_rgb[k]
            out[y, x] = pal_indices[k]
            err = old - new
            # * 7/16 ；下一行 3/16  5/16  1/16（随扫描方向镜像）
            if left_to_right:
                if x + 1 < w:
                    work[y, x + 1] += err * (7.0 / 16.0)
                if y + 1 < h:
                    if x > 0:
                        work[y + 1, x - 1] += err * (3.0 / 16.0)
                    work[y + 1, x] += err * (5.0 / 16.0)
                    if x + 1 < w:
                        work[y + 1, x + 1] += err * (1.0 / 16.0)
            else:
                if x - 1 >= 0:
                    work[y, x - 1] += err * (7.0 / 16.0)
                if y + 1 < h:
                    if x + 1 < w:
                        work[y + 1, x + 1] += err * (3.0 / 16.0)
                    work[y + 1, x] += err * (5.0 / 16.0)
                    if x - 1 >= 0:
                        work[y + 1, x - 1] += err * (1.0 / 16.0)
    return out


def pil_to_grid(
    src: Image.Image,
    palette: list[PaletteColor],
    size: int = GRID_SIZE,
    *,
    algorithm: str = DEFAULT_PIXEL_ALGORITHM,
) -> tuple[np.ndarray, Image.Image]:
    """PIL 图 → (色号矩阵, 量化预览 RGB 图)。始终只使用传入色盘。"""
    if src.mode == "RGBA":
        background = Image.new("RGBA", src.size, (255, 255, 255, 255))
        src = Image.alpha_composite(background, src).convert("RGB")
    elif src.mode != "RGB":
        src = src.convert("RGB")
    small = resize_to_grid(src, size)
    alg = normalize_algorithm(algorithm)
    if alg == ALG_DITHER:
        indices = quantize_floyd_steinberg(small, palette)
    elif alg == ALG_LAB:
        indices = quantize_to_palette(small, palette, space="lab")
    else:
        indices = quantize_to_palette(small, palette, space="rgb")
    preview = indices_to_image(indices, palette)
    return indices, preview


def image_to_grid(
    path: str | Path,
    palette: list[PaletteColor],
    size: int = GRID_SIZE,
    *,
    algorithm: str = DEFAULT_PIXEL_ALGORITHM,
) -> tuple[np.ndarray, Image.Image]:
    """导入图片 → (色号矩阵, 预览 RGB 图)。"""
    return pil_to_grid(load_image(path), palette, size, algorithm=algorithm)


def indices_to_image(indices: np.ndarray, palette: list[PaletteColor]) -> Image.Image:
    lookup = {c.index: c.rgb for c in palette}
    h, w = indices.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    for idx, rgb in lookup.items():
        mask = indices == idx
        out[mask] = rgb
    # 未匹配编号填白
    unknown = ~np.isin(indices, list(lookup.keys()))
    out[unknown] = (255, 255, 255)
    return Image.fromarray(out, mode="RGB")


def blank_grid(fill_index: int = 4) -> np.ndarray:
    """默认填白色（游戏色盘第 4 号）。"""
    return np.full((GRID_SIZE, GRID_SIZE), fill_index, dtype=np.int32)
