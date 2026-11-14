# -*- coding: utf-8 -*-
"""轨道权重福井函数 / 轨道权重双描述符（OW-Fukui）面板。

把主窗口当前载入的闭壳层波函数交给 Multiwfn 主功能 22（Conceptual DFT）
计算轨道权重福井函数与轨道权重双描述符（方法见 http://sobereva.com/533）：

* ``w_i = exp(-((μ-ε_i)/Δ)^2) / Σ exp(...)``，μ = (E_HOMO + E_LUMO)/2；
* ``f_w+ = Σ_{i≥LUMO} w_i |φ_i|²``，``f_w- = Σ_{i≤HOMO} w_i |φ_i|²``，
  ``f_w0 = (f_w+ + f_w-)/2``，``Δf_w = f_w+ - f_w-``。

面板负责界面与线程调度，数值全部来自 ``molstudio.core.ow_fukui``（Qt-free
核心模块）解析 Multiwfn 的 stdout / cube，面板本身不做任何波函数求值。

设计遵循仓库其它面板（重点参考 ``lmo_panel.py``）的惯例：
* 所有界面文字都放在模块级 ``TEXT`` 字典里，``set_lang()`` 负责整页刷新；
* 耗时操作跑在 ``QThread`` 里，通过 ``on_log`` / ``on_stage`` 回调汇报进度；
* 面板不持有主窗口状态，只通过构造时注入的回调取输入、送结果；
* 计算完成后自动把 Δf_w（轨道权重双描述符）cube 交给画布显示，
  等值面用 ``suggest_iso`` 从 cube 数据推算（不能用 MO 的 0.05）。

Multiwfn 交互要点（2026.4.10 实测，详见核心模块）：
主菜单 ``22`` 进 CDFT 菜单；``4`` 设 Δ、``5`` 打印轨道权重、``6`` 算
Hirshfeld 简缩值、``7`` 选网格质量后导出四个 cube；后处理菜单 ``0`` →
CDFT 菜单 ``0`` → 主菜单 ``q`` 退出。
"""

from __future__ import annotations

import os
import threading

from PyQt5.QtCore import QEvent, Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from molstudio.core.fchk_parser import parse_fchk_mo_info
from molstudio.core.ow_fukui import (
    DEFAULT_SETTINGS,
    FUNCTIONS,
    GRID_QUALITIES,
    export_condensed_csv,
    run_ow_fukui,
    suggest_iso,
)


# 面板自己的 Δ 范围（核心模块常量同名，但这里只用于 QDoubleSpinBox）
_DELTA_MIN = 0.001
_DELTA_MAX = 2.0

#: 没有 cube 可读时等值面的初始占位值（文章里 C60 常用 0.0003 a.u.）。
#: 一旦算出 cube，会用 ``suggest_iso`` 自动覆盖。
_ISO_FALLBACK = 0.0003

#: 设置类表单字段的宽度约束：QFormLayout 默认把字段列拉到整行宽，
#: 单行设置看起来像一条横贯页面的输入框，很丑；限制成 200–240 px 后
#: 与「运行」按钮等元素宽度协调（中英文标签下都保持这个范围）。
_FIELD_MIN_WIDTH = 200
_FIELD_MAX_WIDTH = 240

#: 权重表「标记」列至少要放得下 LUMO+10 / HOMO-10（宽度按字体度量现算）。
_WEIGHT_MARK_MIN_WIDTH = 96
_WEIGHT_MARK_MAX_WIDTH = 160
#: 权重表「权重 %」列固定宽度（100.00 / 12.47 这类数值都有余量）。
_WEIGHT_VALUE_WIDTH = 80

#: 简缩值表数值列（OW f+/f-/f0）的最小宽度：要完整显示 0.01667 / -0.00000
#: 这类 5 位小数。实际宽度再按当前字体度量放大（上限见 _CONDENSED_VALUE_MAX_WIDTH）。
_CONDENSED_VALUE_MIN_WIDTH = 95
_CONDENSED_VALUE_MAX_WIDTH = 150
#: 简缩值表「原子 / 元素」列宽。
_CONDENSED_INDEX_WIDTH = 60
_CONDENSED_ELEMENT_WIDTH = 60

#: Multiwfn 选项 5 / 6 打印的轨道权重条数（标题里显示用）
_TOP_WEIGHT_COUNT = 10

#: Δf_w 是最有代表性的显示对象；没有 DD 时按此顺序退回
_AUTO_SHOW_ORDER = ("dd", "f0", "fplus", "fminus")


# ── 界面文字 ─────────────────────────────────────────────────────────────
# 键名尽量语义化；新增键必须 zh / en 成对出现（回归测试会检查英文界面无中文）。
TEXT = {
    "zh": {
        "title": "轨道权重福井函数",
        "intro": (
            "用 Multiwfn 主功能 22 计算轨道权重福井函数（OW-Fukui）与轨道权重"
            "双描述符（OW-DD）：按能级差加权前线轨道"
            "（w_i ∝ exp(−((μ−ε_i)/Δ)²)），特别适合 C60、18 碳环等前线轨道"
            "（准）简并体系预测亲核/亲电反应位点。方法："
            "<a href=\"http://sobereva.com/533\">sobereva.com/533</a>"
        ),
        "source_group": "输入波函数",
        "source_none": "请先在主界面载入含空轨道的闭壳层波函数"
                        "（.fch / .fchk / .mwfn）。",
        "source_missing": "文件不存在：{path}",
        "source_ready": "文件：{name}\n输出目录：{dir}",
        "source_shell_closed": "闭壳层单行列式（满足轨道权重形式的前提）",
        "source_shell_open": "开壳层波函数：轨道权重形式只适用于闭壳层单行列式，"
                             "已禁用计算。",
        "source_shell_no_virtual": "输入不含空轨道（基函数数不大于占据轨道数），"
                                   "无法计算 OW-Fukui。",
        "source_shell_unknown": "未能读取波函数轨道信息，开壳层检查将在运行前再做一次。",
        "refresh": "刷新",
        "refresh_tip": "重新读取主界面当前载入的波函数并检查闭壳层",
        "outdir": "输出目录",
        "outdir_tip": "cube、日志与 CSV 的输出目录；默认与输入文件同目录",
        "outdir_placeholder": "默认与输入文件同目录",
        "browse": "浏览…",
        "browse_tip": "选择输出目录",
        "pick_outdir_title": "选择输出目录",
        "settings_group": "计算设置",
        "delta": "Δ (Hartree)",
        "delta_tip": "轨道权重公式中的能量宽度参数，默认 0.1 Hartree"
                     "（JCC 2017 推荐）",
        "grid": "格点质量",
        "grid_tip": "导出 cube 时 Multiwfn 的网格质量（低/中/高）",
        "grid_low": "低",
        "grid_medium": "中",
        "grid_high": "高",
        "opt_weights": "计算轨道权重（选项 5）",
        "opt_weights_tip": "打印 ε_HOMO / ε_LUMO / μ / Δ 与 f+、f- 各最高 "
                           "10 个轨道权重",
        "opt_condensed": "计算 Hirshfeld 简缩值（选项 6）",
        "opt_condensed_tip": "计算 Hirshfeld 简缩的 OW f+ / f- / f0 / DD，"
                             "并给出两个 sum",
        "opt_export": "导出四个 cube（选项 7）",
        "opt_export_tip": "导出 OW f+ / f- / f0 / DD 的格点数据（.cub）",
        "note_title": "说明",
        "note_text": (
            "• 轨道权重形式仅适用于闭壳层单行列式波函数。\n"
            "• 输入文件必须含空轨道，推荐不使用弥散函数。\n"
            "• Δ 默认 0.1 Hartree（JCC 2017 推荐），可在此调整。\n"
            "• 只有前线轨道（准）简并的体系才需要用它；f_w− 大 / Δf_w 明显为负 "
            "→ 易受亲电进攻，Δf_w 为正 → 易受亲核进攻。"
        ),
        "run_group": "运行",
        "run": "开始计算",
        "run_tip": "按当前设置运行 Multiwfn 主功能 22（后台线程）",
        "stop": "停止",
        "stop_tip": "立即终止正在运行的 Multiwfn",
        "status_no_source": "请先在主界面载入闭壳层波函数。",
        "status_open_shell": "开壳层波函数不支持轨道权重形式，已禁用计算。",
        "status_no_virtual": "输入不含空轨道，无法计算 OW-Fukui。",
        "status_ready": "就绪：设置好参数后点击「开始计算」。",
        "status_working": "正在计算轨道权重福井函数…",
        "status_done_fmt": "计算完成 · 用时 {secs} s · 生成 {n} 个 cube",
        "status_failed": "计算失败",
        "status_cancelling": "正在停止…",
        "status_cancelled": "已停止",
        "result_group": "OW-Fukui 结果",
        "tab_weights": "轨道权重",
        "tab_condensed": "简缩值",
        "tab_vis": "可视化",
        "summary_empty": "计算结果会显示在这里。",
        "condensed_empty": "简缩值会在计算完成后显示在这里。",
        "weights_not_computed": "未计算轨道权重：请勾选「计算轨道权重（选项 5）」。",
        "condensed_not_computed": "未计算 Hirshfeld 简缩值：请勾选"
                                  "「计算 Hirshfeld 简缩值（选项 6）」。",
        "summary_fmt": "HOMO = {homo} a.u. · LUMO = {lumo} a.u. · "
                       "μ = {mu} a.u. · Δ = {delta} a.u.",
        "grid_fmt": "网格：{nx}×{ny}×{nz} = {npoints} 点 · "
                    "间距 {spacing} Bohr · 质量 {quality}",
        "degenerate_hint": "检测到前线轨道简并/准简并——"
                           "这正是轨道权重形式的适用场景。",
        "weight_group": "{name}（前 {n} 个最高权重）",
        "weight_total_fmt": "所列轨道权重合计：f+ {plus}% · f− {minus}%"
                            "（其余轨道权重更小，未逐条列出）",
        "col_orbital": "编号",
        "col_mark": "标记",
        "col_weight": "权重 %",
        "col_ediff": "ε−μ (eV)",
        "col_atom": "原子",
        "col_element": "元素",
        "col_fplus": "OW f+",
        "col_fminus": "OW f-",
        "col_f0": "OW f0",
        "col_dd": "OW DD",
        "sum_fplus": "Σ OW f+",
        "sum_fminus": "Σ OW f-",
        "condensed_summary_fmt": "共 {n} 个原子 · Σ OW f+ = {fplus} · "
                                 "Σ OW f- = {fminus}",
        "export_csv": "导出 CSV",
        "export_csv_tip": "把 Hirshfeld 简缩值表导出为 UTF-8 CSV",
        "csv_filter": "CSV (*.csv)",
        "function": "函数",
        "function_tip": "选择要在画布上显示的 OW-Fukui 函数",
        "iso": "等值面",
        "iso_tip": "等值面数值（a.u.）；切换函数时会按 cube 数据自动推荐",
        "iso_fallback_note": "默认等值面由 cube 数据自动推算"
                             "（fraction × max|value|），可手动微调。",
        "show_canvas": "显示到画布",
        "show_canvas_tip": "把当前函数的 cube 以当前等值面显示到左侧画布",
        "cube_group": "Cube 文件",
        "cube_missing": "尚未生成",
        "vis_state_ready": "当前函数：{name} · cube：{cube}",
        "vis_state_missing": "当前函数：{name} · cube 尚未生成",
        "open_dir": "打开输出目录",
        "open_dir_tip": "打开 cube、日志与 CSV 所在的输出目录",
        "warning": "提示",
        "failed_title": "计算失败",
        "need_source": "请先在主界面载入闭壳层波函数",
        "need_mw": "请先在主界面路径设置中配置 Multiwfn",
        "need_any_task": "请至少勾选一项计算内容（轨道权重 / 简缩值 / 导出 cube）",
        "open_shell_blocked": "开壳层波函数不支持轨道权重形式，"
                              "请换用闭壳层单行列式波函数。",
        "no_virtual_blocked": "输入文件不含空轨道，无法计算 OW-Fukui。",
        "no_cube": "函数「{name}」的 cube 尚未生成：请勾选"
                   "「导出四个 cube」后重新计算。",
        "no_condensed": "没有可导出的简缩值，请先运行计算。",
        "csv_failed_msg": "CSV 导出失败：{msg}",
        "open_dir_failed": "无法打开输出目录：{path}",
        "no_canvas": "当前没有可用的画布，无法显示等值面。",
        "dash": "—",
        "log_run": "[OW-Fukui] Δ={delta} a.u. · 格点 {grid} · 输出 {dir} → {fchk}",
        "log_done": "[OW-Fukui] 完成：用时 {secs} s，生成 {n} 个 cube",
        "log_error": "[OW-Fukui] 失败：{msg}",
        "log_cancelling": "[OW-Fukui] 正在停止…",
        "log_cancelled": "[OW-Fukui] 已停止",
        "log_warning": "[OW-Fukui] 警告：{msg}",
        "log_csv_saved": "[OW-Fukui] CSV 已保存：{path}",
        "log_auto_show": "[OW-Fukui] 自动显示 {name}（iso = {iso}）",
        "log_show": "[OW-Fukui] 在画布上显示 {name}（iso = {iso}）",
    },
    "en": {
        "title": "Orbital-weighted Fukui function",
        "intro": (
            "Compute orbital-weighted Fukui functions (OW-Fukui) and the "
            "orbital-weighted dual descriptor (OW-DD) with Multiwfn main "
            "function 22: frontier orbitals are weighted by their energy "
            "difference (w_i ∝ exp(−((μ−ε_i)/Δ)²)), which is ideal for "
            "(nearly) degenerate frontier orbitals such as C60 or the "
            "18-carbon ring when predicting nucleophilic/electrophilic sites. "
            "Method: <a href=\"http://sobereva.com/533\">sobereva.com/533</a>"
        ),
        "source_group": "Source wavefunction",
        "source_none": "Load a closed-shell wavefunction with virtual "
                       "orbitals (.fch / .fchk / .mwfn) in the main window first.",
        "source_missing": "File not found: {path}",
        "source_ready": "File: {name}\nOutput folder: {dir}",
        "source_shell_closed": "Closed-shell single determinant (valid for the "
                               "orbital-weighted form)",
        "source_shell_open": "Open-shell wavefunction: the orbital-weighted "
                             "form is only valid for a closed-shell single "
                             "determinant; calculation is disabled.",
        "source_shell_no_virtual": "The input has no virtual orbitals (basis "
                                   "functions <= occupied orbitals); OW-Fukui "
                                   "cannot be computed.",
        "source_shell_unknown": "Could not read the orbital information; the "
                                "open-shell check will run again before the "
                                "calculation.",
        "refresh": "Refresh",
        "refresh_tip": "Re-read the wavefunction currently loaded in the main "
                       "window and check the closed-shell requirement",
        "outdir": "Output folder",
        "outdir_tip": "Output folder for cubes, log and CSV; defaults to the "
                      "input file's folder",
        "outdir_placeholder": "Defaults to the input file's folder",
        "browse": "Browse…",
        "browse_tip": "Choose the output folder",
        "pick_outdir_title": "Choose output folder",
        "settings_group": "Calculation settings",
        "delta": "Δ (Hartree)",
        "delta_tip": "Energy-width parameter of the orbital-weight formula; "
                     "the default 0.1 Hartree is recommended (JCC 2017)",
        "grid": "Grid quality",
        "grid_tip": "Multiwfn grid quality used when exporting cubes "
                    "(low/medium/high)",
        "grid_low": "Low",
        "grid_medium": "Medium",
        "grid_high": "High",
        "opt_weights": "Compute orbital weights (option 5)",
        "opt_weights_tip": "Print ε_HOMO / ε_LUMO / μ / Δ and the 10 highest "
                           "f+ / f- orbital weights",
        "opt_condensed": "Compute Hirshfeld condensed values (option 6)",
        "opt_condensed_tip": "Compute the Hirshfeld-condensed OW f+ / f- / f0 "
                             "/ DD and the two sums",
        "opt_export": "Export the four cubes (option 7)",
        "opt_export_tip": "Export the OW f+ / f- / f0 / DD grid data (.cub)",
        "note_title": "Notes",
        "note_text": (
            "• The orbital-weighted form is only valid for a closed-shell "
            "single-determinant wavefunction.\n"
            "• The input must contain virtual orbitals; diffuse functions are "
            "not recommended.\n"
            "• Δ defaults to 0.1 Hartree (JCC 2017 recommendation) and can be "
            "adjusted here.\n"
            "• Use it only for systems with (nearly) degenerate frontier "
            "orbitals; large f_w− / clearly negative Δf_w → prone to "
            "electrophilic attack, positive Δf_w → prone to nucleophilic "
            "attack."
        ),
        "run_group": "Run",
        "run": "Start calculation",
        "run_tip": "Run Multiwfn main function 22 with the current settings "
                   "(background thread)",
        "stop": "Stop",
        "stop_tip": "Terminate the running Multiwfn immediately",
        "status_no_source": "Load a closed-shell wavefunction in the main "
                            "window first.",
        "status_open_shell": "Open-shell wavefunctions are not supported by the "
                             "orbital-weighted form; calculation is disabled.",
        "status_no_virtual": "The input has no virtual orbitals; OW-Fukui "
                             "cannot be computed.",
        "status_ready": "Ready: adjust the settings and click Start calculation.",
        "status_working": "Computing orbital-weighted Fukui functions…",
        "status_done_fmt": "Calculation complete · {secs} s · {n} cube(s)",
        "status_failed": "Calculation failed",
        "status_cancelling": "Stopping…",
        "status_cancelled": "Stopped",
        "result_group": "OW-Fukui results",
        "tab_weights": "Orbital weights",
        "tab_condensed": "Condensed values",
        "tab_vis": "Visualization",
        "summary_empty": "Results appear here after the calculation completes.",
        "condensed_empty": "Condensed values appear here after the calculation "
                           "completes.",
        "weights_not_computed": "Orbital weights were not computed: enable "
                                "Compute orbital weights (option 5).",
        "condensed_not_computed": "Hirshfeld condensed values were not "
                                  "computed: enable Compute Hirshfeld condensed "
                                  "values (option 6).",
        "summary_fmt": "HOMO = {homo} a.u. · LUMO = {lumo} a.u. · "
                       "μ = {mu} a.u. · Δ = {delta} a.u.",
        "grid_fmt": "Grid: {nx}×{ny}×{nz} = {npoints} points · "
                    "spacing {spacing} Bohr · quality {quality}",
        "degenerate_hint": "Frontier orbitals are (nearly) degenerate — exactly "
                           "the case where the orbital-weighted form is needed.",
        "weight_group": "{name} (top {n} weights)",
        "weight_total_fmt": "Sum of the listed orbital weights: f+ {plus}% · "
                            "f− {minus}% (the remaining orbitals have smaller "
                            "weights and are not listed individually)",
        "col_orbital": "Orbital",
        "col_mark": "Label",
        "col_weight": "Weight %",
        "col_ediff": "ε−μ (eV)",
        "col_atom": "Atom",
        "col_element": "Element",
        "col_fplus": "OW f+",
        "col_fminus": "OW f-",
        "col_f0": "OW f0",
        "col_dd": "OW DD",
        "sum_fplus": "Σ OW f+",
        "sum_fminus": "Σ OW f-",
        "condensed_summary_fmt": "{n} atoms · Σ OW f+ = {fplus} · "
                                 "Σ OW f- = {fminus}",
        "export_csv": "Export CSV",
        "export_csv_tip": "Export the Hirshfeld condensed values as a UTF-8 "
                          "CSV file",
        "csv_filter": "CSV (*.csv)",
        "function": "Function",
        "function_tip": "Choose the OW-Fukui function to show on the canvas",
        "iso": "Isosurface value",
        "iso_tip": "Isosurface value (a.u.); switching functions updates the "
                   "suggestion from the cube data",
        "iso_fallback_note": "The default is estimated from the cube data "
                             "(fraction × max|value|) and can be fine-tuned.",
        "show_canvas": "Show on canvas",
        "show_canvas_tip": "Show the current function's cube on the left "
                           "canvas with the current isosurface value",
        "cube_group": "Cube files",
        "cube_missing": "Not generated yet",
        "vis_state_ready": "Current function: {name} · cube: {cube}",
        "vis_state_missing": "Current function: {name} · cube not generated yet",
        "open_dir": "Open output folder",
        "open_dir_tip": "Open the output folder that contains the cubes, log "
                        "and CSV",
        "warning": "Notice",
        "failed_title": "Calculation failed",
        "need_source": "Load a closed-shell wavefunction in the main window "
                       "first",
        "need_mw": "Configure Multiwfn in the main-window Path Settings first",
        "need_any_task": "Enable at least one calculation item (orbital "
                         "weights / condensed values / cube export)",
        "open_shell_blocked": "Open-shell wavefunctions are not supported by "
                              "the orbital-weighted form; use a closed-shell "
                              "single-determinant wavefunction.",
        "no_virtual_blocked": "The input file has no virtual orbitals; "
                              "OW-Fukui cannot be computed.",
        "no_cube": "The cube for {name} has not been generated: enable "
                   "Export the four cubes and run the calculation again.",
        "no_condensed": "No condensed values to export; run the calculation "
                        "first.",
        "csv_failed_msg": "CSV export failed: {msg}",
        "open_dir_failed": "Cannot open the output folder: {path}",
        "no_canvas": "No canvas is available to show the isosurface.",
        "dash": "—",
        "log_run": "[OW-Fukui] Δ={delta} a.u. · grid {grid} · output {dir} → "
                   "{fchk}",
        "log_done": "[OW-Fukui] Complete: {n} cube(s) in {secs} s",
        "log_error": "[OW-Fukui] Failed: {msg}",
        "log_cancelling": "[OW-Fukui] Stopping…",
        "log_cancelled": "[OW-Fukui] Stopped",
        "log_warning": "[OW-Fukui] Warning: {msg}",
        "log_csv_saved": "[OW-Fukui] CSV saved: {path}",
        "log_auto_show": "[OW-Fukui] Showing {name} automatically "
                         "(iso = {iso})",
        "log_show": "[OW-Fukui] Showing {name} on canvas (iso = {iso})",
    },
}


def _as_float(value, default=None):
    """尽力把值转成 float，失败时返回 default。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=None):
    """尽力把值转成 int，失败时返回 default。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _func_label(key, lang="zh"):
    """取核心模块 FUNCTIONS 里的本地化函数名（缺字段时退回键名）。"""
    entry = FUNCTIONS.get(key)
    if not isinstance(entry, dict):
        return str(key or "")
    if lang == "en":
        return str(entry.get("label_en") or entry.get("label_zh") or key)
    return str(entry.get("label_zh") or entry.get("label_en") or key)


class _FitColumnsTable(QTableWidget):
    """前 N-1 列固定宽度、最后一列吃掉剩余宽度的结果表。

    不用 ``QHeaderView.StretchLastSection``：垂直滚动条出现后 viewport 变窄，
    QHeaderView 的 stretch 列不会重新计算，结果最后一列被挤出视口、前面
    数值列反而被压成 ``0.01...``。这里在 viewport 尺寸变化时自己重算最后一列，
    保证 4/6 列在页面宽度下始终完整。
    """

    def __init__(self, columns, parent=None):
        super().__init__(0, columns, parent)
        self._fixed_widths = [80] * max(0, columns - 1)
        self._last_min_width = 72
        self._adjusting = False
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)
        for column in range(columns):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        try:
            self.viewport().installEventFilter(self)
        except Exception:  # noqa: BLE001 - 安装失败仍能靠 resizeEvent 兜底
            pass

    def set_fixed_widths(self, widths, last_min_width=None):
        """设置固定列宽；最后一列宽度 = viewport 剩余宽度（不小于 last_min）。"""
        self._fixed_widths = [int(max(40, width)) for width in widths]
        if last_min_width is not None:
            self._last_min_width = int(max(40, last_min_width))
        self._apply_column_widths()

    def _apply_column_widths(self):
        if self._adjusting or self.columnCount() <= 0:
            return
        self._adjusting = True
        try:
            for column, width in enumerate(self._fixed_widths):
                if self.columnWidth(column) != width:
                    self.setColumnWidth(column, width)
            remaining = self.viewport().width() - sum(self._fixed_widths)
            last_width = max(self._last_min_width, int(remaining))
            last_column = self.columnCount() - 1
            if self.columnWidth(last_column) != last_width:
                self.setColumnWidth(last_column, last_width)
        finally:
            self._adjusting = False

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Resize:
            self._apply_column_widths()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_column_widths()

    def refresh_column_widths(self):
        """数据/滚动条变化后重新分配最后一列的宽度。"""
        self._apply_column_widths()


class OWFukuiWorker(QThread):
    """在后台运行 ``run_ow_fukui``。

    ``finished`` 携带核心模块的结果字典（含 ``ok``），``failed`` 只在未预期
    异常时发出。``stop()`` 置位取消事件并尽力终止 Multiwfn 子进程。
    """

    log = pyqtSignal(str)
    stage = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, fchk_path, multiwfn_exe, settings, out_dir=None,
                 parent=None):
        super().__init__(parent)
        self._fchk_path = str(fchk_path or "")
        self._multiwfn_exe = str(multiwfn_exe or "")
        self._settings = dict(settings or {})
        self._out_dir = str(out_dir or "")
        self._stop_event = threading.Event()
        self._proc = {}

    def is_stopped(self):
        return self._stop_event.is_set()

    def stop(self):
        """请求停止：置位取消标志，并终止正在运行的 Multiwfn 进程。"""
        self._stop_event.set()
        proc = self._proc.get("proc") if isinstance(self._proc, dict) else None
        if proc is None:
            return
        try:
            poll = getattr(proc, "poll", None)
            if (poll is None or poll() is None) and hasattr(proc, "terminate"):
                proc.terminate()
        except Exception:  # noqa: BLE001 - 停止路径不做异常处理
            pass

    def run(self):
        try:
            result = run_ow_fukui(
                self._fchk_path,
                self._multiwfn_exe,
                settings=self._settings,
                out_dir=self._out_dir or None,
                on_log=self.log.emit,
                on_stage=self.stage.emit,
                cancel_check=self._stop_event.is_set,
                proc_holder=self._proc,
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成界面错误
            self.failed.emit(str(exc))
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid OW-Fukui result",
                      "weights": {}, "condensed": [], "sums": {},
                      "cubes": {}, "warnings": []}
        self.finished.emit(result)


class OWFukuiPanel(QWidget):
    """轨道权重福井函数面板（右侧页面，可滚动）。"""

    def __init__(self, glw=None, get_fchk=None, get_multiwfn=None,
                 get_grid_quality=None, on_show_cube=None,
                 log_func=None, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self._lang = "zh"
        self.glw = glw
        self._get_fchk = get_fchk if callable(get_fchk) else (lambda: "")
        self._get_multiwfn = (
            get_multiwfn if callable(get_multiwfn) else (lambda: ""))
        self._get_grid_quality = (
            get_grid_quality if callable(get_grid_quality) else (lambda: "2"))
        self._on_show_cube = on_show_cube if callable(on_show_cube) else None
        self._log_func = log_func if callable(log_func) else None

        self._source_path = ""
        self._source_missing = False
        self._source_signature = None
        self._shell_state = ""
        self._shell_info = {}
        self._outdir_auto = True
        self._worker = None
        self._last_result = None
        self._running = False
        self._shutting_down = False
        self._suppress_iso = False
        self._iso_cache = {}
        self._status_key = "status_no_source"
        self._status_args = {}

        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._build_ui()
        self._populate_combos()
        self._apply_defaults_from_core()
        self._apply_lang()
        self.set_source_from_main()

    # ── 基础工具 ────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        """取当前语言文案；缺键时退回键名，避免界面崩溃。"""
        text = TEXT.get(self._lang, TEXT["zh"]).get(key, key)
        if fmt:
            try:
                return text.format(**fmt)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    def _log(self, message):
        if self._log_func is not None:
            try:
                self._log_func(str(message))
            except Exception:  # noqa: BLE001 - 日志回调失败不影响面板
                pass

    def _on_log(self, message):
        self._log(str(message))

    def _set_status(self, key, **fmt):
        self._status_key = key
        self._status_args = dict(fmt)
        self._refresh_status()

    def _refresh_status(self):
        text = self._t(self._status_key)
        if self._status_args:
            try:
                text = text.format(**self._status_args)
            except (KeyError, IndexError, ValueError):
                pass
        self.lbl_status.setText(text)

    def _current_fchk(self):
        try:
            return str(self._get_fchk() or "").strip()
        except Exception:  # noqa: BLE001 - 回调异常按空值处理
            return ""

    def _current_multiwfn(self):
        try:
            return str(self._get_multiwfn() or "").strip()
        except Exception:  # noqa: BLE001 - 回调异常按空值处理
            return ""

    def _grid_quality_from_main(self):
        try:
            value = int(str(self._get_grid_quality()).strip())
        except Exception:  # noqa: BLE001 - 回调异常按默认网格
            value = 2
        return max(1, min(3, value))

    def _grid_label(self, quality):
        """本地化格点质量名；优先用核心模块 GRID_QUALITIES，缺字段时退回 TEXT。"""
        entry = GRID_QUALITIES.get(int(quality))
        if isinstance(entry, dict):
            if self._lang == "en":
                text = entry.get("en") or entry.get("label_en")
            else:
                text = entry.get("zh") or entry.get("label_zh")
            if text:
                return str(text)
        return self._t({1: "grid_low", 2: "grid_medium",
                        3: "grid_high"}.get(int(quality), "grid_medium"))

    def _func_label(self, key):
        entry = FUNCTIONS.get(key)
        if not isinstance(entry, dict):
            return str(key or "")
        if self._lang == "en":
            return str(entry.get("label_en") or entry.get("label_zh") or key)
        return str(entry.get("label_zh") or entry.get("label_en") or key)

    def _fmt_number(self, value, decimals):
        number = _as_float(value)
        if number is None:
            return self._t("dash")
        return ("%." + str(int(decimals)) + "f") % number

    # ── 界面搭建 ────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        self.content_widget = content
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area, 1)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#0D47A1;")
        root.addWidget(self.lbl_title)

        self.lbl_intro = QLabel()
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setOpenExternalLinks(True)
        self.lbl_intro.setStyleSheet("color:#475569;")
        root.addWidget(self.lbl_intro)

        self._build_source_group(root)
        self._build_settings_group(root)
        self._build_run_group(root)
        self._build_result_group(root)
        root.addStretch(0)

    def _build_source_group(self, root):
        self.grp_source = QGroupBox()
        layout = QVBoxLayout(self.grp_source)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)
        self.lbl_source = QLabel()
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setStyleSheet(
            "padding:8px;background:#F4F8FC;border:1px solid #D9E4EF;"
            "border-radius:6px;color:#24445F;")
        layout.addWidget(self.lbl_source)

        outdir_row = QHBoxLayout()
        outdir_row.setSpacing(4)
        self.lbl_outdir = QLabel()
        self.lbl_outdir.setMinimumWidth(64)
        self.edit_outdir = QLineEdit()
        self.edit_outdir.textEdited.connect(self._on_outdir_edited)
        self.btn_browse_outdir = QPushButton()
        self.btn_browse_outdir.clicked.connect(self._browse_outdir)
        outdir_row.addWidget(self.lbl_outdir, 0)
        outdir_row.addWidget(self.edit_outdir, 1)
        outdir_row.addWidget(self.btn_browse_outdir, 0)
        layout.addLayout(outdir_row)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(
            lambda _checked=False: self.set_source_from_main())
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        layout.addLayout(row)
        root.addWidget(self.grp_source)

    def _build_settings_group(self, root):
        self.grp_settings = QGroupBox()
        form = QFormLayout(self.grp_settings)
        form.setContentsMargins(10, 12, 10, 10)
        form.setSpacing(6)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.lbl_delta = QLabel()
        self.spin_delta = QDoubleSpinBox()
        self.spin_delta.setRange(_DELTA_MIN, _DELTA_MAX)
        self.spin_delta.setDecimals(4)
        self.spin_delta.setSingleStep(0.01)
        self.spin_delta.setSuffix(" a.u.")
        self.spin_delta.setMinimumWidth(_FIELD_MIN_WIDTH)
        self.spin_delta.setMaximumWidth(_FIELD_MAX_WIDTH)
        form.addRow(self.lbl_delta, self.spin_delta)

        self.lbl_grid = QLabel()
        self.cmb_grid = QComboBox()
        self.cmb_grid.setMinimumWidth(_FIELD_MIN_WIDTH)
        self.cmb_grid.setMaximumWidth(_FIELD_MAX_WIDTH)
        form.addRow(self.lbl_grid, self.cmb_grid)

        self.chk_weights = QCheckBox()
        form.addRow(self.chk_weights)

        self.chk_condensed = QCheckBox()
        form.addRow(self.chk_condensed)

        self.chk_export = QCheckBox()
        self.chk_export.toggled.connect(self._on_export_toggled)
        form.addRow(self.chk_export)

        self.lbl_note_title = QLabel()
        self.lbl_note_title.setStyleSheet(
            "font-size:12px;font-weight:600;color:#475569;")
        form.addRow(self.lbl_note_title)
        self.lbl_notes = QLabel()
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setStyleSheet("font-size:12px;color:#64748B;")
        form.addRow(self.lbl_notes)
        root.addWidget(self.grp_settings)

    def _build_run_group(self, root):
        self.grp_run = QGroupBox()
        layout = QVBoxLayout(self.grp_run)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.setMinimumHeight(42)
        self.btn_run.clicked.connect(self._start)
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        buttons.addWidget(self.btn_run, 1)
        buttons.addWidget(self.btn_stop, 0)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)
        root.addWidget(self.grp_run)

    @staticmethod
    def _make_table(columns):
        return _FitColumnsTable(columns)

    def _build_result_group(self, root):
        self.grp_result = QGroupBox()
        layout = QVBoxLayout(self.grp_result)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self._build_weights_tab()
        self._build_condensed_tab()
        self._build_vis_tab()
        self.tabs.addTab(self.tab_weights, "")
        self.tabs.addTab(self.tab_condensed, "")
        self.tabs.addTab(self.tab_vis, "")
        layout.addWidget(self.tabs, 1)
        root.addWidget(self.grp_result, 1)

    def _build_weights_tab(self):
        self.tab_weights = QWidget()
        layout = QVBoxLayout(self.tab_weights)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        self.lbl_orb_summary = QLabel()
        self.lbl_orb_summary.setWordWrap(True)
        self.lbl_orb_summary.setStyleSheet(
            "padding:6px 8px;background:#F8FAFC;border:1px solid #E2E8F0;"
            "border-radius:6px;color:#334155;")
        layout.addWidget(self.lbl_orb_summary)

        tables = QHBoxLayout()
        tables.setSpacing(6)
        self.grp_w_plus = QGroupBox()
        plus_layout = QVBoxLayout(self.grp_w_plus)
        plus_layout.setContentsMargins(6, 10, 6, 6)
        plus_layout.setSpacing(4)
        self.table_fplus = self._make_table(4)
        self.table_fplus.setMinimumHeight(220)
        plus_layout.addWidget(self.table_fplus)
        tables.addWidget(self.grp_w_plus, 1)

        self.grp_w_minus = QGroupBox()
        minus_layout = QVBoxLayout(self.grp_w_minus)
        minus_layout.setContentsMargins(6, 10, 6, 6)
        minus_layout.setSpacing(4)
        self.table_fminus = self._make_table(4)
        self.table_fminus.setMinimumHeight(220)
        minus_layout.addWidget(self.table_fminus)
        tables.addWidget(self.grp_w_minus, 1)
        layout.addLayout(tables, 1)

        # 「所列轨道权重合计」：Multiwfn 只打印前 9/10 条轨道（C60 默认 Δ
        # 下合计只有 70.46 % / 70.37 %，≠100 %），必须写清楚，否则会被
        # 误读成「总权重」。
        self.lbl_weight_total = QLabel()
        self.lbl_weight_total.setWordWrap(True)
        self.lbl_weight_total.setStyleSheet("font-size:12px;color:#64748B;")
        self.lbl_weight_total.setVisible(False)
        layout.addWidget(self.lbl_weight_total)

    def _build_condensed_tab(self):
        self.tab_condensed = QWidget()
        layout = QVBoxLayout(self.tab_condensed)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        self.lbl_condensed_state = QLabel()
        self.lbl_condensed_state.setWordWrap(True)
        self.lbl_condensed_state.setStyleSheet("color:#475569;")
        layout.addWidget(self.lbl_condensed_state)

        self.table_condensed = self._make_table(6)
        self.table_condensed.setMinimumHeight(240)
        layout.addWidget(self.table_condensed, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_export_csv = QPushButton()
        self.btn_export_csv.setEnabled(False)
        self.btn_export_csv.clicked.connect(self._export_csv)
        buttons.addWidget(self.btn_export_csv, 1)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _build_vis_tab(self):
        self.tab_vis = QWidget()
        layout = QVBoxLayout(self.tab_vis)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.lbl_function = QLabel()
        self.cmb_function = QComboBox()
        self.cmb_function.setMinimumWidth(_FIELD_MIN_WIDTH)
        self.cmb_function.setMaximumWidth(_FIELD_MAX_WIDTH)
        self.cmb_function.currentIndexChanged.connect(self._on_function_changed)
        form.addRow(self.lbl_function, self.cmb_function)

        self.lbl_iso = QLabel()
        self.spin_iso = QDoubleSpinBox()
        self.spin_iso.setRange(1e-6, 10.0)
        self.spin_iso.setDecimals(6)
        self.spin_iso.setSingleStep(0.0001)
        self.spin_iso.setValue(_ISO_FALLBACK)
        self.spin_iso.setSuffix(" a.u.")
        self.spin_iso.setMinimumWidth(_FIELD_MIN_WIDTH)
        self.spin_iso.setMaximumWidth(_FIELD_MAX_WIDTH)
        form.addRow(self.lbl_iso, self.spin_iso)
        layout.addLayout(form)

        self.lbl_iso_note = QLabel()
        self.lbl_iso_note.setWordWrap(True)
        self.lbl_iso_note.setStyleSheet("font-size:12px;color:#64748B;")
        layout.addWidget(self.lbl_iso_note)

        self.lbl_vis_state = QLabel()
        self.lbl_vis_state.setWordWrap(True)
        self.lbl_vis_state.setStyleSheet("color:#334155;")
        layout.addWidget(self.lbl_vis_state)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_show = QPushButton()
        self.btn_show.setObjectName("PrimaryBtn")
        self.btn_show.setEnabled(False)
        self.btn_show.clicked.connect(self._show_selected_on_canvas)
        row.addWidget(self.btn_show, 1)
        row.addStretch(1)
        layout.addLayout(row)

        self.grp_cubes = QGroupBox()
        cube_form = QFormLayout(self.grp_cubes)
        cube_form.setContentsMargins(10, 12, 10, 10)
        cube_form.setSpacing(4)
        cube_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._cube_func_labels = {}
        self._cube_edits = {}
        for key in FUNCTIONS:
            label = QLabel()
            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.setCursorPosition(0)
            self._cube_func_labels[key] = label
            self._cube_edits[key] = edit
            cube_form.addRow(label, edit)
        layout.addWidget(self.grp_cubes)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self.btn_open_dir = QPushButton()
        self.btn_open_dir.setEnabled(False)
        self.btn_open_dir.clicked.connect(self._open_output_dir)
        dir_row.addWidget(self.btn_open_dir, 1)
        dir_row.addStretch(1)
        layout.addLayout(dir_row)
        layout.addStretch(1)

    # ── 初始化：下拉框与默认值 ──────────────────────────────────────────
    def _populate_combos(self):
        for key in FUNCTIONS:
            self.cmb_function.addItem("", key)
        for quality in sorted(GRID_QUALITIES):
            self.cmb_grid.addItem("", int(quality))
        # 默认显示 Δf_w（最有代表性）
        index = self.cmb_function.findData("dd")
        if index >= 0:
            self._suppress_iso = True
            try:
                self.cmb_function.setCurrentIndex(index)
            finally:
                self._suppress_iso = False

    def _apply_defaults_from_core(self):
        delta = _as_float(DEFAULT_SETTINGS.get("delta"), 0.1)
        delta = max(_DELTA_MIN, min(_DELTA_MAX, delta))
        self.spin_delta.setValue(delta)
        quality = _as_int(DEFAULT_SETTINGS.get("grid_quality"), 2) or 2
        # 主窗口的格点质量作为面板初始值（用户仍可在面板里改）
        main_quality = self._grid_quality_from_main()
        preferred = main_quality if self.cmb_grid.findData(main_quality) >= 0 \
            else max(1, min(3, quality))
        index = self.cmb_grid.findData(preferred)
        if index >= 0:
            self.cmb_grid.setCurrentIndex(index)
        self.chk_weights.setChecked(bool(DEFAULT_SETTINGS.get("weights", True)))
        self.chk_condensed.setChecked(
            bool(DEFAULT_SETTINGS.get("condensed", True)))
        self.chk_export.setChecked(
            bool(DEFAULT_SETTINGS.get("export") or []))
        self._on_export_toggled(self.chk_export.isChecked())

    # ── 语言 ────────────────────────────────────────────────────────────
    def set_lang(self, lang):
        self._lang = "en" if lang == "en" else "zh"
        self.lang = self._lang
        self._apply_lang()

    def _apply_lang(self):
        t = self._t
        self.lbl_title.setText(t("title"))
        self.lbl_intro.setText(t("intro"))

        # 输入波函数
        self.grp_source.setTitle(t("source_group"))
        self.btn_refresh.setText(t("refresh"))
        self.btn_refresh.setToolTip(t("refresh_tip"))
        self.lbl_outdir.setText(t("outdir"))
        self.edit_outdir.setToolTip(t("outdir_tip"))
        self.edit_outdir.setPlaceholderText(t("outdir_placeholder"))
        self.btn_browse_outdir.setText(t("browse"))
        self.btn_browse_outdir.setToolTip(t("browse_tip"))

        # 计算设置
        self.grp_settings.setTitle(t("settings_group"))
        self.lbl_delta.setText(t("delta"))
        self.spin_delta.setToolTip(t("delta_tip"))
        self.lbl_grid.setText(t("grid"))
        self.cmb_grid.setToolTip(t("grid_tip"))
        for index in range(self.cmb_grid.count()):
            quality = self.cmb_grid.itemData(index)
            self.cmb_grid.setItemText(index, self._grid_label(quality))
        self.chk_weights.setText(t("opt_weights"))
        self.chk_weights.setToolTip(t("opt_weights_tip"))
        self.chk_condensed.setText(t("opt_condensed"))
        self.chk_condensed.setToolTip(t("opt_condensed_tip"))
        self.chk_export.setText(t("opt_export"))
        self.chk_export.setToolTip(t("opt_export_tip"))
        self.lbl_note_title.setText(t("note_title"))
        self.lbl_notes.setText(t("note_text"))

        # 运行
        self.grp_run.setTitle(t("run_group"))
        self.btn_run.setText(t("run"))
        self.btn_run.setToolTip(t("run_tip"))
        self.btn_stop.setText(t("stop"))
        self.btn_stop.setToolTip(t("stop_tip"))

        # 结果
        self.grp_result.setTitle(t("result_group"))
        self.tabs.setTabText(0, t("tab_weights"))
        self.tabs.setTabText(1, t("tab_condensed"))
        self.tabs.setTabText(2, t("tab_vis"))
        self._apply_weights_headers()
        self._apply_condensed_headers()
        self.grp_w_plus.setTitle(t("weight_group").format(
            name=self._func_label("fplus"), n=_TOP_WEIGHT_COUNT))
        self.grp_w_minus.setTitle(t("weight_group").format(
            name=self._func_label("fminus"), n=_TOP_WEIGHT_COUNT))
        self.btn_export_csv.setText(t("export_csv"))
        self.btn_export_csv.setToolTip(t("export_csv_tip"))

        # 可视化
        self.lbl_function.setText(t("function"))
        self.cmb_function.setToolTip(t("function_tip"))
        for index in range(self.cmb_function.count()):
            key = self.cmb_function.itemData(index)
            self.cmb_function.setItemText(index, self._func_label(key))
        self.lbl_iso.setText(t("iso"))
        self.spin_iso.setToolTip(t("iso_tip"))
        self.lbl_iso_note.setText(t("iso_fallback_note"))
        self.btn_show.setText(t("show_canvas"))
        self.btn_show.setToolTip(t("show_canvas_tip"))
        self.grp_cubes.setTitle(t("cube_group"))
        for key in FUNCTIONS:
            self._cube_func_labels[key].setText(self._func_label(key))
            self._cube_edits[key].setPlaceholderText(t("cube_missing"))
        self.btn_open_dir.setText(t("open_dir"))
        self.btn_open_dir.setToolTip(t("open_dir_tip"))

        # 语言切换后重新套用动态内容（状态、来源、摘要、表格、cube 路径）
        self._refresh_status()
        self._refresh_source_label()
        self._refresh_summary()
        self._refresh_weights_tables()
        self._refresh_condensed_table()
        self._refresh_cube_paths()
        self._refresh_vis_state()
        self._update_actions()

    def _apply_weights_headers(self):
        headers = [self._t("col_orbital"), self._t("col_mark"),
                   self._t("col_weight"), self._t("col_ediff")]
        for table in (self.table_fplus, self.table_fminus):
            table.setHorizontalHeaderLabels(headers)
            metrics = table.fontMetrics()
            # 「标记」列必须放得下 LUMO+10 / HOMO-10（旧固定 84 px 会被
            # 截成 "LUM…"）；按当前字体度量现算，DPI/中英文切换都适用。
            mark = max(
                _WEIGHT_MARK_MIN_WIDTH,
                min(_WEIGHT_MARK_MAX_WIDTH,
                    max(metrics.horizontalAdvance("LUMO+10"),
                        metrics.horizontalAdvance("HOMO-10")) + 16))
            # 「权重 %」列放得下表头与 100.00 / 12.47 这类数值。
            value = max(
                _WEIGHT_VALUE_WIDTH,
                min(140,
                    max(metrics.horizontalAdvance(headers[2]),
                        metrics.horizontalAdvance("100.00")) + 16))
            # 前三列固定宽度，最后一列（ε−μ）吃掉剩余宽度。
            table.set_fixed_widths(
                [64, int(mark), int(value)], last_min_width=72)

    def _apply_condensed_headers(self):
        headers = [self._t("col_atom"), self._t("col_element"),
                   self._t("col_fplus"), self._t("col_fminus"),
                   self._t("col_f0"), self._t("col_dd")]
        table = self.table_condensed
        table.setHorizontalHeaderLabels(headers)
        metrics = table.fontMetrics()
        # f+/f-/f0 三列要完整显示 0.01667 / -0.00000 / 0.999953 这类数值，
        # 不能把最后一列 OW DD 设为唯一 Stretch（旧实现把前三个数值列
        # 挤成了 "0.01..."）。
        value = max(
            _CONDENSED_VALUE_MIN_WIDTH,
            min(_CONDENSED_VALUE_MAX_WIDTH,
                max(metrics.horizontalAdvance("0.01667"),
                    metrics.horizontalAdvance("-0.00000"),
                    metrics.horizontalAdvance("0.999953"),
                    metrics.horizontalAdvance(headers[2])) + 16))
        table.set_fixed_widths(
            [_CONDENSED_INDEX_WIDTH, _CONDENSED_ELEMENT_WIDTH,
             int(value), int(value), int(value)],
            last_min_width=90)

    # ── 状态 / 输入来源 / 开壳层检查 ────────────────────────────────────
    def set_source_from_main(self, path=None):
        """读取（或接收）主界面当前波函数路径并刷新显示。"""
        if path is None:
            path = self._current_fchk()
        try:
            path = str(path or "").strip()
        except Exception:  # noqa: BLE001 - 异常输入按空处理
            path = ""
        self._source_path = path
        self._detect_shell(path)
        self._apply_outdir_default()
        self._refresh_source_label()
        self._refresh_vis_state()
        if not self._running and self._last_result is None:
            if not path or self._source_missing:
                self._set_status("status_no_source")
            elif self._shell_state == "open":
                self._set_status("status_open_shell")
            elif self._shell_state == "novirtual":
                self._set_status("status_no_virtual")
            else:
                self._set_status("status_ready")
        self._update_actions()

    def showEvent(self, event):
        # 切换回本页时跟随主窗口当前 fchk（载入新文件后不必手动点刷新）
        super().showEvent(event)
        self.set_source_from_main()

    def _detect_shell(self, path=None, force=False):
        """用 fchk_parser 预检闭壳层 / 空轨道；按 mtime 缓存避免重复解析。"""
        path = str(path if path is not None else self._source_path or "").strip()
        if not path:
            self._shell_state = ""
            self._shell_info = {}
            self._source_missing = False
            self._source_signature = None
            return
        if not os.path.isfile(path):
            self._shell_state = ""
            self._shell_info = {}
            self._source_missing = True
            self._source_signature = None
            return
        self._source_missing = False
        try:
            stat = os.stat(path)
            signature = (path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        if (not force and signature is not None
                and signature == self._source_signature):
            return
        self._source_signature = signature
        try:
            info = parse_fchk_mo_info(path)
        except Exception:  # noqa: BLE001 - .mwfn 等非 fchk 格式无法预检
            info = None
        if not isinstance(info, dict):
            self._shell_state = "unknown"
            self._shell_info = {}
            return
        self._shell_info = info
        n_alpha = _as_int(info.get("n_alpha"), 0) or 0
        n_basis = _as_int(info.get("n_basis"), 0) or 0
        if info.get("is_open_shell"):
            self._shell_state = "open"
        elif n_basis and n_alpha and (info.get("lumo_idx") is None):
            self._shell_state = "novirtual"
        elif n_basis or n_alpha:
            self._shell_state = "closed"
        else:
            self._shell_state = "unknown"

    def _refresh_source_label(self):
        path = self._source_path
        if not path or self._source_missing:
            if path:
                self.lbl_source.setText(
                    self._t("source_missing").format(path=path))
            else:
                self.lbl_source.setText(self._t("source_none"))
            return
        folder = os.path.dirname(path) or "."
        text = self._t("source_ready").format(
            name=os.path.basename(path), dir=folder)
        key = {
            "closed": "source_shell_closed",
            "open": "source_shell_open",
            "novirtual": "source_shell_no_virtual",
            "unknown": "source_shell_unknown",
        }.get(self._shell_state)
        if key:
            text += "\n" + self._t(key)
        self.lbl_source.setText(text)

    def _apply_outdir_default(self):
        if not self._outdir_auto or not self._source_path:
            return
        folder = os.path.dirname(self._source_path)
        if folder:
            self.edit_outdir.setText(folder)

    def _on_outdir_edited(self, _text):
        # 用户手动改过输出目录后，不再跟随输入文件所在目录
        self._outdir_auto = False

    def _browse_outdir(self):
        start = self.edit_outdir.text().strip()
        if not start and self._source_path:
            start = os.path.dirname(self._source_path)
        path = QFileDialog.getExistingDirectory(
            self, self._t("pick_outdir_title"), start)
        if path:
            self._outdir_auto = False
            self.edit_outdir.setText(path)
            self._update_actions()

    # ── 设置读写 ────────────────────────────────────────────────────────
    def _on_export_toggled(self, checked):
        enabled = bool(checked)
        self.lbl_grid.setEnabled(enabled)
        self.cmb_grid.setEnabled(enabled)

    def _settings(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["delta"] = round(float(self.spin_delta.value()), 6)
        quality = _as_int(self.cmb_grid.currentData())
        settings["grid_quality"] = quality if quality in (1, 2, 3) else 2
        settings["weights"] = bool(self.chk_weights.isChecked())
        settings["condensed"] = bool(self.chk_condensed.isChecked())
        settings["export"] = ([key for key in FUNCTIONS]
                              if self.chk_export.isChecked() else [])
        return settings

    # ── 运行 / 停止 ─────────────────────────────────────────────────────
    def _start(self):
        if self._running:
            return
        fchk = self._source_path or self._current_fchk()
        if not fchk or not os.path.isfile(fchk):
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_source"))
            return
        self._detect_shell(fchk, force=True)
        if self._shell_state == "open":
            QMessageBox.warning(
                self, self._t("warning"), self._t("open_shell_blocked"))
            self._set_status("status_open_shell")
            self._update_actions()
            return
        if self._shell_state == "novirtual":
            QMessageBox.warning(
                self, self._t("warning"), self._t("no_virtual_blocked"))
            self._set_status("status_no_virtual")
            self._update_actions()
            return
        multiwfn = self._current_multiwfn()
        if not multiwfn or not os.path.isfile(multiwfn):
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_mw"))
            return
        settings = self._settings()
        if not (settings["weights"] or settings["condensed"]
                or settings["export"]):
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_any_task"))
            return
        out_dir = self.edit_outdir.text().strip()
        if not out_dir:
            out_dir = os.path.dirname(fchk)
        # 新的一次计算会覆盖同名 cube，等值面缓存必须失效
        self._iso_cache.clear()

        self._worker = OWFukuiWorker(
            fchk, multiwfn, settings, out_dir=out_dir, parent=self)
        self._worker.log.connect(self._on_log)
        self._worker.stage.connect(self._on_stage)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._log(self._t("log_run").format(
            delta="%.4f" % settings["delta"],
            grid=self._grid_label(settings["grid_quality"]),
            dir=out_dir,
            fchk=os.path.basename(fchk)))
        # 先进入忙状态，核心模块报来第一个阶段后再切成百分比
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self._set_status("status_working")
        self._set_running(True)
        self._worker.start()

    def _stop(self):
        if self._worker is None or not self._worker.isRunning():
            return
        self._worker.stop()
        self._set_status("status_cancelling")
        self._log(self._t("log_cancelling"))

    def _set_running(self, running):
        self._running = bool(running)
        for widget in (self.grp_source, self.grp_settings, self.btn_run):
            widget.setEnabled(not self._running)
        self.btn_stop.setEnabled(self._running)
        self._update_actions()

    def _on_stage(self, percent, _text):
        # 核心模块的 stage 文本是中文，且只用于日志/调试；状态行保持本面板
        # 的本地化文案，避免英文界面混入中文。
        try:
            value = int(percent)
        except (TypeError, ValueError):
            value = 0
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, value)))

    def _on_worker_finished(self, result):
        worker = self._worker
        cancelled = bool(worker is not None and worker.is_stopped())
        if self._shutting_down:
            # 关窗阶段：不弹窗、不刷界面，安静收尾即可
            self._worker = None
            self._running = False
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid OW-Fukui result",
                      "weights": {}, "condensed": [], "sums": {},
                      "cubes": {}, "warnings": []}
        self._apply_result(result)
        # 设置区很长，结果在页面底部：跑完自动滚到结果区
        try:
            self.scroll_area.ensureWidgetVisible(self.grp_result, 0, 0)
        except Exception:  # noqa: BLE001 - 滚动失败不影响结果
            pass
        self.progress.setRange(0, 100)
        if result.get("ok") and not cancelled:
            self.progress.setValue(100)
            seconds = _as_float(result.get("seconds"))
            secs_text = (("%.1f" % seconds) if seconds is not None
                         else self._t("dash"))
            cube_count = self._cube_count(result)
            self._set_status("status_done_fmt",
                             secs=secs_text, n=cube_count)
            self._log(self._t("log_done").format(
                n=cube_count, secs=secs_text))
            for warning in result.get("warnings") or []:
                self._log(self._t("log_warning").format(msg=warning))
            self._auto_show_cube(result)
        elif cancelled:
            self.progress.setValue(0)
            self._set_status("status_cancelled")
            self._log(self._t("log_cancelled"))
        else:
            self.progress.setValue(0)
            error = str(result.get("error") or self._t("status_failed"))
            self._set_status("status_failed")
            self._log(self._t("log_error").format(msg=error))
            QMessageBox.warning(self, self._t("failed_title"), error)
        self._finish_worker()

    def _on_worker_failed(self, message):
        if self._shutting_down:
            self._worker = None
            self._running = False
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if self._worker is not None and self._worker.is_stopped():
            self._set_status("status_cancelled")
            self._log(self._t("log_cancelled"))
            self._finish_worker()
            return
        self._set_status("status_failed")
        self._log(self._t("log_error").format(msg=message))
        QMessageBox.warning(
            self, self._t("failed_title"),
            str(message or self._t("status_failed")))
        self._finish_worker()

    def _finish_worker(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(3000)
            except Exception:  # noqa: BLE001 - 清理失败不影响界面
                pass
        self._set_running(False)

    # ── 结果展示 ────────────────────────────────────────────────────────
    def _apply_result(self, result):
        """把核心模块的结果字典套用到摘要与结果表（探针脚本也直接调用它）。"""
        if not isinstance(result, dict):
            return
        self._last_result = result
        self._refresh_summary()
        self._refresh_weights_tables()
        self._refresh_condensed_table()
        self._refresh_cube_paths()
        self._refresh_vis_state()
        self._update_actions()

    @staticmethod
    def _cube_map(result):
        cubes = result.get("cubes") if isinstance(result, dict) else None
        return cubes if isinstance(cubes, dict) else {}

    def _cube_count(self, result=None):
        result = result if isinstance(result, dict) else (self._last_result or {})
        cubes = self._cube_map(result)
        count = 0
        for key in FUNCTIONS:
            path = str(cubes.get(key) or "").strip()
            if path and os.path.isfile(path):
                count += 1
        if not count:
            exported = result.get("exported") or []
            count = len(exported) if isinstance(exported, list) else 0
        return count

    def _cube_path(self, key, result=None):
        result = result if isinstance(result, dict) else (self._last_result or {})
        path = str(self._cube_map(result).get(key) or "").strip()
        return path if path and os.path.isfile(path) else ""

    def _result_delta(self, result):
        value = _as_float(result.get("delta"))
        if value is not None:
            return value
        settings = result.get("settings")
        if isinstance(settings, dict):
            return _as_float(settings.get("delta"))
        return None

    def _refresh_summary(self):
        result = self._last_result
        if not isinstance(result, dict) or not result:
            self.lbl_orb_summary.setText(self._t("summary_empty"))
            return
        lines = [self._t("summary_fmt").format(
            homo=self._fmt_number(result.get("homo_energy"), 6),
            lumo=self._fmt_number(result.get("lumo_energy"), 6),
            mu=self._fmt_number(result.get("chemical_potential"), 6),
            delta=self._fmt_number(self._result_delta(result), 6))]
        grid = result.get("grid")
        if isinstance(grid, dict) and grid:
            quality = _as_int(grid.get("quality"))
            quality_text = (self._grid_label(quality)
                            if quality in (1, 2, 3) else self._t("dash"))
            spacing = _as_float(grid.get("spacing_bohr"))
            lines.append(self._t("grid_fmt").format(
                nx=_as_int(grid.get("nx"), 0) or 0,
                ny=_as_int(grid.get("ny"), 0) or 0,
                nz=_as_int(grid.get("nz"), 0) or 0,
                npoints=_as_int(grid.get("npoints"), 0) or 0,
                spacing=(("%.6f" % spacing) if spacing is not None
                         else self._t("dash")),
                quality=quality_text))
        weights = result.get("weights")
        has_weights = isinstance(weights, dict) and any(
            weights.get(key) for key in ("fplus", "fminus"))
        if has_weights and self._degenerate_hint(result):
            lines.append(self._t("degenerate_hint"))
        if not has_weights and result.get("ok"):
            lines.append(self._t("weights_not_computed"))
        self.lbl_orb_summary.setText("\n".join(lines))

    def _degenerate_hint(self, result):
        """f+ / f- 前几个轨道权重并列时返回 True（准简并体系适用场景）。"""
        weights = result.get("weights")
        if not isinstance(weights, dict):
            return False
        for key in ("fplus", "fminus"):
            entries = weights.get(key)
            if not isinstance(entries, list):
                continue
            values = []
            for entry in entries[:5]:
                if isinstance(entry, dict):
                    value = _as_float(entry.get("weight"))
                    if value is not None:
                        values.append(value)
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    if abs(values[i] - values[j]) < 0.01:
                        return True
        return False

    def _fill_weight_table(self, table, entries):
        table.setRowCount(0)
        if not isinstance(entries, list) or not entries:
            return
        table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            cells = (
                _as_int(entry.get("index")),
                str(entry.get("label") or self._t("dash")),
                _as_float(entry.get("weight")),
                _as_float(entry.get("ediff_ev")),
            )
            texts = (
                str(cells[0]) if cells[0] is not None else self._t("dash"),
                cells[1],
                self._fmt_number(cells[2], 2),
                self._fmt_number(cells[3], 3),
            )
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, column, item)

    def _refresh_weights_tables(self):
        result = self._last_result or {}
        weights = result.get("weights") if isinstance(result, dict) else None
        weights = weights if isinstance(weights, dict) else {}
        self._fill_weight_table(
            self.table_fplus, weights.get("fplus"))
        self._fill_weight_table(
            self.table_fminus, weights.get("fminus"))
        # 表高按实际行数调整：10 行权重表整屏可见，不用在小表格里滚动
        for table in (self.table_fplus, self.table_fminus):
            table.refresh_column_widths()
            self._fit_table_height(table)
        self._refresh_weight_total()

    @staticmethod
    def _fit_table_height(table, max_rows=10):
        """按实际行高把权重表撑到能一次显示 ``max_rows`` 行。"""
        rows = table.rowCount()
        if rows <= 0:
            return
        table.resizeRowsToContents()
        total = 0
        for row in range(min(rows, max_rows)):
            height = table.verticalHeader().sectionSize(row)
            if height <= 0:
                height = table.verticalHeader().defaultSectionSize()
            total += height
        header_height = table.horizontalHeader().height()
        if header_height <= 0:
            header_height = max(28, table.fontMetrics().height() + 12)
        table.setMinimumHeight(header_height + total + 8)

    def _refresh_weight_total(self):
        """显示 Multiwfn 实际列出的轨道权重合计（可能 < 100 %，不是总权重）。"""
        result = self._last_result
        weights = (result.get("weights")
                   if isinstance(result, dict) else None)
        has_weights = isinstance(weights, dict) and any(
            weights.get(key) for key in ("fplus", "fminus"))
        if not has_weights:
            self.lbl_weight_total.setVisible(False)
            return
        total = result.get("total_weight")
        total = total if isinstance(total, dict) else {}
        self.lbl_weight_total.setText(self._t("weight_total_fmt").format(
            plus=self._fmt_number(total.get("fplus"), 2),
            minus=self._fmt_number(total.get("fminus"), 2)))
        self.lbl_weight_total.setVisible(True)

    def _condensed_rows(self):
        result = self._last_result or {}
        condensed = result.get("condensed") if isinstance(result, dict) else None
        if not isinstance(condensed, list):
            return []
        return [row for row in condensed if isinstance(row, dict)]

    def _refresh_condensed_table(self):
        rows = self._condensed_rows()
        table = self.table_condensed
        table.setRowCount(0)
        result = self._last_result
        if not rows:
            if isinstance(result, dict) and result:
                self.lbl_condensed_state.setText(
                    self._t("condensed_not_computed"))
            else:
                self.lbl_condensed_state.setText(self._t("condensed_empty"))
            return
        sums = result.get("sums") if isinstance(result, dict) else None
        sums = sums if isinstance(sums, dict) else {}
        table.setRowCount(len(rows) + 2)
        for row_index, entry in enumerate(rows):
            cells = (
                _as_int(entry.get("index")),
                str(entry.get("element") or ""),
                _as_float(entry.get("fplus")),
                _as_float(entry.get("fminus")),
                _as_float(entry.get("f0")),
                _as_float(entry.get("dd")),
            )
            texts = (
                str(cells[0]) if cells[0] is not None else self._t("dash"),
                cells[1],
                self._fmt_number(cells[2], 5),
                self._fmt_number(cells[3], 5),
                self._fmt_number(cells[4], 5),
                self._fmt_number(cells[5], 5),
            )
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, column, item)
        # 底部两行 sum（f+ / f-）
        sum_rows = (
            (self._t("sum_fplus"), 2, _as_float(sums.get("fplus"))),
            (self._t("sum_fminus"), 3, _as_float(sums.get("fminus"))),
        )
        for offset, (label, column, value) in enumerate(sum_rows):
            row_index = len(rows) + offset
            label_item = QTableWidgetItem(label)
            font = label_item.font()
            font.setBold(True)
            label_item.setFont(font)
            table.setItem(row_index, 0, label_item)
            value_item = QTableWidgetItem(self._fmt_number(value, 6))
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value_font = value_item.font()
            value_font.setBold(True)
            value_item.setFont(value_font)
            table.setItem(row_index, column, value_item)
        self.lbl_condensed_state.setText(
            self._t("condensed_summary_fmt").format(
                n=len(rows),
                fplus=self._fmt_number(sums.get("fplus"), 6),
                fminus=self._fmt_number(sums.get("fminus"), 6)))
        self.table_condensed.refresh_column_widths()

    def _refresh_cube_paths(self):
        result = self._last_result or {}
        cubes = self._cube_map(result)
        for key in FUNCTIONS:
            edit = self._cube_edits.get(key)
            if edit is None:
                continue
            path = str(cubes.get(key) or "").strip()
            edit.setText(path)
            edit.setCursorPosition(0)
            edit.setToolTip(path)

    def _refresh_vis_state(self):
        key = self.cmb_function.currentData()
        path = self._cube_path(key)
        name = self._func_label(key)
        if path:
            self.lbl_vis_state.setText(self._t("vis_state_ready").format(
                name=name, cube=os.path.basename(path)))
        else:
            self.lbl_vis_state.setText(self._t("vis_state_missing").format(
                name=name))

    def _suggest_iso_cached(self, path):
        """按 cube 路径缓存 ``suggest_iso`` 结果（cube 可能 1.8 MB+，别反复读）。"""
        path = str(path or "")
        if not path:
            return None
        if path in self._iso_cache:
            return self._iso_cache[path]
        try:
            iso = suggest_iso(path)
        except Exception as exc:  # noqa: BLE001 - 推荐失败不影响界面
            self._log(self._t("log_warning").format(msg=exc))
            iso = None
        value = _as_float(iso)
        if value is not None and value <= 0:
            value = None
        self._iso_cache[path] = value
        return value

    def _refresh_iso_suggestion(self):
        """按当前函数 cube 数据推荐等值面；读失败时保持当前值。"""
        path = self._cube_path(self.cmb_function.currentData())
        if not path:
            return
        value = self._suggest_iso_cached(path)
        if value is None:
            return
        self.spin_iso.setValue(
            max(self.spin_iso.minimum(),
                min(self.spin_iso.maximum(), value)))

    def _select_function(self, key):
        index = self.cmb_function.findData(key)
        if index < 0:
            return
        self._suppress_iso = True
        try:
            self.cmb_function.setCurrentIndex(index)
        finally:
            self._suppress_iso = False

    def _on_function_changed(self, *_args):
        if self._suppress_iso:
            return
        self._refresh_iso_suggestion()
        self._refresh_vis_state()
        self._update_actions()

    def _auto_show_cube(self, result):
        """计算完成后自动把 Δf_w（dd）cube 显示到画布并同步等值面。"""
        if self._on_show_cube is None and self.glw is None:
            # 没有画布（例如无 GUI 的探针/回归环境）：安静跳过，不弹窗
            return
        result = result if isinstance(result, dict) else {}
        cubes = self._cube_map(result)
        key = ""
        for candidate in _AUTO_SHOW_ORDER:
            path = str(cubes.get(candidate) or "").strip()
            if path and os.path.isfile(path):
                key = candidate
                break
        if not key:
            return
        path = str(cubes.get(key) or "").strip()
        iso = self._suggest_iso_cached(path)
        self._select_function(key)
        if iso is not None and iso > 0:
            self.spin_iso.setValue(
                max(self.spin_iso.minimum(),
                    min(self.spin_iso.maximum(), iso)))
        elif iso is None:
            iso = self.spin_iso.value()
        self._refresh_vis_state()
        name = self._func_label(key)
        if self._show_cube(path, iso):
            self._log(self._t("log_auto_show").format(
                name=name, iso=self._fmt_number(iso, 6)))
        else:
            self._log(self._t("log_warning").format(
                msg=self._t("no_canvas")))

    # ── 可视化 ──────────────────────────────────────────────────────────
    def _show_selected_on_canvas(self):
        key = self.cmb_function.currentData()
        path = self._cube_path(key)
        if not path:
            QMessageBox.warning(
                self, self._t("warning"),
                self._t("no_cube").format(name=self._func_label(key)))
            return
        iso = float(self.spin_iso.value())
        if self._show_cube(path, iso):
            self._log(self._t("log_show").format(
                name=self._func_label(key),
                iso=self._fmt_number(iso, 6)))
        else:
            QMessageBox.warning(
                self, self._t("warning"), self._t("no_canvas"))

    def _show_cube(self, cube_path, iso):
        cube_path = str(cube_path or "")
        if not cube_path or not os.path.isfile(cube_path):
            return False
        value = float(iso) if iso is not None else None
        if self._on_show_cube is not None:
            try:
                self._on_show_cube(cube_path, value)
                return True
            except Exception as exc:  # noqa: BLE001 - 回调失败退回 glw
                self._log(self._t("log_warning").format(msg=exc))
        glw = self.glw
        if glw is not None:
            try:
                glw.load(cube_path, value if value is not None else 0.05)
                return True
            except Exception as exc:  # noqa: BLE001 - 无画布时降级
                self._log(self._t("log_warning").format(msg=exc))
        return False

    # ── 导出 / 打开目录 ─────────────────────────────────────────────────
    def _output_dir(self):
        result = self._last_result or {}
        log_path = str(result.get("log_path") or "").strip()
        if log_path:
            return os.path.dirname(log_path)
        cubes = self._cube_map(result)
        for key in FUNCTIONS:
            path = str(cubes.get(key) or "").strip()
            if path:
                return os.path.dirname(path)
        text = self.edit_outdir.text().strip()
        if text:
            return text
        if self._source_path:
            return os.path.dirname(self._source_path)
        return ""

    def _export_csv(self):
        condensed = self._condensed_rows()
        if not condensed:
            QMessageBox.warning(
                self, self._t("warning"), self._t("no_condensed"))
            return
        out_dir = self._output_dir() or os.getcwd()
        stem = os.path.splitext(os.path.basename(
            self._source_path or "OWFukui"))[0] or "OWFukui"
        default_path = os.path.join(
            out_dir, stem + "_OWFukui_condensed.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("export_csv"), default_path,
            self._t("csv_filter"))
        if not path:
            return
        try:
            saved = export_condensed_csv(
                path, condensed, lang=self._lang)
        except Exception as exc:  # noqa: BLE001 - 导出失败弹窗提示
            message = self._t("csv_failed_msg").format(msg=exc)
            self._log(message)
            QMessageBox.warning(self, self._t("failed_title"), message)
            return
        saved_path = str(saved or path)
        self._log(self._t("log_csv_saved").format(path=saved_path))

    def _open_output_dir(self):
        path = self._output_dir()
        if not path or not os.path.isdir(path):
            QMessageBox.warning(
                self, self._t("warning"),
                self._t("open_dir_failed").format(
                    path=path or self._t("dash")))
            return
        try:
            os.startfile(path)  # Windows
            return
        except AttributeError:
            pass
        except Exception as exc:  # noqa: BLE001 - 退回 QDesktopServices
            self._log(str(exc))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ── 动作可用状态 ────────────────────────────────────────────────────
    def _update_actions(self):
        busy = self._running
        source_ok = (bool(self._source_path)
                     and not self._source_missing
                     and os.path.isfile(self._source_path))
        blocked = self._shell_state in ("open", "novirtual")
        self.btn_run.setEnabled(source_ok and not blocked and not busy)
        self.btn_stop.setEnabled(busy)
        self.btn_export_csv.setEnabled(
            bool(self._condensed_rows()) and not busy)
        any_cube = any(self._cube_path(key) for key in FUNCTIONS)
        self.btn_show.setEnabled(any_cube and not busy)
        self.btn_open_dir.setEnabled(
            bool(self._output_dir()) and not busy)

    # ── 生命周期 ────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        """主窗口关闭时调用：停止后台计算线程。

        关闭阶段不再弹任何模态框：后台线程被 stop() 终止后仍可能通过队列
        把 finished/failed 信号送进来，``_shutting_down`` 让这些槽函数安静
        退出（否则关窗时会弹「计算失败」对话框，甚至阻塞退出）。
        """
        self._shutting_down = True
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.stop()
                    worker.wait(5000)
            except Exception:  # noqa: BLE001 - 关闭阶段不再抛错
                pass
        self._running = False


__all__ = ["OWFukuiPanel", "OWFukuiWorker", "TEXT"]
