#!/usr/bin/env python3
"""
fchk 轨道等值面可视化工具 v6.0 (PyQt 中文版)
Multiwfn (fchk → cube) + VMD (预览 + Tachyon 渲染) + Tachyon (scene → BMP/PNG)

PyQt5 重写，清爽浅色科技风界面，微软雅黑字体。
后端逻辑全部引入自 fchk_orbital.py。
"""

import os
import sys
import glob
import subprocess
import threading
import socket
import time
import shutil
import tempfile

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton, QCheckBox,
    QComboBox, QTextEdit, QFileDialog, QMessageBox, QButtonGroup,
    QFrame, QSplitter, QScrollArea, QGridLayout, QSizePolicy,
    QSlider, QTabWidget, QDialog, QDialogButtonBox, QFormLayout,
    QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QFontDatabase, QTextCursor, QKeySequence,
    QLinearGradient, QRadialGradient, QBrush, QPainter, QPen,
    QPainterPath, QPixmap, QIcon, QDoubleValidator,
)

# ── Import backend from original module ──────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fchk_orbital as backend
import orbital_viewer_lib as ovlib

# ── MolCanvas for 3D molecular visualization ──────────
from molcanvas import (
    MolCanvas, get_atoms_from_fchk, get_bonds_from_fchk,
    get_atoms_from_cube, get_bonds_from_cube,
)


# ═══════════════════════════════════════════════════════════════
#  i18n: Internationalization
# ═══════════════════════════════════════════════════════════════
_CURRENT_LANG = "zh"

def tr(key, **fmt):
    s = TR.get(key, {}).get(_CURRENT_LANG, key)
    return s.format(**fmt) if fmt else s

TR = {
    # ── Window title ──
    "win_title": {
        "zh": "轨道等值面可视化 v6.0 — Multiwfn + VMD/Tachyon [PyQt 中文版]",
        "en": "Orbital Isosurface Visualization v6.0 — Multiwfn + VMD/Tachyon [PyQt]"
    },
    # ── Header ──
    "title_label": {
        "zh": "◆  轨道等值面可视化  ◆",
        "en": "◆  ORBITAL ISOSURFACE VISUALIZATION  ◆"
    },
    "subtitle_label": {
        "zh": "Multiwfn + VMD + Tachyon  |  v6.0 PyQt 中文版",
        "en": "Multiwfn + VMD + Tachyon  |  v6.0 PyQt Edition"
    },
    # ── Language button ──
    "lang_btn": {"zh": "EN", "en": "中"},
    # ── MolCanvas toolbar ──
    "mol_hint_default": {
        "zh": "选择 fchk 文件后显示分子结构",
        "en": "Select fchk file to view structure"
    },
    "mol_hint_atoms": {
        "zh": "{natoms} 个原子, {nbonds} 个键  |  {name}",
        "en": "{natoms} atoms, {nbonds} bonds  |  {name}"
    },
    "mol_hint_no_atoms": {
        "zh": "未在文件中找到原子信息",
        "en": "No atoms found in file"
    },

    "lbl_label_mode": {"zh": "标签:", "en": "Label:"},
    "label_mode_elem": {"zh": "元素", "en": "Elem"},
    "label_mode_index": {"zh": "编号", "en": "Index"},
    "label_mode_none": {"zh": "无", "en": "None"},
    "btn_reset_view": {"zh": "重置视角", "en": "Reset View"},
    # ── Tab titles ──
    "tab_setup": {"zh": "📁  轨道绘制", "en": "📁  Orbital Draw"},
    "tab_style": {"zh": "🎨  样式设置", "en": "🎨  Style Settings"},
    "tab_paths": {"zh": "⚙️  路径设置", "en": "⚙️  Path Settings"},
    "tab_preview": {"zh": "▶️  预览运行", "en": "▶️  Preview"},
    "tab_tools": {"zh": "🛠️  工具", "en": "🛠️  Tools"},
    "tab_log": {"zh": "📋  运行日志", "en": "📋  Log"},
    # ── GroupBox titles ──
    "grp_paths": {"zh": "软件路径", "en": "SOFTWARE PATHS"},
    "grp_acknowledgments": {"zh": "致谢", "en": "Acknowledgments"},
    "grp_input": {"zh": "输入文件", "en": "INPUT"},
    "grp_orbital": {"zh": "轨道选择", "en": "ORBITAL SELECTION"},
    "grp_render": {"zh": "渲染参数", "en": "RENDER PARAMETERS"},
    "grp_output": {"zh": "输出目录", "en": "OUTPUT DIRECTORY"},
    "grp_actions": {"zh": "操作", "en": "ACTIONS"},
    "grp_live": {"zh": "LIVE ADJUSTMENTS  (VMD 打开后可用)", "en": "LIVE ADJUSTMENTS  (available once VMD opens)"},
    "grp_hydrogen": {"zh": "隐藏氢原子", "en": "HIDE HYDROGEN"},
    "grp_draw_bond": {"zh": "绘制虚线键", "en": "DRAW DASHED LINE"},
    # ── Path panel ──
    "lbl_multiwfn": {"zh": "Multiwfn:", "en": "Multiwfn:"},
    "lbl_vmd": {"zh": "VMD:", "en": "VMD:"},
    "placeholder_mw": {"zh": "Multiwfn.exe 路径", "en": "Path to Multiwfn.exe"},
    "placeholder_vmd": {"zh": "vmd.exe 路径", "en": "Path to vmd.exe"},
    "btn_browse": {"zh": "浏览", "en": "Browse"},
    # ── Input panel ──
    "rb_folder": {"zh": "文件夹", "en": "Folder"},
    "rb_file": {"zh": "单个文件", "en": "Single File"},
    "placeholder_input": {"zh": "选择或拖放 .fchk / .log / .out / .cub 文件...", "en": "Select or drag .fchk / .log / .out / .cub file..."},
    # ── Orbital panel ──
    "lbl_orbital": {"zh": "轨道编号:", "en": "Orbital ID:"},
    "hint_orbital_sep": {"zh": "逗号分隔，例如: h,l,h-1,l+1", "en": "comma separated, e.g.: h,l,h-1,l+1"},
    "lbl_iso": {"zh": "等值面:", "en": "Isosurface:"},
    "lbl_grid": {"zh": "网格精度:", "en": "Grid Quality:"},
    "hint_grid": {"zh": "1=低 2=中 3=高", "en": "1=low 2=medium 3=high"},
    "orbital_rules": {
        "zh": (
            "<b>轨道编号规则:</b><br>"
            "• 闭壳层: h=HOMO, l=LUMO, h-1=HOMO-1, 数字=轨道序号<br>"
            "• 开壳层: 正数=α轨道, 负数=β轨道<br>"
            "• 开壳层符号: ha=αHOMO, hb=βHOMO, la=αLUMO, lb=βLUMO<br>"
            "• 示例: hb-5=βHOMO-5, la+3=αLUMO+3, -131=β轨道131"
        ),
        "en": (
            "<b>Orbital Naming Rules:</b><br>"
            "• Closed-shell: h=HOMO, l=LUMO, h-1=HOMO-1, number=orbital index<br>"
            "• Open-shell: positive=alpha orbital, negative=beta orbital<br>"
            "• Open-shell symbols: ha=alpha HOMO, hb=beta HOMO, la=alpha LUMO, lb=beta LUMO<br>"
            "• Examples: hb-5=beta HOMO-5, la+3=alpha LUMO+3, -131=beta orbital 131"
        ),
    },
    "orbital_rules_btn": {"zh": "轨道编号规则", "en": "Orbital Naming Rules"},
    "btn_browse_orbital": {"zh": "浏览轨道", "en": "Browse MOs"},
    # ── Orbital browser dialog ──
    "dlg_orbital_browser": {"zh": "轨道浏览器", "en": "Orbital Browser"},
    "dlg_orbital_sys_info": {"zh": "体系: {n_a}α + {n_b}β 电子 | {n_basis} 基函数 | HOMO={homo} LUMO={lumo}", "en": "System: {n_a}α + {n_b}β e | {n_basis} basis | HOMO={homo} LUMO={lumo}"},
    "dlg_orbital_hint": {"zh": "点击轨道填入编号并预览", "en": "Click orbital to fill ID and preview"},
    "dlg_orbital_col_idx": {"zh": "轨道", "en": "MO"},
    "dlg_orbital_col_energy_au": {"zh": "能量 (a.u.)", "en": "Energy (a.u.)"},
    "dlg_orbital_col_energy_ev": {"zh": "能量 (eV)", "en": "Energy (eV)"},
    "dlg_orbital_col_occ": {"zh": "占据", "en": "Occ."},
    "dlg_orbital_col_tag": {"zh": "标记", "en": "Tag"},
    "dlg_btn_fill": {"zh": "填入并预览", "en": "Fill & Preview"},
    "dlg_btn_close": {"zh": "关闭", "en": "Close"},
    # ── Render params panel ──
    "lbl_style": {"zh": "风格:", "en": "Style:"},
    "lbl_pos_phase": {"zh": "正相位:", "en": "Pos:"},
    "lbl_neg_phase": {"zh": "负相位:", "en": "Neg:"},
    "pick_pos_color": {"zh": "点击选择正相位颜色", "en": "Pick positive lobe color"},
    "pick_neg_color": {"zh": "点击选择负相位颜色", "en": "Pick negative lobe color"},
    "lbl_res": {"zh": "分辨率:", "en": "Resolution:"},
    "lbl_shading": {"zh": "光照:", "en": "Lighting:"},
    "rb_full": {"zh": "精细", "en": "Fine"},
    "rb_medium": {"zh": "柔和", "en": "Soft"},
    "chk_auto": {"zh": "自动渲染 (无预览, 批处理模式)", "en": "Auto render (no preview, batch mode)"},
    "chk_open": {"zh": "完成后打开文件夹", "en": "Open folder after completion"},
    "chk_trans_raster": {"zh": "透明背景", "en": "Transparent BG"},
    "tooltip_full": {"zh": "全光照：高光、镜面反射全开，画面最精美", "en": "Full lighting: specular highlights and reflections on, best quality"},
    "tooltip_medium": {"zh": "减半光照：降低高光，画面柔和", "en": "Reduced lighting: softer highlights, gentler look"},
    "tooltip_trans_raster": {"zh": "渲染图片背景透明，方便贴入论文/海报", "en": "Render with transparent background for papers/posters"},
    "lbl_threads": {"zh": "渲染线程数:", "en": "Render threads:"},
    "tooltip_threads": {"zh": "影响出图速度，根据自己电脑核心数设置", "en": "Affects rendering speed; set according to your CPU cores"},
    # ── Output panel ──
    "hint_output_default": {"zh": "(默认: 与输入相同)", "en": "(default: same as input)"},
    "placeholder_output": {"zh": "输出目录...", "en": "Output directory..."},
    # ── Buttons panel ──
    "btn_run_cubes": {"zh": "生成cub", "en": "Generate cub"},
    "btn_preview": {"zh": "预览", "en": "Preview"},
    "btn_render_view": {"zh": "渲染出图", "en": "Render Image"},
    "btn_flip_phase": {"zh": "翻转相位", "en": "Flip Phase"},
    "btn_preview_mol": {"zh": "VMD 预览分子", "en": "VMD Preview Mol"},
    "flip_choose": {"zh": "选择要翻转的轨道:", "en": "Choose orbital to flip:"},
    "btn_stop": {"zh": "停止", "en": "Stop"},
    "btn_save": {"zh": "保存", "en": "Save"},
    "btn_cancel": {"zh": "取消", "en": "Cancel"},
    # ── Live adjustments panel ──
    "lbl_isovalue": {"zh": "等值面:", "en": "Isovalue:"},
    "lbl_opacity": {"zh": "透明度:", "en": "Opacity:"},
    # ── Hydrogen panel ──
    "btn_hide_h": {"zh": "隐藏氢原子", "en": "Hide Hydrogens"},
    "btn_show_h": {"zh": "显示所有氢原子", "en": "Show All Hydrogens"},
    "lbl_keep_indices": {"zh": "保留编号 (逗号分隔):", "en": "Keep indices (comma separated):"},
    "placeholder_h_indices": {"zh": "留空 = 全部隐藏", "en": "empty = hide all"},
    # ── Draw bond panel ──
    "lbl_atom1": {"zh": "原子 1:", "en": "Atom 1:"},
    "lbl_atom2": {"zh": "原子 2:", "en": "Atom 2:"},
    "lbl_color": {"zh": "虚线颜色:", "en": "Dash color:"},
    "lbl_type": {"zh": "类型:", "en": "Type:"},
    "lbl_material": {"zh": "透明度:", "en": "Opacity:"},
    "lbl_segments": {"zh": "间距:", "en": "Spacing:"},
    "lbl_radius": {"zh": "半径:", "en": "Radius:"},
    "chk_dash_mode": {"zh": "虚线模式", "en": "Dash mode"},
    "dash_off": {"zh": "关闭", "en": "Off"},
    "dash_line": {"zh": "线段", "en": "Line"},
    "dash_dots": {"zh": "圆点", "en": "Dots"},
    "dash_selected": {"zh": "已选中原子", "en": "Selected atom"},
    "dash_select_other": {"zh": "请选择另一个原子", "en": "Select other atom"},
    "dash_lines": {"zh": "条虚线", "en": "dashes"},
    "dash_status_lines": {"zh": "条虚线", "en": "dashes"},
    "dash_click_two": {"zh": "请在画布上点击两个原子画虚线", "en": "Click two atoms on canvas to draw dash bond"},
    "btn_draw": {"zh": "绘制", "en": "Draw Line"},
    "btn_undo": {"zh": "撤销", "en": "Undo"},
    "btn_clear_all": {"zh": "清除全部", "en": "Clear All"},
    # ── Progress label ──
    "progress_ready": {"zh": "◆  就绪", "en": "◆  Ready"},
    "progress_done": {"zh": "已完成: {ok}/{total}", "en": "Completed: {ok}/{total}"},
    # ── QMessageBox ──
    "msg_title_hint": {"zh": "提示", "en": "Warning"},
    "msg_title_error": {"zh": "路径错误", "en": "Path Error"},
    "msg_select_file_or_folder": {
        "zh": "请先选择文件或文件夹",
        "en": "Please select file or folder first"
    },
    "msg_mw_not_found": {
        "zh": "Multiwfn 未找到:\n{path}",
        "en": "Multiwfn not found:\n{path}"
    },
    "msg_vmd_not_found": {
        "zh": "VMD 未找到:\n{path}",
        "en": "VMD not found:\n{path}"
    },
    "msg_no_fchk": {
        "zh": "未找到 .fchk 文件",
        "en": "No .fchk files found"
    },
    "msg_enter_orbital": {
        "zh": "请先输入轨道编号",
        "en": "Please enter orbital number first"
    },
    "msg_no_cube": {
        "zh": "输出目录中未找到 cube 文件\n请先点击 [生成 Cube]",
        "en": "No cube files found in output directory\nPlease click [Generate Cube] first"
    },
    "msg_preview_first": {
        "zh": "请先点击 [预览] 打开 VMD",
        "en": "Please click [Preview] to open VMD first"
    },
    "msg_enter_two_atoms": {
        "zh": "请输入两个原子编号",
        "en": "Please enter two atom indices"
    },
    # ── QFileDialog ──
    "dlg_select_exe": {"zh": "选择 {which} 可执行文件", "en": "Select {which} Executable"},
    "dlg_select_exe_filter": {"zh": "可执行文件 (*.exe)", "en": "Executables (*.exe)"},
    "dlg_paths_title": {"zh": "⚙️ 软件路径设置", "en": "⚙️ Software Paths"},
    "log_paths_saved": {"zh": "路径已保存 — Multiwfn: {mw}  VMD: {vmd}", "en": "Paths saved — Multiwfn: {mw}  VMD: {vmd}"},
    "dlg_select_input_folder": {"zh": "选择输入文件夹", "en": "Select Input Folder"},
    "dlg_select_input_file": {"zh": "选择输入文件", "en": "Select Input File"},
    "dlg_input_filter": {
        "zh": "所有支持的 (*.fchk *.log *.out *.cub *.cube *.molden *.molden.input);;格式化 Checkpoint (*.fchk);;Gaussian Log (*.log *.out);;Cube (*.cub *.cube);;所有文件 (*.*)",
        "en": "All Supported (*.fchk *.log *.out *.cub *.cube *.molden *.molden.input);;Formatted Checkpoint (*.fchk);;Gaussian Log (*.log *.out);;Cube (*.cub *.cube);;All Files (*.*)"
    },
    "dlg_select_output": {"zh": "选择输出目录", "en": "Select Output Directory"},
    # ── Preview dialogs ──
    "dlg_select_orbitals": {"zh": "选择要预览的轨道", "en": "Select orbitals to preview"},
    "dlg_select_orbitals_hint": {
        "zh": "选择要预览的轨道 (Ctrl 或 Shift 多选):",
        "en": "Select orbitals to preview (multi-select with Ctrl or Shift):"
    },
    # ── VMD log lines ──
    "log_start_preview": {"zh": "\n启动 VMD 预览: {}", "en": "\nStarting VMD preview: {}"},
    "log_style_iso": {"zh": "风格: {}, 等值面: {}", "en": "Style: {}, Isovalue: {}"},
    "log_adjust_view": {"zh": "请在 VMD 中调整视角，然后点击 [渲染出图]", "en": "Adjust view in VMD, then click [Render Image]"},
    "log_vmd_started": {"zh": "VMD 已启动 (端口 {port})，等待操作...", "en": "VMD started (port {port}), waiting for operations..."},
    "log_vmd_failed": {"zh": "VMD 启动失败", "en": "VMD start failed"},
    "log_vmd_error": {"zh": "VMD 启动错误: {}", "en": "VMD start error: {}"},
    "log_style_live_updated": {"zh": "[实时样式] 已切换至 '{}'（无需重启 VMD）", "en": "[Live Style] Switched to '{}' (no VMD restart needed)"},
    "log_style_live_fail": {"zh": "[实时样式] 切换至 '{}' 失败: {}", "en": "[Live Style] Failed to switch to '{}': {}"},
    "log_style_live_gen_fail": {"zh": "[实时样式] 生成TCL失败: {}", "en": "[Live Style] Failed to generate TCL: {}"},
    "pick_color_title": {"zh": "选择正相位颜色", "en": "Pick positive lobe color"},
    "pick_color_title_neg": {"zh": "选择负相位颜色", "en": "Pick negative lobe color"},
    "log_color_custom": {"zh": "[自定义颜色] 已应用 pos={pos} neg={neg}", "en": "[Custom Color] Applied pos={pos} neg={neg}"},
    "log_color_reset": {"zh": "[颜色] 已恢复风格默认颜色", "en": "[Color] Restored style default colors"},
    "log_color_reset_fail": {"zh": "[颜色] 恢复默认颜色失败: {}", "en": "[Color] Failed to restore defaults: {}"},
    "log_start_preview_multi": {"zh": "\n启动 VMD 多轨道预览: {}", "en": "\nStarting VMD multi-orbital preview: {}"},
    "log_preview_first_hint": {"zh": "请先点击预览按钮启动 VMD", "en": "Please click preview button to start VMD first"},
    "log_hide_h_done": {"zh": "[隐藏H] 已隐藏所有分子的氢原子", "en": "[Hide H] Hid hydrogens for all molecules"},
    "log_show_h_done": {"zh": "[隐藏H] 已恢复所有分子的氢原子", "en": "[Hide H] Restored hydrogens for all molecules"},
    "log_draw_bond_ok": {"zh": "[绘制键] 原子{a1}-{a2} {color} {btype} {mat}", "en": "[Draw Bond] Atom{a1}-{a2} {color} {btype} {mat}"},
    "log_draw_bond_fail": {"zh": "[绘制键] 失败", "en": "[Draw Bond] Failed"},
    "log_undo_bond": {"zh": "[键] 已撤销", "en": "[Bond] Undo"},
    "log_undo_bond_fail": {"zh": "[键] 撤销失败", "en": "[Bond] Undo failed"},
    "log_clear_bond": {"zh": "[键] 已清除全部", "en": "[Bond] Cleared all"},
    "log_clear_bond_fail": {"zh": "[键] 清除失败", "en": "[Bond] Clear failed"},
    "log_iso_change": {"zh": "[等值面] iso = {iso:.4g}  ({status})", "en": "[Isosurface] iso = {iso:.4g}  ({status})"},
    "log_flip": {"zh": "[相位] 相位已翻转 → iso = {iso:.3f}", "en": "[Phase] Phase flipped → iso = {iso:.3f}"},
    "log_opacity_change": {"zh": "[透明度] opacity = {op:.2f}", "en": "[Opacity] opacity = {op:.2f}"},
    "log_iso_vmd_disconnected": {"zh": "VMD 未连接", "en": "VMD not connected"},
    "log_done_hint": {
        "zh": "\n在 VMD 中调整视角后，点击 [预览(单个)] / [预览(多个)] 或 [渲染当前视图]",
        "en": "\nAfter adjusting view in VMD, click [Preview (Single)] / [Preview (Multi)] or [Render Current View]"
    },
    "log_all_done": {"zh": "\n全部完成 {ok}/{total}", "en": "\nAll completed {ok}/{total}"},
    # ── Worker log messages ──
    "log_worker_start": {
        "zh": "{total} 个文件 -> {out_dir}",
        "en": "{total} files -> {out_dir}"
    },
    "log_worker_params_multi": {
        "zh": "轨道=[{orbitals}]  等值面={iso}  网格={grid}  风格={style}  分辨率={res}",
        "en": "Orbital=[{orbitals}]  Isovalue={iso}  Grid={grid}  Style={style}  Resolution={res}"
    },
    "log_worker_params_single": {
        "zh": "轨道={orbital}  等值面={iso}  网格={grid}  风格={style}  分辨率={res}",
        "en": "Orbital={orbital}  Isovalue={iso}  Grid={grid}  Style={style}  Resolution={res}"
    },
    "log_worker_mode_auto": {
        "zh": "模式: 自动渲染 (无预览)",
        "en": "Mode: Auto render (no preview)"
    },
    "log_worker_mode_manual": {
        "zh": "模式: 生成 cube -> 手动预览 -> 渲染",
        "en": "Mode: Generate cube -> manual preview -> render"
    },
    "log_worker_stopped": {"zh": "已停止", "en": "Stopped"},
    "log_worker_cube_ok_orb": {
        "zh": "  cube 完成 ({orb}) -> {path}",
        "en": "  cube done ({orb}) -> {path}"
    },
    "log_worker_cube_fail_dt": {
        "zh": "  Cube 生成失败 ({dt:.1f}s)",
        "en": "  Cube failed ({dt:.1f}s)"
    },
    "log_worker_cube_fail_dt2": {
        "zh": "  Cube 失败 ({dt:.1f}s)",
        "en": "  Cube failed ({dt:.1f}s)"
    },
    "log_worker_cube_ok_dt": {
        "zh": "  cube 完成 ({dt:.1f}s) -> {path}",
        "en": "  cube done ({dt:.1f}s) -> {path}"
    },
    "log_worker_render_error": {
        "zh": "  渲染错误: {e}",
        "en": "  Render error: {e}"
    },
    "log_worker_done_summary": {
        "zh": "\nCube 生成完成: {ok}/{total}, 用时 {elapsed:.1f}s",
        "en": "\nCube generation done: {ok}/{total}, elapsed {elapsed:.1f}s"
    },
    "log_render_start": {
        "zh": "\n正在渲染当前视图 (风格: {style})...",
        "en": "\nRendering current view (style: {style})..."
    },
    "log_render_done": {
        "zh": "渲染完成 ({dt:.1f}s) -> {path}",
        "en": "Render done ({dt:.1f}s) -> {path}"
    },
    "log_render_fail": {
        "zh": "渲染失败 ({dt:.1f}s)",
        "en": "Render failed ({dt:.1f}s)"
    },
    "log_render_err": {
        "zh": "渲染错误: {e}",
        "en": "Render error: {e}"
    },
}


# ── Light Sci-Fi Theme Stylesheet ──────────────────────
LIGHT_QSS = """
/* ── Global ── */
QMainWindow {
    background-color: #E4EAF2;
}

QWidget {
    font-family: "Microsoft YaHei", "Segoe UI", "Consolas", sans-serif;
    font-size: 9.5pt;
    color: #2C3E50;
}

/* ── Group Box ── */
QGroupBox {
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    margin-top: 16px;
    padding: 18px 12px 12px 12px;
    background-color: #FFFFFF;
    font-weight: bold;
    font-size: 10pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 2px 12px 2px 12px;
    color: #FFFFFF;
    background-color: #1565C0;
    border-radius: 4px;
    font-size: 9pt;
}

/* ── Labels ── */
QLabel {
    color: #4A5568;
    padding: 1px 0px;
}

QLabel#TitleLabel {
    color: #0D47A1;
    font-size: 16pt;
    font-weight: bold;
    padding: 6px 8px 2px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#SubTitleLabel {
    color: #5C6BC0;
    font-size: 8.5pt;
    padding: 0px 8px 8px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#ProgressLabel {
    color: #1565C0;
    font-size: 9pt;
    font-weight: bold;
    padding: 5px 12px;
    background-color: #EEF2FF;
    border: 1px solid #C5CAE9;
    border-radius: 4px;
}

QLabel#HintLabel {
    color: #7986CB;
    font-size: 8pt;
    padding: 1px 4px;
}

/* ── Line Edit ── */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #2C3E50;
    selection-background-color: #1E88E5;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 1px solid #1E88E5;
    background-color: #F8FAFE;
}

QLineEdit:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border: 1px solid #E2E8F0;
}

/* ── Combo Box ── */
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #2C3E50;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #1E88E5;
}

QComboBox:hover {
    border: 1px solid #5C6BC0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #E2E8F0;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    background-color: #F8FAFE;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    selection-background-color: #E3F2FD;
    selection-color: #1565C0;
    outline: none;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #E8EAF6;
    color: #1A237E;
}

/* ── Radio Button ── */
QRadioButton {
    color: #4A5568;
    spacing: 6px;
    padding: 3px 6px;
}

QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border-radius: 8px;
    border: 2px solid #A0AEC0;
    background-color: #FFFFFF;
}

QRadioButton::indicator:checked {
    border: 2px solid #1E88E5;
    background-color: #1E88E5;
}

QRadioButton::indicator:hover {
    border: 2px solid #5C6BC0;
}

QRadioButton:checked {
    color: #1565C0;
    font-weight: bold;
}

/* ── Check Box ── */
QCheckBox {
    color: #4A5568;
    spacing: 6px;
    padding: 3px 6px;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 2px solid #A0AEC0;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    border: 2px solid #1E88E5;
    background-color: #1E88E5;
}

QCheckBox::indicator:hover {
    border: 2px solid #5C6BC0;
}

QCheckBox:checked {
    color: #1565C0;
}

/* ── Push Button ── */
QPushButton {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 6px 16px;
    color: #2C3E50;
    font-weight: bold;
    font-size: 9pt;
}

QPushButton:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton:pressed {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QPushButton#PrimaryBtn {
    background-color: #1565C0;
    border: 1px solid #0D47A1;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#PrimaryBtn:hover {
    background-color: #1E88E5;
    border: 1px solid #1565C0;
    color: #FFFFFF;
}

QPushButton#PrimaryBtn:pressed {
    background-color: #0D47A1;
}

QPushButton#RenderBtn {
    background-color: #00897B;
    border: 1px solid #00695C;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#RenderBtn:hover {
    background-color: #26A69A;
    border: 1px solid #00897B;
    color: #FFFFFF;
}

QPushButton#RenderBtn:pressed {
    background-color: #00695C;
}

QPushButton#StopBtn {
    background-color: #FFFFFF;
    border: 1px solid #E53935;
    color: #E53935;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#StopBtn:hover {
    background-color: #FFEBEE;
    border: 1px solid #EF5350;
    color: #D32F2F;
}

QPushButton#StopBtn:pressed {
    background-color: #FFCDD2;
}

QPushButton#ActionBtn {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    font-weight: bold;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#ActionBtn:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton#ActionBtn:pressed {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
}

QPushButton#ActionBtn:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QPushButton#SmallBtn {
    padding: 5px 12px;
    font-size: 9pt;
    min-width: 34px;
}

QPushButton#SmallBtn:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton#GhostBtn {
    background-color: transparent;
    border: none;
    color: #1565C0;
    font-weight: bold;
    padding: 4px 12px;
}

QPushButton#GhostBtn:hover {
    background-color: #E3F2FD;
}

/* ── Text Edit (Log) ── */
QTextEdit {
    background-color: #F5F6FA;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 10px;
    color: #1E293B;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.5pt;
    selection-background-color: #BBDEFB;
    selection-color: #0D47A1;
}

QTextEdit:focus {
    border: 1px solid #1E88E5;
}

QScrollBar:vertical {
    background-color: #F1F5F9;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #CBD5E1;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #1E88E5;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}

QScrollBar:horizontal {
    background-color: #F1F5F9;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #CBD5E1;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #1E88E5;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}

/* ── Frame separator ── */
QFrame#Separator {
    background-color: #CBD5E1;
    max-height: 1px;
}

/* ── Scroll Area ── */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* ── Viewer Frame ── */
QFrame#ViewerFrame {
    background-color: #FFFFFF;
    border: 2px solid #CBD5E1;
    border-radius: 8px;
    padding: 3px;
}

/* ── Slider ── */
QSlider::groove:horizontal {
    border: 1px solid #CBD5E1;
    height: 8px;
    background-color: #F1F5F9;
    border-radius: 4px;
}

QSlider::sub-page:horizontal {
    background-color: #1E88E5;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background-color: #FFFFFF;
    border: 2px solid #1E88E5;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background-color: #E3F2FD;
    border: 2px solid #1565C0;
}

QSlider::handle:horizontal:pressed {
    background-color: #BBDEFB;
    border: 2px solid #0D47A1;
}

QSlider:disabled {
    color: #94A3B8;
}

QSlider::groove:horizontal:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
}

QSlider::handle:horizontal:disabled {
    background-color: #F1F5F9;
    border: 2px solid #E2E8F0;
}

/* ── Tooltip ── */
QToolTip {
    border: none;
    padding: 4px 8px;
    color: #2C3E50;
    font-size: 8.5pt;
}

/* ── Tab Widget ── */
QTabWidget::pane {
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    background-color: #FFFFFF;
    padding: 8px;
}

QTabBar::tab {
    background-color: #F1F5F9;
    border: 1px solid #CBD5E1;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 28px;
    margin-right: 3px;
    min-width: 80px;
    color: #4A5568;
    font-weight: bold;
    font-size: 9pt;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1565C0;
    border-bottom: 2px solid #1E88E5;
}

QTabBar::tab:hover:!selected {
    background-color: #E3F2FD;
    color: #1565C0;
}

QTabBar::tab:disabled {
    color: #94A3B8;
    background-color: #F1F5F9;
}
"""


# ── fchk MO 信息解析 ─────────────────────────────────────────

def parse_fchk_mo_info(fchk_path):
    """
    从 fchk 文件解析轨道信息。
    Returns: dict with n_alpha, n_beta, n_basis, is_open_shell,
             alpha_energies, beta_energies, homo_idx, lumo_idx
    """
    import re
    with open(fchk_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    def _read_int(label):
        m = re.search(rf"^{label}\s+I\s+(\d+)", content, re.MULTILINE)
        return int(m.group(1)) if m else None

    def _read_float_array(label):
        m = re.search(
            rf"^{label}\s+R\s+N=\s+(\d+)\s*\n([\s\S]+?)(?=\n\w|\Z)",
            content, re.MULTILINE)
        if not m:
            return []
        return [float(x) for x in m.group(2).split()]

    n_alpha = _read_int("Number of alpha electrons") or 0
    n_beta  = _read_int("Number of beta electrons")  or 0
    n_basis = _read_int("Number of basis functions")  or 0
    alpha_e = _read_float_array("Alpha Orbital Energies")
    beta_e  = _read_float_array("Beta Orbital Energies")
    is_open = bool(beta_e)
    homo_idx = n_alpha
    lumo_idx = n_alpha + 1 if n_basis > n_alpha else None

    return {
        "n_alpha": n_alpha, "n_beta": n_beta, "n_basis": n_basis,
        "is_open_shell": is_open,
        "alpha_energies": alpha_e,
        "beta_energies": beta_e if is_open else None,
        "homo_idx": homo_idx, "lumo_idx": lumo_idx,
    }


# ── 轨道浏览器弹窗 ──────────────────────────────────────────

class OrbitalBrowserDialog(QDialog):
    """弹窗：表格展示所有 MO，点击填入轨道编号。"""

    def __init__(self, fchk_path, parent=None):
        super().__init__(parent)
        self.fchk_path = fchk_path
        self.selected_orbital = None
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
                if i == n_a:     tag = "α-HOMO"
                elif i == n_a+1: tag = "α-LUMO"
                rows.append((i, e, e*eV, occ, tag, "α"))
            for i, e in enumerate(beta_e, 1):
                occ = 1.0 if i <= n_b else 0.0
                tag = ""
                if i == n_b:     tag = "β-HOMO"
                elif i == n_b+1: tag = "β-LUMO"
                rows.append((-i, e, e*eV, occ, tag, "β"))
            self._fill_rows(rows, is_open=True)
        else:
            rows = []
            for i, e in enumerate(alpha_e, 1):
                occ = 2.0 if i <= n_a else 0.0
                tag = ""
                if i == homo:     tag = "HOMO"
                elif i == lumo:   tag = "LUMO"
                rows.append((i, e, e*eV, occ, tag, "α"))
            self._fill_rows(rows, is_open=False)

        # 滚动到 HOMO
        if homo and homo <= self.table.rowCount():
            self.table.scrollToItem(self.table.item(homo-1, 0))

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


# ── Titled Panel ─────────────────────────────────────
class SciFiGroupBox(QGroupBox):
    """Custom group box with sci-fi style corner decorations."""

    def __init__(self, title, parent=None):
        super().__init__(title, parent)


# ── Worker Threads ───────────────────────────────────────
class CubeWorker(QThread):
    """Background worker for cube generation."""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, int, int, list)

    def __init__(self, files, out_dir, orbitals, iso, grid, style_name,
                 resolution, shade_mode, auto_render, exe_paths, do_open):
        super().__init__()
        self.files = files
        self.out_dir = out_dir
        self.orbitals = orbitals
        self.iso = iso
        self.grid = grid
        self.style_name = style_name
        self.resolution = resolution
        self.shade_mode = shade_mode
        self.auto_render = auto_render
        self.exe_paths = exe_paths
        self.do_open = do_open
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        total = len(self.files)
        is_multi = len(self.orbitals) > 1
        orbital = self.orbitals[0] if self.orbitals else ""

        self.log_signal.emit(tr("log_worker_start", total=total, out_dir=self.out_dir))
        if is_multi:
            self.log_signal.emit(
                tr("log_worker_params_multi",
                   orbitals=','.join(self.orbitals), iso=self.iso,
                   grid=self.grid, style=self.style_name,
                   res=f"{self.resolution[0]}x{self.resolution[1]}"))
        else:
            self.log_signal.emit(
                tr("log_worker_params_single",
                   orbital=orbital, iso=self.iso, grid=self.grid,
                   style=self.style_name,
                   res=f"{self.resolution[0]}x{self.resolution[1]}"))
        if self.auto_render:
            self.log_signal.emit(tr("log_worker_mode_auto"))
        else:
            self.log_signal.emit(tr("log_worker_mode_manual"))
        self.log_signal.emit("=" * 50)

        ok = 0
        cubes = []
        t_total = time.time()
        for i, fchk in enumerate(self.files):
            if not self._running:
                self.log_signal.emit(tr("log_worker_stopped"))
                break
            name = os.path.basename(fchk)
            self.progress_signal.emit(f"[{i+1}/{total}] {name}")
            self.log_signal.emit(f"\n[{i+1}/{total}] {name}")

            t0 = time.time()
            cube_result = None
            if is_multi:
                results = backend.gen_multi_cubes(
                    fchk, self.orbitals,
                    grid_quality=int(self.grid), work_dir=self.out_dir,
                    multiwfn_exe=self.exe_paths["multiwfn"])
                dt = time.time() - t0
                if results:
                    for cube_path, orb_name in results:
                        self.log_signal.emit(
                            tr("log_worker_cube_ok_orb", orb=orb_name, path=os.path.basename(cube_path)))
                        cubes.append((cube_path, orb_name))
                    ok += 1
                    cube_result = results[0][0] if results else None
                else:
                    self.log_signal.emit(tr("log_worker_cube_fail_dt", dt=dt))
            else:
                result = backend.gen_cube(
                    fchk, orbital=orbital,
                    grid_quality=int(self.grid), work_dir=self.out_dir,
                    multiwfn_exe=self.exe_paths["multiwfn"])
                cube_result = result
                dt = time.time() - t0
                if not result:
                    self.log_signal.emit(tr("log_worker_cube_fail_dt2", dt=dt))
                    continue
                self.log_signal.emit(
                    tr("log_worker_cube_ok_dt", dt=dt, path=os.path.basename(result)))
                cubes.append(result)
                ok += 1

            if self.auto_render and cube_result:
                t0 = time.time()
                try:
                    png = self._fchk_to_png_name(fchk)
                    backend.render_cube_auto(
                        cube_result, output_png=png, isovalue=self.iso,
                        style_name=self.style_name, resolution=self.resolution,
                        vmd_exe=self.exe_paths["vmd"],
                        tachyon_exe=self.exe_paths["tachyon"],
                        shade_mode=self.shade_mode)
                    dt = time.time() - t0
                    self.log_signal.emit(f"  PNG: {os.path.basename(png)} ({dt:.1f}s)")
                except Exception as e:
                    self.log_signal.emit(tr("log_worker_render_error", e=e))

        elapsed = time.time() - t_total
        self.log_signal.emit(
            tr("log_worker_done_summary", ok=ok, total=total, elapsed=elapsed))
        self.finished_signal.emit(self.auto_render, ok, total, cubes)

    def _fchk_to_png_name(self, fchk_path):
        orbital = ",".join(self.orbitals) if len(self.orbitals) > 1 else self.orbitals[0]
        stem = os.path.splitext(os.path.basename(fchk_path))[0]
        return os.path.join(self.out_dir, f"{stem}_MO{orbital}.png")


class RenderWorker(QThread):
    """Background worker for Tachyon rendering."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)

    def __init__(self, port, render_dir, output_png, tachyon_exe, resolution,
                 style_name, shade_mode, trans_raster, threads):
        super().__init__()
        self.port = port
        self.render_dir = render_dir
        self.output_png = output_png
        self.tachyon_exe = tachyon_exe
        self.resolution = resolution
        self.style_name = style_name
        self.shade_mode = shade_mode
        self.trans_raster = trans_raster
        self.threads = threads

    def run(self):
        self.log_signal.emit(tr("log_render_start", style=self.style_name))
        t0 = time.time()
        try:
            png = backend.render_current_view(
                self.port, self.render_dir,
                output_png=self.output_png,
                tachyon_exe=self.tachyon_exe,
                resolution=self.resolution,
                style_name=self.style_name,
                shade_mode=self.shade_mode,
                trans_raster=self.trans_raster,
                threads=self.threads,
                log_func=lambda msg: self.log_signal.emit(msg),
            )
            dt = time.time() - t0
            if png:
                self.log_signal.emit(
                    tr("log_render_done", dt=dt, path=os.path.basename(png)))
                self.finished_signal.emit(png)
            else:
                self.log_signal.emit(tr("log_render_fail", dt=dt))
                self.finished_signal.emit("")
        except Exception as e:
            self.log_signal.emit(tr("log_render_err", e=e))
            self.finished_signal.emit("")


# ── Main Application Window ──────────────────────────────
class OrbitalVisApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1400, 820)
        self.setMinimumSize(1100, 680)

        self.paths = backend.load_config()
        self.running = False
        # ── VMD 会话（委托给 orbital_viewer_lib）──
        self._vmd_session = ovlib.VMDOrbitalSession(log_func=self._append_log)
        self.vmd_port = None       # 读取时从 session 同步
        self.vmd_render_dir = None # 读取时从 session 同步
        self.vmd_cube_path = None
        self._vmd_persist_sock = None  # 已废弃，保留兼容
        self._vmd_dash_pairs = []
        self.vmd_multi_cubes = None
        # 应用图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "OV.png")
        if os.path.exists(icon_path):
            from PyQt5.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))
        self._vmd_style_applied = None
        self._custom_pos_rgb = None  # 自定义正相位颜色 (R,G,B), None=用风格默认
        self._custom_neg_rgb = None  # 自定义负相位颜色
        self.current_iso = 0.05
        self.current_opacity = None
        self.iso_step = 0.005
        # ── 轨道状态管理（统一追踪 rep/molid/phase） ──
        self._vmd_state = {"rep_pos": 1, "rep_neg": 2, "molid": 0}
        self.opacity_step = 0.05

        self._current_cubes = []
        # 拖放支持
        self.setAcceptDrops(True)
        self._current_orbitals = []

        # ── MolCanvas 状态 ──
        self.mol_canvas = None
        self._current_fchk = ""

        self._lang = "zh"
        self._h_hidden = False  # track hydrogen filter state

        self._setup_ui()
        self._setup_shortcuts()
        self._apply_theme()
        self._apply_lang_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 10)
        main_layout.setSpacing(6)

        # ── 水平分割: 左侧(画布+日志) | 右侧参数面板 ──
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)

        # 左侧: 分子画布 + 运行日志
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        viewer_wrap = QFrame()
        viewer_wrap.setObjectName("ViewerFrame")
        viewer_wrap.setAutoFillBackground(True)
        viewer_wrap.setMinimumSize(300, 300)
        vl = QVBoxLayout(viewer_wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.mol_canvas = MolCanvas(viewer_wrap)
        vl.addWidget(self.mol_canvas, stretch=1)

        # 画布底部工具栏
        vbar = QWidget()
        vbar.setMaximumHeight(36)
        vbhl = QHBoxLayout(vbar)
        vbhl.setContentsMargins(6, 2, 6, 2)
        vbhl.setSpacing(6)

        # 标签模式
        self.lbl_mode = QLabel()
        _fs = self.lbl_mode.font(); _fs.setPointSizeF(7.5); self.lbl_mode.setFont(_fs)
        vbhl.addWidget(self.lbl_mode)
        self.cb_label = QComboBox()
        self.cb_label.setCurrentIndex(1)
        self.cb_label.setMaximumWidth(60)
        _fs = self.cb_label.font(); _fs.setPointSizeF(7.5); self.cb_label.setFont(_fs)
        self.cb_label.currentIndexChanged.connect(
            lambda idx: (setattr(self.mol_canvas, 'label_mode', idx), self.mol_canvas.update())
        )
        vbhl.addWidget(self.cb_label)

        vbhl.addStretch()

        self.btn_reset_view = QPushButton()
        self.btn_reset_view.setObjectName("GhostBtn")
        self.btn_reset_view.setMaximumHeight(26)
        _fs = self.btn_reset_view.font(); _fs.setPointSizeF(7.5); self.btn_reset_view.setFont(_fs)
        self.btn_reset_view.clicked.connect(lambda: (
            self.mol_canvas.auto_fit(),
            self.mol_canvas.update()
        ))
        vbhl.addWidget(self.btn_reset_view)

        vl.addWidget(vbar)

        # 画布
        left_layout.addWidget(viewer_wrap)

        # 左侧画布区与右侧参数区的分隔
        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        self.tabs = QTabWidget()

        tab_setup = QWidget()
        tab_setup_layout = QVBoxLayout(tab_setup)
        tab_setup_layout.setContentsMargins(4, 4, 4, 4)
        tab_setup_layout.setSpacing(6)
        tab_setup_layout.addWidget(self._build_input_panel())
        tab_setup_layout.addWidget(self._build_orbital_panel())
        # 轨道表格 — 嵌入第一个选项卡，载入 fchk 后自动填充
        self.orbital_tabs = QTabWidget()
        self.orbital_tabs.setMinimumHeight(400)
        self.orbital_table_alpha = self._make_orbital_table()
        self.orbital_tabs.addTab(self.orbital_table_alpha, "")
        self.orbital_table_beta = None
        tab_setup_layout.addWidget(self.orbital_tabs)
        tab_setup_layout.addStretch()
        self.tabs.addTab(tab_setup, "")

        tab_style = QWidget()
        tab_style_layout = QVBoxLayout(tab_style)
        tab_style_layout.setContentsMargins(4, 4, 4, 4)
        tab_style_layout.setSpacing(6)
        tab_style_layout.addWidget(self._build_render_params_panel())
        tab_style_layout.addWidget(self._build_live_panel())
        tab_style_layout.addWidget(self._build_buttons_panel())
        tab_style_layout.addWidget(self._build_draw_bond_panel())
        tab_style_layout.addStretch()
        self.tabs.addTab(tab_style, "")

        tab_preview = QWidget()
        tab_preview_layout = QVBoxLayout(tab_preview)
        tab_preview_layout.setContentsMargins(4, 4, 4, 4)
        tab_preview_layout.setSpacing(6)

        tab_preview_layout.addWidget(self._build_paths_panel())
        tab_preview_layout.addWidget(self._build_acknowledgments_box())
        tab_preview_layout.addStretch()
        self.tabs.addTab(tab_preview, "")

        # 日志选项卡
        tab_log = QWidget()
        tab_log_layout = QVBoxLayout(tab_log)
        tab_log_layout.setContentsMargins(4, 4, 4, 4)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
        tab_log_layout.addWidget(self.log_text)
        # 不再作为选项卡，放到下方
        # self.tabs.addTab(tab_log, "")

        scroll_right.setWidget(self.tabs)

        # 左侧画布区与右侧参数区的分隔
        body_splitter = QSplitter(Qt.Horizontal)
        body_splitter.addWidget(left_widget)
        body_splitter.addWidget(scroll_right)
        body_splitter.setStretchFactor(0, 1)
        body_splitter.setStretchFactor(1, 2)
        body_layout.addWidget(body_splitter, stretch=1)

        # ── 日志区（下方固定高度） ──
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(160)
        self.log_text.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px;"
            "border: 1px solid #CBD5E1; border-radius: 4px;"
        )
        body_layout.addWidget(self.log_text)

        main_layout.addWidget(body, stretch=5)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("ProgressLabel")
        main_layout.addWidget(self.progress_label)

    def _build_input_panel(self):
        self.grp_input = SciFiGroupBox("")
        layout = QHBoxLayout(self.grp_input)
        layout.setSpacing(6)

        self.mode_group = QButtonGroup(self)
        self.rb_folder = QRadioButton("")
        self.rb_file = QRadioButton("")
        self.mode_group.addButton(self.rb_folder, 0)
        self.mode_group.addButton(self.rb_file, 1)
        self.rb_file.setChecked(True)
        self.rb_folder.hide()
        self.rb_file.hide()

        self.var_path = QLineEdit()
        self.var_path.setPlaceholderText("")
        layout.addWidget(self.var_path, stretch=1)
        self.btn_browse_input = QPushButton("")
        self.btn_browse_input.setObjectName("SmallBtn")
        self.btn_browse_input.clicked.connect(self._browse_input)
        layout.addWidget(self.btn_browse_input)

        self._lang_btn = QPushButton("EN")
        self._lang_btn.setObjectName("SmallBtn")
        self._lang_btn.setCursor(Qt.PointingHandCursor)
        self._lang_btn.clicked.connect(self._switch_lang)
        layout.addWidget(self._lang_btn)

        return self.grp_input

    def _build_orbital_panel(self):
        self.grp_orbital = SciFiGroupBox("")
        layout = QGridLayout(self.grp_orbital)
        layout.setVerticalSpacing(4)
        layout.setHorizontalSpacing(6)

        # Row 0: 轨道 | 网格
        self.lbl_orbital_main = QLabel("")
        layout.addWidget(self.lbl_orbital_main, 0, 0)
        self.var_orbital = QLineEdit("h")
        self.var_orbital.setMaximumWidth(160)
        layout.addWidget(self.var_orbital, 0, 1)

        self.lbl_orbital_grid = QLabel("")
        layout.addWidget(self.lbl_orbital_grid, 0, 2)
        self.var_grid = QComboBox()
        self.var_grid.addItems(["1", "2", "3"])
        self.var_grid.setCurrentIndex(1)
        self.var_grid.setMaximumWidth(60)
        layout.addWidget(self.var_grid, 0, 3)
        self.hint_grid = QLabel("")
        self.hint_grid.setObjectName("HintLabel")
        layout.addWidget(self.hint_grid, 0, 4)

        # Browse orbitals button
        self.btn_browse_orbital = QPushButton(self._tr("btn_browse_orbital"))
        self.btn_browse_orbital.setToolTip(self._tr("btn_browse_orbital"))
        self.btn_browse_orbital.setFixedHeight(48)
        self.btn_browse_orbital.setCursor(Qt.PointingHandCursor)
        self.btn_browse_orbital.clicked.connect(self._open_orbital_browser)
        layout.addWidget(self.btn_browse_orbital, 0, 5)

        # Rules button
        self.btn_rules = QPushButton(self._tr("orbital_rules_btn"))
        self.btn_rules.setToolTip(self._tr("orbital_rules_btn"))
        self.btn_rules.setText(self._tr("orbital_rules_btn"))
        self.btn_browse_orbital.setText(self._tr("btn_browse_orbital"))
        self.btn_browse_orbital.setToolTip(self._tr("btn_browse_orbital"))
        self.btn_rules.setFixedHeight(48)
        self.btn_rules.setCursor(Qt.PointingHandCursor)
        self.btn_rules.clicked.connect(self._show_rules_dialog)
        layout.addWidget(self.btn_rules, 0, 6)

        for c in range(7):
            layout.setColumnStretch(c, 0)
        layout.setColumnStretch(1, 1)
        return self.grp_orbital

    def _build_render_params_panel(self):
        self.grp_render = SciFiGroupBox("")
        rlayout = QGridLayout(self.grp_render)
        rlayout.setVerticalSpacing(4)
        rlayout.setHorizontalSpacing(6)

        # 风格 + 自定义颜色，全部放一行
        self.lbl_render_style = QLabel("")
        self.var_style = QComboBox()
        self.var_style.setIconSize(QtCore.QSize(30, 13))
        self.var_style.setMaxVisibleItems(20)
        for name in backend.STYLES:
            icon = self._make_style_icon(backend.STYLES[name])
            self.var_style.addItem(icon, f"  {name}")
        self.var_style.setCurrentIndex(0)
        self.var_style.currentTextChanged.connect(self._on_style_changed)

        self.btn_pos_color = QPushButton("")
        self.btn_pos_color.setFixedSize(28, 28)
        self.btn_pos_color.setToolTip(self._tr("pick_pos_color"))
        self.btn_pos_color.setStyleSheet("background:#00AA00; border:1px solid #555; border-radius:14px;")
        self.btn_pos_color.clicked.connect(lambda: self._pick_phase_color("pos"))
        self.btn_pos_color.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_pos_color.customContextMenuRequested.connect(lambda: self._reset_phase_color("pos"))

        self.btn_neg_color = QPushButton("")
        self.btn_neg_color.setFixedSize(28, 28)
        self.btn_neg_color.setToolTip(self._tr("pick_neg_color"))
        self.btn_neg_color.setStyleSheet("background:#0000AA; border:1px solid #555; border-radius:14px;")
        self.btn_neg_color.clicked.connect(lambda: self._pick_phase_color("neg"))
        self.btn_neg_color.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_neg_color.customContextMenuRequested.connect(lambda: self._reset_phase_color("neg"))

        self.lbl_pos_phase = QLabel("")
        self.lbl_neg_phase = QLabel("")

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self.lbl_render_style)
        top_row.addWidget(self.var_style, 1)
        top_row.addSpacing(12)
        top_row.addWidget(self.lbl_pos_phase)
        top_row.addWidget(self.btn_pos_color)
        top_row.addSpacing(8)
        top_row.addWidget(self.lbl_neg_phase)
        top_row.addWidget(self.btn_neg_color)
        rlayout.addLayout(top_row, 0, 0, 1, 7)

        self.lbl_render_res = QLabel("")
        self.var_res = QComboBox()
        self.var_res.addItems(["2000x1500", "1200x900", "3000x2250"])
        self.var_res.setCurrentIndex(0)
        self.var_res.setMaximumWidth(150)
        res_row = QHBoxLayout()
        res_row.setSpacing(4)
        res_row.setContentsMargins(0, 0, 0, 0)
        res_row.addWidget(self.lbl_render_res)
        res_row.addWidget(self.var_res, 1)
        rlayout.addLayout(res_row, 1, 0, 1, 2)

        self.lbl_render_shading = QLabel("")
        rlayout.addWidget(self.lbl_render_shading, 1, 2)
        shade_frame = QHBoxLayout()
        shade_frame.setSpacing(4)
        self.shade_group = QButtonGroup(self)
        self.rb_full = QRadioButton("")
        self.rb_medium = QRadioButton("")
        self.shade_group.addButton(self.rb_full, 0)
        self.shade_group.addButton(self.rb_medium, 1)
        self.rb_full.setChecked(True)
        shade_frame.addWidget(self.rb_full)
        shade_frame.addWidget(self.rb_medium)
        rlayout.addLayout(shade_frame, 1, 3)

        self.var_trans_raster = QCheckBox("")
        self.var_trans_raster.setChecked(True)
        rlayout.addWidget(self.var_trans_raster, 1, 4)
        self.lbl_render_threads = QLabel("")
        rlayout.addWidget(self.lbl_render_threads, 1, 5)
        self.var_threads = QLineEdit("8")
        self.var_threads.setMaximumWidth(50)
        self.var_threads.setAlignment(Qt.AlignCenter)
        rlayout.addWidget(self.var_threads, 1, 6)

        # hidden
        self.var_auto = QCheckBox("")
        self.var_open = QCheckBox("")
        self.var_auto.hide()
        self.var_open.hide()
        rlayout.addWidget(self.var_auto, 2, 0)
        rlayout.addWidget(self.var_open, 2, 1)

        for c in range(7):
            rlayout.setColumnStretch(c, 0)
        rlayout.setColumnStretch(0, 1)
        return self.grp_render

    def _build_buttons_panel(self):
        self.grp_actions = SciFiGroupBox("")
        layout = QHBoxLayout(self.grp_actions)
        layout.setSpacing(8)

        self.btn_run = QPushButton("")
        self.btn_run.setObjectName("ActionBtn")
        self.btn_run.clicked.connect(self._run_cubes)
        self.btn_run.hide()
        layout.addWidget(self.btn_run)

        self.btn_preview = QPushButton("")
        self.btn_preview.setObjectName("ActionBtn")
        self.btn_preview.setEnabled(False)
        self.btn_preview.clicked.connect(self._preview)
        layout.addWidget(self.btn_preview)

        self.btn_render = QPushButton("")
        self.btn_render.setObjectName("ActionBtn")
        self.btn_render.setEnabled(False)
        self.btn_render.clicked.connect(self._render_view)
        layout.addWidget(self.btn_render)

        self.btn_preview_mol = QPushButton("")
        self.btn_preview_mol.setObjectName("ActionBtn")
        self.btn_preview_mol.setEnabled(False)
        self.btn_preview_mol.clicked.connect(self._preview_mol)
        self.btn_preview_mol.hide()
        layout.addWidget(self.btn_preview_mol)

        self.btn_flip_phase = QPushButton("")
        self.btn_flip_phase.setObjectName("ActionBtn")
        self.btn_flip_phase.setEnabled(False)
        self.btn_flip_phase.clicked.connect(self._on_flip_phase)
        layout.addWidget(self.btn_flip_phase)

        self.btn_h_filter = QPushButton("")
        self.btn_h_filter.setObjectName("ActionBtn")
        self.btn_h_filter.setEnabled(False)
        self.btn_h_filter.clicked.connect(self._toggle_h_filter)
        layout.addWidget(self.btn_h_filter)

        self.lbl_h_keep = QLabel("")
        layout.addWidget(self.lbl_h_keep)
        self.var_h_indices = QLineEdit()
        self.var_h_indices.setMaximumWidth(160)
        self.var_h_indices.setPlaceholderText("")
        layout.addWidget(self.var_h_indices)

        layout.addStretch()

        return self.grp_actions

    def _build_live_panel(self):
        self.grp_live = QWidget()
        layout = QGridLayout(self.grp_live)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setHorizontalSpacing(8)

        self.lbl_live_iso = QLabel("")
        layout.addWidget(self.lbl_live_iso, 0, 0)
        self.iso_slider = QSlider(Qt.Horizontal)
        self.iso_slider.setRange(1, 500)
        self.iso_slider.setSingleStep(1)
        self.iso_slider.setPageStep(5)
        self.iso_slider.setValue(50)
        self.iso_slider.setEnabled(False)
        self.iso_slider.valueChanged.connect(self._on_iso_slider_changed)
        layout.addWidget(self.iso_slider, 0, 1)
        self.iso_edit = QLineEdit("0.050")
        self.iso_edit.setValidator(QDoubleValidator(0.005, 0.500, 4))
        self.iso_edit.setMaximumWidth(90)
        self.iso_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.iso_edit.setEnabled(False)
        self.iso_edit.editingFinished.connect(self._on_iso_edit_finished)
        layout.addWidget(self.iso_edit, 0, 2)

        self.lbl_live_opacity = QLabel("")
        layout.addWidget(self.lbl_live_opacity, 0, 3)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(75)
        self.opacity_slider.setEnabled(False)
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        layout.addWidget(self.opacity_slider, 0, 4)
        self.opacity_edit = QLineEdit("0.75")
        self.opacity_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self.opacity_edit.setMaximumWidth(70)
        self.opacity_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.opacity_edit.setEnabled(False)
        self.opacity_edit.editingFinished.connect(self._on_opacity_edit_finished)
        layout.addWidget(self.opacity_edit, 0, 5)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(4, 1)
        return self.grp_live


    def _build_draw_bond_panel(self):
        """VMD 虚线样式面板 — 移植自 MolViewer。"""
        self.grp_draw_bond = SciFiGroupBox("")
        vmd_layout = QVBoxLayout(self.grp_draw_bond)
        vmd_layout.setSpacing(4)

        # (tcl_key, en_label, zh_label, hex_color)
        self._bond_color_items = [
            ("black",  "Black",  "黑色",   "#000000"),
            ("gray",   "Gray",   "灰色",   "#808080"),
            ("cyan",   "Cyan",   "青色",   "#00FFFF"),
            ("yellow", "Yellow", "黄色",   "#FFFF00"),
            ("red",    "Red",    "红色",   "#FF0000"),
            ("blue",   "Blue",   "蓝色",   "#0000FF"),
            ("green",  "Green",  "绿色",   "#00FF00"),
            ("white",  "White",  "白色",   "#FFFFFF"),
        ]
        # (tcl_key, en_label, zh_label)
        self._bond_type_items = [
            ("dots",     "Dots",          "圆点"),
            ("pymol",    "Dashed(pymol)", "PyMOL虚线"),
            ("cylinder", "Cylinder",      "圆柱"),
            ("cone",     "Cone",          "锥形"),
            ("line",     "Line",          "线段"),
        ]
        self._bond_mat_map = {
            "Opaque": "Opaque", "Transparent": "Transparent",
            "50%Transparent": "HalfTransparent"}

        # ── Row 1: 虚线 / 画布样式 / VMD 颜色 / 类型 / 材质 ──
        row1 = QHBoxLayout()
        self.chk_dash_mode = QCheckBox("")
        self.chk_dash_mode.setEnabled(False)
        self.chk_dash_mode.toggled.connect(lambda v: (
            self.mol_canvas.set_dash_bond_mode(v),
            self._update_dash_status()
        ))
        row1.addWidget(self.chk_dash_mode)

        self.lbl_bond_color = QLabel("")
        row1.addWidget(self.lbl_bond_color)
        self.var_dash_color = QComboBox()
        self.var_dash_color.setMaximumWidth(70)
        self.var_dash_color.currentIndexChanged.connect(self._on_dash_color_changed)
        row1.addWidget(self.var_dash_color)

        self.lbl_bond_type = QLabel("")
        row1.addWidget(self.lbl_bond_type)
        self.var_bond_type = QComboBox()
        self.var_bond_type.setMaximumWidth(100)
        row1.addWidget(self.var_bond_type)

        self.lbl_bond_mat = QLabel("")
        row1.addWidget(self.lbl_bond_mat)
        self.var_bond_mat = QComboBox()
        self.var_bond_mat.addItems(list(self._bond_mat_map.keys()))
        self.var_bond_mat.setCurrentText("Opaque")
        self.var_bond_mat.setMaximumWidth(140)
        row1.addWidget(self.var_bond_mat)
        row1.addStretch()

        self.btn_undo_bond = QPushButton("")
        self.btn_undo_bond.setEnabled(False)
        self.btn_undo_bond.clicked.connect(self._undo_bond)
        row1.addWidget(self.btn_undo_bond)

        self.btn_clear_bond = QPushButton("")
        self.btn_clear_bond.setEnabled(False)
        self.btn_clear_bond.clicked.connect(self._clear_bond)
        row1.addWidget(self.btn_clear_bond)

        vmd_layout.addLayout(row1)

        # 类型/透明度变化 → 实时重绘 VMD 虚线
        self.var_bond_type.currentIndexChanged.connect(lambda: self._vmd_reapply_dashes())
        self.var_bond_mat.currentIndexChanged.connect(lambda: self._vmd_reapply_dashes())

        # ── Row 2: 段数 / 半径 (label + slider + edit，同行) ──
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        self.lbl_bond_segments = QLabel("")
        grid.addWidget(self.lbl_bond_segments, 0, 0)
        self.bond_nbars_slider = QSlider(Qt.Horizontal)
        self.bond_nbars_slider.setRange(5, 100)
        self.bond_nbars_slider.setValue(20)
        self.bond_nbars_slider.valueChanged.connect(self._on_nbars_slider)
        grid.addWidget(self.bond_nbars_slider, 0, 1)
        self.bond_nbars_edit = QLineEdit("0.20")
        self.bond_nbars_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self.bond_nbars_edit.setMaximumWidth(50)
        self.bond_nbars_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.bond_nbars_edit.editingFinished.connect(self._on_nbars_edit)
        grid.addWidget(self.bond_nbars_edit, 0, 2)

        self.lbl_bond_radius = QLabel("")
        grid.addWidget(self.lbl_bond_radius, 0, 3)
        self.bond_radius_slider = QSlider(Qt.Horizontal)
        self.bond_radius_slider.setRange(1, 50)
        self.bond_radius_slider.setValue(6)
        self.bond_radius_slider.valueChanged.connect(self._on_bond_radius_slider)
        grid.addWidget(self.bond_radius_slider, 0, 4)
        self.bond_radius_edit = QLineEdit("0.06")
        self.bond_radius_edit.setValidator(QDoubleValidator(0.01, 0.50, 2))
        self.bond_radius_edit.setMaximumWidth(70)
        self.bond_radius_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.bond_radius_edit.editingFinished.connect(self._on_bond_radius_edit)
        grid.addWidget(self.bond_radius_edit, 0, 5)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        vmd_layout.addLayout(grid)

        return self.grp_draw_bond

    def closeEvent(self, event):
        """关闭程序时，强制关闭 VMD（如果仍在运行）。"""
        # 先尝试通过 socket 优雅关闭
        self._send_vmd_cmd("quit")
        self._close_persist_sock()
        # 再确保进程被终止
        try:
            subprocess.run(["taskkill", "/IM", "vmd.exe", "/F"],
                           capture_output=True, timeout=5)
        except Exception:
            pass
        event.accept()

    def _apply_theme(self):
        self.setStyleSheet(LIGHT_QSS)

    # ═══════════════════════════════════════════════════════════════
    #  i18n Methods
    # ═══════════════════════════════════════════════════════════════
    def _tr(self, key, **fmt):
        global _CURRENT_LANG
        s = TR.get(key, {}).get(_CURRENT_LANG, key)
        return s.format(**fmt) if fmt else s

    def _switch_lang(self):
        global _CURRENT_LANG
        _CURRENT_LANG = "en" if _CURRENT_LANG == "zh" else "zh"
        self._lang = _CURRENT_LANG
        self._apply_lang_ui()

    def _apply_lang_ui(self):
        global _CURRENT_LANG
        # Window
        self.setWindowTitle(self._tr("win_title"))
        self._lang_btn.setText(self._tr("lang_btn"))

        # Tabs
        self.tabs.setTabText(0, self._tr("tab_setup"))
        self.tabs.setTabText(1, self._tr("tab_style"))
        self.tabs.setTabText(2, self._tr("tab_paths"))

        # Group boxes
        self.grp_paths.setTitle(self._tr("grp_paths"))
        self._update_acknowledgments()
        self.grp_input.setTitle(self._tr("grp_input"))
        self.grp_orbital.setTitle(self._tr("grp_orbital"))
        self.grp_render.setTitle(self._tr("grp_render"))
        self.grp_actions.setTitle(self._tr("grp_actions"))
        self.grp_draw_bond.setTitle(self._tr("grp_draw_bond"))
        self._populate_bond_combos()

        # MolCanvas toolbar
        self.lbl_mode.setText(self._tr("lbl_label_mode"))
        self.btn_reset_view.setText(self._tr("btn_reset_view"))

        # Label mode combo - rebuild items
        label_items = [
            self._tr("label_mode_elem"),
            self._tr("label_mode_index"),
            self._tr("label_mode_none"),
        ]
        self.cb_label.blockSignals(True)
        cur = self.cb_label.currentIndex()
        self.cb_label.clear()
        self.cb_label.addItems(label_items)
        self.cb_label.setCurrentIndex(cur)
        self.cb_label.blockSignals(False)

        # Input panel
        self.rb_folder.setText(self._tr("rb_folder"))
        self.rb_file.setText(self._tr("rb_file"))
        self.btn_browse_input.setText(self._tr("btn_browse"))
        self._lang_btn.setText(self._tr("lang_btn"))
        self.var_path.setPlaceholderText(self._tr("placeholder_input"))

        # Orbital panel
        self.lbl_orbital_main.setText(self._tr("lbl_orbital"))
        self.lbl_orbital_grid.setText(self._tr("lbl_grid"))
        self.hint_grid.setText(self._tr("hint_grid"))
        self.btn_rules.setToolTip(self._tr("orbital_rules_btn"))
        self.btn_rules.setText(self._tr("orbital_rules_btn"))

        # Render params
        self.lbl_render_style.setText(self._tr("lbl_style"))
        self.lbl_pos_phase.setText(self._tr("lbl_pos_phase"))
        self.lbl_neg_phase.setText(self._tr("lbl_neg_phase"))
        self.lbl_render_res.setText(self._tr("lbl_res"))
        self.lbl_render_shading.setText(self._tr("lbl_shading"))
        self.rb_full.setText(self._tr("rb_full"))
        self.rb_medium.setText(self._tr("rb_medium"))
        self.var_auto.setText(self._tr("chk_auto"))
        self.var_open.setText(self._tr("chk_open"))
        self.var_trans_raster.setText(self._tr("chk_trans_raster"))
        self.lbl_render_threads.setText(self._tr("lbl_threads"))

        # Shading tooltips
        self.rb_full.setToolTip(self._tr("tooltip_full"))
        self.rb_medium.setToolTip(self._tr("tooltip_medium"))
        self.var_trans_raster.setToolTip(self._tr("tooltip_trans_raster"))
        self.var_threads.setToolTip(self._tr("tooltip_threads"))

        # Custom color buttons tooltip
        self.btn_pos_color.setToolTip(self._tr("pick_pos_color"))
        self.btn_neg_color.setToolTip(self._tr("pick_neg_color"))

        # Buttons
        self.btn_run.setText(self._tr("btn_run_cubes"))
        self.btn_preview.setText(self._tr("btn_preview"))
        self.btn_render.setText(self._tr("btn_render_view"))
        self.btn_flip_phase.setText(self._tr("btn_flip_phase"))
        self.btn_preview_mol.setText(self._tr("btn_preview_mol"))

        # Live adjustments
        self.lbl_live_iso.setText(self._tr("lbl_isovalue"))
        self.lbl_live_opacity.setText(self._tr("lbl_opacity"))

        # Hydrogen panel
        self.lbl_h_keep.setText(self._tr("lbl_keep_indices"))
        if self._h_hidden:
            self.btn_h_filter.setText(self._tr("btn_show_h"))
        else:
            self.btn_h_filter.setText(self._tr("btn_hide_h"))
        self.var_h_indices.setPlaceholderText(self._tr("placeholder_h_indices"))

        # Draw bond panel
        self.lbl_bond_color.setText(self._tr("lbl_color"))
        self.lbl_bond_type.setText(self._tr("lbl_type"))
        self.lbl_bond_mat.setText(self._tr("lbl_material"))
        self.lbl_bond_segments.setText(self._tr("lbl_segments"))
        self.lbl_bond_radius.setText(self._tr("lbl_radius"))
        self.btn_undo_bond.setText(self._tr("btn_undo"))
        self.btn_clear_bond.setText(self._tr("btn_clear_all"))

        # Canvas dash tools
        self.chk_dash_mode.setText(self._tr("chk_dash_mode"))

        # Progress
        self.progress_label.setText(self._tr("progress_ready"))

    def _setup_shortcuts(self):
        pass

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_PageUp:
            self._key_iso_up()
        elif key == Qt.Key_PageDown:
            self._key_iso_down()
        elif key == Qt.Key_Home:
            self._key_opacity_up()
        elif key == Qt.Key_End:
            self._key_opacity_down()
        else:
            super().keyPressEvent(event)

    # ── Drag & Drop ──────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            if ext in (".fchk", ".log", ".out", ".cub", ".cube"):
                self.var_path.setText(path)
                self._load_molecule(path)

    # ── Helper Methods ──

    def _make_style_icon(self, style):
        """Build a dual-color icon (pos|neg) for style combo preview."""
        VMD_BUILTIN = {
            12: (0.00, 1.00, 0.00),
            22: (0.00, 0.00, 1.00),
        }
        def _rgb(color_entry):
            if color_entry[1] is not None:
                return [int(c * 255) for c in color_entry[1:4]]
            return [int(c * 255) for c in VMD_BUILTIN.get(color_entry[0], (0.5, 0.5, 0.5))]

        pos = style.get("pos_color", [31, 0.5, 0.5, 0.5])
        neg = style.get("neg_color", [32, 0.5, 0.5, 0.5])
        r1, g1, b1 = _rgb(pos)
        r2, g2, b2 = _rgb(neg)

        pm = QPixmap(30, 13)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(r1, g1, b1))
        p.drawRoundedRect(0, 0, 14, 13, 2, 2)
        p.setBrush(QColor(r2, g2, b2))
        p.drawRoundedRect(16, 0, 14, 13, 2, 2)
        p.end()
        return QIcon(pm)

    def _append_log(self, msg):
        self.log_text.moveCursor(QTextCursor.End)
        self.log_text.insertPlainText(msg + "\n")
        self.log_text.moveCursor(QTextCursor.End)

    def _set_progress(self, msg):
        self.progress_label.setText(f"◆  {msg}")

    def _get_style_name(self):
        val = self.var_style.currentText().strip()
        if val:
            return val.split("  ")[0].strip()
        return "sob-art"

    def _get_orbitals(self):
        orb_str = self.var_orbital.text().strip()
        if not orb_str:
            return []
        return [x.strip() for x in orb_str.split(',') if x.strip()]

    def _add_orbital(self, orb):
        current = self.var_orbital.text().strip()
        if not current:
            self.var_orbital.setText(orb)
        else:
            orbs = [x.strip() for x in current.split(',') if x.strip()]
            if orb not in orbs:
                orbs.append(orb)
                self.var_orbital.setText(','.join(orbs))

    def _extract_orbital_name(self, cube_path):
        basename = os.path.basename(cube_path)
        name_without_ext = os.path.splitext(basename)[0]
        if '_MO' in name_without_ext:
            return name_without_ext.rsplit('_MO', 1)[1]
        return name_without_ext

    def _get_paths(self):
        return {
            "multiwfn": self.paths["multiwfn"],
            "vmd": self.paths["vmd"],
            "tachyon": self.paths.get("tachyon", backend.find_tachyon(os.path.dirname(self.paths["vmd"]))),
        }

    def _show_rules_dialog(self):
        """弹窗显示轨道编号规则。"""
        QMessageBox.information(self, self._tr("orbital_rules_btn"),
                                self._tr("orbital_rules"))

    def _open_orbital_browser(self):
        """解析 fchk 并填充画布下方的轨道表格。"""
        path = self.var_path.text().strip()
        if not path:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_select_file_or_folder"))
            return
        fchk_path = path if os.path.isfile(path) else None
        if not fchk_path:
            fchks = sorted(glob.glob(os.path.join(path, "*.fchk")))
            if not fchks:
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("msg_no_fchk"))
                return
            fchk_path = fchks[0]
        if not os.path.exists(fchk_path):
            return
        self._fill_orbital_table(fchk_path)

    def _make_orbital_table(self):
        """创建统一的轨道表格。"""
        t = QTableWidget()
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels([
            tr("dlg_orbital_col_energy_au"),
            tr("dlg_orbital_col_energy_ev"),
            tr("dlg_orbital_col_occ"),
            tr("dlg_orbital_col_tag"),
        ])
        oh = t.horizontalHeader()
        oh.setSectionResizeMode(0, QHeaderView.Stretch)
        oh.setSectionResizeMode(1, QHeaderView.Stretch)
        oh.setSectionResizeMode(2, QHeaderView.Stretch)
        oh.setSectionResizeMode(3, QHeaderView.Stretch)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.cellDoubleClicked.connect(self._on_table_orbital_clicked)
        return t

    def _fill_orbital_table(self, fchk_path):
        """解析 fchk 并填充轨道表格（闭壳层单表，开壳层 α/β 双 tab）。"""
        try:
            info = parse_fchk_mo_info(fchk_path)
        except Exception as e:
            self._append_log(f"轨道解析失败: {e}")
            return
        n_a = info["n_alpha"]
        n_b = info["n_beta"]
        homo = info["homo_idx"]
        lumo = info["lumo_idx"]
        alpha_e = info["alpha_energies"]
        beta_e = info.get("beta_energies") or []
        is_open = info["is_open_shell"]
        eV = 27.211386

        # ── 清理 β tab ──
        if self.orbital_table_beta:
            self.orbital_tabs.removeTab(1)
            self.orbital_table_beta.deleteLater()
            self.orbital_table_beta = None

        # ── 构建数据 ──
        if is_open:
            alpha_rows, beta_rows = [], []
            for i, e in enumerate(alpha_e, 1):
                occ = 1.0 if i <= n_a else 0.0
                tag = ""
                if i == n_a:     tag = "HOMO"
                elif i == n_a+1: tag = "LUMO"
                alpha_rows.append((i, e, e*eV, occ, tag))
            for i, e in enumerate(beta_e, 1):
                occ = 1.0 if i <= n_b else 0.0
                tag = ""
                if i == n_b:     tag = "HOMO"
                elif i == n_b+1: tag = "LUMO"
                beta_rows.append((i, e, e*eV, occ, tag))
        else:
            alpha_rows = []
            for i, e in enumerate(alpha_e, 1):
                occ = 2.0 if i <= n_a else 0.0
                tag = ""
                if i == homo:     tag = "HOMO"
                elif i == lumo:   tag = "LUMO"
                alpha_rows.append((i, e, e*eV, occ, tag))

        # ── 填充 α 表 ──
        self._populate_table(self.orbital_table_alpha, alpha_rows, is_open, n_a, orb_sign=1)
        self.orbital_tabs.setTabText(0, "α 轨道" if is_open else tr("dlg_orbital_browser"))

        # ── 开壳层：创建并填充 β 表 ──
        if is_open and beta_rows:
            self.orbital_table_beta = self._make_orbital_table()
            self.orbital_tabs.addTab(self.orbital_table_beta, "β 轨道")
            self._populate_table(self.orbital_table_beta, beta_rows, is_open, n_b, orb_sign=-1)

        self._append_log(
            f"已解析 {len(alpha_rows)}{' + '+str(len(beta_rows)) if is_open else ''}"
            f" 个轨道 (HOMO={homo}, LUMO={lumo if lumo else 'N/A'})")

    def _populate_table(self, table, rows, is_open, homo_idx, orb_sign):
        """填充单个轨道表格。orb_sign=1 为正索引，-1 为负索引（β）。"""
        table.setRowCount(len(rows))
        for r, (orb, energy, ev, occ, tag) in enumerate(rows):
            # orb_sign=-1 → β 轨道，需转 Multiwfn 的 hb/lb 写法
            if orb_sign == -1 and homo_idx:
                if orb == homo_idx:
                    mw_orb = "hb"
                elif orb == homo_idx + 1:
                    mw_orb = "lb"
                elif orb < homo_idx:
                    mw_orb = f"hb-{homo_idx - orb}"
                else:
                    mw_orb = f"lb+{orb - homo_idx - 1}"
            else:
                mw_orb = str(orb)  # α or closed-shell: just the number
            full_orb = orb * orb_sign  # display-only
            # 能量 a.u. (col 0)
            it0 = QTableWidgetItem(f"{energy:.6f}")
            it0.setTextAlignment(Qt.AlignCenter)
            it0.setData(Qt.UserRole, full_orb)        # 显示用（填入 var_orbital）
            it0.setData(Qt.UserRole + 1, mw_orb)       # Multiwfn 用（传给 gen_cube）
            table.setItem(r, 0, it0)
            # 能量 eV (col 1)
            it1 = QTableWidgetItem(f"{ev:.4f}")
            it1.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, 1, it1)
            # 占据 (col 2)
            it2 = QTableWidgetItem(f"{occ:.1f}")
            it2.setTextAlignment(Qt.AlignCenter)
            if occ > 0:
                it2.setBackground(QColor("#E8F5E9"))
            table.setItem(r, 2, it2)
            # 标记 (col 3)
            it3 = QTableWidgetItem(tag)
            it3.setTextAlignment(Qt.AlignCenter)
            if tag == "HOMO":
                it3.setBackground(QColor("#FFF3E0"))
                it3.setFont(QFont("", -1, QFont.Bold))
            elif tag == "LUMO":
                it3.setBackground(QColor("#E3F2FD"))
                it3.setFont(QFont("", -1, QFont.Bold))
            table.setItem(r, 3, it3)
        # 滚动到 HOMO
        if homo_idx and homo_idx <= table.rowCount():
            table.scrollToItem(table.item(homo_idx-1, 0))

    def _on_table_orbital_clicked(self, row, _col):
        """双击轨道表格行 → 从 UserRole 取轨道编号并预览。"""
        table = self.orbital_tabs.currentWidget()
        if not table:
            return
        it = table.item(row, 0)
        if not it:
            return
        orb_display = str(it.data(Qt.UserRole))
        orb_mw = it.data(Qt.UserRole + 1) or orb_display  # Multiwfn 写法（开壳层 β 用 hb/lb）
        self.var_orbital.setText(orb_display)
        self._append_log(f"已选择轨道: {orb_display}" + (f" ({orb_mw})" if orb_mw != orb_display else ""))
        # ── DEBUG: 切换轨道前的状态 ──
        self._append_log(f"  [DEBUG SWITCH] vmd_port={self.vmd_port} current_iso={self.current_iso} "
                         f"_vmd_state={self._vmd_state} vmd_cube_path={self.vmd_cube_path}")
        self._auto_preview_orbital(orb_mw)

    def _auto_preview_orbital(self, orb_str):
        """选中轨道后：删旧 cube → 生成新 cube → VMD 刷新/启动。"""
        path = self.var_path.text().strip()
        out = self._get_out_dir(path)
        exe_paths = self._get_paths()
        if not os.path.exists(exe_paths["multiwfn"]):
            return

        # 确定 fchk 文件
        fchk_file = path if os.path.isfile(path) else None
        if not fchk_file:
            fchks = sorted(glob.glob(os.path.join(path, "*.fchk")))
            if not fchks:
                return
            fchk_file = fchks[0]

        # 删旧 cube
        self._clean_old_cubes(out)

        # 始终生成新 cube
        self._append_log(f"正在生成轨道 {orb_str} 的 cube...")
        grid = self.var_grid.currentText()
        self.worker = CubeWorker(
            [fchk_file], out, [orb_str], "0.05", grid, "sob-art",
            (1024, 768), "full", False, exe_paths, False)
        self.worker.log_signal.connect(self._append_log)
        self.worker.progress_signal.connect(self._set_progress)
        self.worker.finished_signal.connect(self._on_orbital_cube_ready)
        self.worker.start()

    def _on_orbital_cube_ready(self, _auto, ok, total, cubes):
        """cube 生成完毕 → 尝试 socket 刷新 VMD，失败则启动新实例。"""
        if not cubes:
            self._append_log("Cube 生成失败")
            return
        # cubes[0] 在单轨道模式下是字符串路径，多轨道是 (path, label) 元组
        cube_path = cubes[0] if isinstance(cubes[0], str) else cubes[0][0]
        self._append_log(f"  [DEBUG CUBE_READY] cube_path={cube_path} "
                         f"vmd_port={self.vmd_port}")
        self._launch_vmd_orbital(cube_path)

    def _clean_old_cubes(self, out_dir):
        """删除输出目录中的旧 .cub/.cube 文件。"""
        for f in glob.glob(os.path.join(out_dir, "*.cub")) + \
                 glob.glob(os.path.join(out_dir, "*.cube")):
            try:
                os.remove(f)
            except OSError:
                pass

    def _reset_orbital_state(self, cube_path, iso):
        """切换轨道后重置状态：rep 编号、isovalue 绝对值、相位标记。"""
        self._append_log(f"  [DEBUG RESET] BEFORE: iso={self.current_iso} state={self._vmd_state}")
        self.vmd_cube_path = cube_path
        self.current_iso = abs(float(iso))          # 始终存正值
        self._vmd_state["rep_pos"] = 1
        self._vmd_state["rep_neg"] = 2
        self._vmd_state["molid"] = 0
        self._vmd_orbital_labels = [os.path.basename(cube_path)]
        self._append_log(f"  [DEBUG RESET] AFTER:  iso={self.current_iso} state={self._vmd_state}")

    def _launch_vmd_orbital(self, cube_path):
        """启动或刷新 VMD：先尝试 socket 刷新，失败则启动新进程。"""
        self._append_log(f"  [DEBUG LAUNCH] vmd_port={self.vmd_port} cube={os.path.basename(cube_path)} "
                         f"→ {'refresh' if self.vmd_port else 'new VMD'}")
        if self.vmd_port and self._refresh_vmd_orbital(cube_path):
            self._append_log(f"  [DEBUG LAUNCH] refresh succeeded")
            return
        # 启动新 VMD
        self._append_log(f"  [DEBUG LAUNCH] falling back to _do_preview")
        self._do_preview(cube_path)

    def _refresh_vmd_orbital(self, cube_path):
        """通过 socket 刷新已运行的 VMD：删旧分子 → 加载新 cube → 应用样式。"""
        import tempfile as _tmp
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", self.vmd_port))

            # 删旧分子
            sock.sendall(b"if {[molinfo num] > 0} {mol delete top}\n")
            try:
                sock.recv(4096)
            except socket.timeout:
                pass

            # 复制 cube 到临时目录（避免中文路径）
            cube_name = os.path.basename(cube_path)
            tmp_dir = _tmp.mkdtemp(prefix="vmd_orbital_")
            tmp_cube = os.path.join(tmp_dir, cube_name)
            shutil.copy2(cube_path, tmp_cube)

            # 用 backend._style_tcl 生成完整场景（分子+等值面+着色）
            style_name = self._get_style_name()
            try:
                iso = float(self.iso_edit.text().strip())
            except ValueError:
                iso = 0.05
            style_tcl = backend._style_tcl(
                cube_name, isovalue=iso, style_name=style_name)
            tcl_path = os.path.join(tmp_dir, "_refresh.tcl")
            with open(tcl_path, "w", encoding="utf-8") as f:
                f.write(style_tcl)

            # 逐条执行关键命令
            cmds = [
                f"cd {tmp_dir.replace(chr(92), '/')}",
                "source _refresh.tcl",
                "display resetview",
            ]
            for cmd in cmds:
                sock.sendall((cmd + "\n").encode("utf-8"))
                try:
                    resp = sock.recv(4096)
                    if b"ERROR" in resp:
                        self._append_log(f"VMD: {resp.decode('utf-8', errors='replace').strip()}")
                except socket.timeout:
                    pass

            sock.close()
            self.vmd_render_dir = tmp_dir   # 更新目录，让 live style 切换能正确写入
            self.vmd_multi_cubes = None
            self._reset_orbital_state(cube_path, iso)   # 统一管理状态
            self._append_log(f"VMD 轨道已刷新: {os.path.basename(cube_path)}")
            return True
        except Exception as e:
            self._append_log(f"VMD socket 刷新失败: {e}")
            self.vmd_port = None
            return False

    def _build_paths_panel(self):
        """路径设置面板：Multiwfn 和 VMD 路径配置。"""
        grp = SciFiGroupBox("")
        self.grp_paths = grp
        layout = QVBoxLayout(grp)
        layout.setSpacing(4)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Multiwfn row
        mw_row = QHBoxLayout()
        self.path_mw_edit = QLineEdit(self.paths["multiwfn"])
        self.path_mw_edit.setMinimumWidth(300)
        mw_row.addWidget(self.path_mw_edit)
        btn_browse_mw = QPushButton(self._tr("btn_browse"))
        btn_browse_mw.clicked.connect(
            lambda: self._browse_file_dialog(self.path_mw_edit, "multiwfn"))
        mw_row.addWidget(btn_browse_mw)
        form.addRow(self._tr("lbl_multiwfn"), mw_row)

        # VMD row
        vmd_row = QHBoxLayout()
        self.path_vmd_edit = QLineEdit(self.paths["vmd"])
        self.path_vmd_edit.setMinimumWidth(300)
        vmd_row.addWidget(self.path_vmd_edit)
        btn_browse_vmd = QPushButton(self._tr("btn_browse"))
        btn_browse_vmd.clicked.connect(
            lambda: self._browse_file_dialog(self.path_vmd_edit, "vmd"))
        vmd_row.addWidget(btn_browse_vmd)
        form.addRow(self._tr("lbl_vmd"), vmd_row)

        layout.addLayout(form)

        btn_save = QPushButton(self._tr("btn_save"))
        btn_save.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_save.clicked.connect(lambda: self._do_save_paths(
            None, self.path_mw_edit.text().strip(), self.path_vmd_edit.text().strip()))
        layout.addWidget(btn_save)

        return grp

    @staticmethod
    def _ack_html(is_cn):
        if is_cn:
            return (
                "<p><b>Multiwfn</b><br>"
                "本软件的核心计算引擎来自 <b>卢天</b> 老师开发的 "
                "<b>Multiwfn</b> 多功能波函数分析程序，特此致以最诚挚的感谢！</p>"
                "<p style='font-size:9pt;color:#666'>"
                "Tian Lu, Feiwu Chen, <i>Multiwfn: A Multifunctional Wavefunction Analyzer</i>, "
                "J. Comput. Chem., 2012, 33, 580–592.<br>"
                "Tian Lu, <i>A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn</i>, "
                "J. Chem. Phys., 2024, 161, 082503. <i>(JCP Editors' Choice 2024)</i></p>"
                "<p>Multiwfn 目前已被超过 <b>4 万篇</b> 论文引用，用户遍布全球 <b>90 余国</b>。</p>"
                "<p><b>vcube2.0</b><br>"
                "渲染样式系统源自 <b>vcube2.0</b>（钟成老师），提供了 11 套精美的 VMD 轨道渲染配置。</p>"
                "<p><b>虚线绘制</b><br>"
                "VMD 虚线绘制功能来自 KeinSci 论坛 <b>Eming 老师</b> 的 <b>draw_bond Tcl 脚本</b>，特此致谢。</p>"
                "<p><b>VMD</b><br>"
                "Humphrey, W., Dalke, A. and Schulten, K., "
                "<i>VMD: Visual Molecular Dynamics</i>, J. Molec. Graphics, 1996, 14, 33–38.</p>"
                "<p><b>Tachyon</b><br>"
                "Stone, J. E., <i>An Efficient Library for Parallel Ray Tracing and Animation</i>, "
                "M.Sc. Thesis, University of Missouri-Rolla, 1998.</p>"
            )
        else:
            return (
                "<p><b>Multiwfn</b><br>"
                "The core calculation engine of this software comes from <b>Multiwfn</b>, "
                "a multifunctional wavefunction analysis program developed by <b>Prof. Tian Lu</b>. "
                "Our sincere gratitude!</p>"
                "<p style='font-size:9pt;color:#666'>"
                "Tian Lu, Feiwu Chen, <i>Multiwfn: A Multifunctional Wavefunction Analyzer</i>, "
                "J. Comput. Chem., 2012, 33, 580–592.<br>"
                "Tian Lu, <i>A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn</i>, "
                "J. Chem. Phys., 2024, 161, 082503. <i>(JCP Editors' Choice 2024)</i></p>"
                "<p>Multiwfn has been cited by over <b>40,000</b> papers across <b>90+</b> countries.</p>"
                "<p><b>vcube2.0</b><br>"
                "The rendering style system originates from <b>vcube2.0</b> (by Zhong Cheng), "
                "providing 11 elegant VMD orbital rendering presets.</p>"
                "<p><b>Draw Bond</b><br>"
                "The VMD dashed bond feature is based on the <b>draw_bond Tcl script</b> "
                "by <b>Eming 老师</b> from the KeinSci forum. Many thanks!</p>"
                "<p><b>VMD</b><br>"
                "Humphrey, W., Dalke, A. and Schulten, K., "
                "<i>VMD: Visual Molecular Dynamics</i>, J. Molec. Graphics, 1996, 14, 33–38.</p>"
                "<p><b>Tachyon</b><br>"
                "Stone, J. E., <i>An Efficient Library for Parallel Ray Tracing and Animation</i>, "
                "M.Sc. Thesis, University of Missouri-Rolla, 1998.</p>"
            )

    def _build_acknowledgments_box(self):
        """构建致谢面板（QTextBrowser 放路径设置下方）。"""
        grp = SciFiGroupBox("")

        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setStyleSheet("QTextBrowser { border: none; background: transparent; font-family: 'Microsoft YaHei'; }")
        tb.setHtml(self._ack_html(_CURRENT_LANG == "zh"))

        layout = QVBoxLayout(grp)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tb)
        self._ack_box = grp

        return grp

    def _update_acknowledgments(self):
        if hasattr(self, '_ack_box'):
            self._ack_box.setTitle(self._tr("grp_acknowledgments"))
            tb = self._ack_box.findChild(QTextBrowser)
            if tb:
                tb.setHtml(self._ack_html(_CURRENT_LANG == "zh"))

    @staticmethod
    def _browse_file_dialog(target_widget, which):
        path, _ = QFileDialog.getOpenFileName(
            None, f"Select {which}", "",
            "Executables (*.exe);;All Files (*)")
        if path:
            target_widget.setText(path)

    def _do_save_paths(self, dlg, mw, vmd):
        if mw:
            self.paths["multiwfn"] = mw
            self.path_mw_edit.setText(mw)
        if vmd:
            self.paths["vmd"] = vmd
            self.path_vmd_edit.setText(vmd)
        tachyon = backend.find_tachyon(os.path.dirname(vmd or self.paths["vmd"]))
        backend.save_config(
            self.paths["multiwfn"], self.paths["vmd"], tachyon)
        self._append_log(self._tr("log_paths_saved",
                                  mw=self.paths["multiwfn"],
                                  vmd=self.paths["vmd"]))
        if dlg:
            dlg.accept()

    def _get_params(self):
        orbitals = self._get_orbitals()
        orbital = orbitals[0] if orbitals else ""
        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05
        grid = self.var_grid.currentText().strip()
        style_name = self._get_style_name()
        try:
            res_str = self.var_res.currentText().strip()
            w, h = res_str.split("x")
            resolution = (int(w), int(h))
        except (ValueError, AttributeError):
            resolution = (2000, 1500)
        shade_id = self.shade_group.checkedId()
        shade_mode = "full" if shade_id == 0 else "medium"
        return orbital, iso, grid, style_name, resolution, shade_mode

    # ── Browse Methods ──

    def _browse_input(self):
        if self.mode_group.checkedId() == 0:
            path = QFileDialog.getExistingDirectory(self, self._tr("dlg_select_input_folder"))
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, self._tr("dlg_select_input_file"), "",
                self._tr("dlg_input_filter"))
        if path:
            self.var_path.setText(path)
            self._load_molecule(path)

    def _load_molecule(self, path):
        """Parse fchk/cub/log atoms and display in MolCanvas."""
        if not path or not os.path.isfile(path):
            return
        ext = os.path.splitext(path)[1].lower()
        atoms, bonds = [], []
        if ext == ".fchk":
            parser = get_atoms_from_fchk
            bond_parser = get_bonds_from_fchk
        elif ext in (".cub", ".cube"):
            parser = get_atoms_from_cube
            bond_parser = get_bonds_from_cube
        elif ext in (".log", ".out"):
            # Use Gaussian log parser from backend
            try:
                atoms, bonds = backend.parse_log(path)
            except Exception:
                atoms, bonds = [], []
            if atoms:
                self.mol_canvas.set_data(atoms, bonds)
                self._current_fchk = None
                self.btn_run.setEnabled(False)
                self.btn_preview.setEnabled(False)
                self.btn_render.setEnabled(False)
                self.btn_preview_mol.setEnabled(True)
                self.btn_preview_mol.show()
                self.chk_dash_mode.setEnabled(True)
                self._update_color_buttons()
                # Show log file info
                log_info = backend.parse_log_info(path)
                info_str = " | ".join(f"{k}: {v}" for k, v in log_info.items())
                self._append_log(
                    f"{len(atoms)} atoms, {len(bonds)} bonds  |  {os.path.basename(path)}\n"
                    f"  {info_str}")
                return
            else:
                self._append_log(f"Failed to parse log file: {os.path.basename(path)}")
                return
        else:
            return
        try:
            atoms = parser(path)
            if atoms:
                bonds = bond_parser(atoms)
                self.mol_canvas.set_data(atoms, bonds)
                self._current_fchk = path
                self.btn_run.setEnabled(True)  # fchk 需要生成 cub
                self.chk_dash_mode.setEnabled(True)
                self._update_color_buttons()
                self._append_log(
                    self._tr("mol_hint_atoms",
                             natoms=len(atoms), nbonds=len(bonds),
                             name=os.path.basename(path)))
                # 自动填充轨道表格
                if ext == ".fchk":
                    self._fill_orbital_table(path)
                # 载入 .cub/.cube 文件：禁用"生成cub"，直接预览此文件
                if ext in (".cub", ".cube"):
                    self._current_cubes = [path]
                    self.btn_preview.setEnabled(True)
                    self.btn_run.setEnabled(False)
                    self._append_log(
                        self._tr("log_start_preview").format(os.path.basename(path)))
            else:
                self._append_log(self._tr("mol_hint_no_atoms"))
        except Exception as e:
            import traceback
            self.log_text.append(f"Parse error: {e}\n{traceback.format_exc()}")

    # ── Core Actions ──

    def _get_out_dir(self, input_path=None):
        """输出目录 = 输入目录。"""
        if input_path is None:
            input_path = self.var_path.text().strip()
        return input_path if os.path.isdir(input_path) else os.path.dirname(input_path)

    def _run_cubes(self):
        if self.running:
            return
        path = self.var_path.text().strip()
        if not path:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_select_file_or_folder"))
            return

        # Auto-parse molecular structure
        self._load_molecule(path)

        exe_paths = self._get_paths()
        if not os.path.exists(exe_paths["multiwfn"]):
            QMessageBox.warning(self, self._tr("msg_title_error"),
                self._tr("msg_mw_not_found", path=exe_paths['multiwfn']))
            return
        if not os.path.exists(exe_paths["vmd"]):
            QMessageBox.warning(self, self._tr("msg_title_error"),
                self._tr("msg_vmd_not_found", path=exe_paths['vmd']))
            return

        files = (sorted(glob.glob(os.path.join(path, "*.fchk")))
                 if os.path.isdir(path) else [path])
        if not files:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_no_fchk"))
            return

        out = self._get_out_dir(path)
        os.makedirs(out, exist_ok=True)

        orbitals = self._get_orbitals()
        if not orbitals:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_enter_orbital"))
            return

        orbital, iso, grid, style_name, resolution, shade_mode = self._get_params()
        auto_render = self.var_auto.isChecked()
        do_open = self.var_open.isChecked()

        self.running = True
        self._set_buttons_state("running")

        self.worker = CubeWorker(
            files, out, orbitals, iso, grid, style_name,
            resolution, shade_mode, auto_render, exe_paths, do_open)
        self.worker.log_signal.connect(self._append_log)
        self.worker.progress_signal.connect(self._set_progress)
        self.worker.finished_signal.connect(self._on_cubes_done)
        self.worker.start()

    def _on_cubes_done(self, auto_render, ok, total, cubes):
        self.running = False
        self._set_buttons_state("idle")

        if not auto_render and cubes:
            self._current_cubes = cubes
            self._append_log(self._tr("log_done_hint"))
            self.btn_preview.setEnabled(True)

        if auto_render:
            self._append_log(self._tr("log_all_done", ok=ok, total=total))
            self._set_progress(self._tr("progress_done", ok=ok, total=total))
            if self.var_open.isChecked() and ok > 0 and cubes:
                out = self._get_out_dir()
                os.startfile(out)

    def _preview_mol(self):
        """Write atoms to XYZ directly, then launch VMD molecule preview."""
        path = self.var_path.text().strip()
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".log", ".out"):
            self._append_log("Only .log/.out files supported for molecule preview")
            return

        exe_paths = self._get_paths()
        if not os.path.exists(exe_paths["vmd"]):
            QMessageBox.warning(self, self._tr("msg_title_error"),
                self._tr("msg_vmd_not_found", path=exe_paths['vmd']))
            return

        # 直接用画布里已解析的 atoms 写 XYZ（不走 Multiwfn）
        atoms = self.mol_canvas.atoms
        if not atoms:
            self._append_log("No atoms loaded — re-parse log...")
            try:
                atoms, _ = backend.parse_log(path)
            except Exception:
                self._append_log("Parse log failed")
                return
            if not atoms:
                self._append_log("No atoms found in log file")
                return

        out_dir = self._get_out_dir(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        xyz_path = os.path.join(out_dir, f"{stem}.xyz")

        with open(xyz_path, "w", encoding="utf-8") as f:
            f.write(f"{len(atoms)}\n")
            f.write(f"Generated from {os.path.basename(path)}\n")
            for a in atoms:
                # atoms format: (center_num, symbol, atomic_num, (x, y, z))
                sym = a[1]
                x, y, z = a[3]
                f.write(f"{sym:>2s} {x:12.6f} {y:12.6f} {z:12.6f}\n")

        self._append_log(f"xyz written: {os.path.basename(xyz_path)} ({len(atoms)} atoms)")
        self._append_log(f"Launching VMD molecule preview...")

        style_name = self._get_style_name()
        try:
            port, render_dir, vmd_proc = backend.preview_mol(
                xyz_path, style_name=style_name,
                representation="CPK", cpk_scale="1.0",
                vmd_exe=exe_paths["vmd"])
            self.vmd_port = port
            self.vmd_render_dir = render_dir
            self._vmd_proc = vmd_proc
            self._reset_orbital_state(xyz_path, 0.0)
            self._vmd_state["molid"] = 0
            self._vmd_orbital_labels = [os.path.basename(xyz_path)]
            self.iso_slider.setEnabled(False)
            self.iso_edit.setEnabled(False)
            self.opacity_slider.setEnabled(True)
            self.opacity_edit.setEnabled(True)
            self.btn_render.setEnabled(True)
            self.btn_preview_mol.setEnabled(False)
            self.btn_undo_bond.setEnabled(True)
            self.btn_clear_bond.setEnabled(True)
            self.btn_h_filter.setEnabled(True)
            self.chk_dash_mode.setEnabled(True)
            # Canvas → VMD dash sync
            self.mol_canvas.on_dash_added = self._vmd_draw_dash
            self.mol_canvas.on_dash_undone = self._vmd_undo_bond
            self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
            self._vmd_dash_pairs.clear()
            for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                pair = (a1, a2)
                if pair not in self._vmd_dash_pairs:
                    self._vmd_dash_pairs.append(pair)
            if self._vmd_dash_pairs:
                self._send_vmd_cmd("")
                self._vmd_reapply_dashes()
            self.btn_flip_phase.setEnabled(False)
            self._append_log(f"VMD ready (port {port}) — molecule: {os.path.basename(xyz_path)}")
        except Exception as e:
            self._append_log(f"VMD launch failed: {e}")

    def _preview(self):
        path = self.var_path.text().strip()
        out = self._get_out_dir(path)

        # 如果是直接载入的 .cub 文件，用已有的 cube 列表
        ext = os.path.splitext(path)[1].lower() if os.path.isfile(path) else ""
        if ext in (".cub", ".cube") and self._current_cubes:
            all_cubes = list(self._current_cubes)
        else:
            all_cubes = sorted(glob.glob(os.path.join(out, "*.cub")))
        if not all_cubes:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_no_cube"))
            return

        from PyQt5.QtWidgets import QListWidget

        if len(all_cubes) == 1:
            self._do_preview(all_cubes[0])
        else:
            dlg = QDialog(self)
            dlg.setWindowTitle(self._tr("dlg_select_orbitals"))
            dlg.resize(500, 420)
            dlg_layout = QVBoxLayout(dlg)

            dlg_layout.addWidget(QLabel(
                self._tr("dlg_select_orbitals_hint")))

            list_widget = QListWidget()
            list_widget.setSelectionMode(QListWidget.ExtendedSelection)
            for i, c in enumerate(all_cubes):
                list_widget.addItem(os.path.basename(c))
                list_widget.item(i).setSelected(True)
            dlg_layout.addWidget(list_widget)

            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dlg.accept)
            btn_box.rejected.connect(dlg.reject)
            dlg_layout.addWidget(btn_box)

            if dlg.exec_() != QDialog.Accepted:
                return

            selected = [all_cubes[i.row()] for i in list_widget.selectedIndexes()]
            if not selected:
                return

            if len(selected) == 1:
                self._do_preview(selected[0])
            else:
                cubes = [(c, self._extract_orbital_name(c)) for c in selected]
                self._do_preview_multi(cubes)

    def _do_preview(self, cube_path):
        self._close_persist_sock()
        self._vmd_orbital_labels = [os.path.basename(cube_path)]
        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05

        style_name = self._get_style_name()
        _, _, _, _, _, shade_mode = self._get_params()
        exe_paths = self._get_paths()

        self.current_iso = iso
        self.current_opacity = None
        self._vmd_style_applied = style_name

        self._append_log(self._tr("log_start_preview").format(os.path.basename(cube_path)))
        self._append_log(self._tr("log_style_iso").format(style_name, iso))
        self._append_log(self._tr("log_adjust_view"))

        try:
            port, render_dir = backend.preview_cube(
                cube_path, isovalue=iso, style_name=style_name,
                vmd_exe=exe_paths["vmd"], shade_mode=shade_mode)
            if port:
                self.vmd_port = port
                self.vmd_render_dir = render_dir
                # ── 同步 VMD 会话状态 ──
                self._vmd_session.port = port
                self._vmd_session.render_dir = render_dir
                self._vmd_session._current_style = style_name
                self._vmd_session._current_isovalue = iso
                self.vmd_multi_cubes = None
                self._reset_orbital_state(cube_path, iso)   # 统一管理状态
                self.btn_render.setEnabled(True)
                self.btn_undo_bond.setEnabled(True)
                self.btn_clear_bond.setEnabled(True)
                self.btn_h_filter.setEnabled(True)
                self.chk_dash_mode.setEnabled(True)
                # Canvas → VMD dash sync setup
                self.mol_canvas.on_dash_added = self._vmd_draw_dash
                self.mol_canvas.on_dash_undone = self._vmd_undo_bond
                self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
                self._vmd_dash_pairs.clear()
                for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                    pair = (a1, a2)
                    if pair not in self._vmd_dash_pairs:
                        self._vmd_dash_pairs.append(pair)
                # Replay existing dashes on new VMD
                if self._vmd_dash_pairs:
                    self._send_vmd_cmd("")
                    self._vmd_reapply_dashes()
                self.iso_slider.setEnabled(True)
                self.iso_slider.blockSignals(True)
                self.iso_slider.setValue(int(iso * 1000))
                self.iso_slider.blockSignals(False)
                self.iso_edit.setEnabled(True)
                self.iso_edit.setText(f"{iso:.3f}")
                self.opacity_slider.setEnabled(True)
                self.opacity_edit.setEnabled(True)
                if self.current_opacity is None:
                    style = backend.STYLES.get(style_name, backend.STYLES["sob-art"])
                    self.current_opacity = style["surface_mat"][5]
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(int(self.current_opacity * 100))
                self.opacity_slider.blockSignals(False)
                self.opacity_edit.setText(f"{self.current_opacity:.2f}")
                self.btn_flip_phase.setEnabled(True)
                self._append_log(self._tr("log_vmd_started", port=port))
            else:
                self._append_log(self._tr("log_vmd_failed"))
        except Exception as e:
            self._append_log(self._tr("log_vmd_error").format(e))

    def _do_preview_multi(self, cubes):
        self._close_persist_sock()
        orbitals = [orb for _, orb in cubes]
        self._vmd_orbital_labels = orbitals
        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05

        style_name = self._get_style_name()
        _, _, _, _, _, shade_mode = self._get_params()
        exe_paths = self._get_paths()

        h_str = self.var_h_indices.text().strip()
        if h_str:
            try:
                keep_h_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
            except ValueError:
                keep_h_indices = []
        else:
            keep_h_indices = None

        self.current_iso = iso
        self.current_opacity = None
        self._vmd_style_applied = style_name

        orb_names = ", ".join([orb for _, orb in cubes])
        self._append_log(self._tr("log_start_preview_multi").format(orb_names))
        self._append_log(self._tr("log_style_iso").format(style_name, iso))
        self._append_log(self._tr("log_adjust_view"))

        try:
            port, render_dir, copied_cubes = backend.preview_multi_cubes(
                cubes, iso, style_name=style_name,
                vmd_exe=exe_paths["vmd"], shade_mode=shade_mode,
                keep_h_indices=keep_h_indices)
            if port:
                self.vmd_port = port
                self.vmd_render_dir = render_dir
                # ── 同步 VMD 会话状态 ──
                self._vmd_session.port = port
                self._vmd_session.render_dir = render_dir
                self._vmd_session._current_style = style_name
                self._vmd_session._current_isovalue = iso
                self._vmd_session._multi_cubes = copied_cubes
                self.vmd_multi_cubes = copied_cubes
                self.vmd_cube_path = None
                self.btn_render.setEnabled(True)
                self.btn_undo_bond.setEnabled(True)
                self.btn_clear_bond.setEnabled(True)
                self.btn_h_filter.setEnabled(True)
                self.chk_dash_mode.setEnabled(True)
                # Canvas → VMD dash sync setup
                self.mol_canvas.on_dash_added = self._vmd_draw_dash
                self.mol_canvas.on_dash_undone = self._vmd_undo_bond
                self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
                self._vmd_dash_pairs.clear()
                for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                    pair = (a1, a2)
                    if pair not in self._vmd_dash_pairs:
                        self._vmd_dash_pairs.append(pair)
                if self._vmd_dash_pairs:
                    self._send_vmd_cmd("")
                    self._vmd_reapply_dashes()
                self.iso_slider.setEnabled(True)
                self.iso_slider.blockSignals(True)
                self.iso_slider.setValue(int(iso * 1000))
                self.iso_slider.blockSignals(False)
                self.iso_edit.blockSignals(True)
                self.iso_edit.setText(f"{iso:.3f}")
                self.iso_edit.blockSignals(False)
                self.iso_edit.setEnabled(True)
                self.opacity_slider.setEnabled(True)
                self.opacity_edit.setEnabled(True)
                if self.current_opacity is None:
                    style = backend.STYLES.get(style_name, backend.STYLES["sob-art"])
                    self.current_opacity = style["surface_mat"][5]
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(int(self.current_opacity * 100))
                self.opacity_slider.blockSignals(False)
                self.opacity_edit.setText(f"{self.current_opacity:.2f}")
                self.btn_flip_phase.setEnabled(True)
                self._append_log(self._tr("log_vmd_started", port=port))
            else:
                self._append_log(self._tr("log_vmd_failed"))
        except Exception as e:
            self._append_log(self._tr("log_vmd_error").format(e))

    def _render_view(self):
        if not self.vmd_port or not self.vmd_render_dir:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_preview_first"))
            return

        out = self._get_out_dir()
        os.makedirs(out, exist_ok=True)

        _, _, _, style_name, resolution, shade_mode = self._get_params()
        exe_paths = self._get_paths()

        output_png = None
        if self.vmd_cube_path:
            cube_stem = os.path.splitext(os.path.basename(self.vmd_cube_path))[0]
            fchk_name = cube_stem.rsplit("_MO", 1)[0]
            orbital = self._get_orbitals()
            orbital_str = ",".join(orbital) if orbital else "unknown"
            output_png = os.path.join(out, f"{fchk_name}_MO{orbital_str}.png") if out else None
        elif self.vmd_multi_cubes and self.vmd_multi_cubes[0][0]:
            cube_stem = os.path.splitext(os.path.basename(self.vmd_multi_cubes[0][0]))[0]
            fchk_name = cube_stem.rsplit("_MO", 1)[0]
            orbitals = self._get_orbitals()
            orbital_suffix = "_".join(orbitals) if orbitals else "multi"
            output_png = os.path.join(out, f"{fchk_name}_MO{orbital_suffix}.png") if out else None

        trans_raster = self.var_trans_raster.isChecked()
        threads = int(self.var_threads.text())

        self.btn_render.setEnabled(False)
        self.render_worker = RenderWorker(
            self.vmd_port, self.vmd_render_dir, output_png,
            exe_paths["tachyon"], resolution, style_name,
            shade_mode, trans_raster, threads)
        self.render_worker.log_signal.connect(self._append_log)
        self.render_worker.finished_signal.connect(self._on_render_done)
        self.render_worker.start()

    def _on_render_done(self, png_path):
        self.btn_render.setEnabled(True)
        if png_path and os.path.exists(png_path):
            os.startfile(png_path)

    def _stop(self):
        self.running = False
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()

    # ── Hydrogen Filter ──

    def _toggle_h_filter(self):
        if not self.vmd_port:
            self._append_log(self._tr("log_preview_first_hint"))
            return

        if not self._h_hidden:
            self._h_hidden = True
            self.btn_h_filter.setText(self._tr("btn_show_h"))
            h_str = self.var_h_indices.text().strip()
            if h_str:
                try:
                    keep_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                    # VMD index 是 0-based，画布编号是 1-based，需要减1
                    vmd_indices = [str(i - 1) for i in keep_indices]
                    idx_str = " ".join(vmd_indices)
                    sel_str = f"not element H or (element H and index {idx_str})"
                except ValueError:
                    sel_str = "not element H"
            else:
                sel_str = "not element H"
            cmd = (
                f'foreach mid [molinfo list] {{'
                f'  mol modselect 0 $mid "{sel_str}"'
                f'}}'
            )
            self._send_vmd_cmd(cmd)
            self._append_log(self._tr("log_hide_h_done"))
        else:
            self._h_hidden = False
            self.btn_h_filter.setText(self._tr("btn_hide_h"))
            cmd = 'foreach mid [molinfo list] { mol modselect 0 $mid all }'
            self._send_vmd_cmd(cmd)
            self._append_log(self._tr("log_show_h_done"))

    # ── Draw Bond Methods (移植自 MolViewer) ──

    # ── Draw Bond Methods (Python 实现，graphics top delete all 安全) ──

    def _vmd_delete_all_user_gfx(self):
        """删除全部用户图形（graphics top delete all 不影响等值面）。"""
        self._send_vmd_cmd("graphics top delete all")

    def _vmd_draw_one(self, a1, a2, log=True):
        """向 VMD 发送虚线命令，全部 6 种风格均为虚线分段。"""
        if not self.vmd_port:
            return False
        atoms = self.mol_canvas.atoms
        a1_idx = int(a1) - 1
        a2_idx = int(a2) - 1
        if a1_idx >= len(atoms) or a2_idx >= len(atoms):
            return False
        pos1 = atoms[a1_idx][3]
        pos2 = atoms[a2_idx][3]
        x1, y1, z1 = pos1
        x2, y2, z2 = pos2

        gap = self.bond_nbars_slider.value() / 100.0
        radius = self.bond_radius_slider.value() / 100.0
        color_hex = getattr(self.mol_canvas, 'dash_color_hex', '#000000')
        vmd_color = self._hex_to_vmd_color(color_hex)
        mat = self._bond_mat_map.get(self.var_bond_mat.currentText(), "Opaque")
        h_type = self._resolve_bond_tcl_key(self.var_bond_type.currentText(), is_color=False)
        h_resol = 6

        dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
        length = (dx*dx + dy*dy + dz*dz) ** 0.5
        if length < 0.001:
            return False

        n_bars = max(1, int(length / gap))
        ratio = 0.7

        self._send_vmd_cmd(f"graphics top color {vmd_color}; graphics top material {mat}")

        if h_type == "dots":
            for i in range(n_bars):
                t = (i + 0.5) / n_bars
                cx, cy, cz = x1+dx*t, y1+dy*t, z1+dz*t
                self._send_vmd_cmd(f"graphics top sphere {{{cx} {cy} {cz}}} radius {radius} resolution 12")

        elif h_type == "pymol":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top cylinder {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")

        elif h_type == "cylinder":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top cylinder {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")

        elif h_type == "sphere":
            for i in range(n_bars):
                t = (i + 0.5) / n_bars
                cx, cy, cz = x1+dx*t, y1+dy*t, z1+dz*t
                self._send_vmd_cmd(f"graphics top sphere {{{cx} {cy} {cz}}} radius {radius} resolution 12")

        elif h_type == "cone":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top cone {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")

        elif h_type == "line":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top line {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}}")

        if log:
            self._append_log(self._tr("log_draw_bond_ok", a1=a1, a2=a2,
                                       color=color_hex, btype=h_type, mat=mat))
        return True

    def _hex_to_vmd_color(self, hex_str):
        """将 #rrggbb 转为最接近的 VMD 内建颜色名。"""
        if not hex_str.startswith('#'):
            return hex_str
        r = int(hex_str[1:3], 16) / 255.0
        g = int(hex_str[3:5], 16) / 255.0
        b = int(hex_str[5:7], 16) / 255.0
        named = [
            (0.00, 0.00, 0.00, "black"), (1.00, 1.00, 1.00, "white"),
            (1.00, 0.00, 0.00, "red"), (0.00, 1.00, 0.00, "green"),
            (0.00, 0.00, 1.00, "blue"), (1.00, 1.00, 0.00, "yellow"),
            (0.00, 1.00, 1.00, "cyan"), (1.00, 0.00, 1.00, "magenta"),
            (0.50, 0.50, 0.50, "gray"), (0.75, 0.75, 0.75, "silver"),
            (1.00, 0.50, 0.00, "orange"), (0.50, 0.00, 0.50, "purple"),
            (0.00, 0.50, 0.00, "green2"), (0.50, 0.50, 0.00, "yellow2"),
            (0.00, 0.00, 0.50, "blue2"), (0.50, 0.00, 0.00, "red2"),
            (0.65, 0.16, 0.16, "brickred"),
        ]
        best, best_d = "black", 999.0
        for nr, ng, nb, name in named:
            d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
            if d < best_d:
                best, best_d = name, d
        return best

    def _vmd_reapply_dashes(self):
        """用当前样式重绘全部虚线（graphics top delete all 安全，不动等值面）。"""
        if not self._vmd_dash_pairs:
            return
        self._send_vmd_cmd("graphics top delete all")
        for a1, a2 in self._vmd_dash_pairs:
            self._vmd_draw_one(a1, a2, log=False)

    def _vmd_draw_dash(self, a1, a2):
        """画布虚线同步回调：在 VMD 中画虚线并记录。"""
        if not self.vmd_port:
            return
        if self._vmd_draw_one(a1, a2):
            pair = (int(a1), int(a2))
            if pair not in self._vmd_dash_pairs:
                self._vmd_dash_pairs.append(pair)
            self._update_dash_status()

    def _vmd_undo_bond(self):
        """VMD 撤销最后一根虚线（删掉全部再重绘剩余）。"""
        if self._vmd_dash_pairs:
            self._vmd_dash_pairs.pop()
        self._send_vmd_cmd("graphics top delete all")
        for a1, a2 in self._vmd_dash_pairs:
            self._vmd_draw_one(a1, a2, log=False)
        self._append_log(self._tr("log_undo_bond"))

    def _vmd_clear_bonds(self):
        """清空 VMD 虚线（只清 graphics，不动等值面）。"""
        self._send_vmd_cmd("graphics top delete all")
        self._vmd_dash_pairs.clear()
        self._append_log(self._tr("log_clear_bond"))

    def _undo_bond(self):
        # Remove from canvas
        if hasattr(self, 'mol_canvas'):
            self.mol_canvas.undo_last_dash_line()
        # VMD: 用 draw_bond_redraw + 重绘（不删等值面）
        self._send_vmd_cmd("draw_bond_redraw")
        if self._vmd_dash_pairs:
            self._vmd_dash_pairs.pop()
            for a1, a2 in self._vmd_dash_pairs:
                self._vmd_draw_one(a1, a2, log=False)
        self._append_log(self._tr("log_undo_bond"))

    def _clear_bond(self):
        # Clear canvas
        if hasattr(self, 'mol_canvas'):
            self.mol_canvas.clear_dash_lines()
        # VMD: 用 draw_bond_redraw 清空（不删等值面）
        self._send_vmd_cmd("draw_bond_redraw")
        self._vmd_dash_pairs.clear()
        self._append_log(self._tr("log_clear_bond"))

    def _on_style_changed(self, _text=None):
        """VMD预览已启动时，切换样式立即刷新VMD（委托给库会话）。"""
        self._custom_pos_rgb = None  # 切换风格时重置自定义颜色
        self._custom_neg_rgb = None
        self._update_color_buttons()
        if not self.vmd_port:
            return
        style_name = self._get_style_name()
        if not style_name or style_name == self._vmd_style_applied:
            return
        _, _, _, _, _, shade_mode = self._get_params()
        ok = self._vmd_session.set_style(style_name, shade_mode=shade_mode)
        if ok:
            self._vmd_style_applied = style_name
            self._append_log(self._tr("log_style_live_updated").format(style_name))

    def _update_color_buttons(self):
        """更新颜色按钮的背景色，优先用自定义颜色，否则用风格默认。"""
        style_name = self._get_style_name()
        style = backend.STYLES.get(style_name, None)
        if style is None:
            return
        pc = style["pos_color"]
        nc = style["neg_color"]
        pos_rgb = self._custom_pos_rgb if self._custom_pos_rgb else \
                  self._resolve_color_rgb(pc)
        neg_rgb = self._custom_neg_rgb if self._custom_neg_rgb else \
                  self._resolve_color_rgb(nc)
        self.btn_pos_color.setStyleSheet(
            f"background:rgb({pos_rgb[0]},{pos_rgb[1]},{pos_rgb[2]}); "
            "border:2px solid #999; border-radius:14px;")
        self.btn_neg_color.setStyleSheet(
            f"background:rgb({neg_rgb[0]},{neg_rgb[1]},{neg_rgb[2]}); "
            "border:2px solid #999; border-radius:14px;")
        # 自定义时加粗边框提示
        if self._custom_pos_rgb:
            self.btn_pos_color.setStyleSheet(
                f"background:rgb({pos_rgb[0]},{pos_rgb[1]},{pos_rgb[2]}); "
                "border:3px solid #FFD700; border-radius:14px;")
        if self._custom_neg_rgb:
            self.btn_neg_color.setStyleSheet(
                f"background:rgb({neg_rgb[0]},{neg_rgb[1]},{neg_rgb[2]}); "
                "border:3px solid #FFD700; border-radius:14px;")

    def _resolve_color_rgb(self, color_def):
        """把样式的颜色定义 [ColorID, R,G,B 或 None] 转为 (R*255, G*255, B*255) 0-255 整数。"""
        import math
        if len(color_def) == 4 and color_def[1] is not None:
            r = int(round(color_def[1] * 255))
            g = int(round(color_def[2] * 255))
            b = int(round(color_def[3] * 255))
            return (r, g, b)
        cid = color_def[0]
        # VMD ColorID → 默认 RGB (VMD 1.9.3 color scale)
        VMD_COLORS = {
            0: (0, 0, 255), 1: (255, 0, 0), 2: (128, 128, 128), 3: (255, 165, 0),
            4: (255, 255, 0), 5: (0, 255, 0), 6: (0, 255, 255), 7: (255, 0, 255),
            8: (128, 0, 128), 9: (0, 128, 128), 10: (128, 128, 0), 11: (0, 128, 0),
            12: (0, 128, 0), 13: (0, 128, 0), 14: (0, 128, 0), 15: (0, 128, 0),
            16: (0, 128, 0), 17: (0, 0, 255), 18: (255, 255, 255), 19: (255, 0, 255),
            20: (0, 255, 255), 21: (255, 255, 0), 22: (0, 0, 255),
            23: (255, 0, 0), 24: (0, 255, 0), 25: (0, 255, 255),
            26: (255, 0, 255), 27: (255, 255, 0), 28: (255, 165, 0),
            29: (255, 192, 203), 30: (255, 105, 180), 31: (0, 255, 0),
            32: (0, 0, 255), 33: (255, 255, 0),
        }
        return VMD_COLORS.get(cid, (128, 128, 128))

    def _pick_phase_color(self, lobe):
        """弹出颜色对话框选择自定义相位颜色。"""
        from PyQt5.QtWidgets import QColorDialog
        from PyQt5.QtGui import QColor
        current = self._custom_pos_rgb if lobe == "pos" else self._custom_neg_rgb
        if current is None:
            style = backend.STYLES.get(self._get_style_name(), None)
            if style:
                cd = style["pos_color"] if lobe == "pos" else style["neg_color"]
                current = self._resolve_color_rgb(cd)
            else:
                current = (0, 128, 0) if lobe == "pos" else (0, 0, 255)
        init = QColor(current[0], current[1], current[2])
        title_key = "pick_color_title" if lobe == "pos" else "pick_color_title_neg"
        color = QColorDialog.getColor(init, self, self._tr(title_key))
        if not color.isValid():
            return
        rgb = (color.red(), color.green(), color.blue())
        if lobe == "pos":
            self._custom_pos_rgb = rgb
        else:
            self._custom_neg_rgb = rgb
        self._update_color_buttons()
        self._apply_custom_colors_to_vmd()

    def _reset_phase_color(self, lobe):
        """右键重置单个相位颜色为风格默认。"""
        if lobe == "pos":
            self._custom_pos_rgb = None
        else:
            self._custom_neg_rgb = None
        self._update_color_buttons()
        self._apply_custom_colors_to_vmd()

    def _apply_custom_colors_to_vmd(self):
        """将自定义颜色写入 VMD（委托给库会话）。"""
        if not self.vmd_port:
            return
        pos_rgb = self._custom_pos_rgb
        neg_rgb = self._custom_neg_rgb
        self._vmd_session.set_phase_colors(pos_rgb=pos_rgb, neg_rgb=neg_rgb)
        if pos_rgb is None and neg_rgb is None:
            self._append_log(self._tr("log_color_reset"))
        else:
            self._append_log(self._tr("log_color_custom").format(
                pos=pos_rgb, neg=neg_rgb))

    # ── Socket Communication (delegated to VMD session) ──

    def _send_vmd_cmd(self, cmd):
        """向 VMD 发送 TCL 命令（委托给 orbital_viewer_lib 会话）。"""
        return self._vmd_session.send_cmd(cmd)

    def _close_persist_sock(self):
        """关闭持久 socket 连接。"""
        self._vmd_session._close_socket()
        # 兼容旧代码
        sock = getattr(self, '_vmd_persist_sock', None)
        if sock:
            try:
                sock.close()
            except Exception:
                pass
            self._vmd_persist_sock = None

    # ── Keyboard Shortcuts ──

    def _key_iso_up(self):
        self.current_iso = round(min(self.current_iso + self.iso_step, 0.5), 4)
        self._apply_iso_change()

    def _key_iso_down(self):
        self.current_iso = round(max(self.current_iso - self.iso_step, 0.005), 4)
        self._apply_iso_change()

    def _key_opacity_up(self):
        if self.current_opacity is None:
            style = backend.STYLES.get(self._get_style_name(), backend.STYLES["sob-art"])
            self.current_opacity = style["surface_mat"][5]
        self.current_opacity = round(min(self.current_opacity + self.opacity_step, 1.0), 2)
        self._apply_opacity_change()

    def _key_opacity_down(self):
        if self.current_opacity is None:
            style = backend.STYLES.get(self._get_style_name(), backend.STYLES["sob-art"])
            self.current_opacity = style["surface_mat"][5]
        self.current_opacity = round(max(self.current_opacity - self.opacity_step, 0.05), 2)
        self._apply_opacity_change()

    # ── Slider Handlers ──

    def _on_iso_slider_changed(self, val):
        if not self.vmd_port:
            return
        iso = val / 1000.0
        self.current_iso = iso
        self.iso_edit.blockSignals(True)
        self.iso_edit.setText(f"{iso:.3f}")
        self.iso_edit.blockSignals(False)
        self._vmd_session.set_isovalue(iso)

    def _on_opacity_slider_changed(self, val):
        if not self.vmd_port:
            return
        op = val / 100.0
        self.current_opacity = op
        self.opacity_edit.blockSignals(True)
        self.opacity_edit.setText(f"{op:.2f}")
        self.opacity_edit.blockSignals(False)
        self._vmd_session.set_opacity(op)

    def _on_iso_edit_finished(self):
        """从输入框精确设置等值面"""
        if not self.vmd_port:
            return
        try:
            iso = float(self.iso_edit.text())
        except ValueError:
            return
        iso = max(0.005, min(iso, 0.500))
        self.current_iso = iso
        self._apply_iso_change()

    def _on_opacity_edit_finished(self):
        """从输入框精确设置透明度"""
        if not self.vmd_port:
            return
        try:
            op = float(self.opacity_edit.text())
        except ValueError:
            return
        op = round(max(0.05, min(op, 1.00)), 2)
        self.current_opacity = op
        self._apply_opacity_change()

    # ── Canvas Dash Mode ──

    def _update_dash_status(self):
        """更新画布虚线模式状态（日志输出）。"""
        if not hasattr(self, 'chk_dash_mode'):
            return
        n = len(self.mol_canvas.custom_dash_lines)
        if self.mol_canvas._dash_bond_atom1 is not None:
            self._append_log(f"{self._tr('dash_selected')} {self.mol_canvas._dash_bond_atom1}，{self._tr('dash_select_other')}（{n} {self._tr('dash_lines')}）")
        elif n:
            self._append_log(f"{n} {self._tr('dash_status_lines')}，{self._tr('dash_click_two')}")

    def _bond_display_label(self, tcl_key, is_color=False):
        """根据当前语言返回显示标签。"""
        idx = 1 if self._lang == "en" else 2
        items = self._bond_color_items if is_color else self._bond_type_items
        for it in items:
            if it[0] == tcl_key:
                return it[idx]
        return tcl_key

    def _populate_bond_combos(self):
        """根据当前语言重建颜色和类型下拉框。"""
        idx = 1 if self._lang == "en" else 2

        # 虚线颜色
        cur_color = self.var_dash_color.currentText()
        self.var_dash_color.blockSignals(True)
        self.var_dash_color.clear()
        new_idx = 0
        for i, it in enumerate(self._bond_color_items):
            self.var_dash_color.addItem(it[idx])
            if it[0] == self._resolve_bond_tcl_key(cur_color, is_color=True):
                new_idx = i
        self.var_dash_color.setCurrentIndex(new_idx)
        self.var_dash_color.blockSignals(False)

        # 虚线类型
        cur_type = self.var_bond_type.currentText()
        self.var_bond_type.blockSignals(True)
        self.var_bond_type.clear()
        new_idx = 0
        for i, it in enumerate(self._bond_type_items):
            self.var_bond_type.addItem(it[idx])
            if it[0] == self._resolve_bond_tcl_key(cur_type, is_color=False):
                new_idx = i
        self.var_bond_type.setCurrentIndex(new_idx)
        self.var_bond_type.blockSignals(False)

    def _resolve_bond_tcl_key(self, label, is_color=False):
        """根据显示标签（中/英）反查 tcl_key。"""
        items = self._bond_color_items if is_color else self._bond_type_items
        for it in items:
            if label in (it[1], it[2]):
                return it[0]
        return "black" if is_color else "dots"

    def _get_bond_color_hex(self):
        """获取当前选择的虚线颜色 hex。"""
        label = self.var_dash_color.currentText()
        for it in self._bond_color_items:
            if label in (it[1], it[2]):
                return it[3]
        return "#000000"

    def _on_dash_color_changed(self):
        """下拉选择虚线颜色 → 同步画布 + VMD。"""
        if not hasattr(self, 'mol_canvas') or not self.vmd_port:
            return
        hex_str = self._get_bond_color_hex()
        self.mol_canvas.dash_color_hex = hex_str
        self.mol_canvas.update()
        self._vmd_reapply_dashes()

    def _sync_dash_to_canvas(self):
        """将虚线面板的参数同步到画布。"""
        if not hasattr(self, 'bond_nbars_slider'):
            return
        gap = self.bond_nbars_slider.value() / 100.0
        self.mol_canvas.dash_dot_count = max(2, int(3.0 / gap))
        self.mol_canvas.dash_dot_radius = max(1, self.bond_radius_slider.value())
        self.mol_canvas.repaint()

    def _on_nbars_slider(self, val):
        gap = val / 100.0
        self.bond_nbars_edit.blockSignals(True)
        self.bond_nbars_edit.setText(f"{gap:.2f}")
        self.bond_nbars_edit.blockSignals(False)
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_nbars_edit(self):
        try:
            gap = float(self.bond_nbars_edit.text())
            gap = max(0.05, min(1.00, gap))
        except ValueError:
            return
        val = int(round(gap * 100))
        self.bond_nbars_slider.blockSignals(True)
        self.bond_nbars_slider.setValue(val)
        self.bond_nbars_slider.blockSignals(False)
        self.bond_nbars_edit.setText(f"{val/100.0:.2f}")
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_bond_radius_slider(self, val):
        r = val / 100.0
        self.bond_radius_edit.blockSignals(True)
        self.bond_radius_edit.setText(f"{r:.2f}")
        self.bond_radius_edit.blockSignals(False)
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_bond_radius_edit(self):
        try:
            r = float(self.bond_radius_edit.text())
            r = max(0.01, min(0.50, r))
        except ValueError:
            return
        val = int(round(r * 100))
        self.bond_radius_slider.blockSignals(True)
        self.bond_radius_slider.setValue(val)
        self.bond_radius_slider.blockSignals(False)
        self.bond_radius_edit.setText(f"{val/100.0:.2f}")
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_flip_phase(self):
        """翻转等值面相位：交换 rep_pos / rep_neg 的 isovalue 符号。"""
        if not self.vmd_port or self.current_iso is None:
            self._append_log("翻转相位失败 (VMD 未连接或无当前 isovalue)")
            return
        rp = self._vmd_state["rep_pos"]
        rn = self._vmd_state["rep_neg"]
        iso_before = self.current_iso
        self.current_iso = -self.current_iso
        iso = self.current_iso
        self._append_log(f"  [DEBUG FLIP] iso_before={iso_before} iso_after={iso} "
                         f"rp={rp} rn={rn} vmd_port={self.vmd_port}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", self.vmd_port))
            cmd1 = f"mol modstyle {rp} top Isosurface {iso} 0 0 0 1 1"
            cmd2 = f"mol modstyle {rn} top Isosurface {-iso} 0 0 0 1 1"
            self._append_log(f"  [DEBUG FLIP] → VMD: {cmd1}")
            self._append_log(f"  [DEBUG FLIP] → VMD: {cmd2}")
            sock.sendall((cmd1 + "\n").encode("utf-8"))
            try:
                resp1 = sock.recv(4096).decode("utf-8", errors="replace").strip()
            except socket.timeout:
                resp1 = "(timeout)"
            sock.sendall((cmd2 + "\n").encode("utf-8"))
            try:
                resp2 = sock.recv(4096).decode("utf-8", errors="replace").strip()
            except socket.timeout:
                resp2 = "(timeout)"
            sock.close()
            ok = "ERROR" not in (resp1 + resp2)
            self._append_log(
                self._tr("log_flip", iso=iso) if ok
                else f"翻转相位失败: resp1={resp1} resp2={resp2}"
            )
        except Exception as e:
            self._append_log(f"翻转相位失败 (连接): {e}")

    def _apply_iso_change(self):
        iso = self.current_iso
        self.iso_slider.blockSignals(True)
        self.iso_slider.setValue(int(iso * 1000))
        self.iso_slider.blockSignals(False)
        self.iso_edit.blockSignals(True)
        self.iso_edit.setText(f"{iso:.3f}")
        self.iso_edit.blockSignals(False)
        self._vmd_session.set_isovalue(iso)
        self._append_log(self._tr("log_iso_change", iso=iso, status="OK"))

    def _apply_opacity_change(self):
        op = self.current_opacity
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(op * 100))
        self.opacity_slider.blockSignals(False)
        self.opacity_edit.blockSignals(True)
        self.opacity_edit.setText(f"{op:.2f}")
        self.opacity_edit.blockSignals(False)
        self._vmd_session.set_opacity(op)
        self._append_log(self._tr("log_opacity_change", op=op))

    # ── Button State Management ──

    def _set_buttons_state(self, state):
        if state == "running":
            self.btn_run.setEnabled(False)
            self.btn_preview.setEnabled(False)
            self.btn_render.setEnabled(False)
            self.btn_h_filter.setEnabled(False)
            self.btn_undo_bond.setEnabled(False)
            self.btn_clear_bond.setEnabled(False)
            self.btn_flip_phase.setEnabled(False)
            self.btn_preview_mol.setEnabled(False)
            self.btn_preview_mol.hide()
            self.iso_slider.setEnabled(False)
            self.opacity_slider.setEnabled(False)
            self.iso_edit.setEnabled(False)
            self.opacity_edit.setEnabled(False)
        else:
            self.btn_run.setEnabled(True)
            self._vmd_orbital_labels = []


# ── Entry Point ───────────────────────────────────────────
def main():
    if len(sys.argv) > 1:
        import argparse
        p = argparse.ArgumentParser(
            description="Multiwfn + VMD/Tachyon Orbital Isosurface Visualization v6.0")
        p.add_argument("input", help="fchk file or folder")
        p.add_argument("--mo", default="h", help="Orbital (h/l/h-1/number)")
        p.add_argument("--iso", type=float, default=0.05, help="Isosurface threshold")
        p.add_argument("--grid", default="2", help="Grid quality (1/2/3)")
        p.add_argument("--style", default="sob-art",
                       choices=list(backend.STYLES.keys()), help="Render style")
        p.add_argument("--res", default="2000,1500", help="Resolution width,height")
        p.add_argument("--no-render", action="store_true", help="Generate cube only")
        p.add_argument("--out", default=None)
        a = p.parse_args()

        files = (sorted(glob.glob(os.path.join(a.input, "*.fchk")))
                 if os.path.isdir(a.input) else [a.input])
        out = a.out or (os.path.dirname(a.input)
                        if os.path.isfile(a.input) else a.input)
        os.makedirs(out, exist_ok=True)

        w, h = [int(x) for x in a.res.split(",")]

        for i, f in enumerate(files):
            print(f"[{i+1}/{len(files)}] {os.path.basename(f)}")
            cube = backend.gen_cube(f, orbital=a.mo, grid_quality=int(a.grid),
                                    work_dir=out)
            if cube:
                print(f"  cube: {os.path.basename(cube)}")
                if not a.no_render:
                    png = backend.render_cube_auto(
                        cube, isovalue=a.iso, style_name=a.style,
                        resolution=(w, h))
                    if png:
                        print(f"  png:  {os.path.basename(png)}")
            else:
                print(f"  Failed")
    else:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        # Uniform tooltip background (QToolTip QSS is unreliable on Windows —
        # set palette directly on QApplication for consistency)
        tip_pal = app.palette()
        tip_pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
        tip_pal.setColor(QPalette.ToolTipText, QColor("#2C3E50"))
        app.setPalette(tip_pal)
        window = OrbitalVisApp()
        window.show()
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()


