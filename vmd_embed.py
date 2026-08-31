# -*- coding: utf-8 -*-
"""
VMD 嵌入可视化窗口 —— 用 Win32 SetParent 把 VMD 的 OpenGL Display 窗口
挂到 Qt 容器下，实现「左边 VMD / 右边控制台」的分栏窗口。

原理（Windows）：
  1. 用 subprocess 启动 VMD（-dispdev win），VMD 会创建一个顶层窗口，
     标题为 "VMD 1.9.3 OpenGL Display"（class 名 "VMD"），菜单栏也在其中。
  2. 按进程 PID 枚举顶层窗口找到该 HWND。
  3. SetParent(vmd_hwnd, qt_container_hwnd) 把它变成 Qt 容器的子窗口，
     再去掉 WS_CAPTION / WS_THICKFRAME 边框样式。
  4. 定时器检测容器尺寸变化，用 SetWindowPos 让 VMD 窗口跟随缩放。
  5. 关闭时先经 socket 发 quit，再 terminate() 兜底强杀 VMD 进程。

注意：
  - VMD 1.9.3 只有一个顶层窗口，菜单栏会随窗口一起嵌入（可接受）。
  - 关闭必须由本窗口驱动：先杀 VMD 再销毁容器，否则 VMD 成孤儿/崩溃。
"""

import os
import sys
import time
import ctypes
import socket
import subprocess
from ctypes import wintypes

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel
from PyQt5.QtCore import Qt, QTimer

user32 = ctypes.windll.user32


# ── Win32 窗口操作 ──────────────────────────────────────────────

def _enum_top_windows(pid):
    """枚举属于进程 pid 的所有顶层窗口，返回 [(hwnd, title, classname), ...]。"""
    results = []
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, lparam):
        wpid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            results.append((int(hwnd), buf.value, cls.value))
        return True

    cb = WNDPROC(_cb)
    user32.EnumWindows(cb, 0)
    return results


def find_vmd_windows(pid, timeout=25.0):
    """轮询查找 VMD 的三个可见顶层窗口，返回 (gl_hwnd, menu_hwnd, tkcon_hwnd)。

    VMD 1.9.3 启动（含 menu tkcon on）后有：
      - "VMD 1.9.3 OpenGL Display" (class VMD)     —— 3D 显示区
      - "VMD Main" (class FLTK)                     —— 菜单栏窗口
      - "VMD TkConsole" (class TkTopLevel)          —— VMD 自带控制台
    三者独立存在且出现时间略有先后，故轮询等待显示区 + 菜单栏就绪，
    TkConsole 若尚未出现返回 None（由调用方决定是否重试）。
    """
    deadline = time.time() + timeout
    gl = None
    menu = None
    tkcon = None
    while time.time() < deadline:
        for hwnd, title, cls in _enum_top_windows(pid):
            if "OpenGL Display" in title and cls == "VMD":
                gl = hwnd
            elif title == "VMD Main" and cls == "FLTK":
                menu = hwnd
            elif title == "VMD TkConsole" and cls == "TkTopLevel":
                tkcon = hwnd
        if gl is not None and menu is not None and tkcon is not None:
            return gl, menu, tkcon
        time.sleep(0.3)
    return gl, menu, tkcon


def find_vmd_display_hwnd(pid, timeout=25.0):
    """兼容旧接口：只返回 OpenGL Display 窗口句柄。"""
    gl, _, _ = find_vmd_windows(pid, timeout)
    return gl


def embed_window(hwnd, host_hwnd, w, h):
    """SetParent + 去边框样式 + 填满宿主客户区（w/h 为物理像素）。"""
    WS_CHILD = 0x40000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    GWL_STYLE = -16
    SWP_SHOWWINDOW = 0x0040
    SWP_NOZORDER = 0x0004

    user32.SetParent(hwnd, host_hwnd)
    st = user32.GetWindowLongW(hwnd, GWL_STYLE)
    st = (st & ~WS_CAPTION & ~WS_THICKFRAME) | WS_CHILD
    user32.SetWindowLongW(hwnd, GWL_STYLE, st)
    user32.SetWindowPos(hwnd, 0, 0, 0, max(1, w), max(1, h),
                        SWP_SHOWWINDOW | SWP_NOZORDER)


# ── VMD 启动 ────────────────────────────────────────────────────

def launch_vmd(scene, style_name, shade_mode, vmd_exe):
    """启动 VMD 显示场景（带 socket 服务器），返回 (proc, port, render_dir)。

    scene / style_name / shade_mode 与 fchk_orbital.preview_scene 语义一致；
    这里额外保留 subprocess.Popen 对象，供后续枚举窗口句柄与清理。
    """
    import fchk_orbital as backend

    if vmd_exe is None:
        vmd_exe = backend.DEFAULT_VMD

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    render_dir, tcl_name = backend.build_scene_tcl(
        scene, style_name, shade_mode, port=port)

    # 在生成的 TCL 末尾追加「打开 TkConsole（VMD 自带控制台）」命令，
    # 使 VMD 启动时就有独立的 TkConsole 窗口可供嵌入。
    tcl_path = os.path.join(render_dir, tcl_name)
    with open(tcl_path, "a", encoding="utf-8") as f:
        f.write("\nmenu tkcon on\n")

    proc = subprocess.Popen(
        [vmd_exe, "-e", tcl_name],
        cwd=render_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    return proc, port, render_dir


# ── 嵌入窗口 ────────────────────────────────────────────────────

class VMDEmbedWindow(QWidget):
    """布局（三个 VMD 窗口都嵌入）：
      上：菜单栏（VMD Main）+ 3D 显示区（OpenGL Display），菜单栏在显示区上方
      下左：VMD 自带控制台（TkConsole）
      下右：我们的控制台
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 关键：即使传了 parent（用于生命周期管理），也要设 Qt.Window 标志，
        # 否则 QWidget 会被当作父窗口的子控件嵌在父窗口内部，而不是独立弹窗。
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("VMD 嵌入可视化")
        self.resize(1280, 820)
        # close() 后销毁对象并触发 destroyed 信号，主窗口据此清理 VMD 会话状态
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        # 上左：VMD 菜单栏容器（VMD Main 嵌入处）
        self._menu_container = QWidget()
        self._menu_container.setStyleSheet("background:#1A1A1A;")

        # 上右：VMD 可视化容器（OpenGL Display 嵌入处）
        self._gl_container = QWidget()
        self._gl_container.setStyleSheet("background:#101820;")

        # 下左：VMD 自带控制台容器（TkConsole 嵌入处）
        self._tkcon_container = QWidget()
        self._tkcon_container.setStyleSheet("background:#0D0D0D;")

        # 下右：我们的控制台面板（主窗口把 VMD 控制台 groupbox 挂进来）
        self._right = QWidget()
        self._right_lay = QVBoxLayout(self._right)
        self._right_lay.setContentsMargins(6, 6, 6, 6)
        self._right_lay.setSpacing(6)

        # 上部：水平分栏（左菜单栏 | 右显示区）
        top = QSplitter(Qt.Horizontal)
        top.addWidget(self._menu_container)
        top.addWidget(self._gl_container)
        top.setStretchFactor(0, 2)
        top.setStretchFactor(1, 5)
        top.setChildrenCollapsible(False)
        top.setSizes([360, 900])

        # 下部：水平分栏（左 TkConsole | 右我们的控制台）
        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(self._tkcon_container)
        bottom.addWidget(self._right)
        bottom.setStretchFactor(0, 4)
        bottom.setStretchFactor(1, 4)
        bottom.setChildrenCollapsible(False)
        bottom.setSizes([640, 620])

        # 上（可视化+菜单栏）与下（TkConsole+控制台）垂直分栏
        main_split = QSplitter(Qt.Vertical)
        main_split.addWidget(top)
        main_split.addWidget(bottom)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)
        main_split.setChildrenCollapsible(False)
        main_split.setSizes([520, 260])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(main_split)

        self._proc = None
        self._port = None
        self._render_dir = None
        self._gl_hwnd = None
        self._menu_hwnd = None
        self._tkcon_hwnd = None
        self._last_gl_geom = None
        self._last_menu_geom = None
        self._last_tkcon_geom = None

        # 定时器：容器尺寸变化时让三个 VMD 窗口跟随
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._sync_geometry)
        self._timer.start()

    # ── 对外接口 ──
    def set_control_widget(self, widget):
        """把主窗口的 VMD 控制台 groupbox 挂到右下角面板。"""
        self._right_lay.addWidget(widget)

    def attach_vmd(self, proc, port, render_dir, gl_hwnd, menu_hwnd=None,
                   tkcon_hwnd=None):
        """记录 VMD 进程信息，并把三个窗口分别嵌入对应容器。"""
        self._proc = proc
        self._port = port
        self._render_dir = render_dir
        self._gl_hwnd = gl_hwnd
        self._menu_hwnd = menu_hwnd
        self._tkcon_hwnd = tkcon_hwnd
        self._last_gl_geom = None
        self._last_menu_geom = None
        self._last_tkcon_geom = None
        self._sync_geometry()

    def port(self):
        return self._port

    def render_dir(self):
        return self._render_dir

    def is_vmd_alive(self):
        return self._proc is not None and self._proc.poll() is None

    # ── 内部 ──
    def _sync_geometry(self):
        if not self.isVisible():
            return
        # 显示区 → 上右容器
        if self._gl_hwnd:
            dpr = self._gl_container.devicePixelRatioF()
            w = max(1, int(self._gl_container.width() * dpr))
            h = max(1, int(self._gl_container.height() * dpr))
            key = (w, h)
            if key != self._last_gl_geom:
                self._last_gl_geom = key
                embed_window(self._gl_hwnd, int(self._gl_container.winId()), w, h)
        # 菜单栏 → 上左容器
        if self._menu_hwnd:
            dpr = self._menu_container.devicePixelRatioF()
            w = max(1, int(self._menu_container.width() * dpr))
            h = max(1, int(self._menu_container.height() * dpr))
            key = (w, h)
            if key != self._last_menu_geom:
                self._last_menu_geom = key
                embed_window(self._menu_hwnd, int(self._menu_container.winId()), w, h)
        # TkConsole → 下左容器
        if self._tkcon_hwnd:
            dpr = self._tkcon_container.devicePixelRatioF()
            w = max(1, int(self._tkcon_container.width() * dpr))
            h = max(1, int(self._tkcon_container.height() * dpr))
            key = (w, h)
            if key != self._last_tkcon_geom:
                self._last_tkcon_geom = key
                embed_window(self._tkcon_hwnd, int(self._tkcon_container.winId()), w, h)

    def _kill_vmd(self):
        """关闭前清理 VMD：socket quit → terminate 兜底 → kill。"""
        if self._port:
            try:
                s = socket.create_connection(("127.0.0.1", self._port), timeout=2)
                s.sendall(b"quit\n")
                time.sleep(0.2)
                s.close()
            except Exception:
                pass
        if self._proc is not None:
            for _ in range(20):
                if self._proc.poll() is not None:
                    break
                time.sleep(0.2)
            if self._proc.poll() is None:
                try:
                    self._proc.terminate()
                    time.sleep(0.5)
                except Exception:
                    pass
            if self._proc.poll() is None:
                try:
                    self._proc.kill()
                except Exception:
                    pass

    def closeEvent(self, event):
        self._timer.stop()
        self._kill_vmd()
        self._gl_hwnd = None
        self._menu_hwnd = None
        self._tkcon_hwnd = None
        event.accept()
