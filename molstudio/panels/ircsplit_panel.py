# -*- coding: utf-8 -*-
"""
ircsplit_panel.py — IRC 拆分面板（GXNU MolStudio 的一个 tab）

把 Gaussian IRC 输出文件（.out/.log）里的**每个结构点**（TS + 正向点 +
反向点）解析出来：
  * 左侧共享 OpenGL 画布：点击/上下键逐点浏览结构（球棍模型）；
  * 右侧设置：正向/反向取点数、翻转顺序、泛函/基组等计算参数；
  * 一键把整条 IRC 拆成逐点单点能计算的 .gjf（含 %chk/%mem/%nproc）。

解析与编号逻辑移植自早期的 IRCsplit_GUI.py（基于卢天 IRCsplit 思路）：
  * 坐标段：Input orientation:（缺省回退 Z-Matrix orientation:）
  * Gaussian IRC 输出中每点坐标出现在其 "Path Number:" 之前，故向后回溯
  * 第一个 "Path Number: 1" 是过渡态 TS，正向点数 = Path1 数 - 1
  * 默认文件顺序：反向点(倒序) + TS + 正向点；勾选翻转则反向。
"""

import os
import re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QFileDialog, QMessageBox, QGroupBox, QListWidget,
    QSpinBox, QGridLayout,
)
from PyQt5.QtCore import Qt, QSettings

from molstudio.core.fchk_orbital import ELEMENT_SYMBOLS

# 与 IRCsplit 相同的带宽度元素符号表（索引 0 = 幽灵原子占位，Z 直接索引）
_ELEMENT_PAD = [
    "Bq", "H ", "He", "Li", "Be", "B ", "C ", "N ", "O ", "F ", "Ne",
    "Na", "Mg", "Al", "Si", "P ", "S ", "Cl", "Ar", "K ", "Ca", "Sc",
    "Ti", "V ", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Br", "Kr", "Rb", "Sr", "Y ", "Zr", "Nb", "Mo", "Tc",
    "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I ", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
    "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W ", "Re", "Os",
    "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr",
    "Ra", "Ac", "Th", "Pa", "U ", "Np", "Pu", "Am", "Cm", "Bk", "Cf",
    "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt",
]

_TYPE_LABEL = {"TS": "TS", "forward": "正向", "reverse": "反向"}


def _parse_idx_ranges(text):
    """解析 "1,3,5-8" 类原子编号串 → 1-based 正整数集合。"""
    out = set()
    for part in re.split(r"[;,，、\s]+", str(text or "").strip()):
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                lo, hi = int(a), int(b)
                if lo > hi:
                    lo, hi = hi, lo
                out.update(range(lo, hi + 1))
            except ValueError:
                continue
        else:
            try:
                out.add(int(part))
            except ValueError:
                continue
    return {x for x in out if x > 0}


def _fmt_ranges(nums):
    """把编号集合压缩成 "1,3,5-8" 形式的显示串。"""
    nums = sorted(set(nums))
    if not nums:
        return ""
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


class IRCSplitPanel(QWidget):
    """IRC 拆分面板：解析 IRC 输出 → 画布浏览结构 → 拆分为逐点 gjf。"""

    def __init__(self, glw=None, log_func=None, parent=None):
        super().__init__(parent)
        self._glw = glw
        self._log_func = log_func

        self.irc_data = []      # [{"index": "TS"|int, "type": ..., "coords": [(z,x,y,z) Å]}]
        self.ordered = []       # 按当前设置排序后的浏览/生成顺序
        self.natm = 0
        self.charge = 0
        self.mult = 1
        self._frag_set = set()      # 分片段拆分：片段 A 的 1-based 原子编号
        self._saved_box_cb = None   # 进入画布框选模式前保存的既有回调（避免覆盖 IGMH 等）

        self.settings = QSettings("GXNU", "IRCsplit")
        self._load_settings()
        self._build_ui()

    # ── 设置持久化 ──────────────────────────────────────────
    def _load_settings(self):
        self._irc_file = self.settings.value("irc_file", "")
        self._output_folder = self.settings.value("output_folder", "")
        self._method = self.settings.value("method", "M06L")
        self._basis = self.settings.value("basis", "def2svp")
        self._extra_kw = self.settings.value("extra_kw", "")
        self._nproc = int(self.settings.value("nproc", 8))
        self._mem = self.settings.value("mem", "32GB")
        self._nforward = int(self.settings.value("nforward", 0))
        self._nreverse = int(self.settings.value("nreverse", 0))
        self._reverse = self.settings.value("reverse", "false") == "true"

    def _save_settings(self):
        s = self.settings
        s.setValue("irc_file", self.ed_irc.text())
        s.setValue("output_folder", self.ed_out.text())
        s.setValue("method", self.ed_method.text())
        s.setValue("basis", self.ed_basis.text())
        s.setValue("extra_kw", self.ed_kw.text())
        s.setValue("nproc", self.spin_nproc.value())
        s.setValue("mem", self.ed_mem.text())
        s.setValue("nforward", self.spin_nf.value())
        s.setValue("nreverse", self.spin_nr.value())
        s.setValue("reverse", str(self.chk_reverse.isChecked()))

    def _log(self, msg):
        if callable(self._log_func):
            try:
                self._log_func(str(msg))
            except Exception:
                pass

    # ── UI ─────────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        # 全站统一：页面外边距 8px + 一级块间距 8px（基准 = AIM 面板，见
        # aim_panel._build_ui）。
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # ── 文件 ──
        fg = QGroupBox("IRC 文件")
        fl = QGridLayout(fg)
        fl.setContentsMargins(10, 14, 10, 10)
        fl.setHorizontalSpacing(6)
        fl.setVerticalSpacing(6)
        fl.addWidget(QLabel("IRC 输出 (.out/.log):"), 0, 0)
        self.ed_irc = QLineEdit(self._irc_file)
        self.ed_irc.setPlaceholderText("选择 Gaussian IRC 输出文件")
        fl.addWidget(self.ed_irc, 0, 1)
        btn_irc = QPushButton("浏览")
        btn_irc.clicked.connect(self._browse_irc)
        fl.addWidget(btn_irc, 0, 2)
        fl.addWidget(QLabel("gjf 输出目录:"), 1, 0)
        self.ed_out = QLineEdit(self._output_folder)
        self.ed_out.setPlaceholderText("拆分出的 gjf 文件保存位置")
        fl.addWidget(self.ed_out, 1, 1)
        btn_out = QPushButton("浏览")
        btn_out.clicked.connect(self._browse_out)
        fl.addWidget(btn_out, 1, 2)
        fl.setColumnStretch(1, 1)
        lay.addWidget(fg)

        # ── 解析 / 取点 ──
        pg = QGroupBox("IRC 拆分")
        pl = QGridLayout(pg)
        pl.setContentsMargins(10, 14, 10, 10)
        pl.setHorizontalSpacing(6)
        pl.setVerticalSpacing(6)
        pl.addWidget(QLabel("正向点数:"), 0, 0)
        self.spin_nf = QSpinBox()
        self.spin_nf.setRange(0, 10000)
        self.spin_nf.setValue(self._nforward)
        self.spin_nf.valueChanged.connect(self._refresh_order)
        pl.addWidget(self.spin_nf, 0, 1)
        pl.addWidget(QLabel("反向点数:"), 0, 2)
        self.spin_nr = QSpinBox()
        self.spin_nr.setRange(0, 10000)
        self.spin_nr.setValue(self._nreverse)
        self.spin_nr.valueChanged.connect(self._refresh_order)
        pl.addWidget(self.spin_nr, 0, 3)
        self.chk_reverse = QCheckBox("翻转路径顺序")
        self.chk_reverse.setChecked(self._reverse)
        self.chk_reverse.toggled.connect(self._refresh_order)
        pl.addWidget(self.chk_reverse, 0, 4)
        pl.setColumnStretch(5, 1)

        self.btn_parse = QPushButton("解析 IRC 文件")
        self.btn_parse.setObjectName("PrimaryBtn")
        self.btn_parse.clicked.connect(self._parse_irc_file)
        pl.addWidget(self.btn_parse, 1, 0, 1, 2)
        self.lbl_summary = QLabel("未解析")
        self.lbl_summary.setStyleSheet("color:#5B6B7F;")
        pl.addWidget(self.lbl_summary, 1, 2, 1, 4)
        lay.addWidget(pg)

        # ── 结构列表（左侧画布浏览） ──
        cg = QGroupBox("IRC 结构点（点击在左侧画布显示）")
        cl = QVBoxLayout(cg)
        cl.setContentsMargins(10, 14, 10, 10)
        cl.setSpacing(4)
        self.list_pts = QListWidget()
        self.list_pts.setMinimumHeight(120)
        self.list_pts.currentRowChanged.connect(self._on_list_row)
        cl.addWidget(self.list_pts, stretch=1)
        nav = QHBoxLayout()
        b_prev = QPushButton("上一结构")
        b_prev.clicked.connect(lambda: self._step(-1))
        b_next = QPushButton("下一结构")
        b_next.clicked.connect(lambda: self._step(1))
        b_ts = QPushButton("跳转 TS")
        b_ts.clicked.connect(self._goto_ts)
        nav.addWidget(b_prev)
        nav.addWidget(b_next)
        nav.addWidget(b_ts)
        nav.addStretch(1)
        cl.addLayout(nav)
        lay.addWidget(cg, stretch=1)

        # ── 分片段拆分（片段 A = 框选/编号原子，片段 B = 其余） ──
        fg = QGroupBox("分片段拆分（片段 A 原子，其余自动为片段 B）")
        f2 = QGridLayout(fg)
        f2.setContentsMargins(10, 14, 10, 10)
        f2.setHorizontalSpacing(6)
        f2.setVerticalSpacing(6)
        f2.addWidget(QLabel("片段 A 原子:"), 0, 0)
        self.ed_frag = QLineEdit()
        self.ed_frag.setPlaceholderText("如 1,3,5-8；与画布 Shift+框选结果同步")
        f2.addWidget(self.ed_frag, 0, 1, 1, 3)
        self.btn_box = QPushButton("框选→片段 A")
        self.btn_box.setCheckable(True)
        self.btn_box.setToolTip("开启后：在左侧画布按住 Shift 拖框，框中的原子并入片段 A；"
                                "再点一次退出（退出后恢复画布原有框选用途，如 IGMH 分片段）")
        self.btn_box.toggled.connect(self._on_box_mode_toggled)
        f2.addWidget(self.btn_box, 0, 4)
        btn_apply = QPushButton("应用编号")
        btn_apply.clicked.connect(self._apply_frag_text)
        f2.addWidget(btn_apply, 0, 5)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._clear_frag)
        f2.addWidget(btn_clear, 0, 6)
        self.lbl_frag = QLabel("片段 A：0 个原子")
        self.lbl_frag.setStyleSheet("color:#5B6B7F;")
        f2.addWidget(self.lbl_frag, 0, 7)
        f2.setColumnStretch(8, 1)
        f2.addWidget(QLabel("片段 A 电荷/多重度:"), 1, 0)
        self.ed_cm_a = QLineEdit("0")
        self.ed_cm_a.setFixedWidth(46)
        self.ed_mul_a = QLineEdit("1")
        self.ed_mul_a.setFixedWidth(46)
        f2.addWidget(self.ed_cm_a, 1, 1)
        f2.addWidget(self.ed_mul_a, 1, 2)
        f2.addWidget(QLabel("片段 B 电荷/多重度:"), 1, 3)
        self.ed_cm_b = QLineEdit("0")
        self.ed_cm_b.setFixedWidth(46)
        self.ed_mul_b = QLineEdit("1")
        self.ed_mul_b.setFixedWidth(46)
        f2.addWidget(self.ed_cm_b, 1, 4)
        f2.addWidget(self.ed_mul_b, 1, 5)
        self.btn_gen_frag = QPushButton("批量生成片段 A/B gjf（全部结构点）")
        self.btn_gen_frag.setObjectName("PrimaryBtn")
        self.btn_gen_frag.clicked.connect(self._generate_fragment_gjf_files)
        f2.addWidget(self.btn_gen_frag, 2, 0, 1, 6)
        lay.addWidget(fg)

        # ── 计算设置 ──
        sg = QGroupBox("单点计算设置（生成 gjf 用）")
        sl = QGridLayout(sg)
        sl.setContentsMargins(10, 14, 10, 10)
        sl.setHorizontalSpacing(6)
        sl.setVerticalSpacing(6)
        sl.addWidget(QLabel("泛函:"), 0, 0)
        self.ed_method = QLineEdit(self._method)
        self.ed_method.setFixedWidth(120)
        sl.addWidget(self.ed_method, 0, 1)
        sl.addWidget(QLabel("基组:"), 0, 2)
        self.ed_basis = QLineEdit(self._basis)
        self.ed_basis.setFixedWidth(120)
        sl.addWidget(self.ed_basis, 0, 3)
        sl.addWidget(QLabel("CPU 核:"), 0, 4)
        self.spin_nproc = QSpinBox()
        self.spin_nproc.setRange(1, 128)
        self.spin_nproc.setValue(self._nproc)
        sl.addWidget(self.spin_nproc, 0, 5)
        sl.addWidget(QLabel("内存:"), 0, 6)
        self.ed_mem = QLineEdit(self._mem)
        self.ed_mem.setFixedWidth(90)
        sl.addWidget(self.ed_mem, 0, 7)
        sl.setColumnStretch(8, 1)
        sl.addWidget(QLabel("其它关键词:"), 1, 0)
        self.ed_kw = QLineEdit(self._extra_kw)
        self.ed_kw.setPlaceholderText("如 empiricaldispersion=gd3bj  scrf=(smd,solvent=water)")
        sl.addWidget(self.ed_kw, 1, 1, 1, 7)
        lay.addWidget(sg)

        # ── 生成 ──
        self.btn_gen = QPushButton("拆分全部结构 → 生成逐点 gjf")
        self.btn_gen.setObjectName("PrimaryBtn")
        self.btn_gen.clicked.connect(self._generate_gjf_files)
        lay.addWidget(self.btn_gen)
        tip = QLabel("提示：正向/反向点数在解析后自动设为全部；"
                     "「电荷/多重度」取自 IRC 文件头。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#7A8699; font-size:9pt;")
        lay.addWidget(tip)
        lay.addStretch(1)

    # ── 文件选择 ───────────────────────────────────────────
    def _browse_irc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 IRC 输出文件", self.ed_irc.text(),
            "Gaussian 输出文件 (*.out *.log);;所有文件 (*.*)")
        if path:
            self.ed_irc.setText(path)
            if not self.ed_out.text():
                self.ed_out.setText(os.path.dirname(path))

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出文件夹",
                                             self.ed_out.text())
        if d:
            self.ed_out.setText(d)

    # ── 解析 ───────────────────────────────────────────────
    def _parse_irc_file(self):
        irc_path = self.ed_irc.text().strip()
        if not irc_path or not os.path.exists(irc_path):
            QMessageBox.critical(self, "错误", "请选择有效的 IRC 输出文件")
            return

        self._log(f"正在解析 IRC: {irc_path}")
        try:
            with open(irc_path, "rb") as f:
                raw = f.read()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = raw.decode("gbk", errors="replace")
        except OSError as e:
            QMessageBox.critical(self, "错误", f"无法读取文件: {e}")
            return

        coord_label = ("Input orientation:"
                       if "Input orientation:" in content
                       else "Z-Matrix orientation:")
        self._log(f"使用坐标段: {coord_label.strip()}")

        m_natm = re.search(r"NAtoms=\s*(\d+)", content)
        if not m_natm:
            QMessageBox.critical(self, "错误", "未找到原子数 (NAtoms=)")
            return
        self.natm = int(m_natm.group(1))

        self._extract_charge_mult(content)

        nf_total = content.count("Path Number:   1")
        nr_total = content.count("Path Number:   2")
        # 与 Fortran 版一致：第一个 Path1 是 TS，不是正向点
        nf_avail = max(nf_total - 1, 0)
        nr_avail = nr_total

        self.spin_nf.setMaximum(nf_avail)
        self.spin_nr.setMaximum(nr_avail)
        self.spin_nf.setValue(nf_avail)
        self.spin_nr.setValue(nr_avail)

        self._log(f"正向路径段: {nf_total}（含 TS）  反向路径段: {nr_total}")
        self._log(f"电荷/多重度: {self.charge} {self.mult}  原子数: {self.natm}")

        lines = content.splitlines()
        data = []
        start = 0
        for i in range(1, nf_total + 1):
            coords, end = self._find_coords(lines, 1, coord_label,
                                            self.natm, start)
            if not coords:
                continue
            if i == 1:
                data.append({"index": "TS", "type": "TS", "coords": coords})
            else:
                data.append({"index": i - 1, "type": "forward",
                             "coords": coords})
            start = end + 1

        start = 0
        for i in range(1, nr_total + 1):
            coords, end = self._find_coords(lines, 2, coord_label,
                                            self.natm, start)
            if not coords:
                continue
            data.append({"index": i, "type": "reverse", "coords": coords})
            start = end + 1

        self.irc_data = data
        self._log(f"共提取 {len(data)} 个 IRC 点（TS + 正向 {max(nf_avail, 0)} + "
                  f"反向 {nr_avail}）")
        self._refresh_order()

    def _find_coords(self, lines, path_num, coord_label, natm, start_idx=0):
        """自 start_idx 向后找 Path Number，再向前回溯坐标段读取 natm 行。"""
        for idx in range(start_idx, len(lines)):
            if f"Path Number:   {path_num}" not in lines[idx]:
                continue
            coord_idx = idx - 1
            found = False
            while coord_idx >= 0:
                if coord_label in lines[coord_idx]:
                    found = True
                    break
                coord_idx -= 1
            if not found:
                return None, idx
            coord_idx += 5
            coords = []
            for _ in range(natm):
                if coord_idx >= len(lines):
                    break
                parts = lines[coord_idx].split()
                if len(parts) >= 6:
                    try:
                        an = int(parts[1])
                        x = float(parts[3])
                        y = float(parts[4])
                        z = float(parts[5])
                        coords.append((an, x, y, z))
                    except (ValueError, IndexError):
                        pass
                coord_idx += 1
            if len(coords) == natm:
                return coords, idx
            return None, idx
        return None, 0

    def _extract_charge_mult(self, content):
        patterns = [
            r'Charge\s*=\s*([-\d]+)\s*Multiplicity\s*=\s*(\d+)',
            r'Charge\s*-\s*Multiplicity\s*\n\s*([-\d]+)\s+(\d+)',
            r'^\s*([-\d]+)\s+(\d+)\s*$',
        ]
        for pat in patterns:
            for m in re.findall(pat, content, re.MULTILINE):
                try:
                    chg, mul = int(m[0]), int(m[1])
                except (ValueError, IndexError):
                    continue
                if mul >= 1:
                    self.charge, self.mult = chg, mul
                    return

    # ── 排序 / 列表 / 画布浏览 ─────────────────────────────
    def _selected_points(self):
        """按当前 取点数/翻转 设置筛出点（TS 恒保留）。"""
        nf = self.spin_nf.value()
        nr = self.spin_nr.value()
        ts, fwd, rev = None, [], []
        for pt in self.irc_data:
            if pt["type"] == "TS":
                ts = pt
            elif pt["type"] == "forward" and pt["index"] <= nf:
                fwd.append(pt)
            elif pt["type"] == "reverse" and pt["index"] <= nr:
                rev.append(pt)
        if self.chk_reverse.isChecked():
            return fwd[::-1] + ([ts] if ts else []) + rev
        return rev[::-1] + ([ts] if ts else []) + fwd

    def _refresh_order(self):
        self.ordered = self._selected_points()
        self.list_pts.blockSignals(True)
        self.list_pts.clear()
        for i, pt in enumerate(self.ordered):
            lab = _TYPE_LABEL.get(pt["type"], pt["type"])
            if pt["type"] == "TS":
                info = "TS（过渡态）"
            else:
                info = f"{lab}点 {pt['index']}"
            self.list_pts.addItem(f"{i + 1:03d}  {info}  ({self.natm} 原子)")
        self.list_pts.blockSignals(False)
        nf_used = sum(1 for p in self.ordered if p["type"] == "forward")
        nr_used = sum(1 for p in self.ordered if p["type"] == "reverse")
        self.lbl_summary.setText(
            f"共 {len(self.irc_data)} 点 → 生成 {len(self.ordered)} 个"
            f"（TS 1 + 正向 {nf_used} + 反向 {nr_used}）"
            if self.irc_data else "未解析")
        if self.ordered:
            self.list_pts.setCurrentRow(0)
        else:
            self._show_structure(None)

    def _on_list_row(self, row):
        if 0 <= row < len(self.ordered):
            self._show_structure(self.ordered[row])

    def _step(self, delta):
        if not self.ordered:
            return
        row = max(0, min(len(self.ordered) - 1,
                         self.list_pts.currentRow() + delta))
        self.list_pts.setCurrentRow(row)

    def _goto_ts(self):
        for i, pt in enumerate(self.ordered):
            if pt["type"] == "TS":
                self.list_pts.setCurrentRow(i)
                return

    def _show_structure(self, point):
        """把当前 IRC 结构显示到共享画布（球棍模型，坐标 Å→画布 Bohr）。"""
        glw = self._glw
        if glw is None:
            return
        if point is None:
            if hasattr(glw, "clear_molecule"):
                try:
                    glw.clear_molecule()
                except Exception:
                    pass
            return
        atoms = []
        for i, (an, x, y, z) in enumerate(point["coords"]):
            sym = ELEMENT_SYMBOLS.get(an, "?")
            atoms.append((i + 1, sym, an, (x, y, z)))   # Å，画布内部转 Bohr
        try:
            glw.set_molecule(atoms)
            glw.frame_to_molecule()
        except Exception as e:
            self._log(f"画布显示失败: {e}")

    # ── 生成 gjf ───────────────────────────────────────────
    def _generate_gjf_files(self):
        if not self.irc_data:
            QMessageBox.critical(self, "错误", "请先解析 IRC 文件")
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            QMessageBox.critical(self, "错误", "请选择 gjf 输出目录")
            return

        ordered = self.ordered
        if not ordered:
            QMessageBox.information(self, "提示", "当前取点设置为 0，无文件可生成")
            return

        os.makedirs(out_dir, exist_ok=True)
        nf = sum(1 for p in ordered if p["type"] == "forward")
        nr = sum(1 for p in ordered if p["type"] == "reverse")
        is_rev = self.chk_reverse.isChecked()
        base = os.path.splitext(os.path.basename(self.ed_irc.text()))[0] \
            if self.ed_irc.text() else "IRC"

        self._log(f"开始拆分: {len(ordered)} 个结构 → {out_dir}")
        written = 0
        for i, pt in enumerate(ordered):
            # 与 IRCsplit 一致的最终文件序号（翻转时正向倒排、TS 居中）
            fidx = self._fidx(pt, nf, nr, is_rev)
            fname = os.path.join(out_dir, f"{base}-{fidx:03d}.gjf")
            self._write_gjf(fname, pt["coords"], fidx, base)
            written += 1
            if (i + 1) % 10 == 0:
                self._log(f"  已生成 {i + 1}/{len(ordered)}")
        self._log(f"拆分完成：共 {written} 个 gjf")
        QMessageBox.information(self, "完成",
                                f"成功拆分 {written} 个结构 → {out_dir}")

    def _write_gjf(self, filename, coords, idx, basename=""):
        method = self.ed_method.text().strip()
        basis = self.ed_basis.text().strip()
        nproc = self.spin_nproc.value()
        mem = self.ed_mem.text().strip()
        add_kw = self.ed_kw.text().strip()

        lines = []
        chk = f"{basename}-{idx:03d}.chk" if basename else f"IRC{idx:04d}.chk"
        lines.append(f"%chk={chk}")
        if mem:
            lines.append(f"%mem={mem}")
        if nproc:
            lines.append(f"%nprocshared={nproc}")
        route = f"# {method}/{basis}" if basis else f"# {method}"
        if add_kw:
            route += " " + add_kw
        lines.append(route)
        lines.append("")
        lines.append(f"IRC point {idx}")
        lines.append("")
        lines.append(f"{self.charge} {self.mult}")
        for an, x, y, z in coords:
            elem = _ELEMENT_PAD[an] if 0 <= an < len(_ELEMENT_PAD) else f"{an}"
            lines.append(f"{elem:2s} {x:12.8f} {y:12.8f} {z:12.8f}")
        lines.append("")
        lines.append("")

        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # ── 分片段拆分（片段 A = 指定原子，片段 B = 其余） ─────────────
    def _fidx(self, pt, nf, nr, is_rev):
        """与 IRCsplit 一致的点文件序号（翻转时正向倒排、TS 居中）。"""
        if is_rev:
            if pt["type"] == "forward":
                return nf - pt["index"] + 1
            if pt["type"] == "TS":
                return nf + 1
            return nf + 1 + pt["index"]
        if pt["type"] == "reverse":
            return nr + 1 - pt["index"]
        if pt["type"] == "TS":
            return nr + 1
        return nr + 1 + pt["index"]

    def _on_box_mode_toggled(self, on):
        """进入/退出画布框选模式（接管→还原回调，避免覆盖 IGMH 等用途）。"""
        glw = self._glw
        if glw is None:
            self.btn_box.setChecked(False)
            return
        if on:
            self._saved_box_cb = getattr(glw, "_box_cb", None)
            glw.set_box_select_callback(self._on_box_select)
            self._log("片段 A 框选模式已开启：在左侧画布 Shift+左键拖框，"
                      "框中的原子并入片段 A")
        else:
            glw.set_box_select_callback(self._saved_box_cb)
            self._log("片段 A 框选模式已关闭")

    def _on_box_select(self, indices):
        add = {int(i) for i in indices if int(i) > 0}
        before = len(self._frag_set)
        self._frag_set |= add
        self._sync_frag_ui()
        if len(self._frag_set) > before:
            self._log(f"框选新增 {len(self._frag_set) - before} 个原子 → "
                      f"片段 A（共 {len(self._frag_set)} 个）")

    def _apply_frag_text(self):
        self._frag_set = _parse_idx_ranges(self.ed_frag.text())
        self._sync_frag_ui()

    def _clear_frag(self):
        self._frag_set = set()
        self._sync_frag_ui()
        if self.btn_box.isChecked():
            self.btn_box.setChecked(False)   # 顺带退出框选模式

    def _sync_frag_ui(self):
        self.ed_frag.setText(_fmt_ranges(self._frag_set))
        self.lbl_frag.setText(f"片段 A：{len(self._frag_set)} 个原子")

    def _read_cm(self, edit_c, edit_m):
        """读取片段电荷/多重度（合法返回 (charge, mult)，否则 None）。"""
        try:
            c = int(edit_c.text().strip() or "0")
            m = int(edit_m.text().strip() or "1")
        except ValueError:
            QMessageBox.warning(self, "错误", "电荷/多重度需为整数")
            return None
        if m < 1:
            QMessageBox.warning(self, "错误", "多重度需 ≥ 1")
            return None
        return c, m

    def _generate_fragment_gjf_files(self):
        """按片段 A（框选/编号原子）对全部结构点批量生成 A/B 两个片段 gjf。"""
        if not self.irc_data:
            QMessageBox.critical(self, "错误", "请先解析 IRC 文件")
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            QMessageBox.critical(self, "错误", "请选择 gjf 输出目录")
            return
        frag = {i for i in self._frag_set if 1 <= i <= max(self.natm, 1)}
        if not frag:
            QMessageBox.information(
                self, "提示",
                "片段 A 为空：请先在画布 Shift+框选原子，或在上方输入编号后点「应用编号」")
            return
        cm_a = self._read_cm(self.ed_cm_a, self.ed_mul_a)
        cm_b = self._read_cm(self.ed_cm_b, self.ed_mul_b)
        if cm_a is None or cm_b is None:
            return

        ordered = self.ordered
        if not ordered:
            QMessageBox.information(self, "提示", "当前取点设置为 0，无文件可生成")
            return

        os.makedirs(out_dir, exist_ok=True)
        nf = sum(1 for p in ordered if p["type"] == "forward")
        nr = sum(1 for p in ordered if p["type"] == "reverse")
        is_rev = self.chk_reverse.isChecked()
        base = os.path.splitext(os.path.basename(self.ed_irc.text()))[0] \
            if self.ed_irc.text() else "IRC"
        a_range = _fmt_ranges(sorted(frag))

        self._log(f"片段 A = 原子 {a_range}（{len(frag)} 个）；"
                  f"片段 B = 其余 {max(self.natm - len(frag), 0)} 个；"
                  f"对 {len(ordered)} 个结构点批量生成 → {out_dir}")
        written = 0
        for i, pt in enumerate(ordered):
            fidx = self._fidx(pt, nf, nr, is_rev)
            sub_a = [c for k, c in enumerate(pt["coords"]) if (k + 1) in frag]
            sub_b = [c for k, c in enumerate(pt["coords"]) if (k + 1) not in frag]
            if not sub_a or not sub_b:
                continue
            name_a = os.path.join(out_dir, f"{base}-{fidx:03d}-A.gjf")
            name_b = os.path.join(out_dir, f"{base}-{fidx:03d}-B.gjf")
            self._write_fragment_gjf(name_a, sub_a, fidx, base, cm_a, "A", a_range)
            self._write_fragment_gjf(name_b, sub_b, fidx, base, cm_b, "B", a_range)
            written += 2
            if (i + 1) % 10 == 0:
                self._log(f"  片段对 {i + 1}/{len(ordered)}")
        self._log(f"片段拆分完成：共 {written // 2} 对（{written} 个 gjf）")
        QMessageBox.information(self, "完成",
                                f"片段拆分完成：{written // 2} 对 → {out_dir}")

    def _write_fragment_gjf(self, filename, coords, idx, basename, cm, tag,
                            a_range=""):
        """写一个片段 gjf（沿用单点计算设置；电荷/多重度取该片段）。"""
        method = self.ed_method.text().strip()
        basis = self.ed_basis.text().strip()
        nproc = self.spin_nproc.value()
        mem = self.ed_mem.text().strip()
        add_kw = self.ed_kw.text().strip()
        charge, mult = cm

        lines = []
        chk = f"{basename}-{idx:03d}-{tag}.chk" if basename \
            else f"IRC{idx:04d}-{tag}.chk"
        lines.append(f"%chk={chk}")
        if mem:
            lines.append(f"%mem={mem}")
        if nproc:
            lines.append(f"%nprocshared={nproc}")
        route = f"# {method}/{basis}" if basis else f"# {method}"
        if add_kw:
            route += " " + add_kw
        lines.append(route)
        lines.append("")
        title = f"Fragment {tag} of IRC point {idx}"
        if a_range:
            title += f"  [fragment A atoms: {a_range}]"
        lines.append(title)
        lines.append("")
        lines.append(f"{charge} {mult}")
        for an, x, y, z in coords:
            elem = _ELEMENT_PAD[an] if 0 <= an < len(_ELEMENT_PAD) else f"{an}"
            lines.append(f"{elem:2s} {x:12.8f} {y:12.8f} {z:12.8f}")
        lines.append("")
        lines.append("")

        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def shutdown(self):
        """程序退出前保存设置（无后台线程，仅持久化）。"""
        try:
            self._save_settings()
        except Exception:
            pass
