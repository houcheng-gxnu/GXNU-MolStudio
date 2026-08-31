# -*- coding: utf-8 -*-
"""
AIM 拓扑分析面板（GXNU MolStudio 的第七个 tab）。

移植自 AIM_Qt5_Analyzer.py（广西师范大学侯成课题组），实现完整功能：
  - fchk / wfn 输入 → 调用 Multiwfn 完成 AIM 拓扑分析
    （生成 mol.pdb / CPs.pdb / paths.pdb，可选 CPprop.txt）
  - 临界点（CP）按类型着色、梯度路径（bond path）点云，直接画进左侧
    OpenGL 画布（CubGLWidget.glw）；点击 CP 查询 ρ(r)/V(r) 等属性
  - VMD 期刊级预览 + Tachyon 渲染（复用 aim_visualize 模块）

与主程序的关系：
  - Multiwfn / VMD / Tachyon 路径全部走主窗口「⚙️ 路径设置」
    （fchk_orbital.ini），本面板不再重复提供路径输入框。
  - 分子显示复用 glw.set_molecule（自动生成键），不再自绘。
  - 已移除原程序的重复设置：一键样式、虚线键、氢过滤等（主程序已有）。
"""

import os
import re
import csv
import traceback
import subprocess
import tempfile

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QFileDialog, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QCheckBox, QMessageBox, QFrame, QProgressBar,
    QSlider, QAbstractItemView, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QTextCursor

# 原子解析复用项目已有实现（molcanvas.get_atoms_from_fchk 返回
# [(idx, symbol, anum, (x,y,z))]，坐标 Å，与 glw.set_molecule 期望一致）
try:
    from molcanvas import get_atoms_from_fchk, ELEMENT_SYMBOLS
except Exception:  # pragma: no cover
    get_atoms_from_fchk = None
    ELEMENT_SYMBOLS = {}

# VMD 渲染模块（已精简：不含独立 GUI 与路径配置）
try:
    import aim_visualize
except Exception:  # pragma: no cover
    aim_visualize = None

BOHR_TO_ANGSTROM = 1.8897259886   # Å / Bohr

# ── i18n 字典（AIM 面板）──
_AIM_TR = {
    "zh": {
        "cp_log": "CP 查询记录",
        "queried_only": "仅显示已查询的 CP",
        "export_csv": "导出 CSV",
        "run_log": "运行日志",
        "grp_run": "运行",
        "run_btn": "◆  开始 AIM 分析",
        "stop": "■  停止",
        "no_mol": "尚未加载分子",
        "no_atoms": "未找到原子信息",
        "atoms_n": "{n} 原子  |  {name}",
        "load_cps": "载入已有 CPs.pdb",
        "load_paths": "载入已有 paths.pdb",
        "load_cpprop": "载入 CPprop.txt",
        "grp_settings": "AIM 分析设置",
        "large": "大体系（跳过原子中心初猜，用于大分子）",
        "show_cp_types": "显示 CP 类型:",
        "cp_c": "(3,-3)核", "cp_n": "(3,-1)键",
        "cp_o": "(3,+1)环", "cp_f": "(3,+3)笼",
        "cp_size": "CP 点大小",
        "path_width": "路径点粗细",
        "refresh": "刷新画布",
        "grp_legend": "图例",
        "grp_vmd": "VMD 渲染（期刊级出图）",
        "style": "风格",
        "vmd_path_hint": "VMD / Tachyon 路径请在主窗口 ⚙️ 路径设置中配置",
        "vmd_preview": "在 VMD 中预览",
        "render_png": "渲染当前视角为 PNG",
        "col_idx": "编号", "col_type": "类型",
        "col_rho": "电子密度ρ(r)", "col_v": "势能密度V(r)",
        "warn": "警告", "error": "错误", "hint": "提示",
        "export_fail": "导出失败",
        "cps_fail": "无法读取 CP 文件或文件中没有临界点！",
        "paths_fail": "无法读取 Paths 文件！",
        "cpprop_fail": "无法读取 CPprop.txt 文件！",
        "running": "程序正在运行中！",
        "need_mw": "请先在主窗口 ⚙️ 路径设置中配置 Multiwfn！",
        "need_input": "请先在主窗口载入输入文件 (.fchk / .wfn)！",
        "need_cps": "请先加载/生成 CPs.pdb！",
        "need_paths": "请先加载/生成 paths.pdb！",
        "need_mol": "未找到 mol.pdb，请先运行 AIM 分析！",
        "no_aimviz": "aim_visualize 模块缺失！",
        "need_vmd": "未找到 VMD，请先在 ⚙️ 路径设置中配置！",
        "need_preview": "请先点击“在 VMD 中预览”。",
        "cpprop_hint": "请先加载 CPprop.txt 文件查看 CP 属性\n",
        "cp_not_found": "CP #{serial} ({cp_type}) 属性未找到\n",
        "tbl_empty": "查询表为空，请先点击 CP 查询。",
        "loaded_cps": "已加载 CPs: {name} ({n} 个)\n",
        "loaded_paths": "已加载 Paths: {name} ({np} 条键径, {npts} 个点)\n",
        "loaded_cpprop": "已加载 CPprop: {name} ({n} 个 CP)\n",
        "cpprop_tip": "提示: 点击画布中的 CP 可查看其属性\n",
        "done_auto": "AIM 分析完成，自动加载结果。\n",
        "done_none": "AIM 分析未成功生成结果，请检查 Multiwfn 输出。\n",
        "vmd_previewed": "已在 VMD 中预览（端口 {port}）。\n",
        "vmd_fail": "VMD 预览失败: {e}\n{tb}\n",
        "rendered": "已渲染: {png}\n",
        "render_fail": "渲染失败: {msg}\n",
        "render_fail_e": "渲染失败: {e}\n{tb}\n",
        "draw_err": "画布绘制错误: {e}\n{tb}\n",
        "parsed_err": "解析错误: {e}\n{tb}\n",
        "loaded_mol": "已加载分子: {name} ({n} 原子)\n",
        "exported": "已导出: {path}\n",
        "dlg_cps": "选择 CPs.pdb", "dlg_paths": "选择 paths.pdb",
        "dlg_cpprop": "选择 CPprop.txt", "dlg_save_csv": "导出 CP 查询表",
    },
    "en": {
        "cp_log": "CP Query Log",
        "queried_only": "Queried CPs only",
        "export_csv": "Export CSV",
        "run_log": "Run Log",
        "grp_run": "Run",
        "run_btn": "◆  Start AIM Analysis",
        "stop": "■  Stop",
        "no_mol": "No molecule loaded",
        "no_atoms": "No atom info found",
        "atoms_n": "{n} atoms  |  {name}",
        "load_cps": "Load CPs.pdb",
        "load_paths": "Load paths.pdb",
        "load_cpprop": "Load CPprop.txt",
        "grp_settings": "AIM Settings",
        "large": "Large system (skip atom-centered guess)",
        "show_cp_types": "CP types:",
        "cp_c": "(3,-3) nuclei", "cp_n": "(3,-1) bonds",
        "cp_o": "(3,+1) rings", "cp_f": "(3,+3) cages",
        "cp_size": "CP point size",
        "path_width": "Path point width",
        "refresh": "Refresh Canvas",
        "grp_legend": "Legend",
        "grp_vmd": "VMD Rendering (Publication)",
        "style": "Style",
        "vmd_path_hint": "Set VMD / Tachyon paths in ⚙️ Path Settings (main window)",
        "vmd_preview": "Preview in VMD",
        "render_png": "Render Current View (PNG)",
        "col_idx": "Index", "col_type": "Type",
        "col_rho": "Electron density ρ(r)", "col_v": "Potential density V(r)",
        "warn": "Warning", "error": "Error", "hint": "Notice",
        "export_fail": "Export Failed",
        "cps_fail": "Failed to read CP file, or no critical points in it!",
        "paths_fail": "Failed to read Paths file!",
        "cpprop_fail": "Failed to read CPprop.txt!",
        "running": "An analysis is already running!",
        "need_mw": "Configure Multiwfn in ⚙️ Path Settings (main window) first!",
        "need_input": "Load an input file (.fchk / .wfn) in the main window first!",
        "need_cps": "Load or generate CPs.pdb first!",
        "need_paths": "Load or generate paths.pdb first!",
        "need_mol": "mol.pdb not found — run AIM analysis first!",
        "no_aimviz": "aim_visualize module missing!",
        "need_vmd": "VMD not found — configure it in ⚙️ Path Settings first!",
        "need_preview": "Click \"Preview in VMD\" first.",
        "cpprop_hint": "Load CPprop.txt first to view CP properties\n",
        "cp_not_found": "CP #{serial} ({cp_type}) properties not found\n",
        "tbl_empty": "Query table is empty — run a CP query first.",
        "loaded_cps": "Loaded CPs: {name} ({n})\n",
        "loaded_paths": "Loaded Paths: {name} ({np} bond paths, {npts} points)\n",
        "loaded_cpprop": "Loaded CPprop: {name} ({n} CPs)\n",
        "cpprop_tip": "Tip: click a CP in the canvas to view its properties\n",
        "done_auto": "AIM analysis done — results auto-loaded.\n",
        "done_none": "AIM analysis produced no results — check Multiwfn output.\n",
        "vmd_previewed": "Previewed in VMD (port {port}).\n",
        "vmd_fail": "VMD preview failed: {e}\n{tb}\n",
        "rendered": "Rendered: {png}\n",
        "render_fail": "Render failed: {msg}\n",
        "render_fail_e": "Render failed: {e}\n{tb}\n",
        "draw_err": "Canvas draw error: {e}\n{tb}\n",
        "parsed_err": "Parse error: {e}\n{tb}\n",
        "loaded_mol": "Loaded molecule: {name} ({n} atoms)\n",
        "exported": "Exported: {path}\n",
        "dlg_cps": "Select CPs.pdb", "dlg_paths": "Select paths.pdb",
        "dlg_cpprop": "Select CPprop.txt", "dlg_save_csv": "Export CP Query Table",
    },
}


# ── 临界点类型定义（与原程序一致：CPs.pdb 用 name 列 C/N/O/F 表示类型）──
CP_NAMES = {
    'C': '(3,-3)核',
    'N': '(3,-1)键',
    'O': '(3,+1)环',
    'F': '(3,+3)笼',
}
CP_NAMES_SHORT = {
    'C': 'NNA',
    'N': 'BCP',
    'O': 'RCP',
    'F': 'CCP',
}
CP_COLORS = {   # 十六进制（与原程序一致，VMD ColorID 亦由此映射）
    'C': '#FF00FF',   # (3,-3) 核临界点 ─ 紫色
    'N': '#00FF00',   # (3,-1) 键临界点 ─ 绿色
    'O': '#FFFF00',   # (3,+1) 环临界点 ─ 黄色
    'F': '#00FFFF',   # (3,+3) 笼临界点 ─ 青色
}


def _hex_to_rgb(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


CP_COLOR_RGB = {k: _hex_to_rgb(v) for k, v in CP_COLORS.items()}


# ── fchk / wfn 原子解析 ────────────────────────────────────────
def get_atoms_from_wfn(wfn_path):
    """从 .wfn / .wfx 文件读取原子信息（返回格式与 get_atoms_from_fchk 一致）。"""
    atoms = []
    try:
        with open(wfn_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        atom_section = False
        for line in lines:
            ls = line.strip()
            if ls.startswith('CENTRE ASSIGNMENTS'):
                atom_section = True
                continue
            if atom_section:
                if not ls or ls.startswith('CENTRE'):
                    continue
                if ls.startswith('MO'):
                    break
                parts = ls.split()
                if len(parts) >= 6:
                    try:
                        idx = int(parts[0])
                        sym = parts[1]
                        an = int(parts[2])
                        x = float(parts[3]) * BOHR_TO_ANGSTROM
                        y = float(parts[4]) * BOHR_TO_ANGSTROM
                        z = float(parts[5]) * BOHR_TO_ANGSTROM
                        atoms.append((idx, sym, an, (x, y, z)))
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass
    return atoms


def get_atoms_auto(path):
    """自动识别文件类型读取原子信息。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.wfn', '.wfx'):
        return get_atoms_from_wfn(path)
    if get_atoms_from_fchk is not None:
        try:
            return get_atoms_from_fchk(path)
        except Exception:
            pass
    # 兜底：不是 fchk 就按 wfn 试
    return get_atoms_from_wfn(path)


# ── PDB / CPprop 解析（从原程序照搬，保持列对齐）─────────────────
def get_cps_from_pdb(pdb_path):
    """解析 CPs.pdb，返回 [(serial, cp_type, (x,y,z)), ...]，坐标 Å。
    cp_type ∈ {C,N,O,F}（取自 PDB name 列）。"""
    cps = []
    if not pdb_path or not os.path.isfile(pdb_path):
        return cps
    try:
        with open(pdb_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not (line.startswith("ATOM") or line.startswith("HETATM")):
                    continue
                try:
                    serial = int(line[6:11].strip())
                    name = line[12:16].strip()
                    cp_type = name if name in CP_COLORS else (name[0] if name else '?')
                    x = float(line[30:38].strip())
                    y = float(line[38:46].strip())
                    z = float(line[46:54].strip())
                    cps.append((serial, cp_type, (x, y, z)))
                except (ValueError, IndexError):
                    continue
    except Exception:
        return []
    return cps


def get_paths_from_pdb(pdb_path):
    """解析 paths.pdb，按 resid 分组返回 [{resid, pts:[(x,y,z),...]}, ...]，坐标 Å。

    Multiwfn 键径文件里，同一条键径的所有点共享同一个残基序号（resid，第 23-26 列），
    借此把点云还原成一条条独立的键径，便于后续「只显示与已查询 CP 相关的键径」。
    """
    groups = {}   # resid -> [(x,y,z), ...]
    order = []
    if not pdb_path or not os.path.isfile(pdb_path):
        return []
    try:
        with open(pdb_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not (line.startswith("ATOM") or line.startswith("HETATM")):
                    continue
                try:
                    resid = int(line[22:26].strip())
                    x = float(line[30:38].strip())
                    y = float(line[38:46].strip())
                    z = float(line[46:54].strip())
                except (ValueError, IndexError):
                    continue
                if resid not in groups:
                    groups[resid] = []
                    order.append(resid)
                groups[resid].append((x, y, z))
    except Exception:
        return []
    return [{"resid": r, "pts": groups[r]} for r in order]


def parse_cpprop_txt(txt_path):
    """解析 CPprop.txt，返回 {serial: {prop_name: value}, ...}。

    兼容两种 Multiwfn 输出格式：
      - 旧式: "----- CP  1, Type  (3,-1) -----"  +  "Name : value"
      - 新式: "Critical point  1 :"  +  "CP type: (3,-1)"  +  "Name : value"
    """
    props = {}
    if not txt_path or not os.path.isfile(txt_path):
        return props
    current = None
    try:
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                ls = line.strip()
                m = re.search(r'CP\s+(\d+),\s*Type\s*\(([^)]+)\)', ls)
                if m and ls.startswith("-"):
                    current = int(m.group(1))
                    props[current] = {"CP_type": "(" + m.group(2).strip() + ")"}
                    continue
                m2 = re.match(r'^\s*Critical point\s+(\d+)\s*:?', ls)
                if m2:
                    current = int(m2.group(1))
                    props[current] = {"CP_type": "unknown"}
                    continue
                if current is not None:
                    if re.match(r'^\s*CP type\s*:', ls):
                        props[current]["CP_type"] = ls.split(':', 1)[1].strip()
                        continue
                    if ':' in ls and 'Critical point' not in ls:
                        parts = ls.split(':', 1)
                        if len(parts) == 2:
                            pn, pv = parts[0].strip(), parts[1].strip()
                            try:
                                props[current][pn] = float(pv)
                            except ValueError:
                                props[current][pn] = pv
    except Exception:
        return {}
    return props


# ── Multiwfn 工作线程（照搬原程序：一次性输入序列 + communicate）──
class AIMWorker(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, input_path, output_dir, multiwfn_path, pdb_name,
                 large_system, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.output_dir = output_dir
        self.multiwfn_path = multiwfn_path
        self.pdb_name = pdb_name
        self.large_system = large_system
        self._process = None

    def stop(self):
        if self._process is not None:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            self.log.emit(f"\n错误: {e}\n{traceback.format_exc()}\n")
            self.done.emit(False, self.output_dir)

    def _run_impl(self):
        pdb_name = self.pdb_name if self.pdb_name else "mol.pdb"
        input_lines = ["2", "2", "3"]
        if not self.large_system:
            input_lines.extend(["4", "5"])
        else:
            self.log.emit("大体系模式：已跳过 3/4 原子中心初猜\n")
        input_lines.append("8")
        input_lines.extend([
            "-4", "6", "0", "-5", "6", "0", "7",
            "-1", "-10", "100", "2", "1", pdb_name, "0", "q",
        ])
        input_seq = "\n".join(input_lines) + "\n"

        self.log.emit("=" * 60 + "\n")
        self.log.emit("开始 AIM 分析...\n")
        self.log.emit(f"  Multiwfn: {self.multiwfn_path}\n")
        self.log.emit(f"  输入文件: {self.input_path}\n")
        self.log.emit(f"  输出目录: {self.output_dir}\n")
        self.log.emit(f"  输出 PDB : {pdb_name}\n")
        self.log.emit("-" * 60 + "\n")

        os.makedirs(self.output_dir, exist_ok=True)
        env = os.environ.copy()
        mw_dir = os.path.dirname(self.multiwfn_path)
        if "Multiwfnpath" not in env:
            env["Multiwfnpath"] = mw_dir

        self.log.emit("启动 Multiwfn ...\n")
        self._process = subprocess.Popen(
            [self.multiwfn_path, self.input_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            cwd=self.output_dir, env=env,
        )

        try:
            stdout, stderr = self._process.communicate(input=input_seq, timeout=600)
        except subprocess.TimeoutExpired:
            self.log.emit("\n错误: 运行超时！\n")
            try:
                self._process.kill()
                self._process.communicate(timeout=5)
            except Exception:
                pass
            self.done.emit(False, self.output_dir)
            return

        for line in stdout.splitlines():
            if line.strip():
                self.log.emit(line + "\n")
        if stderr:
            self.log.emit("-" * 40 + "\n[警告/错误]\n")
            for line in stderr.splitlines():
                if line.strip():
                    self.log.emit(line + "\n")

        self.log.emit(f"\n退出代码: {self._process.returncode}\n")
        if self._process.returncode == 0 and self._check_output(self.output_dir):
            self.log.emit("=" * 60 + "\n")
            self.log.emit("AIM 分析完成！\n")
            self.done.emit(True, self.output_dir)
        else:
            self.log.emit("分析异常退出\n")
            self.done.emit(False, self.output_dir)

    def _check_output(self, out_dir):
        mol_name = self.pdb_name if self.pdb_name else "mol.pdb"
        expected = [mol_name, "CPs.pdb", "paths.pdb"]
        all_ok = True
        for fname in expected:
            fp = os.path.join(out_dir, fname)
            if os.path.exists(fp):
                self.log.emit(f"  ✓ {fname}  ({os.path.getsize(fp)} bytes)\n")
            else:
                self.log.emit(f"  ✗ {fname}  (缺失)\n")
                all_ok = False
        return all_ok


# ── 主面板 ────────────────────────────────────────────────────
class AIMPanel(QWidget):
    def __init__(self, glw=None, multiwfn_path="", get_fchk=None,
                 get_multiwfn=None, log_func=None, parent=None,
                 get_vmd=None, get_tachyon=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path
        self.get_fchk = get_fchk or (lambda: "")
        self.get_multiwfn = get_multiwfn or (lambda: "")
        self.get_vmd = get_vmd or (lambda: "")
        self.get_tachyon = get_tachyon or (lambda: "")
        self._log_func = log_func

        self.current_atoms = []
        self.current_cps = []
        self.current_paths = []
        self.cp_props = {}
        self._cps_path = ""
        self._paths_path = ""
        self._mol_pdb_path = ""
        self.worker = None
        self._vmd_port = None
        self._vmd_render_dir = None
        self._queried_serials = set()   # 已点击查询的 CP serial

        self._build_ui()
        self._on_filter_changed()   # 初始画布（空）

        # 输入文件直接用主窗口已载入的 fchk（本面板不再提供输入/输出路径框，
        # 输出目录 = fchk 所在目录，基础名固定 mol.pdb）
        cur = self.get_fchk()
        if cur and not self.current_atoms:
            self._load_molecule(cur)

        if self.glw is not None:
            self.glw.set_aim_pick_callback(self._on_cp_click)

    def showEvent(self, event):
        """切到本 tab 时若画布还没有分子，自动载入主窗口已载入的 fchk。"""
        super().showEvent(event)
        if not self.current_atoms:
            cur = self.get_fchk()
            if cur:
                self._load_molecule(cur)

    # ── i18n ──
    def _t(self, key, **fmt):
        s = _AIM_TR.get(self.lang, {}).get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        """主窗口切换语言时调用（"zh"/"en"）。"""
        if lang not in ("zh", "en"):
            lang = "zh"
        self.lang = lang
        self._apply_lang()

    def _apply_lang(self):
        """刷新常驻控件的可见文本（运行时消息每次构造时走 _t()）。"""
        self.lbl_cp_log.setText(self._t("cp_log"))
        self.chk_show_queried_only.setText(self._t("queried_only"))
        self.btn_export.setText(self._t("export_csv"))
        self.log_label.setText(self._t("run_log"))
        self.grp_run.setTitle(self._t("grp_run"))
        self.btn_run.setText(self._t("run_btn"))
        self.btn_stop.setText(self._t("stop"))
        self.grp_settings.setTitle(self._t("grp_settings"))
        self.chk_large_system.setText(self._t("large"))
        self.lbl_show_cp.setText(self._t("show_cp_types"))
        self.chk_show_3n3.setText(self._t("cp_c"))
        self.chk_show_3n1.setText(self._t("cp_n"))
        self.chk_show_3p1.setText(self._t("cp_o"))
        self.chk_show_3p3.setText(self._t("cp_f"))
        self.lbl_cp_size.setText(self._t("cp_size"))
        self.lbl_path_size.setText(self._t("path_width"))
        self.btn_refresh.setText(self._t("refresh"))
        self.grp_legend.setTitle(self._t("grp_legend"))
        for lbl, key in zip(self._legend_labels,
                            ("cp_c", "cp_n", "cp_o", "cp_f")):
            lbl.setText(self._t(key))
        self.cp_table.setHorizontalHeaderLabels([
            self._t("col_idx"), self._t("col_type"),
            self._t("col_rho"), self._t("col_v")])
        # 未加载分子时状态文本也随语言刷新
        if not self.current_atoms:
            self.lbl_mol_hint.setText(self._t("no_mol"))
        # 三个载入按钮按新语言文字重新定宽（QSS padding 6px 16px）
        for b in (self.btn_load_cps, self.btn_load_paths,
                  self.btn_load_cpprop):
            b.setText(self._t({"btn_load_cps": "load_cps",
                               "btn_load_paths": "load_paths",
                               "btn_load_cpprop": "load_cpprop"}[b.objectName()]))
            b.setFixedWidth(b.fontMetrics().horizontalAdvance(b.text()) + 40)

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._grp_aim_settings())
        root.addWidget(self._grp_run())
        root.addWidget(self._grp_legend())

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

        # CP 查询记录卡片：圆角矩形包裹「标题标签 + 查询表格 + 筛选/导出行」，
        # 表格随窗口高度自适应伸缩（原固定最大高度 200px 改为最小高度并拉伸）。
        card = QFrame()
        card.setObjectName("CpLogCard")
        card.setStyleSheet("""
            QFrame#CpLogCard {
                background-color: #FFFFFF;
                border: 1px solid #D7E1EC;
                border-radius: 10px;
            }
            QLabel#CpLogChip {
                background-color: #1565C0;
                color: #FFFFFF;
                border-radius: 4px;
                padding: 2px 14px;
                font-weight: bold;
                font-size: 9pt;
            }
            QTableWidget#CpTable {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
            }
        """)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(12, 10, 12, 10)
        card_l.setSpacing(8)

        self.lbl_cp_log = QLabel(self._t("cp_log"))
        self.lbl_cp_log.setObjectName("CpLogChip")
        self.lbl_cp_log.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        card_l.addWidget(self.lbl_cp_log, 0, Qt.AlignLeft)

        self.cp_table = self._build_cp_table()
        self.cp_table.setObjectName("CpTable")
        card_l.addWidget(self.cp_table, 1)

        row_csv = QHBoxLayout()
        self.chk_show_queried_only = QCheckBox(self._t("queried_only"))
        self.chk_show_queried_only.toggled.connect(self._on_filter_changed)
        row_csv.addWidget(self.chk_show_queried_only)
        row_csv.addStretch()
        self.btn_export = QPushButton(self._t("export_csv"))
        self.btn_export.setMaximumWidth(110)
        self.btn_export.clicked.connect(self._export_cp_table_csv)
        row_csv.addWidget(self.btn_export)
        card_l.addLayout(row_csv)

        root.addWidget(card, 1)

        # 运行日志默认隐藏（仍保留 log_text 以承接 _append_log 输出）
        self.log_label = QLabel(self._t("run_log"))
        self.log_label.hide()
        root.addWidget(self.log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(140)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        self.log_text.hide()
        root.addWidget(self.log_text, 1)

    def _grp_run(self):
        self.grp_run = QGroupBox(self._t("grp_run"))
        grp = self.grp_run
        l = QVBoxLayout(grp)
        l.setSpacing(6)

        # 运行 + 载入已有结果按钮合并为一行
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_run = QPushButton(self._t("run_btn"))
        self.btn_run.setMinimumWidth(160)
        self.btn_run.clicked.connect(self._start_analysis)
        row.addWidget(self.btn_run)
        self.btn_stop = QPushButton(self._t("stop"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumWidth(90)
        self.btn_stop.clicked.connect(self._stop_analysis)
        row.addWidget(self.btn_stop)

        # 载入已有结果（原「文件设置」组，已并入运行区）
        self.btn_load_cps = QPushButton(self._t("load_cps"))
        self.btn_load_paths = QPushButton(self._t("load_paths"))
        self.btn_load_cpprop = QPushButton(self._t("load_cpprop"))
        self.btn_load_cps.setObjectName("btn_load_cps")
        self.btn_load_paths.setObjectName("btn_load_paths")
        self.btn_load_cpprop.setObjectName("btn_load_cpprop")
        for b in (self.btn_load_cps, self.btn_load_paths, self.btn_load_cpprop):
            # QSS padding 6px 16px：按字体度量定宽，保证文字完整不截断
            b.setFixedWidth(b.fontMetrics().horizontalAdvance(b.text()) + 40)
            row.addWidget(b)
        self.btn_load_cps.clicked.connect(self._browse_cps)
        self.btn_load_paths.clicked.connect(self._browse_paths)
        self.btn_load_cpprop.clicked.connect(self._browse_cpprop)
        row.addStretch()
        l.addLayout(row)

        # 当前分子状态（_load_molecule 会更新文本；按钮行下方小字状态行）
        self.lbl_mol_hint = QLabel(self._t("no_mol"))
        self.lbl_mol_hint.setObjectName("AimMolHint")
        self.lbl_mol_hint.setStyleSheet(
            "QLabel#AimMolHint { color:#7E9AB8; font-size:9pt; }")
        l.addWidget(self.lbl_mol_hint)
        return grp

    def _grp_aim_settings(self):
        self.grp_settings = QGroupBox(self._t("grp_settings"))
        grp = self.grp_settings
        l = QVBoxLayout(grp)
        l.setSpacing(6)

        self.chk_large_system = QCheckBox(self._t("large"))
        l.addWidget(self.chk_large_system)

        disp = QHBoxLayout()
        self.lbl_show_cp = QLabel(self._t("show_cp_types"))
        disp.addWidget(self.lbl_show_cp)
        self.chk_show_3n3 = QCheckBox(self._t("cp_c"))
        self.chk_show_3n1 = QCheckBox(self._t("cp_n"))
        self.chk_show_3p1 = QCheckBox(self._t("cp_o"))
        self.chk_show_3p3 = QCheckBox(self._t("cp_f"))
        for c in (self.chk_show_3n3, self.chk_show_3n1,
                  self.chk_show_3p1, self.chk_show_3p3):
            c.setChecked(True)
            c.toggled.connect(self._on_filter_changed)
            disp.addWidget(c)
        l.addLayout(disp)

        row1 = QHBoxLayout()
        self.lbl_cp_size = QLabel(self._t("cp_size"))
        row1.addWidget(self.lbl_cp_size)
        self.sld_cp_size = QSlider(Qt.Horizontal)
        self.sld_cp_size.setRange(5, 100)            # 0.05 .. 1.00 Å
        self.sld_cp_size.setValue(10)                # 默认 0.10 Å
        self.sld_cp_size.valueChanged.connect(self._on_size_changed)
        self.lbl_cp_size_val = QLabel("0.10")
        self.lbl_cp_size_val.setMinimumWidth(40)
        self.lbl_cp_size_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row1.addWidget(self.sld_cp_size, 1)
        row1.addWidget(self.lbl_cp_size_val)
        l.addLayout(row1)

        row2 = QHBoxLayout()
        self.lbl_path_size = QLabel(self._t("path_width"))
        row2.addWidget(self.lbl_path_size)
        self.sld_path_size = QSlider(Qt.Horizontal)
        self.sld_path_size.setRange(1, 200)          # 0.001 .. 0.200 Å
        self.sld_path_size.setValue(10)              # 默认 0.010 Å
        self.sld_path_size.valueChanged.connect(self._on_size_changed)
        self.lbl_path_size_val = QLabel("0.010")
        self.lbl_path_size_val.setMinimumWidth(40)
        self.lbl_path_size_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row2.addWidget(self.sld_path_size, 1)
        row2.addWidget(self.lbl_path_size_val)
        l.addLayout(row2)

        self.btn_refresh = QPushButton(self._t("refresh"))
        self.btn_refresh.clicked.connect(self._redraw)
        l.addWidget(self.btn_refresh)
        return grp

    def _grp_legend(self):
        self.grp_legend = QGroupBox(self._t("grp_legend"))
        grp = self.grp_legend
        l = QHBoxLayout(grp)
        l.setSpacing(14)
        self._legend_labels = []
        for letter, key in [('C', "cp_c"), ('N', "cp_n"),
                            ('O', "cp_o"), ('F', "cp_f")]:
            sw = QFrame()
            sw.setFixedSize(14, 14)
            rgb = CP_COLOR_RGB[letter]
            sw.setStyleSheet(
                f"background:rgb({int(rgb[0]*255)},{int(rgb[1]*255)},{int(rgb[2]*255)});"
                f"border:1px solid #888;")
            l.addWidget(sw)
            lbl = QLabel(self._t(key))
            self._legend_labels.append(lbl)
            l.addWidget(lbl)
        l.addStretch()
        self.lbl_cp_count = QLabel("CP: 0")
        l.addWidget(self.lbl_cp_count)
        return grp

    def _build_cp_table(self):
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels([self._t("col_idx"), self._t("col_type"),
                                     self._t("col_rho"), self._t("col_v")])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setMinimumHeight(200)   # 原为 setMaximumHeight(200)：改为最小高度，随卡片/窗口自适应拉伸
        return t

    # ── 日志 ──
    def _append_log(self, msg):
        if self._log_func:
            try:
                self._log_func(msg)
            except Exception:
                pass
        self.log_text.moveCursor(QTextCursor.End)
        self.log_text.insertPlainText(msg if msg.endswith("\n") else msg + "\n")
        self.log_text.moveCursor(QTextCursor.End)

    # ── 浏览 ──
    def _browse_cps(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("dlg_cps"), "", "PDB 文件 (*.pdb);;所有文件 (*.*)")
        if path:
            self._load_cps(path)

    def _browse_paths(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("dlg_paths"), "", "PDB 文件 (*.pdb);;所有文件 (*.*)")
        if path:
            self._load_paths(path)

    def _browse_cpprop(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("dlg_cpprop"), "", "文本文件 (*.txt);;所有文件 (*.*)")
        if path:
            self._load_cpprop(path)

    # ── 分子加载 ──
    def _load_molecule(self, path):
        if not path or not os.path.isfile(path):
            return
        try:
            atoms = get_atoms_auto(path)
            if not atoms:
                self.lbl_mol_hint.setText(self._t("no_atoms"))
                return
            self.current_atoms = atoms
            self._append_log(self._t(
                "loaded_mol", name=os.path.basename(path), n=len(atoms)))
            self.lbl_mol_hint.setText(self._t(
                "atoms_n", n=len(atoms), name=os.path.basename(path)))
            self._redraw()
        except Exception as e:
            self._append_log(self._t(
                "parsed_err", e=e, tb=traceback.format_exc()))

    # ── CP / Path 加载 ──
    def _load_cps(self, path):
        cps = get_cps_from_pdb(path)
        if not cps:
            QMessageBox.warning(self, self._t("warn"), self._t("cps_fail"))
            return
        self._cps_path = path
        self.current_cps = cps
        self.lbl_cp_count.setText(f"CP: {len(cps)}")
        counts = {}
        for _, ct, _ in cps:
            counts[ct] = counts.get(ct, 0) + 1
        self._append_log(self._t(
            "loaded_cps", name=os.path.basename(path), n=len(cps)))
        for ct, n in sorted(counts.items()):
            self._append_log(f"  {CP_NAMES.get(ct, ct)}: {n}\n")
        self._redraw()

    def _load_paths(self, path):
        paths = get_paths_from_pdb(path)
        if not paths:
            QMessageBox.warning(self, self._t("warn"), self._t("paths_fail"))
            return
        self._paths_path = path
        self.current_paths = paths
        n_pts = sum(len(p["pts"]) for p in paths)
        self._append_log(self._t(
            "loaded_paths", name=os.path.basename(path),
            np=len(paths), npts=n_pts))
        self._redraw()

    def _load_cpprop(self, path):
        props = parse_cpprop_txt(path)
        if not props:
            QMessageBox.warning(self, self._t("warn"), self._t("cpprop_fail"))
            return
        self.cp_props = props
        self._append_log(self._t(
            "loaded_cpprop", name=os.path.basename(path), n=len(props)))
        self._append_log(self._t("cpprop_tip"))

    # ── 可视化（接入左侧 OpenGL 画布）──
    def clear_canvas(self):
        """清空画布上的 AIM 覆盖层并取消类型显示勾选（保留已加载数据）。
        由主窗口「清空样式」联动调用；勾选框 blockSignals 防止触发重绘。"""
        if self.glw is not None:
            self.glw.clear_aim_overlay()
        for chk in (getattr(self, "chk_show_3n3", None),
                    getattr(self, "chk_show_3n1", None),
                    getattr(self, "chk_show_3p1", None),
                    getattr(self, "chk_show_3p3", None)):
            if chk is not None:
                try:
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)
                except Exception:
                    pass

    def _redraw(self):
        if self.glw is None:
            return
        try:
            self._draw_to_glw()
        except Exception as e:
            self._append_log(self._t(
                "draw_err", e=e, tb=traceback.format_exc()))

    def _draw_to_glw(self):
        glw = self.glw
        # 1) 分子（glw.set_molecule 期望 [(idx,sym,anum,(x,y,z))] Å，自动生成键）
        if self.current_atoms:
            glw.set_molecule(self.current_atoms)
            try:
                glw.frame_to_molecule()
            except Exception:
                pass

        # 2) 临界点（按类型着色，可拾取）+ 梯度路径点云（灰色）
        queried_only = self.chk_show_queried_only.isChecked()
        cps_pts = []
        for serial, ct, (x, y, z) in self.current_cps:
            if not self._cp_visible(ct):
                continue
            if queried_only and serial not in self._queried_serials:
                continue
            cps_pts.append((x, y, z, CP_COLOR_RGB.get(ct, (1.0, 0.5, 0.0)),
                            serial, ct))

        # 键径：仅显示已查询 CP 时，只保留与已查询 (3,-1) BCP 关联的键径
        path_resids = self._queried_path_resids() if queried_only else None
        path_pts = []
        for p in self.current_paths:
            if queried_only and p["resid"] not in path_resids:
                continue
            path_pts.extend(p["pts"])

        glw.set_aim_overlay(
            cps_pts, path_pts,
            cp_radius=self._cp_size(),
            path_radius=self._path_size())

    def _cp_visible(self, ct):
        return {
            'C': self.chk_show_3n3.isChecked(),
            'N': self.chk_show_3n1.isChecked(),
            'O': self.chk_show_3p1.isChecked(),
            'F': self.chk_show_3p3.isChecked(),
        }.get(ct, True)

    def _queried_path_resids(self):
        """返回与已查询 (3,-1) BCP 关联的键径 resid 集合。

        键临界点（BCP）位于键径上，因此若某条键径存在一点距已查询 BCP
        小于 0.5 Å，即认为该键径与该 BCP 相关（对齐 sob/aim_visualize 判定）。
        """
        bcp_coords = {}
        for serial, ct, (x, y, z) in self.current_cps:
            if ct == 'N' and serial in self._queried_serials:
                bcp_coords[serial] = (x, y, z)
        if not bcp_coords:
            return set()
        resids = set()
        cp2 = 0.5 * 0.5
        for p in self.current_paths:
            for (px, py, pz) in p["pts"]:
                hit = False
                for (cx, cy, cz) in bcp_coords.values():
                    if (px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2 < cp2:
                        resids.add(p["resid"])
                        hit = True
                        break
                if hit:
                    break
        return resids

    def _cp_size(self):
        return self.sld_cp_size.value() / 100.0

    def _path_size(self):
        return self.sld_path_size.value() / 1000.0

    def _on_filter_changed(self, *_):
        self._redraw()

    def _on_size_changed(self, *_):
        self.lbl_cp_size_val.setText(f"{self._cp_size():.2f}")
        self.lbl_path_size_val.setText(f"{self._path_size():.3f}")
        self._redraw()

    # ── 运行 ──
    def _resolve_input(self):
        """输入文件 = 主窗口已载入的 fchk（.wfn 亦兼容，按扩展名自动识别）。"""
        return self.get_fchk()

    def _start_analysis(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, self._t("hint"), self._t("running"))
            return

        multiwfn = self.get_multiwfn() or self.multiwfn_path
        if not multiwfn or not os.path.exists(multiwfn):
            QMessageBox.warning(self, self._t("error"), self._t("need_mw"))
            return
        input_path = self._resolve_input()
        if not input_path or not os.path.exists(input_path):
            QMessageBox.warning(self, self._t("error"), self._t("need_input"))
            return
        # 确保分子已画入画布（分析后 CP/path 才能叠在分子结构上）
        if not self.current_atoms:
            self._load_molecule(input_path)
        # 输出归档目录 = <输入文件目录>/<输入名>_AIM（同 ESP 的 <stem>_ESP 惯例），
        # Multiwfn 产物 mol.pdb / CPs.pdb / paths.pdb / CPprop.txt 等统一归档，不散在输入目录
        base_dir = os.path.dirname(os.path.abspath(input_path))
        stem = os.path.splitext(os.path.basename(input_path))[0] or "mol"
        output_dir = os.path.join(base_dir, f"{stem}_AIM")
        os.makedirs(output_dir, exist_ok=True)
        pdb_name = "mol.pdb"

        self.worker = AIMWorker(input_path, output_dir, multiwfn, pdb_name,
                                self.chk_large_system.isChecked(), self)
        self.worker.log.connect(self._append_log)
        self.worker.done.connect(self._on_analysis_done)
        self.worker.start()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.show()

    def _stop_analysis(self):
        if self.worker is not None:
            self.worker.stop()
        self.btn_stop.setEnabled(False)

    def shutdown(self):
        """主窗口关闭时调用：终止运行中的 AIM 分析线程（避免 QThread
        销毁时仍在运行导致 Qt 致命崩溃）。"""
        w = getattr(self, "worker", None)
        if w is not None and w.isRunning():
            try:
                w.terminate()
                w.wait(3000)
            except Exception:
                pass
            self.worker = None

    def _on_analysis_done(self, ok, output_dir):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.hide()
        if ok:
            self._append_log(self._t("done_auto"))
            cps = os.path.join(output_dir, "CPs.pdb")
            paths = os.path.join(output_dir, "paths.pdb")
            mol = os.path.join(output_dir, "mol.pdb")
            if os.path.exists(cps):
                self._load_cps(cps)
            if os.path.exists(paths):
                self._load_paths(paths)
            if os.path.exists(mol):
                self._mol_pdb_path = mol
            # CPprop.txt（若存在则一并载入）
            for cand in ("CPprop.txt", "CPprop_1.txt"):
                fp = os.path.join(output_dir, cand)
                if os.path.exists(fp):
                    self._load_cpprop(fp)
                    break
        else:
            self._append_log(self._t("done_none"))

    # ── VMD 渲染 ──
    def _ensure_vmd_files(self):
        cps = self._cps_path
        paths = self._paths_path
        mol = self._mol_pdb_path
        if not cps:
            QMessageBox.warning(self, self._t("hint"), self._t("need_cps"))
            return None
        if not paths:
            cand = os.path.join(os.path.dirname(cps), "paths.pdb")
            if os.path.exists(cand):
                paths = cand
                self._paths_path = cand
            else:
                QMessageBox.warning(self, self._t("hint"), self._t("need_paths"))
                return None
        if not mol:
            cand = os.path.join(os.path.dirname(cps), "mol.pdb")
            if os.path.exists(cand):
                mol = cand
                self._mol_pdb_path = cand
            else:
                QMessageBox.warning(self, self._t("hint"), self._t("need_mol"))
                return None
        return cps, paths, mol

    def _resolve_vmd_exe(self):
        vmd = self.get_vmd() or ""
        if vmd and os.path.exists(vmd):
            return vmd
        if aim_visualize is not None and os.path.exists(aim_visualize.DEFAULT_VMD):
            return aim_visualize.DEFAULT_VMD
        return None

    def _filtered_cps_pdb(self, cps_path):
        """生成仅含已查询 serial 的临时 CPs.pdb，返回其路径。"""
        kept = self._queried_serials
        out = os.path.join(tempfile.mkdtemp(prefix="aim_cps_"),
                           "CPs_queried.pdb")
        try:
            with open(cps_path, "r", encoding="utf-8", errors="ignore") as fin, \
                 open(out, "w", encoding="utf-8") as fout:
                for line in fin:
                    if line.startswith(("ATOM", "HETATM")):
                        try:
                            serial = int(line[6:11].strip())
                        except ValueError:
                            serial = -1
                        if serial not in kept:
                            continue
                    fout.write(line)
        except Exception:
            return cps_path
        return out

    def _filtered_paths_pdb(self, paths_path):
        """生成仅含与已查询 BCP 相关键径的临时 paths.pdb，返回其路径。"""
        resids = self._queried_path_resids()
        out = os.path.join(tempfile.mkdtemp(prefix="aim_paths_"),
                           "paths_queried.pdb")
        try:
            with open(paths_path, "r", encoding="utf-8", errors="ignore") as fin, \
                 open(out, "w", encoding="utf-8") as fout:
                for line in fin:
                    if line.startswith(("ATOM", "HETATM")):
                        try:
                            resid = int(line[22:26].strip())
                        except ValueError:
                            resid = -1
                        if resid not in resids:
                            continue
                    fout.write(line)
        except Exception:
            return paths_path
        return out

    def _vmd_preview(self, style=None):
        """在 VMD 中预览 AIM 场景。style 由 VMD 控制台传入，缺省用 sob-art。"""
        if aim_visualize is None:
            QMessageBox.warning(self, self._t("error"), self._t("no_aimviz"))
            return
        files = self._ensure_vmd_files()
        if not files:
            return
        cps, paths, mol = files
        vmd_exe = self._resolve_vmd_exe()
        if not vmd_exe:
            QMessageBox.warning(self, self._t("error"), self._t("need_vmd"))
            return
        style = style or "sob-art"
        try:
            # 「仅显示已查询的 CP」→ 只显示已查询 CP 及其相关键径
            cps_used = cps
            paths_used = paths
            if self.chk_show_queried_only.isChecked() and self._queried_serials:
                cps_used = self._filtered_cps_pdb(cps)
                paths_used = self._filtered_paths_pdb(paths)
            port, render_dir, _ = aim_visualize.preview_aim(
                cps_used, paths_used, mol,
                cp_size=self._cp_size(),
                path_size=self._path_size(),
                show_3n3=self.chk_show_3n3.isChecked(),
                show_3n1=self.chk_show_3n1.isChecked(),
                show_3p1=self.chk_show_3p1.isChecked(),
                show_3p3=self.chk_show_3p3.isChecked(),
                style_name=style, vmd_exe=vmd_exe)
            self._vmd_port = port
            self._vmd_render_dir = render_dir
            self._append_log(self._t("vmd_previewed", port=port))
        except Exception as e:
            self._append_log(self._t(
                "vmd_fail", e=e, tb=traceback.format_exc()))

    def _vmd_render(self, style=None):
        """渲染当前 AIM 视角为 PNG。style 由 VMD 控制台传入，缺省用 sob-art。"""
        if aim_visualize is None:
            QMessageBox.warning(self, self._t("error"), self._t("no_aimviz"))
            return
        if not self._vmd_port:
            QMessageBox.warning(self, self._t("hint"), self._t("need_preview"))
            return
        tachyon = self.get_tachyon() or ""
        if not tachyon or not os.path.exists(tachyon):
            if aim_visualize is not None:
                tachyon = aim_visualize.DEFAULT_TACHYON
        style = style or "sob-art"
        try:
            png, msg = aim_visualize.render_current_view(
                self._vmd_port, self._vmd_render_dir,
                tachyon_exe=tachyon, style_name=style)
            if png:
                self._append_log(self._t("rendered", png=png))
            else:
                self._append_log(self._t("render_fail", msg=msg))
        except Exception as e:
            self._append_log(self._t(
                "render_fail_e", e=e, tb=traceback.format_exc()))

    # ── CP 属性查询 ──
    def _on_cp_click(self, serial, cp_type):
        self._queried_serials.add(int(serial))
        if not self.cp_props:
            self._append_log("请先加载 CPprop.txt 文件查看 CP 属性\n")
            if self.chk_show_queried_only.isChecked():
                self._redraw()
            return
        if serial not in self.cp_props:
            self._append_log(self._t(
                "cp_not_found", serial=serial, cp_type=cp_type))
            if self.chk_show_queried_only.isChecked():
                self._redraw()
            return
        props = self.cp_props[serial]
        type_name = CP_NAMES.get(cp_type, cp_type)
        self._add_cp_to_table(serial, cp_type, props)
        if self.chk_show_queried_only.isChecked():
            self._redraw()

        def _fmt(v):
            if isinstance(v, float):
                if abs(v) < 1e-4 and v != 0.0:
                    return f"{v:>20.6e}"
                return f"{v:>20.8f}"
            return f"{str(v):>20}"

        def _row(label, value, indent="  "):
            return f"{indent}{label:<34}{_fmt(value)}\n"

        log = []
        log.append(f"\n{'=' * 62}\n")
        w = 62 - 2
        title = f"  CP #{serial}  —  {type_name}"
        log.append(f"{title:^{w}}\n")
        log.append(f"{'=' * 62}\n")

        log.append("  ◆ 基本信息\n")
        log.append(f"  {'─' * 56}\n")
        for en, cn in [("Connected atoms", "连接原子"),
                       ("Position (Angstrom)", "坐标 (Å)")]:
            if en in props:
                log.append(_row(cn, props[en]))
        log.append("\n")

        log.append("  ◆ 拓扑指标\n")
        log.append(f"  {'─' * 56}\n")
        topo_keys = [
            ("Density of all electrons", "电子密度 ρ(r)"),
            ("Laplacian of electron density", "拉普拉斯 ∇²ρ"),
            ("Potential energy density V(r)", "势能密度 V(r)"),
            ("Lagrangian kinetic energy G(r)", "拉格朗日动能 G(r)"),
            ("Hamiltonian kinetic energy K(r)", "哈密顿动能 K(r)"),
            ("Energy density E(r) or H(r)", "能量密度 H(r)"),
            ("Ellipticity of electron density", "椭圆度 ε"),
            ("eta index", "η 指标"),
        ]
        for en, cn in topo_keys:
            if en in props:
                log.append(_row(cn, props[en]))
        log.append("\n")

        elec_keys = [
            ("Electron localization function (ELF)", "ELF"),
            ("Localized orbital locator (LOL)", "LOL"),
            ("Local information entropy", "局部信息熵"),
            ("Interaction region indicator (IRI)", "IRI"),
            ("Reduced density gradient (RDG)", "RDG"),
            ("Sign(lambda2)*rho", "sign(λ₂)ρ"),
            ("Average local ionization energy (ALIE)", "ALIE"),
        ]
        if any(en in props for en, _ in elec_keys):
            log.append("  ◆ 电子结构\n")
            log.append(f"  {'─' * 56}\n")
            for en, cn in elec_keys:
                if en in props:
                    log.append(_row(cn, props[en]))
            log.append("\n")

        eig_str = self._extract_eigenvalues(props)
        if eig_str:
            log.append("  ◆ Hessian 矩阵 (电子密度)\n")
            log.append(f"  {'─' * 56}\n")
            log.append(f"{eig_str}")

        displayed = set()
        for grp in (topo_keys, elec_keys):
            for en, _ in grp:
                displayed.add(en)
        displayed.update(["CP_type", "Connected atoms", "Position (Angstrom)",
                          "Position (Bohr)", "Density of Alpha electrons",
                          "Density of Beta electrons", "Spin density of electrons",
                          "Eigenvalues of Hessian", "Determinant of Hessian",
                          "Stiffness", "Eigenvectors"])
        remaining = {k: v for k, v in props.items() if k not in displayed}
        if remaining:
            log.append("  ◆ 其他属性\n")
            log.append(f"  {'─' * 56}\n")
            for k in sorted(remaining.keys()):
                log.append(_row(k, remaining[k]))

        log.append(f"{'=' * 62}\n\n")
        for line in log:
            self._append_log(line)

    @staticmethod
    def _extract_eigenvalues(props):
        lines = []
        eig_str = props.get("Eigenvalues of Hessian", "")
        if not eig_str:
            return ""
        parts = str(eig_str).split()
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            return ""
        if len(vals) < 3:
            return ""
        det = props.get("Determinant of Hessian", None)
        stiff = props.get("Stiffness", None)
        lines.append(f"  特征值 λ₁: {vals[0]:>20.8f}\n")
        lines.append(f"  特征值 λ₂: {vals[1]:>20.8f}\n")
        lines.append(f"  特征值 λ₃: {vals[2]:>20.8f}\n")
        if det is not None:
            lines.append(f"  行列式    : {det:>20.8f}\n")
        if stiff is not None:
            lines.append(f"  刚度      : {stiff:>20.8f}\n")
        return "".join(lines)

    def _add_cp_to_table(self, serial, cp_type, props):
        row = self.cp_table.rowCount()
        self.cp_table.insertRow(row)
        self.cp_table.setItem(row, 0, QTableWidgetItem(str(serial)))
        self.cp_table.setItem(row, 1,
                              QTableWidgetItem(CP_NAMES.get(cp_type, cp_type)))
        rho = props.get("Density of all electrons", "")
        v = props.get("Potential energy density V(r)", "")
        self.cp_table.setItem(row, 2, QTableWidgetItem(str(rho)))
        self.cp_table.setItem(row, 3, QTableWidgetItem(str(v)))
        self.cp_table.scrollToBottom()

    def _export_cp_table_csv(self):
        if self.cp_table.rowCount() == 0:
            QMessageBox.warning(self, self._t("hint"), self._t("tbl_empty"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("dlg_save_csv"), "cp_query.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([self._t("col_idx"), self._t("col_type"),
                                 self._t("col_rho"), self._t("col_v")])
                for r in range(self.cp_table.rowCount()):
                    row = []
                    for c in range(self.cp_table.columnCount()):
                        item = self.cp_table.item(r, c)
                        row.append(item.text() if item else "")
                    writer.writerow(row)
            self._append_log(self._t("exported", path=path))
        except Exception as e:
            QMessageBox.warning(self, self._t("export_fail"), str(e))
