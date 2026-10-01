#!/usr/bin/env python3
"""
GXNU MolStudio 分子可视化与量子化学分析工具 — 应用引导模块

用法:
    python main.py                          # 启动 GUI（仓库根目录的薄入口）
    python -m molstudio                     # 等价入口
    python main.py input.fchk --mo h        # 命令行批处理模式
"""

import os
import re
import sys
import glob

# 注意：批处理分支里另有 `paths = backend.load_config()`，这里用别名避免同名遮蔽
from molstudio import paths as _paths
from molstudio.ui.main_window import OrbitalVisApp


# ── 界面风格选择 ─────────────────────────────────────────────────────────
#   --ui clean      → Clean Light 卡片界面（main_window_clean.py）
#   --ui clean2     → Bridge 卡片界面（main_window_clean2.py，xTBridge Lite 风）
#   --ui canvas     → 画布优先界面（main_window_canvas_first.py：图标 rail +
#                     可收起抽屉 + 样式下拉；2026-09-27 新增）
#   --ui classic    → 原来的界面（默认，行为与以前完全一致）
#   环境变量 MOLSTUDIO_UI 可作为默认值（--ui 优先级更高）
#   `python main_window_clean.py` 就是给自己设上 MOLSTUDIO_UI=clean 再走这里。
def _pick_ui():
    val = os.environ.get("MOLSTUDIO_UI", "").strip().lower()
    argv = sys.argv
    if "--ui" in argv:
        i = argv.index("--ui")
        if i + 1 < len(argv):
            val = argv[i + 1].strip().lower()
            del argv[i:i + 2]          # 摘掉，免得干扰批处理模式的 argparse
        else:
            del argv[i]
    return val if val in ("clean", "clean2", "canvas", "classic") else ""


def _make_window(ui):
    """按选择构造主窗口；新界面加载失败时自动回退到经典界面。"""
    if ui == "clean":
        try:
            from molstudio.ui.main_window_clean import MolStudioCleanWindow
            return MolStudioCleanWindow()
        except Exception as e:
            import traceback
            print(f"[ui] 新界面加载失败，回退到经典界面：{e}")
            traceback.print_exc()
    if ui == "clean2":
        try:
            from molstudio.ui.main_window_clean2 import MolStudioCleanWindow2
            return MolStudioCleanWindow2()
        except Exception as e:
            import traceback
            print(f"[ui] Bridge 界面加载失败，回退到经典界面：{e}")
            traceback.print_exc()
    if ui == "canvas":
        try:
            from molstudio.ui.main_window_canvas_first import MolStudioCanvasFirstWindow
            return MolStudioCanvasFirstWindow()
        except Exception as e:
            import traceback
            print(f"[ui] 画布优先界面加载失败，回退到经典界面：{e}")
            traceback.print_exc()
    return OrbitalVisApp()


def main():
    _ui = _pick_ui()
    if len(sys.argv) > 1:
        import argparse
        import molstudio.core.fchk_orbital as backend

        p = argparse.ArgumentParser(
            description="GXNU MolStudio v1.0 — Molecular Visualization & Quantum Chemical Analysis")
        p.add_argument("input", help="fchk file or folder")
        p.add_argument("--mo", default="h", help="Orbital (h/l/h-1/number)")
        p.add_argument("--iso", type=float, default=0.05, help="Isosurface threshold")
        p.add_argument("--grid", default="2", help="Grid quality (1/2/3)")
        p.add_argument("--style", default="sob-art",
                       choices=list(backend.STYLES.keys()), help="Render style")
        p.add_argument("--res", default="2000,1500", help="Resolution width,height")
        p.add_argument("--no-render", action="store_true", help="Generate cube only")
        p.add_argument("--out", default=None)
        a = p.parse_args()

        # .fch 与 .fchk 是同一格式（Gaussian 格式化检查点；Multiwfn 也常导出 .fch）
        files = (sorted(glob.glob(os.path.join(a.input, "*.fchk"))
                        + glob.glob(os.path.join(a.input, "*.fch")))
                 if os.path.isdir(a.input) else [a.input])
        if not files:
            print("未找到任何 .fchk / .fch 文件")
            sys.exit(1)
        out = a.out or (os.path.dirname(a.input)
                        if os.path.isfile(a.input) else a.input)
        if not out:
            out = os.getcwd()
        os.makedirs(out, exist_ok=True)

        # 批处理同样读取用户在 GUI ⚙️ 里配置的 exe 路径，而不是硬编码默认值
        paths = backend.load_config()
        multiwfn_exe = paths["multiwfn"]
        vmd_exe = paths["vmd"]
        tachyon_exe = paths["tachyon"]

        w, h = [int(x) for x in re.split(r"[x,]", a.res)]

        for i, f in enumerate(files):
            print(f"[{i+1}/{len(files)}] {os.path.basename(f)}")
            cube = backend.gen_cube(f, orbital=a.mo, grid_quality=int(a.grid),
                                    work_dir=out, multiwfn_exe=multiwfn_exe)
            if cube:
                print(f"  cube: {os.path.basename(cube)}")
                if not a.no_render:
                    png = backend.render_cube_auto(
                        cube, isovalue=a.iso, style_name=a.style,
                        resolution=(w, h), vmd_exe=vmd_exe,
                        tachyon_exe=tachyon_exe)
                    if png:
                        print(f"  png:  {os.path.basename(png)}")
            else:
                print(f"  Failed")
    else:
        from PyQt5.QtWidgets import QApplication, QWidget
        from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, QElapsedTimer, QEasingCurve, QVariantAnimation
        from PyQt5.QtGui import (QColor, QPalette, QSurfaceFormat, QPixmap,
                                 QPainter, QLinearGradient, QFont, QFontMetrics,
                                 QPen)

        # 内嵌 QOpenGLWidget 必须在 QApplication 创建前设置默认 GL 格式，
        # 否则画布拿不到 3.3 Core Profile 上下文。
        _fmt = QSurfaceFormat()
        _fmt.setSamples(0)
        _fmt.setDepthBufferSize(24)
        _fmt.setVersion(3, 3)
        _fmt.setProfile(QSurfaceFormat.CoreProfile)
        QSurfaceFormat.setDefaultFormat(_fmt)

        # 弹窗（QDialog）右上角不显示「?」帮助按钮（PyQt5 默认会带，
        # 须在 QApplication 创建前设置）
        QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

        # ── 临时调试：启动期小窗口/DPI 侦查 ──
        # 已确认：PyInstaller 6.19 默认 manifest 不含 dpiAware 声明（读 exe 资源核实），
        # 进程在 Qt 初始化前是 DPI-unaware，由 Qt 5.15 的 AA_EnableHighDpiScaling 内部
        # 再设为 PerMonitor。故本模拟默认关闭；如需对比「提前 DPI 感知」的影响改 _SIM_DPI。
        _SIM_DPI = False
        if _SIM_DPI:
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass

        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        # 应用级窗口图标：主窗口及所有弹窗默认继承
        _icon_path = _paths.find_asset(
            "OV.png", "molstudio.ico", "gxnu_molstudio.ico", "molstudio_icon_src.png")
        if _icon_path:
            from PyQt5.QtGui import QIcon
            app.setWindowIcon(QIcon(_icon_path))
        # Uniform tooltip background
        tip_pal = app.palette()
        tip_pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
        tip_pal.setColor(QPalette.ToolTipText, QColor("#2C3E50"))
        app.setPalette(tip_pal)

        # ── 调试日志：写文件（exe 是 console=False，print 不可见）──
        import time as _time
        _DBG_LOG = os.path.join(os.path.expanduser("~"), "molstudio_dbg.log")

        def _dbg(msg):
            line = f"[{_time.time():.3f}] {msg}"
            print(line, flush=True)
            try:
                with open(_DBG_LOG, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        # ── 全局异常钩子：windowed 打包无控制台，未捕获异常会静默闪退；
        #    这里改为写调试日志 + 弹错误对话框，方便定位问题 ──
        import traceback as _traceback
        from PyQt5.QtWidgets import QMessageBox as _QMB

        def _gui_excepthook(etype, val, tb):
            msg = "".join(_traceback.format_exception(etype, val, tb))
            _dbg("UNCAUGHT EXCEPTION:\n" + msg)
            try:
                _QMB(_QMB.Critical, "MolStudio 错误",
                     "程序遇到未处理的错误：\n\n" + msg[-3000:]).exec_()
            except Exception:
                pass

        sys.excepthook = _gui_excepthook

        _dbg("=== MolStudio startup debug ===")
        _dbg("QT_QPA_PLATFORM=%r  HIGHDPI=%r" % (
            os.environ.get("QT_QPA_PLATFORM"), os.environ.get("QT_AUTO_SCREEN_SCALE_FACTOR")))
        _dbg("app.dpr=%s AA_EnableHighDpiScaling=%s AA_UseHighDpiPixmaps=%s" % (
            app.devicePixelRatio(),
            app.testAttribute(Qt.AA_EnableHighDpiScaling),
            app.testAttribute(Qt.AA_UseHighDpiPixmaps)))
        try:
            _scr = app.primaryScreen()
            _dbg("screen size=%s avail=%s dpr=%s logicalDpi=%s physicalDpi=%s" % (
                _scr.size(), _scr.availableGeometry(), _scr.devicePixelRatio(),
                _scr.logicalDotsPerInch(), _scr.physicalDotsPerInch()))
        except Exception as _e:
            _dbg("screen info err %s" % _e)
        try:
            import ctypes as _ct
            _v = _ct.c_int(0)
            _ct.windll.shcore.GetProcessDpiAwareness(0, _ct.byref(_v))
            _dbg("GetProcessDpiAwareness=%d" % _v.value)
        except Exception as _e:
            _dbg("GetProcessDpiAwareness err %s" % _e)

        def _make_splash_pixmap():
            """绘制品牌启动画面：白底 + 校徽 + 全英文文案 + 紫色主题。

            排版：顶部色带 → 校徽 → 产品名 → 定位语 → 出品署名 → 版本 →
            加载条 → 状态；字号整体偏小、间距留白充足，视觉干净工整。
            """
            W, H = 560, 380
            pm = QPixmap(W, H)
            pm.fill(Qt.white)

            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)

            def _fit_font(text, size, bold=False):
                """自动缩字号，保证一行内放得下（左右各留 24px，DPI 缩放也稳）。"""
                s = int(size)
                while s >= 7:
                    ff = QFont("Segoe UI", s)
                    ff.setBold(bold)
                    ff.setStyleHint(QFont.SansSerif)
                    if QFontMetrics(ff).horizontalAdvance(text) <= W - 48:
                        return ff
                    s -= 1
                ff = QFont("Segoe UI", 7)
                ff.setBold(bold)
                ff.setStyleHint(QFont.SansSerif)
                return ff

            # 顶部品牌色细线（界面主题蓝 #1565C0）
            p.fillRect(0, 0, W, 5, QColor("#1565C0"))

            # 中央校徽图片（找不到则留空不画）
            _emblem_path = _paths.find_asset("校徽.png", "校徽.jpg")
            if _emblem_path:
                _emblem = QPixmap(_emblem_path)
                if not _emblem.isNull():
                    _emblem = _emblem.scaled(
                        100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    p.drawPixmap((W - _emblem.width()) // 2, 28, _emblem)

            # ── 主标题：产品名（全英文，主题紫深色，最大的字号）──
            p.setPen(QColor("#0D47A1"))
            p.setFont(_fit_font("GXNU MolStudio", 23, True))
            p.drawText(QRectF(0, 134, W, 46), Qt.AlignCenter, "GXNU MolStudio")

            # ── 定位语（英文，主题紫，次大；过长会自动缩字保证一行放得下）──
            _tag = "Molecular Visualization & Quantum Chemistry Analysis"
            p.setPen(QColor("#1565C0"))
            p.setFont(_fit_font(_tag, 12))
            p.drawText(QRectF(0, 190, W, 26), Qt.AlignCenter, _tag)

            # ── 出品署名（英文小字，主题紫）──
            # 绘制区域加高、下方多留白：避免字母下伸部分（g/y/p 等）显示不全
            _grp = "Guangxi Normal University · Hou Cheng Group"
            p.setPen(QColor("#1565C0"))
            p.setFont(_fit_font(_grp, 10, True))
            p.drawText(QRectF(0, 222, W, 34), Qt.AlignCenter, _grp)

            # ── 版本（弱化紫灰，最小一行；与上面署名行之间留足行距）──
            p.setPen(QColor("#7C96B9"))
            p.setFont(_fit_font("Version 1.0", 9))
            p.drawText(QRectF(0, 272, W, 20), Qt.AlignCenter, "Version 1.0")

            # ── 底部加载条：只画浅色轨道（进度填充由 _FadeSplash.set_progress 动画绘制）──
            bar_w, bar_h, bar_y = 300, 5, 318
            bar_x = (W - bar_w) // 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E7F0FA"))
            p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 2, 2)

            # 状态文字
            p.setPen(QColor("#7C96B9"))
            f5 = QFont("Segoe UI", 9)
            f5.setStyleHint(QFont.SansSerif)
            p.setFont(f5)
            p.drawText(QRectF(0, bar_y + 16, W, 20), Qt.AlignCenter,
                       "Initializing…")

            p.end()
            return pm, (bar_x, bar_y, bar_w, bar_h)

        class _FadeSplash(QWidget):
            """带淡入淡出动画的启动画面：普通无边框窗口 + windowOpacity 动画，
            不依赖 QSplashScreen（其分层窗口在 Windows 上不响应透明度动画）。"""

            def __init__(self, pixmap, bar=None):
                super().__init__(None, Qt.FramelessWindowHint
                                 | Qt.WindowStaysOnTopHint | Qt.Tool)
                self._base = pixmap.copy()
                self._bar = bar          # (x, y, w, h)；None = 无动画条
                self._pixmap = pixmap
                self._after_fade_out = None
                self.setFixedSize(pixmap.size())
                screen = QApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    self.move(geo.center() - self.rect().center())
                self.setWindowOpacity(0.0)
                self._anim = QVariantAnimation(self)
                self._anim.setDuration(420)
                self._anim.setEasingCurve(QEasingCurve.InOutCubic)
                self._anim.valueChanged.connect(self._set_opacity)

            def _set_opacity(self, v):
                self.setWindowOpacity(float(v))

            def paintEvent(self, a0):
                p = QPainter(self)
                p.drawPixmap(0, 0, self._pixmap)
                p.end()

            def set_progress(self, frac):
                """把加载条进度填充为 frac(0..1)，每次在底层位图拷贝上重绘。"""
                frac = max(0.0, min(1.0, float(frac)))
                if self._bar is None:
                    return
                bx, by, bw, bh = self._bar
                pm = self._base.copy()
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                p.setPen(Qt.NoPen)
                grad = QLinearGradient(bx, by, bx + bw, by)
                grad.setColorAt(0.0, QColor("#1565C0"))
                grad.setColorAt(1.0, QColor("#1E88E5"))
                p.setBrush(grad)
                p.drawRoundedRect(bx, by, max(1, int(bw * frac)), bh, 2, 2)
                p.end()
                self._pixmap = pm
                self.update()

            def fade_in(self):
                self._anim.stop()
                self._anim.setStartValue(self.windowOpacity())
                self._anim.setEndValue(1.0)
                try:
                    self._anim.finished.disconnect(self._on_fade_out_done)
                except TypeError:
                    pass
                self._anim.start()

            def fade_out(self, after=None):
                self._after_fade_out = after
                self._anim.stop()
                self._anim.setStartValue(self.windowOpacity())
                self._anim.setEndValue(0.0)
                try:
                    self._anim.finished.disconnect(self._on_fade_out_done)
                except TypeError:
                    pass
                self._anim.finished.connect(self._on_fade_out_done)
                self._anim.start()

            def finish(self, widget=None):
                self.hide()
                self.close()

            def _on_fade_out_done(self):
                cb = self._after_fade_out
                self._after_fade_out = None
                if cb is not None:
                    cb()

        # 启动画面（GXNU MolStudio 欢迎界面）默认**显示**：它盖住 bootloader /
        # Qt 布局 / GL 上下文初始化那段空窗期，同时展示品牌信息。
        # 注：此前默认关闭是因为启动时会另有一个"小矩形窗口"一闪而过，那个
        # 窗口其实来自画布参数面板（ovcanvas/_panel.py 里 parent 未就位就
        # setVisible 的旧顺序），与本启动画面无关；该问题修复后这里恢复默认显示。
        # 需要临时关掉时设环境变量 MOLSTUDIO_SPLASH=0。
        _SHOW_SPLASH = os.environ.get("MOLSTUDIO_SPLASH", "").strip().lower() \
            not in ("0", "false", "no", "off")
        splash = None
        if _SHOW_SPLASH:
            _splash_pm, _splash_bar = _make_splash_pixmap()
            splash = _FadeSplash(_splash_pm, _splash_bar)
            splash.show()
            splash.fade_in()
        app.processEvents()

        # ── 临时调试：splash/主窗口物理尺寸 + 进程内窗口枚举（含类名，写日志）──
        if splash is not None:
            try:
                import ctypes
                from ctypes import wintypes
                _r = wintypes.RECT()
                _h = int(splash.winId())
                ctypes.windll.user32.GetWindowRect(_h, ctypes.byref(_r))
                _dbg("splash logical=%dx%d physical=%dx%d dpr=%s" % (
                    splash.width(), splash.height(),
                    _r.right - _r.left, _r.bottom - _r.top,
                    splash.devicePixelRatioF()))
            except Exception as _e:
                _dbg("splash err %s" % _e)
        else:
            _dbg("splash disabled (MOLSTUDIO_SPLASH not set)")

        import ctypes as _ct
        from ctypes import wintypes as _wt
        _self_pid = _ct.windll.kernel32.GetCurrentProcessId()
        _u32 = _ct.windll.user32

        def _dbg_enum(tag):
            """枚举本进程所有可见顶层窗口：尺寸/类名/标题/窗口 DPI。"""
            try:
                def _cb(h, _l):
                    r = _wt.RECT()
                    _u32.GetWindowRect(h, _ct.byref(r))
                    w = r.right - r.left
                    hh = r.bottom - r.top
                    if w <= 0 or hh <= 0:
                        return True
                    n = _u32.GetWindowTextLengthW(h)
                    tt = ""
                    if n > 0:
                        b = _ct.create_unicode_buffer(n + 1)
                        _u32.GetWindowTextW(h, b, n + 1)
                        tt = b.value
                    cn = _ct.create_unicode_buffer(128)
                    _u32.GetClassNameW(h, cn, 128)
                    cls = cn.value
                    if "MolStudio" in tt or "python" in tt or w < 600 or hh < 500:
                        pid = _wt.DWORD()
                        _u32.GetWindowThreadProcessId(h, _ct.byref(pid))
                        if pid.value == _self_pid:
                            dpi = 0
                            try:
                                dpi = _u32.GetDpiForWindow(h)
                            except Exception:
                                pass
                            _dbg("  [%s] %dx%d class=%r title=%r dpi=%d" % (
                                tag, w, hh, cls, tt, dpi))
                    return True
                _u32.EnumWindows(
                    _ct.WINFUNCTYPE(_ct.c_bool, _wt.HWND, _wt.LPARAM)(_cb), 0)
            except Exception as _e:
                _dbg("  [%s] enum err %s" % (tag, _e))

        _dbg("=== before OrbitalVisApp() ===")
        _dbg_enum("pre")

        window = _make_window(_ui)
        # Fix the final geometry before the first paint so no tiny placeholder
        # frame is ever shown.
        window.resize(1400, 820)
        window.ensurePolished()
        _dbg("=== after OrbitalVisApp() resize ===")
        _dbg_enum("post")

        try:
            _r = _wt.RECT()
            _h = int(window.winId())
            _u32.GetWindowRect(_h, _ct.byref(_r))
            _dbg("mainwin logical=%dx%d physical=%dx%d dpr=%s" % (
                window.width(), window.height(),
                _r.right - _r.left, _r.bottom - _r.top, window.devicePixelRatioF()))
        except Exception as _e:
            _dbg("mainwin err %s" % _e)

        # ── 别把启动焦点给文本输入框 ──
        # 主窗口里第一个可聚焦控件是个 QLineEdit；一拿到焦点，系统输入法
        # （本机是搜狗）就会立刻弹出它的**状态条窗口**（实测 345x48、
        # 窗口类名 "SoPY_Status"、属于本进程但其实是输入法注入创建的）。
        # 用户看到的就是"启动后冒出一个小窗口、停留一下、里面只有一些
        # 滑块一样的小图标"。
        # ★ 顺序很关键：必须在 show() **之前**把焦点定到画布上。
        #   放到 show() 之后再抢是没用的 —— 那时 QLineEdit 已经拿过焦点、
        #   输入法窗口已经弹出来了（实测仍会出现 SoPY_Status）。
        try:
            _canvas = (getattr(window, "cub_canvas", None)
                       or getattr(window, "mol_canvas", None))
            if _canvas is not None:
                _canvas.setFocus()
        except Exception as _e:
            _dbg("pre-show focus err %s" % _e)

        window.show()
        app.processEvents()

        # 兜底：万一焦点还是落在输入框上（不同平台/Qt 版本行为略有差异），
        # 收回来交给画布。
        try:
            from PyQt5.QtWidgets import (QLineEdit, QTextEdit,
                                         QPlainTextEdit, QAbstractSpinBox)
            _fw = app.focusWidget()
            if isinstance(_fw, (QLineEdit, QTextEdit, QPlainTextEdit,
                                QAbstractSpinBox)):
                _fw.clearFocus()
                if _canvas is not None:
                    _canvas.setFocus()
                app.processEvents()
        except Exception as _e:
            _dbg("focus handoff err %s" % _e)
        _dbg("=== after window.show() ===")
        _dbg_enum("show")

        # 周期枚举：捕捉一闪而过的小窗口（前 8 秒每 150ms 一次，新窗口才记录）
        _dbg_seen = set()

        def _dbg_tick():
            def _cb2(h, _l):
                r = _wt.RECT()
                _u32.GetWindowRect(h, _ct.byref(r))
                w = r.right - r.left
                hh = r.bottom - r.top
                if w <= 0 or hh <= 0:
                    return True
                if h in _dbg_seen:
                    return True
                n = _u32.GetWindowTextLengthW(h)
                tt = ""
                if n > 0:
                    b = _ct.create_unicode_buffer(n + 1)
                    _u32.GetWindowTextW(h, b, n + 1)
                    tt = b.value
                cn = _ct.create_unicode_buffer(128)
                _u32.GetClassNameW(h, cn, 128)
                cls = cn.value
                if "MolStudio" in tt or "python" in tt or w < 600 or hh < 500:
                    pid = _wt.DWORD()
                    _u32.GetWindowThreadProcessId(h, _ct.byref(pid))
                    if pid.value == _self_pid:
                        dpi = 0
                        try:
                            dpi = _u32.GetDpiForWindow(h)
                        except Exception:
                            pass
                        _dbg_seen.add(h)
                        _dbg("  [tick] NEW %dx%d class=%r title=%r dpi=%d" % (
                            w, hh, cls, tt, dpi))
                return True
            _u32.EnumWindows(
                _ct.WINFUNCTYPE(_ct.c_bool, _wt.HWND, _wt.LPARAM)(_cb2), 0)

        _dbg_timer = QTimer()
        _dbg_timer.timeout.connect(_dbg_tick)
        _dbg_timer.start(150)
        QTimer.singleShot(8000, _dbg_timer.stop)
        if splash is not None:
            # 启动画面停留 5 秒：前 ~4.6 秒加载条从 0 平滑走到 100%，随后淡出
            # 收尾，转交主窗口。
            _elapsed = QElapsedTimer()
            _elapsed.start()
            _prog_timer = QTimer()

            def _splash_tick():
                el = _elapsed.elapsed()
                splash.set_progress(el / 4600.0)
                if el >= 5000:
                    _prog_timer.stop()
                    splash.fade_out(lambda: splash.finish(window))

            _prog_timer.timeout.connect(_splash_tick)
            _prog_timer.start(33)
        else:
            # 无启动画面：主窗口已经在上面 show() 过了，直接置前并进事件循环。
            window.raise_()
            window.activateWindow()
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
