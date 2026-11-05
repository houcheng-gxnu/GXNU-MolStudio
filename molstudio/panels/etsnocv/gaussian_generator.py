# -*- coding: utf-8 -*-
"""
Gaussian Input File Generator — for ETS-NOCV fragment definition and gjf generation.
Standalone widget: load molecular structure, define fragments via click/box-select,
generate Gaussian gjf input files for the whole molecule and each fragment.
"""

import os
try:
    from rdkit import Chem
    from rdkit.Chem import AllChem
    HAS_RDKIT = True
except ImportError:
    HAS_RDKIT = False
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QMessageBox, QFrame, QGroupBox, QListWidget, QProgressBar,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices

from molstudio.panels.etsnocv.config import LIGHT_QSS
from molstudio.panels.etsnocv.molcanvas import MolCanvas, get_atoms_from_any, get_bonds_from_fchk as calc_bonds
from molstudio.panels.etsnocv.locale import get_locale
from molstudio.panels.etsnocv.local_jobs import (
    LocalETSCancelled,
    prepare_ets_jobs,
    run_ets_jobs,
    write_gaussian_input,
)
from molstudio.core.gaussian_run import find_formchk, find_gaussian


class SciFiGroupBox(QGroupBox):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)


class LocalETSWorker(QThread):
    """Run three Gaussian jobs and formchk conversions off the UI thread."""

    log = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, jobs, g16_exe, formchk_exe, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.g16_exe = g16_exe
        self.formchk_exe = formchk_exe
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def is_cancel_requested(self):
        return self._cancel_requested

    def run(self):
        try:
            result = run_ets_jobs(
                self.jobs, self.g16_exe, self.formchk_exe,
                on_log=self.log.emit, cancel=self.is_cancel_requested)
            self.completed.emit(result)
        except LocalETSCancelled:
            self.failed.emit("本机计算已停止。")
        except Exception as exc:  # noqa: BLE001 - surfaced in the dialog
            self.failed.emit(str(exc))


class GjfGeneratorWidget(QWidget):
    """Gaussian gjf input file generator with 3D fragment editor."""

    last_dir_changed = pyqtSignal(str)
    local_analysis_ready = pyqtSignal(object)

    def __init__(self, L=None, last_dir="", get_g16=None, log_func=None):
        super().__init__()
        self.L = L if L is not None else get_locale("zh")
        self._last_dir = last_dir if last_dir else os.path.expanduser("~")
        self._get_g16 = get_g16 or (lambda: "")
        self._log_func = log_func

        # Gen state
        self._gen_atoms = []
        self._gen_bonds = []
        self._gen_fragments = []  # list of {name, charge, multiplicity, atoms: set}
        self._gen_sel_frag = -1
        self._last_generated_jobs = []
        self._local_worker = None

        self._build_ui()

    def _build_ui(self):
        L = self.L
        page_layout = QHBoxLayout(self)
        page_layout.setContentsMargins(16, 12, 16, 12)
        page_layout.setSpacing(12)

        # ── Left panel: controls ──
        left_panel = QWidget()
        left_panel.setFixedWidth(400)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Input file card
        input_card = SciFiGroupBox(L["card_input_frag"])
        ic_layout = QGridLayout(input_card)
        ic_layout.setContentsMargins(10, 10, 10, 10)
        ic_layout.setSpacing(6)

        ic_layout.addWidget(QLabel(L["lbl_input_file"]), 0, 0)
        self.gen_input_path = QLineEdit()
        self.gen_input_path.setPlaceholderText(L["frag_placeholder_input"])
        self.gen_input_path.setReadOnly(True)
        ic_layout.addWidget(self.gen_input_path, 0, 1)
        btn_browse_input = QPushButton(L["btn_browse"])
        btn_browse_input.clicked.connect(self._browse_input)
        ic_layout.addWidget(btn_browse_input, 0, 2)

        ic_layout.addWidget(QLabel(L["lbl_output_dir"]), 1, 0)
        self.gen_output_dir = QLineEdit()
        self.gen_output_dir.setPlaceholderText(L["frag_placeholder_output"])
        self.gen_output_dir.setReadOnly(True)
        ic_layout.addWidget(self.gen_output_dir, 1, 1)
        btn_browse_out = QPushButton(L["btn_browse"])
        btn_browse_out.clicked.connect(self._browse_output)
        ic_layout.addWidget(btn_browse_out, 1, 2)
        self.btn_open_output = QPushButton(L.get(
            "btn_open_output_dir", "打开输出目录"))
        self.btn_open_output.setToolTip(L.get(
            "btn_open_output_tip", "在文件资源管理器中打开输出目录"))
        self.btn_open_output.clicked.connect(self._open_output_dir)
        ic_layout.addWidget(self.btn_open_output, 2, 1, 1, 2)

        left_layout.addWidget(input_card)

        # SMILES card
        smiles_card = SciFiGroupBox(L["card_smiles"])
        sm_layout = QGridLayout(smiles_card)
        sm_layout.setContentsMargins(10, 10, 10, 10)
        sm_layout.setSpacing(6)

        sm_layout.addWidget(QLabel(L["lbl_smiles"]), 0, 0)
        self.gen_smiles_input = QLineEdit()
        self.gen_smiles_input.setPlaceholderText(L["frag_placeholder_smiles"])
        self.gen_smiles_input.returnPressed.connect(self._convert_smiles)
        sm_layout.addWidget(self.gen_smiles_input, 0, 1)
        btn_smiles = QPushButton(L["btn_convert_smiles"])
        btn_smiles.clicked.connect(self._convert_smiles)
        sm_layout.addWidget(btn_smiles, 0, 2)

        left_layout.addWidget(smiles_card)

        # Calculation settings card
        calc_card = SciFiGroupBox(L["card_frag_settings"])
        cc_layout = QGridLayout(calc_card)
        cc_layout.setContentsMargins(10, 10, 10, 10)
        cc_layout.setSpacing(6)

        cc_layout.addWidget(QLabel(L["lbl_method"]), 0, 0)
        self.gen_method = QLineEdit("m06l/def2svp")
        self.gen_method.setPlaceholderText(L["frag_placeholder_method"])
        cc_layout.addWidget(self.gen_method, 0, 1)

        cc_layout.addWidget(QLabel(L["lbl_sys_charge"]), 1, 0)
        self.gen_sys_charge = QLineEdit("0")
        cc_layout.addWidget(self.gen_sys_charge, 1, 1)

        cc_layout.addWidget(QLabel(L["lbl_sys_multiplicity"]), 2, 0)
        self.gen_sys_multiplicity = QLineEdit("1")
        cc_layout.addWidget(self.gen_sys_multiplicity, 2, 1)

        left_layout.addWidget(calc_card)

        # Fragment management card
        frag_card = SciFiGroupBox(L["card_frag_manage"])
        fc_layout = QVBoxLayout(frag_card)
        fc_layout.setContentsMargins(10, 10, 10, 10)
        fc_layout.setSpacing(4)

        self.gen_frag_list = QListWidget()
        self.gen_frag_list.currentRowChanged.connect(self._on_frag_select)
        fc_layout.addWidget(self.gen_frag_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        btn_add = QPushButton(L["btn_add_frag"])
        btn_add.clicked.connect(self._add_fragment)
        btn_row.addWidget(btn_add)
        btn_del = QPushButton(L["btn_del_frag"])
        btn_del.clicked.connect(self._del_fragment)
        btn_row.addWidget(btn_del)
        btn_auto = QPushButton(L["btn_auto_frag"])
        btn_auto.clicked.connect(self._auto_complete)
        btn_row.addWidget(btn_auto)
        fc_layout.addLayout(btn_row)

        # Fragment charge / multiplicity
        prop_layout = QGridLayout()
        prop_layout.setSpacing(4)
        prop_layout.addWidget(QLabel(L["lbl_frag_charge"]), 0, 0)
        self.gen_frag_charge = QLineEdit("0")
        prop_layout.addWidget(self.gen_frag_charge, 0, 1)
        prop_layout.addWidget(QLabel(L["lbl_frag_multiplicity"]), 0, 2)
        self.gen_frag_multiplicity = QLineEdit("1")
        prop_layout.addWidget(self.gen_frag_multiplicity, 0, 3)
        btn_apply = QPushButton(L["btn_apply_frag"])
        btn_apply.clicked.connect(self._apply_frag)
        prop_layout.addWidget(btn_apply, 0, 4)
        fc_layout.addLayout(prop_layout)

        # Atom list
        al_row = QHBoxLayout()
        al_row.setSpacing(4)
        al_row.addWidget(QLabel(L["lbl_frag_atom_list"]))
        self.gen_atom_entry = QLineEdit()
        self.gen_atom_entry.setPlaceholderText(L["frag_placeholder_atom_list"])
        al_row.addWidget(self.gen_atom_entry)
        btn_clear = QPushButton(L["btn_clear_atoms"])
        btn_clear.clicked.connect(self._clear_frag_atoms)
        al_row.addWidget(btn_clear)
        fc_layout.addLayout(al_row)

        left_layout.addWidget(frag_card)

        # Action buttons
        btn_bottom = QHBoxLayout()
        btn_bottom.setSpacing(6)
        btn_gen = QPushButton(L["btn_gen_gjf"])
        btn_gen.clicked.connect(self._generate_all)
        btn_gen.setObjectName("PrimaryBtn")
        btn_bottom.addWidget(btn_gen)
        btn_clr = QPushButton(L["btn_clear_all"])
        btn_clr.clicked.connect(self._clear_all)
        btn_bottom.addWidget(btn_clr)
        left_layout.addLayout(btn_bottom)

        run_row = QHBoxLayout()
        run_row.setSpacing(6)
        self.btn_run_local = QPushButton(L.get(
            "btn_run_local", "本机运行 3 个任务并分析"))
        self.btn_run_local.setObjectName("PrimaryBtn")
        self.btn_run_local.setToolTip(L.get(
            "btn_run_local_tip",
            "依次运行复合物、碎片 1、碎片 2；formchk 后自动载入 ETS-NOCV。"))
        self.btn_run_local.clicked.connect(self._run_local_workflow)
        run_row.addWidget(self.btn_run_local, 1)
        self.btn_stop_local = QPushButton(L.get("btn_stop_local", "停止"))
        self.btn_stop_local.setEnabled(False)
        self.btn_stop_local.clicked.connect(self._stop_local_workflow)
        run_row.addWidget(self.btn_stop_local)
        left_layout.addLayout(run_row)

        self.gen_local_progress = QProgressBar()
        self.gen_local_progress.setRange(0, 3)
        self.gen_local_progress.setValue(0)
        self.gen_local_progress.setTextVisible(False)
        self.gen_local_progress.hide()
        left_layout.addWidget(self.gen_local_progress)
        self.gen_status = QLabel("")
        self.gen_status.setObjectName("HintLabel")
        self.gen_status.setWordWrap(True)
        left_layout.addWidget(self.gen_status)
        left_layout.addStretch()

        page_layout.addWidget(left_panel)

        # ── Right panel: MolCanvas ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        canvas_frame = QFrame()
        canvas_frame.setObjectName("CanvasFrame")
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.gen_canvas = MolCanvas()
        self.gen_canvas.atom_clicked.connect(self._on_atom_click)
        self.gen_canvas.box_selected.connect(self._on_box_select)
        canvas_layout.addWidget(self.gen_canvas)
        right_layout.addWidget(canvas_frame, stretch=1)

        # Hint bar
        hint_label = QLabel(L["frag_hint"])
        hint_label.setObjectName("HintLabel")
        hint_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(hint_label)

        page_layout.addWidget(right_panel, stretch=1)

    # ── Callbacks ────────────────────────────────────────

    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load molecular structure",
            self._last_dir,
            "Molecule files (*.xyz *.gjf *.com *.log *.out);;All (*.*)")
        if path:
            self._last_dir = os.path.dirname(path)
            self.last_dir_changed.emit(self._last_dir)
            self.gen_input_path.setText(path)
            try:
                atoms = get_atoms_from_any(path)
            except Exception as exc:  # noqa: BLE001 - malformed user input
                QMessageBox.warning(
                    self, "Error",
                    "%s\n\n%s" % (self.L["frag_warn_parse_fail"], exc))
                return
            if not atoms:
                QMessageBox.warning(self, "Error", self.L["frag_warn_parse_fail"])
                return
            bonds = calc_bonds(atoms)
            self._gen_atoms = atoms
            self._gen_bonds = bonds
            self._gen_fragments = []
            self._gen_sel_frag = -1
            self.gen_canvas.set_data(atoms, bonds)
            self._add_fragment()
            self._add_fragment()
            self.gen_frag_list.setCurrentRow(0)
            if not self.gen_output_dir.text().strip():
                stem = os.path.splitext(os.path.basename(path))[0] or "molecule"
                self.gen_output_dir.setText(
                    os.path.join(os.path.dirname(path), stem + "_ETS_NOCV"))
            self.gen_status.setText(
                "已载入 %d 个原子。请把全部原子分配给两个片段，再生成或运行。"
                % len(atoms))

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select output directory", "")
        if path:
            self.gen_output_dir.setText(path)

    def _open_output_dir(self):
        path = self.gen_output_dir.text().strip()
        if not path:
            QMessageBox.information(
                self, "ETS-NOCV",
                self.L.get("frag_warn_no_output", "请先选择输出目录。"))
            return
        try:
            os.makedirs(path, exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except OSError as exc:
            QMessageBox.warning(self, "ETS-NOCV", str(exc))
            return
        if not opened:
            QMessageBox.warning(
                self, "ETS-NOCV",
                "无法打开输出目录：\n%s" % path)

    def _convert_smiles(self):
        if not HAS_RDKIT:
            QMessageBox.warning(self, "Error", self.L["frag_warn_rdkit"])
            return
        smiles = self.gen_smiles_input.text().strip()
        if not smiles:
            return
        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                raise ValueError("Invalid SMILES")
            mol_h = Chem.AddHs(mol)
            status = AllChem.EmbedMolecule(mol_h, AllChem.ETKDGv3())
            if status != 0:
                raise ValueError("Embedding failed")
            AllChem.MMFFOptimizeMolecule(mol_h)
            conf = mol_h.GetConformer()
            atoms = []
            for i, atom in enumerate(mol_h.GetAtoms()):
                pos = conf.GetAtomPosition(i)
                atoms.append((i + 1, atom.GetSymbol(), atom.GetAtomicNum(),
                              (pos.x, pos.y, pos.z)))
            bonds = calc_bonds(atoms)
            self._gen_atoms = atoms
            self._gen_bonds = bonds
            self._gen_fragments = []
            self._gen_sel_frag = -1
            self.gen_input_path.clear()
            self.gen_canvas.set_data(atoms, bonds)
            self._add_fragment()
            self._add_fragment()
            self.gen_frag_list.setCurrentRow(0)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"{self.L['frag_warn_smiles_fail']}\n{str(e)}")

    def _refresh_frag_list(self):
        self.gen_frag_list.blockSignals(True)
        self.gen_frag_list.clear()
        for i, frag in enumerate(self._gen_fragments):
            q = frag['charge']
            m = frag['multiplicity']
            n = len(frag['atoms'])
            self.gen_frag_list.addItem(f"{frag['name']}: chg={q} mult={m} atoms={n}")
        self.gen_frag_list.blockSignals(False)
        if 0 <= self._gen_sel_frag < len(self._gen_fragments):
            self.gen_frag_list.setCurrentRow(self._gen_sel_frag)
        self._update_canvas_frags()

    def _update_canvas_frags(self):
        frag_atoms = {}
        for i, frag in enumerate(self._gen_fragments):
            frag_atoms[i] = frag['atoms']
        self.gen_canvas.fragment_atoms = frag_atoms
        self.gen_canvas.repaint()

    def _add_fragment(self):
        if len(self._gen_fragments) >= 2:
            QMessageBox.information(
                self, "ETS-NOCV", "ETS-NOCV 只需要两个片段。")
            return
        idx = len(self._gen_fragments) + 1
        self._gen_fragments.append({
            'name': f'Fragment{idx}',
            'charge': 0,
            'multiplicity': 1,
            'atoms': set(),
        })
        self._gen_sel_frag = idx - 1
        self._refresh_frag_list()
        self._update_frag_ui()

    def _del_fragment(self):
        if self._gen_sel_frag < 0 or len(self._gen_fragments) <= 1:
            QMessageBox.warning(self, "Warning", "At least one fragment required.")
            return
        del self._gen_fragments[self._gen_sel_frag]
        self._gen_sel_frag = max(0, self._gen_sel_frag - 1)
        self._refresh_frag_list()
        self._update_frag_ui()

    def _auto_complete(self):
        if not self._gen_atoms:
            QMessageBox.warning(self, "Warning", self.L["frag_warn_no_atoms"])
            return
        all_atoms = set(range(1, len(self._gen_atoms) + 1))
        used = set()
        for frag in self._gen_fragments:
            used.update(frag['atoms'])
        remaining = all_atoms - used
        if not remaining:
            QMessageBox.information(self, self.L["frag_auto_title"], "All atoms already assigned.")
            return
        if len(self._gen_fragments) == 2:
            target = self._gen_sel_frag
            if target < 0 or self._gen_fragments[target]['atoms']:
                empty = [i for i, frag in enumerate(self._gen_fragments)
                         if not frag['atoms']]
                if not empty:
                    QMessageBox.warning(
                        self, self.L["frag_auto_title"],
                        "两片段都已有原子，无法自动补全。")
                    return
                target = empty[0]
            self._gen_fragments[target]['atoms'].update(remaining)
            self._gen_sel_frag = target
            self._refresh_frag_list()
            self._update_frag_ui()
            return
        reply = QMessageBox.question(
            self, self.L["frag_auto_title"],
            f"Used {len(used)} atoms, {len(remaining)} unassigned.\n"
            f"{self.L['frag_auto_confirm']}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            idx = len(self._gen_fragments) + 1
            self._gen_fragments.append({
                'name': f'Fragment{idx}',
                'charge': 0, 'multiplicity': 1,
                'atoms': remaining,
            })
            self._gen_sel_frag = idx - 1
            self._refresh_frag_list()
            self._update_frag_ui()

    def _on_frag_select(self, idx):
        if idx < 0:
            return
        self._gen_sel_frag = idx
        self._update_frag_ui()

    def _update_frag_ui(self):
        if self._gen_sel_frag < 0 or self._gen_sel_frag >= len(self._gen_fragments):
            return
        frag = self._gen_fragments[self._gen_sel_frag]
        self.gen_frag_charge.setText(str(frag['charge']))
        self.gen_frag_multiplicity.setText(str(frag['multiplicity']))
        atoms = frag['atoms']
        self.gen_atom_entry.setText(', '.join(str(a) for a in sorted(atoms)))

    def _apply_frag(self):
        if self._gen_sel_frag < 0:
            QMessageBox.warning(self, "Warning", self.L["frag_warn_no_selection"])
            return
        try:
            frag = self._gen_fragments[self._gen_sel_frag]
            frag['charge'] = int(self.gen_frag_charge.text())
            frag['multiplicity'] = int(self.gen_frag_multiplicity.text())
            atoms = self._parse_atom_ids(self.gen_atom_entry.text())
            valid = {atom[0] for atom in self._gen_atoms}
            invalid = atoms - valid
            if invalid:
                raise ValueError("无效原子序号：%s" % ", ".join(map(str, sorted(invalid))))
            for i, other in enumerate(self._gen_fragments):
                if i != self._gen_sel_frag:
                    other['atoms'].difference_update(atoms)
            frag['atoms'] = atoms
            self._refresh_frag_list()
            self._update_frag_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "Warning", str(exc))

    @staticmethod
    def _parse_atom_ids(text):
        result = set()
        for token in text.replace("，", ",").replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                start, end = token.split("-", 1)
                start, end = int(start), int(end)
                if start > end:
                    start, end = end, start
                result.update(range(start, end + 1))
            else:
                result.add(int(token))
        return result

    def _clear_frag_atoms(self):
        if self._gen_sel_frag < 0:
            return
        self._gen_fragments[self._gen_sel_frag]['atoms'] = set()
        self._refresh_frag_list()
        self.gen_atom_entry.clear()

    def _on_atom_click(self, atom_idx):
        if self._gen_sel_frag < 0 or not self._gen_fragments:
            return
        frag = self._gen_fragments[self._gen_sel_frag]
        if atom_idx in frag['atoms']:
            frag['atoms'].remove(atom_idx)
        else:
            for i, other in enumerate(self._gen_fragments):
                if i != self._gen_sel_frag:
                    other['atoms'].discard(atom_idx)
            frag['atoms'].add(atom_idx)
        self._refresh_frag_list()
        self._update_frag_ui()

    def _on_box_select(self, atom_indices):
        if self._gen_sel_frag < 0 or not self._gen_fragments:
            return
        frag = self._gen_fragments[self._gen_sel_frag]
        for idx in atom_indices:
            if idx not in frag['atoms']:
                for i, other in enumerate(self._gen_fragments):
                    if i != self._gen_sel_frag:
                        other['atoms'].discard(idx)
                frag['atoms'].add(idx)
        self._refresh_frag_list()
        self._update_frag_ui()

    def _prepare_jobs_from_ui(self):
        if not self._gen_atoms:
            QMessageBox.warning(self, "Warning", self.L["frag_warn_no_atoms"])
            return None
        if len(self._gen_fragments) != 2:
            QMessageBox.warning(
                self, "Warning",
                "ETS-NOCV 需要恰好两个片段（当前 %d 个）。" %
                len(self._gen_fragments))
            return None
        out_dir = self.gen_output_dir.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Warning", "Please select an output directory.")
            return None
        try:
            charge = int(self.gen_sys_charge.text().strip())
            mult = int(self.gen_sys_multiplicity.text().strip())
            for fragment in self._gen_fragments:
                fragment["charge"] = int(fragment.get("charge", 0))
                fragment["multiplicity"] = int(fragment.get("multiplicity", 1))
            method = self.gen_method.text().strip() or "M06L/def2SVP"
            name = os.path.splitext(
                os.path.basename(self.gen_input_path.text()))[0] or "molecule"
            jobs = prepare_ets_jobs(
                self._gen_atoms, self._gen_fragments, out_dir, name, method,
                charge, mult)
        except (TypeError, ValueError, OSError) as exc:
            QMessageBox.warning(
                self, "ETS-NOCV", "无法生成输入文件：\n%s" % exc)
            return None
        self._last_generated_jobs = jobs
        return jobs

    def _generate_all(self):
        jobs = self._prepare_jobs_from_ui()
        if not jobs:
            return
        QMessageBox.information(
            self, "Success",
            "已生成 3 个 Gaussian 输入文件：\n\n" +
            "\n".join(os.path.basename(job["gjf"]) for job in jobs) +
            "\n\n复合物中的碎片坐标保持连续，并已写入 nosymm。")

    def _write_gjf(self, atoms, path, method, charge, multiplicity):
        write_gaussian_input(atoms, path, method, charge, multiplicity)

    def _append_log(self, message):
        if self._log_func:
            try:
                self._log_func(message + "\n")
            except Exception:  # noqa: BLE001 - logging must never block a job
                pass

    def _run_local_workflow(self):
        if self._local_worker is not None and self._local_worker.isRunning():
            return
        jobs = self._prepare_jobs_from_ui()
        if not jobs:
            return
        g16 = (self._get_g16() or find_gaussian()).strip()
        if not g16 or not os.path.isfile(g16):
            QMessageBox.warning(
                self, "Gaussian",
                "没有找到 g16.exe。请先在主窗口 ⚙️ 路径设置中配置。")
            return
        formchk = find_formchk(g16)
        if not formchk:
            QMessageBox.warning(
                self, "Gaussian",
                "没有找到 formchk.exe，它应与 g16.exe 位于同一目录。")
            return

        self._local_worker = LocalETSWorker(jobs, g16, formchk, self)
        self._local_worker.log.connect(self._on_local_log)
        self._local_worker.completed.connect(self._on_local_completed)
        self._local_worker.failed.connect(self._on_local_failed)
        self.gen_local_progress.setValue(0)
        self.gen_local_progress.show()
        self.gen_status.setText("准备运行 3 个 Gaussian 任务...")
        self._set_local_running(True)
        self._append_log("ETS-NOCV 本机流程：3 个 Gaussian 任务开始")
        self._local_worker.start()

    def _set_local_running(self, running):
        self.btn_run_local.setEnabled(not running)
        self.btn_stop_local.setEnabled(running)
        self.gen_frag_list.setEnabled(not running)

    def _on_local_log(self, message):
        self._append_log(message)
        stripped = message.strip()
        if stripped.startswith("=== [") and "/3]" in stripped:
            try:
                index = int(stripped.split("[", 1)[1].split("/", 1)[0])
                self.gen_local_progress.setValue(max(0, index - 1))
            except (ValueError, IndexError):
                pass
        if stripped:
            self.gen_status.setText(stripped[:180])

    def _on_local_completed(self, result):
        self._set_local_running(False)
        self.gen_local_progress.setValue(3)
        self.gen_status.setText("3 个任务及 formchk 已完成，正在载入 ETS-NOCV 分析。")
        self._append_log("ETS-NOCV 本机流程完成，3 个 .fch 已生成")
        self.local_analysis_ready.emit(result)

    def _on_local_failed(self, message):
        self._set_local_running(False)
        self.gen_local_progress.setValue(0)
        self.gen_status.setText(message.splitlines()[0][:180] if message else "计算失败")
        self._append_log("ETS-NOCV 本机流程失败：" + message)
        QMessageBox.warning(self, "Gaussian / formchk", message)

    def _stop_local_workflow(self):
        if self._local_worker is not None and self._local_worker.isRunning():
            self.btn_stop_local.setEnabled(False)
            self.gen_status.setText("正在停止当前 Gaussian 任务...")
            self._local_worker.request_cancel()

    def shutdown(self):
        """Cancel and join a running local job before the dialog is destroyed."""
        worker = self._local_worker
        if worker is not None and worker.isRunning():
            worker.request_cancel()
            worker.wait(15000)

    def _clear_all(self):
        if self._local_worker is not None and self._local_worker.isRunning():
            QMessageBox.information(self, "ETS-NOCV", "本机任务运行中，请先停止。")
            return
        self._gen_atoms = []
        self._gen_bonds = []
        self._gen_fragments = []
        self._gen_sel_frag = -1
        self.gen_input_path.clear()
        self.gen_output_dir.clear()
        self.gen_frag_list.clear()
        self.gen_atom_entry.clear()
        self.gen_frag_charge.setText("0")
        self.gen_frag_multiplicity.setText("1")
        self.gen_canvas.fragment_atoms = {}
        self.gen_canvas.set_data([], [])
        self.gen_status.clear()
        self.gen_local_progress.hide()
