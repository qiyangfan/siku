# -*- mode: python ; coding: utf-8 -*-
"""siku 桌面 sidecar 的 PyInstaller 描述（onedir，BYOK 瘦身版，无模型运行时）。

由 scripts/build_sidecar.py 驱动；ADR-0009 后内核不含 torch 系依赖，也无需
hiddenimports 点名——全部依赖走常规静态分析即可收集。
"""

a = Analysis(
    ["sidecar_entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="siku-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="siku-sidecar",
)
