# -*- coding: utf-8 -*-
"""
表面距离投影图面板（Multiwfn 主功能 300 → 子功能 8）。

布局按使用习惯分上下两块：

  * 上：出图区（matplotlib 画布，随窗口缩放）；
  * 下：参数设置。

朝向来自**左侧 OpenGL 画布**：用户在画布上把分子转到想要的朝向，
点「绘制投影图」，面板就读画布相机的旋转量，把它烘焙进坐标再交给
Multiwfn。所以这里的图和你看到的样子是同一朝向。

计算全部由 Multiwfn 完成（见 ``molstudio.core.surface_projection``），
本面板只负责取朝向、传参数、显示结果。
"""

from __future__ import annotations

import os
import tempfile
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from molstudio.core import surface_projection as sp


_TR = {
    "zh": {
        "grp_view": "表面距离投影图",
        "grp_params": "参数设置",
        "hint_empty": "左侧画布还没有分子。\n先打开一个 xyz / gjf / log 文件，"
                      "再把朝向转到想要的方向。",
        "hint_ready": "在左侧画布把分子转到想要的朝向，然后点「绘制投影图」。",
        "out_dir": "输出目录",
        "browse": "浏览…",
        "surface": "表面定义",
        "surf_promol": "准分子密度等值面（推荐）",
        "surf_wfn": "真实波函数密度等值面",
        "surf_vdw": "范德华球叠加",
        "iso": "等值面 (a.u.)",
        "grid": "网格数（每边）",
        "grid_tip": "每边网格数；越大细节越多、Multiwfn 越慢。\n"
                    "出图会自动做双三次插值，300 通常已经足够光滑。",
        "cmap": "配色方案",
        "cmap_tip": "色带/等高线图的配色方案（只影响显示，不改数值）",
        "show_atoms": "显示分子结构",
        "raise": "扫描起点抬高 (Å)",
        "bg": "背景色",
        "void": "轮廓外留白",
        "void_tip": "分子轮廓之外扫不到表面，Multiwfn 会记成全图最小值（最深的蓝）。\n"
                    "勾选则把这些区域留白；取消则按 Multiwfn 原样着色。",
        "draw": "绘制投影图",
        "save": "保存图片…",
        "busy": "正在调用 Multiwfn 计算…",
        "no_mw": "Multiwfn 路径未设置，请在主界面 ⚙️ 路径设置中配置",
        "no_mol": "左侧画布还没有分子结构",
        "no_rot": "读取不到画布朝向",
        "done": "完成：{nx}×{ny} 网格，值 {hi:.2f} … {lo:.2f}（Z' − Z_start，Å），"
                "用时 {t:.1f} s",
        "void_n": "其中 {n} 个格点扫不到表面（分子轮廓外），已留白",
        "saved": "已保存：{path}",
        "failed": "计算失败：{err}",
        "cancel": "已取消",
    },
    "en": {
        "grp_view": "Surface Distance Projection",
        "grp_params": "Parameters",
        "hint_empty": "No molecule on the canvas yet.\nOpen an xyz / gjf / log file "
                      "first, then rotate to the orientation you want.",
        "hint_ready": "Rotate the molecule on the left canvas, then click Draw.",
        "out_dir": "Output folder",
        "browse": "Browse…",
        "surface": "Surface definition",
        "surf_promol": "Promolecular density isosurface (recommended)",
        "surf_wfn": "Wavefunction density isosurface",
        "surf_vdw": "van der Waals spheres",
        "iso": "Isovalue (a.u.)",
        "grid": "Grid points (per axis)",
        "grid_tip": "Grid points per axis; higher = more detail but slower in "
                    "Multiwfn.\nThe plot is bicubic-interpolated, so 300 is "
                    "usually smooth enough.",
        "cmap": "Colormap",
        "cmap_tip": "Colormap for the filled map (display only, values unchanged)",
        "show_atoms": "Show molecular structure",
        "raise": "Raise scan start (Å)",
        "bg": "Background",
        "void": "Blank the outside",
        "void_tip": "Outside the molecular outline the scan never hits a surface, and "
                    "Multiwfn records the global minimum (deepest blue).\n"
                    "Tick to blank those cells; untick to colour them as Multiwfn does.",
        "draw": "Draw map",
        "save": "Save image…",
        "busy": "Running Multiwfn…",
        "no_mw": "Multiwfn path is not set — configure it in ⚙️ Path Settings",
        "no_mol": "No molecule on the canvas",
        "no_rot": "Cannot read the canvas orientation",
        "done": "Done: {nx}×{ny} grid, value {hi:.2f} … {lo:.2f} "
                "(Z' - Z_start, Angstrom), {t:.1f} s",
        "void_n": "{n} cells never hit a surface (outside the outline) — blanked",
        "saved": "Saved: {path}",
        "failed": "Failed: {err}",
        "cancel": "Cancelled",
    },
}


#: 投影图配色方案：(matplotlib 名称, 中文标签, 英文标签)
CMAP_OPTIONS = (
    ("jet", "Jet（经典）", "Jet (classic)"),
    ("turbo", "Turbo", "Turbo"),
    ("viridis", "Viridis", "Viridis"),
    ("plasma", "Plasma", "Plasma"),
    ("inferno", "Inferno", "Inferno"),
    ("magma", "Magma", "Magma"),
    ("cividis", "Cividis", "Cividis"),
    ("coolwarm", "Coolwarm（冷暖）", "Coolwarm"),
    ("RdBu_r", "RdBu（红蓝）", "RdBu (red-blue)"),
    ("RdYlBu_r", "RdYlBu（红黄蓝）", "RdYlBu (red-yellow-blue)"),
    ("Spectral_r", "Spectral（光谱）", "Spectral"),
    ("rainbow", "Rainbow（彩虹）", "Rainbow"),
    ("gist_rainbow", "Gist Rainbow", "Gist Rainbow"),
    ("twilight", "Twilight", "Twilight"),
)


class _MapCanvas(FigureCanvasQTAgg):
    """随控件尺寸缩放的 matplotlib 画布。

    matplotlib 的 Qt 画布**不会**自动跟随控件大小（figure 保持固定英寸尺寸），
    所以这里在 resize 时把 figure 尺寸同步过去，图才会铺满出图区。
    """

    def __init__(self, figure):
        super().__init__(figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(300)

    def resizeEvent(self, event):                                  # noqa: N802
        super().resizeEvent(event)
        w = max(self.width(), 60)
        h = max(self.height(), 60)
        dpi = float(self.figure.get_dpi()) or 100.0
        self.figure.set_size_inches(w / dpi, h / dpi, forward=False)
        self.draw_idle()


class SurfaceProjectionWorker(QThread):
    """后台跑 Multiwfn。主线程不阻塞，结果通过信号回传。"""

    done = pyqtSignal(dict)
    log = pyqtSignal(str)

    def __init__(self, symbols, coords, R, outdir, mw_exe, params, parent=None):
        super().__init__(parent)
        self._symbols = symbols
        self._coords = coords
        self._R = R
        self._outdir = outdir
        self._mw = mw_exe
        self._params = dict(params)

    def run(self):
        try:
            xs, ys, V, info = sp.project(
                self._symbols, self._coords, self._R, self._outdir, self._mw,
                on_log=self.log.emit, **self._params)
            self.done.emit({"ok": True, "xs": xs, "ys": ys, "V": V,
                            "info": info, "symbols": self._symbols})
        except Exception as exc:                                   # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc),
                            "traceback": traceback.format_exc()})


class SurfaceProjectionPanel(QWidget):
    """「表面距离投影图」页：上出图、下参数，朝向取自左侧画布。"""

    def __init__(self, glw=None, multiwfn_path="", get_multiwfn=None,
                 get_input_path=None, log_func=None, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path or ""
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        self._get_input = get_input_path or (lambda: "")
        self._log_func = log_func

        self._worker = None
        self._result = None          # (xs, ys, V, info)
        self._symbols = []
        self._n_void = 0
        self._v_lo = 0.0             # 实际使用的色标下限（<= 0）
        self._outdir_manual = ""

        self._build_ui()
        self._apply_lang()
        self._refresh_canvas_state()

    # ── i18n ──────────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        s = _TR.get(self.lang, _TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    def _apply_lang(self):
        self.grp_view.setTitle(self._t("grp_view"))
        self.grp_params.setTitle(self._t("grp_params"))
        self.lbl_outdir.setText(self._t("out_dir"))
        self.btn_outdir.setText(self._t("browse"))
        self.lbl_surface.setText(self._t("surface"))
        for i, key in enumerate(("surf_promol", "surf_wfn", "surf_vdw")):
            self.cmb_surface.setItemText(i, self._t(key))
        self.lbl_iso.setText(self._t("iso"))
        self.lbl_grid.setText(self._t("grid"))
        self.lbl_grid.setToolTip(self._t("grid_tip"))
        self.spn_grid.setToolTip(self._t("grid_tip"))
        self.lbl_cmap.setText(self._t("cmap"))
        self.lbl_cmap.setToolTip(self._t("cmap_tip"))
        self.cmb_cmap.setToolTip(self._t("cmap_tip"))
        for i, (_key, zh, en) in enumerate(CMAP_OPTIONS):
            self.cmb_cmap.setItemText(i, zh if self.lang == "zh" else en)
        self.lbl_raise.setText(self._t("raise"))
        self.lbl_bg.setText(self._t("bg"))
        self.chk_atoms.setText(self._t("show_atoms"))
        self.chk_void.setText(self._t("void"))
        self.chk_void.setToolTip(self._t("void_tip"))
        self.btn_draw.setText(self._t("draw"))
        self.btn_save.setText(self._t("save"))
        if self._result is None:
            self._set_hint(self._t("hint_empty") if self._canvas_empty()
                           else self._t("hint_ready"))

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 上：出图区
        self.grp_view = QGroupBox()
        gv = QVBoxLayout(self.grp_view)
        gv.setContentsMargins(6, 6, 6, 6)
        self.figure = Figure(figsize=(6.6, 4.6), dpi=100)
        self._canvas = _MapCanvas(self.figure)
        gv.addWidget(self._canvas, 1)
        root.addWidget(self.grp_view, 3)

        # 下：参数
        self.grp_params = QGroupBox()
        gp = QVBoxLayout(self.grp_params)
        gp.setSpacing(6)

        row = QHBoxLayout()
        self.lbl_outdir = QLabel()
        self.edit_outdir = QLineEdit()
        self.btn_outdir = QPushButton()
        self.btn_outdir.clicked.connect(self._pick_outdir)
        row.addWidget(self.lbl_outdir)
        row.addWidget(self.edit_outdir, 1)
        row.addWidget(self.btn_outdir)
        gp.addLayout(row)

        row2 = QHBoxLayout()
        self.lbl_surface = QLabel()
        self.cmb_surface = QComboBox()
        self.cmb_surface.addItems(["", "", ""])          # 文案由 _apply_lang 填
        self.cmb_surface.currentIndexChanged.connect(self._on_surface_changed)
        row2.addWidget(self.lbl_surface)
        row2.addWidget(self.cmb_surface, 1)
        gp.addLayout(row2)

        row3 = QHBoxLayout()
        self.lbl_iso = QLabel()
        self.spn_iso = QDoubleSpinBox()
        self.spn_iso.setDecimals(4)
        self.spn_iso.setRange(0.0001, 2.0)
        self.spn_iso.setSingleStep(0.005)
        self.spn_iso.setValue(0.05)
        self.lbl_grid = QLabel()
        self.spn_grid = QSpinBox()
        self.spn_grid.setRange(50, 1000)
        self.spn_grid.setSingleStep(50)
        self.spn_grid.setValue(300)
        row3.addWidget(self.lbl_iso)
        row3.addWidget(self.spn_iso)
        row3.addSpacing(12)
        row3.addWidget(self.lbl_grid)
        row3.addWidget(self.spn_grid)
        row3.addStretch(1)
        gp.addLayout(row3)

        row3b = QHBoxLayout()
        self.lbl_cmap = QLabel()
        self.cmb_cmap = QComboBox()
        for key, zh, _en in CMAP_OPTIONS:
            self.cmb_cmap.addItem(zh, key)
        self.cmb_cmap.setCurrentIndex(0)
        self.cmb_cmap.currentIndexChanged.connect(self._refresh_result)
        row3b.addWidget(self.lbl_cmap)
        row3b.addWidget(self.cmb_cmap, 1)
        gp.addLayout(row3b)

        row4 = QHBoxLayout()
        self.lbl_raise = QLabel()
        self.spn_raise = QDoubleSpinBox()
        self.spn_raise.setDecimals(2)
        self.spn_raise.setRange(0.0, 30.0)
        self.spn_raise.setSingleStep(0.5)
        self.spn_raise.setSuffix(" Å")
        self.lbl_bg = QLabel()
        self.btn_bg = QPushButton()
        self._bg = "#ffffff"
        self.btn_bg.clicked.connect(self._pick_bg)
        row4.addWidget(self.lbl_raise)
        row4.addWidget(self.spn_raise)
        row4.addSpacing(12)
        row4.addWidget(self.lbl_bg)
        row4.addWidget(self.btn_bg)
        row4.addStretch(1)
        gp.addLayout(row4)

        self.chk_atoms = QCheckBox()
        self.chk_atoms.setChecked(True)
        self.chk_atoms.toggled.connect(self._refresh_result)
        self.chk_void = QCheckBox()
        self.chk_void.setChecked(True)
        self.chk_void.toggled.connect(self._refresh_result)
        row_chk = QHBoxLayout()
        row_chk.addWidget(self.chk_atoms)
        row_chk.addWidget(self.chk_void)
        row_chk.addStretch(1)
        gp.addLayout(row_chk)

        row5 = QHBoxLayout()
        self.btn_draw = QPushButton()
        self.btn_draw.setDefault(True)
        self.btn_draw.clicked.connect(self.start)
        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self._save_image)
        self.btn_save.setEnabled(False)
        row5.addWidget(self.btn_draw, 2)
        row5.addWidget(self.btn_save, 1)
        gp.addLayout(row5)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        gp.addWidget(self.lbl_status)

        root.addWidget(self.grp_params, 2)
        self._sync_bg_button()

    # ── 状态 ──────────────────────────────────────────────────────────────
    def _canvas_empty(self) -> bool:
        mol = getattr(self.glw, "_molecule", None) if self.glw is not None else None
        return not mol

    def _refresh_canvas_state(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self._result is None:
            self._set_hint(self._t("hint_empty") if self._canvas_empty()
                           else self._t("hint_ready"))
        if not self.edit_outdir.text().strip():
            self.edit_outdir.setText(str(self._default_outdir()))

    def _set_hint(self, text):
        """出图区还没有内容时，用一行文字占位。"""
        self.lbl_status.setText(text)
        if self._result is None:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.set_axis_off()
            ax.text(0.5, 0.5, text, ha="center", va="center", wrap=True,
                    fontsize=10, color="#7a8595", transform=ax.transAxes)
            self._canvas.draw_idle()

    def _default_outdir(self) -> Path:
        src = self._get_input() or ""
        if src and os.path.isfile(src):
            return Path(src).parent / (Path(src).stem + "_sdm")
        return Path(tempfile.gettempdir()) / "MolStudio_surface_projection"

    def _outdir(self) -> Path:
        txt = self.edit_outdir.text().strip()
        return Path(txt) if txt else self._default_outdir()

    # ── 参数控件 ──────────────────────────────────────────────────────────
    def _on_surface_changed(self, idx):
        # 范德华球模式下 "等值面" 实际是半径缩放系数，给个合理默认
        if idx == 2:
            self.spn_iso.setRange(0.1, 2.0)
            self.spn_iso.setDecimals(2)
            self.spn_iso.setSingleStep(0.05)
            self.spn_iso.setValue(1.0)
        else:
            self.spn_iso.setRange(0.0001, 2.0)
            self.spn_iso.setDecimals(4)
            self.spn_iso.setSingleStep(0.005)
            if self.spn_iso.value() > 1.0:
                self.spn_iso.setValue(0.05)

    def _pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, self._t("out_dir"),
                                             str(self._outdir()))
        if d:
            self.edit_outdir.setText(d)

    def _pick_bg(self):
        col = QColorDialog.getColor(parent=self)
        if col.isValid():
            self._bg = col.name()
            self._sync_bg_button()
            self._refresh_result()

    def _sync_bg_button(self):
        light = sp.luminance(self._bg) > 0.55
        self.btn_bg.setText(self._bg)
        self.btn_bg.setStyleSheet(
            f"background:{self._bg};color:{'#20242b' if light else '#f0f0f0'};")

    def _surface_key(self) -> str:
        return ("promol", "wfn", "vdw")[max(0, self.cmb_surface.currentIndex())]

    def _log(self, msg):
        if callable(self._log_func):
            try:
                self._log_func(msg)
            except Exception:                                     # noqa: BLE001
                pass

    # ── 运行 ──────────────────────────────────────────────────────────────
    def start(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self.glw is None:
            QMessageBox.warning(self, self._t("grp_view"), self._t("no_mol"))
            return

        mw = self._get_mw()
        if not mw or not os.path.isfile(mw):
            QMessageBox.warning(self, self._t("grp_view"), self._t("no_mw"))
            return

        got = sp.atoms_from_canvas(self.glw)
        if got is None:
            QMessageBox.information(self, self._t("grp_view"), self._t("no_mol"))
            return
        symbols, coords = got

        R = sp.camera_rotation(self.glw)
        if R is None:
            QMessageBox.warning(self, self._t("grp_view"), self._t("no_rot"))
            return

        # 范德华球模式下 iso 是半径系数，其余是等值面数值
        params = {
            "surface": self._surface_key(),
            "iso": float(self.spn_iso.value()),
            "zstart_raise": float(self.spn_raise.value()),
            "nx": int(self.spn_grid.value()),
            "ny": int(self.spn_grid.value()),
        }
        outdir = self._outdir()
        outdir.mkdir(parents=True, exist_ok=True)

        ax, bx, gx = sp.euler_zyx_from_matrix(R)
        self._log(f"\n━━━ 表面距离投影图 ━━━\n"
                  f"  原子数: {len(symbols)}   画布朝向 --rot {ax:.1f} {bx:.1f} {gx:.1f}\n"
                  f"  表面定义: {params['surface']}  等值面/系数: {params['iso']:g}  "
                  f"网格: {params['nx']}\n  输出目录: {outdir}\n")

        self.btn_draw.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.lbl_status.setText(self._t("busy"))

        self._worker = SurfaceProjectionWorker(symbols, coords, R, outdir, mw,
                                               params, parent=self)
        self._worker.log.connect(self._log)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, payload):
        self.btn_draw.setEnabled(True)
        if not payload.get("ok"):
            err = payload.get("error", "?")
            self.lbl_status.setText(self._t("failed", err=err))
            self._log(f"  失败: {err}\n{payload.get('traceback','')}")
            QMessageBox.warning(self, self._t("grp_view"), self._t("failed", err=err))
            return

        xs, ys, V, info = payload["xs"], payload["ys"], payload["V"], payload["info"]
        self._result = (xs, ys, V, info)
        self._symbols = payload.get("symbols") or []
        self._redraw()
        self.btn_save.setEnabled(True)

        msg = self._t("done", nx=info["nx"], ny=info["ny"],
                      hi=0.0, lo=self._v_lo, t=info["elapsed"])
        if self._n_void:
            msg += "\n" + self._t("void_n", n=self._n_void)
        self.lbl_status.setText(msg)
        self._log("  " + msg.replace("\n", "\n  ") + "\n")

    def _cmap_name(self) -> str:
        data = self.cmb_cmap.currentData()
        return str(data or "jet")

    def _refresh_result(self, *_):
        """只重画，不重算 Multiwfn；用于配色/显示结构/留白等纯显示选项。"""
        if self._worker is not None and self._worker.isRunning():
            return
        if self._result is not None:
            self._redraw()

    def _redraw(self):
        """把最近一次结果画到画布上（朝向、原子叠加都和 Multiwfn 用的那份一致）。"""
        if self._result is None:
            return
        xs, ys, V, info = self._result
        title = (f"{Path(info['distmap']).parent.name}   "
                 f"{self._surface_key()}, iso={self.spn_iso.value():g}")
        # 叠加层必须用**朝向之后**的坐标（info 里那份），否则会整体错位
        atoms = ((self._symbols, info["coords_oriented"])
                 if self.chk_atoms.isChecked() else None)
        self._n_void, self._v_lo = sp.draw_map(
            self.figure, xs, ys, V, title=title,
            atoms=atoms,
            x_offset=info["x_range"][0], y_offset=info["y_range"][0],
            floor=info["floor"], void="bg" if self.chk_void.isChecked() else "color",
            bg=self._bg, cmap=self._cmap_name())
        self._canvas.draw_idle()

    def _save_image(self):
        if self._result is None:
            return
        # 先用当前绘图代码重画一遍（不重算 Multiwfn），再保存；
        # 这样旧结果也能立刻享受到新的插值/300 dpi，而不用重新跑计算。
        self._redraw()
        default = str(self._outdir() / "surface_distance_projection.png")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save"), default, "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not path:
            return
        try:
            self.figure.savefig(path, dpi=300, facecolor=self._bg,
                                bbox_inches="tight")
        except Exception as exc:                                   # noqa: BLE001
            QMessageBox.warning(self, self._t("save"), str(exc))
            return
        self.lbl_status.setText(self._t("saved", path=path))
        self._log(f"  已保存图片: {path}\n")

    # ── 生命周期 ──────────────────────────────────────────────────────────
    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
