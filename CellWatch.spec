# -*- mode: python ; coding: utf-8 -*-
import sys
sys.setrecursionlimit(5000)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Dynamically locate packages to ensure portability across different .venv names and environments
import onnxruntime
import customtkinter

base_tcl = os.path.join(sys.base_prefix, 'tcl')
datas = [
    ('config.yaml', '.'), 
    ('monitor_app/assets', 'monitor_app/assets/'), 
    ('monitor_app/models', 'monitor_app/models/'), 
    (base_tcl, '_tcl_data')
]
datas += collect_data_files('customtkinter')

hiddenimports = [
    'tkinter', 'tkinter.ttk', '_tkinter', 'PIL._tkinter_finder'
]
hiddenimports += collect_submodules('onnxruntime')

a = Analysis(
    ['monitor_app\\main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch.utils.tensorboard', 'tensorboard', 'tensorflow', 'tensorflow_hub', 'tf2onnx'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CellWatch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CellWatch',
)
