"""默认颜料色盘（与游戏右侧「颜料」栏顺序一致）。

编号从 1 开始，按左→右、上→下。
色值由 data/1-24.jpg + data/16-40.jpg 采样固化（见 tools/sample_palette_from_shots.py）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaletteColor:
    index: int  # 1-based
    name: str
    rgb: tuple[int, int, int]


def _hex(code: str) -> tuple[int, int, int]:
    h = code.removeprefix("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# 游戏顺序 1..40（截图校准结果）
_HEX_COLORS: list[str] = [
    "#222222",  # 1 黑
    "#b4b4b4",  # 2 灰
    "#eae7de",  # 3 浅灰米
    "#ffffff",  # 4 白
    "#d32f36",  # 5 红
    "#9d0a00",  # 6 深红
    "#d60b4a",  # 7 玫红
    "#e6968d",  # 8 浅粉
    "#ff9875",  # 9 珊瑚
    "#f7d0bf",  # 10 肉色
    "#fcefe9",  # 11 粉白
    "#fcf6e8",  # 12 米白
    "#dcd2c8",  # 13 浅褐灰
    "#e2ceab",  # 14 杏色
    "#d56422",  # 15 橙棕
    "#d48c42",  # 16 赭石
    "#f29900",  # 17 橙
    "#f8c933",  # 18 金黄
    "#fce599",  # 19 浅黄
    "#b3b47a",  # 20 橄榄灰
    "#c1da72",  # 21 黄绿
    "#6c6e00",  # 22 暗橄榄
    "#b19156",  # 23 棕黄
    "#a38970",  # 24 灰棕
    "#aa9228",  # 25 芥末
    "#3f2b12",  # 26 深棕
    "#74491f",  # 27 褐
    "#534658",  # 28 紫灰
    "#2a2446",  # 29 深蓝紫
    "#394599",  # 30 宝蓝
    "#59459c",  # 31 紫
    "#baa3d7",  # 32 薰衣草
    "#b6bce0",  # 33 浅蓝紫
    "#a9acbf",  # 34 钢灰蓝
    "#63abb9",  # 35 青蓝
    "#b4d2dc",  # 36 淡青
    "#90d8e6",  # 37 天蓝
    "#48aea0",  # 38 青绿
    "#b5d3c7",  # 39 薄荷绿
    "#273864",  # 40 午夜
]

DEFAULT_PALETTE: list[PaletteColor] = [
    PaletteColor(i, code.upper(), _hex(code)) for i, code in enumerate(_HEX_COLORS, start=1)
]

# 纯白：空白画布 / 「跳过白色」
WHITE_INDEX = 4


def palette_to_rgb_list(palette: list[PaletteColor]) -> list[tuple[int, int, int]]:
    return [c.rgb for c in palette]


def rebuild_palette(
    rgbs: list[tuple[int, int, int]],
    names: list[str] | None = None,
) -> list[PaletteColor]:
    result: list[PaletteColor] = []
    for i, rgb in enumerate(rgbs, start=1):
        name = names[i - 1] if names and i - 1 < len(names) else f"色{i}"
        result.append(
            PaletteColor(index=i, name=name, rgb=(int(rgb[0]), int(rgb[1]), int(rgb[2])))
        )
    return result


def find_white_index(palette: list[PaletteColor], fallback: int = WHITE_INDEX) -> int:
    """找最接近纯白的色号；没有则用 fallback。"""
    if not palette:
        return fallback
    best = min(
        palette,
        key=lambda c: (255 - c.rgb[0]) ** 2 + (255 - c.rgb[1]) ** 2 + (255 - c.rgb[2]) ** 2,
    )
    return best.index
