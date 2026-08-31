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
    QMessageBox, QFrame, QGroupBox, QListWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal

from etsnocv.config import LIGHT_QSS
from etsnocv.molcanvas import MolCanvas, get_atoms_from_any, get_bonds_from_fchk as calc_bonds
from etsnocv.locale import get_locale


class SciFiGroupBox(QGroupBox):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)


class GjfGeneratorWidget(QWidget):
    """Gaussian gjf input file generator with 3D fragment editor."""

    last_dir_changed = pyqtSignal(str)

    def __init__(self, L=None, last_dir=""):
        super().__init__()
        self.L = L if L is not None else get_locale("zh")
        self._last_dir = last_dir if last_dir else os.path.expanduser("~")

        # Gen state
        self._gen_atoms = []
        self._gen_bonds = []
        self._gen_fragments = []  # list of {name, charge, multiplicity, atoms: set}
        self._gen_sel_frag = -1

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
            self._last_dir, "Molecule files (*.xyz *.gjf *.com *.log);;All (*.*)")
        if path:
            self._last_dir = os.path.dirname(path)
            self.last_dir_changed.emit(self._last_dir)
            self.gen_input_path.setText(path)
            atoms = get_atoms_from_any(path)
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

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select output directory", "")
        if path:
            self.gen_output_dir.setText(path)

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
            self._refresh_frag_list()
        except ValueError:
            pass

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
            frag['atoms'].add(atom_idx)
        self._refresh_frag_list()
        self._update_frag_ui()

    def _on_box_select(self, atom_indices):
        if self._gen_sel_frag < 0 or not self._gen_fragments:
            return
        frag = self._gen_fragments[self._gen_sel_frag]
        for idx in atom_indices:
            if idx not in frag['atoms']:
                frag['atoms'].add(idx)
        self._refresh_frag_list()
        self._update_frag_ui()

    def _generate_all(self):
        if not self._gen_atoms:
            QMessageBox.warning(self, "Warning", self.L["frag_warn_no_atoms"])
            return
        if len(self._gen_fragments) < 2:
            QMessageBox.warning(self, "Warning", self.L["frag_warn_no_frags"])
            return
        out_dir = self.gen_output_dir.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Warning", "Please select an output directory.")
            return
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        method = self.gen_method.text().strip()
        charge = self.gen_sys_charge.text().strip()
        mult = self.gen_sys_multiplicity.text().strip()
        name = os.path.splitext(os.path.basename(self.gen_input_path.text()))[0] or "molecule"

        # Build reordered whole molecule
        atom_map = {a[0]: a for a in self._gen_atoms}
        all_set = set(atom_map.keys())
        used_set = set()
        for f in self._gen_fragments:
            used_set.update(f['atoms'])
        ordered = []
        for f in self._gen_fragments:
            for a_idx in sorted(f['atoms']):
                if a_idx in atom_map:
                    ordered.append(atom_map[a_idx])
        for a_idx in sorted(all_set - used_set):
            if a_idx in atom_map:
                ordered.append(atom_map[a_idx])

        self._write_gjf(ordered, os.path.join(out_dir, f"{name}.gjf"), method, charge, mult)
        for f in self._gen_fragments:
            f_atoms = [atom_map[a] for a in sorted(f['atoms']) if a in atom_map]
            self._write_gjf(f_atoms, os.path.join(out_dir, f"{f['name']}.gjf"),
                            method, str(f['charge']), str(f['multiplicity']))
        QMessageBox.information(self, "Success",
            self.L["frag_gen_success"].format(n=len(self._gen_fragments) + 1))

    def _write_gjf(self, atoms, path, method, charge, multiplicity):
        chk_name = os.path.basename(path).replace('.gjf', '.chk')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"%nprocshared=24\n%mem=10GB\n%chk={chk_name}\n")
            f.write(f"#P {method} nosymm\n\n")
            f.write(f"{os.path.basename(path).replace('.gjf', '')}\n\n")
            f.write(f"{charge} {multiplicity}\n")
            for _, sym, _, (x, y, z) in atoms:
                f.write(f" {sym:2s}  {x:14.8f}  {y:14.8f}  {z:14.8f}\n")
            f.write(f"\n")

    def _clear_all(self):
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
