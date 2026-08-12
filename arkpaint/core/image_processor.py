"""图片转 24×24 像素并映射到游戏色盘。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from arkpaint.config import GRID_SIZE
from arkpaint.core.palette import PaletteColor, palette_to_rgb_list


def load_image(path: str | Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    # 透明底合成到白底，避免透明像素干扰量化
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, img).convert("RGB")


def resize_to_grid(img: Image.Image, size: int = GRID_SIZE) -> Image.Image:
    """缩放到 size×size，使用平均采样保持整体色块感。"""
    return img.resize((size, size), Image.Resampling.BOX)


def _color_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # 简单欧氏距离；后续可换成感知加权
    diff = a.astype(np.float32) - b.astype(np.float32)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def quantize_to_palette(
    img: Image.Image,
    palette: list[PaletteColor],
) -> np.ndarray:
    """将 RGB 图映射为色盘编号矩阵（1-based），形状 (H, W)。"""
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    h, w, _ = arr.shape
    flat = arr.reshape(-1, 3)
    palette_rgb = np.asarray(palette_to_rgb_list(palette), dtype=np.uint8)

    # (N, 1, 3) vs (1, P, 3)
    dists = _color_distance(flat[:, None, :], palette_rgb[None, :, :])
    indices = np.argmin(dists, axis=1) + 1  # 1-based
    return indices.reshape(h, w).astype(np.int32)


def pil_to_grid(
    src: Image.Image,
    palette: list[PaletteColor],
    size: int = GRID_SIZE,
) -> tuple[np.ndarray, Image.Image]:
    """PIL 图 → (色号矩阵, 量化预览 RGB 图)。"""
    if src.mode == "RGBA":
        background = Image.new("RGBA", src.size, (255, 255, 255, 255))
        src = Image.alpha_composite(background, src).convert("RGB")
    elif src.mode != "RGB":
        src = src.convert("RGB")
    small = resize_to_grid(src, size)
    indices = quantize_to_palette(small, palette)
    preview = indices_to_image(indices, palette)
    return indices, preview


def image_to_grid(
    path: str | Path,
    palette: list[PaletteColor],
    size: int = GRID_SIZE,
) -> tuple[np.ndarray, Image.Image]:
    """导入图片 → (色号矩阵, 预览 RGB 图)。"""
    return pil_to_grid(load_image(path), palette, size)


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
