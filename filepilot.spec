# -*- mode: python ; coding: utf-8 -*-
# Сборка: python -m PyInstaller --noconfirm --clean filepilot.spec
import os

from PyInstaller.utils.hooks import collect_submodules

icon = os.path.join("assets", "icon.ico")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.png", "assets"), ("assets/icon.ico", "assets"), ("CHANGELOG.md", ".")],
    hiddenimports=collect_submodules("pypdf") + collect_submodules("send2trash"),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "PIL", "IPython", "pytest", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FilePilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if os.path.exists(icon) else None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FilePilot")
