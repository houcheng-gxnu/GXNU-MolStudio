#!/usr/bin/env python3
"""
GXNU MolStudio 分子可视化与量子化学分析工具 v1.0 — 入口模块
用法:
    python main.py                        # 启动 GUI
    python main.py input.fchk --mo h     # 命令行批处理模式
"""

import os
import re
import sys
import glob

# 确保当前目录在 sys.path 中，以便能找到本地模块和 backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main_window import OrbitalVisApp


def main():
    if len(sys.argv) > 1:
        import argparse
        import fchk_orbital as backend

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

        files = (sorted(glob.glob(os.path.join(a.input, "*.fchk")))
                 if os.path.isdir(a.input) else [a.input])
        if not files:
            print("未找到任何 .fchk 文件")
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
        from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, QEasingCurve, QVariantAnimation
        from PyQt5.QtGui import (QColor, QPalette, QSurfaceFormat, QPixmap,
                                 QPainter, QLinearGradient, QFont, QPen)

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
        # 应用级窗口图标：主窗口及所有弹窗默认继承（打包后图标可能在 exe 同目录
        # 或 _internal/sys._MEIPASS——onedir 的 datas 都进 _internal）
        _icon_dirs = [os.path.dirname(os.path.abspath(__file__))]
        if getattr(sys, "frozen", False):
            _icon_dirs.insert(0, os.path.dirname(sys.executable))
            _meipass = getattr(sys, "_MEIPASS", None)
            if _meipass:
                _icon_dirs.append(_meipass)
        for _n in ("OV.png", "molstudio.ico", "gxnu_molstudio.ico",
                   "molstudio_icon_src.png"):
            _p = None
            for _dir in _icon_dirs:
                _cand = os.path.join(_dir, _n)
                if os.path.exists(_cand):
                    _p = _cand
                    break
            if _p:
                from PyQt5.QtGui import QIcon
                app.setWindowIcon(QIcon(_p))
                break
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
            """绘制品牌启动画面：白底 + 校徽图片 + presents 字幕 + 装饰加载条。"""
            W, H = 560, 380
            pm = QPixmap(W, H)
            pm.fill(Qt.white)

            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)

            # 顶部品牌色细线
            p.fillRect(0, 0, W, 5, QColor("#3E8E7E"))

            # 中央校徽图片（打包后可能在 exe 同目录或 _internal/sys._MEIPASS；
            # 找不到则留空不画）
            _base_dirs = [os.path.dirname(os.path.abspath(__file__))]
            if getattr(sys, "frozen", False):
                _base_dirs.insert(0, os.path.dirname(sys.executable))
                _meipass = getattr(sys, "_MEIPASS", None)
                if _meipass:
                    _base_dirs.append(_meipass)
            _emblem_path = None
            for _n in ("校徽.png", "校徽.jpg"):
                for _dir in _base_dirs:
                    _p = os.path.join(_dir, _n)
                    if os.path.exists(_p):
                        _emblem_path = _p
                        break
                if _emblem_path:
                    break
            if _emblem_path:
                _emblem = QPixmap(_emblem_path)
                if not _emblem.isNull():
                    _emblem = _emblem.scaled(
                        120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    p.drawPixmap((W - _emblem.width()) // 2, 40, _emblem)

            # 主标题（作品名，白底深色，清晰醒目）
            p.setPen(QColor("#1F2D3D"))
            f = QFont("Microsoft YaHei", 27)
            f.setBold(True)
            f.setStyleHint(QFont.SansSerif)
            p.setFont(f)
            p.drawText(QRectF(0, 158, W, 48), Qt.AlignCenter, "GXNU MolStudio")

            # 副标题
            p.setPen(QColor("#5A6B7D"))
            f2 = QFont("Microsoft YaHei", 12)
            f2.setStyleHint(QFont.SansSerif)
            p.setFont(f2)
            p.drawText(QRectF(0, 206, W, 26), Qt.AlignCenter,
                       "分子可视化工具")

            # 版本
            p.setPen(QColor("#8A99A8"))
            f3 = QFont("Arial", 10)
            f3.setStyleHint(QFont.SansSerif)
            p.setFont(f3)
            p.drawText(QRectF(0, 232, W, 20), Qt.AlignCenter, "Version 1.0")

            # 出品方署名：课题组 + presents（衬线斜体，位于底部加载条上方）
            p.setPen(QColor("#3E8E7E"))
            f4 = QFont("Georgia", 15)
            f4.setItalic(True)
            f4.setStyleHint(QFont.Serif)
            p.setFont(f4)
            p.drawText(QRectF(0, 256, W, 26), Qt.AlignCenter,
                       "HOU Cheng research group")

            f4.setPointSize(13)
            p.setFont(f4)
            p.drawText(QRectF(0, 284, W, 24), Qt.AlignCenter, "presents")

            # 底部装饰加载条（浅色轨道 + 品牌色进度）
            bar_w, bar_h, bar_y = 320, 6, 322
            bar_x = (W - bar_w) // 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E3E9F0"))
            p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 3, 3)
            grad = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
            grad.setColorAt(0.0, QColor("#3E8E7E"))
            grad.setColorAt(1.0, QColor("#2B6CB0"))
            p.setBrush(grad)
            p.drawRoundedRect(bar_x, bar_y, int(bar_w * 0.35), bar_h, 3, 3)

            # 状态文字
            p.setPen(QColor("#7E9AB8"))
            f5 = QFont("Microsoft YaHei", 9)
            f5.setStyleHint(QFont.SansSerif)
            p.setFont(f5)
            p.drawText(QRectF(0, bar_y + 16, W, 24), Qt.AlignCenter,
                       "正在初始化…")

            p.end()
            return pm

        class _FadeSplash(QWidget):
            """带淡入淡出动画的启动画面：普通无边框窗口 + windowOpacity 动画，
            不依赖 QSplashScreen（其分层窗口在 Windows 上不响应透明度动画）。"""

            def __init__(self, pixmap):
                super().__init__(None, Qt.FramelessWindowHint
                                 | Qt.WindowStaysOnTopHint | Qt.Tool)
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

        # Splash screen: covers the brief blank/empty window that appears while
        # the bootloader + Qt layout + GL context are initialising, so the user
        # never sees the small-to-large window flash.
        splash = _FadeSplash(_make_splash_pixmap())
        splash.show()
        splash.fade_in()
        app.processEvents()

        # ── 临时调试：splash/主窗口物理尺寸 + 进程内窗口枚举（含类名，写日志）──
        try:
            import ctypes
            from ctypes import wintypes
            _r = wintypes.RECT()
            _h = int(splash.winId())
            ctypes.windll.user32.GetWindowRect(_h, ctypes.byref(_r))
            _dbg("splash logical=%dx%d physical=%dx%d dpr=%s" % (
                splash.width(), splash.height(),
                _r.right - _r.left, _r.bottom - _r.top, splash.devicePixelRatioF()))
        except Exception as _e:
            _dbg("splash err %s" % _e)

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

        window = OrbitalVisApp()
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

        window.show()
        app.processEvents()
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
        # 启动画面多停留 3 秒后淡出收尾，转交主窗口。
        QTimer.singleShot(3000, lambda: splash.fade_out(
            lambda: splash.finish(window)))
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
