# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成单文件 ArkPaint.exe。"""

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
)
