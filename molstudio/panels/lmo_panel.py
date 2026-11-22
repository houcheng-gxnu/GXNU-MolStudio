# -*- coding: utf-8 -*-
"""轨道定域化（LMO）面板。

把主窗口当前载入的 .fchk 交给 Multiwfn 主功能 19（轨道定域化）处理，
得到保留 σ/π 分离的局域分子轨道（LMO），在右侧页面用表格展示
能量、占据、成分指认与 LMO 中心；双击某一行即可生成该 LMO 的
cube 并交给画布显示。定域化完成后，同一页面还可对 `_LMO.fch`
运行 Multiwfn 的 LOBA / mLOBA 氧化态分析。

设计遵循仓库其它面板的惯例：
* 所有界面文字都放在模块级 ``TEXT`` 字典里，``set_lang()`` 负责整页刷新；
* 耗时操作跑在 ``QThread`` 里，通过 ``on_log`` / ``on_stage`` 回调汇报进度；
* 面板本身不持有主窗口状态，只通过构造时注入的回调取输入、送结果。
"""

from __future__ import annotations

import csv
import os
import re
import threading

from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from molstudio.core.multiwfn_lmo import (
    BOHR_TO_ANG,
    COMPOSITION_METHODS,
    DEFAULT_SETTINGS,
    LMO_METHODS,
    LOBA_DEFAULT_SETTINGS,
    LOBA_METHODS,
    gen_lmo_cube,
    parse_lmocen,
    parse_fragment_spec,
    run_localization,
    run_loba,
)


# ── 界面文字 ─────────────────────────────────────────────────────────────
# 键名尽量语义化；新增键必须 zh / en 成对出现（回归测试会检查英文界面无中文）。
TEXT = {
    "zh": {
        "title": "轨道定域化",
        "intro": (
            "把当前波函数交给 Multiwfn 主功能 19 做轨道定域化（LMO），"
            "得到保留 σ/π 分离的局域分子轨道；双击结果行即可在画布上查看"
            "该 LMO 的等值面，并可继续计算 LOBA 氧化态。"
            "<a href=\"http://sobereva.com/380\">Multiwfn 轨道定域化教程</a>"
            " · <a href=\"http://sobereva.com/362\">LOBA 氧化态教程</a>"
        ),
        "source_group": "输入波函数",
        "source_none": "请先在主界面载入 .fch / .fchk 文件。",
        "source_ready": "文件：{name}\n输出目录：{dir}",
        "refresh": "刷新",
        "refresh_tip": "重新读取主界面当前载入的波函数",
        "settings_group": "定域化设置",
        "method": "定域化方法",
        "method_tip": (
            "PM-Mulliken 速度快且保持 σ/π 分离，是默认选择；"
            "PM-Löwdin 同样快速；PM-Becke 对含弥散函数的基组更稳健但更耗时；"
            "Foster-Boys 稳健，但会得到香蕉键，不再保持 σ/π 分离。"
        ),
        "scope": "定域化范围",
        "scope_occupied": "仅占据轨道",
        "scope_all": "占据 + 未占据轨道",
        "calc_energy": "计算 LMO 能量",
        "energy_source": "能量来源",
        "energy_mo": "由 MO 能量与系数反解",
        "energy_file": "从文件读取（.47 等）",
        "energy_source_tip": "LMO 能量是 Fock 算符的期望值；可由 MO 能量与系数反解，也可读取已有能量文件。",
        "fock_file": "能量数据文件",
        "fock_placeholder": "选择含 Fock 矩阵的能量文件，例如 .47",
        "browse": "浏览…",
        "fock_filter": "能量数据 (*.47 *.47?);;所有文件 (*)",
        "fock_pick_title": "选择能量数据文件",
        "composition": "成分指认方法",
        "composition_tip": (
            "用原子成分判断 LMO 类型：单中心（一个原子 > 单中心阈值）、"
            "双中心（两个原子合计 > 双中心阈值）、其余为多中心。"
            "Hirshfeld 是默认方法。"
        ),
        "composition_none": "不指认",
        "thr_single": "单中心阈值 (%)",
        "thr_two": "双中心阈值 (%)",
        "thr_single_tip": "一个原子的贡献超过该百分比时，记为单中心 LMO",
        "thr_two_tip": "两个原子的贡献合计超过该百分比时，记为双中心 LMO",
        "advanced": "高级",
        "advanced_show": "展开高级设置",
        "advanced_hide": "收起高级设置",
        "core_orb": "核心轨道参与定域化",
        "convergence": "收敛判据",
        "convergence_tip": "相邻两轮定域化之间的最大变化低于该值时判定收敛",
        "max_cycles": "最大迭代轮数",
        "centers": "生成 LMO 中心并加入偶极分析",
        "centers_tip": (
            "调用 LMOcen 计算 LMO 中心；分析时会向输入加入 Bq 原子，"
            "仅 Multiwfn 使用，不改变本软件中的分子结构。"
        ),
        "dipole": "同时计算 LMO 偶极矩",
        "centers_note": (
            "注：LMO 中心分析会向输入文件加入 Bq 原子（仅 Multiwfn 使用，"
            "不影响本软件显示的结构）。"
        ),
        "run_group": "运行",
        "run": "开始定域化",
        "stop": "停止",
        "status_no_source": "请先在主界面载入 .fch / .fchk 文件。",
        "status_ready": "就绪：载入波函数后点击「开始定域化」。",
        "status_working": "正在定域化…",
        "status_done": "定域化完成",
        "status_failed": "定域化失败",
        "status_cancelling": "正在停止…",
        "status_cancelled": "已停止",
        "status_generating": "正在生成 LMO {label} 的 cube…",
        "status_cube_done": "cube 已生成：{name}",
        "status_cube_failed": "cube 生成失败",
        "result_group": "LMO 结果",
        "summary_empty": "结果会在定域化完成后显示在这里。",
        "summary": (
            "{method} · {conv} · 迭代 {cycles} 轮 · 用时 {secs} s · "
            "{n} 个 LMO{warn}\nLMO 波函数：{lmo}\n日志：{log}"
        ),
        "summary_cen": "LMO 中心：{name}",
        "summary_dip": "LMO 偶极：{name}",
        "loba_title": "LOBA 氧化态分析",
        "loba_intro": (
            "对已定域化波函数计算 Hirshfeld 轨道成分，按贡献阈值把每个"
            "占据轨道的电子归属给原子（LOBA），或用“最大贡献归属”"
            "（mLOBA）得到氧化态。可填片段原子序号（如 1-5,7-11）"
            "同时计算片段氧化态。"
        ),
        "loba_method": "方法",
        "loba_threshold": "贡献阈值 (%)",
        "loba_fragment": "片段原子",
        "loba_fragment_placeholder": "例如 1-5,7-11；留空只算逐原子结果",
        "loba_fragment_tip": (
            "按 Multiwfn 原子序号填写，支持逗号与范围。留空只输出逐原子氧化态。"
        ),
        "loba_threshold_tip": (
            "常用 50%；结果异常时可比较 60%、70%。阈值敏感通常说明 "
            "LOBA 对该体系或原子不够可靠。"
        ),
        "loba_method_tip": (
            "LOBA 只在单原子贡献超过阈值时归属该轨道；mLOBA 总是归属给"
            "贡献最大的原子。两者都使用 Hirshfeld 原子成分。"
        ),
        "loba_hint": (
            "LOBA 使用 Hirshfeld 成分，不保证总和等于净电荷；过渡金属"
            "通常是 LOBA 最可靠的使用对象。建议用不同阈值或 mLOBA 做稳定性对照。"
        ),
        "loba_run": "计算氧化态",
        "loba_stop": "停止",
        "loba_status_waiting": "请先完成轨道定域化，生成 LMO 波函数。",
        "loba_status_ready": "就绪：可在已定域化波函数上运行 LOBA。",
        "loba_status_working": "正在计算 LOBA 氧化态…",
        "loba_status_done": "LOBA 氧化态计算完成",
        "loba_status_failed": "LOBA 氧化态计算失败",
        "loba_status_cancelled": "LOBA 已停止",
        "loba_result_empty": "氧化态结果会显示在这里。",
        "loba_summary": (
            "{method} · Hirshfeld · {threshold} · 用时 {secs} s\n"
            "氧化态总和：{sum}　体系净电荷：{charge}\n日志：{log}"
        ),
        "loba_summary_fragment": "片段 {fragment} 的氧化态：{state}",
        "loba_sum_error": "总和与净电荷不一致；LOBA 不保证二者相等。",
        "loba_col_index": "原子",
        "loba_col_element": "元素",
        "loba_col_state": "氧化态",
        "loba_export": "导出氧化态 CSV",
        "loba_export_tip": "把逐原子氧化态导出为 UTF-8 CSV 文件",
        "loba_no_result": "尚未生成 LOBA 氧化态结果",
        "loba_no_lmo_fch": "找不到已定域化的 LMO 波函数，请先运行轨道定域化",
        "loba_invalid_fragment": "片段原子定义无效：{msg}",
        "loba_failed_title": "LOBA 分析失败",
        "loba_log_start": "[LOBA] {method} · {threshold} · {fragment}",
        "loba_log_done": "[LOBA] 完成：{n} 个原子，总和 {sum}，用时 {secs} s",
        "loba_log_error": "[LOBA] 失败：{msg}",
        "loba_log_cancelling": "[LOBA] 正在停止…",
        "loba_log_cancelled": "[LOBA] 已停止",
        "loba_log_csv_saved": "[LOBA] CSV 已保存：{path}",
        "conv_yes": "已收敛",
        "conv_no": "未收敛",
        "warn_count": " · {n} 条警告",
        "col_orbital": "轨道",
        "col_energy_au": "E (a.u.)",
        "col_energy_ev": "E (eV)",
        "col_occ": "占据",
        "col_kind": "指认",
        "col_contrib": "主要贡献",
        "col_center": "中心 (Å)",
        "kind_single": "单中心",
        "kind_two": "双中心",
        "kind_more": "多中心",
        "kind_unknown": "未指认",
        "kind_tip_single": "单中心 LMO（一个原子贡献超过单中心阈值）",
        "kind_tip_two": "双中心 LMO（两个原子贡献合计超过双中心阈值）",
        "kind_tip_more": "离域到三个及以上中心的 LMO",
        "kind_tip_unknown": "未做轨道成分分析，无法指认中心数",
        "spin_alpha": "α",
        "spin_beta": "β",
        "spin_both": "α+β",
        "orbital_fmt": "{spin} {index}",
        "dash": "—",
        "visualize": "可视化选中 LMO",
        "visualize_tip": "在画布上显示选中 LMO 的等值面（双击表格行也可以）",
        "open_wavefunction": "用 LMO 波函数打开轨道表",
        "open_wavefunction_tip": "把导出的 LMO 波函数切换为当前波函数，便于用轨道表浏览",
        "export_csv": "导出 CSV",
        "export_csv_tip": "把结果表导出为 UTF-8 CSV 文件",
        "open_dir": "打开输出目录",
        "open_dir_tip": "打开 LMO 结果所在的输出目录",
        "csv_filter": "CSV (*.csv)",
        "csv_orbital": "轨道",
        "csv_spin": "自旋",
        "csv_energy_au": "能量(a.u.)",
        "csv_energy_ev": "能量(eV)",
        "csv_occ": "占据",
        "csv_kind": "指认",
        "csv_contrib": "主要贡献",
        "csv_center_x": "中心X(Ang)",
        "csv_center_y": "中心Y(Ang)",
        "csv_center_z": "中心Z(Ang)",
        "warning": "提示",
        "failed_title": "定域化失败",
        "need_source": "请先在主界面载入 .fch / .fchk 文件",
        "need_mw": "请先在主界面路径设置中配置 Multiwfn",
        "need_fock": "已选择从文件读取能量，请先指定能量数据文件",
        "need_fock_missing": "指定的能量数据文件不存在：{path}",
        "need_fock_missing_status": "能量数据文件不存在",
        "no_selection": "请先在结果表中选择一个 LMO",
        "no_rows": "结果表中还没有 LMO",
        "no_lmo_fch": "尚未生成 LMO 波函数文件，请先运行定域化",
        "lmo_wavefunction_missing": "LMO 波函数文件不存在：{path}",
        "no_canvas": "当前没有可用的画布，无法显示等值面。",
        "no_open_wavefunction_callback": "当前界面未提供打开波函数的回调。",
        "cube_failed_msg": "cube 生成失败：{msg}",
        "csv_empty": "结果表为空，无法导出",
        "csv_failed_msg": "CSV 导出失败：{msg}",
        "open_dir_failed": "无法打开输出目录：{path}",
        "log_run": "[LMO] {method} · {scope} → {fchk}",
        "log_done": "[LMO] 完成：{n} 个 LMO，用时 {secs} s",
        "log_error": "[LMO] 失败：{msg}",
        "log_cancelling": "[LMO] 正在停止…",
        "log_cancelled": "[LMO] 已停止",
        "log_cube_start": "[LMO] 生成 cube：{label}（网格 {grid}，{path}）",
        "log_cube_done": "[LMO] cube 已生成：{path}",
        "log_cube_error": "[LMO] cube 生成失败：{msg}",
        "log_open_wavefunction": "[LMO] 已用 LMO 波函数打开轨道表：{name}",
        "log_csv_saved": "[LMO] CSV 已保存：{path}",
        "log_warning": "[LMO] 警告：{msg}",
    },
    "en": {
        "title": "Orbital localization",
        "intro": (
            "Localize the current wavefunction into localized molecular "
            "orbitals (LMOs) with Multiwfn main function 19; PM-Mulliken "
            "keeps the σ/π separation. Double-click a result row to show the "
            "LMO isosurface on the canvas, then continue with LOBA oxidation "
            "states. "
            "<a href=\"http://sobereva.com/380\">Multiwfn orbital-localization "
            "tutorial</a> · <a href=\"http://sobereva.com/362\">LOBA oxidation-"
            "state tutorial</a>"
        ),
        "source_group": "Source wavefunction",
        "source_none": "Load a .fch / .fchk file in the main window first.",
        "source_ready": "File: {name}\nOutput folder: {dir}",
        "refresh": "Refresh",
        "refresh_tip": "Re-read the wavefunction currently loaded in the main window",
        "settings_group": "Localization settings",
        "method": "Localization method",
        "method_tip": (
            "PM-Mulliken is fast and keeps the σ/π separation (default); "
            "PM-Löwdin is fast too; PM-Becke is robust for diffuse functions "
            "but more expensive; Foster-Boys is robust but gives banana bonds "
            "instead of σ/π."
        ),
        "scope": "Localization scope",
        "scope_occupied": "Occupied orbitals only",
        "scope_all": "Occupied + unoccupied orbitals",
        "calc_energy": "Compute LMO energies",
        "energy_source": "Energy source",
        "energy_mo": "Back-solve from MO energies",
        "energy_file": "Read from file (.47 etc.)",
        "energy_source_tip": (
            "LMO energies are expectation values of the Fock operator; they can "
            "be back-solved from MO energies and coefficients, or read from a "
            "prepared energy file."
        ),
        "fock_file": "Energy data file",
        "fock_placeholder": "Choose an energy file containing the Fock matrix, e.g. .47",
        "browse": "Browse…",
        "fock_filter": "Energy data (*.47 *.47?);;All files (*)",
        "fock_pick_title": "Choose energy data file",
        "composition": "Composition assignment",
        "composition_tip": (
            "Classify each LMO by atomic composition: single-center (one atom "
            "above the single-center threshold), two-center (two atoms together "
            "above the two-center threshold), otherwise more-delocalized. "
            "Hirshfeld is the default."
        ),
        "composition_none": "No assignment",
        "thr_single": "Single-center threshold (%)",
        "thr_two": "Two-center threshold (%)",
        "thr_single_tip": "An LMO is single-center when one atom exceeds this percentage",
        "thr_two_tip": "An LMO is two-center when two atoms together exceed this percentage",
        "advanced": "Advanced",
        "advanced_show": "Show advanced settings",
        "advanced_hide": "Hide advanced settings",
        "core_orb": "Localize core orbitals too",
        "convergence": "Convergence criterion",
        "convergence_tip": "Converged when the largest change between two successive rounds is below this value",
        "max_cycles": "Maximum iterations",
        "centers": "Generate LMO centers and add dipole analysis",
        "centers_tip": (
            "Runs LMOcen to compute LMO centers; the analysis adds Bq atoms to "
            "the input, used by Multiwfn only and not by this application."
        ),
        "dipole": "Also compute LMO dipole moments",
        "centers_note": (
            "Note: the LMO center analysis adds Bq atoms to the input file "
            "(used by Multiwfn only; the structure shown here is unaffected)."
        ),
        "run_group": "Run",
        "run": "Start localization",
        "stop": "Stop",
        "status_no_source": "Load a .fch / .fchk file in the main window first.",
        "status_ready": "Ready: load a wavefunction and click Start localization.",
        "status_working": "Localizing…",
        "status_done": "Localization complete",
        "status_failed": "Localization failed",
        "status_cancelling": "Stopping…",
        "status_cancelled": "Stopped",
        "status_generating": "Generating cube for LMO {label}…",
        "status_cube_done": "Cube generated: {name}",
        "status_cube_failed": "Cube generation failed",
        "result_group": "LMO results",
        "summary_empty": "Results appear here after localization completes.",
        "summary": (
            "{method} · {conv} · {cycles} cycles · {secs} s · "
            "{n} LMOs{warn}\nLMO wavefunction: {lmo}\nLog: {log}"
        ),
        "summary_cen": "LMO centers: {name}",
        "summary_dip": "LMO dipoles: {name}",
        "loba_title": "LOBA oxidation states",
        "loba_intro": (
            "Compute Hirshfeld orbital contributions for the localized "
            "wavefunction, assign electrons by a contribution threshold "
            "(LOBA), or assign every orbital to its largest contributor "
            "(mLOBA). Enter fragment atom indices (for example 1-5,7-11) to "
            "also obtain a fragment oxidation state."
        ),
        "loba_method": "Method",
        "loba_threshold": "Contribution threshold (%)",
        "loba_fragment": "Fragment atoms",
        "loba_fragment_placeholder": "e.g. 1-5,7-11; leave blank for atoms only",
        "loba_fragment_tip": (
            "Use Multiwfn atom indices with commas and ranges. Leave blank to "
            "output atomic oxidation states only."
        ),
        "loba_threshold_tip": (
            "50% is commonly used. Compare 60% and 70% if a result looks "
            "unusual; strong threshold sensitivity suggests LOBA is not reliable "
            "for that system or atom."
        ),
        "loba_method_tip": (
            "LOBA assigns an orbital only when one atom exceeds the threshold; "
            "mLOBA always assigns it to the largest contributor. Both use "
            "Hirshfeld atomic contributions."
        ),
        "loba_hint": (
            "LOBA uses Hirshfeld contributions and does not guarantee that the "
            "oxidation-state sum equals the net charge. It is usually most "
            "informative for transition metals; check stability with another "
            "threshold or mLOBA."
        ),
        "loba_run": "Compute oxidation states",
        "loba_stop": "Stop",
        "loba_status_waiting": "Run orbital localization first to create the LMO wavefunction.",
        "loba_status_ready": "Ready: run LOBA on the localized wavefunction.",
        "loba_status_working": "Computing LOBA oxidation states…",
        "loba_status_done": "LOBA oxidation-state calculation complete",
        "loba_status_failed": "LOBA oxidation-state calculation failed",
        "loba_status_cancelled": "LOBA stopped",
        "loba_result_empty": "Oxidation-state results appear here.",
        "loba_summary": (
            "{method} · Hirshfeld · {threshold} · {secs} s\n"
            "Oxidation-state sum: {sum}   Net charge: {charge}\nLog: {log}"
        ),
        "loba_summary_fragment": "Oxidation state of fragment {fragment}: {state}",
        "loba_sum_error": "Sum and net charge differ; LOBA does not guarantee equality.",
        "loba_col_index": "Atom",
        "loba_col_element": "Element",
        "loba_col_state": "Ox. state",
        "loba_export": "Export oxidation-state CSV",
        "loba_export_tip": "Export atomic oxidation states as a UTF-8 CSV file",
        "loba_no_result": "No LOBA oxidation-state result is available yet",
        "loba_no_lmo_fch": "Cannot find the localized LMO wavefunction; run orbital localization first",
        "loba_invalid_fragment": "Invalid fragment definition: {msg}",
        "loba_failed_title": "LOBA analysis failed",
        "loba_log_start": "[LOBA] {method} · {threshold} · {fragment}",
        "loba_log_done": "[LOBA] Complete: {n} atoms, sum {sum}, {secs} s",
        "loba_log_error": "[LOBA] Failed: {msg}",
        "loba_log_cancelling": "[LOBA] Stopping…",
        "loba_log_cancelled": "[LOBA] Stopped",
        "loba_log_csv_saved": "[LOBA] CSV saved: {path}",
        "conv_yes": "converged",
        "conv_no": "not converged",
        "warn_count": " · {n} warning(s)",
        "col_orbital": "LMO",
        "col_energy_au": "E (a.u.)",
        "col_energy_ev": "E (eV)",
        "col_occ": "Occ.",
        "col_kind": "Type",
        "col_contrib": "Contrib.",
        "col_center": "Center (Å)",
        # 窄栏里用 1c/2c/multi 的紧凑写法（多中心键的常见记号），
        # 完整含义见列 tooltip 的本地化说明
        "kind_single": "1c",
        "kind_two": "2c",
        "kind_more": "multi",
        "kind_unknown": "Unassigned",
        "kind_tip_single": "Single-center LMO (one atom above the single-center threshold)",
        "kind_tip_two": "Two-center LMO (two atoms above the two-center threshold)",
        "kind_tip_more": "LMO delocalized over three or more centers",
        "kind_tip_unknown": "No orbital composition was computed; center count unknown",
        "spin_alpha": "α",
        "spin_beta": "β",
        "spin_both": "A+B",
        "orbital_fmt": "{spin} {index}",
        "dash": "—",
        "visualize": "Visualize selected LMO",
        "visualize_tip": "Show the selected LMO isosurface on the canvas (or double-click a table row)",
        "open_wavefunction": "Open orbital table with LMO wavefunction",
        "open_wavefunction_tip": "Switch the current wavefunction to the exported LMO file to browse it with the orbital table",
        "export_csv": "Export CSV",
        "export_csv_tip": "Export the result table as a UTF-8 CSV file",
        "open_dir": "Open output folder",
        "open_dir_tip": "Open the output folder that contains the LMO results",
        "csv_filter": "CSV (*.csv)",
        "csv_orbital": "Orbital",
        "csv_spin": "Spin",
        "csv_energy_au": "Energy (a.u.)",
        "csv_energy_ev": "Energy (eV)",
        "csv_occ": "Occupancy",
        "csv_kind": "Assignment",
        "csv_contrib": "Main contributions",
        "csv_center_x": "Center X (Ang)",
        "csv_center_y": "Center Y (Ang)",
        "csv_center_z": "Center Z (Ang)",
        "warning": "Notice",
        "failed_title": "Localization failed",
        "need_source": "Load a .fch / .fchk file in the main window first",
        "need_mw": "Configure Multiwfn in the main-window Path Settings first",
        "need_fock": "Energy is read from a file; choose the energy data file first",
        "need_fock_missing": "The specified energy data file does not exist: {path}",
        "need_fock_missing_status": "Energy data file not found",
        "no_selection": "Select an LMO in the result table first",
        "no_rows": "No LMO rows are available yet",
        "no_lmo_fch": "The LMO wavefunction has not been generated; run localization first",
        "lmo_wavefunction_missing": "The LMO wavefunction file does not exist: {path}",
        "no_canvas": "No canvas is available to show the isosurface.",
        "no_open_wavefunction_callback": "No callback is available to open the wavefunction in this window.",
        "cube_failed_msg": "Cube generation failed: {msg}",
        "csv_empty": "The result table is empty; nothing to export",
        "csv_failed_msg": "CSV export failed: {msg}",
        "open_dir_failed": "Cannot open the output folder: {path}",
        "log_run": "[LMO] {method} · {scope} → {fchk}",
        "log_done": "[LMO] Complete: {n} LMOs in {secs} s",
        "log_error": "[LMO] Failed: {msg}",
        "log_cancelling": "[LMO] Stopping…",
        "log_cancelled": "[LMO] Stopped",
        "log_cube_start": "[LMO] Generating cube: {label} (grid {grid}, {path})",
        "log_cube_done": "[LMO] Cube generated: {path}",
        "log_cube_error": "[LMO] Cube generation failed: {msg}",
        "log_open_wavefunction": "[LMO] Opened orbital table with LMO wavefunction: {name}",
        "log_csv_saved": "[LMO] CSV saved: {path}",
        "log_warning": "[LMO] Warning: {msg}",
    },
}

_ORBITAL_ROLE = Qt.UserRole
_SPIN_ROLE = Qt.UserRole + 1


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


class LMOWorker(QThread):
    """在后台运行 ``run_localization``。

    ``finished`` 携带结果字典（含 ``ok``），``failed`` 只在未预期异常时发出。
    ``stop()`` 置位取消事件并尽力终止 Multiwfn 子进程。
    """

    log = pyqtSignal(str)
    stage = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, fchk_path, multiwfn_exe, settings, parent=None):
        super().__init__(parent)
        self._fchk_path = str(fchk_path or "")
        self._multiwfn_exe = str(multiwfn_exe or "")
        self._settings = dict(settings or {})
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
            result = run_localization(
                self._fchk_path,
                self._multiwfn_exe,
                settings=self._settings,
                on_log=self.log.emit,
                on_stage=self.stage.emit,
                cancel_check=self._stop_event.is_set,
                proc_holder=self._proc,
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成界面错误
            self.failed.emit(str(exc))
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid localization result",
                      "energies": [], "character": {}}
        self.finished.emit(result)


class LOBAWorker(QThread):
    """在后台对已定域化波函数运行 LOBA / mLOBA。"""

    log = pyqtSignal(str)
    stage = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, lmo_fch, multiwfn_exe, settings, parent=None):
        super().__init__(parent)
        self._lmo_fch = str(lmo_fch or "")
        self._multiwfn_exe = str(multiwfn_exe or "")
        self._settings = dict(settings or {})
        self._stop_event = threading.Event()
        self._proc = {}

    def is_stopped(self):
        return self._stop_event.is_set()

    def stop(self):
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
            result = run_loba(
                self._lmo_fch,
                self._multiwfn_exe,
                settings=self._settings,
                on_log=self.log.emit,
                on_stage=self.stage.emit,
                cancel_check=self._stop_event.is_set,
                proc_holder=self._proc,
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成界面错误
            self.failed.emit(str(exc))
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid LOBA result",
                      "atoms": [], "warnings": []}
        self.finished.emit(result)


class LMOCubeWorker(QThread):
    """后台为单个 LMO 生成 cube（调用 ``gen_lmo_cube``）。

    ``stop()`` 置位取消事件并终止 Multiwfn 子进程，供关窗清理使用。
    """

    log = pyqtSignal(str)
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, lmo_fch, orbital_index, grid_quality=2,
                 multiwfn_exe=None, work_dir=None, parent=None):
        super().__init__(parent)
        self._lmo_fch = str(lmo_fch or "")
        self._index = int(orbital_index)
        self._grid_quality = int(grid_quality or 2)
        self._multiwfn_exe = str(multiwfn_exe or "")
        self._work_dir = work_dir
        self._stop_event = threading.Event()
        self._proc = {}

    def is_stopped(self):
        return self._stop_event.is_set()

    def stop(self):
        """请求停止：置位取消标志并终止正在运行的 Multiwfn 进程。"""
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
            cube = gen_lmo_cube(
                self._lmo_fch,
                self._index,
                grid_quality=self._grid_quality,
                multiwfn_exe=self._multiwfn_exe or None,
                work_dir=self._work_dir,
                cancel_check=self._stop_event.is_set,
                proc_holder=self._proc,
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成界面错误
            self.error.emit(str(exc))
            return
        if cube:
            self.done.emit(str(cube))
        else:
            self.error.emit("gen_lmo_cube returned no cube path")


class LMOPanel(QWidget):
    """轨道定域化面板（右侧页面，可滚动）。"""

    def __init__(self, glw=None, get_fchk=None, get_multiwfn=None,
                 get_grid_quality=None, on_show_cubes=None,
                 on_open_wavefunction=None, log_func=None, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self._lang = "zh"
        self.glw = glw
        self._get_fchk = get_fchk if callable(get_fchk) else (lambda: "")
        self._get_multiwfn = (
            get_multiwfn if callable(get_multiwfn) else (lambda: ""))
        self._get_grid_quality = (
            get_grid_quality if callable(get_grid_quality) else (lambda: "2"))
        self._on_show_cubes = on_show_cubes if callable(on_show_cubes) else None
        self._on_open_wavefunction = (
            on_open_wavefunction if callable(on_open_wavefunction) else None)
        self._log_func = log_func if callable(log_func) else None

        self._source_path = ""
        self._worker = None
        self._loba_worker = None
        self._cube_worker = None
        self._last_result = None
        self._last_loba_result = None
        self._row_specs_cache = []
        self._running = False
        self._loba_running = False
        self._generating = False
        self._shutting_down = False
        self._gen_label = ""
        self._status_key = "status_no_source"
        self._loba_status_key = "loba_status_waiting"
        self._status_args = {}
        self._advanced_open = False

        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._build_ui()
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

    def _set_loba_status(self, key):
        self._loba_status_key = key
        self._refresh_loba_status()

    def _refresh_loba_status(self):
        try:
            self.lbl_loba_status.setText(self._t(self._loba_status_key))
        except AttributeError:
            pass

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

    def _grid_quality(self):
        try:
            value = int(str(self._get_grid_quality()).strip())
        except Exception:  # noqa: BLE001 - 回调异常按默认网格
            value = 2
        return max(1, min(3, value))

    @staticmethod
    def _method_entry(key):
        entry = LMO_METHODS.get(key)
        return entry if isinstance(entry, dict) else {}

    def _method_name(self, key):
        entry = self._method_entry(key)
        field = "name_zh" if self._lang == "zh" else "name_en"
        return (entry.get(field) or entry.get("name_en")
                or entry.get("name_zh") or str(key or ""))

    @staticmethod
    def _composition_entry(key):
        entry = COMPOSITION_METHODS.get(key)
        return entry if isinstance(entry, dict) else {}

    def _composition_name(self, key):
        entry = self._composition_entry(key)
        field = "name_zh" if self._lang == "zh" else "name_en"
        name = (entry.get(field) or entry.get("name_en")
                or entry.get("name_zh"))
        if name:
            return name
        if str(key) == "none":
            return self._t("composition_none")
        return str(key or "")

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
        self._build_loba_group(root)
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

        self.lbl_method = QLabel()
        self.cmb_method = QComboBox()
        form.addRow(self.lbl_method, self.cmb_method)

        self.lbl_scope = QLabel()
        self.cmb_scope = QComboBox()
        # 核心模块约定的 scope：occupied（仅占据）/ both（占据 + 未占据）
        self.cmb_scope.addItem("", "occupied")
        self.cmb_scope.addItem("", "both")
        form.addRow(self.lbl_scope, self.cmb_scope)

        self.chk_energy = QCheckBox()
        form.addRow(self.chk_energy)

        self.lbl_energy_source = QLabel()
        self.cmb_energy_source = QComboBox()
        self.cmb_energy_source.addItem("", "mo")
        self.cmb_energy_source.addItem("", "file")
        form.addRow(self.lbl_energy_source, self.cmb_energy_source)

        self.lbl_fock_file = QLabel()
        fock_row = QWidget()
        fock_layout = QHBoxLayout(fock_row)
        fock_layout.setContentsMargins(0, 0, 0, 0)
        fock_layout.setSpacing(4)
        self.edit_fock = QLineEdit()
        self.btn_browse_fock = QPushButton()
        self.btn_browse_fock.clicked.connect(self._browse_fock_file)
        fock_layout.addWidget(self.edit_fock, 1)
        fock_layout.addWidget(self.btn_browse_fock, 0)
        form.addRow(self.lbl_fock_file, fock_row)

        self.lbl_composition = QLabel()
        self.cmb_composition = QComboBox()
        form.addRow(self.lbl_composition, self.cmb_composition)

        self.lbl_thr_single = QLabel()
        self.spin_thr_single = QDoubleSpinBox()
        self.spin_thr_single.setRange(50.0, 100.0)
        self.spin_thr_single.setDecimals(1)
        self.spin_thr_single.setSingleStep(1.0)
        self.spin_thr_single.setSuffix(" %")
        self.spin_thr_single.setValue(
            _as_float(DEFAULT_SETTINGS.get("threshold_single"), 0.85) * 100.0)
        form.addRow(self.lbl_thr_single, self.spin_thr_single)

        self.lbl_thr_two = QLabel()
        self.spin_thr_two = QDoubleSpinBox()
        self.spin_thr_two.setRange(50.0, 100.0)
        self.spin_thr_two.setDecimals(1)
        self.spin_thr_two.setSingleStep(1.0)
        self.spin_thr_two.setSuffix(" %")
        self.spin_thr_two.setValue(
            _as_float(DEFAULT_SETTINGS.get("threshold_two"), 0.80) * 100.0)
        form.addRow(self.lbl_thr_two, self.spin_thr_two)

        # 高级设置：折叠区
        self.btn_advanced = QPushButton()
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        form.addRow(self.btn_advanced)

        self.advanced_body = QWidget()
        adv_form = QFormLayout(self.advanced_body)
        adv_form.setContentsMargins(0, 2, 0, 0)
        adv_form.setSpacing(6)
        adv_form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.chk_core = QCheckBox()
        adv_form.addRow(self.chk_core)

        self.lbl_convergence = QLabel()
        self.spin_convergence = QDoubleSpinBox()
        self.spin_convergence.setRange(1e-6, 1e-2)
        self.spin_convergence.setDecimals(6)
        self.spin_convergence.setSingleStep(1e-5)
        self.spin_convergence.setValue(
            _as_float(DEFAULT_SETTINGS.get("convergence"), 1e-4))
        adv_form.addRow(self.lbl_convergence, self.spin_convergence)

        self.lbl_max_cycles = QLabel()
        self.spin_max_cycles = QSpinBox()
        self.spin_max_cycles.setRange(10, 2000)
        self.spin_max_cycles.setSingleStep(10)
        self.spin_max_cycles.setValue(
            _as_int(DEFAULT_SETTINGS.get("max_cycles"), 80))
        adv_form.addRow(self.lbl_max_cycles, self.spin_max_cycles)

        self.chk_centers = QCheckBox()
        self.chk_centers.toggled.connect(self._on_centers_toggled)
        adv_form.addRow(self.chk_centers)

        self.chk_dipole = QCheckBox()
        adv_form.addRow(self.chk_dipole)

        self.lbl_centers_note = QLabel()
        self.lbl_centers_note.setWordWrap(True)
        self.lbl_centers_note.setStyleSheet(
            "font-size:12px;color:#64748B;")
        adv_form.addRow(self.lbl_centers_note)

        self.advanced_body.hide()
        form.addRow(self.advanced_body)

        self._populate_settings_widgets()

        self.chk_energy.setChecked(
            bool(DEFAULT_SETTINGS.get("calc_energy", True)))
        self.chk_energy.toggled.connect(self._refresh_energy_controls)
        self.cmb_energy_source.currentIndexChanged.connect(
            self._refresh_energy_controls)
        self._refresh_energy_controls()
        self.chk_core.setChecked(
            bool(DEFAULT_SETTINGS.get("localize_core", True)))
        self.chk_centers.setChecked(bool(DEFAULT_SETTINGS.get("centers", False)))
        self.chk_dipole.setChecked(bool(DEFAULT_SETTINGS.get("dipole", False)))
        self._on_centers_toggled(self.chk_centers.isChecked())
        root.addWidget(self.grp_settings)

    def _populate_settings_widgets(self):
        """按核心模块的登记表填方法 / 成分下拉框。"""
        method_order = ("pm_mulliken", "pm_lowdin", "pm_becke", "foster_boys")
        for key in method_order:
            if key in LMO_METHODS:
                self.cmb_method.addItem("", key)
        for key in LMO_METHODS:
            if self.cmb_method.findData(key) < 0:
                self.cmb_method.addItem("", key)
        self._set_combo_data(
            self.cmb_method, DEFAULT_SETTINGS.get("method", "pm_mulliken"))

        composition_order = ("none", "mulliken", "hirshfeld", "becke")
        for key in composition_order:
            if key in COMPOSITION_METHODS:
                self.cmb_composition.addItem("", key)
        for key in COMPOSITION_METHODS:
            if self.cmb_composition.findData(key) < 0:
                self.cmb_composition.addItem("", key)
        self._set_combo_data(
            self.cmb_composition, DEFAULT_SETTINGS.get("composition", "hirshfeld"))

        self._set_combo_data(
            self.cmb_scope, DEFAULT_SETTINGS.get("scope", "occupied"))
        self._set_combo_data(
            self.cmb_energy_source,
            DEFAULT_SETTINGS.get("energy_source", "mo"))

    @staticmethod
    def _set_combo_data(combo, data):
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

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

    def _build_result_group(self, root):
        self.grp_result = QGroupBox()
        layout = QVBoxLayout(self.grp_result)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)

        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(
            "padding:6px 8px;background:#F8FAFC;border:1px solid #E2E8F0;"
            "border-radius:6px;color:#334155;")
        layout.addWidget(self.lbl_summary)

        self.table = QTableWidget(0, 7)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(240)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column, width in (
                (0, 54), (1, 100), (2, 88), (3, 66), (4, 96), (6, 100)):
            self.table.setColumnWidth(column, width)
        # 「主要贡献」占剩余宽度；单元格省略的部分可悬停查看完整内容
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

        buttons = QGridLayout()
        buttons.setHorizontalSpacing(6)
        buttons.setVerticalSpacing(6)
        self.btn_visualize = QPushButton()
        self.btn_visualize.setEnabled(False)
        self.btn_visualize.clicked.connect(self._visualize_selected)
        self.btn_open_wavefunction = QPushButton()
        self.btn_open_wavefunction.setEnabled(False)
        self.btn_open_wavefunction.clicked.connect(self._open_lmo_wavefunction)
        self.btn_export_csv = QPushButton()
        self.btn_export_csv.setEnabled(False)
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_open_dir = QPushButton()
        self.btn_open_dir.setEnabled(False)
        self.btn_open_dir.clicked.connect(self._open_output_dir)
        # 两行排布：680 px 宽下四个按钮排一行会溢出
        buttons.addWidget(self.btn_visualize, 0, 0)
        buttons.addWidget(self.btn_open_wavefunction, 0, 1)
        buttons.addWidget(self.btn_export_csv, 1, 0)
        buttons.addWidget(self.btn_open_dir, 1, 1)
        buttons.setColumnStretch(0, 1)
        buttons.setColumnStretch(1, 1)
        layout.addLayout(buttons)

        root.addWidget(self.grp_result, 1)

    def _build_loba_group(self, root):
        self.grp_loba = QGroupBox()
        layout = QVBoxLayout(self.grp_loba)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)

        self.lbl_loba_intro = QLabel()
        self.lbl_loba_intro.setWordWrap(True)
        self.lbl_loba_intro.setStyleSheet("color:#475569;")
        layout.addWidget(self.lbl_loba_intro)

        self.loba_inputs = QWidget()
        form = QFormLayout(self.loba_inputs)
        form.setContentsMargins(0, 2, 0, 2)
        form.setSpacing(6)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.lbl_loba_method = QLabel()
        self.cmb_loba_method = QComboBox()
        for key in ("loba", "mloba"):
            self.cmb_loba_method.addItem("", key)
        self._set_combo_data(
            self.cmb_loba_method,
            LOBA_DEFAULT_SETTINGS.get("method", "loba"))
        self.cmb_loba_method.currentIndexChanged.connect(
            self._refresh_loba_controls)
        form.addRow(self.lbl_loba_method, self.cmb_loba_method)

        self.lbl_loba_threshold = QLabel()
        self.spin_loba_threshold = QDoubleSpinBox()
        self.spin_loba_threshold.setRange(1.0, 100.0)
        self.spin_loba_threshold.setDecimals(1)
        self.spin_loba_threshold.setSingleStep(1.0)
        self.spin_loba_threshold.setSuffix(" %")
        self.spin_loba_threshold.setValue(
            float(LOBA_DEFAULT_SETTINGS.get("threshold", 50.0)))
        form.addRow(self.lbl_loba_threshold, self.spin_loba_threshold)

        self.lbl_loba_fragment = QLabel()
        self.edit_loba_fragment = QLineEdit()
        form.addRow(self.lbl_loba_fragment, self.edit_loba_fragment)
        layout.addWidget(self.loba_inputs)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_loba_run = QPushButton()
        self.btn_loba_run.setMinimumHeight(38)
        self.btn_loba_run.clicked.connect(self._start_loba)
        self.btn_loba_stop = QPushButton()
        self.btn_loba_stop.setEnabled(False)
        self.btn_loba_stop.clicked.connect(self._stop_loba)
        buttons.addWidget(self.btn_loba_run, 1)
        buttons.addWidget(self.btn_loba_stop, 0)
        layout.addLayout(buttons)

        self.loba_progress = QProgressBar()
        self.loba_progress.setRange(0, 100)
        self.loba_progress.setValue(0)
        layout.addWidget(self.loba_progress)

        self.lbl_loba_status = QLabel()
        self.lbl_loba_status.setWordWrap(True)
        layout.addWidget(self.lbl_loba_status)

        self.lbl_loba_hint = QLabel()
        self.lbl_loba_hint.setWordWrap(True)
        self.lbl_loba_hint.setStyleSheet("font-size:12px;color:#64748B;")
        layout.addWidget(self.lbl_loba_hint)

        self.lbl_loba_summary = QLabel()
        self.lbl_loba_summary.setWordWrap(True)
        self.lbl_loba_summary.setStyleSheet(
            "padding:6px 8px;background:#F8FAFC;border:1px solid #E2E8F0;"
            "border-radius:6px;color:#334155;")
        layout.addWidget(self.lbl_loba_summary)

        self.loba_table = QTableWidget(0, 3)
        self.loba_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.loba_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.loba_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.loba_table.setAlternatingRowColors(True)
        self.loba_table.verticalHeader().setVisible(False)
        self.loba_table.setMinimumHeight(150)
        self.loba_table.setWordWrap(False)
        loba_header = self.loba_table.horizontalHeader()
        loba_header.setStretchLastSection(True)
        loba_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        loba_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self.loba_table)

        self.btn_loba_export = QPushButton()
        self.btn_loba_export.setEnabled(False)
        self.btn_loba_export.clicked.connect(self._export_loba_csv)
        layout.addWidget(self.btn_loba_export)

        root.addWidget(self.grp_loba)

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

        # 定域化设置
        self.grp_settings.setTitle(t("settings_group"))
        self.lbl_method.setText(t("method"))
        self.cmb_method.setToolTip(t("method_tip"))
        for index in range(self.cmb_method.count()):
            self.cmb_method.setItemText(
                index, self._method_name(self.cmb_method.itemData(index)))

        self.lbl_scope.setText(t("scope"))
        self.cmb_scope.setItemText(0, t("scope_occupied"))
        self.cmb_scope.setItemText(1, t("scope_all"))

        self.chk_energy.setText(t("calc_energy"))
        self.lbl_energy_source.setText(t("energy_source"))
        self.cmb_energy_source.setToolTip(t("energy_source_tip"))
        self.cmb_energy_source.setItemText(0, t("energy_mo"))
        self.cmb_energy_source.setItemText(1, t("energy_file"))

        self.lbl_fock_file.setText(t("fock_file"))
        self.edit_fock.setPlaceholderText(t("fock_placeholder"))
        self.btn_browse_fock.setText(t("browse"))

        self.lbl_composition.setText(t("composition"))
        self.cmb_composition.setToolTip(t("composition_tip"))
        for index in range(self.cmb_composition.count()):
            self.cmb_composition.setItemText(
                index,
                self._composition_name(self.cmb_composition.itemData(index)))

        self.lbl_thr_single.setText(t("thr_single"))
        self.spin_thr_single.setToolTip(t("thr_single_tip"))
        self.lbl_thr_two.setText(t("thr_two"))
        self.spin_thr_two.setToolTip(t("thr_two_tip"))

        self.btn_advanced.setText(
            t("advanced_hide") if self.btn_advanced.isChecked()
            else t("advanced_show"))
        self.chk_core.setText(t("core_orb"))
        self.lbl_convergence.setText(t("convergence"))
        self.spin_convergence.setToolTip(t("convergence_tip"))
        self.lbl_max_cycles.setText(t("max_cycles"))
        self.chk_centers.setText(t("centers"))
        self.chk_centers.setToolTip(t("centers_tip"))
        self.chk_dipole.setText(t("dipole"))
        self.lbl_centers_note.setText(t("centers_note"))

        # 运行
        self.grp_run.setTitle(t("run_group"))
        self.btn_run.setText(t("run"))
        self.btn_stop.setText(t("stop"))

        # 结果
        self.grp_result.setTitle(t("result_group"))
        self.table.setHorizontalHeaderLabels([
            t("col_orbital"), t("col_energy_au"), t("col_energy_ev"),
            t("col_occ"), t("col_kind"), t("col_contrib"), t("col_center")])
        self._fit_table_columns()
        self.btn_visualize.setText(t("visualize"))
        self.btn_visualize.setToolTip(t("visualize_tip"))
        self.btn_open_wavefunction.setText(t("open_wavefunction"))
        self.btn_open_wavefunction.setToolTip(t("open_wavefunction_tip"))
        self.btn_export_csv.setText(t("export_csv"))
        self.btn_export_csv.setToolTip(t("export_csv_tip"))
        self.btn_open_dir.setText(t("open_dir"))
        self.btn_open_dir.setToolTip(t("open_dir_tip"))

        # LOBA / mLOBA
        self.grp_loba.setTitle(t("loba_title"))
        self.lbl_loba_intro.setText(t("loba_intro"))
        self.lbl_loba_method.setText(t("loba_method"))
        self.cmb_loba_method.setToolTip(t("loba_method_tip"))
        for index in range(self.cmb_loba_method.count()):
            key = self.cmb_loba_method.itemData(index)
            entry = LOBA_METHODS.get(key) or {}
            self.cmb_loba_method.setItemText(
                index,
                entry.get("name_zh" if self._lang == "zh" else "name_en")
                or str(key))
        self.lbl_loba_threshold.setText(t("loba_threshold"))
        self.spin_loba_threshold.setToolTip(t("loba_threshold_tip"))
        self.lbl_loba_fragment.setText(t("loba_fragment"))
        self.edit_loba_fragment.setPlaceholderText(
            t("loba_fragment_placeholder"))
        self.edit_loba_fragment.setToolTip(t("loba_fragment_tip"))
        self.btn_loba_run.setText(t("loba_run"))
        self.btn_loba_stop.setText(t("loba_stop"))
        self.lbl_loba_hint.setText(t("loba_hint"))
        self.loba_table.setHorizontalHeaderLabels([
            t("loba_col_index"), t("loba_col_element"),
            t("loba_col_state")])
        self.btn_loba_export.setText(t("loba_export"))
        self.btn_loba_export.setToolTip(t("loba_export_tip"))

        # 语言切换后重新套用动态内容（状态、来源、摘要、已填表格行）
        self._refresh_status()
        self._refresh_loba_status()
        self._refresh_source()
        self._refresh_energy_controls()
        self._refresh_loba_controls()
        self._refresh_summary()
        self._refresh_loba_summary()
        self._refresh_loba_table()
        if self._last_result is not None:
            self._refresh_table()
        self._update_actions()

    # ── 状态 / 输入来源 ─────────────────────────────────────────────────
    def set_source_from_main(self, path=None):
        """读取（或接收）主界面当前波函数路径并刷新显示。"""
        previous_loba_input = self._loba_input_path()
        if path is None:
            path = self._current_fchk()
        try:
            path = str(path or "").strip()
        except Exception:  # noqa: BLE001 - 异常输入按空处理
            path = ""
        self._source_path = path
        if (previous_loba_input
                and self._loba_input_path() != previous_loba_input):
            self._last_loba_result = None
            self.loba_progress.setRange(0, 100)
            self.loba_progress.setValue(0)
            self._refresh_loba_table()
            self._refresh_loba_summary()
        self._refresh_source()
        if not self._running and not self._loba_running:
            self._refresh_loba_status_from_result()
            self._update_actions()

    def showEvent(self, event):
        # 切换回本页时跟随主窗口当前 fchk（载入新文件后不必手动点刷新）
        super().showEvent(event)
        self.set_source_from_main()

    def _refresh_source(self):
        if not self._source_path:
            self.lbl_source.setText(self._t("source_none"))
            if not self._running and self._last_result is None:
                self._set_status("status_no_source")
            return
        folder = os.path.dirname(self._source_path) or "."
        self.lbl_source.setText(self._t("source_ready").format(
            name=os.path.basename(self._source_path), dir=folder))
        if not self._running and self._last_result is None:
            self._set_status("status_ready")

    # ── 设置读写 ────────────────────────────────────────────────────────
    def _settings(self):
        settings = dict(DEFAULT_SETTINGS)
        settings.update({
            "method": self.cmb_method.currentData() or "pm_mulliken",
            "scope": (self.cmb_scope.currentData()
                      if self.cmb_scope.currentData() in ("occupied", "both")
                      else "occupied"),
            "calc_energy": self.chk_energy.isChecked(),
            "energy_source": self.cmb_energy_source.currentData() or "mo",
            "fock_file": self.edit_fock.text().strip(),
            "composition": self.cmb_composition.currentData() or "hirshfeld",
            "threshold_single": self.spin_thr_single.value() / 100.0,
            "threshold_two": self.spin_thr_two.value() / 100.0,
            "localize_core": self.chk_core.isChecked(),
            "convergence": self.spin_convergence.value(),
            "max_cycles": self.spin_max_cycles.value(),
            "centers": self.chk_centers.isChecked(),
            "dipole": (self.chk_centers.isChecked()
                       and self.chk_dipole.isChecked()),
        })
        return settings

    def _refresh_energy_controls(self, *_args):
        enabled = self.chk_energy.isChecked()
        self.lbl_energy_source.setEnabled(enabled)
        self.cmb_energy_source.setEnabled(enabled)
        file_mode = enabled and self.cmb_energy_source.currentData() == "file"
        for widget in (self.lbl_fock_file, self.edit_fock, self.btn_browse_fock):
            widget.setEnabled(file_mode)

    def _refresh_loba_controls(self, *_args):
        loba_mode = self.cmb_loba_method.currentData() == "loba"
        self.lbl_loba_threshold.setEnabled(loba_mode)
        self.spin_loba_threshold.setEnabled(loba_mode)
        self.spin_loba_threshold.setToolTip(
            self._t("loba_threshold_tip") if loba_mode else "")

    def _loba_settings(self):
        method = self.cmb_loba_method.currentData()
        if method not in LOBA_METHODS:
            method = "loba"
        return {
            "method": method,
            "threshold": float(self.spin_loba_threshold.value()),
            "fragment": self.edit_loba_fragment.text().strip(),
        }

    def _toggle_advanced(self, checked):
        self._advanced_open = bool(checked)
        self.advanced_body.setVisible(self._advanced_open)
        self.btn_advanced.setText(
            self._t("advanced_hide") if self._advanced_open
            else self._t("advanced_show"))

    def _on_centers_toggled(self, checked):
        self.chk_dipole.setVisible(bool(checked))
        self.chk_dipole.setEnabled(bool(checked))
        if not checked:
            self.chk_dipole.setChecked(False)

    def _browse_fock_file(self):
        start = self.edit_fock.text().strip()
        if not start and self._source_path:
            start = os.path.dirname(self._source_path)
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("fock_pick_title"), start, self._t("fock_filter"))
        if path:
            self.edit_fock.setText(path)

    # ── 运行 / 停止 ─────────────────────────────────────────────────────
    def _start(self):
        if self._running or self._generating or self._loba_running:
            return
        fchk = self._current_fchk()
        if not fchk or not os.path.isfile(fchk):
            QMessageBox.warning(self, self._t("warning"), self._t("need_source"))
            return
        multiwfn = self._current_multiwfn()
        if not multiwfn or not os.path.isfile(multiwfn):
            QMessageBox.warning(self, self._t("warning"), self._t("need_mw"))
            return
        settings = self._settings()
        if settings["calc_energy"] and settings["energy_source"] == "file":
            fock_file = settings.get("fock_file") or ""
            if not fock_file:
                QMessageBox.warning(
                    self, self._t("warning"), self._t("need_fock"))
                return
            if not os.path.isfile(fock_file):
                QMessageBox.warning(
                    self, self._t("warning"),
                    self._t("need_fock_missing").format(path=fock_file))
                return

        self._worker = LMOWorker(fchk, multiwfn, settings, self)
        self._worker.log.connect(self._on_log)
        self._worker.stage.connect(self._on_stage)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._log(self._t("log_run").format(
            method=self._method_name(settings.get("method")),
            scope=self.cmb_scope.currentText(),
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

    def _start_loba(self):
        if self._running or self._generating or self._loba_running:
            return
        lmo_fch = self._loba_input_path()
        if not lmo_fch or not os.path.isfile(lmo_fch):
            QMessageBox.warning(
                self, self._t("warning"), self._t("loba_no_lmo_fch"))
            return
        multiwfn = self._current_multiwfn()
        if not multiwfn or not os.path.isfile(multiwfn):
            QMessageBox.warning(self, self._t("warning"), self._t("need_mw"))
            return
        settings = self._loba_settings()
        try:
            settings["fragment"] = parse_fragment_spec(
                settings.get("fragment"))
        except ValueError as exc:
            QMessageBox.warning(
                self, self._t("warning"),
                self._t("loba_invalid_fragment").format(msg=exc))
            return

        self._last_loba_result = None
        self._refresh_loba_table()
        self._refresh_loba_summary()
        self._loba_worker = LOBAWorker(lmo_fch, multiwfn, settings, self)
        self._loba_worker.log.connect(self._on_log)
        self._loba_worker.stage.connect(self._on_loba_stage)
        self._loba_worker.finished.connect(self._on_loba_finished)
        self._loba_worker.failed.connect(self._on_loba_failed)

        method = self.cmb_loba_method.currentText()
        threshold = ("mLOBA" if settings["method"] == "mloba"
                     else "%.1f%%" % settings["threshold"])
        fragment = settings.get("fragment") or self._t("dash")
        self._log(self._t("loba_log_start").format(
            method=method, threshold=threshold, fragment=fragment))
        self.loba_progress.setRange(0, 0)
        self.loba_progress.setValue(0)
        self._set_loba_status("loba_status_working")
        self._set_loba_running(True)
        self._loba_worker.start()

    def _stop_loba(self):
        if (self._loba_worker is None
                or not self._loba_worker.isRunning()):
            return
        self._loba_worker.stop()
        self._set_loba_status("loba_status_cancelled")
        self._log(self._t("loba_log_cancelling"))

    def _set_loba_running(self, running):
        self._loba_running = bool(running)
        self.loba_inputs.setEnabled(not self._loba_running)
        self.btn_loba_run.setEnabled(not self._loba_running)
        self.btn_loba_stop.setEnabled(self._loba_running)
        for widget in (self.grp_source, self.grp_settings, self.btn_run):
            widget.setEnabled(not self._loba_running and not self._running)
        self._update_actions()

    def _on_loba_stage(self, percent, _text):
        try:
            value = int(percent)
        except (TypeError, ValueError):
            value = 0
        if self.loba_progress.maximum() == 0:
            self.loba_progress.setRange(0, 100)
        self.loba_progress.setValue(max(0, min(100, value)))

    def _on_loba_finished(self, result):
        if self._shutting_down:
            self._loba_worker = None
            self._loba_running = False
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid LOBA result",
                      "atoms": [], "warnings": []}
        cancelled = (self._loba_worker is not None
                     and self._loba_worker.is_stopped())
        if result.get("ok") and not cancelled:
            self._apply_loba_result(result)
        self.loba_progress.setRange(0, 100)
        if result.get("ok") and not cancelled:
            self.loba_progress.setValue(100)
            self._set_loba_status("loba_status_done")
            seconds = _as_float(result.get("seconds"))
            seconds_text = ("%.1f" % seconds) if seconds is not None else "—"
            total = _as_float(result.get("sum"))
            total_text = ("%.6g" % total) if total is not None else "—"
            self._log(self._t("loba_log_done").format(
                n=len(result.get("atoms") or []),
                sum=total_text,
                secs=seconds_text))
            try:
                self.scroll_area.ensureWidgetVisible(self.grp_loba, 0, 0)
            except Exception:  # noqa: BLE001 - 滚动失败不影响结果
                pass
        elif cancelled:
            self.loba_progress.setValue(0)
            self._set_loba_status("loba_status_cancelled")
            self._log(self._t("loba_log_cancelled"))
        else:
            self.loba_progress.setValue(0)
            error = str(result.get("error") or self._t("loba_status_failed"))
            self._set_loba_status("loba_status_failed")
            self._log(self._t("loba_log_error").format(msg=error))
            QMessageBox.warning(self, self._t("loba_failed_title"), error)
        self._finish_loba_worker()

    def _on_loba_failed(self, message):
        if self._shutting_down:
            self._loba_worker = None
            self._loba_running = False
            return
        self.loba_progress.setRange(0, 100)
        self.loba_progress.setValue(0)
        if self._loba_worker is not None and self._loba_worker.is_stopped():
            self._set_loba_status("loba_status_cancelled")
            self._log(self._t("loba_log_cancelled"))
            self._finish_loba_worker()
            return
        self._set_loba_status("loba_status_failed")
        self._log(self._t("loba_log_error").format(msg=message))
        QMessageBox.warning(
            self, self._t("loba_failed_title"),
            str(message or self._t("loba_status_failed")))
        self._finish_loba_worker()

    def _finish_loba_worker(self):
        worker = self._loba_worker
        self._loba_worker = None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(3000)
            except Exception:  # noqa: BLE001 - 清理失败不影响界面
                pass
        self._set_loba_running(False)
        if self._last_loba_result is None:
            self._set_loba_status(
                "loba_status_ready" if self._loba_input_path() else
                "loba_status_waiting")

    def _set_running(self, running):
        self._running = bool(running)
        for widget in (self.grp_source, self.grp_settings, self.btn_run):
            widget.setEnabled(not self._running and not self._loba_running)
        self.btn_stop.setEnabled(self._running)
        if self._running:
            self.btn_loba_run.setEnabled(False)
        else:
            self._refresh_loba_status_from_result()
        self._update_actions()

    def _on_stage(self, percent, _text):
        try:
            value = int(percent)
        except (TypeError, ValueError):
            value = 0
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, value)))

    def _on_worker_finished(self, result):
        if self._shutting_down:
            # 关窗阶段：不弹窗、不刷界面，安静收尾即可
            self._worker = None
            self._running = False
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid localization result",
                      "energies": [], "character": {}}
        cancelled = self._worker is not None and self._worker.is_stopped()
        self._apply_result(result)
        # 设置区很长，结果表在页面底部：跑完自动滚到结果区，避免用户以为
        # 没有反应（尤其是第一次使用时）。
        try:
            self.scroll_area.ensureWidgetVisible(self.grp_result, 0, 0)
        except Exception:  # noqa: BLE001 - 滚动失败不影响结果
            pass
        self.progress.setRange(0, 100)
        if result.get("ok") and not cancelled:
            self.progress.setValue(100)
            self._set_status("status_done")
            count = self._lmo_count(result)
            seconds = _as_float(result.get("seconds"))
            self._log(self._t("log_done").format(
                n=count,
                secs=("%.1f" % seconds) if seconds is not None
                else self._t("dash")))
            for warning in result.get("warnings") or []:
                self._log(self._t("log_warning").format(msg=warning))
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
        self._finish_localization_worker()

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
            self._finish_localization_worker()
            return
        self._set_status("status_failed")
        self._log(self._t("log_error").format(msg=message))
        QMessageBox.warning(
            self, self._t("failed_title"), str(message or self._t("status_failed")))
        self._finish_localization_worker()

    def _finish_localization_worker(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(3000)
            except Exception:  # noqa: BLE001 - 清理失败不影响界面
                pass
        self._set_running(False)

    # ── 结果表 ──────────────────────────────────────────────────────────
    def _apply_result(self, result):
        """把核心模块的结果字典套用到摘要与结果表（探针脚本也直接调用它）。"""
        if not isinstance(result, dict):
            return
        previous_loba_input = self._loba_input_path()
        self._last_result = result
        current_loba_input = self._loba_input_path()
        if (previous_loba_input
                and current_loba_input != previous_loba_input):
            self._last_loba_result = None
            self.loba_progress.setRange(0, 100)
            self.loba_progress.setValue(0)
            self._refresh_loba_table()
            self._refresh_loba_summary()
        self._refresh_summary()
        self._refresh_table()
        self._refresh_loba_status_from_result()
        self._update_actions()

    def _lmo_fch_path(self):
        result = self._last_result
        if not isinstance(result, dict):
            return ""
        return str(result.get("lmo_fch") or "").strip()

    def _loba_input_path(self):
        """优先使用本次定域化产物；也接受主界面已载入的 ``*_LMO.fch``。"""
        path = self._lmo_fch_path()
        if path and os.path.isfile(path):
            return path
        source = str(self._source_path or "").strip()
        if (source and os.path.isfile(source)
                and re.match(r"(?i)^.+_LMO\.fchk?$", os.path.basename(source))):
            return source
        return ""

    def _refresh_loba_status_from_result(self):
        if self._loba_running:
            return
        path = self._loba_input_path()
        if path:
            self._set_loba_status("loba_status_ready")
        else:
            self._set_loba_status("loba_status_waiting")

    def _lmo_count(self, result=None):
        """表格实际行数 = 能量行 ∪ 只有指认的行（摘要/日志统一用这个数）。

        回归：开壳层 occupied+unoccupied 一起定域化时 Multiwfn 只给部分 LMO
        的能量行（如 138 条），但指认覆盖全部 150 个 LMO；旧摘要按能量行数
        报“138 个 LMO”，与表格 150 行不一致。
        """
        if not isinstance(result, dict):
            result = self._last_result or {}
        try:
            return len(self._row_specs(result))
        except Exception:  # noqa: BLE001 - 统计失败退回旧口径
            return (len(result.get("energies") or [])
                    or len(result.get("character") or {}))

    def _refresh_summary(self):
        result = self._last_result
        if not isinstance(result, dict) or not result:
            self.lbl_summary.setText(self._t("summary_empty"))
            return
        settings = result.get("settings")
        settings = settings if isinstance(settings, dict) else {}
        method = self._method_name(
            settings.get("method") or DEFAULT_SETTINGS.get("method"))
        converged = bool(result.get("converged"))
        sections = result.get("sections") or []
        cycles = 0
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict):
                    cycles += _as_int(section.get("cycles"), 0) or 0
        cycles_text = str(cycles) if cycles > 0 else self._t("dash")
        seconds = _as_float(result.get("seconds"))
        secs_text = ("%.1f" % seconds) if seconds is not None else self._t("dash")
        count = self._lmo_count(result)
        warnings = result.get("warnings") or []
        warn_text = (self._t("warn_count").format(n=len(warnings))
                     if isinstance(warnings, list) and warnings else "")
        lmo_name = os.path.basename(str(result.get("lmo_fch") or ""))
        log_name = os.path.basename(str(result.get("log_path") or ""))
        summary = self._t("summary").format(
            method=method,
            conv=self._t("conv_yes") if converged else self._t("conv_no"),
            cycles=cycles_text,
            secs=secs_text,
            n=count,
            warn=warn_text,
            lmo=lmo_name or self._t("dash"),
            log=log_name or self._t("dash"))
        cen_name = os.path.basename(str(result.get("cen_txt") or ""))
        if cen_name:
            summary += "\n" + self._t("summary_cen").format(name=cen_name)
        dip_name = os.path.basename(str(result.get("dip_txt") or ""))
        if dip_name:
            summary += "\n" + self._t("summary_dip").format(name=dip_name)
        self.lbl_summary.setText(summary)

    def _refresh_table(self):
        rows = self._row_specs(self._last_result or {})
        self._row_specs_cache = rows
        self.table.setRowCount(0)
        if not rows:
            return
        self.table.setRowCount(len(rows))
        for row_index, spec in enumerate(rows):
            cells = (
                spec["orbital"],
                self._fmt_number(spec["energy_au"], 6),
                self._fmt_number(spec["energy_ev"], 2),
                self._fmt_number(spec["occ"], 1),
                spec["kind"],
                spec["contrib"],
                self._center_text(spec["center"]),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if column in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if column in (4, 5, 6) and str(text) not in (
                        "", self._t("dash")):
                    item.setToolTip(str(text))
                self.table.setItem(row_index, column, item)
            # 中心列显示 1 位小数（省横向空间），悬停时给完整 3 位小数
            if spec.get("center"):
                center_item = self.table.item(row_index, 6)
                if center_item is not None:
                    center_item.setToolTip(
                        self._center_text(spec["center"], decimals=3))
            # 窄栏里「指认」用 1c/2c/multi，悬停给完整的本地化说明
            kind_item = self.table.item(row_index, 4)
            if kind_item is not None:
                kind_item.setToolTip(self._t(
                    {"single": "kind_tip_single", "two": "kind_tip_two",
                     "more": "kind_tip_more"}.get(
                         spec.get("kind_raw"), "kind_tip_unknown")))
            index_item = self.table.item(row_index, 0)
            index_item.setData(_ORBITAL_ROLE, spec["global"])
            index_item.setData(_SPIN_ROLE, spec["spin"] or "")

    def _fit_table_columns(self):
        """按当前字体度量（随 DPI 缩放）设置列宽，避免数值被省略号截断。

        固定像素列宽在 150% 缩放的 Windows 上会把 ``-267.96``、``2.0`` 之类
        的数值截成 ``-267…``，因此这里用 ``fontMetrics`` 现算：每列取
        「表头宽 / 典型值宽」的较大者再加一点内边距。「主要贡献」仍占剩余宽度。
        """
        try:
            metrics = self.table.fontMetrics()
            pad = max(14, int(metrics.height() * 0.8))
            header = self.table.horizontalHeader()
            samples = (
                "β 76", "-9.847475", "-267.96", "2.0",
                self._t("kind_more"), "", "-1.2, -0.4, -1.7")
            for column, sample in enumerate(samples):
                if column == 5:
                    # 主要贡献列保持 Stretch，只给一个最小可读宽度
                    self.table.setColumnWidth(column, max(110,
                                                          metrics.horizontalAdvance(
                                                              self.table
                                                              .horizontalHeaderItem(5)
                                                              .text()) + pad))
                    continue
                head_item = self.table.horizontalHeaderItem(column)
                head_text = head_item.text() if head_item is not None else ""
                width = max(metrics.horizontalAdvance(head_text),
                            metrics.horizontalAdvance(sample)) + pad
                self.table.setColumnWidth(column, max(44, width))
        except Exception:  # noqa: BLE001 - 列宽算不出来就用默认值
            pass

    def _fmt_number(self, value, decimals):
        number = _as_float(value)
        if number is None:
            return self._t("dash")
        return ("%." + str(decimals) + "f") % number

    def _row_specs(self, result):
        """把结果字典整理成按全局轨道序号排序的表格行。"""
        if not isinstance(result, dict) or not result:
            return []
        energies = result.get("energies") or []
        character = result.get("character") or {}
        centers = self._center_map(result)
        n_alpha_total = _as_int(result.get("n_alpha_total"), 0) or 0
        n_beta = _as_int(result.get("n_beta_occupied"), 0) or 0

        open_shell = n_beta > 0
        if isinstance(energies, list):
            for entry in energies:
                if (isinstance(entry, dict)
                        and self._spin_kind(entry.get("spin")) == "beta"):
                    open_shell = True
                    break

        char_map = {}
        if isinstance(character, dict):
            for raw_index, entry in character.items():
                index = _as_int(raw_index)
                if index is None:
                    continue
                if not isinstance(entry, dict):
                    entry = {"kind": entry}
                # 核心模块已把 β 的 character 键换算成全局序号，无需再偏移
                char_map[index] = entry

        rows = []
        seen = set()
        if isinstance(energies, list) and energies:
            for entry in energies:
                if not isinstance(entry, dict):
                    continue
                index = _as_int(entry.get("index"))
                if index is None:
                    continue
                spin = self._spin_kind(entry.get("spin"))
                global_index = self._to_global(
                    index, spin, n_alpha_total, n_beta)
                if global_index in seen:
                    continue
                seen.add(global_index)
                rows.append(self._make_row(
                    global_index, spin, entry,
                    char_map.get(global_index),
                    centers.get(global_index), open_shell))
        # 只出现在 character 里、没有对应能量行的 LMO 也要显示（能量列给“—”）。
        # 例：开壳层 occupied+unoccupied 一起定域化时，Multiwfn 只给 α 与
        # β 空轨道的能量行，β 占据 LMO（76..87）只有指认没有能量。
        for global_index in sorted(char_map):
            if global_index in seen:
                continue
            seen.add(global_index)
            entry = char_map.get(global_index) or {}
            spin = self._spin_kind(entry.get("spin"))
            rows.append(self._make_row(
                global_index, spin, {}, entry,
                centers.get(global_index), open_shell))

        rows.sort(key=lambda row: row["global"])
        return rows

    @staticmethod
    def _spin_kind(value):
        """把核心模块的 A / B / A+B / alpha / beta 统一成 alpha / beta / ""。"""
        text = str(value or "").strip().lower()
        if text in ("b", "beta", "β"):
            return "beta"
        if text in ("a", "alpha", "α"):
            return "alpha"
        return ""

    @staticmethod
    def _to_global(index, spin, n_alpha_total, n_beta):
        """把开壳层 β 的“每自旋序号”换算成全局序号（已是全局则原样返回）。"""
        if spin == "beta" and 0 < index <= (n_beta or 0):
            return (n_alpha_total or 0) + index
        return index

    def _make_row(self, global_index, spin, energy_entry,
                  character_entry, center, open_shell):
        spin = self._spin_kind(spin)
        if open_shell:
            # 开壳层：按自旋标注（β 用全局编号）；闭壳层没有自旋区分。
            spin = spin or "alpha"
            spin_text = (self._t("spin_beta") if spin == "beta"
                         else self._t("spin_alpha"))
            orbital = self._t("orbital_fmt").format(
                spin=spin_text, index=global_index)
        else:
            spin = ""
            spin_text = self._t("spin_both")
            orbital = str(global_index)
        entry = character_entry if isinstance(character_entry, dict) else {}
        kind = self._kind_text(entry.get("kind")) if entry else self._t(
            "kind_unknown")
        return {
            "global": int(global_index),
            "spin": spin,
            "spin_text": spin_text,
            "orbital": orbital,
            "energy_au": energy_entry.get("energy_au"),
            "energy_ev": energy_entry.get("energy_ev"),
            "occ": energy_entry.get("occ"),
            "kind": kind,
            "kind_raw": str(entry.get("kind") or "").strip().lower(),
            "contrib": self._contribution_text(entry),
            "center": center,
        }

    def _kind_text(self, kind):
        key = {
            "single": "kind_single",
            "two": "kind_two",
            "more": "kind_more",
        }.get(str(kind or "").strip().lower(), "kind_unknown")
        return self._t(key)

    def _contribution_text(self, character_entry):
        if not isinstance(character_entry, dict):
            return self._t("dash")
        atoms = character_entry.get("atoms") or []
        parts = []
        if isinstance(atoms, list):
            for atom in atoms[:3]:
                if not isinstance(atom, dict):
                    continue
                element = str(
                    atom.get("element") or atom.get("symbol") or "").strip()
                index = atom.get("index")
                percent = _as_float(atom.get("percent"))
                if percent is None:
                    continue
                parts.append("%s%s %.1f%%" % (element, index, percent))
        return " · ".join(parts) if parts else self._t("dash")

    def _center_map(self, result):
        """把 ``result["lmo_centers"]`` / ``cen_txt`` 整理成全局序号→Å 坐标。"""
        data = None
        if isinstance(result, dict):
            data = result.get("lmo_centers")
        if not isinstance(data, dict):
            data = result.get("centers") if isinstance(result, dict) else None
        if not isinstance(data, dict) or not data:
            data = {}
            text = result.get("cen_txt") if isinstance(result, dict) else None
            if isinstance(text, str) and text:
                if os.path.isfile(text):
                    try:
                        with open(text, "r", encoding="utf-8",
                                  errors="replace") as handle:
                            text = handle.read()
                    except OSError:
                        text = ""
                if text:
                    try:
                        data = parse_lmocen(text)
                    except Exception:  # noqa: BLE001 - 解析失败则无中心列
                        data = {}
        if not isinstance(data, dict) or not data:
            return {}
        n_alpha_total = _as_int(result.get("n_alpha_total"), 0) or 0
        n_beta = _as_int(result.get("n_beta_occupied"), 0) or 0
        mapping = {}
        closed = data.get("closed")
        if isinstance(closed, dict):
            for raw_index, value in closed.items():
                index = _as_int(raw_index)
                coordinates = self._coords(value)
                if index is not None and coordinates is not None:
                    mapping[index] = coordinates
        has_spin_blocks = (isinstance(data.get("alpha"), dict)
                           or isinstance(data.get("beta"), dict))
        if has_spin_blocks:
            for spin in ("alpha", "beta"):
                entries = data.get(spin)
                if not isinstance(entries, dict):
                    continue
                for raw_index, value in entries.items():
                    index = _as_int(raw_index)
                    if index is None:
                        continue
                    coordinates = self._coords(value)
                    if coordinates is None:
                        continue
                    # parse_lmocen() 的 alpha/beta 是**每自旋**编号（互不偏移），
                    # beta 必须整体加 n_alpha_total 换成全局序号。不能只在
                    # index <= n_beta_occupied 时才偏移：occuped+unoccupied 一起
                    # 定域化时 beta 的 LMOcen 键可以到 1..n_beta_total，否则
                    # β13..β75 会和 α13..α75 撞车。
                    if spin == "beta":
                        mapping[index + (n_alpha_total or 0)] = coordinates
                    else:
                        mapping[index] = coordinates
        elif not mapping:
            # 兼容平铺的 {序号: 坐标} 结构（非契约，仅防御）
            for raw_index, value in data.items():
                index = _as_int(raw_index)
                if index is None:
                    continue
                coordinates = self._coords(value)
                if coordinates is not None:
                    mapping[index] = coordinates
        return mapping

    @staticmethod
    def _coords(value):
        """兼容 tuple/list / dict / 字符串三种坐标表示，返回 Å 坐标 (x, y, z)。"""
        if isinstance(value, dict):
            if "xyz_ang" in value:
                return LMOPanel._coords(value.get("xyz_ang"))
            if "xyz_bohr" in value:
                coordinates = LMOPanel._coords(value.get("xyz_bohr"))
                if coordinates is not None:
                    return tuple(coord * BOHR_TO_ANG for coord in coordinates)
            for key in ("center", "xyz", "coords", "ang"):
                if key in value:
                    return LMOPanel._coords(value.get(key))
            coordinates = (
                _as_float(value.get("x")), _as_float(value.get("y")),
                _as_float(value.get("z")))
            if all(item is not None for item in coordinates):
                return coordinates
            return None
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            coordinates = tuple(_as_float(item) for item in value[:3])
            if all(item is not None for item in coordinates):
                return coordinates
            return None
        if isinstance(value, str):
            parts = re.split(r"[,\s]+", value.strip())
            if len(parts) >= 3:
                coordinates = tuple(_as_float(item) for item in parts[:3])
                if all(item is not None for item in coordinates):
                    return coordinates
        return None

    def _center_text(self, center, decimals=1):
        if not center:
            return self._t("dash")
        try:
            return ("%." + str(int(decimals)) + "f, "
                    + "%." + str(int(decimals)) + "f, "
                    + "%." + str(int(decimals)) + "f") % tuple(center)[:3]
        except (TypeError, ValueError):
            return self._t("dash")

    # ── LOBA 结果 ───────────────────────────────────────────────────────
    def _apply_loba_result(self, result):
        """套用 LOBA 结果字典（探针测试也直接调用）。"""
        if not isinstance(result, dict):
            return
        self._last_loba_result = result
        self._refresh_loba_table()
        self._refresh_loba_summary()
        self._update_actions()

    def _refresh_loba_table(self):
        result = self._last_loba_result
        atoms = result.get("atoms") if isinstance(result, dict) else []
        atoms = atoms if isinstance(atoms, list) else []
        self.loba_table.setRowCount(0)
        if not atoms:
            return
        atoms = sorted(
            [atom for atom in atoms if isinstance(atom, dict)],
            key=lambda atom: (_as_int(atom.get("index"), 10 ** 9)
                              or 10 ** 9))
        self.loba_table.setRowCount(len(atoms))
        for row, atom in enumerate(atoms):
            index = _as_int(atom.get("index"))
            state = _as_float(atom.get("oxidation_state"))
            state_text = self._t("dash")
            if state is not None:
                if abs(state - round(state)) < 1e-8:
                    state_text = "%+d" % int(round(state))
                else:
                    state_text = "%+.4g" % state
            values = (
                self._t("dash") if index is None else str(index),
                str(atom.get("element") or self._t("dash")),
                state_text,
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column in (0, 2):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.loba_table.setItem(row, column, item)

    def _refresh_loba_summary(self):
        result = self._last_loba_result
        if not isinstance(result, dict) or not result:
            self.lbl_loba_summary.setText(self._t("loba_result_empty"))
            return
        settings = result.get("settings")
        settings = settings if isinstance(settings, dict) else {}
        method_key = str(settings.get("method") or "loba")
        method_entry = LOBA_METHODS.get(method_key) or {}
        method = str(method_entry.get(
            "name_zh" if self._lang == "zh" else "name_en") or method_key)
        if method_key == "mloba":
            threshold = self._t("dash")
        else:
            threshold_value = _as_float(settings.get("threshold"), 50.0)
            threshold = "%.1f%%" % threshold_value
        seconds = _as_float(result.get("seconds"))
        secs_text = ("%.1f" % seconds) if seconds is not None else self._t(
            "dash")
        total = _as_float(result.get("sum"))
        total_text = ("%.6g" % total) if total is not None else self._t("dash")
        charge = _as_float(result.get("net_charge"))
        charge_text = ("%g" % charge) if charge is not None else self._t("dash")
        log_name = os.path.basename(str(result.get("log_path") or ""))
        summary = self._t("loba_summary").format(
            method=method,
            threshold=threshold,
            secs=secs_text,
            sum=total_text,
            charge=charge_text,
            log=log_name or self._t("dash"))
        fragment = str(settings.get("fragment") or "")
        fragment_state = _as_float(result.get("fragment_oxidation_state"))
        if fragment:
            state_text = (("%+.6g" % fragment_state)
                          if fragment_state is not None else self._t("dash"))
            summary += "\n" + self._t("loba_summary_fragment").format(
                fragment=fragment, state=state_text)
        difference = _as_float(result.get("sum_difference"))
        if difference is not None and abs(difference) > 1e-6:
            summary += "\n" + self._t("loba_sum_error")
        self.lbl_loba_summary.setText(summary)

    def _export_loba_csv(self):
        result = self._last_loba_result
        atoms = result.get("atoms") if isinstance(result, dict) else None
        if not isinstance(atoms, list) or not atoms:
            QMessageBox.warning(
                self, self._t("warning"), self._t("loba_no_result"))
            return
        work_dir = os.path.dirname(str(result.get("log_path") or ""))
        if not work_dir:
            work_dir = self._output_dir() or os.getcwd()
        stem = os.path.splitext(os.path.basename(
            self._loba_input_path() or "LMO"))[0] or "LMO"
        if stem.endswith("_LMO"):
            stem = stem[:-4]
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("loba_export"),
            os.path.join(work_dir, stem + "_LOBA.csv"),
            self._t("csv_filter"))
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    self._t("loba_col_index"), self._t("loba_col_element"),
                    self._t("loba_col_state")])
                for atom in atoms:
                    if not isinstance(atom, dict):
                        continue
                    index = _as_int(atom.get("index"))
                    state = _as_float(atom.get("oxidation_state"))
                    writer.writerow([
                        "" if index is None else index,
                        atom.get("element") or "",
                        "" if state is None else ("%.10g" % state),
                    ])
            self._log(self._t("loba_log_csv_saved").format(path=path))
        except Exception as exc:  # noqa: BLE001 - CSV 操作失败给出提示
            QMessageBox.warning(
                self, self._t("failed_title"),
                self._t("csv_failed_msg").format(msg=exc))

    def _update_actions(self):
        result = self._last_result or {}
        has_rows = self.table.rowCount() > 0
        busy = self._running or self._generating or self._loba_running
        self.btn_visualize.setEnabled(has_rows and not busy)
        lmo_fch = self._lmo_fch_path()
        self.btn_open_wavefunction.setEnabled(bool(lmo_fch) and not busy)
        self.btn_export_csv.setEnabled(has_rows and not self._running)
        self.btn_open_dir.setEnabled(bool(self._output_dir()) and not busy)
        lmo_ready = bool(self._loba_input_path())
        self.btn_loba_run.setEnabled(lmo_ready and not busy)
        self.btn_loba_stop.setEnabled(self._loba_running)
        self.btn_loba_export.setEnabled(
            bool(self._last_loba_result) and not self._loba_running)

    def _output_dir(self):
        result = self._last_result or {}
        # run_localization 的 work_dir 是运行期临时目录（结束后已删除），
        # 因此输出目录以复制到 fchk 同目录的产物路径为准。
        for key in ("lmo_fch", "cen_txt", "log_path", "dip_txt"):
            path = str(result.get(key) or "").strip()
            if path:
                return os.path.dirname(path)
        if self._source_path:
            return os.path.dirname(self._source_path)
        return ""

    # ── 选中 / 可视化 ───────────────────────────────────────────────────
    def _selected_index(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        index = _as_int(item.data(_ORBITAL_ROLE))
        return index

    def _label_for_index(self, index):
        for spec in self._row_specs_cache:
            if spec.get("global") == index:
                return spec.get("orbital") or str(index)
        return str(index)

    def _visualize_selected(self):
        index = self._selected_index()
        if index is None:
            QMessageBox.warning(
                self, self._t("warning"), self._t("no_selection"))
            return
        self._generate_cube(index)

    def _on_cell_double_clicked(self, row, _column):
        item = self.table.item(row, 0)
        if item is None:
            return
        index = _as_int(item.data(_ORBITAL_ROLE))
        if index is not None:
            self._generate_cube(index)

    def _generate_cube(self, orbital_index):
        if self._running or self._generating:
            return
        result = self._last_result or {}
        lmo_fch = str(result.get("lmo_fch") or "").strip()
        if not lmo_fch or not os.path.isfile(lmo_fch):
            QMessageBox.warning(self, self._t("warning"), self._t("no_lmo_fch"))
            return
        multiwfn = self._current_multiwfn()
        if not multiwfn or not os.path.isfile(multiwfn):
            QMessageBox.warning(self, self._t("warning"), self._t("need_mw"))
            return
        grid = self._grid_quality()
        label = self._label_for_index(orbital_index)
        # cube 与 LMO 波函数放在同一个输出目录（不是运行期临时目录）
        work_dir = os.path.dirname(lmo_fch) or os.getcwd()
        self._generating = True
        self._gen_label = label
        self._set_status("status_generating", label=label)
        self._log(self._t("log_cube_start").format(
            label=label, grid=grid, path=os.path.basename(lmo_fch)))
        self._update_actions()
        self._cube_worker = LMOCubeWorker(
            lmo_fch, orbital_index, grid_quality=grid,
            multiwfn_exe=multiwfn, work_dir=work_dir, parent=self)
        self._cube_worker.log.connect(self._on_log)
        self._cube_worker.done.connect(self._on_cube_ready)
        self._cube_worker.error.connect(self._on_cube_error)
        self._cube_worker.finished.connect(self._on_cube_thread_finished)
        self._cube_worker.start()

    def _show_cube_on_canvas(self, cube_path):
        if self._on_show_cubes is not None:
            try:
                self._on_show_cubes([cube_path])
                return True
            except Exception as exc:  # noqa: BLE001 - 回调失败退回画布
                self._log(self._t("log_cube_error").format(msg=exc))
        glw = self.glw
        if glw is not None:
            try:
                glw.load(cube_path, 0.05)
                return True
            except Exception as exc:  # noqa: BLE001 - 无画布时降级
                self._log(self._t("log_cube_error").format(msg=exc))
        return False

    def _on_cube_ready(self, cube_path):
        if self._shutting_down:
            return
        cube_path = str(cube_path or "")
        if not cube_path:
            self._on_cube_error(self._t("status_cube_failed"))
            return
        self._set_status("status_cube_done", name=os.path.basename(cube_path))
        self._log(self._t("log_cube_done").format(path=cube_path))
        if not self._show_cube_on_canvas(cube_path):
            QMessageBox.warning(
                self, self._t("warning"), self._t("no_canvas"))

    def _on_cube_error(self, message):
        if self._shutting_down:
            return
        self._set_status("status_cube_failed")
        self._log(self._t("log_cube_error").format(msg=message))
        QMessageBox.warning(
            self, self._t("failed_title"),
            self._t("cube_failed_msg").format(msg=message))

    def _on_cube_thread_finished(self):
        worker = self._cube_worker
        self._cube_worker = None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(3000)
            except Exception:  # noqa: BLE001 - 清理失败不影响界面
                pass
        self._generating = False
        self._gen_label = ""
        if self._status_key == "status_generating":
            self._set_status(
                "status_ready" if self._source_path else "status_no_source")
        self._update_actions()

    # ── 其它动作 ────────────────────────────────────────────────────────
    def _open_lmo_wavefunction(self):
        result = self._last_result or {}
        path = str(result.get("lmo_fch") or "").strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(
                self, self._t("warning"),
                self._t("lmo_wavefunction_missing").format(
                    path=path or self._t("dash")))
            return
        if self._on_open_wavefunction is not None:
            try:
                self._on_open_wavefunction(path)
                self._log(self._t("log_open_wavefunction").format(
                    name=os.path.basename(path)))
            except Exception as exc:  # noqa: BLE001 - 回调异常弹窗提示
                QMessageBox.warning(self, self._t("failed_title"), str(exc))
        else:
            self._log(self._t("no_open_wavefunction_callback"))

    def _export_csv(self):
        rows = (self._row_specs_cache
                or self._row_specs(self._last_result or {}))
        if not rows:
            QMessageBox.warning(self, self._t("warning"), self._t("csv_empty"))
            return
        result = self._last_result or {}
        work_dir = self._output_dir() or os.getcwd()
        stem = os.path.splitext(os.path.basename(
            str(result.get("lmo_fch") or "LMO")))[0] or "LMO"
        # LMO 波函数名本身就以 _LMO 结尾，别再拼出 xxx_LMO_LMO.csv
        if stem.endswith("_LMO"):
            stem = stem[:-4]
        default_path = os.path.join(work_dir, stem + "_LMO.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("export_csv"), default_path, self._t("csv_filter"))
        if not path:
            return
        try:
            headers = [
                self._t("csv_orbital"), self._t("csv_spin"),
                self._t("csv_energy_au"), self._t("csv_energy_ev"),
                self._t("csv_occ"), self._t("csv_kind"),
                self._t("csv_contrib"), self._t("csv_center_x"),
                self._t("csv_center_y"), self._t("csv_center_z")]
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                for spec in rows:
                    center = spec.get("center") or (None, None, None)
                    center_values = []
                    for value in list(center)[:3]:
                        number = _as_float(value)
                        center_values.append(
                            "" if number is None else "%.3f" % number)
                    while len(center_values) < 3:
                        center_values.append("")
                    writer.writerow([
                        spec.get("orbital", ""),
                        spec.get("spin_text", ""),
                        self._fmt_number(spec.get("energy_au"), 6)
                        if _as_float(spec.get("energy_au")) is not None else "",
                        self._fmt_number(spec.get("energy_ev"), 4)
                        if _as_float(spec.get("energy_ev")) is not None else "",
                        self._fmt_number(spec.get("occ"), 4)
                        if _as_float(spec.get("occ")) is not None else "",
                        spec.get("kind", ""),
                        spec.get("contrib", ""),
                        center_values[0], center_values[1],
                        center_values[2],
                    ])
            self._log(self._t("log_csv_saved").format(path=path))
        except Exception as exc:  # noqa: BLE001 - 导出失败弹窗提示
            self._log(self._t("csv_failed_msg").format(msg=exc))
            QMessageBox.warning(
                self, self._t("failed_title"),
                self._t("csv_failed_msg").format(msg=exc))

    def _open_output_dir(self):
        path = self._output_dir()
        if not path or not os.path.isdir(path):
            QMessageBox.warning(
                self, self._t("warning"),
                self._t("open_dir_failed").format(path=path or self._t("dash")))
            return
        try:
            os.startfile(path)  # Windows
            return
        except AttributeError:
            pass
        except Exception as exc:  # noqa: BLE001 - 退回 QDesktopServices
            self._log(str(exc))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ── 生命周期 ────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        """主窗口关闭时调用：停止定域化、LOBA 与 cube 生成线程。

        关闭阶段不再弹任何模态框：后台线程被 stop() 终止后仍可能通过队列
        把 finished/error 信号送进来，`_shutting_down` 会让这些槽函数安静
        退出（否则关窗时会弹「定域化失败」对话框，甚至阻塞退出）。
        """
        self._shutting_down = True
        for worker in (self._worker, self._loba_worker, self._cube_worker):
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    if hasattr(worker, "stop"):
                        worker.stop()
                    worker.wait(5000)
            except Exception:  # noqa: BLE001 - 关闭阶段不再抛错
                pass
        self._worker = None
        self._loba_worker = None
        self._cube_worker = None


__all__ = ["LMOPanel", "LMOWorker", "LOBAWorker", "LMOCubeWorker", "TEXT"]
