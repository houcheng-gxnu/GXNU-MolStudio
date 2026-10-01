#!/usr/bin/env python3
"""
轨道等值面可视化可复用库 — VMDOrbitalSession
=============================================
封装 VMD 进程管理、cube 文件加载、实时样式切换、等值面/透明度调节、
Tachyon 渲染等核心功能，可脱离 GUI 直接调用。

  依赖:
    - fchk_orbital (backend: STYLES, gen_cube, preview_cube, render_current_view, ...)
    - VMD + Tachyon 已安装

  快速使用:
    >>> from orbital_viewer_lib import VMDOrbitalSession
    >>> sess = VMDOrbitalSession()
    >>> sess.load_cube("MO_50.cub", isovalue=0.05, style="sob-art")
    >>> sess.set_style("ao-shiny")        # 实时切换样式
    >>> sess.set_isovalue(0.03)           # 实时调节等值面
    >>> sess.render("output.png")         # Tachyon 渲染出图
    >>> sess.close()

  便捷函数:
    >>> from orbital_viewer_lib import view_cube, cube_to_png
    >>> view_cube("MO_50.cub", style="sob-art")        # 一行打开预览
    >>> cube_to_png("MO_50.cub", "out.png", style="ao-shiny")  # 一行渲染

作者: Workbuddy + Trae AI
"""

import os
import sys
import socket
import time
import tempfile
import shutil
import subprocess

# ── 导入后端 ──────────────────────────────────────────
# 直接运行本文件时把仓库根目录加入 sys.path（包方式导入不需要）
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import molstudio.core.fchk_orbital as backend


# ═══════════════════════════════════════════════════════════════
#  VMDOrbitalSession — 核心 VMD 会话管理
# ═══════════════════════════════════════════════════════════════

class VMDOrbitalSession:
    """管理一个 VMD 进程的完整生命周期，提供实时控制和渲染功能。

    封装了 VMD 启动、socket 通信、样式切换、等值面/透明度调节和
    Tachyon 渲染，可在脚本或 GUI 中直接使用。

    Attributes:
        port (int|None): VMD socket 端口号，None 表示未连接
        render_dir (str|None): VMD 工作目录
        current_style (str): 当前应用的样式名
        current_isovalue (float): 当前等值面值
        current_opacity (float|None): 当前表面不透明度
    """

    # ── 多轨道预定义色板 ──
    MULTI_ORBIT_COLORS = [
        {"pos": [12, 0.1, 0.8, 0.3], "neg": [22, 0.1, 0.4, 0.9]},
        {"pos": [3,  0.9, 0.3, 0.1], "neg": [23, 0.9, 0.7, 0.1]},
        {"pos": [4,  1.0, 1.0, 0.0], "neg": [11, 0.6, 0.1, 0.6]},
        {"pos": [17, 0.0, 0.7, 0.7], "neg": [15, 0.7, 0.1, 0.1]},
        {"pos": [7,  0.1, 0.8, 0.1], "neg": [9,  0.1, 0.1, 0.5]},
    ]

    def __init__(self, vmd_exe=None, tachyon_exe=None, multiwfn_exe=None,
                 log_func=None, paths=None):
        """
        Args:
            vmd_exe: VMD 可执行文件路径，默认从 fchk_orbital.ini 读取
            tachyon_exe: Tachyon 渲染器路径
            multiwfn_exe: Multiwfn 路径（仅 gen_cubes 需要）
            log_func: 日志回调函数 Callable[[str], None]，None 则用 print
            paths: 预加载的路径字典，避免重复读 ini
        """
        if paths is None:
            paths = backend.load_config()
        self.vmd_exe = vmd_exe or paths.get("vmd", backend.DEFAULT_VMD)
        self.tachyon_exe = tachyon_exe or paths.get("tachyon", backend.DEFAULT_TACHYON)
        self.multiwfn_exe = multiwfn_exe or paths.get("multiwfn", backend.DEFAULT_MULTIWFN)
        self._log = log_func if log_func else lambda msg: print(msg)

        # 运行时状态
        self.port = None
        self.render_dir = None
        self._sock = None
        self._current_style = None
        self._current_isovalue = None
        self._current_opacity = None
        self._multi_cubes = None
        self._vmd_state = {"rep_pos": 1, "rep_neg": 2, "molid": 0}
        self._mol_mode = False  # True = molecule-only preview (log file)
        self._vmd_process = None

    # ── Cube 加载 ──────────────────────────────────────

    def load_cube(self, cube_path, isovalue=0.05, style="sob-art",
                  shade_mode="full", keep_h_indices=None):
        """启动 VMD 并加载单个 cube 文件。

        Args:
            cube_path: .cub 文件路径
            isovalue: 等值面阈值 (默认 0.05)
            style: 渲染样式名 (默认 "sob-art")
            shade_mode: "full" 或 "medium"
            keep_h_indices: 保留的氢原子索引列表，None=全部保留，[]=全部隐藏
        Returns:
            bool: 是否成功启动
        """
        self._close_existing()

        self._log(f"启动 VMD 预览: {os.path.basename(cube_path)}")
        self._log(f"  样式: {style}  等值面: {isovalue}")

        port, render_dir = backend.preview_cube(
            cube_path, isovalue=isovalue, style_name=style,
            vmd_exe=self.vmd_exe, shade_mode=shade_mode,
            keep_h_indices=keep_h_indices)

        if port:
            self.port = port
            self.render_dir = render_dir
            self._current_style = style
            self._current_isovalue = isovalue
            self._multi_cubes = None
            return True
        else:
            self._log("VMD 启动失败")
            return False

    def load_multi_cubes(self, cube_files, isovalues=0.05, style="sob-art",
                         shade_mode="full", keep_h_indices=None):
        """启动 VMD 并加载多个 cube 文件（多轨道模式）。

        Args:
            cube_files: [(cube_path, orbital_name), ...] 或 [cube_path, ...]
            isovalues: 等值面值列表或单一值
            style: 渲染样式名
        Returns:
            bool: 是否成功启动
        """
        self._close_existing()

        n = len(cube_files)
        if isinstance(isovalues, (int, float)):
            isovalues = [isovalues] * n

        # 规范化格式
        normalized = []
        for item in cube_files:
            if isinstance(item, (list, tuple)):
                normalized.append((item[0], item[1]))
            else:
                normalized.append((item, os.path.basename(item)))

        self._log(f"启动 VMD 多轨道预览: {n} 个 cube")

        port, render_dir, copied_cubes = backend.preview_multi_cubes(
            normalized, isovalues, style_name=style,
            vmd_exe=self.vmd_exe, shade_mode=shade_mode,
            keep_h_indices=keep_h_indices)

        if port:
            self.port = port
            self.render_dir = render_dir
            self._current_style = style
            self._current_isovalue = isovalues[0] if isovalues else 0.05
            self._multi_cubes = copied_cubes or normalized
            return True
        else:
            self._log("VMD 多轨道启动失败")
            return False

    # ── 实时样式切换 ───────────────────────────────────

    def set_style(self, style_name, shade_mode=None, vol_color=False,
                  cmap=None, atom_cpk=None, vol_range=None):
        """实时切换渲染样式（不重启 VMD）。

        Args:
            style_name: 样式名（见 backend.STYLES.keys()）
            shade_mode: None=保持当前，或 "full"/"medium"
            vol_color:  当前场景的等值面是否为「按体积连续着色」（ESP/IGMH）。
                        样式带 volume_color 且此项为 True 时，不发 ColorID，
                        改发 color scale method + mol scaleminmax，保住 Volume 着色。
            cmap:       「VMD 控制台」选的色标方法，覆盖样式自带的
                        volume_color.cmap（None = 用样式自带的）。
            atom_cpk:   样式的 CPK 四参数，一并换掉球棍半径；None = 不动
                        （调用方确认 rep 0 不是 CPK 原子 rep 时应传 None）。
            vol_range:  体着色的数值量程 (cmin, cmax)。给了才会重申
                        `mol modcolor … Volume`（那条命令会重置 scaleminmax，
                        必须成对发）；None = 只发色标方法，不碰 modcolor。
        Returns:
            bool: 是否成功切换
        """
        if not self.port:
            self._log("VMD 未运行，无法切换样式")
            return False

        if style_name not in backend.STYLES:
            self._log(f"未知样式: {style_name}，可选: {list(backend.STYLES.keys())}")
            return False

        # 注意：这里**故意不做**「style_name == self._current_style 就直接
        # return True」的短路。那条短路返回 True 却一个命令都不发，调用方
        # （_on_style_changed）会当成切换成功并记下 _vmd_style_applied，
        # 于是「记录的状态」和「VMD 实际状态」一旦分叉，被记下的那个样式就
        # 再也切不回去了（表现：选了没反应）。重发同一套样式是幂等的，
        # 代价只是一次写文件 + 一次 socket 往返，换掉这一整类静默失败值得。

        sm = shade_mode or "full"

        try:
            if self._mol_mode:
                live_tcl = backend._live_style_tcl_mol(style_name, shade_mode=sm)
            else:
                n_mols = len(self._multi_cubes) if self._multi_cubes else 1
                live_tcl = backend._live_style_tcl(style_name, shade_mode=sm,
                                                   n_mols=n_mols,
                                                   vol_color=vol_color,
                                                   cmap=cmap,
                                                   atom_cpk=atom_cpk,
                                                   vol_range=vol_range)
            tcl_path = os.path.join(self.render_dir, "_live_style.tcl")
            with open(tcl_path, "w", encoding="utf-8") as f:
                f.write(live_tcl)
            resp = self.send_cmd("source _live_style.tcl")
            if resp is not None and "ERROR" not in resp:
                self._current_style = style_name
                style = backend.STYLES[style_name]
                # 同步更新不透明度
                if style["surface_mat"][5] is not None:
                    self._current_opacity = style["surface_mat"][5]
                self._log(f"样式已切换: {style_name}")
                return True
            else:
                self._log(f"样式切换失败: {resp}")
                return False
        except Exception as e:
            self._log(f"样式切换异常: {e}")
            return False

    # ── 实时等值面 / 不透明度调节 ────────────────────────

    def set_isovalue(self, value):
        """实时修改等值面阈值。

        Args:
            value: 新的等值面值 (通常 0.001 ~ 0.5)
        """
        if not self.port:
            self._log("VMD 未运行")
            return

        value = max(0.001, min(value, 0.5))
        rp = self._vmd_state["rep_pos"]
        rn = self._vmd_state["rep_neg"]

        cmd = f"mol modstyle {rp} top Isosurface {value} 0 0 0 1 1 ; mol modstyle {rn} top Isosurface {-value} 0 0 0 1 1"
        resp = self.send_cmd(cmd)
        if resp is not None:
            self._current_isovalue = value
            self._log(f"等值面值: {value:.4f}")

    def set_opacity(self, value):
        """实时修改表面不透明度。

        Args:
            value: 不透明度 (0.0 ~ 1.0)，1.0=完全不透明
        """
        if not self.port:
            self._log("VMD 未运行")
            return

        value = max(0.0, min(value, 1.0))
        if self._multi_cubes:
            n_mols = len(self._multi_cubes)
            for i in range(n_mols):
                for mat_suffix in ["a", "b"]:
                    mat_name = f"_stl_orb_{i}_{mat_suffix}"
                    self.send_cmd(f"material change opacity {mat_name} {value}")
        else:
            for mat_name in ["_stl_a", "_stl_b"]:
                self.send_cmd(f"material change opacity {mat_name} {value}")
        self._current_opacity = value
        self._log(f"不透明度: {value:.3f}")

    # ── 自定义相位颜色 ──────────────────────────────────

    def set_phase_colors(self, pos_rgb=None, neg_rgb=None):
        """设置自定义正/负相位颜色，None 表示恢复样式默认。

        Args:
            pos_rgb: 正相位 (R, G, B) 0-255，None 恢复默认
            neg_rgb: 负相位 (R, G, B) 0-255，None 恢复默认
        """
        if not self.port:
            return

        if pos_rgb is None and neg_rgb is None:
            # 恢复默认：重新 source live_style
            live_tcl = backend._live_style_tcl(
                self._current_style or "sob-art", shade_mode="full",
                n_mols=len(self._multi_cubes) if self._multi_cubes else 1)
            tcl_path = os.path.join(self.render_dir, "_live_color.tcl")
            with open(tcl_path, "w", encoding="utf-8") as f:
                f.write(live_tcl)
            self.send_cmd("source _live_color.tcl")
            self._log("相位颜色已恢复默认")
            return

        rp = self._vmd_state["rep_pos"]
        rn = self._vmd_state["rep_neg"]
        if pos_rgb is not None:
            self.send_cmd(
                f"color change rgb 31 {pos_rgb[0]/255:.4f} {pos_rgb[1]/255:.4f} {pos_rgb[2]/255:.4f}")
            self.send_cmd(f"mol modcolor {rp} top ColorID 31")
        if neg_rgb is not None:
            self.send_cmd(
                f"color change rgb 32 {neg_rgb[0]/255:.4f} {neg_rgb[1]/255:.4f} {neg_rgb[2]/255:.4f}")
            self.send_cmd(f"mol modcolor {rn} top ColorID 32")

    # ── Tachyon 渲染 ────────────────────────────────────

    def render(self, output_png, resolution=(2000, 1500), style=None,
               shade_mode="full", trans_raster=True, threads=4):
        """将当前 VMD 视图渲染为 PNG 图片。

        Args:
            output_png: 输出 PNG 路径
            resolution: (宽, 高) 元组
            style: 渲染样式，None=使用当前样式
            shade_mode: "full" 或 "medium"
            trans_raster: 是否启用 -trans_raster3d
            threads: Tachyon 线程数
        Returns:
            str|None: 成功返回 PNG 路径，失败返回 None
        """
        if not self.port:
            self._log("VMD 未运行，无法渲染")
            return None

        style = style or self._current_style or "sob-art"
        self._log(f"Tachyon 渲染: {style} → {os.path.basename(output_png)}")

        png = backend.render_current_view(
            self.port, self.render_dir, output_png=output_png,
            tachyon_exe=self.tachyon_exe, resolution=resolution,
            style_name=style, shade_mode=shade_mode,
            trans_raster=trans_raster, threads=threads,
            log_func=self._log)

        if png:
            self._log(f"渲染完成: {png}")
        return png

    # ── Socket 通信 ─────────────────────────────────────

    def send_cmd(self, tcl_command):
        """向 VMD 发送 TCL 命令并接收响应。

        使用持久 socket 连接，首次调用自动建立连接。

        Args:
            tcl_command: TCL 命令字符串
        Returns:
            str|None: VMD 响应内容，失败返回 None
        """
        if not self.port:
            return None
        try:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(5)
                self._sock.connect(("127.0.0.1", self.port))
            self._sock.sendall((tcl_command + "\n").encode("utf-8"))
            resp = b""
            try:
                self._sock.settimeout(3.0)
                while True:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in resp:
                        break
            except socket.timeout:
                pass
            self._sock.settimeout(5)
            if not resp:
                # 一个字节都没收到 = 对端没回话。以前这里返回空串 ""，
                # 而调用方判断的是 `resp is not None and "ERROR" not in resp`，
                # 空串会被当成功 —— 于是「其实没执行」被记成「切换成功」，
                # 状态记录就这么和 VMD 实际状态分叉了。返回 None 才是诚实的。
                return None
            return resp.decode("utf-8", errors="replace").strip()
        except Exception as e:
            self._close_socket()
            self._log(f"VMD 通信错误: {e}")
            return None

    # ── 状态查询 ────────────────────────────────────────

    @property
    def is_connected(self):
        """检查 VMD socket 是否仍然连接。"""
        if not self.port:
            return False
        try:
            result = self.send_cmd("puts OK")
            return result is not None and "OK" in result
        except Exception:
            return False

    @property
    def available_styles(self):
        """返回所有可用样式名列表。"""
        return list(backend.STYLES.keys())

    def get_style_info(self, style_name=None):
        """获取样式详细信息。

        Args:
            style_name: 样式名，None 返回当前样式
        Returns:
            dict: 样式配置字典，含 desc, pos_color, neg_color 等
        """
        name = style_name or self._current_style or "sob-art"
        return backend.STYLES.get(name, backend.STYLES["sob-art"])

    # ── Cube 生成（调用 Multiwfn）───────────────────────

    def gen_cube(self, fchk_path, orbital="h", grid_quality=2, work_dir=None):
        """从 fchk 文件生成单个 .cub 文件。

        Args:
            fchk_path: .fchk 文件路径
            orbital: 轨道号 (h/l/h-1/数字)
            grid_quality: 网格质量 (1=低, 2=中, 3=高)
            work_dir: 输出目录，None=与 fchk 同目录
        Returns:
            str|None: 生成的 cube 路径，失败返回 None
        """
        self._log(f"生成 cube: {os.path.basename(fchk_path)} MO={orbital}")
        return backend.gen_cube(
            fchk_path, orbital=orbital, grid_quality=grid_quality,
            work_dir=work_dir, multiwfn_exe=self.multiwfn_exe)

    def gen_multi_cubes(self, fchk_path, orbitals, grid_quality=2, work_dir=None):
        """从 fchk 文件批量生成多个轨道的 .cub 文件。

        Args:
            fchk_path: .fchk 文件路径
            orbitals: 轨道号列表，如 ["h-1","h","l","l+1"]
            grid_quality: 网格质量
            work_dir: 输出目录
        Returns:
            list: [(cube_path, orbital_name), ...]
        """
        self._log(f"批量生成 cube: {os.path.basename(fchk_path)} MO={orbitals}")
        return backend.gen_multi_cubes(
            fchk_path, orbitals, grid_quality=grid_quality,
            work_dir=work_dir, multiwfn_exe=self.multiwfn_exe) or []

    def auto_render(self, cube_path, output_png, isovalue=0.05, style="sob-art",
                    resolution=(2000, 1500), shade_mode="full"):
        """一步完成：从 cube 文件自动渲染 PNG（启动 VMD → 渲染 → 关闭）。

        适合批处理场景，不需要保留 VMD 窗口。

        Args:
            cube_path: .cub 文件路径
            output_png: 输出 PNG 路径
            isovalue: 等值面阈值
            style: 渲染样式
            resolution: 输出分辨率
            shade_mode: "full" 或 "medium"
        Returns:
            str|None: 成功返回 PNG 路径
        """
        backend.render_cube_auto(
            cube_path, output_png=output_png, isovalue=isovalue,
            style_name=style, resolution=resolution,
            vmd_exe=self.vmd_exe, tachyon_exe=self.tachyon_exe,
            shade_mode=shade_mode)
        if os.path.exists(output_png):
            self._log(f"自动渲染完成: {output_png}")
            return output_png
        return None

    # ── 关闭 / 清理 ─────────────────────────────────────

    def close(self):
        """关闭 VMD 会话，释放资源。"""
        self._log("关闭 VMD 会话...")
        self._close_existing()
        self.port = None
        self.render_dir = None

    def _close_existing(self):
        """关闭现有 VMD 连接。"""
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._vmd_state = {"rep_pos": 1, "rep_neg": 2, "molid": 0}

    def _close_socket(self):
        """仅关闭 socket 连接。"""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __repr__(self):
        status = "connected" if self.port else "idle"
        style = self._current_style or "none"
        iso = f"{self._current_isovalue:.3f}" if self._current_isovalue else "N/A"
        return f"<VMDOrbitalSession {status} style={style} iso={iso}>"


# ═══════════════════════════════════════════════════════════════
#  便捷顶层函数
# ═══════════════════════════════════════════════════════════════

def view_cube(cube_path, isovalue=0.05, style="sob-art",
              vmd_exe=None, tachyon_exe=None):
    """快速打开 cube 文件在 VMD 中预览（返回 session，不自动关闭）。

    Args:
        cube_path: .cub 文件路径
        isovalue: 等值面阈值
        style: 渲染样式名
    Returns:
        VMDOrbitalSession: 会话对象，可继续操作
    """
    sess = VMDOrbitalSession(vmd_exe=vmd_exe, tachyon_exe=tachyon_exe)
    ok = sess.load_cube(cube_path, isovalue=isovalue, style=style)
    return sess if ok else None


def cube_to_png(cube_path, output_png, isovalue=0.05, style="sob-art",
                resolution=(2000, 1500), shade_mode="full",
                vmd_exe=None, tachyon_exe=None):
    """一步渲染：cube 文件 → PNG 图片（自动打开/关闭 VMD）。

    适合批处理脚本，整个过程无需人工干预。

    Args:
        cube_path: .cub 文件路径
        output_png: 输出 PNG 路径
        isovalue: 等值面阈值
        style: 渲染样式名
        resolution: (宽, 高)
        shade_mode: "full" 或 "medium"
    Returns:
        str|None: 成功返回 PNG 路径
    """
    sess = VMDOrbitalSession(vmd_exe=vmd_exe, tachyon_exe=tachyon_exe)
    try:
        png = sess.auto_render(
            cube_path, output_png=output_png, isovalue=isovalue,
            style=style, resolution=resolution, shade_mode=shade_mode)
        return png
    finally:
        sess.close()


def fchk_to_png(fchk_path, orbital="h", isovalue=0.05, style="sob-art",
                grid_quality=2, output_png=None, resolution=(2000, 1500),
                vmd_exe=None, tachyon_exe=None, multiwfn_exe=None):
    """从 fchk 文件一步到位生成 PNG（fchk → cube → PNG）。

    Args:
        fchk_path: .fchk 文件路径
        orbital: 轨道号
        isovalue: 等值面阈值
        style: 渲染样式
        grid_quality: 网格质量 (1/2/3)
        output_png: 输出 PNG，None=自动命名
        resolution: 输出分辨率
    Returns:
        str|None: 成功返回 PNG 路径
    """
    sess = VMDOrbitalSession(
        vmd_exe=vmd_exe, tachyon_exe=tachyon_exe, multiwfn_exe=multiwfn_exe)

    cube = sess.gen_cube(fchk_path, orbital=orbital, grid_quality=grid_quality)
    if not cube:
        sess.close()
        return None

    if output_png is None:
        stem = os.path.splitext(os.path.basename(fchk_path))[0]
        out_dir = os.path.dirname(os.path.abspath(cube))
        output_png = os.path.join(out_dir, f"{stem}_MO{orbital}.png")

    try:
        png = sess.auto_render(cube, output_png=output_png, isovalue=isovalue,
                               style=style, resolution=resolution)
        return png
    finally:
        sess.close()


def list_styles():
    """列出所有可用渲染样式及描述。"""
    for name, s in backend.STYLES.items():
        print(f"  {name:20s} — {s.get('desc', '')}")


# ═══════════════════════════════════════════════════════════════
#  命令行入口
# ═══════════════════════════════════════════════════════════════

def main():
    """命令行快速渲染工具。"""
    import argparse
    p = argparse.ArgumentParser(
        description="轨道等值面可视化库 — 命令行快速渲染",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python orbital_viewer_lib.py view MO_50.cub --style ao-shiny
  python orbital_viewer_lib.py render MO_50.cub -o out.png --iso 0.03
  python orbital_viewer_lib.py list-styles
  python orbital_viewer_lib.py full my.fchk --mo h --style sob-art -o out.png
        """)
    sub = p.add_subparsers(dest="cmd")

    # view
    pv = sub.add_parser("view", help="在 VMD 中打开 cube 预览")
    pv.add_argument("cube", help=".cub 文件路径")
    pv.add_argument("--iso", type=float, default=0.05)
    pv.add_argument("--style", default="sob-art")

    # render
    pr = sub.add_parser("render", help="cube → PNG 渲染")
    pr.add_argument("cube", help=".cub 文件路径")
    pr.add_argument("-o", "--output", required=True, help="输出 PNG")
    pr.add_argument("--iso", type=float, default=0.05)
    pr.add_argument("--style", default="sob-art")
    pr.add_argument("--res", default="2000,1500", help="分辨率 w,h")

    # full
    pf = sub.add_parser("full", help="fchk → cube → PNG 全流程")
    pf.add_argument("fchk", help=".fchk 文件路径")
    pf.add_argument("--mo", default="h", help="轨道号")
    pf.add_argument("--iso", type=float, default=0.05)
    pf.add_argument("--style", default="sob-art")
    pf.add_argument("--grid", default="2", choices=["1","2","3"])
    pf.add_argument("-o", "--output", help="输出 PNG")
    pf.add_argument("--res", default="2000,1500")

    # list-styles
    _ = sub.add_parser("list-styles", help="列出所有样式")

    args = p.parse_args()

    if args.cmd == "list-styles":
        list_styles()
    elif args.cmd == "view":
        sess = view_cube(args.cube, isovalue=args.iso, style=args.style)
        if sess:
            print(f"VMD 已启动，按 Ctrl+C 退出...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                sess.close()
    elif args.cmd == "render":
        res = tuple(int(x) for x in args.res.split(","))
        png = cube_to_png(args.cube, args.output, isovalue=args.iso,
                          style=args.style, resolution=res)
        print(f"完成: {png}" if png else "渲染失败")
    elif args.cmd == "full":
        res = tuple(int(x) for x in args.res.split(","))
        png = fchk_to_png(args.fchk, orbital=args.mo, isovalue=args.iso,
                          style=args.style, grid_quality=int(args.grid),
                          output_png=args.output, resolution=res)
        print(f"完成: {png}" if png else "失败")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
