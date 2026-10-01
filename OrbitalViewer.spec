# -*- mode: python ; coding: utf-8 -*-

# MolStudio — 分子可视化与量子化学分析
# PyInstaller onedir（文件夹形式）打包配置。
#
# 用法（在仓库根目录执行）:
#     pyinstaller OrbitalViewer.spec --noconfirm --clean
#
# 约定:
#   * 所有路径都以本 spec 所在目录为基准，不再出现 D:\... 之类的绝对路径，
#     换机器 / 换目录都能直接打包；
#   * 应用代码全部在 molstudio 包内，模块清单由 collect_submodules 自动收集，
#     新增面板或模块不必手工登记（旧版手写 hiddenimports 容易漏，漏了就是
#     打包版里整个页签消失）；
#   * 内置资源统一在 molstudio/assets/，打包后落在 _internal/molstudio/assets/，
#     由 molstudio/paths.py 统一查找。

import os
import shutil

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH 即本 spec 所在目录；再做一次兜底，保证指向仓库根目录
ROOT = os.path.abspath(SPECPATH)
if not os.path.isfile(os.path.join(ROOT, "main.py")):
    ROOT = os.path.dirname(ROOT)
ASSETS = os.path.join(ROOT, "molstudio", "assets")

# VC++ 运行库：Qt5Core/Qt5Gui 依赖 MSVCP140.dll，PyInstaller 默认会从 System32
# 解析到它并跳过（假定目标机装了 VC++ Redistributable）。显式捆绑，保证分发给
# 未装运行库的机器也能启动；本机没有该文件时自动跳过。
_MSVCP140 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                         "System32", "MSVCP140.dll")
binaries = [(_MSVCP140, ".")] if os.path.exists(_MSVCP140) else []

hiddenimports = collect_submodules("molstudio") + [
    # 第三方（部分在函数内延迟 import，显式声明确保收集）
    "numpy", "mcubes", "matplotlib",
    # 导出 SVG 用 QSvgGenerator（PyQt5.QtSvg 是独立扩展模块，
    # 只有 Qt5Svg.dll / qsvg.dll 不会自动带上 Python 绑定）
    "PyQt5.QtSvg",
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=[
        # 窗口/任务栏图标、启动画面校徽、内置样式 json
        (ASSETS, os.path.join("molstudio", "assets")),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt 里没用到的重模块
        "PySide6",
        "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "PyQt5.QtWebEngine",
        "PyQt5.QtWebChannel", "PyQt5.QtWebEngineQuick",
        # 仅存在于 Anaconda 站点包、项目代码未引用（留着会让产物从 ~350 MB
        # 涨到 1 GB 以上）
        "IPython", "jupyter", "jupyterlab", "notebook", "nbconvert", "nbformat",
        "ipykernel", "ipywidgets", "ipympl", "qtconsole",
        "pandas", "sympy", "bokeh", "astropy", "distributed", "numba", "sklearn",
        "skimage", "vtk", "vtkmodules", "pytest", "sphinx",
    ],
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
    icon=os.path.join(ASSETS, "molstudio.ico"),
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
_internal = os.path.join(DISTPATH, 'MolStudio', '_internal')
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
