# -*- mode: python ; coding: utf-8 -*-
"""siku 桌面 sidecar 的 PyInstaller 描述（onedir，含 torch 系检索运行时）。

由 scripts/build_sidecar.py 驱动；模型权重不在此打包，构建完成后由脚本复制到
siku-sidecar/models/hub（离线缓存布局见 src/siku/sidecar.py）。
"""

a = Analysis(
    ["sidecar_entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # torch/transformers/sentence_transformers 走方法体内延迟导入，需显式点名
    hiddenimports=[
        "sentence_transformers",
        "transformers",
        "torch",
    ],
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
