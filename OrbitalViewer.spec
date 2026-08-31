# -*- mode: python ; coding: utf-8 -*-

# MolStudio — 分子可视化与量子化学分析
# PyInstaller onedir（文件夹形式）打包配置。
# 用法: pyinstaller OrbitalViewer.spec

import os
import shutil

a = Analysis(
    ['main.py'],
    pathex=[r'D:\OrbitalViewer 5.3'],
    binaries=[
        # VC++ 运行库：Qt5Core/Qt5Gui 依赖 MSVCP140.dll，而 PyInstaller 只会
        # 从 System32 解析到它并默认跳过（假定目标机装有 VC++ Redistributable）。
        # 显式捆绑，保证分发给未装运行库的机器也能启动。
        (r'C:\Windows\System32\MSVCP140.dll', '.'),
    ],
    datas=[
        # 窗口/任务栏图标 + 启动画面校徽（main.py 运行时从 exe 同目录加载）
        ('molstudio.ico', '.'),
        ('校徽.png', '.'),
    ],
    hiddenimports=[
        # 主程序依赖
        'main_window', 'i18n', 'theme', 'dialogs', 'workers',
        'fchk_parser', 'fchk_orbital', 'file_dialogs',
        'molcanvas', 'widgets', 'marching_cubes', 'glsl_shaders',
        # 第三方（部分为延迟 import，显式声明确保收集）
        'numpy', 'mcubes', 'matplotlib',
        # ovcanvas 渲染包（旧 cub_canvas/cub_viewer/color_wheel 已并入）
        'ovcanvas', 'ovcanvas._panel', 'ovcanvas._glwidget',
        'ovcanvas._molviewer_style', 'ovcanvas._colorwheel',
        # 各分析面板
        'esp_panel', 'esp_viewer', 'charge_viewer', 'charge_bond_panel',
        'nbo_viewer', 'nbo_parser', 'igmh_panel',
        'aim_panel', 'aim_visualize',
        'etsnocv_panel', 'etsnocv', 'etsnocv.viewer', 'etsnocv.molcanvas',
        # MPP 分子平面性参数分析（移植自 mpp_auto_qt.py）
        'mpp_panel',
        # 旧版独立查看器（保留兼容）
        'orbital_viewer_v53', 'orbital_viewer_lib',
        'orbital_gl_viewer', 'orbital_gl_widget',
        'cubviewer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
               'PyQt5.QtWebEngine', 'PyQt5.QtWebChannel', 'PyQt5.QtWebEngineQuick',
               # 以下仅存在于站点包、项目代码未引用，排除以减小体积
               'IPython', 'pandas', 'sympy', 'bokeh', 'astropy',
               'distributed', 'numba', 'sklearn'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ── 360 安全卫士按文件名拦截写入的 DLL ──
# 本机 360 会拦截 "d3dcompiler_47.dll"、"ucrtbase.dll" 等已知高危 DLL 的
# 直接写入（即使覆盖已存在文件），导致 COLLECT 阶段 PermissionError。
# 处理：先从 a.binaries 剔除，COLLECT 完成后用「写临时名 → os.rename」
# 技巧绕过拦截放回 _internal（rename 不受该规则限制）。
_BLOCKED_DLLS = {'ucrtbase.dll', 'd3dcompiler_47.dll'}
_blocked_entries = []
_kept = []
for b in a.binaries:
    name = b[0].replace('\\', '/').rsplit('/', 1)[-1]
    if name in _BLOCKED_DLLS:
        _blocked_entries.append(b)
    else:
        _kept.append(b)
a.binaries = _kept

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MolStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    upx=False,
    icon=r'D:\OrbitalViewer 5.3\molstudio.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MolStudio',
)

# ── 事后放回被拦截的 DLL（写 .tmp 再改名，绕过 360 按名拦截） ──
_internal = os.path.join(r'D:\OrbitalViewer 5.3\dist', 'MolStudio', '_internal')
os.makedirs(_internal, exist_ok=True)
for _dest, _src, _tc in _blocked_entries:
    _name = _dest.replace('\\', '/').rsplit('/', 1)[-1]
    if not os.path.exists(_src):
        print(f"[spec] 源缺失，跳过 {_name}: {_src}")
        continue
    _final = os.path.join(_internal, _name)
    if os.path.exists(_final):
        try:
            os.remove(_final)
        except OSError:
            pass
    _tmp = _final + '.tmp'
    try:
        shutil.copyfile(_src, _tmp)
        os.rename(_tmp, _final)
        print(f"[spec] 已放回 {_name}")
    except OSError as e:
        print(f"[spec] 放回 {_name} 失败: {e}")
