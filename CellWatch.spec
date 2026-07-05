# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files

base_tcl = os.path.join(sys.base_prefix, 'tcl')
datas = [
    ('config.yaml', '.'), 
    ('monitor_app/assets', 'monitor_app/assets/'), 
    ('monitor_app/models', 'monitor_app/models/'), 
    (base_tcl, '_tcl_data'),
    ('.venv310/Lib/site-packages/tensorflow', 'tensorflow'),
    ('.venv310/Lib/site-packages/tensorflow_hub', 'tensorflow_hub')
]
datas += collect_data_files('customtkinter')

a = Analysis(
    ['monitor_app\\main.py'],
    pathex=['.venv310\\Lib\\site-packages'],
    binaries=[],
    datas=datas,
    hiddenimports=['tkinter', 'tkinter.ttk', '_tkinter', 'PIL._tkinter_finder'],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch.utils.tensorboard', 'tensorboard', 'tensorflow', 'tensorflow_hub'],
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
    console=False,
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
