# -*- coding: utf-8 -*-
"""
MPP 分子平面性参数分析面板（GXNU MolStudio 的一个 tab）。

移植自 mpp_auto_qt.py（广西师范大学侯成课题组）：
  - 输入：fchk / log / out / wfn / pdb / xyz 分子文件
    （主窗口已载入的 fchk 自动取用；也可浏览其它格式。
     Gaussian .log/.out 解析几何后临时转 xyz 交给 Multiwfn，因 Multiwfn 不能直接读 log）
  - 原子选择：点击左侧 OpenGL 画布选原子，或直接输入编号范围（如 9-10,13-30）
  - 计算：调用 Multiwfn 的 MPP 子程序（命令序列 MPP → 原子选择 → y → 退出），
    解析输出中的 MPP（分子平面性参数）与 SDP（平面偏离跨度），单位 Å，
    并生成 .pqr 文件（其 charge 列存放各原子到拟合平面的带符号偏离距离）
  - 可视化：分子/选中集显示在左侧 OpenGL 画布——选中原子按偏离平面的
    距离着色（BWR，±0.5 Å：平面下蓝、平面上红、在平面内白）；
    VMD 同样按该偏离值着色，控制台/渲染出图照常可用

依赖：Multiwfn / VMD / Tachyon 路径全部走主窗口 ⚙️ 路径设置。
"""

import os
import re
import subprocess
import tempfile
import traceback

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QFileDialog, QMessageBox, QFrame, QLineEdit, QSizePolicy,
    QProgressBar,
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

try:
    from molcanvas import get_atoms_from_fchk, ELEMENT_SYMBOLS
except Exception:  # pragma: no cover
    get_atoms_from_fchk = None
    ELEMENT_SYMBOLS = {}

try:
    from etsnocv.molcanvas import parse_log_file as _parse_gaussian_log
    from etsnocv.molcanvas import parse_xyz_file as _parse_xyz
except Exception:  # pragma: no cover
    _parse_gaussian_log = None
    _parse_xyz = None

BOHR_TO_ANGSTROM = 0.52917720859

# VMD/画布偏离值着色范围（Å，对齐原工具 mpp_auto_qt.py 的默认 ±0.5）
DEFAULT_PQR_RANGE = (-0.5, 0.5)

# ── i18n ──
_MPP_TR = {
    "zh": {
        "grp_files": "文件设置",
        "browse": "浏览...",
        "use_main": "载入主窗口文件",
        "main_hint": "优先使用主窗口已载入的 fchk/log",
        "mol_status": "{n} 原子 | {name}",
        "no_mol": "尚未加载分子（载入主窗口文件或浏览选择）",
        "grp_sel": "原子选择",
        "sel_hint": "点击左侧画布原子选择；或直接输入编号范围（如 9-10,13-30）",
        "sel_placeholder": "如 9-10,13-30",
        "apply_sel": "应用选择",
        "select_all": "全选",
        "clear_sel": "清除",
        "sel_current": "当前选择: {sel}",
        "sel_empty": "（未选择）",
        "grp_run": "运行",
        "run_btn": "◆  运行 MPP 分析",
        "stop": "■  停止",
        "run_hint": "计算分子平面性参数（MPP）与平面偏离跨度（SDP），并生成 .pqr 偏离文件",
        "card_title": "MPP 结果",
        "mpp_cap": "MPP 分子平面性参数",
        "sdp_cap": "SDP 平面偏离跨度",
        "unit_ang": "Å",
        "pqr_lbl": "偏离文件: ",
        "no_pqr": "（未生成）",
        "vmd_preview": "VMD 预览（偏离着色）",
        "no_file": "请先选择分子文件（载入主窗口文件或浏览选择）",
        "no_sel": "请先选择原子：输入编号范围（如 9-10,13-30）或点击画布原子",
        "no_multiwfn": "Multiwfn 路径未设置，请在 ⚙️ 路径设置中配置",
        "parse_fail": "解析分子失败: {err}",
        "unsupported": "不支持的文件类型: {ext}",
        "running": "MPP 分析进行中...",
        "done": "MPP 分析完成：MPP = {mpp} Å，SDP = {sdp} Å",
        "done_nopqr": "MPP 分析完成，但未找到 .pqr 偏离文件",
        "run_fail": "MPP 分析失败: {err}",
        "load_ok": "已载入分子: {name}（{n} 原子，{nsel} 已选）",
        "vmd_registered": "偏离场景已登记（BWR，±0.5 Å）",
        "vmd_no_cb": "VMD 控制台由主窗口提供（左侧画布「同步到VMD」）",
    },
    "en": {
        "grp_files": "Files",
        "browse": "Browse...",
        "use_main": "Load main-window file",
        "main_hint": "Prefer the .fchk/.log loaded in the main window",
        "mol_status": "{n} atoms | {name}",
        "no_mol": "No molecule loaded (load the main-window file or browse)",
        "grp_sel": "Atom Selection",
        "sel_hint": "Click atoms on the left canvas, or type index ranges (e.g. 9-10,13-30)",
        "sel_placeholder": "e.g. 9-10,13-30",
        "apply_sel": "Apply",
        "select_all": "Select All",
        "clear_sel": "Clear",
        "sel_current": "Selected: {sel}",
        "sel_empty": "(none)",
        "grp_run": "Run",
        "run_btn": "◆  Run MPP Analysis",
        "stop": "■  Stop",
        "run_hint": "Compute MPP (molecular planarity) and SDP (span of deviation), producing a .pqr deviation file",
        "card_title": "MPP Results",
        "mpp_cap": "MPP",
        "sdp_cap": "SDP",
        "unit_ang": "Å",
        "pqr_lbl": "Charge file: ",
        "no_pqr": "(not generated)",
        "vmd_preview": "VMD Preview (deviation-colored)",
        "no_file": "Select a molecule file first (load the main-window file or browse)",
        "no_sel": "Select atoms first: type index ranges (e.g. 9-10,13-30) or click canvas atoms",
        "no_multiwfn": "Multiwfn path not set — configure it in ⚙️ Path Settings",
        "parse_fail": "Failed to parse molecule: {err}",
        "unsupported": "Unsupported file type: {ext}",
        "running": "MPP analysis running...",
        "done": "MPP analysis done: MPP = {mpp} Å, SDP = {sdp} Å",
        "done_nopqr": "MPP analysis done, but no .pqr deviation file was found",
        "run_fail": "MPP analysis failed: {err}",
        "load_ok": "Loaded molecule: {name} ({n} atoms, {nsel} selected)",
        "vmd_registered": "Deviation scene registered (BWR, ±0.5 Å)",
        "vmd_no_cb": "The VMD console is provided by the main window (canvas 'Sync to VMD')",
    },
}


# ── 分子解析 ─────────────────────────────────────────

def _get_atoms_from_wfn(wfn_path):
    """解析 wfn 文件的原子（坐标 Bohr → Å）。"""
    atoms = []
    try:
        with open(wfn_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        atom_section = False
        for line in lines:
            line = line.strip()
            if line.startswith("CENTRE ASSIGNMENTS"):
                atom_section = True
                continue
            if atom_section:
                if not line or line.startswith("CENTRE"):
                    continue
                if line.startswith("MO"):
                    break
                parts = line.split()
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


def _get_atoms_from_pdb(pdb_path):
    """解析 pdb 文件的原子（坐标 Å）。"""
    atoms = []
    try:
        with open(pdb_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("ATOM") or line.startswith("HETATM"):
                    try:
                        serial = int(line[6:11].strip())
                        sym = line[76:78].strip()
                        if not sym:
                            name = line[12:16].strip()
                            sym = re.sub(r"\d+", "", name)
                            if len(sym) > 1:
                                sym = sym[0] + sym[1].lower()
                        if not sym:
                            sym = "C"
                        x = float(line[30:38].strip())
                        y = float(line[38:46].strip())
                        z = float(line[46:54].strip())
                        an = 0
                        for _an, _sym in ELEMENT_SYMBOLS.items():
                            if _sym == sym:
                                an = _an
                                break
                        if not an:
                            an = 6
                        atoms.append((serial, sym, an, (x, y, z)))
                    except (ValueError, IndexError):
                        continue
    except Exception:
        pass
    return atoms


def load_atoms_any(filepath):
    """按扩展名解析原子坐标，返回 [(idx, sym, an, (x,y,z))]（坐标 Å）。"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".fchk" and get_atoms_from_fchk:
        return get_atoms_from_fchk(filepath)
    if ext in (".log", ".out") and _parse_gaussian_log:
        return _parse_gaussian_log(filepath)
    if ext == ".xyz" and _parse_xyz:
        return _parse_xyz(filepath)
    if ext == ".wfn":
        return _get_atoms_from_wfn(filepath)
    if ext == ".pdb":
        return _get_atoms_from_pdb(filepath)
    # 兜底：逐个尝试
    for fn in (get_atoms_from_fchk, _parse_gaussian_log, _parse_xyz,
               _get_atoms_from_wfn, _get_atoms_from_pdb):
        if fn is None:
            continue
        try:
            atoms = fn(filepath)
            if atoms:
                return atoms
        except Exception:
            continue
    return []


def _atoms_to_xyz_text(atoms):
    """把原子列表写成 xyz 文本（供 Multiwfn 加载 log 解析出的几何）。"""
    lines = [str(len(atoms)), "MPP temp geometry"]
    for _i, sym, _an, (x, y, z) in atoms:
        lines.append("%-3s %15.8f %15.8f %15.8f" % (sym, x, y, z))
    return "\n".join(lines) + "\n"


# ── Multiwfn MPP 计算（移植自 mpp_auto_qt.py） ─────────

def run_multiwfn_mpp(multiwfn_exe, input_file, atom_selection,
                     pqr_output_path=None, timeout=300):
    """调用 Multiwfn 运行 MPP 子程序，返回 {mpp, sdp, pqr_path, stdout}。"""
    input_abs = os.path.abspath(input_file)
    input_dir = os.path.dirname(input_abs) or "."
    if not pqr_output_path:
        base = os.path.splitext(os.path.basename(input_file))[0]
        pqr_output_path = os.path.join(input_dir, base + ".pqr")
    pqr_out = os.path.abspath(pqr_output_path)

    cmds = ["MPP", atom_selection, "y", "", "q"]
    cmd_input = "\n".join(cmds) + "\n"

    multiwfn_dir = os.path.dirname(os.path.abspath(multiwfn_exe)) or "."
    env = os.environ.copy()
    env["Multiwfnpath"] = multiwfn_dir

    script_file = os.path.join(input_dir, "mpp_input.txt")
    try:
        with open(script_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(cmd_input)
    except OSError:
        script_file = os.path.join(tempfile.gettempdir(), "mpp_input.txt")
        with open(script_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(cmd_input)

    stdout_text = ""
    stderr_text = ""
    try:
        proc = subprocess.Popen(
            [multiwfn_exe, input_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            cwd=input_dir,
            env=env,
        )
        stdout_text, stderr_text = proc.communicate(input=cmd_input, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_text, stderr_text = proc.communicate()
        stderr_text += "\n[错误] Multiwfn 运行超时"
    except Exception as e:
        return {"error": str(e)}

    combined_text = stdout_text + "\n" + stderr_text
    result = _parse_mpp_output(combined_text)
    result["stdout"] = stdout_text
    result["stderr"] = stderr_text

    if os.path.exists(pqr_out):
        result["pqr_path"] = pqr_out
    else:
        base_input = os.path.splitext(os.path.basename(input_file))[0]
        for cand in (os.path.join(input_dir, base_input + ".pqr"),
                     os.path.join(input_dir, base_input + "_mpp.pqr")):
            if os.path.exists(cand):
                result["pqr_path"] = cand
                break
        else:
            result["pqr_path"] = ""
    return result


def _parse_mpp_output(text):
    """从 Multiwfn 输出中提取 MPP 与 SDP 数值。"""
    result = {"mpp": None, "sdp": None}
    m1 = re.search(
        r"Molecular planarity parameter\s*\(MPP\)\s*is\s*([\d.]+)\s*Angstrom",
        text, re.IGNORECASE)
    m2 = re.search(
        r"Span of deviation from plane\s*\(SDP\)\s*is\s*([\d.]+)\s*Angstrom",
        text, re.IGNORECASE)
    if m1:
        result["mpp"] = float(m1.group(1))
    if m2:
        result["sdp"] = float(m2.group(1))
    return result


def _format_atom_selection(indices):
    """把 1-based 原子序号列表压缩成范围串，如 [9,10,13..30] → "9-10,13-30"。"""
    if not indices:
        return ""
    atoms = sorted(set(int(i) for i in indices))
    ranges = []
    start = end = atoms[0]
    for i in range(1, len(atoms)):
        if atoms[i] == end + 1:
            end = atoms[i]
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = atoms[i]
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(ranges)


def parse_pqr_deviations(pqr_path):
    """解析 Multiwfn MPP 输出的 PQR 文件，返回 {1-based 序号: 偏离值(Å)}。

    Multiwfn MPP 的 PQR 行格式（charge 列装的是原子到最佳拟合平面的
    带符号偏离距离，Å）：
        HETATM serial name resName chain resSeq  x  y  z  偏离  半径  元素
    兼容标准 PQR（无末尾元素列）：… x y z charge radius
    """
    def _is_num(s):
        try:
            float(s)
            return True
        except (TypeError, ValueError):
            return False

    deviations = {}
    with open(pqr_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                serial = int(parts[1])
            except ValueError:
                continue
            # 末尾有元素列（Multiwfn MPP）→ 偏离 = parts[-3]；
            # 标准 PQR（末尾两列都是数字）→ 偏离 = parts[-2]
            if _is_num(parts[-1]):
                val_tok = parts[-2]
            else:
                val_tok = parts[-3]
            try:
                deviations[serial] = float(val_tok)
            except ValueError:
                continue
    return deviations


def _bwr_rgb(t):
    """BWR（蓝-白-红）色标映射：t∈[0,1] → (r,g,b)，分量 0..1。"""
    t = max(0.0, min(1.0, float(t)))
    if t <= 0.5:
        return (2.0 * t, 2.0 * t, 1.0)
    return (1.0, 2.0 - 2.0 * t, 2.0 - 2.0 * t)


# ── 后台工作线程 ─────────────────────────────────────

class MppWorker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, multiwfn_exe, input_file, atom_selection, parent=None):
        super().__init__(parent)
        self._exe = multiwfn_exe
        self._input = input_file
        self._sel = atom_selection

    def run(self):
        try:
            result = run_multiwfn_mpp(self._exe, self._input, self._sel)
            self.done.emit(result)
        except Exception as e:
            self.done.emit({"error": str(e), "traceback": traceback.format_exc()})


# ── 面板 ─────────────────────────────────────────────

class MPPPanel(QWidget):
    """MPP 分子平面性参数分析面板（MolStudio 的一个 tab）。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None, parent=None,
                 get_multiwfn=None, on_sync_vmd=None, on_vmd_refresh=None,
                 on_set_mol_style=None, log_func=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path or ""
        self._get_fchk = get_fchk or (lambda: "")
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        # VMD 回调：on_sync_vmd = 打开控制台并同步/启动 VMD；
        # on_vmd_refresh = 仅当 VMD 已连接时推送更新
        self._on_sync_vmd = on_sync_vmd
        self._on_vmd_refresh = on_vmd_refresh
        # 原子配色回调（主窗口注入：切到「单色白」，可视化 tab 可见可改）
        self._on_set_mol_style = on_set_mol_style
        self._log_func = log_func

        self._input_path = ""
        self._atoms = []          # [(idx, sym, an, (x,y,z))] Å
        self._sel_indices = set() # 1-based 已选原子
        self._pqr_path = ""
        self._deviations = {}        # {1-based 序号: 偏离值(Å)}，来自 MPP 生成的 .pqr
        self._mpp = None
        self._sdp = None
        self._worker = None

        self._build_ui()
        self._apply_lang()

        if self.glw is not None:
            try:
                self.glw.add_atom_pick_callback(self._on_atom_pick)
            except Exception:
                pass
        # 主窗口已载入文件 → 自动取用
        QTimer.singleShot(0, self._try_use_main_file)

    # ── i18n ──
    def _t(self, key, **fmt):
        s = _MPP_TR.get(self.lang, _MPP_TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    def _apply_lang(self):
        self.grp_files.setTitle(self._t("grp_files"))
        self.btn_browse.setText(self._t("browse"))
        self.btn_use_main.setText(self._t("use_main"))
        self.btn_use_main.setToolTip(self._t("main_hint"))
        self.lbl_mol.setText(self._t("mol_status",
                                     n=len(self._atoms),
                                     name=os.path.basename(self._input_path))
                             if self._atoms else self._t("no_mol"))
        self.grp_sel.setTitle(self._t("grp_sel"))
        self.lbl_sel_hint.setText(self._t("sel_hint"))
        self.btn_apply_sel.setText(self._t("apply_sel"))
        self.btn_select_all.setText(self._t("select_all"))
        self.btn_clear_sel.setText(self._t("clear_sel"))
        self.lbl_sel_current.setText(self._t("sel_current",
                                             sel=self._selection_text()))
        self.grp_run.setTitle(self._t("grp_run"))
        self.btn_run.setText(self._t("run_btn"))
        self.btn_stop.setText(self._t("stop"))
        self.lbl_run_hint.setText(self._t("run_hint"))
        self.lbl_card_title.setText(self._t("card_title"))
        self.lbl_mpp_cap.setText(self._t("mpp_cap"))
        self.lbl_sdp_cap.setText(self._t("sdp_cap"))
        self.lbl_pqr_lbl.setText(self._t("pqr_lbl"))
        self.btn_vmd.setText(self._t("vmd_preview"))

    def _selection_text(self):
        if not self._sel_indices:
            return self._t("sel_empty")
        return _format_atom_selection(sorted(self._sel_indices))

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(self._grp_files())
        root.addWidget(self._grp_selection())
        root.addWidget(self._grp_run())
        root.addWidget(self._grp_result_card(), 1)

    def _grp_files(self):
        self.grp_files = QGroupBox()
        l = QVBoxLayout(self.grp_files)
        l.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_use_main = QPushButton()
        self.btn_use_main.clicked.connect(self._try_use_main_file)
        row.addWidget(self.btn_use_main)
        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self._browse_file)
        row.addWidget(self.btn_browse)
        row.addStretch()
        l.addLayout(row)
        self.lbl_mol = QLabel(self._t("no_mol"))
        l.addWidget(self.lbl_mol)
        return self.grp_files

    def _grp_selection(self):
        self.grp_sel = QGroupBox()
        l = QVBoxLayout(self.grp_sel)
        l.setSpacing(6)
        self.lbl_sel_hint = QLabel()
        self.lbl_sel_hint.setWordWrap(True)
        l.addWidget(self.lbl_sel_hint)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit_sel = QLineEdit()
        self.edit_sel.setPlaceholderText("9-10,13-30")
        row.addWidget(self.edit_sel, 1)
        self.btn_apply_sel = QPushButton()
        self.btn_apply_sel.clicked.connect(self._apply_edit_selection)
        row.addWidget(self.btn_apply_sel)
        self.btn_select_all = QPushButton()
        self.btn_select_all.clicked.connect(self._select_all)
        row.addWidget(self.btn_select_all)
        self.btn_clear_sel = QPushButton()
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        row.addWidget(self.btn_clear_sel)
        l.addLayout(row)
        self.lbl_sel_current = QLabel()
        l.addWidget(self.lbl_sel_current)
        return self.grp_sel

    def _grp_run(self):
        self.grp_run = QGroupBox()
        l = QVBoxLayout(self.grp_run)
        l.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_run = QPushButton()
        self.btn_run.setMinimumWidth(170)
        self.btn_run.clicked.connect(self._run_mpp)
        row.addWidget(self.btn_run)
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumWidth(90)
        self.btn_stop.clicked.connect(self._stop_mpp)
        row.addWidget(self.btn_stop)
        row.addStretch()
        l.addLayout(row)
        self.lbl_run_hint = QLabel()
        self.lbl_run_hint.setWordWrap(True)
        l.addWidget(self.lbl_run_hint)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        l.addWidget(self.progress_bar)
        return self.grp_run

    def _grp_result_card(self):
        """MPP 结果卡片：圆角矩形包裹「标题 + 数值 + 偏离文件 + VMD 按钮 + 日志」。"""
        card = QFrame()
        card.setObjectName("MppCard")
        card.setStyleSheet("""
            QFrame#MppCard {
                background-color: #FFFFFF;
                border: 1px solid #D7E1EC;
                border-radius: 10px;
            }
            QLabel#MppChip {
                background-color: #1565C0;
                color: #FFFFFF;
                border-radius: 4px;
                padding: 2px 14px;
                font-weight: bold;
                font-size: 9pt;
            }
            QLabel#MppValue {
                font-size: 15pt;
                font-weight: bold;
                color: #1F2D3D;
            }
        """)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(12, 10, 12, 10)
        card_l.setSpacing(8)

        self.lbl_card_title = QLabel()
        self.lbl_card_title.setObjectName("MppChip")
        self.lbl_card_title.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        card_l.addWidget(self.lbl_card_title, 0, Qt.AlignLeft)

        val_row = QHBoxLayout()
        val_row.setSpacing(16)
        mpp_box = QVBoxLayout()
        self.lbl_mpp_cap = QLabel()
        self.lbl_mpp_cap.setStyleSheet("color:#5A6B7D; font-size:9pt;")
        mpp_box.addWidget(self.lbl_mpp_cap)
        self.lbl_mpp_val = QLabel("—")
        self.lbl_mpp_val.setObjectName("MppValue")
        mpp_box.addWidget(self.lbl_mpp_val)
        val_row.addLayout(mpp_box)
        sdp_box = QVBoxLayout()
        self.lbl_sdp_cap = QLabel()
        self.lbl_sdp_cap.setStyleSheet("color:#5A6B7D; font-size:9pt;")
        sdp_box.addWidget(self.lbl_sdp_cap)
        self.lbl_sdp_val = QLabel("—")
        self.lbl_sdp_val.setObjectName("MppValue")
        sdp_box.addWidget(self.lbl_sdp_val)
        val_row.addLayout(sdp_box)
        val_row.addStretch()
        card_l.addLayout(val_row)

        pqr_row = QHBoxLayout()
        pqr_row.setSpacing(6)
        self.lbl_pqr_lbl = QLabel()
        pqr_row.addWidget(self.lbl_pqr_lbl)
        self.lbl_pqr_path = QLabel(self._t("no_pqr"))
        self.lbl_pqr_path.setStyleSheet("color:#7E9AB8; font-size:9pt;")
        self.lbl_pqr_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pqr_row.addWidget(self.lbl_pqr_path, 1)
        self.btn_vmd = QPushButton()
        self.btn_vmd.clicked.connect(self._vmd_preview)
        pqr_row.addWidget(self.btn_vmd)
        card_l.addLayout(pqr_row)
        # 注：输出日志已并入主窗口「运行日志」tab，本面板不再单独显示
        card_l.addStretch(1)
        return card

    # ── 文件 ──
    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择分子文件", "",
            "分子文件 (*.fchk *.log *.out *.wfn *.pdb *.xyz);;"
            "格式化 Checkpoint (*.fchk);;Gaussian Log (*.log *.out);;"
            "波函数 (*.wfn);;PDB (*.pdb);;XYZ (*.xyz);;所有文件 (*.*)")
        if path:
            self._load_molecule(path)

    def _try_use_main_file(self):
        try:
            p = self._get_fchk()
        except Exception:
            p = ""
        if p and os.path.isfile(p) and p != self._input_path:
            self._load_molecule(p, quiet=True)

    def _load_molecule(self, path, quiet=False):
        try:
            atoms = load_atoms_any(path)
        except Exception as e:
            self._append_log(self._t("parse_fail", err=e) + "\n")
            return
        if not atoms:
            self._append_log(self._t("parse_fail", err="no atoms parsed") + "\n")
            return
        self._input_path = path
        self._atoms = atoms
        self._sel_indices = set()
        self._pqr_path = ""
        self._deviations = {}
        self._mpp = self._sdp = None
        self.lbl_mpp_val.setText("—")
        self.lbl_sdp_val.setText("—")
        self.lbl_pqr_path.setText(self._t("no_pqr"))
        if self.glw is not None:
            try:
                # 清除画布残留选中态与旧着色，避免旧索引越界
                try:
                    self.glw._selected_atoms.clear()
                    self.glw.set_atom_colors(None)
                except Exception:
                    pass
                self.glw.set_molecule(atoms)
            except Exception as e:
                self._append_log("set_molecule: %s\n" % e)
        self._apply_lang()
        self._update_sel_ui()
        if not quiet:
            self._append_log(
                self._t("load_ok", name=os.path.basename(path),
                        n=len(atoms), nsel=0) + "\n")

    # ── 选择 ──
    def _on_atom_pick(self, _idx_1based):
        """画布原子点击回调（1-based）：同步选中集与文本。"""
        self._sync_selection_from_glw()

    def _sync_selection_from_glw(self):
        if self.glw is None:
            return
        sel = sorted(getattr(self.glw, "_selected_atoms", []) or [])
        self._sel_indices = set(i + 1 for i in sel)
        self._update_sel_ui()
        self._apply_canvas_colors()

    def _apply_edit_selection(self):
        """把编辑框里的范围串解析并应用到画布选择。"""
        text = (self.edit_sel.text() or "").strip()
        if not text:
            self._clear_selection()
            return
        indices = set()
        ok = True
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-")
                    lo, hi = int(a), int(b)
                    if lo > hi:
                        lo, hi = hi, lo
                    indices.update(range(lo, hi + 1))
                except ValueError:
                    ok = False
                    break
            else:
                try:
                    indices.add(int(part))
                except ValueError:
                    ok = False
                    break
        if not ok:
            self._append_log("无效的编号范围: %s\n" % text)
            return
        n = len(self._atoms)
        indices = {i for i in indices if 1 <= i <= n}
        self._sel_indices = indices
        if self.glw is not None:
            try:
                self.glw._selected_atoms[:] = sorted(i - 1 for i in indices)
                self.glw._regenerate_atoms()
                self.glw._needs_upload = True
                self.glw.update()
            except Exception:
                pass
        self._update_sel_ui()
        self._apply_canvas_colors()

    def _select_all(self):
        if not self._atoms:
            return
        self._sel_indices = set(range(1, len(self._atoms) + 1))
        if self.glw is not None:
            try:
                self.glw._selected_atoms[:] = list(range(len(self._atoms)))
                self.glw._regenerate_atoms()
                self.glw._needs_upload = True
                self.glw.update()
            except Exception:
                pass
        self._update_sel_ui()
        self._apply_canvas_colors()

    def _clear_selection(self):
        self._sel_indices = set()
        self.edit_sel.clear()
        if self.glw is not None:
            try:
                self.glw._clear_selection()
            except Exception:
                try:
                    self.glw._selected_atoms.clear()
                    self.glw.update()
                except Exception:
                    pass
        self._update_sel_ui()
        self._apply_canvas_colors()

    def _update_sel_ui(self):
        txt = self._selection_text()
        self.lbl_sel_current.setText(self._t("sel_current", sel=txt))
        if self.edit_sel.text().strip() != txt:
            self.edit_sel.setText(txt)

    # ── 运行 ──
    def _run_mpp(self):
        if not self._atoms:
            QMessageBox.information(self, self._t("grp_run"), self._t("no_file"))
            return
        if not self._sel_indices:
            QMessageBox.information(self, self._t("grp_run"), self._t("no_sel"))
            return
        mw = self._get_mw()
        if not mw or not os.path.isfile(mw):
            QMessageBox.warning(self, self._t("grp_run"), self._t("no_multiwfn"))
            return

        # Multiwfn 不能直接读 .log/.out：解析出的几何写临时 xyz 再喂给它
        ext = os.path.splitext(self._input_path)[1].lower()
        mw_input = self._input_path
        tmp_xyz = None
        if ext in (".log", ".out"):
            tmp_xyz = os.path.join(tempfile.gettempdir(),
                                   "mpp_geom_" + os.path.basename(self._input_path) + ".xyz")
            with open(tmp_xyz, "w", encoding="utf-8", newline="\n") as f:
                f.write(_atoms_to_xyz_text(self._atoms))
            mw_input = tmp_xyz

        sel_str = self._selection_text()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.show()
        self._append_log("━━━ MPP 分析 ━━━\n")
        self._append_log(f"  输入: {os.path.basename(self._input_path)}\n")
        self._append_log(f"  原子: {sel_str}（{len(self._sel_indices)} 个）\n")
        self._append_log(self._t("running") + "\n")

        self._worker = MppWorker(mw, mw_input, sel_str, parent=self)
        self._worker.done.connect(self._on_worker_done)
        self._worker.start()

    def _stop_mpp(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
            self._append_log("■ 已停止\n")
        self._on_run_finished()

    def _on_run_finished(self):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.hide()

    def _on_worker_done(self, result):
        self._on_run_finished()
        if result.get("error"):
            self._append_log(self._t("run_fail", err=result["error"]) + "\n")
            return
        self._mpp = result.get("mpp")
        self._sdp = result.get("sdp")
        self._pqr_path = result.get("pqr_path", "")

        if self._mpp is not None:
            self.lbl_mpp_val.setText(f"{self._mpp:.4f} {self._t('unit_ang')}")
        else:
            self.lbl_mpp_val.setText("—")
        if self._sdp is not None:
            self.lbl_sdp_val.setText(f"{self._sdp:.4f} {self._t('unit_ang')}")
        else:
            self.lbl_sdp_val.setText("—")
        if self._pqr_path:
            self.lbl_pqr_path.setText(self._pqr_path)
            # 解析 PQR 偏离值 → 进入偏离着色模式（配色切单色白 + 选中原子着色）
            try:
                self._deviations = parse_pqr_deviations(self._pqr_path)
            except Exception as e:
                self._deviations = {}
                self._append_log("PQR 偏离值解析失败: %s\n" % e)
            self._activate_deviation_coloring()
            self._register_vmd_scene()
            self._append_log(self._t("vmd_registered") + "\n")
            # VMD 已连接则自动推送
            if callable(self._on_vmd_refresh):
                try:
                    self._on_vmd_refresh()
                except Exception:
                    pass

        if self._mpp is not None and self._sdp is not None:
            self._append_log(self._t("done", mpp=self._mpp, sdp=self._sdp) + "\n")
        else:
            self._append_log(self._t("done_nopqr") + "\n")
            tail = (result.get("stdout") or "")[-400:]
            self._append_log("输出末尾:\n" + tail + "\n")

    # ── VMD ──
    def _activate_deviation_coloring(self):
        """进入偏离着色模式：原子配色切到「单色白」（可视化 tab 可见可改），
        选中原子叠加偏离色；未选中原子与键跟随当前原子配色。"""
        # 1) 原子配色 → 单色白
        if callable(self._on_set_mol_style):
            try:
                self._on_set_mol_style("单色白")
            except Exception:
                pass
        elif self.glw is not None:
            try:
                self.glw.set_mol_style("Mono white")
            except Exception:
                pass
        # 2) 选中原子按偏离着色
        self._apply_canvas_colors()

    def _apply_canvas_colors(self):
        """选中原子按偏离平面的距离着色（BWR ±0.5 Å：平面下蓝、平面上红、
        平面内白），未选中原子保持当前原子配色（默认单色白）。"""
        if self.glw is None or not self._deviations or not self._atoms:
            return
        lo, hi = DEFAULT_PQR_RANGE
        span = (hi - lo) or 1e-9
        overrides = {}
        for i in self._sel_indices:
            if i in self._deviations:
                q = self._deviations[i]
                overrides[i] = _bwr_rgb((q - lo) / span)
        try:
            self.glw.set_atom_colors(overrides)
        except Exception as e:
            self._append_log("画布着色失败: %s\n" % e)

    def _register_vmd_scene(self):
        if self.glw is None or not self._pqr_path:
            return
        try:
            lo, hi = DEFAULT_PQR_RANGE
            self.glw.set_vmd_scene([
                {"type": "pqr", "pqr": self._pqr_path,
                 "cmin": lo, "cmax": hi},
            ])
        except Exception as e:
            self._append_log("VMD 场景登记失败: %s\n" % e)

    def _vmd_preview(self):
        """「VMD 预览（偏离着色）」：登记场景 → 打开 VMD 控制台并同步/启动 VMD。"""
        if not self._pqr_path:
            QMessageBox.information(self, self._t("card_title"),
                                    self._t("done_nopqr"))
            return
        self._register_vmd_scene()
        if callable(self._on_sync_vmd):
            self._on_sync_vmd()
        else:
            self._append_log(self._t("vmd_no_cb") + "\n")

    # ── 日志（转发到主窗口「运行日志」tab） ──
    def _append_log(self, msg):
        if self._log_func:
            try:
                self._log_func(msg)
            except Exception:
                pass

    def shutdown(self):
        """主窗口关闭时调用：终止运行中的 MPP 分析线程（避免 QThread
        销毁时仍在运行导致 Qt 致命崩溃）。"""
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.terminate()
                self._worker.wait(3000)
            except Exception:
                pass
            self._worker = None
