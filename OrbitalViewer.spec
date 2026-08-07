# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[r'D:\OrbitalViewer 5.3'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'main_window', 'i18n', 'theme', 'dialogs', 'fchk_parser', 'workers',
        'orbital_viewer_v53', 'orbital_viewer_lib',
        'molcanvas', 'widgets', 'cub_canvas', 'cub_viewer', 'glsl_shaders',
        'marching_cubes', 'esp_viewer', 'orbital_gl_viewer', 'orbital_gl_widget',
        'color_wheel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
               'PyQt5.QtWebEngine', 'PyQt5.QtWebChannel', 'PyQt5.QtWebEngineQuick'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OrbitalViewer',
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
    icon=r'C:\Users\Administrator\Pictures\OV2.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OrbitalViewer',
)
