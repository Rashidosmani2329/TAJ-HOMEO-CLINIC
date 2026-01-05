# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['homeo_patient_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('patients.csv', '.'),
        ('visits.csv', '.'),
        ('medicines.csv', '.'),
        ('invoices.csv', '.'),
        ('suppliers.csv', '.'),
        ('stock_adjustments.csv', '.'),
        ('shifts.csv', '.'),
        ('clinics.json', '.'),
        ('order_list.csv', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TajHomeoApp',
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
