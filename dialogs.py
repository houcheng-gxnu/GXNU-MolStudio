"""
dialogs: 弹窗对话框
提供 OrbitalBrowserDialog 轨道浏览器。
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from i18n import tr
from fchk_parser import parse_fchk_mo_info


class OrbitalBrowserDialog(QDialog):
    """弹窗：表格展示所有 MO，点击填入轨道编号。"""

    def __init__(self, fchk_path, parent=None):
        super().__init__(parent)
        self.fchk_path = fchk_path
        self.selected_orbital = None
        self._homo_row = None   # 打开后滚到表格中间的 HOMO 行
        self.setWindowTitle(tr("dlg_orbital_browser"))
        self.setMinimumSize(680, 500)
        self._setup_ui()
        self._parse_and_fill()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 体系信息
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("font-size:13px; color:#555; padding:4px;")
        layout.addWidget(self.lbl_info)

        # 提示
        self.lbl_hint = QLabel(tr("dlg_orbital_hint"))
        self.lbl_hint.setStyleSheet("font-size:12px; color:#888;")
        layout.addWidget(self.lbl_hint)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("dlg_orbital_col_idx"),
            tr("dlg_orbital_col_energy_au"),
            tr("dlg_orbital_col_energy_ev"),
            tr("dlg_orbital_col_occ"),
            tr("dlg_orbital_col_tag"),
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table, 1)

        # 按钮
        btn_row = QHBoxLayout()
        self.btn_fill = QPushButton(tr("dlg_btn_fill"))
        self.btn_fill.clicked.connect(self._on_fill)
        btn_row.addWidget(self.btn_fill)
        self.btn_close = QPushButton(tr("dlg_btn_close"))
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        # 样式
        self.setStyleSheet("""
            QDialog { background: #F5F6FA; }
            QTableWidget {
                background: #FFFFFF; alternate-background-color: #F8F9FB;
                border: 1px solid #E0E4E8; font-size: 12px;
            }
            QTableWidget::item:selected { background: #3498DB; color: white; }
            QPushButton {
                background: #3498DB; color: white; border: none;
                border-radius: 4px; padding: 8px 20px; font-size: 13px;
            }
            QPushButton:hover { background: #2980B9; }
        """)

    def _parse_and_fill(self):
        try:
            info = parse_fchk_mo_info(self.fchk_path)
        except Exception as e:
            self.lbl_info.setText(f"解析失败: {e}")
            return

        n_a = info["n_alpha"]
        n_b = info["n_beta"]
        n_basis = info["n_basis"]
        homo = info["homo_idx"]
        lumo = info["lumo_idx"]
        self.lbl_info.setText(tr("dlg_orbital_sys_info",
                                 n_a=n_a, n_b=n_b, n_basis=n_basis,
                                 homo=homo, lumo=lumo if lumo else "N/A"))

        alpha_e = info["alpha_energies"]
        beta_e = info.get("beta_energies") or []
        is_open = info["is_open_shell"]
        eV = 27.211386

        if is_open:
            rows = []
            for i, e in enumerate(alpha_e, 1):
                occ = 1.0 if i <= n_a else 0.0
                tag = ""
                if i == n_a:
                    tag = "α-HOMO"
                elif i == n_a + 1:
                    tag = "α-LUMO"
                rows.append((i, e, e * eV, occ, tag, "α"))
            for i, e in enumerate(beta_e, 1):
                occ = 1.0 if i <= n_b else 0.0
                tag = ""
                if i == n_b:
                    tag = "β-HOMO"
                elif i == n_b + 1:
                    tag = "β-LUMO"
                rows.append((-i, e, e * eV, occ, tag, "β"))
            self._fill_rows(rows, is_open=True)
        else:
            rows = []
            for i, e in enumerate(alpha_e, 1):
                occ = 2.0 if i <= n_a else 0.0
                tag = ""
                if i == homo:
                    tag = "HOMO"
                elif i == lumo:
                    tag = "LUMO"
                rows.append((i, e, e * eV, occ, tag, "α"))
            self._fill_rows(rows, is_open=False)

        # 定位到 HOMO-LUMO：表格按能量升序填充，HOMO（第 homo 个轨道）
        # 在第 homo-1 行。滚动必须在布局完全就绪后做——构造期 viewport
        # 还没有真实尺寸，showEvent 时对话框仍会 resize，滚动会被冲掉
        #（打开时停在顶部的根因）。showEvent 里用 singleShot(0) 推迟到
        # 事件循环下一拍（布局/尺寸全部就绪）再滚，PositionAtCenter 让
        # HOMO 居中、LUMO（下一行）也在视口内，打开即见 HOMO-LUMO
        if homo and 1 <= homo <= self.table.rowCount():
            self._homo_row = homo - 1
            self.table.setCurrentCell(self._homo_row, 0)

    def showEvent(self, e):
        super().showEvent(e)
        # 布局就绪后把 HOMO 行滚到表格中间。触发点：0ms（下一拍）、
        # 150ms 兜底、resizeEvent——对话框打开后往往还有 resize，会把
        # 一次性的滚动冲掉，所以目标行不消费、多次幂等重滚；用户
        # 之后手动滚动时不再有触发点，不受影响
        QTimer.singleShot(0, self._scroll_to_homo)
        QTimer.singleShot(150, self._scroll_to_homo)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.isVisible() and self._homo_row is not None:
            QTimer.singleShot(0, self._scroll_to_homo)

    def _scroll_to_homo(self):
        """把 HOMO 行垂直居中（打开即见 HOMO-LUMO），可安全重复调用。"""
        r = self._homo_row
        if r is None or not self.isVisible():
            return
        it = self.table.item(r, 0)
        if it is None or self.table.viewport().height() <= 0:
            return
        self.table.selectRow(r)
        self.table.scrollToItem(it, QAbstractItemView.PositionAtCenter)

    def _fill_rows(self, rows, is_open):
        self.table.setRowCount(len(rows))
        for r, (orb, energy, ev, occ, tag, spin) in enumerate(rows):
            # 轨道编号
            it0 = QTableWidgetItem(str(orb))
            it0.setTextAlignment(Qt.AlignCenter)
            if is_open and spin == "β":
                it0.setForeground(QColor("#E74C3C"))
            self.table.setItem(r, 0, it0)
            # 能量 a.u.
            it1 = QTableWidgetItem(f"{energy:.6f}")
            it1.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 1, it1)
            # 能量 eV
            it2 = QTableWidgetItem(f"{ev:.4f}")
            it2.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 2, it2)
            # 占据
            it3 = QTableWidgetItem(f"{occ:.1f}")
            it3.setTextAlignment(Qt.AlignCenter)
            if occ > 0:
                it3.setBackground(QColor("#E8F5E9"))
            self.table.setItem(r, 3, it3)
            # 标记
            it4 = QTableWidgetItem(tag)
            it4.setTextAlignment(Qt.AlignCenter)
            if "HOMO" in tag:
                it4.setBackground(QColor("#FFF3E0"))
                it4.setFont(QFont("", -1, QFont.Bold))
            elif "LUMO" in tag:
                it4.setBackground(QColor("#E3F2FD"))
                it4.setFont(QFont("", -1, QFont.Bold))
            self.table.setItem(r, 4, it4)

    def _on_double_click(self, row, _col):
        it = self.table.item(row, 0)
        if it:
            self.selected_orbital = it.text().strip()
            self.accept()

    def _on_fill(self):
        row = self.table.currentRow()
        if row >= 0:
            it = self.table.item(row, 0)
            if it:
                self.selected_orbital = it.text().strip()
                self.accept()
