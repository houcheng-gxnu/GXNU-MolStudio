# -*- coding: utf-8 -*-
"""
esp_panel.py — ESP 表面可视化面板（整合自 ESPViewer v3.0）
===========================================================

从 `.fchk` 出发：
  1. 后台调 Multiwfn 生成电子密度 cube (density.cub) 与静电势 cube (ESP.cub)，
     以及极值点 (surfanalysis.pdb)、分区面积分布；
  2. 复用 esp_viewer.extract_esp_surface —— 密度场定几何（vdW 等值面）、
     ESP 场定顶点连续着色（默认 RWB：红=负电势/富电子，蓝=正电势/缺电子）；
  3. 把表面加载到左侧 OpenGL 画布显示。

支持四种模式（移植自 ESPViewer）：
  * ISO —— 等值面三角网格；
  * PT  —— 顶点着色点云（画布 PT 模式）；
  * EXT —— 极值点标注（金=极大、浅蓝=极小小球，叠加在表面上）；
  * ALL —— 等值面 + 极值点。

另有：画布内色标条、分区面积分布图（matplotlib）、多分子合并预览。

本模块 Multiwfn 命令模板与解析移植自 ESPViewer
(scr/multiwfn_runner.py, scr/area_chart.py, scr/main_window.py)。
"""

import os
import re
import shutil
import subprocess
import tempfile
import traceback

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QSlider, QRadioButton, QTextEdit, QFileDialog,
    QMessageBox, QFrame, QDoubleSpinBox, QDialog, QFormLayout, QSpinBox,
    QDialogButtonBox, QScrollArea, QGridLayout, QGroupBox, QProgressBar,
    QSizePolicy, QFontComboBox, QMenu,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QCursor, QFont
from molstudio.ui.file_dialogs import open_file, open_files, save_file, existing_directory

from molstudio.core.marching_cubes import read_cube, compute_bounding_sphere, marching_cubes, _trilinear

# ── 进度解析（移植自 ESPViewer2/esp_surface_gui.py） ──
_PROGRESS_PATTERNS = [
    (re.compile(r'(\d+(?:\.\d+)?)\s*%', re.IGNORECASE), 'pct'),
    (re.compile(r'(\d+)\s*/\s*(\d+)', re.IGNORECASE), 'frac'),
]


def _parse_progress(line):
    """从 Multiwfn 输出行提取进度。

    Returns (value: float 0.0-1.0 or None, msg: str)。
    """
    for pat, kind in _PROGRESS_PATTERNS:
        m = pat.search(line)
        if m:
            if kind == 'pct':
                return min(float(m.group(1)) / 100.0, 1.0), line.strip()
            elif kind == 'frac':
                num, den = int(m.group(1)), int(m.group(2))
                if den > 0:
                    return min(num / den, 1.0), line.strip()
    return None, line.strip()
from molstudio.render.ovcanvas._glwidget import (
    merge_iso_surfaces, ANGSTROM_TO_BOHR,
    _GLOSS_DEFAULT,
    MOL_STYLE_DISPLAY, MOL_STYLE_NAMES,
    # 导出图片格式支持（PNG / JPG / TIFF / SVG）
    export_dialog_filter, export_ext_for, export_ext_from_path,
    export_ext_from_filter, export_ensure_suffix,
    export_format_supports_alpha,
)
from molstudio.panels.esp_viewer import (
    extract_esp_surface, ESP_CMAPS,
    DEFAULT_ISOLEVEL, DEFAULT_VMIN, DEFAULT_VMAX,
)
import numpy as np
import matplotlib
matplotlib.use("Qt5Agg")
# matplotlib 图表支持中文：默认字体链加入微软雅黑（否则中文标题/轴标签显示方块）。
# 仅影响 matplotlib 绘制的图（面积分布等），Qt 界面文字不受影响。
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC",
    "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as _FigureCanvas
from matplotlib.figure import Figure as _MplFigure


# ── 子对话框 i18n（构造时按当前语言求值；key = 中文原文）──
_CV_EN = {'ESP 面积分布 – 分区设置': 'ESP Area Distribution – Bin Settings', '最小值 (kcal/mol):': 'Min (kcal/mol):', '最大值 (kcal/mol):': 'Max (kcal/mol):', '分区数:': 'Bins:', '单位提示: 1 eV = 23.06 kcal/mol; 1 Hartree = 627.51 kcal/mol': 'Units: 1 eV = 23.06 kcal/mol; 1 Hartree = 627.51 kcal/mol', 'ESP 表面分区面积分布': 'ESP Area Distribution', '标题与坐标轴': 'Title & Axes', 'X 轴范围': 'X Range', '样式设置': 'Style', '标注': 'Annotations', '字号设置': 'Font Sizes', '多文件': 'Multi-file', '输出': 'Output', '标题': 'Title', 'X 轴标签': 'X label', 'Y 轴标签': 'Y label', 'Y 轴数据': 'Y data', '最小值': 'Min', '最大值': 'Max', '配色 (colormap)': 'Colormap', '透明度': 'Opacity', '刻度字号': 'Tick font', '数值字号': 'Value font', '标题字号': 'Title font', '轴标签字号': 'Axis label font', '文件': 'File', '图宽 (inch)': 'Width (inch)', '图高 (inch)': 'Height (inch)', '自定义范围': 'Custom range', '网格线': 'Grid', '图例': 'Legend', '标记最高/最低点': 'Mark max/min points', '水平参考线': 'Horizontal ref. line', '显示柱顶数值': 'Show bar values', '叠加模式': 'Overlay mode', '面积 (Å²)': 'Area (Å²)', '百分比 (%)': 'Percent (%)', '柱状图': 'Bar', '折线图': 'Line', '导出 CSV': 'Export CSV', '保存图片': 'Save Image', '关闭': 'Close', '提示': 'Notice', '导出失败': 'Export Failed'}

def _cv(text):
    """子对话框文本翻译：zh 原样返回，en 查 _CV_EN（无条目返回原文）。"""
    import molstudio.core.i18n as _i18n
    if _i18n._CURRENT_LANG == "zh":
        return text
    return _CV_EN.get(text, text)


# ── Multiwfn 命令模板（移植自 ESPViewer multiwfn_runner.py） ──
# ISO: 生成 density.cub 与 totesp.cub
CMD_ESPISO = "\n5\n1\n3\n2\n0\n5\n12\n1\n2\n"
# EXT: 分子表面极值点分析 → surfanalysis.pdb
CMD_ESPEXT = "\n12\n3\n0.15\n0\n5\nmol.pdb\n6\n2\n"
# Area: ESP 分区面积分布
CMD_ESP_AREA_DIST = "\n12\n0\n9\nall\n"
ESPRHOISO = "0.001"


# ═══════════════════════════════════════════════════════════════
# 解析函数（纯文本）
# ═══════════════════════════════════════════════════════════════

def parse_extrema_pdb(pdb_path):
    """解析 Multiwfn 的 surfanalysis.pdb（极值点）。

    每行 HETATM/ATOM：坐标在 31-54 列，beta 在 61-66 列（ESP 数值），
    原子名 13-16 列：'C' = 极大值，'O' = 极小值。
    返回 [(kind, x, y, z, value), ...]，坐标 Å。移植自 ESPViewer。
    """
    pts = []
    try:
        with open(pdb_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                rec = line[:6].strip()
                if rec not in ("ATOM", "HETATM"):
                    continue
                if len(line) < 66:
                    continue
                name = line[12:16].strip()
                try:
                    x = float(line[30:38]); y = float(line[38:46])
                    z = float(line[46:54]); beta = float(line[60:66])
                except ValueError:
                    continue
                if name.upper().startswith("C"):
                    kind = "max"
                elif name.upper().startswith("O"):
                    kind = "min"
                else:
                    continue
                pts.append((kind, x, y, z, beta))
    except OSError:
        return []
    return pts


def parse_area_output(stdout):
    """解析 Multiwfn 面积分布输出 → [(center, area, pct), ...]。移植自 ESPViewer。"""
    data = []
    lines = stdout.split("\n")
    ncols = 3
    header_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if 'Begin' in stripped and 'End' in stripped and 'Center' in stripped:
            ncols = 5
            header_idx = i
            break
        if 'Center' in stripped and 'Area' in stripped and 'Begin' not in stripped:
            ncols = 3
            header_idx = i
            break
    if header_idx < 0:
        return data
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            if data:
                break
            continue
        if stripped.startswith('Sum') or stripped.startswith('---') or \
           stripped.startswith('===') or 'Area unit' in stripped:
            continue
        nums = re.findall(r'[-+]?\d+\.?\d*', stripped)
        if ncols == 5:
            if len(nums) >= 5:
                try:
                    data.append((float(nums[2]), float(nums[3]), float(nums[4])))
                except ValueError:
                    continue
        else:
            if len(nums) >= 3:
                try:
                    data.append((float(nums[0]), float(nums[1]), float(nums[2])))
                except ValueError:
                    continue
    return data


def plot_esp_area_histogram(area_data, output_path,
                            title="ESP Area Distribution",
                            xlabel="ESP (kcal/mol)"):
    """把面积分布数据画成 RWB 配色柱状图（matplotlib，静态 PNG）。移植自 ESPViewer。
    RWB（红-白-蓝）：低值红=负电势/富电子，高值蓝=正电势/缺电子。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except Exception:
        return None
    if not area_data:
        return None
    centers = [d[0] for d in area_data]
    areas = [d[1] for d in area_data]
    bin_width = centers[1] - centers[0] if len(centers) > 1 else 2.0
    dmin, dmax = min(centers), max(centers)
    pad = max(0.5, (dmax - dmin) * 0.05)
    norm = mcolors.TwoSlopeNorm(vmin=dmin - pad, vcenter=0, vmax=dmax + pad)
    cmap_rwb = plt.get_cmap('bwr_r')
    colors = [cmap_rwb(norm(c)) for c in centers]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(centers, areas, width=bin_width * 0.92, align='center',
                  color=colors, edgecolor='#333333', linewidth=0.8)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel('Surface Area (Å²)', fontsize=12)
    ax.set_title(title, fontsize=13, fontweight='bold')
    ax.set_xticks(centers)
    ax.set_xticklabels([f'{c:.1f}' for c in centers],
                       rotation=45, ha='right', fontsize=8)
    max_area = max(areas) if max(areas) > 0 else 1
    for bar, val in zip(bars, areas):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2.,
                    bar.get_height() + max_area * 0.02,
                    f'{val:.1f}', ha='center', va='bottom',
                    fontsize=7, rotation=90, color='#333333')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_xlim(centers[0] - bin_width, centers[-1] + bin_width)
    ax.set_ylim(0, max_area * 1.18)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return output_path


# ═══════════════════════════════════════════════════════════════
# 后台线程
# ═══════════════════════════════════════════════════════════════

class EspWorker(QThread):
    """ESP 管线：Multiwfn cube/极值点 → 提取表面 → 合并（可选）。"""
    finished = pyqtSignal(object)   # result dict
    error = pyqtSignal(str)
    progress = pyqtSignal(str)      # 原始输出行（进运行日志）
    progress_val = pyqtSignal(int)  # 总体进度 0-100（进度条）
    stage_msg = pyqtSignal(str)     # 简短计算信息（进度条旁标签）

    def __init__(self, fchk_list, mw_exe, mode, isolevel, vmin, vmax,
                 cmap, auto_range, invert=False):
        super().__init__()
        self.fchk_list = fchk_list
        self.mw_exe = mw_exe
        self.mode = mode          # iso / pt / ext / all / merge
        self.isolevel = isolevel
        self.vmin = vmin
        self.vmax = vmax
        self.cmap = cmap
        self.auto_range = auto_range
        self.invert = invert
        self._proc = None
        self._file_idx = 0        # 当前处理文件下标（进度映射用）

    def kill(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def _run_multiwfn(self, cmd_string, work_dir, fch_name, extra="",
                      stage_lo=0.0, stage_hi=0.85):
        cmd_file = os.path.join(work_dir, "_mw_cmd.txt")
        with open(cmd_file, "w", encoding="ascii") as f:
            f.write(cmd_string)
        cmd = f'"{self.mw_exe}" "{fch_name}" {extra} < _mw_cmd.txt'
        self._proc = subprocess.Popen(
            cmd, shell=True, cwd=work_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        n_files = max(len(self.fchk_list), 1)
        file_base = self._file_idx / n_files
        span = stage_hi - stage_lo
        out_lines = []
        for line in self._proc.stdout:
            out_lines.append(line)
            stripped = line.rstrip()
            if len(stripped) > 100:
                stripped = stripped[:97] + "..."
            self.progress.emit(stripped)
            pct, _ = _parse_progress(stripped)
            if pct is not None:
                frac = stage_lo + span * pct
                self.progress_val.emit(int((file_base + frac / n_files) * 100))
                self.stage_msg.emit(
                    "[%d/%d] %d%%" % (self._file_idx + 1, n_files,
                                      int(pct * 100)))
        self._proc.wait()
        return self._proc.returncode, "".join(out_lines)

    def _ensure_cubes(self, fchk):
        """生成（或复用归档的）density.cub / ESP.cub，返回 (density, esp)。"""
        stem = os.path.splitext(os.path.basename(fchk))[0]
        arch_dir = os.path.join(os.path.dirname(os.path.abspath(fchk)), f"{stem}_ESP")
        density_path = os.path.join(arch_dir, "density.cub")
        esp_path = os.path.join(arch_dir, "ESP.cub")
        if not (os.path.exists(density_path) and os.path.exists(esp_path)):
            self.stage_msg.emit(f"运行 Multiwfn 生成 density/ESP cube（{stem}）…")
            self.progress.emit(f"运行 Multiwfn 生成 density/ESP cube（{stem}）…")
            tmp = tempfile.mkdtemp(prefix="esp_")
            try:
                fch_name = "sys1.fch"
                shutil.copy2(fchk, os.path.join(tmp, fch_name))
                rc, _ = self._run_multiwfn(
                    CMD_ESPISO, tmp, fch_name, f"-ESPrhoiso {ESPRHOISO}",
                    stage_lo=0.0, stage_hi=0.85)
                if rc not in (0, 24):
                    raise RuntimeError(f"Multiwfn 退出码 {rc}")
                d_src = os.path.join(tmp, "density.cub")
                e_src = os.path.join(tmp, "totesp.cub")
                if not (os.path.exists(d_src) and os.path.exists(e_src)):
                    raise RuntimeError("Multiwfn 未生成 density.cub / totesp.cub")
                os.makedirs(arch_dir, exist_ok=True)
                shutil.move(d_src, density_path)
                shutil.move(e_src, esp_path)
            finally:
                try:
                    shutil.rmtree(tmp)
                except OSError:
                    pass
        else:
            self.stage_msg.emit(f"复用已归档 cube：{os.path.basename(arch_dir)}")
            self.progress.emit(f"复用已归档 cube：{os.path.basename(arch_dir)}")
        n_files = max(len(self.fchk_list), 1)
        file_base = self._file_idx / n_files
        self.progress_val.emit(int((file_base + 0.85 / n_files) * 100))
        return read_cube(density_path), read_cube(esp_path)

    def _run_extrema(self, fchk):
        """跑 CMD_ESPEXT，返回 [(kind, x, y, z, value)] Å 或 []。"""
        # ext 单独模式无 cube 生成阶段：极值点占满整个文件切片
        if self.mode == "ext":
            lo, hi = 0.0, 0.95
        else:  # all：cube 阶段已占 [0, 0.85]
            lo, hi = 0.85, 0.95
        self.stage_msg.emit("运行 Multiwfn 极值点分析 …")
        self.progress.emit("运行 Multiwfn 极值点分析 …")
        tmp = tempfile.mkdtemp(prefix="espext_")
        try:
            fch_name = "sys1.fch"
            shutil.copy2(fchk, os.path.join(tmp, fch_name))
            rc, _ = self._run_multiwfn(CMD_ESPEXT, tmp, fch_name,
                                       stage_lo=lo, stage_hi=hi)
            if rc not in (0, 24):
                raise RuntimeError(f"Multiwfn 退出码 {rc}")
            pdb = os.path.join(tmp, "surfanalysis.pdb")
            if not os.path.exists(pdb):
                self.progress.emit("未找到 surfanalysis.pdb（该体系可能无极值点输出）")
                return []
            pts = parse_extrema_pdb(pdb)
            return pts
        finally:
            try:
                shutil.rmtree(tmp)
            except OSError:
                pass

    def run(self):
        result = {"mode": self.mode}
        try:
            surfs = []
            first_density = None
            n_files = max(len(self.fchk_list), 1)
            for file_idx, fchk in enumerate(self.fchk_list):
                self._file_idx = file_idx
                self.stage_msg.emit(
                    "[%d/%d] %s" % (self._file_idx + 1, n_files,
                                    os.path.basename(fchk)))
                if self.mode in ("iso", "pt", "all", "merge"):
                    density, esp = self._ensure_cubes(fchk)
                    if first_density is None:
                        first_density = density
                    self.stage_msg.emit("提取 ESP 表面 …")
                    self.progress.emit("提取 ESP 表面 …")
                    surf, _ = extract_esp_surface(
                        density, esp,
                        isolevel=self.isolevel,
                        vmin=self.vmin, vmax=self.vmax,
                        cmap=self.cmap, auto_range=self.auto_range,
                        invert=self.invert)
                    if surf.vertex_count == 0:
                        self.progress.emit("该体系密度等值面为空，跳过")
                        continue
                    surfs.append(surf)
                    # 表面提取阶段：本文件切片内 0.85 → 0.97
                    self.progress_val.emit(
                        int((self._file_idx + 0.97 / n_files) * 100))
                if self.mode in ("ext", "all"):
                    pts = self._run_extrema(fchk)
                    result["extrema"] = pts
                # 本文件完成：切片结束
                self.progress_val.emit(
                    int((self._file_idx + 1) / n_files * 100))
            if surfs:
                if len(surfs) == 1:
                    result["surf"] = surfs[0]
                else:
                    result["surf"] = merge_iso_surfaces(surfs)
                result["density"] = first_density
                result["n_merged"] = len(surfs)
            self.finished.emit(result)
        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))


class EspAreaWorker(QThread):
    """分区面积分布：Multiwfn → 解析 → 柱状图 + 数据文件。"""
    finished = pyqtSignal(object)   # dict: files / area_data
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, fchk_list, mw_exe, range_low, range_high, n_bins):
        super().__init__()
        self.fchk_list = fchk_list
        self.mw_exe = mw_exe
        self.range_low = range_low
        self.range_high = range_high
        self.n_bins = n_bins
        self._proc = None

    def kill(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def run(self):
        try:
            all_data = []
            results = []
            for fchk in self.fchk_list:
                stem = os.path.splitext(os.path.basename(fchk))[0]
                tmp = tempfile.mkdtemp(prefix="esparea_")
                try:
                    fch_name = "sys1.fch"
                    shutil.copy2(fchk, os.path.join(tmp, fch_name))
                    cmd = (CMD_ESP_AREA_DIST +
                           f"{self.range_low},{self.range_high}\n{self.n_bins}\n3\nn\n")
                    cmd_file = os.path.join(tmp, "_mw_cmd.txt")
                    with open(cmd_file, "w", encoding="ascii") as f:
                        f.write(cmd)
                    cmdline = f'"{self.mw_exe}" "{fch_name}" < _mw_cmd.txt'
                    self._proc = subprocess.Popen(
                        cmdline, shell=True, cwd=tmp,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        bufsize=1)
                    out_lines = []
                    for line in self._proc.stdout:
                        out_lines.append(line)
                        self.progress.emit(line.rstrip()[-90:])
                    self._proc.wait()
                    data = parse_area_output("".join(out_lines))
                finally:
                    try:
                        shutil.rmtree(tmp)
                    except OSError:
                        pass
                if not data:
                    self.progress.emit(f"{stem}: 未解析到面积分布数据")
                    continue
                all_data.append((os.path.basename(fchk), data))
                out_dir = os.path.dirname(os.path.abspath(fchk))
                chart = os.path.join(out_dir, f"{stem}_esp_area.png")
                if plot_esp_area_histogram(
                        data, chart, title=f"ESP Area Distribution - {stem}"):
                    results.append(chart)
                data_path = os.path.join(out_dir, f"{stem}_esp_area_data.txt")
                with open(data_path, "w", encoding="utf-8") as f:
                    f.write("Center(kcal/mol)\tArea(Ang^2)\tPercentage(%)\n")
                    for center, area, pct in data:
                        f.write(f"{center:.4f}\t{area:.4f}\t{pct:.4f}\n")
                results.append(data_path)
            self.finished.emit({"files": results, "area_data": all_data})
        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════
# ESP 面板
# ═══════════════════════════════════════════════════════════════

_ESP_TR = {
    "zh": {
        "open_fchk": "打开 fchk…",
        "merge": "合并预览…",
        "generate": "生成 ESP 表面",
        "area": "📊 分区面积图",
        "reset_view": "重置视角",
        "clear": "清空",
        "multiwfn": "Multiwfn:",
        "browse": "浏览",
        "load_cubdir": "载入 cub 文件夹:",
        "placeholder_cubdir": "选择含 density*.cub / ESP*.cub 的文件夹…",
        "load_cub_ok": "已载入 cub 文件夹（{n} 对），直接绘制等值面（未运行 Multiwfn）",
        "load_cub_none": "所选文件夹未找到 density*.cub 与 ESP*.cub 文件",
        "load_cub_fail": "绘制等值面失败: {err}",
        "mode": "模式:",
        "iso": "ISO 等值面",
        "pt": "PT 点云",
        "ext": "EXT 极值点",
        "all": "ALL 叠加",
        "pt_size": "点大小:",
        "cs_show": "显示色标条",
        "cs_settings": "色标轴设置…",
        "isolevel": "密度等值面:",
        "vmin": "色标下限:",
        "vmax": "色标上限:",
        "auto_range": "自动范围",
        "cmap": "配色:",
        "invert": "翻转配色",
        "opacity": "不透明度:",
        "unit_hint": "(a.u.)",
        "status_ready": "就绪 — 打开 fchk 选模式后点「生成 ESP 表面」",
        "no_fchk": "请先打开 .fchk 文件",
        "no_exe": "Multiwfn.exe 不存在，请先在主界面⛒️ 路径设置中配置",
        "generating": "正在运行 Multiwfn（首次需数分钟，请耐心等待）…",
        "ops_grp": "操作",
        "display": "显示设置",
        "done": "ESP 表面已加载（{n} 顶点，{m} 个分子）",
        "done_pt": "PT 点云已加载（{n} 顶点）",
        "done_ext": "极值点：{n} 个（金=极大、浅蓝=极小）",
        "empty": "未提取到有效表面",
        "area_done": "面积分布图完成: {n} 个文件",
        "render_surface": "渲染 ESP 表面",
        "detect_range": "检测 ESP 范围",
        "detect_no_cube": "未找到当前分子的 density.cub / ESP.cub，请先生成 ESP 表面",
        "detect_done": "已检测 ESP 范围：{lo:g} ~ {hi:g} ({unit})",
        "detect_fail": "检测 ESP 范围失败: {err}",
        "transparent_bg": "透明背景",
        "dpi_label": "导出图片 DPI:",
        "export_image": "导出图片",
        "fmt_png": "PNG — 无损 · 支持透明",
        "fmt_jpg": "JPG — 有损压缩 · 体积小",
        "fmt_tif": "TIFF — 无损 · 支持透明",
        "fmt_svg": "SVG — 矢量容器（内嵌位图）",
        "export_png": "导出 PNG",
        "export_done": "已导出: {path} (DPI={dpi}{trans})",
        "export_jpg_note": "（JPG 不支持透明背景，已合成到画布底色）",
        "ticks_label": "刻度段数:",
        "orient_label": "方位:",
        "orient_v": "竖直",
        "orient_h": "水平",
        "cs_len": "长度:",
        "unit_changed": "能量单位已切换为 {unit}",
        "canvas_ctl": "画布控制",
        "unit_label": "单位:",
        "param_grp": "显示参数",
        "iso_mat": "材质光泽:",
        "iso_peel": "深度剥离透明合成",
        "atom_style": "配色方案:",
        "atom_r": "原子半径:",
        "bond_r": "键半径:",
        "thinning": "收腰效果:",
        "ext_spheres": "显示极值点小球",
        "ext_labels": "显示极值点数值",
        "ext_border": "数字加边框/白底背景",
        "ext_font": "标签字号:",
        "ext_radius": "小球半径:",
        "ext_dist": "标签距离:",
    },
    "en": {
        "open_fchk": "Open fchk…",
        "merge": "Merge…",
        "generate": "Generate ESP",
        "area": "📊 Area Chart",
        "reset_view": "Reset View",
        "clear": "Clear",
        "multiwfn": "Multiwfn:",
        "browse": "Browse",
        "load_cubdir": "Load cub folder:",
        "placeholder_cubdir": "Choose a folder containing density*.cub / ESP*.cub…",
        "load_cub_ok": "Loaded cub folder ({n} pair(s)) and drew the isosurface (no Multiwfn run)",
        "load_cub_none": "No density*.cub / ESP*.cub found in the selected folder",
        "load_cub_fail": "Failed to draw isosurface: {err}",
        "mode": "Mode:",
        "iso": "ISO surface",
        "pt": "PT points",
        "ext": "EXT extrema",
        "all": "ALL overlay",
        "pt_size": "Point size:",
        "cs_show": "Color scale bar",
        "cs_settings": "Color scale setup…",
        "isolevel": "Density isolevel:",
        "vmin": "Color min:",
        "vmax": "Color max:",
        "auto_range": "Auto range",
        "cmap": "Colormap:",
        "invert": "Invert",
        "opacity": "Opacity:",
        "unit_hint": "(a.u.)",
        "status_ready": "Ready — open fchk, pick mode, then Generate ESP",
        "no_fchk": "Please open an .fchk file first",
        "no_exe": "Multiwfn.exe not found, configure it in ⛒️ Path Settings first",
        "generating": "Running Multiwfn (first run takes minutes)…",
        "ops_grp": "Actions",
        "display": "Display",
        "done": "ESP surface loaded ({n} vertices, {m} molecule(s))",
        "done_pt": "PT point cloud loaded ({n} vertices)",
        "done_ext": "Extrema: {n} (gold=max, light-blue=min)",
        "empty": "No valid surface extracted",
        "area_done": "Area charts done: {n} files",
        "render_surface": "Render ESP Surface",
        "detect_range": "Detect ESP Range",
        "detect_no_cube": "density.cub / ESP.cub not found for this molecule — generate the ESP surface first",
        "detect_done": "ESP range detected: {lo:g} ~ {hi:g} ({unit})",
        "detect_fail": "ESP range detection failed: {err}",
        "transparent_bg": "Transparent BG",
        "dpi_label": "Export DPI:",
        "export_image": "Export Image",
        "fmt_png": "PNG — lossless · alpha",
        "fmt_jpg": "JPG — lossy · small file",
        "fmt_tif": "TIFF — lossless · alpha",
        "fmt_svg": "SVG — vector container (raster inside)",
        "export_png": "Export PNG",
        "export_done": "Exported: {path} (DPI={dpi}{trans})",
        "export_jpg_note": "(JPG has no alpha; composited onto the canvas background)",
        "ticks_label": "Ticks:",
        "orient_label": "Orient:",
        "orient_v": "Vertical",
        "orient_h": "Horizontal",
        "cs_len": "Length:",
        "unit_changed": "Energy unit switched to {unit}",
        "canvas_ctl": "Canvas Control",
        "unit_label": "Unit:",
        "param_grp": "Display Params",
        "iso_mat": "Shininess:",
        "iso_peel": "Depth-peeling transparency",
        "atom_style": "Atom style:",
        "atom_r": "Atom radius:",
        "bond_r": "Bond radius:",
        "thinning": "Bond thinning:",
        "ext_spheres": "Show extrema spheres",
        "ext_labels": "Show extrema values",
        "ext_border": "Label border / white bg",
        "ext_font": "Label font:",
        "ext_radius": "Sphere radius:",
        "ext_dist": "Label offset:",
    },
}


class ColorScaleFontDialog(QDialog):
    """色彩刻度轴的字体设置（字体族 / 字号 + 实时预览）。

    改动即时生效（直接调 ``glw.set_color_scale_font``），所以调的时候画布上
    的色标条同步变化；点「取消」会恢复打开对话框时的字体。
    说明：刻度字体原本只挂在"右键点画布色标条"的菜单里，不容易发现，
    因此在 ESP 面板的参数区补了一个入口按钮。
    """

    DEFAULT = ("Arial", 10)

    def __init__(self, glw, parent=None, lang="zh"):
        super().__init__(parent)
        self.glw = glw
        self._lang = "en" if str(lang).startswith("en") else "zh"
        self._orig = (str(getattr(glw, "_cs_font_family", self.DEFAULT[0])),
                      int(getattr(glw, "_cs_font_pt", self.DEFAULT[1])))
        zh = self._lang == "zh"
        self.setWindowTitle("色彩刻度轴字体" if zh else "Color scale font")
        self.setMinimumWidth(360)

        form = QFormLayout(self)
        self.cb_family = QFontComboBox()
        self.cb_family.setCurrentFont(QFont(*self._orig))
        form.addRow("字体" if zh else "Family", self.cb_family)

        self.sp_size = QSpinBox()
        self.sp_size.setRange(6, 48)
        self.sp_size.setValue(self._orig[1])
        self.sp_size.setSuffix(" pt")
        self.sp_size.setMaximumWidth(90)
        form.addRow("字号" if zh else "Size", self.sp_size)

        self.lbl_preview = QLabel("ESP (kcal/mol)   0.03")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(56)
        self.lbl_preview.setStyleSheet(
            "border:1px solid #B8C2D0; border-radius:6px; background:#FFFFFF;")
        form.addRow("预览" if zh else "Preview", self.lbl_preview)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_default = bb.addButton(
            "恢复默认" if zh else "Default", QDialogButtonBox.ResetRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.btn_default.clicked.connect(self._restore_default)
        form.addRow(bb)

        self.cb_family.currentFontChanged.connect(self._apply)
        self.sp_size.valueChanged.connect(self._apply)
        self._apply()

    def _current(self):
        return (self.cb_family.currentFont().family(), int(self.sp_size.value()))

    def _apply(self, *_a):
        fam, pt = self._current()
        self.glw.set_color_scale_font(fam, pt)
        f = QFont(fam, pt)
        f.setHintingPreference(QFont.PreferFullHinting)
        self.lbl_preview.setFont(f)

    def _restore_default(self):
        self.cb_family.setCurrentFont(QFont(self.DEFAULT[0], self.DEFAULT[1]))
        self.sp_size.setValue(self.DEFAULT[1])
        self._apply()

    def reject(self):
        """取消：恢复打开对话框时的字体（改动是即时生效的）。"""
        self.glw.set_color_scale_font(*self._orig)
        super().reject()


#: 补充语言表：切语言时对整棵控件树套用（见 molstudio/ui/i18n_utils.py）
_LANG_EXTRA = {
    # 色标配色下拉
    "CPK (按元素)": "CPK (by element)",
    "BWR (蓝-白-红)": "BWR (blue-white-red)",
    "RWB (红-白-蓝)": "RWB (red-white-blue)",
    "BWG (蓝-白-绿)": "BWG (blue-white-green)",
    "RWG (红-白-绿)": "RWG (red-white-green)",
    "VESTA (VESTA 配色)": "VESTA (VESTA palette)",
    "Vcube (VMD 风格)": "Vcube (VMD style)",
    "VMD (碳金色)": "VMD (carbon-gold)",
    "彩虹 HSV": "Rainbow HSV",
    "彩虹 Jet": "Rainbow Jet",
    "彩虹 Turbo": "Rainbow Turbo",
    "彩虹 NCAR": "Rainbow NCAR",
    "彩虹 NipySpectral": "Rainbow NipySpectral",
    "冰火 IceFire": "IceFire",
    "灰度出版": "Grayscale (print)",
    "霓虹": "Neon",
    "单色白": "Monochrome white",
    # 按钮 tooltip
    "从已生成的 density/ESP cube 重新提取表面（不重跑 Multiwfn）":
        "Re-extract the surface from existing density/ESP cubes (without re-running Multiwfn)",
    "统计分子等值面上的 ESP 极值并填入色标上下限":
        "Compute ESP extrema on the molecular isosurface and use them as the color-scale limits",
    "色彩刻度轴的字体设置（字体族 / 字号，带实时预览）。\n原来只能右键点画布上的色标条，这里给出入口。":
        "Font settings for the color-scale axis (family / size, live preview).\n"
        "Previously this was only reachable by right-clicking the color bar on the canvas.",
    "导出时背景设为透明（alpha=0）。对 PNG / TIFF / SVG 有效；JPG 无 alpha 通道，会合成到画布底色。":
        "Export with a transparent background (alpha = 0). Applies to PNG / TIFF / SVG; "
        "JPG has no alpha channel and is composited onto the canvas background.",
    "导出 ESP 表面图片 —— 点开选择格式：\n"
    "  PNG  无损，支持透明背景\n"
    "  JPG  有损压缩，体积小（不支持透明）\n"
    "  TIFF 无损，支持透明背景\n"
    "  SVG  矢量容器（内嵌满分辨率位图）":
        "Export an ESP surface image — click to choose a format:\n"
        "  PNG  lossless, transparent background supported\n"
        "  JPG  lossy, small files (no transparency)\n"
        "  TIFF lossless, transparent background supported\n"
        "  SVG  vector container (embeds a full-resolution bitmap)",
}


class EspPanel(QWidget):
    """ESP 表面面板：fchk → Multiwfn cube/极值点 → 左画布渲染（ISO/PT/EXT/ALL）。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None, parent=None,
                 get_multiwfn=None, on_vmd_refresh=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path or ""
        self._get_fchk = get_fchk or (lambda: None)
        # VMD 刷新回调（主窗口注入：检测/自动范围等改变范围后刷新已连接的 VMD）
        self._on_vmd_refresh = on_vmd_refresh
        # Multiwfn 路径统一走主窗口 ⚙️ 路径设置（实时读取）
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        self.fchk_file = None
        self._worker = None
        self._last_fchk_list = None   # 最近一次分析使用的 fchk 列表（VMD 同步用）
        self._loaded_cub_pairs = None # 载入的 cub 文件夹配对 [(density.cub, ESP.cub), ...]；None=用 fchk 归档
        self._area_worker = None
        self._mode = "iso"
        self._extrema_pts = []   # [(kind, x, y, z, value)] Å
        self._unit = "kcal/mol"  # 色标显示单位：kcal/mol / a.u.（渲染统一用 a.u.）

        self._build_ui()
        self._apply_lang()

    # ── 语言 ──
    def _t(self, key, **fmt):
        s = _ESP_TR.get(self.lang, _ESP_TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def _apply_lang(self):
        self.btn_merge.setText(self._t("merge"))
        self.btn_generate.setText(self._t("generate"))
        self.btn_area.setText(self._t("area"))
        self.btn_reset.setText(self._t("reset_view"))
        self.btn_clear.setText(self._t("clear"))
        self.lbl_cubdir.setText(self._t("load_cubdir"))
        self.edit_cubdir.setPlaceholderText(self._t("placeholder_cubdir"))
        self.btn_browse_cubdir.setText(self._t("browse"))
        self.lbl_mode.setText(self._t("mode"))
        self.rb_iso.setText(self._t("iso"))
        self.rb_pt.setText(self._t("pt"))
        self.rb_ext.setText(self._t("ext"))
        self.rb_all.setText(self._t("all"))
        self.lbl_ptsize.setText(self._t("pt_size"))
        self.chk_cs.setText(self._t("cs_show"))
        self.btn_cs_settings.setText(self._t("cs_settings"))
        self.lbl_iso.setText(self._t("isolevel"))
        self.lbl_vmin.setText(self._t("vmin"))
        self.lbl_vmax.setText(self._t("vmax"))
        self.chk_auto.setText(self._t("auto_range"))
        self.lbl_cmap.setText(self._t("cmap"))
        self.lbl_invert.setText(self._t("invert"))
        self.lbl_op.setText(self._t("opacity"))
        self.lbl_unit.setText(self._t("unit_hint"))
        self.grp_ops.setTitle(self._t("ops_grp"))
        self.grp_disp.setTitle(self._t("display"))
        self.grp_canvas.setTitle(self._t("canvas_ctl"))
        self.btn_rerender.setText(self._t("render_surface"))
        self.btn_detect.setText(self._t("detect_range"))
        self.chk_transparent.setText(self._t("transparent_bg"))
        self.lbl_dpi.setText(self._t("dpi_label"))
        self.btn_export.setText(self._t("export_image"))
        # 导出格式菜单项也要跟着切语言
        if getattr(self, "_export_menu", None) is not None:
            for act, key in zip(self._export_menu.actions(),
                                ("fmt_png", "fmt_jpg", "fmt_tif", "fmt_svg")):
                act.setText(self._t(key))
        self.lbl_ticks.setText(self._t("ticks_label"))
        self.lbl_orient.setText(self._t("orient_label"))
        self.lbl_cs_len.setText(self._t("cs_len"))
        self.lbl_unitc.setText(self._t("unit_label"))
        self.combo_orient.setItemText(0, self._t("orient_v"))
        self.combo_orient.setItemText(1, self._t("orient_h"))
        self.grp_param.setTitle(self._t("param_grp"))
        self.lbl_iso_mat.setText(self._t("iso_mat"))
        self.chk_peel.setText(self._t("iso_peel"))
        self.lbl_atom_style.setText(self._t("atom_style"))
        self.lbl_atom_r.setText(self._t("atom_r"))
        self.lbl_bond_r.setText(self._t("bond_r"))
        self.lbl_thinning_l.setText(self._t("thinning"))
        self.chk_ext_spheres.setText(self._t("ext_spheres"))
        self.chk_ext_labels.setText(self._t("ext_labels"))
        self.chk_ext_border.setText(self._t("ext_border"))
        self.lbl_ext_font_l.setText(self._t("ext_font"))
        self.lbl_ext_radius_l.setText(self._t("ext_radius"))
        self.lbl_ext_dist_l.setText(self._t("ext_dist"))
        self._set_status(self._t("status_ready"))
        # 文案变了 → 重算行首标签的统一宽度（切中英文时标签长短不一）
        self._align_lead_labels()

    def _align_lead_labels(self):
        """把各行的行首标签拉到同一宽度（取实测最长值），行首才不会参差不齐。

        宽度不能用固定值：同一行标签在中文/英文下长度差别很大（如「配色方案:」
        与「Atom style:」），写死会在另一种语言下留一截空白或挤到控件。
        """
        labels = getattr(self, "_lead_labels", None) or []
        if not labels:
            return
        w = 0
        for lbl in labels:
            try:
                w = max(w, lbl.sizeHint().width())
            except Exception:
                pass
        if w <= 0:
            return
        for lbl in labels:
            lbl.setMinimumWidth(w)

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()
        from molstudio.ui.i18n_utils import apply_text_map
        apply_text_map(self, _LANG_EXTRA, self.lang)

    # ── UI ──
    # ════════════════════════════════════════════════════════════════════
    #  版面（2026-09-18 重写）
    # ════════════════════════════════════════════════════════════════════
    # 整页一条竖向布局，四块自上而下：操作 / 显示设置 / 画布控制 / 显示参数。
    # 节奏：页面外边距 8px + 一级块间距 8px（全站统一，基准 = AIM 面板，见
    # aim_panel._build_ui）；块内行距 11px、行内控件间距 8px，行首标签按实测
    # 最长值对齐。（原来这里是 10px / 14px，2026-09-29 统一到 8px 基准。）
    #
    # 与旧版最大的差别：不再为了「一屏塞得下」压行距。旧版把三组参数硬压进
    # 678px 视口（行距 7~10px、分组标题留白砍到 4px、一行塞 5 个控件），
    # 结果就是挤成一团；右栏 PagedScrollArea 已按「当前页固有高度」滚动
    # （见 main_window.PagedScrollArea），内容超出视口滚动即可，不必牺牲行距。
    #
    # 各块竖向策略仍取 Maximum：页面栈高度取的是所有页 sizeHint 的最大值
    # （可视化页近 1900px），若放任 QVBoxLayout 分摊富余高度，行距会被撑肥；
    # 锁成 Maximum 后富余高度由末尾 stretch 沉到底部，块内行距始终稳定。
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # hrow() 里的「末端弹性空白」哨兵：把行内容顶到左侧，不被拉散
        STRETCH = "stretch"
        # 行首标签登记表（_align_lead_labels 按实测最长值统一宽度）
        self._lead_labels = []

        def hrow(*items, spacing=8):
            """一行控件容器。

            items 支持四种写法：控件 / (控件, 拉伸系数) / 整数=固定空白 /
            STRETCH=末端弹性空白。
            """
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(spacing)
            for it in items:
                if isinstance(it, int):
                    h.addSpacing(it)
                elif isinstance(it, tuple):
                    h.addWidget(it[0], it[1])
                elif it == STRETCH:
                    h.addStretch(1)
                else:
                    h.addWidget(it)
            return w

        def vgroup():
            """分组框：直接用主题里的 QGroupBox（蓝色标题条 + 圆角白底），
            与其余 tab 保持一致；内部一条竖向布局。"""
            g = QGroupBox()
            gl = QVBoxLayout(g)
            gl.setContentsMargins(12, 8, 12, 10)
            gl.setSpacing(11)
            return g, gl

        def sld_field(sld, val, min_width=110):
            """滑块 + 右侧数值标签（不含行首标签）。

            滑块最小宽度取 110px：一行放两组「标签+滑块+数值」时，英文文案下
            也能塞进 620px 的右栏（再宽就会把右侧数值挤出可视区）。
            """
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            sld.setMinimumWidth(min_width)
            h.addWidget(sld, 1)
            val.setMinimumWidth(34)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(val)
            return w

        # ── 操作区：生成 / 合并 / 面积图 / 视图 / 载入归档 cube ──
        # 原来是块裸控件（没有边框、没有标题），夹在页面顶部与「显示设置」之间
        # 看不出属于哪一区。改用与其它分节同款的圆角分组框（vgroup()），标题走
        # _apply_lang 的 ops_grp，观感与本页其余分节一致。
        self.grp_ops, ops_l = vgroup()

        self.btn_merge = QPushButton()
        self.btn_merge.clicked.connect(self._merge_preview)
        self.btn_generate = QPushButton()
        self.btn_generate.setStyleSheet("font-weight:bold;")
        self.btn_generate.clicked.connect(self._generate)
        self.btn_area = QPushButton()
        self.btn_area.clicked.connect(self._run_area_chart)
        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self._reset_view)
        self.btn_clear = QPushButton()
        self.btn_clear.clicked.connect(self._clear_canvas)
        ops_l.addWidget(hrow(self.btn_merge, self.btn_generate, self.btn_area,
                             self.btn_reset, self.btn_clear, STRETCH))

        # 计算进度条 + 计算信息（移植自 ESPViewer2/esp_surface_gui.py）
        self._progress_row = prog_row = QWidget()
        ph = QHBoxLayout(prog_row)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: none; border-radius: 6px;"
            " background: #E2E8F0; height: 14px;"
            " color: #1E293B; font-size: 9pt; text-align: center; }"
            "QProgressBar::chunk { border-radius: 6px;"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #3E8E7E, stop:1 #1565C0); }")
        self.progress_bar.hide()
        ph.addWidget(self.progress_bar, 1)
        self.lbl_esp_info = QLabel()
        self.lbl_esp_info.setStyleSheet("color: #64748B; font-size: 9pt;")
        self.lbl_esp_info.hide()
        ph.addWidget(self.lbl_esp_info)
        ops_l.addWidget(prog_row)

        # 载入 cub 文件夹（直接可视化已归档 cube，无需重跑 Multiwfn）
        self.lbl_cubdir = QLabel()
        self.edit_cubdir = QLineEdit()
        self.edit_cubdir.setPlaceholderText("")
        self.edit_cubdir.returnPressed.connect(self._load_cubdir_from_edit)
        self.btn_browse_cubdir = QPushButton()
        self.btn_browse_cubdir.clicked.connect(self._browse_cubdir)
        ops_l.addWidget(hrow(self.lbl_cubdir, (self.edit_cubdir, 1),
                             self.btn_browse_cubdir))
        v.addWidget(self.grp_ops)

        # ── 显示设置（模式 / 色标 / 范围 / 配色不透明度）──
        self.grp_disp, disp_l = vgroup()

        # 行 1：显示模式（四个单选独占一行：中文/英文文案下都接近栏宽上限，
        # 再往里塞「点大小」会把右侧控件挤出可视区）
        self.lbl_mode = QLabel()
        self.rb_iso = QRadioButton()
        self.rb_iso.setChecked(True)
        self.rb_iso.toggled.connect(lambda on: on and self._set_mode("iso"))
        self.rb_pt = QRadioButton()
        self.rb_pt.toggled.connect(lambda on: on and self._set_mode("pt"))
        self.rb_ext = QRadioButton()
        self.rb_ext.toggled.connect(lambda on: on and self._set_mode("ext"))
        self.rb_all = QRadioButton()
        self.rb_all.toggled.connect(lambda on: on and self._set_mode("all"))
        disp_l.addWidget(hrow(self.lbl_mode, self.rb_iso, self.rb_pt,
                              self.rb_ext, self.rb_all, STRETCH))
        self._lead_labels.append(self.lbl_mode)

        # 行 2：点云大小（仅 PT 模式）+ 密度等值面
        self.lbl_ptsize = QLabel()
        self.spin_ptsize = QDoubleSpinBox()
        self.spin_ptsize.setRange(0.5, 12.0)
        self.spin_ptsize.setValue(3.0)
        self.spin_ptsize.setDecimals(1)
        self.spin_ptsize.setMaximumWidth(70)
        self.spin_ptsize.valueChanged.connect(self._on_ptsize)
        self.lbl_iso = QLabel()
        self.edit_iso = QLineEdit(str(DEFAULT_ISOLEVEL))
        self.edit_iso.setMaximumWidth(90)
        disp_l.addWidget(hrow(self.lbl_ptsize, self.spin_ptsize, 18,
                              self.lbl_iso, self.edit_iso, STRETCH))
        self._lead_labels.extend((self.lbl_ptsize, self.lbl_iso))

        # 行 3：色标条开关 + 刻度段数 + 方位 + 长度
        self.chk_cs = QCheckBox()
        self.chk_cs.setChecked(True)
        self.chk_cs.toggled.connect(self._on_cs_toggle)
        self.lbl_ticks = QLabel()
        self.spin_ticks = QSpinBox()
        self.spin_ticks.setRange(2, 20)
        self.spin_ticks.setValue(10)
        self.spin_ticks.setMaximumWidth(64)
        self.spin_ticks.valueChanged.connect(self._on_ticks)
        self.lbl_orient = QLabel()
        self.combo_orient = QComboBox()
        self.combo_orient.addItems([self._t("orient_v"), self._t("orient_h")])
        self.combo_orient.setMinimumWidth(80)
        self.combo_orient.setMaximumWidth(90)
        self.combo_orient.currentIndexChanged.connect(self._on_orient)
        self.lbl_cs_len = QLabel()
        self.spin_cs_len = QSpinBox()
        self.spin_cs_len.setRange(15, 95)
        self.spin_cs_len.setValue(55)
        self.spin_cs_len.setSuffix("%")
        self.spin_cs_len.setMaximumWidth(64)
        self.spin_cs_len.valueChanged.connect(self._on_cs_len)
        # 「色标轴设置…」：刻度字体等（原先只能右键点画布上的色标条才能改）
        self.btn_cs_settings = QPushButton()
        self.btn_cs_settings.setToolTip(
            "色彩刻度轴的字体设置（字体族 / 字号，带实时预览）。\n"
            "原来只能右键点画布上的色标条，这里给出入口。")
        self.btn_cs_settings.clicked.connect(self._open_cs_settings)
        disp_l.addWidget(hrow(self.chk_cs, 10, self.lbl_ticks, self.spin_ticks,
                              10, self.lbl_orient, self.combo_orient,
                              10, self.lbl_cs_len, self.spin_cs_len,
                              10, self.btn_cs_settings, STRETCH))

        # 行 4：色标上下限 + 单位 + 自动范围
        # 注：原先这里还挂着一枚写死的「(a.u.)」提示（lbl_unit），单位切成
        # kcal/mol 时它就是错的，而且挤占近 100px。控件仍建着（_apply_lang
        # 要给它设文案），但不再入布局。
        self.lbl_vmin = QLabel()
        self.edit_vmin = QLineEdit("-50")
        self.edit_vmin.setMaximumWidth(90)
        self.lbl_vmax = QLabel()
        self.edit_vmax = QLineEdit("50")
        self.edit_vmax.setMaximumWidth(90)
        self.lbl_unitc = QLabel()
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["kcal/mol", "a.u."])
        self.combo_unit.setMaximumWidth(92)
        # 组合框的 minimumSizeHint 按最长条目算（151px），显式压到 92 才好和
        # 上下限编辑框同处一行
        self.combo_unit.setMinimumWidth(92)
        self.combo_unit.setCurrentText(self._unit)
        # 连接须放在 setCurrentText 之后，避免初始化期间触发一次换算
        self.combo_unit.currentTextChanged.connect(self._on_unit_changed)
        self.lbl_unit = QLabel()   # 见上：保留属性，不入布局
        self.chk_auto = QCheckBox()
        disp_l.addWidget(hrow(self.lbl_vmin, self.edit_vmin, 14,
                              self.lbl_vmax, self.edit_vmax, 14,
                              self.lbl_unitc, self.combo_unit, 14,
                              self.chk_auto, STRETCH))
        self._lead_labels.append(self.lbl_vmin)

        # 行 5：配色 + 翻转 + 不透明度
        self.lbl_cmap = QLabel()
        self.combo_cmap = QComboBox()
        self.combo_cmap.addItems(list(ESP_CMAPS.keys()))
        self.combo_cmap.setCurrentText("RWB (红-白-蓝)")
        # 同上：最长条目「彩虹 NipySpectral」会把 minimumSizeHint 顶到 242px，
        # 显式压到 150，横向才放得下「配色 + 翻转 + 不透明度」这一行
        self.combo_cmap.setMinimumWidth(150)
        self.combo_cmap.setMaximumWidth(220)
        # 切换配色：色标条立即换色；已生成过表面则防抖后自动重提取着色
        #（免手点「渲染 ESP 表面」）。连接须放在 setCurrentText 之后，
        # 避免初始化期间 addItems/setCurrentText 触发一次。
        self._cmap_debounce = QTimer(self)
        self._cmap_debounce.setSingleShot(True)
        self._cmap_debounce.setInterval(250)
        self._cmap_debounce.timeout.connect(self._rerender_surface)
        self.combo_cmap.currentTextChanged.connect(self._on_cmap_changed)
        self.lbl_invert = QLabel()
        self.chk_invert = QCheckBox()
        self.chk_invert.setChecked(False)
        self.chk_invert.toggled.connect(self._on_cmap_changed)
        self.lbl_op = QLabel()
        self.sld_op = QSlider(Qt.Horizontal)
        self.sld_op.setRange(5, 100)
        self.sld_op.setValue(100)
        self.sld_op.setMinimumWidth(130)
        self.sld_op.setMaximumWidth(220)
        self.sld_op.valueChanged.connect(self._on_opacity)
        disp_l.addWidget(hrow(self.lbl_cmap, (self.combo_cmap, 1), 14,
                              self.lbl_invert, self.chk_invert, 16,
                              self.lbl_op, (self.sld_op, 1), STRETCH))
        self._lead_labels.append(self.lbl_cmap)

        v.addWidget(self.grp_disp)

        # ── 画布控制（渲染 / 检测范围 / 导出）──
        self.grp_canvas, cv_l = vgroup()
        self.btn_rerender = QPushButton()
        self.btn_rerender.setToolTip("从已生成的 density/ESP cube 重新提取表面（不重跑 Multiwfn）")
        self.btn_rerender.clicked.connect(self._rerender_surface)
        self.btn_detect = QPushButton()
        self.btn_detect.setToolTip("统计分子等值面上的 ESP 极值并填入色标上下限")
        self.btn_detect.clicked.connect(self._detect_esp_range)
        self.btn_export = QPushButton()
        # 格式（PNG / JPG / TIFF / SVG）收在下拉菜单里，按钮本身不再只出 PNG
        self._export_fmt = "png"
        self._export_menu = QMenu(self.btn_export)
        for ext, key in (("png", "fmt_png"), ("jpg", "fmt_jpg"),
                         ("tif", "fmt_tif"), ("svg", "fmt_svg")):
            act = self._export_menu.addAction(self._t(key))
            act.setData(ext)
            act.triggered.connect(
                lambda _checked=False, e=ext: self._export_image(e))
        self.btn_export.setMenu(self._export_menu)
        self.btn_export.setToolTip(
            "导出 ESP 表面图片 —— 点开选择格式：\n"
            "  PNG  无损，支持透明背景\n"
            "  JPG  有损压缩，体积小（不支持透明）\n"
            "  TIFF 无损，支持透明背景\n"
            "  SVG  矢量容器（内嵌满分辨率位图）")
        cv_l.addWidget(hrow(self.btn_rerender, self.btn_detect,
                            self.btn_export, STRETCH))

        self.chk_transparent = QCheckBox()
        self.chk_transparent.setToolTip(
            "导出时背景设为透明（alpha=0）。对 PNG / TIFF / SVG 有效；"
            "JPG 无 alpha 通道，会合成到画布底色。")
        self.lbl_dpi = QLabel()
        self.edit_dpi = QLineEdit("600")
        self.edit_dpi.setMaximumWidth(64)
        cv_l.addWidget(hrow(self.chk_transparent, 16,
                            self.lbl_dpi, self.edit_dpi, STRETCH))
        v.addWidget(self.grp_canvas)

        # ── 显示参数（等值面材质 / 原子键 / 极值点标注）──
        self.grp_param, pm_l = vgroup()

        # 等值面：材质光泽 + 深度剥离
        self.lbl_iso_mat = QLabel()
        self.combo_shiny = QSlider(Qt.Horizontal)
        self.combo_shiny.setRange(0, 100)
        self.combo_shiny.setValue(int(_GLOSS_DEFAULT * 100))
        self.combo_shiny.setMinimumWidth(130)
        self.combo_shiny.setMaximumWidth(260)
        self.combo_shiny.valueChanged.connect(self._on_iso_mat)
        self.chk_peel = QCheckBox()
        self.chk_peel.setChecked(True)
        self.chk_peel.toggled.connect(self._on_peel)
        pm_l.addWidget(hrow(self.lbl_iso_mat, (self.combo_shiny, 1), 16,
                            self.chk_peel, STRETCH))
        self._lead_labels.append(self.lbl_iso_mat)

        # 原子与化学键：配色方案
        self.lbl_atom_style = QLabel()
        self.combo_atom_style = QComboBox()
        self.combo_atom_style.addItems(MOL_STYLE_DISPLAY)
        # 同上：MOL_STYLE_DISPLAY 里最长条目会把 minimumSizeHint 顶到 255px
        self.combo_atom_style.setMinimumWidth(170)
        self.combo_atom_style.setMaximumWidth(200)
        self.combo_atom_style.currentIndexChanged.connect(self._on_atom_style)
        pm_l.addWidget(hrow(self.lbl_atom_style, self.combo_atom_style, STRETCH))
        self._lead_labels.append(self.lbl_atom_style)

        # 原子半径 / 键半径（同一行，各占一半）
        self.lbl_atom_r = QLabel()
        self.sld_atom_scale = QSlider(Qt.Horizontal)
        self.sld_atom_scale.setRange(5, 400)
        self.sld_atom_scale.setValue(168)
        self.sld_atom_scale.valueChanged.connect(self._on_atom_scale)
        self.lbl_atom_scale = QLabel("")
        self.lbl_bond_r = QLabel()
        self.sld_bond_scale = QSlider(Qt.Horizontal)
        self.sld_bond_scale.setRange(2, 500)
        self.sld_bond_scale.setValue(200)
        self.sld_bond_scale.valueChanged.connect(self._on_bond_scale)
        self.lbl_bond_scale = QLabel("")
        pm_l.addWidget(hrow(self.lbl_atom_r,
                            (sld_field(self.sld_atom_scale, self.lbl_atom_scale), 1),
                            16, self.lbl_bond_r,
                            (sld_field(self.sld_bond_scale, self.lbl_bond_scale), 1)))
        self._lead_labels.extend((self.lbl_atom_r, self.lbl_bond_r))

        # 收腰效果
        self.lbl_thinning_l = QLabel()
        self.sld_thinning = QSlider(Qt.Horizontal)
        self.sld_thinning.setRange(20, 100)
        self.sld_thinning.setValue(100)
        self.sld_thinning.valueChanged.connect(self._on_thinning)
        self.lbl_thinning = QLabel("")
        pm_l.addWidget(hrow(self.lbl_thinning_l,
                            (sld_field(self.sld_thinning, self.lbl_thinning), 1),
                            STRETCH))
        self._lead_labels.append(self.lbl_thinning_l)

        # 极值点标注：三个开关
        self.chk_ext_spheres = QCheckBox()
        self.chk_ext_spheres.setChecked(True)
        self.chk_ext_spheres.toggled.connect(self._on_ext_spheres)
        self.chk_ext_labels = QCheckBox()
        self.chk_ext_labels.setChecked(False)
        self.chk_ext_labels.toggled.connect(self._on_ext_labels)
        self.chk_ext_border = QCheckBox()
        self.chk_ext_border.setChecked(True)
        self.chk_ext_border.toggled.connect(self._on_ext_border)
        pm_l.addWidget(hrow(self.chk_ext_spheres, self.chk_ext_labels,
                            self.chk_ext_border, STRETCH))

        # 标签字号 / 小球半径
        self.lbl_ext_font_l = QLabel()
        self.sld_ext_font = QSlider(Qt.Horizontal)
        self.sld_ext_font.setRange(8, 28)
        self.sld_ext_font.setValue(9)
        self.sld_ext_font.valueChanged.connect(self._on_ext_font)
        self.lbl_ext_font = QLabel("")
        self.lbl_ext_radius_l = QLabel()
        self.sld_ext_radius = QSlider(Qt.Horizontal)
        self.sld_ext_radius.setRange(5, 100)
        self.sld_ext_radius.setValue(8)
        self.sld_ext_radius.valueChanged.connect(self._on_ext_radius)
        self.lbl_ext_radius = QLabel("")
        pm_l.addWidget(hrow(self.lbl_ext_font_l,
                            (sld_field(self.sld_ext_font, self.lbl_ext_font), 1),
                            16, self.lbl_ext_radius_l,
                            (sld_field(self.sld_ext_radius, self.lbl_ext_radius), 1)))
        self._lead_labels.extend((self.lbl_ext_font_l, self.lbl_ext_radius_l))

        # 标签距离
        self.lbl_ext_dist_l = QLabel()
        self.sld_ext_dist = QSlider(Qt.Horizontal)
        self.sld_ext_dist.setRange(0, 60)
        self.sld_ext_dist.setValue(12)
        self.sld_ext_dist.valueChanged.connect(self._on_ext_dist)
        self.lbl_ext_dist = QLabel("")
        pm_l.addWidget(hrow(self.lbl_ext_dist_l,
                            (sld_field(self.sld_ext_dist, self.lbl_ext_dist), 1),
                            STRETCH))
        self._lead_labels.append(self.lbl_ext_dist_l)

        v.addWidget(self.grp_param)

        # 初始化滑块数值显示并应用一次
        self.lbl_atom_scale.setText("1.68")
        self.lbl_bond_scale.setText("2.00")
        self.lbl_thinning.setText("1.00")
        self.lbl_ext_font.setText("9")
        self.lbl_ext_radius.setText("0.08")
        self.lbl_ext_dist.setText("12")
        self._on_iso_mat(self.combo_shiny.value())
        self._on_peel(True)
        self._on_atom_style(self.combo_atom_style.currentIndex())
        self._on_atom_scale(168)
        self._on_bond_scale(200)
        self._on_thinning(100)
        self._on_ext_font(9)
        self._on_ext_radius(8)
        self._on_ext_dist(12)
        self._on_ext_border(True)

        # 日志（Multiwfn 输出区域，按需要隐藏；后台仍运行，仅不显示）
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setVisible(False)
        v.addWidget(self.log_text, stretch=1)

        # 各块竖向锁 Maximum（理由见本方法开头注释）：高度停在自身 sizeHint，
        # 富余高度不再钻进块里把行距撑肥。横向仍 Expanding，照旧吃满栏宽。
        for _blk in (self.grp_ops, self.grp_disp, self.grp_canvas,
                     self.grp_param):
            _sp = _blk.sizePolicy()
            _sp.setHorizontalPolicy(QSizePolicy.Expanding)
            _sp.setVerticalPolicy(QSizePolicy.Maximum)
            _blk.setSizePolicy(_sp)

        # 进度条行默认整行隐藏（只在计算时才出现），把竖向空间让给参数区
        self._set_progress_row_visible(False)

        # 尾部弹性空白：富余高度全部沉到底部，四块始终顶在上方
        v.addStretch(1)

        self._status = QLabel()
        self._status.setStyleSheet(
            "color:#5C6BC0; font-size:8.5pt; background:#EEF2FF;"
            "border-top:1px solid #C5CAE9; padding:4px 10px;")
        self._status.setVisible(False)   # 底部状态栏已移除（保留属性供 _set_status 调用）

    # ── 状态/日志 ──
    def _set_status(self, msg):
        self._status.setText(str(msg))

    def _set_progress_row_visible(self, visible):
        """整行显示/隐藏「进度条 + 计算信息」行。

        只 hide() 子控件是不够的：容器仍会按子项最小高度占位（约 26px），
        在竖向空间紧张的 ESP 页里就是白白少一行参数。可见时恢复内容的高度，
        隐藏时把最大高度压到 0，让这点高度让给参数区。
        """
        row = getattr(self, "_progress_row", None)
        bar = getattr(self, "progress_bar", None)
        info = getattr(self, "lbl_esp_info", None)
        if row is None or bar is None or info is None:
            return
        if visible:
            for wd in (bar, info):
                wd.setMaximumHeight(16777215)
                wd.show()
            row.setMaximumHeight(16777215)
            row.show()
        else:
            bar.hide()
            info.hide()
            row.setMaximumHeight(0)
            row.hide()

    def _start_progress(self):
        """开始计算：显示进度行并复位。"""
        self._set_progress_row_visible(True)
        self.progress_bar.setValue(0)
        self.lbl_esp_info.setText("准备中 …")

    def _finish_progress(self):
        """计算结束：进度行复位并整行收起。"""
        self.progress_bar.setValue(100)
        self._set_progress_row_visible(False)

    def _log(self, msg):
        self.log_text.append(str(msg))
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── 浏览 ──
    def _browse_fchk(self):
        p, _ = open_file(
            self, "选择 fchk 文件", "",
            "Formatted Checkpoint (*.fchk *.fch);;所有文件 (*)")
        if p:
            self.fchk_file = p
            self._log("fchk: " + os.path.basename(p))

    def _merge_preview(self):
        """多分子合并预览：多选 fchk，同画布叠加 ESP 表面。"""
        paths, _ = open_files(
            self, "选择多个 fchk 文件", "",
            "Formatted Checkpoint (*.fchk *.fch);;所有文件 (*)")
        if len(paths) < 2:
            if paths:
                self.fchk_file = paths[0]
                self._log("fchk: " + os.path.basename(paths[0]))
            QMessageBox.information(self, "提示", "合并预览请选择至少 2 个 fchk 文件")
            return
        self._start_worker(paths, "merge")

    def _resolve_fchk(self):
        f = (self.fchk_file or "").strip()
        if f and os.path.exists(f):
            return f
        f2 = (self._get_fchk() or "").strip()
        return f2 if f2 and os.path.exists(f2) else ""

    def _cube_paths_for(self, fchk):
        """返回某 fchk 的归档 density/ESP cube 路径（可能不存在）。"""
        stem = os.path.splitext(os.path.basename(fchk))[0]
        arch_dir = os.path.join(os.path.dirname(os.path.abspath(fchk)),
                                f"{stem}_ESP")
        return (os.path.join(arch_dir, "density.cub"),
                os.path.join(arch_dir, "ESP.cub"))

    @staticmethod
    def _vmd_cmap_name(cmap_name, invert=False):
        """面板配色名 → VMD color scale method。

        VMD 的色标方法是**固定枚举**，实测 VMD 1.9.3 只认 6 个：
        RGB / BGR / RWB / BWR / RWG / BWG（RG、GB、Gray、jet、viridis 等
        全被拒绝）。所以画布上那十几种配色最终只能落到这 6 个上。

        invert=True 时翻转方向：BWR↔RWB 互换（枚举里只有这一组互为反向）；
        RWG/BWG 在 VMD 里没有反向对应项，故忽略 invert、保持原样。
        """
        n = (cmap_name or "").upper()
        if "BGR" in n:
            return "BGR"
        if "RWG" in n:
            return "RWG"
        if "BWG" in n:
            return "BWG"
        if "RWB" in n:
            return "BWR" if invert else "RWB"
        if "BWR" in n:
            return "RWB" if invert else "BWR"
        if "JET" in n:
            return "RGB"
        if "RDBU" in n or "COOLWARM" in n:
            return "BWR" if invert else "RWB"
        return "BWR"

    def _set_mode(self, mode):
        self._mode = mode

    def _on_ptsize(self, val):
        if self.glw is not None and self._mode == "pt":
            self.glw.set_esp_point_mode(True, float(val))

    def _on_cs_toggle(self, on):
        if self.glw is not None:
            self.glw.set_show_color_scale(bool(on))

    def _on_ticks(self, n):
        if self.glw is not None:
            self.glw.set_color_scale_ticks(int(n))

    def _on_orient(self, idx):
        if self.glw is not None:
            self.glw.set_color_scale_orient("horizontal" if idx == 1 else "vertical")

    def _on_cs_len(self, v):
        if self.glw is not None:
            self.glw.set_color_scale_len(v / 100.0)

    def _open_cs_settings(self):
        """弹出色彩刻度轴设置（字体族 / 字号）。"""
        if self.glw is None:
            QMessageBox.information(self, "提示", "画布尚未就绪。")
            return
        dlg = ColorScaleFontDialog(self.glw, self, lang=self.lang)
        dlg.exec_()

    # ── 显示参数（等值面材质 / 原子键 / 极值点标注） ──
    def _on_iso_mat(self, value):
        if self.glw is not None:
            self.glw.set_gloss(value / 100.0)

    def _on_peel(self, on):
        # 深度剥离透明合成开关（Everitt 2001，本项目独立实现；不可用时自动
        # 回退 WBOIT / 排序混合）。关闭则回退到按深度排序的混合。
        if self.glw is not None:
            self.glw.set_transparency_mode("peel" if on else "sorted")

    def _on_atom_style(self, idx):
        if self.glw is not None and 0 <= idx < len(MOL_STYLE_NAMES):
            self.glw.set_mol_style(MOL_STYLE_NAMES[idx])

    def _on_atom_scale(self, v):
        self.lbl_atom_scale.setText(f"{v / 100:.2f}")
        if self.glw is not None:
            self.glw.set_atom_scale(v / 100.0)

    def _on_bond_scale(self, v):
        self.lbl_bond_scale.setText(f"{v / 100:.2f}")
        if self.glw is not None:
            self.glw.set_bond_scale(v / 100.0)

    def _on_thinning(self, v):
        self.lbl_thinning.setText(f"{v / 100:.2f}")
        if self.glw is not None:
            self.glw.set_bond_thinning(v / 100.0)

    def _apply_extrema_to_canvas(self):
        """把 self._extrema_pts（Å，含数值）推到画布（球 + 标签数值）。"""
        if self.glw is None or not self._extrema_pts:
            return
        pts = self._extrema_pts   # [(kind, x, y, z, value)] Å
        pts_bohr = [(p[1] * ANGSTROM_TO_BOHR, p[2] * ANGSTROM_TO_BOHR,
                     p[3] * ANGSTROM_TO_BOHR, p[0]) for p in pts]
        # Multiwfn 的 surfanalysis.pdb 极值点数值本来就是 kcal/mol（显示单位），
        # 不能再乘 627.509；只有切到 a.u. 显示时才需要除以 627.509。
        vals = [p[4] if self._unit == "kcal/mol" else p[4] / self.AU_TO_KCAL
                for p in pts]
        radius = self.sld_ext_radius.value() / 100.0
        self.glw.set_extrema(pts_bohr, radius=radius, values=vals)

    def _on_ext_spheres(self, on):
        if self.glw is None:
            return
        if bool(on) and self._extrema_pts:
            self._apply_extrema_to_canvas()
        else:
            self.glw.clear_extrema()

    def _on_ext_labels(self, on):
        if self.glw is not None:
            self.glw.set_extrema_labels(show=bool(on))

    def _on_ext_border(self, on):
        if self.glw is not None:
            self.glw.set_extrema_labels(border=bool(on))

    def _on_ext_font(self, v):
        self.lbl_ext_font.setText(str(v))
        if self.glw is not None:
            self.glw.set_extrema_labels(font_size=int(v))

    def _on_ext_radius(self, v):
        self.lbl_ext_radius.setText(f"{v / 100:.2f}")
        if self.glw is not None:
            self.glw.set_extrema_radius(v / 100.0)

    def _on_ext_dist(self, v):
        self.lbl_ext_dist.setText(str(v))
        if self.glw is not None:
            self.glw.set_extrema_labels(dist=int(v))

    def _on_opacity(self, v):
        if self.glw is not None:
            self.glw.set_opacity(max(0.05, v / 100.0))

    # ── 画布控制：重渲 / 检测范围 / 导出 ──
    # ── 载入 cub 文件夹（复用已归档 cube，不重跑 Multiwfn） ──
    def _browse_cubdir(self):
        folder = existing_directory(
            self, self._t("load_cubdir").rstrip(":"),
            self.edit_cubdir.text().strip() or "")
        if folder:
            self._load_cubdir(folder)

    def _load_cubdir_from_edit(self):
        folder = self.edit_cubdir.text().strip()
        if folder:
            self._load_cubdir(folder)

    def _load_cubdir(self, folder, rerender=True):
        """在 folder 里配对 density*.cub / ESP*.cub，直接渲染等值面（不跑 Multiwfn）。
        rerender=False 时仅登记 cub 配对（不立即重渲染），供生成完成后自动载入用。"""
        import glob as _glob
        dens = sorted(_glob.glob(os.path.join(folder, "density*.cub")))
        esps = sorted(_glob.glob(os.path.join(folder, "ESP*.cub")))
        if not dens or not esps:
            QMessageBox.warning(self, self._t("load_cubdir"), self._t("load_cub_none"))
            return

        def _num(p):
            m = re.search(r"(\d+)(?=\.cub$)", os.path.basename(p))
            return int(m.group(1)) if m else None

        # 按文件名序号配对（density1.cub ↔ ESP1.cub），无序号/剩余项按排序顺序补齐
        dmap, emap = {}, {}
        for p in dens:
            n = _num(p)
            if n is not None and n not in dmap:
                dmap[n] = p
        for p in esps:
            n = _num(p)
            if n is not None and n not in emap:
                emap[n] = p
        nums = sorted(set(dmap) & set(emap))
        pairs = [(dmap[n], emap[n]) for n in nums]
        matched = set()
        for n in nums:
            matched.add(dmap[n])
            matched.add(emap[n])
        rd = [p for p in dens if p not in matched]
        re_ = [p for p in esps if p not in matched]
        for d, e in zip(rd, re_):
            pairs.append((d, e))
        if not pairs:
            pairs = [(dens[0], esps[0])]

        self._loaded_cub_pairs = pairs
        self.edit_cubdir.setText(folder)
        self._log(self._t("load_cub_ok", n=len(pairs)))
        if not rerender:
            return
        try:
            self._rerender_surface()
        except Exception as e:  # noqa
            QMessageBox.warning(self, self._t("load_cubdir"),
                                self._t("load_cub_fail", err=str(e)))

    def _auto_fill_cubdir(self):
        """生成 ESP 完成后：把归档 cub 目录自动填入「载入 cub 文件夹」并自动载入，
        后续调样式/配色直接复用归档 cube，无需重跑 Multiwfn。
        仅单个分子时自动载入（多分子 merge 的 cub 分散在多个目录，不自动载入）。"""
        lst = getattr(self, "_last_fchk_list", None) or []
        if len(lst) != 1:
            return
        fchk = lst[0]
        if not os.path.exists(fchk):
            return
        d, e = self._cube_paths_for(fchk)
        if not (os.path.exists(d) and os.path.exists(e)):
            return
        try:
            self._load_cubdir(os.path.dirname(d), rerender=False)
        except Exception:  # noqa: BLE001
            pass

    def _current_cube_paths(self):
        """返回当前 cube 源 (fchk_or_None, density, esp) 路径对列表。
        优先用「载入 cub 文件夹」覆盖的配对；否则用当前 fchk 列表的归档。"""
        loaded = getattr(self, "_loaded_cub_pairs", None)
        if loaded:
            return [(None, d, e) for d, e in loaded]
        fchk_list = getattr(self, "_last_fchk_list", None) or []
        if not fchk_list:
            f = self._resolve_fchk()
            fchk_list = [f] if f else []
        pairs = []
        for f in fchk_list:
            d, e = self._cube_paths_for(f)
            if os.path.exists(d) and os.path.exists(e):
                pairs.append((f, d, e))
        return pairs

    def _apply_surface(self, surfs, first_density, n_files):
        """把提取出的表面推到左侧画布（无 Multiwfn 的快速重渲路径）。"""
        glw = self.glw
        if not surfs:
            self._set_status(self._t("empty"))
            return
        if len(surfs) == 1:
            surf = surfs[0]
        else:
            surf = merge_iso_surfaces(surfs)
        glw._esp_point_mode = False
        glw._cube = first_density
        glw._pos_surf = surf
        glw._neg_surf = None
        # 通知画布：表面带 ESP 顶点连续着色（一键样式/相位色操作不得平铺覆盖）
        glw._surf_vcolor = True
        if first_density is not None:
            ctr, r = compute_bounding_sphere(first_density)
            glw.cam.set_center_zoom(ctr, r)
        glw._gen_atoms()
        glw._needs_upload = True
        glw.update()
        self._sync_color_scale()
        self._set_status(self._t("done", n=surf.vertex_count, m=n_files))

    def _rerender_surface(self):
        """「渲染 ESP 表面」：从已归档 cube 重新提取表面（不重跑 Multiwfn）。"""
        if self.glw is None:
            return
        pairs = self._current_cube_paths()
        if not pairs:
            QMessageBox.information(self, "渲染 ESP 表面", self._t("detect_no_cube"))
            return
        iso, vmin, vmax, cmap, auto, invert = self._params()
        surfs = []
        first_density = None
        for _f, d, e in pairs:
            density = read_cube(d)
            esp = read_cube(e)
            surf, _ = extract_esp_surface(density, esp, isolevel=iso,
                                          vmin=vmin, vmax=vmax, cmap=cmap,
                                          auto_range=auto, invert=invert)
            if surf.vertex_count == 0:
                continue
            surfs.append(surf)
            if first_density is None:
                first_density = density
        self._apply_surface(surfs, first_density, len(pairs))
        # VMD 同步场景登记（density 定几何、ESP 定色，a.u. 范围）
        self._register_vmd_scene(iso, vmin, vmax, cmap, invert)

    def _detect_esp_range(self):
        """「检测 ESP 范围」：统计等值面上 ESP 极值 → 回填上下限（当前单位）。"""
        pairs = self._current_cube_paths()
        if not pairs:
            QMessageBox.information(self, self._t("detect_range"), self._t("detect_no_cube"))
            return
        iso, _, _, _, _, _ = self._params()
        try:
            lo_au, hi_au = None, None
            for _f, d, e in pairs:
                density = read_cube(d)
                esp = read_cube(e)
                surf = marching_cubes(density, float(iso), flip_normal=False)
                if surf.vertex_count == 0:
                    continue
                world = surf.vertices.astype(np.float64)
                ebasis = np.array([esp.dx, esp.dy, esp.dz], dtype=np.float64)
                try:
                    inv_eb = np.linalg.inv(ebasis)
                except np.linalg.LinAlgError:
                    inv_eb = np.eye(3)
                eidx = (world - esp.origin.astype(np.float64)) @ inv_eb
                edims = np.array([esp.nx, esp.ny, esp.nz], dtype=np.int64)
                e0 = np.floor(eidx).astype(np.int64)
                np.clip(e0, 0, edims - 1, out=e0)
                e1 = np.minimum(e0 + 1, edims - 1)
                vals = _trilinear(esp.data.astype(np.float64), e0, e1, eidx - e0)
                vals = vals[np.isfinite(vals)]
                if vals.size:
                    lo = float(vals.min())
                    hi = float(vals.max())
                    lo_au = lo if lo_au is None else min(lo_au, lo)
                    hi_au = hi if hi_au is None else max(hi_au, hi)
            if lo_au is None or hi_au is None or hi_au - lo_au < 1e-12:
                raise RuntimeError("等值面上未取到有效 ESP 值")
        except Exception as e:
            self._set_status(self._t("detect_fail", err=e))
            return
        self.edit_vmin.setText(f"{self._au_to_display(lo_au):g}")
        self.edit_vmax.setText(f"{self._au_to_display(hi_au):g}")
        if self.chk_auto.isChecked():
            self.chk_auto.setChecked(False)
        self._rerender_surface()
        self._set_status(self._t("detect_done",
                                 lo=self._au_to_display(lo_au),
                                 hi=self._au_to_display(hi_au),
                                 unit=self._unit))
        # 通知主窗口：范围已更新 → 若 VMD 已连接则刷新 VMD 显示
        if callable(self._on_vmd_refresh):
            try:
                self._on_vmd_refresh()
            except Exception:
                pass

    def _export_image(self, fmt=None):
        """按当前 DPI（可透明背景）导出画布，格式由 fmt / 对话框决定。

        支持 PNG / JPG / TIFF / SVG，判定优先级与画布面板一致：
        路径里明确的扩展名 > 对话框选中的过滤器 > 菜单里点的格式。
        """
        if self.glw is None:
            return
        want = export_ext_for(fmt, getattr(self, "_export_fmt", "png"))
        path, sel = save_file(
            self, self._t("export_image"), f"esp_surface.{want}",
            export_dialog_filter(preferred=want))
        if not path:
            return
        ext = export_ext_from_path(path, default="")
        if ext not in ("png", "jpg", "tif", "svg"):
            ext = export_ext_from_filter(sel, default=want)
        path = export_ensure_suffix(path, ext)
        self._export_fmt = ext
        try:
            dpi = int(self.edit_dpi.text().strip())
        except (ValueError, AttributeError):
            dpi = 600
        if dpi <= 0:
            dpi = 600
        transparent = self.chk_transparent.isChecked()
        alpha_ok = export_format_supports_alpha(ext)
        note = ""
        if transparent and not alpha_ok:
            note = " " + self._t("export_jpg_note")
        try:
            ok = self.glw.export_image(path, dpi=dpi,
                                       transparent=transparent and alpha_ok)
            if ok:
                self._set_status(self._t(
                    "export_done", path=os.path.basename(path), dpi=dpi,
                    trans=", " + self._t("transparent_bg")
                    if (transparent and alpha_ok) else "")
                    + note)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_png(self):
        """兼容旧调用：等价于导出 PNG。"""
        self._export_image("png")

    # ── 生成 ──
    def _params(self):
        """返回 (iso, vmin_au, vmax_au, cmap, auto)——色标范围已换算成 a.u.。"""
        try:
            iso = float(self.edit_iso.text().strip())
            vmin = float(self.edit_vmin.text().strip())
            vmax = float(self.edit_vmax.text().strip())
        except ValueError:
            iso = DEFAULT_ISOLEVEL
            vmin, vmax = -50.0, 50.0
        vmin = self._display_to_au(vmin)
        vmax = self._display_to_au(vmax)
        cmap = self.combo_cmap.currentText()
        auto = self.chk_auto.isChecked()
        invert = self.chk_invert.isChecked()
        return iso, vmin, vmax, cmap, auto, invert

    AU_TO_KCAL = 627.509

    def _display_to_au(self, v):
        """显示单位数值 → a.u.（渲染/着色统一用 a.u.）。"""
        if self._unit == "kcal/mol":
            return v / self.AU_TO_KCAL
        return v

    def _au_to_display(self, v):
        """a.u. 数值 → 当前显示单位。"""
        if self._unit == "kcal/mol":
            return v * self.AU_TO_KCAL
        return v

    def _display_range(self):
        """返回显示单位下的色标范围 (lo, hi)（用于画布色标轴显示）。"""
        try:
            lo = float(self.edit_vmin.text().strip())
            hi = float(self.edit_vmax.text().strip())
        except ValueError:
            lo, hi = -50.0, 50.0
        return lo, hi

    def _sync_color_scale(self):
        """把色标范围/配色/单位同步到画布内色彩刻度轴。"""
        if self.glw is None:
            return
        lo, hi = self._display_range()
        unit = f"ESP ({self._unit})"
        self.glw.set_color_scale_cmap(self.combo_cmap.currentText(),
                                      invert=self.chk_invert.isChecked())
        self.glw.set_color_scale(lo, hi, unit=unit,
                                 show=self.chk_cs.isChecked())

    def _on_cmap_changed(self, _cmap=None):
        """切换配色：色标条立即换色；已生成 cube 则防抖后自动重提取表面
        （表面颜色与色标条一起变，无需再点「生成 ESP 表面」）。
        还没生成过 → 静默跳过，生成时自然带上新配色。"""
        self._sync_color_scale()
        if self._current_cube_paths():
            self._cmap_debounce.start()

    def _on_unit_changed(self, unit_text):
        """切换能量单位（kcal/mol ↔ a.u.），编辑框数值同步换算。"""
        if unit_text == self._unit:
            return
        old = self._unit
        try:
            vmin = float(self.edit_vmin.text().strip())
            vmax = float(self.edit_vmax.text().strip())
            self._unit = old
            vmin_au = self._display_to_au(vmin)
            vmax_au = self._display_to_au(vmax)
            self._unit = unit_text
            self.edit_vmin.setText(f"{self._au_to_display(vmin_au):g}")
            self.edit_vmax.setText(f"{self._au_to_display(vmax_au):g}")
        except ValueError:
            self._unit = unit_text
        self._sync_color_scale()
        self._set_status(self._t("unit_changed", unit=unit_text))

    def _generate(self):
        if self._worker is not None and self._worker.isRunning():
            return
        fchk = self._resolve_fchk()
        mw = (self._get_mw() or "").strip()
        if not fchk or not os.path.exists(fchk):
            QMessageBox.critical(self, "错误", self._t("no_fchk"))
            return
        if not mw or not os.path.exists(mw):
            QMessageBox.critical(self, "错误", self._t("no_exe"))
            return
        self._start_worker([fchk], self._mode)

    def _start_worker(self, fchk_list, mode):
        iso, vmin, vmax, cmap, auto, invert = self._params()
        self._last_fchk_list = list(fchk_list)
        self._loaded_cub_pairs = None   # 重新生成时取消「载入 cub 文件夹」覆盖
        self.btn_generate.setEnabled(False)
        self._set_status(self._t("generating"))
        self._log(f"生成 ESP（模式 {mode}）：" + ", ".join(
            os.path.basename(f) for f in fchk_list))
        self._worker = EspWorker(fchk_list, (self._get_mw() or "").strip(),
                                 mode, iso, vmin, vmax, cmap, auto, invert)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self._log)
        self._worker.progress_val.connect(self.progress_bar.setValue)
        self._worker.stage_msg.connect(self.lbl_esp_info.setText)
        self._start_progress()
        self._worker.start()

    def _on_done(self, result):
        self.btn_generate.setEnabled(True)
        mode = result.get("mode", self._mode)
        glw = self.glw
        surf = result.get("surf")
        density = result.get("density")
        n_merged = result.get("n_merged", 1)

        if glw is None:
            self._set_status("画布不可用")
            self._set_progress_row_visible(False)
            return

        # 表面 / 点云
        if surf is not None:
            if mode in ("iso", "all", "merge"):
                glw._esp_point_mode = False
                glw._cube = density
                glw._pos_surf = surf
                glw._neg_surf = None
                if density is not None:
                    ctr, r = compute_bounding_sphere(density)
                    glw.cam.set_center_zoom(ctr, r)
                else:
                    # 合并视图：用各分子整体范围（已并入 surf 顶点）
                    pts = np_bbox(surf)
                    if pts is not None:
                        glw.cam.set_center_zoom(pts[0], max(pts[1], 1.0) * 1.1)
                glw._gen_atoms()
                glw._needs_upload = True
                glw.update()
            elif mode == "pt":
                glw._cube = density
                glw._pos_surf = surf
                glw._neg_surf = None
                if density is not None:
                    ctr, r = compute_bounding_sphere(density)
                    glw.cam.set_center_zoom(ctr, r)
                glw.set_esp_point_mode(True, self.spin_ptsize.value())
                glw._gen_atoms()
                glw._needs_upload = True
                glw.update()
            else:  # ext：仅极值点（无表面）
                glw._pos_surf = None
                glw._neg_surf = None

        # 极值点
        if "extrema" in result:
            pts = result["extrema"]
            self._extrema_pts = pts
            if pts and self.chk_ext_spheres.isChecked():
                self._apply_extrema_to_canvas()
                self._log(self._t("done_ext", n=len(pts)))
            else:
                glw.clear_extrema()
        elif mode in ("iso", "pt", "merge"):
            glw.clear_extrema()

        # 色标条同步（显示单位数值）
        iso, vmin, vmax, cmap, auto, invert = self._params()
        self._sync_color_scale()

        # ── 登记 VMD 同步场景（density 定几何、ESP 定色，a.u. 范围） ──
        self._register_vmd_scene(iso, vmin, vmax, cmap, invert)

        if surf is not None:
            if mode == "pt":
                self._set_status(self._t("done_pt", n=surf.vertex_count))
            else:
                self._set_status(self._t("done", n=surf.vertex_count, m=n_merged))
        elif "extrema" in result:
            self._set_status(self._t("done_ext", n=len(result["extrema"])))
        else:
            self._set_status(self._t("empty"))

        # 生成完成后：把归档 cub 目录自动填入「载入 cub 文件夹」并自动载入，
        # 之后调样式/配色直接复用归档 cube，无需重跑 Multiwfn。
        self._auto_fill_cubdir()

        # 完成后：进度条走满后整行收起
        self._finish_progress()

    def _register_vmd_scene(self, iso, vmin, vmax, cmap, invert=False):
        """登记 VMD 同步场景；失败只影响「同步到 VMD」，不影响 ESP 显示。

        ★ 配色解耦（按用户要求）：本面板的「配色」下拉**只管 OpenGL 画布**，
        不再传给 VMD；VMD 侧的色标改由「VMD 控制台」里的「VMD 色标」独立控制。
        所以这里只登记 `kind="esp"`（主窗口据此注入控制台选的色标），
        不再写 `cmap`。形参 cmap/invert 保留只为兼容既有调用点。

        ★ 球棍模型（VMD 侧）：**不**再登记 `atom_color="Name"`（那是 ESPViewer2
        的 VMD 默认 Name 配色），改由 VMD 控制台选的样式决定 —— 样式的
        `atom_cpk` / `atom_mat` / 元素色表 / 碳色会一起套上去。
        """
        try:
            vmd_surfs = []
            loaded = getattr(self, "_loaded_cub_pairs", None)
            if loaded:
                # 载入 cub 文件夹：直接用这对 cube（density 定几何、ESP 定色）
                for d, e in loaded:
                    if os.path.exists(d) and os.path.exists(e):
                        vmd_surfs.append({"type": "bgr", "vol": d, "color_vol": e,
                                          "iso": iso, "cmin": vmin, "cmax": vmax,
                                          "kind": "esp", "material": "EdgyGlass"})
            else:
                fchk_list = getattr(self, "_last_fchk_list", None) or []
                if not fchk_list:
                    f = self._resolve_fchk()
                    fchk_list = [f] if f else []
                for f in fchk_list:
                    d, e = self._cube_paths_for(f)
                    if d and e and os.path.exists(d) and os.path.exists(e):
                        vmd_surfs.append({"type": "bgr", "vol": d, "color_vol": e,
                                          "iso": iso, "cmin": vmin, "cmax": vmax,
                                          "kind": "esp", "material": "EdgyGlass"})
            if self.glw is not None:
                self.glw.set_vmd_scene(vmd_surfs or None)
        except Exception as e:
            self._log("VMD 场景登记失败: " + str(e))

    def _on_error(self, msg):
        self.btn_generate.setEnabled(True)
        self._set_status("错误: " + str(msg))
        self._log("错误: " + str(msg))
        self._set_progress_row_visible(False)

    # ── 面积分布图 ──
    def _run_area_chart(self):
        if self._area_worker is not None and self._area_worker.isRunning():
            return
        fchk = self._resolve_fchk()
        mw = (self._get_mw() or "").strip()
        if not fchk or not os.path.exists(fchk):
            QMessageBox.critical(self, "错误", self._t("no_fchk"))
            return
        if not mw or not os.path.exists(mw):
            QMessageBox.critical(self, "错误", self._t("no_exe"))
            return
        # 先弹分区设置对话框（范围/分区数），对齐 ESP2 的交互入口
        dlg = BinSettingsDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        lo, hi, n_bins = dlg.get_values()
        if hi <= lo:
            QMessageBox.critical(self, "错误", "最大值必须大于最小值")
            return
        self._area_src_name = os.path.basename(fchk)
        self._set_status("计算 ESP 分区面积分布 …")
        self._area_worker = EspAreaWorker([fchk], mw, lo, hi, n_bins)
        self._area_worker.finished.connect(self._on_area_done)
        self._area_worker.error.connect(lambda e: self._set_status("错误: " + str(e)))
        self._area_worker.progress.connect(self._log)
        self._area_worker.start()

    def _on_area_done(self, result):
        files = result.get("files", [])
        self._set_status(self._t("area_done", n=len(files)))
        for f in files:
            self._log("  输出: " + f)
        # 面积数据存在则弹出交互式分布图（对齐 ESP2 的 AreaChartDialog）
        data = result.get("area_data")
        if data:
            label = result.get("unit_label", "kcal/mol")
            try:
                # area_data 已是 [(name, [(center, area, pct), ...]), ...] 列表
                dlg = AreaChartDialog(self, results=data, unit_label=label)
                dlg.exec_()
            except Exception as e:
                import traceback
                self._log("交互式面积图打开失败: " + str(e))
                traceback.print_exc()
                QMessageBox.critical(self, "面积图对话框错误", str(e))

    # ── 视图 ──
    def _reset_view(self):
        if self.glw is not None:
            if self.glw._cube is not None:
                ctr, r = compute_bounding_sphere(self.glw._cube)
                self.glw.cam.set_center_zoom(ctr, r)
                self.glw.update()
            else:
                self.glw.frame_to_molecule()

    def _clear_canvas(self):
        if self.glw is not None:
            self.glw._pos_surf = None
            self.glw._neg_surf = None
            self.glw._cube = None
            self.glw.set_esp_point_mode(False)
            self.glw.clear_extrema()
            self.glw.set_show_color_scale(False)
            self.glw.set_vmd_scene(None)   # 清除 VMD 同步场景登记
            self.glw._needs_upload = True
            self.glw.update()

    def reset_view_state(self):
        """新分子载入时清空状态（由主窗口调用）。"""
        self.fchk_file = None
        self._last_fchk_list = None
        self._loaded_cub_pairs = None
        if hasattr(self, "edit_cubdir"):
            self.edit_cubdir.clear()
        self._extrema_pts = []
        if self.glw is not None:
            self.glw.clear_extrema()
            self.glw.set_vmd_scene(None)

    def shutdown(self):
        for w in (self._worker, self._area_worker):
            if w is not None and w.isRunning():
                w.kill()
                w.wait(3000)


def np_bbox(surf):
    """返回等值面顶点的 (中心, 半径)（用于合并视图取景）。"""
    try:
        import numpy as np
        pts = np.asarray(surf.vertices, dtype=np.float64)
        if len(pts) == 0:
            return None
        ctr = pts.mean(axis=0)
        r = float(np.max(np.linalg.norm(pts - ctr, axis=1)))
        return ctr, max(r, 1e-3)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# 面积分布图：分区设置 + 交互式显示对话框（对齐 ESP2 的 BinSettingsDialog /
# AreaChartDialog，含可调配色、叠加、折线、CSV 导出）
# ──────────────────────────────────────────────────────────────────────────
class BinSettingsDialog(QDialog):
    """输入面积分布图的数值范围与分区数（默认 -25~22 kcal/mol，对齐 ESP2）。"""

    def __init__(self, parent=None, lo=-25.0, hi=22.0, n=15):
        super().__init__(parent)
        self.setWindowTitle(_cv("ESP 面积分布 – 分区设置"))
        self.resize(320, 200)
        lay = QFormLayout(self)
        self.edit_lo = QDoubleSpinBox()
        self.edit_lo.setRange(-1000, 1000)
        self.edit_lo.setDecimals(2)
        self.edit_lo.setValue(lo)
        self.edit_hi = QDoubleSpinBox()
        self.edit_hi.setRange(-1000, 1000)
        self.edit_hi.setDecimals(2)
        self.edit_hi.setValue(hi)
        self.edit_n = QSpinBox()
        self.edit_n.setRange(2, 250)
        self.edit_n.setValue(n)
        lay.addRow(_cv("最小值 (kcal/mol):"), self.edit_lo)
        lay.addRow(_cv("最大值 (kcal/mol):"), self.edit_hi)
        lay.addRow(_cv("分区数:"), self.edit_n)
        lay.addRow(QLabel("单位提示: 1 eV = 23.06 kcal/mol; "
                          "1 Hartree = 627.51 kcal/mol"))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addRow(btns)

    def get_values(self):
        return self.edit_lo.value(), self.edit_hi.value(), self.edit_n.value()


class AreaChartDialog(QDialog):
    """交互式 ESP 面积分布柱状图（完整对齐 ESP2 的 AreaChartDialog）。

    弹出一个 matplotlib 嵌入对话框，支持：标题/轴标签/配色/透明度/数值范围/
    网格/图例/峰标注/水平参考线/字号/柱顶数值/多文件叠加或折线对比/
    导出 CSV 与 PNG（jpg/pdf，可调 DPI 与图尺寸）。

    数据格式：``results = [(name, [(center, area, pct), ...]), ...]``，
    与本项目 ``EspAreaWorker`` 的返回格式一致。
    """

    _GROUP_STYLE = "QGroupBox { font-weight: bold; border: 1px solid #BBDEFB; " \
                   "border-radius: 6px; margin-top: 6px; padding: 4px; } " \
                   "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"

    def __init__(self, parent=None, results=None, unit_label="kcal/mol"):
        super().__init__(parent)
        self.setWindowTitle(_cv("ESP 表面分区面积分布"))
        self.resize(1180, 720)
        # results: [(name, [(center, area, pct), ...]), ...]
        self.all_data = list(results or [])
        self.unit_label = unit_label
        self.current_idx = 0
        self._overlay_mode = False
        self._chart_type = "bar"

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── 左侧：matplotlib 画布 + 工具栏 ──
        left = QWidget()
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(0, 0, 0, 0)
        self._fig = _MplFigure(figsize=(7, 5), dpi=100)
        self._canvas = _FigureCanvas(self._fig)
        self._ax = self._fig.add_subplot(111)
        from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        left_v.addWidget(self._canvas, stretch=1)
        left_v.addWidget(self._toolbar)
        root.addWidget(left, stretch=1)

        # ── 右侧：可滚动设置面板 ──
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(360)
        right_inner = QWidget()
        right = QVBoxLayout(right_inner)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        # 卡片：标题与坐标轴（默认英文，可改成中文；matplotlib 已配中文字体）
        title_box = QGroupBox(_cv("标题与坐标轴"))
        title_box.setStyleSheet(self._GROUP_STYLE)
        title_gl = QGridLayout()
        title_gl.setContentsMargins(12, 8, 12, 12)
        title_gl.setVerticalSpacing(8)
        title_gl.setHorizontalSpacing(10)
        title_gl.setColumnStretch(1, 1)
        title_gl.addWidget(QLabel(_cv("标题")), 0, 0)
        self.title_edit = QLineEdit("ESP Area Distribution")
        title_gl.addWidget(self.title_edit, 0, 1)
        title_gl.addWidget(QLabel(_cv("X 轴标签")), 1, 0)
        self.xlabel_edit = QLineEdit(f"ESP ({unit_label})")
        title_gl.addWidget(self.xlabel_edit, 1, 1)
        title_gl.addWidget(QLabel(_cv("Y 轴标签")), 2, 0)
        self.ylabel_edit = QLineEdit("Surface Area (Å²)")
        title_gl.addWidget(self.ylabel_edit, 2, 1)
        title_gl.addWidget(QLabel(_cv("Y 轴数据")), 3, 0)
        self._y_mode_combo = QComboBox()
        self._y_mode_combo.addItems([_cv("面积 (Å²)"), _cv("百分比 (%)")])
        title_gl.addWidget(self._y_mode_combo, 3, 1)
        self._align_grid_labels(title_gl)
        title_box.setLayout(title_gl)
        right.addWidget(title_box)

        # 卡片：X 轴范围
        xrange_box = QGroupBox(_cv("X 轴范围"))
        xrange_box.setStyleSheet(self._GROUP_STYLE)
        data_gl = QGridLayout()
        data_gl.setContentsMargins(12, 8, 12, 12)
        data_gl.setVerticalSpacing(8)
        data_gl.setHorizontalSpacing(10)
        data_gl.setColumnStretch(1, 1)
        data_gl.addWidget(QLabel(_cv("最小值")), 0, 0)
        self._xmin_spin = QDoubleSpinBox()
        self._xmin_spin.setRange(-100, 100)
        self._xmin_spin.setValue(-25.0)
        self._xmin_spin.setDecimals(1)
        data_gl.addWidget(self._xmin_spin, 0, 1)
        data_gl.addWidget(QLabel(_cv("最大值")), 1, 0)
        self._xmax_spin = QDoubleSpinBox()
        self._xmax_spin.setRange(-100, 100)
        self._xmax_spin.setValue(22.0)
        self._xmax_spin.setDecimals(1)
        data_gl.addWidget(self._xmax_spin, 1, 1)
        self._xrange_cb = QCheckBox(_cv("自定义范围"))
        self._xrange_cb.stateChanged.connect(self._refresh_chart)
        data_gl.addWidget(self._xrange_cb, 2, 0, 1, 2)
        self._align_grid_labels(data_gl)
        xrange_box.setLayout(data_gl)
        right.addWidget(xrange_box)

        # 卡片：样式设置
        style_box = QGroupBox(_cv("样式设置"))
        style_box.setStyleSheet(self._GROUP_STYLE)
        style_gl = QGridLayout()
        style_gl.setContentsMargins(12, 8, 12, 12)
        style_gl.setVerticalSpacing(8)
        style_gl.setHorizontalSpacing(10)
        style_gl.setColumnStretch(1, 1)
        self._grid_cb = QCheckBox(_cv("网格线"))
        self._grid_cb.setChecked(False)
        self._grid_cb.stateChanged.connect(self._refresh_chart)
        style_gl.addWidget(self._grid_cb, 0, 0)
        self._legend_cb = QCheckBox(_cv("图例"))
        self._legend_cb.setChecked(True)
        self._legend_cb.stateChanged.connect(self._refresh_chart)
        style_gl.addWidget(self._legend_cb, 0, 1)
        style_gl.addWidget(QLabel(_cv("配色 (colormap)")), 1, 0)
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(["RWB", "BWR", "Jet", "Viridis", "RdBu", "coolwarm", "Spectral"])
        self._cmap_combo.currentIndexChanged.connect(self._refresh_chart)
        style_gl.addWidget(self._cmap_combo, 1, 1)
        style_gl.addWidget(QLabel(_cv("透明度")), 2, 0)
        alpha_row = QHBoxLayout()
        self._alpha_slider = QSlider(Qt.Horizontal)
        self._alpha_slider.setRange(10, 100)
        self._alpha_slider.setValue(85)
        self._alpha_slider.valueChanged.connect(self._refresh_chart)
        alpha_row.addWidget(self._alpha_slider, stretch=1)
        self._alpha_label = QLabel("0.85")
        self._alpha_label.setFixedWidth(36)
        self._alpha_slider.valueChanged.connect(
            lambda v: self._alpha_label.setText(f"{v / 100:.2f}"))
        alpha_row.addWidget(self._alpha_label)
        style_gl.addLayout(alpha_row, 2, 1)
        self._align_grid_labels(style_gl)
        style_box.setLayout(style_gl)
        right.addWidget(style_box)

        # 卡片：标注
        anno_box = QGroupBox(_cv("标注"))
        anno_box.setStyleSheet(self._GROUP_STYLE)
        anno_gl = QGridLayout()
        anno_gl.setContentsMargins(12, 8, 12, 12)
        anno_gl.setVerticalSpacing(8)
        anno_gl.setHorizontalSpacing(10)
        anno_gl.setColumnStretch(1, 1)
        self._mark_peak_cb = QCheckBox(_cv("标记最高/最低点"))
        self._mark_peak_cb.setChecked(False)
        self._mark_peak_cb.stateChanged.connect(self._refresh_chart)
        anno_gl.addWidget(self._mark_peak_cb, 0, 0, 1, 2)
        self._hline_cb = QCheckBox(_cv("水平参考线"))
        self._hline_cb.setChecked(False)
        self._hline_cb.stateChanged.connect(self._refresh_chart)
        anno_gl.addWidget(self._hline_cb, 1, 0)
        self._hline_spin = QDoubleSpinBox()
        self._hline_spin.setRange(0, 9999)
        self._hline_spin.setValue(0)
        self._hline_spin.setDecimals(1)
        self._hline_spin.setFixedWidth(90)
        self._hline_spin.setEnabled(False)
        self._hline_cb.stateChanged.connect(
            lambda s: self._hline_spin.setEnabled(bool(s)))
        self._hline_spin.valueChanged.connect(self._refresh_chart)
        anno_gl.addWidget(self._hline_spin, 1, 1)
        self._align_grid_labels(anno_gl)
        anno_box.setLayout(anno_gl)
        right.addWidget(anno_box)

        # 卡片：字号设置
        font_box = QGroupBox(_cv("字号设置"))
        font_box.setStyleSheet(self._GROUP_STYLE)
        font_gl = QGridLayout()
        font_gl.setContentsMargins(12, 8, 12, 12)
        font_gl.setVerticalSpacing(8)
        font_gl.setHorizontalSpacing(10)
        font_gl.setColumnStretch(1, 1)
        font_gl.addWidget(QLabel(_cv("刻度字号")), 0, 0)
        self.tick_fs_spin = QSpinBox()
        self.tick_fs_spin.setRange(6, 20)
        self.tick_fs_spin.setValue(9)
        self.tick_fs_spin.setFixedWidth(90)
        self.tick_fs_spin.valueChanged.connect(self._refresh_chart)
        font_gl.addWidget(self.tick_fs_spin, 0, 1)
        font_gl.addWidget(QLabel(_cv("数值字号")), 1, 0)
        self.bar_fs_spin = QSpinBox()
        self.bar_fs_spin.setRange(5, 18)
        self.bar_fs_spin.setValue(7)
        self.bar_fs_spin.setFixedWidth(90)
        self.bar_fs_spin.valueChanged.connect(self._refresh_chart)
        font_gl.addWidget(self.bar_fs_spin, 1, 1)
        font_gl.addWidget(QLabel(_cv("标题字号")), 2, 0)
        self.title_fs_spin = QSpinBox()
        self.title_fs_spin.setRange(8, 24)
        self.title_fs_spin.setValue(14)
        self.title_fs_spin.setFixedWidth(90)
        self.title_fs_spin.valueChanged.connect(self._refresh_chart)
        font_gl.addWidget(self.title_fs_spin, 2, 1)
        font_gl.addWidget(QLabel(_cv("轴标签字号")), 3, 0)
        self.label_fs_spin = QSpinBox()
        self.label_fs_spin.setRange(6, 20)
        self.label_fs_spin.setValue(12)
        self.label_fs_spin.setFixedWidth(90)
        self.label_fs_spin.valueChanged.connect(self._refresh_chart)
        font_gl.addWidget(self.label_fs_spin, 3, 1)
        self._show_bar_val_cb = QCheckBox(_cv("显示柱顶数值"))
        self._show_bar_val_cb.setChecked(True)
        self._show_bar_val_cb.stateChanged.connect(self._refresh_chart)
        font_gl.addWidget(self._show_bar_val_cb, 4, 0, 1, 2)
        self._align_grid_labels(font_gl)
        font_box.setLayout(font_gl)
        right.addWidget(font_box)

        # 卡片：多文件
        if len(self.all_data) > 1:
            mf_box = QGroupBox(_cv("多文件"))
            mf_box.setStyleSheet(self._GROUP_STYLE)
            mf_gl = QGridLayout()
            mf_gl.setContentsMargins(12, 8, 12, 12)
            mf_gl.setVerticalSpacing(8)
            mf_gl.setHorizontalSpacing(10)
            mf_gl.setColumnStretch(1, 1)
            mf_gl.addWidget(QLabel(_cv("文件")), 0, 0)
            self.file_combo = QComboBox()
            self.file_combo.addItems([d[0] for d in self.all_data])
            self.file_combo.currentIndexChanged.connect(self._on_file_changed)
            mf_gl.addWidget(self.file_combo, 0, 1)
            self._overlay_cb = QCheckBox(_cv("叠加模式"))
            self._overlay_cb.stateChanged.connect(self._on_overlay_toggled)
            mf_gl.addWidget(self._overlay_cb, 1, 0)
            self._chart_type_combo = QComboBox()
            self._chart_type_combo.addItems([_cv("柱状图"), _cv("折线图")])
            self._chart_type_combo.setEnabled(False)
            self._chart_type_combo.currentIndexChanged.connect(self._on_chart_type_changed)
            mf_gl.addWidget(self._chart_type_combo, 1, 1)
            self._align_grid_labels(mf_gl)
            mf_box.setLayout(mf_gl)
            right.addWidget(mf_box)

        # 卡片：输出
        out_box = QGroupBox(_cv("输出"))
        out_box.setStyleSheet(self._GROUP_STYLE)
        out_gl = QGridLayout()
        out_gl.setContentsMargins(12, 8, 12, 12)
        out_gl.setVerticalSpacing(8)
        out_gl.setHorizontalSpacing(10)
        out_gl.setColumnStretch(1, 1)
        out_gl.addWidget(QLabel("DPI"), 0, 0)
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 1200)
        self._dpi_spin.setValue(300)
        self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setFixedWidth(90)
        out_gl.addWidget(self._dpi_spin, 0, 1)
        out_gl.addWidget(QLabel(_cv("图宽 (inch)")), 1, 0)
        self._fig_w_spin = QDoubleSpinBox()
        self._fig_w_spin.setRange(3, 20)
        self._fig_w_spin.setValue(7)
        self._fig_w_spin.setDecimals(1)
        self._fig_w_spin.setFixedWidth(90)
        out_gl.addWidget(self._fig_w_spin, 1, 1)
        out_gl.addWidget(QLabel(_cv("图高 (inch)")), 2, 0)
        self._fig_h_spin = QDoubleSpinBox()
        self._fig_h_spin.setRange(3, 20)
        self._fig_h_spin.setValue(7)
        self._fig_h_spin.setDecimals(1)
        self._fig_h_spin.setFixedWidth(90)
        out_gl.addWidget(self._fig_h_spin, 2, 1)
        self._align_grid_labels(out_gl)
        out_box.setLayout(out_gl)
        right.addWidget(out_box)

        right.addStretch()

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        csv_btn = QPushButton(_cv("导出 CSV"))
        csv_btn.setCursor(QCursor(Qt.PointingHandCursor))
        csv_btn.clicked.connect(self._export_csv)
        btn_row.addWidget(csv_btn)
        save_btn = QPushButton(_cv("保存图片"))
        save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        save_btn.setStyleSheet(
            "QPushButton { background: #1E88E5; color: white; font-weight: bold; "
            "padding: 8px 20px; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #1976D2; }")
        save_btn.clicked.connect(self._save_chart)
        btn_row.addWidget(save_btn)
        close_btn = QPushButton(_cv("关闭"))
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        right.addLayout(btn_row)

        right_scroll.setWidget(right_inner)
        root.addWidget(right_scroll, stretch=0)

        self.setLayout(root)
        self._refresh_chart()

    # ── 辅助方法 ──
    @staticmethod
    def _align_grid_labels(grid):
        for i in range(grid.count()):
            w = grid.itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def _get_cmap(self):
        names = ["bwr_r", "bwr", "jet", "viridis", "RdBu", "coolwarm", "Spectral"]
        idx = self._cmap_combo.currentIndex()
        return plt.get_cmap(names[idx] if idx < len(names) else "bwr_r")

    def _get_alpha(self):
        return self._alpha_slider.value() / 100.0

    def _on_overlay_toggled(self, state):
        self._overlay_mode = bool(state)
        self.file_combo.setEnabled(not self._overlay_mode)
        self._chart_type_combo.setEnabled(self._overlay_mode)
        self._refresh_chart()

    def _on_chart_type_changed(self, idx):
        self._chart_type = "bar" if idx == 0 else "line"
        self._refresh_chart()

    def _on_file_changed(self, idx):
        self.current_idx = idx
        self._refresh_chart()

    def _refresh_chart(self):
        if self._ax is None:
            return
        self._ax.clear()

        if self._overlay_mode and len(self.all_data) > 1:
            if self._chart_type == "line":
                self._draw_overlay_line()
            else:
                self._draw_overlay()
        else:
            self._draw_single()

        if self._grid_cb.isChecked():
            self._ax.grid(True, linestyle='--', alpha=0.7, color='#999999', linewidth=0.8)
        else:
            self._ax.grid(False)

        w = self._fig_w_spin.value()
        h = self._fig_h_spin.value()
        self._fig.set_size_inches(w, h)
        self._fig.tight_layout()
        self._canvas.draw_idle()

    def _apply_annotations(self, centers, areas):
        """标记最高/最低点与水平参考线。"""
        if self._mark_peak_cb.isChecked() and areas:
            max_val = max(areas)
            min_val = min(areas)
            max_idx = areas.index(max_val)
            min_idx = areas.index(min_val)
            self._ax.annotate(
                f'MAX: {max_val:.1f}', (centers[max_idx], max_val),
                textcoords="offset points", xytext=(0, 14),
                ha='center', fontsize=9, fontweight='bold', color='#D32F2F',
                arrowprops=dict(arrowstyle='->', color='#D32F2F', lw=1.5),
            )
            if min_idx != max_idx:
                self._ax.annotate(
                    f'MIN: {min_val:.1f}', (centers[min_idx], min_val),
                    textcoords="offset points", xytext=(0, -18),
                    ha='center', fontsize=9, fontweight='bold', color='#1565C0',
                    arrowprops=dict(arrowstyle='->', color='#1565C0', lw=1.5),
                )
        if self._hline_cb.isChecked():
            self._ax.axhline(y=self._hline_spin.value(), color='#666666',
                             linestyle='--', linewidth=1.2, alpha=0.7)

    # ── 绘制方法 ──
    def _draw_single(self):
        _, data = self.all_data[self.current_idx]
        pct_mode = self._y_mode_combo.currentIndex() == 1
        centers = [d[0] for d in data]
        areas = [d[2] for d in data] if pct_mode else [d[1] for d in data]
        if len(centers) > 1:
            bin_width = centers[1] - centers[0]
        else:
            bin_width = 2.0
        data_min, data_max = min(centers), max(centers)
        pad = max(0.5, (data_max - data_min) * 0.05)
        cmap = self._get_cmap()
        norm = mcolors.TwoSlopeNorm(vmin=data_min - pad, vcenter=0, vmax=data_max + pad)
        colors = [cmap(norm(c)) for c in centers]
        alpha = self._get_alpha()
        bars = self._ax.bar(
            centers, areas, width=bin_width * 0.92, align='center',
            color=colors, edgecolor='#333333', linewidth=0.8, alpha=alpha,
        )
        y_unit = "%" if pct_mode else "Å²"
        self._ax.set_xlabel(self.xlabel_edit.text() or "ESP", fontsize=self.label_fs_spin.value())
        self._ax.set_ylabel(self.ylabel_edit.text() or f"Area ({y_unit})", fontsize=self.label_fs_spin.value())
        self._ax.set_title(self.title_edit.text() or "Area Distribution",
                           fontsize=self.title_fs_spin.value(), fontweight='bold', pad=12)
        self._ax.set_xticks(centers)
        tick_fs = self.tick_fs_spin.value()
        self._ax.set_xticklabels([f'{c:.1f}' for c in centers], rotation=45, ha='right', fontsize=tick_fs)
        self._ax.tick_params(axis='y', labelsize=tick_fs)
        max_area = max(areas) if max(areas) > 0 else 1
        if self._show_bar_val_cb.isChecked():
            bar_fs = self.bar_fs_spin.value()
            for bar, val in zip(bars, areas):
                if val > 0:
                    self._ax.text(
                        bar.get_x() + bar.get_width() / 2.,
                        bar.get_height() + max_area * 0.02,
                        f'{val:.1f}', ha='center', va='bottom',
                        fontsize=bar_fs, rotation=90, color='#333333',
                    )
        self._ax.spines['top'].set_visible(True)
        self._ax.spines['right'].set_visible(True)
        if self._xrange_cb.isChecked():
            self._ax.set_xlim(self._xmin_spin.value(), self._xmax_spin.value())
        else:
            self._ax.set_xlim(centers[0] - bin_width, centers[-1] + bin_width)
        self._ax.set_ylim(0, max_area * 1.18)
        self._apply_annotations(centers, areas)

    def _draw_overlay(self):
        all_centers = set()
        for _, data in self.all_data:
            for d in data:
                all_centers.add(round(d[0], 2))
        centers = sorted(all_centers)
        n_centers = len(centers)
        bin_width = centers[1] - centers[0] if n_centers > 1 else 2.0
        n_mols = len(self.all_data)
        pct_mode = self._y_mode_combo.currentIndex() == 1
        y_idx = 2 if pct_mode else 1
        mol_colors = ['#E53935', '#1E88E5', '#43A047', '#FB8C00',
                      '#8E24AA', '#00ACC1', '#F4511E', '#3949AB']
        total_width = bin_width * 0.85
        bar_w = total_width / n_mols
        alpha = self._get_alpha()
        all_bars = []
        max_val = 0
        for mi, (fname, data) in enumerate(self.all_data):
            data_map = {round(d[0], 2): d[y_idx] for d in data}
            areas = [data_map.get(c, 0.0) for c in centers]
            max_val = max(max_val, max(areas) if areas else 0)
            offset = (mi - (n_mols - 1) / 2) * bar_w
            pos = [c + offset for c in centers]
            short_name = os.path.splitext(fname)[0]
            if len(short_name) > 25:
                short_name = short_name[:24] + "…"
            bars = self._ax.bar(
                pos, areas, width=bar_w * 0.92, align='center',
                color=mol_colors[mi % len(mol_colors)],
                edgecolor='#222222', linewidth=0.6, alpha=alpha,
                label=short_name,
            )
            all_bars.append(bars)
        y_unit = "%" if pct_mode else "Å²"
        self._ax.set_xlabel(self.xlabel_edit.text() or "ESP", fontsize=self.label_fs_spin.value())
        self._ax.set_ylabel(self.ylabel_edit.text() or f"Area ({y_unit})", fontsize=self.label_fs_spin.value())
        self._ax.set_title(self.title_edit.text() or "Area Distribution",
                           fontsize=self.title_fs_spin.value(), fontweight='bold', pad=12)
        self._ax.set_xticks(centers)
        tick_fs = self.tick_fs_spin.value()
        self._ax.set_xticklabels([f'{c:.1f}' for c in centers], rotation=45, ha='right', fontsize=tick_fs)
        self._ax.tick_params(axis='y', labelsize=tick_fs)
        if self._show_bar_val_cb.isChecked():
            bar_fs = self.bar_fs_spin.value()
            for bars in all_bars:
                for bar in bars:
                    val = bar.get_height()
                    if val > 0:
                        self._ax.text(
                            bar.get_x() + bar.get_width() / 2.,
                            val + max_val * 0.01,
                            f'{val:.1f}', ha='center', va='bottom',
                            fontsize=bar_fs, rotation=90, color='#333333',
                        )
        if max_val > 0:
            self._ax.set_ylim(0, max_val * 1.22)
        data_min = min(centers)
        data_max = max(centers)
        pad = max(0.5, (data_max - data_min) * 0.05)
        self._ax.set_xlim(centers[0] - bin_width * 0.6, centers[-1] + bin_width * 0.6)
        self._ax.spines['top'].set_visible(True)
        self._ax.spines['right'].set_visible(True)
        if self._legend_cb.isChecked() and n_mols <= 8:
            self._ax.legend(loc='upper right', fontsize=9, framealpha=0.9)
        annotate_areas = [
            max((dict((round(d[0], 2), d[y_idx]) for d in data).get(c, 0.0)
                 for _, data in self.all_data))
            for c in centers
        ]
        self._apply_annotations(centers, annotate_areas)

    def _draw_overlay_line(self):
        all_centers = set()
        for _, data in self.all_data:
            for d in data:
                all_centers.add(round(d[0], 2))
        centers = sorted(all_centers)
        pct_mode = self._y_mode_combo.currentIndex() == 1
        y_idx = 2 if pct_mode else 1
        mol_colors = ['#E53935', '#1E88E5', '#43A047', '#FB8C00',
                      '#8E24AA', '#00ACC1', '#F4511E', '#3949AB']
        markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p']
        n_mols = len(self.all_data)
        max_val = 0
        data_min, data_max = min(centers), max(centers)
        for mi, (fname, data) in enumerate(self.all_data):
            data_map = {round(d[0], 2): d[y_idx] for d in data}
            areas = [data_map.get(c, 0.0) for c in centers]
            max_val = max(max_val, max(areas) if areas else 0)
            short_name = os.path.splitext(fname)[0]
            if len(short_name) > 25:
                short_name = short_name[:24] + "…"
            color = mol_colors[mi % len(mol_colors)]
            marker = markers[mi % len(markers)]
            self._ax.plot(
                centers, areas, color=color, marker=marker,
                linewidth=2.2, markersize=7, label=short_name,
                markeredgecolor='#222222', markeredgewidth=0.5,
            )
            if self._show_bar_val_cb.isChecked():
                bar_fs = self.bar_fs_spin.value()
                for cx, ay in zip(centers, areas):
                    if ay > 0:
                        self._ax.annotate(
                            f'{ay:.1f}', (cx, ay),
                            textcoords="offset points", xytext=(0, 7),
                            ha='center', fontsize=bar_fs, color='#333333',
                        )
        y_unit = "%" if pct_mode else "Å²"
        self._ax.set_xlabel(self.xlabel_edit.text() or "ESP", fontsize=self.label_fs_spin.value())
        self._ax.set_ylabel(self.ylabel_edit.text() or f"Area ({y_unit})", fontsize=self.label_fs_spin.value())
        self._ax.set_title(self.title_edit.text() or "Area Distribution",
                           fontsize=self.title_fs_spin.value(), fontweight='bold', pad=12)
        tick_fs = self.tick_fs_spin.value()
        self._ax.set_xticks(centers)
        self._ax.set_xticklabels([f'{c:.1f}' for c in centers], rotation=45, ha='right', fontsize=tick_fs)
        self._ax.tick_params(axis='y', labelsize=tick_fs)
        pad = max(0.5, (data_max - data_min) * 0.05)
        if self._xrange_cb.isChecked():
            self._ax.set_xlim(self._xmin_spin.value(), self._xmax_spin.value())
        else:
            self._ax.set_xlim(data_min - pad, data_max + pad)
        if max_val > 0:
            self._ax.set_ylim(0, max_val * 1.18)
        self._ax.spines['top'].set_visible(True)
        self._ax.spines['right'].set_visible(True)
        if self._legend_cb.isChecked() and n_mols <= 8:
            self._ax.legend(loc='upper right', fontsize=9, framealpha=0.9)

    # ── 导出 ──
    def _export_csv(self):
        if len(self.all_data) == 1:
            default_name = os.path.splitext(self.all_data[0][0])[0] + "_esp_area.csv"
        else:
            default_name = "esp_area_all.csv"
        path, _ = save_file(self, _cv("导出 CSV"), default_name, "CSV (*.csv)")
        if not path:
            return
        try:
            import csv
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["File", "Center (kcal/mol)", "Area (Å²)", "Percentage (%)"])
                for fname, data in self.all_data:
                    base = os.path.basename(fname)
                    for center, area, pct in data:
                        writer.writerow([base, f"{center:.2f}", f"{area:.2f}", f"{pct:.2f}"])
            QMessageBox.information(self, "完成", f"已导出:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def _save_chart(self):
        default_name = os.path.splitext(self.all_data[self.current_idx][0])[0] + "_esp_area.png"
        path, _ = save_file(
            self, _cv("保存图片"), default_name,
            "PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf)")
        if path:
            try:
                dpi = self._dpi_spin.value()
                self._fig.savefig(path, dpi=dpi, bbox_inches='tight', facecolor='white')
                QMessageBox.information(self, "完成", f"已保存:\n{path}\n(DPI={dpi})")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {e}")
