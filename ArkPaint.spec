# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成带品牌图标的 ArkPaint.exe。"""

from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

datas = []
assets = root / "assets"
if assets.exists():
    datas.append((str(assets), "assets"))

# 若项目内带有 platform-tools，一并打进包，降低用户门槛
for name in ("tools", "platform-tools"):
    folder = root / name
    if folder.exists():
        datas.append((str(folder), name))

# Windows exe 图标：由 logo PNG 生成多尺寸 ICO
icon_path = None
logo_png = root / "assets" / "logo" / "ArkPaint.png"
logo_ico = root / "assets" / "logo" / "ArkPaint.ico"
if logo_png.is_file():
    try:
        from PIL import Image

        img = Image.open(logo_png).convert("RGBA")
        # 方形裁切，避免非方图拉伸变形
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        # 像素风：最近邻缩放，保持块感
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        variants = [
            img.resize(s, Image.Resampling.NEAREST) for s in sizes
        ]
        variants[0].save(
            logo_ico,
            format="ICO",
            sizes=sizes,
            append_images=variants[1:],
        )
        icon_path = str(logo_ico)
        print(f"[ArkPaint.spec] icon -> {icon_path}")
    except Exception as exc:  # noqa: BLE001 - 打包时降级为无图标
        print(f"[ArkPaint.spec] 生成 ICO 失败，将不设置 exe 图标: {exc}")

a = Analysis(
    ["main.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "cv2",
        "numpy",
        "PIL",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ArkPaint",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
