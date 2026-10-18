# -*- coding: utf-8 -*-
"""
AICD（感应电流密度各向异性）面板
=================================

把 Gaussian 的 ``NMR=CSGT`` + ``IOp(10/93)`` 计算变成一张 AICD 效果图：

1. 选一个 Gaussian 输出（``.log`` / ``.out``）——AICD 的张量转储是 Gaussian
   在同一个任务里顺手写出来的，文件名记在输出里（``Writing AICD formatted
   file "test.txt"``），所以张量文件能自动找出来，不用手点；
2. 参数：标量场、外磁场方向、等值面数值、网格间距、箭头密度/长度、平滑等，
   对应 AICD 命令行的 ``-i -b -l -p -s -maxarrow``；
3. 计算 → 出图（:mod:`molstudio.render.aicd_figure`），面板内预览，并可导出
   cube 送进主画布看三维等值面。

轨道分解（只看 π / 只看 σ）不是这里的参数，而是要在 Gaussian 输入里写成
``IOp(10/93=2)`` + 文件末尾列出轨道编号，本面板读对应的张量转储即可。

计算全在本机完成，不调用 Multiwfn（AICD 的数据来源是 Gaussian 本身）。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import traceback

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from molstudio.core import aicd as A
from molstudio.core import gaussian_run as GR
from molstudio.core import multiwfn_pi as MPI
from molstudio.panels.aicd_figure_panel import AicdFigurePanel
from molstudio.render.aicd_figure import (AICD_FIGURE_STYLE, DEFAULT_VIEWS,
                                          build_arrow_surface,
                                          render_aicd_montage)


_TR = {
    "zh": {
        "grp_view": "AICD 效果图",
        "sub_workflow": "工作流",
        "sub_figure": "AICD 效果图",
        "grp_editor": "① 结构 / ② 输入文件（可直接编辑）",
        "grp_actions": "③ 运行",
        "grp_result": "④ 结果",
        "grp_advanced": "高级设置（数据 / 参数 / 导出）",
        "btn_advanced": "⚙ 参数与导出 ▾",
        "btn_advanced_open": "收起参数 ▴",
        "data_none": "结果：还没载入 .log",
        "data_ready": "结果：{log} + {tensor}",
        "structure_none": "还没有结构——先载入 .gjf，或点「生成输入…」从画布建一个",
        "structure_ready": "{n} 个原子 · {name}",
        "scope": "计算范围",
        "scope_all": "全部电子",
        "scope_pi": "只看 π",
        "scope_sigma": "只看 σ",
        "scope_custom": "输入里的轨道 (iop=2)",
        "scope_info_none": "π/σ 轨道号：未检测（选「只看 π/σ」会用 Multiwfn 自动找）",
        "scope_info_ready": "π 轨道: {pi}　σ 轨道: {sig}",
        "detect_orb": "检测 π/σ…",
        "detect_tip": "用 Multiwfn 从当前体系的 fchk 检测占据 π 轨道；平面体系用平面法，"
                      "扭曲体系用 LMO 投影。检测用的是主界面当前打开的 fchk，"
                      "请确认是同一体系。",
        "detect_running": "正在用 Multiwfn 检测 π/σ 轨道…",
        "detect_fail": "π/σ 轨道检测失败：{err}",
        "detect_need_fchk": "要单独画 π/σ 电流，需要知道占据 π/σ 轨道的编号；"
                            "自动检测要有这个体系的 fchk 或 .chk。\n\n"
                            "这个波函数不必来自 AICD 全电子任务——opt/freq 等"
                            "任何 SCF 留下的都可以：用 formchk 把 .chk 转成 fchk，"
                            "在主界面打开，再选「只看 π / 只看 σ」。\n\n"
                            "如果已经知道轨道号（苯是 17,20,21），也可以直接用"
                            "「生成输入… → 指定轨道」填好再算，跳过检测。",
        "detect_need_mw": "Multiwfn 路径未配置（⚙️ 路径设置）",
        "fchk_mismatch_title": "fchk 与当前结构不匹配",
        "fchk_mismatch_msg": "当前 fchk 有 {n_fchk} 个原子，载入的结构有 "
                             "{n_struct} 个原子，可能不是同一体系。\n\n"
                             "仍要用这个 fchk 检测 π/σ 轨道吗？",
        "scope_pi_applied": "已切到 π-only：输入写入 iop(10/93=2)，轨道 {orbs}",
        "scope_sigma_applied": "已切到 σ-only：输入写入 iop(10/93=2)，轨道 {orbs}",
        "scope_all_applied": "已切回全部电子（iop(10/93=1)）",
        "scope_custom_applied": "保持输入里指定的轨道（iop(10/93=2)）",
        "scope_switch_fail": "切换计算范围失败：{err}",
        "scope_short_all": "全部",
        "scope_short_pi": "π-only",
        "scope_short_sigma": "σ-only",
        "scope_short_orbs": "指定轨道",
        "flow_hint": "① 载入 GJF　→　② 检查 / 生成输入　→　③ 本地运行或服务器运行　→　④ 载入结果出图",
        "result_none": "算完后（或服务器算完）：把 .log 和同目录的张量 txt 放一起，"
                       "点上面的按钮载入",
        "result_ready": "结果：{log} + {tensor}",
        "from_canvas": "从画布生成",
        "load_gjf_editor": "载入 GJF…",
        "open_generator": "生成输入…",
        "save_gjf": "保存为…",
        "editor_hint": "载入 .gjf 会自动补齐 nmr=csgt iop(10/93=1) 与张量文件名，"
                       "也可以直接在这里改。本地运行算完自动出图；服务器运行算完"
                       "用「载入结果并出图」接上。",
        "editor_info": "{n} 个原子 · {route} · 张量 {tensor}",
        "editor_missing": "编辑器是空的——先「从画布生成」或「载入 .gjf…」",
        "editor_no_csgt": "⚠ 缺少 nmr=csgt",
        "editor_no_iop": "⚠ 缺少 iop(10/93=…)",
        "editor_no_tensor": "⚠ 没找到张量文件名（应在几何/连通性表之后）",
        "editor_bad_method": "⚠ 未知方法 {name}",
        "editor_suggest": "（是不是 {alt}？）",
        "editor_missing_link": "⚠ Gaussian 安装目录缺少 {name}（NMR 链接，可能被杀软隔离）",
        "missing_link_msg": "Gaussian 的 NMR 链接 {name} 不在 {folder} 里。\n\n"
                            "缺了它，任务会在 SCF 跑完后立刻失败（No executable "
                            "for file l801.exe），拿不到 AICD 张量。\n\n"
                            "常见原因：杀毒软件误报隔离。请到杀软隔离区恢复该文件，"
                            "或重装/修复 Gaussian；然后把安装目录加入信任列表。",
        "saved_gjf": "已保存输入：{path}",
        "need_save_gjf": "先把编辑器内容保存成 .gjf，再运行计算",
        "editor_loaded": "已载入 {name}（可直接编辑）",
        "no_canvas_mol": "画布上还没有分子——先打开一个结构文件",
        "grp_input": "分析数据（高级）",
        "grp_params": "出图参数（高级）",
        "hint_empty": "还没选 Gaussian 输出。\n\n"
                      "先跑一个带 nmr=csgt iop(10/93=1) 的 Gaussian 任务，"
                      "再选它的 .log；张量 txt 会自动找到。",
        "lbl_log": "Gaussian 输出",
        "pick_log": "选择 .log…",
        "lbl_tensor": "张量转储",
        "tensor_auto": "自动找到 {name}",
        "tensor_missing": "没在输出里找到 AICD 张量文件——确认这个任务是 "
                          "nmr=csgt iop(10/93=1) 算的，或手动指定",
        "pick_tensor": "手动指定…",
        "replot": "重新出图（当前结果）",
        "gen_input": "生成输入…",
        "gen_input_tip": "按当前画布（或编辑器里）的结构生成 Gaussian 输入"
                          "（nmr=csgt iop(10/93=1|2)），确认关键字和轨道后保存。",
        "gen_done": "已生成输入：{path}——点「本地运行」或「服务器运行…」",
        "quantity": "标量场",
        "quantity_tip": "Aniso = 各向异性（AICD 默认）；Iso = 各向同性分量"
                        "（看抗磁/顺磁环电流）",
        "field": "磁场方向",
        "field_tip": "外磁场方向，只需要方向（对应 AICD 的 -b）。\n"
                     "注意：这里的 x/y/z 是 Gaussian **标准取向**的坐标轴"
                     "（不是画布里看到的朝向——计算与摆位无关）。\n"
                     "选中 .log 后会按分子平面自动预选垂直方向：芳香性要看的就是"
                     "垂直环平面的环电流。",
        "field_auto": "已按分子平面自动选磁场方向：{dir}（平面度 RMS {rms:.3f} Å）",
        "field_auto_nonplanar": "体系不共平面（偏差 RMS {rms:.3f} Å）：磁场方向"
                                "先给 {dir}，需要的话请自行确认。",
        "field_auto_ring": "整体不共平面（RMS {rms:.3f} Å）→ 改按最平的环定方向："
                           "{dir}（{size} 元环，平面度 RMS {ring_rms:.3f} Å，"
                           "环上原子 {atoms}）。配合物请确认这个环是不是你要考察的。",
        "field_auto_selection": "按画布中选中的 {n} 个原子定平面 → 磁场方向 {dir}"
                                "（平面度 RMS {rms:.3f} Å）。",
        "iso": "等值面 (a.u.)",
        "iso_tip": "AICD 默认 0.05。π/σ 分解的电流密度比全电子弱；如果 π 骨架"
                   "断开，把等值面降到 0.04 或 0.03 就会连起来（AICD 官方图也"
                   "常用更低的等值面）。",
        "spacing": "网格间距 (Å)",
        "decimate": "箭头抽稀",
        "decimate_tip": "网格抽稀步长：1 最密（约 0.15 Å 一支），2 ≈ 0.3 Å 一支，"
                        "越大箭头越少（对应 AICD 的 -p）。画布和效果图共用这个值；"
                        "改完请点「重新出图（当前结果）」再送画布。",
        "arrow_len": "平均箭头长 (Å)",
        "arrow_len_tip": "AICD 把平均箭头长度固定归一化到 0.626 Bohr ≈ 0.33 Å；"
                         "这里默认放宽到 0.5 Å 更好看，可自行调",
        "max_arrow": "最长箭头 (×均长)",
        "max_arrow_tip": "对应 AICD 的 -maxarrow：数值噪声偶尔产出格外长的箭头"
                         "（σ 电子图里常见），超过该倍数的丢弃。0 = 不过滤",
        "smooth": "等值面平滑 σ",
        "smooth_tip": "提取等值面前对场做高斯平滑，0 = 关闭。AICD 的 -s 只磨圆"
                       "三角面、不缩面；场平滑会让等值面变瘦、π 带颈部凹口更深，"
                       "所以 π/σ 图默认 0。",
        "alpha": "等值面不透明度",
        "views": "视角",
        "views_montage": "六视图拼图",
        "views_top": "顶视大图",
        "views_oblique": "斜视大图",
        "outdir": "输出目录",
        "browse": "浏览…",
        "write_cube": "同时导出 cube（可在画布中查看三维等值面）",
        "auto_canvas": "算完自动送进画布（等值面 + 箭头）",
        "auto_canvas_tip": "计算完成后把等值面（cube）和绿杆红尖头箭头一起送进"
                           "左侧 OpenGL 画布，并把等值面配色设为 AICD 黄。",
        "show_arrows": "画布中显示箭头",
        "show_arrows_tip": "只切换画布上箭头的显示，不重新计算",
        "lock_iso": "等值面锁定为 AICD 黄（不透明）",
        "lock_iso_tip": "AICD 官方程序的等值面就是黄色且不透明。勾上后，送进画布"
                        "的等值面会保持 AICD 黄 + 不透明，点任何「一键样式」都不会"
                        "把它换成别的颜色。",
        "arrows_shown": "画布中已显示 {n} 支箭头（与等值面叠加）",
        "no_volume": "没有可用的计算结果，先运行或载入结果",
        "run": "载入结果并出图…",
        "cancel": "取消",
        "cancel_done": "已取消",
        "save_png": "保存图片…",
        "save_cube": "导出 cube…",
        "open_canvas": "在画布中打开",
        "busy": "正在计算…",
        "need_log": "请先选择 Gaussian 输出文件",
        "grp_run": "本机计算（高级）",
        "lbl_gjf": "输入 .gjf",
        "pick_gjf": "选择 .gjf…",
        "run_gauss": "本地运行",
        "cancel_run": "取消计算",
        "run_hint": "本地运行：直接在本机算，.log 与张量 txt 写在该 .gjf 的目录下，"
                    "算完自动出图。",
        "run_server": "服务器运行…",
        "server_title": "在服务器上运行",
        "server_saved": "输入已保存到：{path}",
        "server_cmd_hint": "把 .gjf 上传到服务器，在它所在目录执行（g16 换成你的版本）：",
        "server_bring_back": "算完后，把 .log 和同目录的 {tensor} 一起拷回本地"
                             "（放在同一目录），再点「载入结果并出图」。",
        "server_note": "本程序不直接连接服务器；这里只准备输入和命令。",
        "server_exported": "已导出输入：{path}；算完点「载入结果并出图」",
        "copy_cmd": "复制命令",
        "copy_path": "复制路径",
        "open_folder": "打开所在文件夹",
        "copied": "已复制",
        "close": "关闭",
        "tensor_pick_title": "没找到张量文件",
        "tensor_pick_msg": "这个 .log 里没有记录 AICD 张量文件（任务可能没跑到 "
                           "NMR，或文件被改名）。要手动选择张量 .txt 吗？",
        "need_gjf": "请先选择 .gjf 输入文件",
        "need_g16": "没有找到 Gaussian 可执行文件——请在 ⚙️ 路径设置里配置 g16.exe",
        "gauss_running": "Gaussian 计算中…（{elapsed:.0f}s）",
        "gauss_done": "Gaussian 算完：{log}（{t:.0f}s）；已自动接上张量 {tensor}",
        "gauss_done_analyzing": "Gaussian 算完（{t:.0f}s），开始出 AICD 图…",
        "gauss_failed": "Gaussian 失败：{err}",
        "gauss_cancelled": "已取消 Gaussian 计算",
        "auto_after_run": "算完自动出图",
        "auto_pi": "算完自动检测 π 轨道（Multiwfn，较慢）",
        "auto_pi_tip": "计算完成后调用 formchk 把 .chk 转成 .fchk，再用 Multiwfn "
                       "找出占据 π 轨道，为它们生成 cube 并叠加到画布上"
                       "（最多 8 个，便于一眼看清 π 体系）。",
        "pi_running": "正在 chk→fch 并分析 π 轨道…",
        "pi_found": "π 轨道：{pi}（{mode}）；已生成 {n} 个 cube 并叠加到画布",
        "pi_fail": "π 轨道分析失败：{err}",
        "pi_label": "π 轨道：{pi}",
        "pi_none": "π 轨道：（未检测）",
        "write_pi": "写 π-only 输入",
        "write_sigma": "写 σ-only 输入",
        "pi_need": "还没有 π 轨道编号——先跑一次计算（勾了自动检测的话算完就有了）",
        "pi_written": "已把 {tag} 轨道 {orbs} 写进输入（iop(10/93=2)），"
                      "点「运行 Gaussian」即可算第二遍",
        "no_tensor": "这个输出里没有 AICD 张量文件（test.txt 之类）。\n"
                     "确认任务是 nmr=csgt iop(10/93=1) / iop(10/93=2) 算的，"
                     "或者用「手动指定…」选张量 txt。",
        "done": "完成：{n} 格点 → {na} 支箭头，标量场 {lo:.4f}–{hi:.4f}，"
                "用时 {t:.1f} s",
        "failed": "失败：{err}",
        "saved": "已保存：{path}",
        "no_result": "还没有结果，先点「计算并出图」",
        "no_cube": "这次没有导出 cube（勾上「同时导出 cube」再算一次）",
        "cube_done": "已写 cube：{path}",
        "loaded_canvas": "已把等值面送进画布（{name}）",
        "no_canvas": "画布不可用",
    },
    "en": {
        "grp_view": "AICD figure",
        "sub_workflow": "Workflow",
        "sub_figure": "AICD figure",
        "grp_editor": "① Structure / ② Input file (editable)",
        "grp_actions": "③ Run",
        "grp_result": "④ Results",
        "grp_advanced": "Advanced (data / parameters / export)",
        "btn_advanced": "⚙ Parameters & export ▾",
        "btn_advanced_open": "Hide parameters ▴",
        "data_none": "Results: no .log loaded yet",
        "data_ready": "Results: {log} + {tensor}",
        "structure_none": "No structure yet — load a .gjf, or click "
                          "\"Generate input…\" to use the canvas",
        "structure_ready": "{n} atoms · {name}",
        "scope": "Scope",
        "scope_all": "All electrons",
        "scope_pi": "π only",
        "scope_sigma": "σ only",
        "scope_custom": "Orbitals in input (iop=2)",
        "scope_info_none": "π/σ orbital indices: not detected yet (choosing "
                           "π/σ runs Multiwfn automatically)",
        "scope_info_ready": "π orbitals: {pi}　σ orbitals: {sig}",
        "detect_orb": "Detect π/σ…",
        "detect_tip": "Detect occupied π orbitals from the current fchk with "
                      "Multiwfn (plane method for planar, LMO projection for "
                      "distorted systems). It uses the fchk currently open in the "
                      "main window — make sure it is the same system.",
        "detect_running": "Detecting π/σ orbitals with Multiwfn…",
        "detect_fail": "π/σ orbital detection failed: {err}",
        "detect_need_fchk": "To plot π/σ current separately you need the occupied "
                            "π/σ orbital indices; automatic detection needs an "
                            "fchk or .chk of this system.\n\nThat wavefunction "
                            "does not have to come from an all-electron AICD job — "
                            "any SCF run (opt/freq etc.) works: convert the .chk "
                            "to .fchk with formchk, open it in the main window, "
                            "then choose π only / σ only.\n\nIf you already know "
                            "the indices (benzene: 17,20,21), use \"Generate "
                            "input… → Selected orbitals\", fill them in and run "
                            "that job directly — no detection needed.",
        "detect_need_mw": "Multiwfn path is not configured (⚙️ Path settings)",
        "fchk_mismatch_title": "fchk does not match the current structure",
        "fchk_mismatch_msg": "The current fchk has {n_fchk} atoms while the loaded "
                             "structure has {n_struct} — they may be different "
                             "systems.\n\nUse this fchk to detect π/σ orbitals "
                             "anyway?",
        "scope_pi_applied": "Switched to π-only: iop(10/93=2), orbitals {orbs}",
        "scope_sigma_applied": "Switched to σ-only: iop(10/93=2), orbitals {orbs}",
        "scope_all_applied": "Switched back to all electrons (iop(10/93=1))",
        "scope_custom_applied": "Keeping the orbitals specified in the input "
                                "(iop(10/93=2))",
        "scope_switch_fail": "Could not switch scope: {err}",
        "scope_short_all": "all",
        "scope_short_pi": "π-only",
        "scope_short_sigma": "σ-only",
        "scope_short_orbs": "selected orbitals",
        "flow_hint": "① Load GJF  →  ② Check / generate input  →  ③ Run locally or on a server  →  ④ Load results & plot",
        "result_none": "When the job is done (or back from the server): put the "
                       ".log and its tensor .txt in one folder, then load them "
                       "with the button above",
        "result_ready": "Results: {log} + {tensor}",
        "from_canvas": "From canvas",
        "load_gjf_editor": "Load GJF…",
        "open_generator": "Generate input…",
        "save_gjf": "Save as…",
        "editor_hint": "Loading a .gjf fills in nmr=csgt iop(10/93=1) and the "
                       "tensor file name automatically; you can still edit it "
                       "here. A local run renders the figure automatically; for a "
                       "server run use \"Load results & plot\" when it finishes.",
        "editor_info": "{n} atoms · {route} · tensor {tensor}",
        "editor_missing": "Editor is empty — use \"From canvas\" or \"Load .gjf…\"",
        "editor_no_csgt": "⚠ missing nmr=csgt",
        "editor_no_iop": "⚠ missing iop(10/93=…)",
        "editor_no_tensor": "⚠ no tensor file name (should follow the geometry/"
                            "connectivity table)",
        "editor_bad_method": "⚠ unknown method {name}",
        "editor_suggest": " (did you mean {alt}?)",
        "editor_missing_link": "⚠ Gaussian install is missing {name} (NMR link, "
                               "possibly quarantined)",
        "missing_link_msg": "Gaussian's NMR link {name} is missing from {folder}.\n\n"
                            "Without it the job dies right after SCF (No executable "
                            "for file l801.exe) and no AICD tensor is written.\n\n"
                            "Usually an antivirus quarantined it: restore it from the "
                            "quarantine, or reinstall/repair Gaussian, then whitelist "
                            "the install folder.",
        "saved_gjf": "Input saved: {path}",
        "need_save_gjf": "Save the editor content as a .gjf before running",
        "editor_loaded": "Loaded {name} (editable)",
        "no_canvas_mol": "No molecule on the canvas — open a structure first",
        "grp_input": "Analysis data (advanced)",
        "grp_params": "Plot parameters (advanced)",
        "hint_empty": "No Gaussian output selected yet.\n\n"
                      "Run a job with nmr=csgt iop(10/93=1), then pick its .log — "
                      "the tensor dump is found automatically.",
        "lbl_log": "Gaussian output",
        "pick_log": "Open .log…",
        "lbl_tensor": "Tensor dump",
        "tensor_auto": "found {name}",
        "tensor_missing": "No AICD tensor file recorded in this output — make sure "
                          "the job used nmr=csgt iop(10/93=1), or pick it manually",
        "pick_tensor": "Pick manually…",
        "replot": "Re-plot current result",
        "gen_input": "Generate input…",
        "gen_input_tip": "Generate the Gaussian input (nmr=csgt iop(10/93=1|2)) from "
                         "the canvas (or the structure in the editor), then save it.",
        "gen_done": "Input written: {path} — click \"Run locally\" or "
                    "\"Run on server…\"",
        "quantity": "Quantity",
        "quantity_tip": "Aniso = anisotropy (AICD default); Iso = isotropic part "
                        "(diatropic/paratropic ring current)",
        "field": "Field direction",
        "field_tip": "Direction of the external magnetic field (AICD's -b); "
                     "only the direction matters.\nNote: x/y/z here are the axes of "
                     "Gaussian's **standard orientation** (not what you see on the "
                     "canvas — placement does not affect the calculation).\n"
                     "Picking a .log auto-selects the perpendicular direction from "
                     "the molecular plane, which is what aromaticity analysis "
                     "needs.",
        "field_auto": "Field direction auto-set from the molecular plane: {dir} "
                      "(planarity RMS {rms:.3f} Å)",
        "field_auto_nonplanar": "System is not planar (RMS {rms:.3f} Å): defaulting "
                                "to {dir} — please double-check.",
        "field_auto_ring": "System is not planar (RMS {rms:.3f} Å) → using the "
                           "flattest ring instead: {dir} ({size}-membered ring, RMS "
                           "{ring_rms:.3f} Å, ring atoms {atoms}). For complexes, "
                           "check that this is the ring you care about.",
        "field_auto_selection": "Plane fitted through the {n} atoms selected on the "
                                "canvas → field direction {dir} (RMS {rms:.3f} Å).",
        "iso": "Isovalue (a.u.)",
        "iso_tip": "AICD's default is 0.05. The π/σ current density is weaker "
                   "than the all-electron one; if the π skeleton breaks, lower "
                   "the isovalue to 0.04 or 0.03 to reconnect it (AICD figures "
                   "often use a lower isovalue as well).",
        "spacing": "Grid spacing (Å)",
        "decimate": "Arrow thinning",
        "decimate_tip": "Grid stride: 1 = densest (~0.15 Å), 2 ≈ 0.3 Å, "
                        "larger = fewer arrows (AICD's -p). Canvas and figure "
                        "share this value; click Re-plot after changing it.",
        "arrow_len": "Mean arrow length (Å)",
        "arrow_len_tip": "AICD normalises the mean arrow length to 0.626 Bohr "
                         "≈ 0.33 Å; 0.5 Å reads better",
        "max_arrow": "Longest arrow (×mean)",
        "max_arrow_tip": "AICD's -maxarrow: numerical noise occasionally gives very "
                         "long arrows (common in σ-only maps); drop them. 0 = off",
        "smooth": "Isosurface smoothing σ",
        "smooth_tip": "Gaussian smoothing of the scalar field before isosurface "
                      "extraction; 0 = off. AICD's -s only smooths the "
                      "triangulation, it does not shrink the surface. Field "
                      "smoothing thins the surface and deepens the π-band necks, "
                      "so π/σ figures default to 0.",
        "alpha": "Isosurface opacity",
        "views": "Views",
        "views_montage": "Six-view montage",
        "views_top": "Top view (large)",
        "views_oblique": "Oblique view (large)",
        "outdir": "Output folder",
        "browse": "Browse…",
        "write_cube": "Also export a cube (view the 3D isosurface on the canvas)",
        "auto_canvas": "Send to canvas after computing (isosurface + arrows)",
        "auto_canvas_tip": "After computing, push the isosurface (cube) and the "
                           "green-shaft/red-head arrows into the OpenGL canvas on "
                           "the left, and tint the isosurface AICD yellow.",
        "show_arrows": "Show arrows on canvas",
        "show_arrows_tip": "Toggle the arrow layer on the canvas without "
                           "recomputing",
        "lock_iso": "Lock isosurface to AICD yellow (opaque)",
        "lock_iso_tip": "The AICD program's isosurface is yellow and opaque. When "
                        "ticked, the isosurface pushed to the canvas stays AICD "
                        "yellow + opaque even after one-click styles.",
        "arrows_shown": "{n} arrows now shown on the canvas (over the isosurface)",
        "no_volume": "No result available — run the job or load a result first",
        "run": "Load results & plot…",
        "cancel": "Cancel",
        "cancel_done": "Cancelled",
        "save_png": "Save image…",
        "save_cube": "Export cube…",
        "open_canvas": "Open on canvas",
        "busy": "Computing…",
        "need_log": "Pick a Gaussian output file first",
        "grp_run": "Local run (advanced)",
        "lbl_gjf": "Input .gjf",
        "pick_gjf": "Open .gjf…",
        "run_gauss": "Run locally",
        "cancel_run": "Cancel job",
        "run_hint": "Run locally: the .log and tensor dump land in the .gjf's "
                    "folder and the figure is rendered automatically.",
        "run_server": "Run on server…",
        "server_title": "Run on a server",
        "server_saved": "Input saved to: {path}",
        "server_cmd_hint": "Upload the .gjf and run this in its folder "
                           "(swap g16 for your version):",
        "server_bring_back": "When it finishes, copy the .log and {tensor} back "
                             "(same folder), then click \"Load results & plot\".",
        "server_note": "MolStudio does not connect to the server; this only "
                       "prepares the input and the command.",
        "server_exported": "Input exported: {path} — click \"Load results & "
                           "plot\" when the server job is done",
        "copy_cmd": "Copy command",
        "copy_path": "Copy path",
        "open_folder": "Open folder",
        "copied": "Copied",
        "close": "Close",
        "tensor_pick_title": "Tensor file not found",
        "tensor_pick_msg": "No AICD tensor file is recorded in this .log (the job "
                           "may not have reached NMR, or the file was renamed). "
                           "Pick the tensor .txt manually?",
        "need_gjf": "Pick a .gjf input file first",
        "need_g16": "No Gaussian executable found — configure g16.exe in "
                    "⚙️ Path settings",
        "gauss_running": "Gaussian running… ({elapsed:.0f}s)",
        "gauss_done": "Gaussian finished: {log} ({t:.0f}s); tensor wired in: "
                      "{tensor}",
        "gauss_done_analyzing": "Gaussian finished ({t:.0f}s) — rendering the "
                                "AICD figure…",
        "gauss_failed": "Gaussian failed: {err}",
        "gauss_cancelled": "Gaussian job cancelled",
        "auto_after_run": "Render figure automatically when done",
        "auto_pi": "Detect π orbitals after the run (Multiwfn, slower)",
        "auto_pi_tip": "When the job finishes, convert the .chk with formchk, detect "
                       "the occupied π orbitals with Multiwfn, generate their cubes "
                       "and overlay them on the canvas (up to 8).",
        "pi_running": "Converting chk→fch and analysing π orbitals…",
        "pi_found": "π orbitals: {pi} ({mode}); {n} cubes generated and overlaid on "
                    "the canvas",
        "pi_fail": "π-orbital analysis failed: {err}",
        "pi_label": "π orbitals: {pi}",
        "pi_none": "π orbitals: (not detected)",
        "write_pi": "Write π-only input",
        "write_sigma": "Write σ-only input",
        "pi_need": "No π orbital numbers yet — run the job once (auto-detection "
                   "fills them in)",
        "pi_written": "Wrote the {tag} orbitals {orbs} into the input "
                      "(iop(10/93=2)); click \"Run Gaussian\" for the second pass",
        "no_tensor": "This output has no AICD tensor file (test.txt etc.).\n"
                     "Make sure the job used nmr=csgt iop(10/93=1) / iop(10/93=2), "
                     "or use \"Pick manually…\".",
        "done": "Done: {n} grid points → {na} arrows, "
                "quantity {lo:.4f}–{hi:.4f}, {t:.1f} s",
        "failed": "Failed: {err}",
        "saved": "Saved: {path}",
        "no_result": "No result yet — click \"Compute & render\"",
        "no_cube": "No cube was written (tick \"Also export a cube\" and run again)",
        "cube_done": "Cube written: {path}",
        "loaded_canvas": "Isosurface sent to the canvas ({name})",
        "no_canvas": "Canvas is not available",
    },
}


#: 磁场方向下拉：显示文本 → 矢量（只需方向，与 AICD 的 -b 同理）。
#: 文本刻意只用符号，免得跟语言切换耦合；说明放在 tooltip 里。
_FIELDS = (
    ("+z", (0.0, 0.0, 1.0)),
    ("−z", (0.0, 0.0, -1.0)),
    ("+x", (1.0, 0.0, 0.0)),
    ("−x", (-1.0, 0.0, 0.0)),
    ("+y", (0.0, 1.0, 0.0)),
    ("−y", (0.0, -1.0, 0.0)),
)

#: 计算范围下拉：全部 / 只看 π / 只看 σ / 输入里已有的指定轨道
_SCOPES = ("all", "pi", "sigma", "custom")

#: 视角预设：视图表 / 行 / 列 / 画幅
_VIEW_PRESETS = {
    "montage": (DEFAULT_VIEWS, 2, 3, (16.2, 10.6)),
    "top": (((0, 0, "surface", 90.0, -90.0),), 1, 1, (7.6, 7.6)),
    "oblique": (((0, 0, "surface", 24.0, -55.0),), 1, 1, (7.6, 7.6)),
}


#: 常见 Gaussian 方法/泛函（用于"路由写错"的提醒，比如把 b3lyp 打成 n3lyp）。
#: 只做提示，不强制——Gaussian 认得的方法比这里多得多。
_KNOWN_METHODS = {
    "hf", "uhf", "rhf", "rohf", "mp2", "mp3", "mp4", "ccsd", "ccsd(t)", "cis",
    "b3lyp", "b3pw91", "b3p86", "b3lyp-d3", "b3lyp-d3bj", "b2plyp", "blyp",
    "bp86", "bpbe", "pbe", "pbe0", "pbepbe", "opbe", "tpss", "tpssh",
    "tpsstpss", "m06", "m06-2x", "m06-l", "m06-hf", "m08-hx", "m08-so",
    "m11", "mn12-l", "mn15", "cam-b3lyp", "wb97x", "wb97xd", "wb97x-d",
    "hse06", "hse03", "b97d", "b97d3", "bhandh", "bhandhlyp", "x3lyp",
    "apfd", "apf", "lc-wpbe", "mpw1pw91", "mpw1k", "cbs-qb3", "g4", "g4mp2",
}

#: 提示排序：常见方法排前面（"n3lyp" 这种拼错时先给 b3lyp，而不是 x3lyp）
_METHOD_PRIORITY = {name: i for i, name in enumerate((
    "b3lyp", "b3pw91", "pbe0", "m06-2x", "wb97xd", "hf", "mp2", "tpss",
    "cam-b3lyp", "m06", "b97d3", "pbe", "bp86", "blyp",
))}


class _Cancelled(Exception):
    """用户点了取消：由进度回调抛出，用来中断计算。"""


class _GaussWorker(QThread):
    """后台跑本机 Gaussian（g16.exe），把日志按里程碑回传。"""

    line = pyqtSignal(str)          # 每行日志（界面只显示最后一行）
    milestone = pyqtSignal(str)     # 里程碑（写进主日志）
    done = pyqtSignal(dict)

    def __init__(self, gjf, exe, parent=None):
        super().__init__(parent)
        self._gjf = gjf
        self._exe = exe
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        seen = set()

        def on_line(text):
            self.line.emit(text)
            low = text.lower()
            for key, label in GR.MILESTONES:
                if key.lower() in low and label not in seen:
                    seen.add(label)
                    self.milestone.emit(label)

        try:
            res = GR.run_gaussian(self._gjf, self._exe, on_line=on_line,
                                  cancel=lambda: self._cancel)
            self.done.emit({
                "ok": res.ok, "cancelled": res.cancelled,
                "log": res.log_path, "tensor": res.tensor_path,
                "seconds": res.seconds, "error": res.error,
                "returncode": res.returncode,
            })
        except Exception as exc:                        # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc)})


class _PiPostWorker(QThread):
    """算完的收尾链：chk → fchk（formchk）→ 找占有 π 轨道 → 生成 π 轨道 cube。

    为什么需要 fchk：Multiwfn 的 π 轨道检测读的是格式化检查点；Gaussian 只写
    .chk，所以必须调 formchk。cube 生成也走 Multiwfn（主功能 5 → 4 → 轨道号）。
    """

    log = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, log_path, multiwfn, max_cubes=8, threshold=80,
                 parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._mw = multiwfn
        self._max = int(max_cubes)
        self._threshold = int(threshold)

    def run(self):
        try:
            chk = GR.find_chk_file(self._log_path)
            if not chk:
                raise RuntimeError("找不到 .chk（Gaussian 没写检查点？）")
            self.log.emit("chk → fchk：%s" % os.path.basename(chk))
            fchk = GR.chk_to_fchk(chk)
            atoms = A.read_standard_orientation(self._log_path)
            planar = bool(atoms) and A.guess_plane_normal(atoms)["planar"]
            if planar:
                info = MPI.detect_pi_orbitals(fchk, self._mw)
            else:
                info = MPI.detect_pi_by_projection(
                    fchk, self._mw, threshold=self._threshold)
            pi = list(info.get("pi_occupied") or [])
            cubes = []
            if pi:
                from molstudio.core.fchk_orbital import gen_multi_cubes
                res = gen_multi_cubes(
                    fchk, [str(n) for n in pi][:self._max], 2, self._mw,
                    work_dir=os.path.dirname(fchk))
                cubes = list(res or [])
            self.done.emit({
                "ok": True, "chk": chk, "fchk": fchk,
                "pi": pi, "pi_str": info.get("pi_occupied_str", ""),
                "sigma_str": info.get("sigma_occupied_str", ""),
                "mode": info.get("mode", "planar"),
                "cubes": [c for c, _ in cubes],
            })
        except Exception as exc:                        # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc)})


class _ScopeWorker(QThread):
    """后台用 Multiwfn 检测 π/σ 轨道（给"只看 π / 只看 σ"的输入改写用）。"""

    log = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, fchk, multiwfn, planar=True, threshold=80, parent=None):
        super().__init__(parent)
        self._fchk = fchk
        self._mw = multiwfn
        self._planar = bool(planar)
        self._threshold = int(threshold)

    def run(self):
        try:
            if self._planar:
                info = MPI.detect_pi_orbitals(
                    self._fchk, self._mw, on_log=self.log.emit)
            else:
                info = MPI.detect_pi_by_projection(
                    self._fchk, self._mw, threshold=self._threshold,
                    on_log=self.log.emit)
            self.done.emit({"ok": True, "info": info})
        except Exception as exc:                        # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc)})


class AicdWorker(QThread):
    """后台跑 AICD 计算 + 出图，主线程不阻塞。"""

    log = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, log_path, tensor_path, outdir, params, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._tensor_path = tensor_path
        self._outdir = outdir
        self._p = dict(params)
        self._cancel = False
        self._n_arrow = 0

    def cancel(self):
        self._cancel = True

    def _progress(self, msg):
        if self._cancel:
            raise _Cancelled()
        self.log.emit(str(msg))

    def run(self):
        t0 = time.time()
        try:
            p = self._p
            os.makedirs(self._outdir, exist_ok=True)
            base = os.path.splitext(os.path.basename(self._log_path))[0]
            png = os.path.join(self._outdir, base + "_AICD.png")

            self._progress("读取 AICD 张量数据…")
            vol = A.compute_aicd(
                self._tensor_path, self._log_path,
                quantity=p["quantity"], field=p["field"],
                spacing=p["spacing"], padding=p["padding"],
                with_vectors=True, progress=self._progress)

            views, rows, cols, figsize = _VIEW_PRESETS[p["views"]]
            self._progress("渲染效果图…")
            stats = {}
            png = render_aicd_montage(
                vol, png, iso=p["iso"], field_axis=p["field"],
                views=views, rows=rows, cols=cols, figsize=figsize,
                decimate=p["decimate"], magnitude_floor=0.02,
                arrow_mean_length=p["arrow_len"], smooth_sigma=p["smooth"],
                max_arrow=p["max_arrow"], min_arrow=0.0,
                surface_alpha=p["alpha"], progress=self._progress,
                stats=stats)

            cube = ""
            if p["write_cube"]:
                cube = os.path.join(self._outdir, base + "_AICD_Aniso.cub")
                A.write_cube(cube, vol.origin, vol.spacing, vol.field, vol.atoms,
                             comment="AICD %s (B = %s)" % (p["quantity"], p["field"]))

            meta = vol.metadata or {}
            self.done.emit({
                "ok": True, "png": png, "cube": cube, "volume": vol,
                "n_grid": int(meta.get("n_grid_points", 0)),
                "n_arrow": int(stats.get("n_arrows", 0)),
                "quantity": p.get("quantity", ""),
                "scope": p.get("scope", "all"),
                "field_text": "%g %g %g" % tuple(p.get("field", (0, 0, 1))),
                "iso": float(p.get("iso", 0.05)),
                "lo": float(vol.value_range[0]), "hi": float(vol.value_range[1]),
                "seconds": time.time() - t0,
            })
        except _Cancelled:
            self.done.emit({"ok": False, "cancelled": True})
        except Exception as exc:                      # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc),
                            "trace": traceback.format_exc()})


class AicdPanel(QWidget):
    """「感应电流（AICD）」工作流页。

    右侧从上到下是三步：**输入文件编辑 → 本机 Gaussian 计算 → 出图参数**。
    算完的效果图不再挤在这一页，而是发到独立的「AICD 效果图」页（可以单独
    打开给别人看），见 :class:`molstudio.panels.aicd_figure_panel.AicdFigurePanel`。
    """

    #: 出图完成：(png 路径, 参数摘要)。主窗口把它接到「AICD 效果图」页并切过去
    figureReady = pyqtSignal(str, str)

    def __init__(self, glw=None, log_func=None, on_open_cube=None,
                 get_fchk=None, get_multiwfn=None, get_g16=None, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self._log = log_func or (lambda m: None)
        self._on_open_cube = on_open_cube
        # 输入生成器里"用 Multiwfn 找 π/σ 轨道"要用：当前体系的 fchk + Multiwfn 路径
        self._get_fchk = get_fchk or (lambda: "")
        self._get_mw = get_multiwfn or (lambda: "")
        self._get_g16 = get_g16 or (lambda: "")

        self._log_path = ""
        self._tensor_path = ""
        self._outdir = ""
        self._worker = None
        self._png = ""
        self._cube = ""
        self._vol = None                 # 最近一次算出的 AICDVolume（送画布用）
        self._arrows_pushed = 0          # 画布上当前箭头数（0 = 没有）
        self._iso_locked = False         # 画布等值面是否处于 AICD 黄锁定
        self._gjf_path = ""              # 要交给本机 Gaussian 的输入
        self._gauss_worker = None
        self._gauss_started = 0.0
        self._pi_worker = None           # chk→fch + π 轨道检测
        self._pi_str = ""                # 检测到的占据 π 轨道（"17,20,21"）
        self._sigma_str = ""             # 对应的 σ 轨道
        self._pi_cubes = []
        self._params_used = {}           # 最近一次出图用的参数（画布必须与图一致）
        self._scope_worker = None        # π/σ 轨道检测
        self._base_input_text = ""       # 全电子输入（π/σ 从它派生）
        self._base_gjf_path = ""
        self._last_chk = ""              # 最近一次本地全电子任务的 .chk
        self._syncing_scope = False
        self._iso_auto = True            # 用户没手动改 iso 时，π/σ 自动用 0.04
        self._syncing_iso = False
        self._smooth_auto = True         # 用户没手动改 smooth 时，π/σ 自动用 0
        self._syncing_smooth = False
        self._struct_atoms = []          # [(符号, x, y, z)] Å：当前结构（画布/标签用）
        self._struct_name = ""           # 结构来源文件名

        self._build_ui()
        self._apply_lang()

    # ── i18n ──────────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        s = _TR.get(self.lang, _TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    def _apply_lang(self):
        self.subtabs.setTabText(0, self._t("sub_workflow"))
        self.subtabs.setTabText(1, self._t("sub_figure"))
        self.lbl_flow.setText(self._t("flow_hint"))
        self.grp_editor.setTitle(self._t("grp_editor"))
        self.grp_actions.setTitle(self._t("grp_actions"))
        self.grp_result.setTitle(self._t("grp_result"))
        self.grp_advanced.setTitle(self._t("grp_advanced"))
        self.btn_advanced.setText(self._t(
            "btn_advanced_open" if self.btn_advanced.isChecked()
            else "btn_advanced"))
        if getattr(self, "figure_view", None) is not None:
            self.figure_view.set_lang(self.lang)
        self.btn_from_canvas.setText(self._t("from_canvas"))
        self.btn_load_gjf.setText(self._t("load_gjf_editor"))
        self.btn_generator.setText(self._t("open_generator"))
        self.btn_generator.setToolTip(self._t("gen_input_tip"))
        self.btn_save_editor.setText(self._t("save_gjf"))
        self.lbl_editor_hint.setText(self._t("editor_hint"))
        self.lbl_scope.setText(self._t("scope"))
        for i, key in enumerate(("scope_all", "scope_pi", "scope_sigma",
                                 "scope_custom")):
            self.cmb_scope.setItemText(i, self._t(key))
        self.btn_detect_orb.setText(self._t("detect_orb"))
        self.btn_detect_orb.setToolTip(self._t("detect_tip"))
        self._refresh_scope_info()
        self.grp_input.setTitle(self._t("grp_input"))
        self.grp_params.setTitle(self._t("grp_params"))
        self.grp_run.setTitle(self._t("grp_run"))
        self.lbl_gjf.setText(self._t("lbl_gjf"))
        self.btn_pick_gjf.setText(self._t("pick_gjf"))
        self.btn_run_gauss.setText(self._t("run_gauss"))
        self.btn_run_gauss.setToolTip(self._t("run_hint"))
        self.btn_server.setText(self._t("run_server"))
        self.btn_server.setToolTip(self._t("server_note"))
        self.btn_run.setText(self._t("run"))
        self.btn_cancel.setText(self._t("cancel"))
        self.btn_cancel_gauss.setText(self._t("cancel_run"))
        self.chk_auto_pi.setText(self._t("auto_pi"))
        self.chk_auto_pi.setToolTip(self._t("auto_pi_tip"))
        self.btn_write_pi.setText(self._t("write_pi"))
        self.btn_write_sigma.setText(self._t("write_sigma"))
        self._refresh_pi_label()
        self.lbl_run_hint.setText(self._t("run_hint"))
        self.lbl_log.setText(self._t("lbl_log"))
        self.btn_pick_log.setText(self._t("pick_log"))
        self.lbl_tensor.setText(self._t("lbl_tensor"))
        self.btn_pick_tensor.setText(self._t("pick_tensor"))
        self.btn_gen_input.setText(self._t("gen_input"))
        self.btn_gen_input.setToolTip(self._t("gen_input_tip"))
        self.btn_replot.setText(self._t("replot"))
        self.lbl_quantity.setText(self._t("quantity"))
        self.cmb_quantity.setToolTip(self._t("quantity_tip"))
        self.lbl_field.setText(self._t("field"))
        self.lbl_field.setToolTip(self._t("field_tip"))
        self.cmb_field.setToolTip(self._t("field_tip"))
        self.lbl_iso.setText(self._t("iso"))
        self.lbl_iso.setToolTip(self._t("iso_tip"))
        self.spn_iso.setToolTip(self._t("iso_tip"))
        self.lbl_spacing.setText(self._t("spacing"))
        self.lbl_decimate.setText(self._t("decimate"))
        self.lbl_decimate.setToolTip(self._t("decimate_tip"))
        self.spn_decimate.setToolTip(self._t("decimate_tip"))
        self.lbl_arrow_len.setText(self._t("arrow_len"))
        self.lbl_arrow_len.setToolTip(self._t("arrow_len_tip"))
        self.spn_arrow_len.setToolTip(self._t("arrow_len_tip"))
        self.lbl_max_arrow.setText(self._t("max_arrow"))
        self.lbl_max_arrow.setToolTip(self._t("max_arrow_tip"))
        self.spn_max_arrow.setToolTip(self._t("max_arrow_tip"))
        self.lbl_smooth.setText(self._t("smooth"))
        self.lbl_smooth.setToolTip(self._t("smooth_tip"))
        self.spn_smooth.setToolTip(self._t("smooth_tip"))
        self.lbl_alpha.setText(self._t("alpha"))
        self.lbl_views.setText(self._t("views"))
        for i, key in enumerate(("views_montage", "views_top", "views_oblique")):
            self.cmb_views.setItemText(i, self._t(key))
        self.lbl_outdir.setText(self._t("outdir"))
        self.btn_outdir.setText(self._t("browse"))
        self.chk_cube.setText(self._t("write_cube"))
        self.chk_auto_canvas.setText(self._t("auto_canvas"))
        self.chk_auto_canvas.setToolTip(self._t("auto_canvas_tip"))
        self.chk_arrows.setText(self._t("show_arrows"))
        self.chk_arrows.setToolTip(self._t("show_arrows_tip"))
        self.chk_lock_iso.setText(self._t("lock_iso"))
        self.chk_lock_iso.setToolTip(self._t("lock_iso_tip"))
        self.btn_save_png.setText(self._t("save_png"))
        self.btn_save_cube.setText(self._t("save_cube"))
        self.btn_open_canvas.setText(self._t("open_canvas"))
        self._refresh_structure_label()
        self._refresh_input_labels()
        self._refresh_editor_info()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 右侧这一块本身是两页签：设置/计算（工作流）与 AICD 效果图。
        # 这样效果图不用再占一个左侧导航项——就在这里切一下即可。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.subtabs = QTabWidget()
        self.subtabs.setDocumentMode(True)
        outer.addWidget(self.subtabs)

        # ── 页 1：工作流（内容较高，自己可滚动） ──
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.subtabs.addTab(scroll, "")
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        self.lbl_flow = QLabel()
        self.lbl_flow.setWordWrap(True)
        self.lbl_flow.setStyleSheet("color:#64748B;")
        root.addWidget(self.lbl_flow)

        # ① 结构 + ② 输入文件：一行只放两个主按钮，其余靠编辑器自动补齐
        self.grp_editor = QGroupBox()
        ge = QVBoxLayout(self.grp_editor)
        ge.setContentsMargins(6, 6, 6, 6)
        ge.setSpacing(4)
        bar = QHBoxLayout()
        self.btn_load_gjf = QPushButton()
        self.btn_load_gjf.clicked.connect(self._load_gjf_into_editor)
        self.btn_generator = QPushButton()
        self.btn_generator.clicked.connect(self._open_generator_from_editor)
        # 下面两个保留对象（旧代码/语言切换还会引用），但不再占主流程按钮位
        self.btn_from_canvas = QPushButton()
        self.btn_from_canvas.clicked.connect(self._generate_from_canvas)
        self.btn_from_canvas.setVisible(False)
        self.btn_save_editor = QPushButton()
        self.btn_save_editor.clicked.connect(self._save_editor)
        self.btn_save_editor.setVisible(False)
        bar.addWidget(self.btn_load_gjf)
        bar.addWidget(self.btn_generator)
        bar.addStretch(1)
        ge.addLayout(bar)
        self.lbl_structure = QLabel()
        self.lbl_structure.setWordWrap(True)
        self.lbl_structure.setStyleSheet("color:#64748B;")
        ge.addWidget(self.lbl_structure)

        # 计算范围：全部 / 只看 π / 只看 σ / 输入里已有的指定轨道
        scope_row = QHBoxLayout()
        self.lbl_scope = QLabel()
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItems(["", "", "", ""])
        self.cmb_scope.currentIndexChanged.connect(self._on_scope_changed)
        self.btn_detect_orb = QPushButton()
        self.btn_detect_orb.clicked.connect(self._detect_orbitals_now)
        self.btn_detect_orb.setFlat(True)
        self.btn_detect_orb.setStyleSheet(
            "QPushButton{color:#0369A1;border:none;padding:0 4px;}"
            "QPushButton:hover{color:#0F172A;}")
        scope_row.addWidget(self.lbl_scope)
        scope_row.addWidget(self.cmb_scope)
        scope_row.addWidget(self.btn_detect_orb)
        scope_row.addStretch(1)
        ge.addLayout(scope_row)
        self.lbl_scope_info = QLabel()
        self.lbl_scope_info.setWordWrap(True)
        self.lbl_scope_info.setStyleSheet("color:#64748B;")
        ge.addWidget(self.lbl_scope_info)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "%chk=...\n# b3lyp/6-31g(d) nmr=csgt iop(10/93=1)\n\n"
            "title\n\n0 1\n C ...\n\ntest.txt")
        self.editor.setMinimumHeight(190)
        self.editor.setTabChangesFocus(False)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        f = self.editor.font()
        f.setFamily("Consolas")
        f.setPointSize(max(9, f.pointSize()))
        self.editor.setFont(f)
        self.editor.textChanged.connect(self._refresh_editor_info)
        ge.addWidget(self.editor, 1)
        self.lbl_editor_info = QLabel()
        self.lbl_editor_info.setWordWrap(True)
        self.lbl_editor_info.setStyleSheet("color:#475569;")
        ge.addWidget(self.lbl_editor_info)
        self.lbl_editor_hint = QLabel()
        self.lbl_editor_hint.setWordWrap(True)
        self.lbl_editor_hint.setStyleSheet("color:#94A3B8;")
        ge.addWidget(self.lbl_editor_hint)
        root.addWidget(self.grp_editor, 1)

        # ③ 运行：本地 / 服务器，两个按钮，算完自动出图
        self.grp_actions = QGroupBox()
        ga = QVBoxLayout(self.grp_actions)
        ga.setContentsMargins(8, 8, 8, 8)
        ga.setSpacing(4)
        act = QHBoxLayout()
        self.btn_run_gauss = QPushButton()
        self.btn_run_gauss.clicked.connect(self._run_gaussian)
        self.btn_server = QPushButton()
        self.btn_server.clicked.connect(self._server_run)
        self.btn_cancel_gauss = QPushButton()
        self.btn_cancel_gauss.clicked.connect(self._cancel_gaussian)
        self.btn_cancel_gauss.setEnabled(False)
        self.btn_cancel = QPushButton()
        self.btn_cancel.clicked.connect(self._cancel_any)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)         # 只在跑任务时出现
        for b in (self.btn_run_gauss, self.btn_server, self.btn_cancel):
            act.addWidget(b)
        self.btn_cancel_gauss.setVisible(False)   # 合并成一个"取消"（谁在跑就取消谁）
        act.addStretch(1)
        ga.addLayout(act)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color:#64748B;")
        ga.addWidget(self.lbl_status)
        root.addWidget(self.grp_actions)

        # ④ 结果：本地算完自动出图；服务器算完从这里载入 .log
        self.grp_result = QGroupBox()
        gr = QVBoxLayout(self.grp_result)
        gr.setContentsMargins(8, 8, 8, 8)
        gr.setSpacing(4)
        self.btn_run = QPushButton()
        self.btn_run.clicked.connect(self._load_result_and_run)
        gr.addWidget(self.btn_run)
        self.lbl_data = QLabel()
        self.lbl_data.setWordWrap(True)
        self.lbl_data.setStyleSheet("color:#94A3B8;")
        gr.addWidget(self.lbl_data)
        root.addWidget(self.grp_result)

        # 高级设置开关放到最下面，不打断主流程（做成扁平链接样式）
        self.btn_advanced = QPushButton()
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        self.btn_advanced.setFlat(True)
        self.btn_advanced.setStyleSheet(
            "QPushButton{text-align:left;color:#475569;border:none;padding:2px 0;}"
            "QPushButton:hover{color:#0F172A;}")
        root.addWidget(self.btn_advanced)

        # ── 高级设置（默认收起）：数据来源 / 计算选项 / 出图参数 / 导出 ──
        self.grp_advanced = QGroupBox()
        gadv = QVBoxLayout(self.grp_advanced)
        gadv.setContentsMargins(2, 2, 2, 2)
        gadv.setSpacing(6)

        # 本机计算选项
        self.grp_run = QGroupBox()
        gq = QGridLayout(self.grp_run)
        gq.setContentsMargins(8, 8, 8, 8)
        gq.setHorizontalSpacing(6)
        gq.setVerticalSpacing(4)
        self.lbl_gjf = QLabel()
        self.edit_gjf = QLineEdit()
        self.edit_gjf.setReadOnly(True)
        self.btn_pick_gjf = QPushButton()
        self.btn_pick_gjf.clicked.connect(self._pick_gjf)
        gq.addWidget(self.lbl_gjf, 0, 0)
        gq.addWidget(self.edit_gjf, 0, 1, 1, 2)
        gq.addWidget(self.btn_pick_gjf, 0, 3)
        self.chk_auto_pi = QCheckBox()
        self.chk_auto_pi.setChecked(False)
        gq.addWidget(self.chk_auto_pi, 1, 0, 1, 4)
        self.lbl_pi = QLabel()
        self.btn_write_pi = QPushButton()
        self.btn_write_pi.clicked.connect(lambda: self._write_orbitals("π"))
        self.btn_write_sigma = QPushButton()
        self.btn_write_sigma.clicked.connect(lambda: self._write_orbitals("σ"))
        gq.addWidget(self.lbl_pi, 2, 0, 1, 2)
        gq.addWidget(self.btn_write_pi, 2, 2)
        gq.addWidget(self.btn_write_sigma, 2, 3)
        self.lbl_run_hint = QLabel()
        self.lbl_run_hint.setWordWrap(True)
        self.lbl_run_hint.setStyleSheet("color:#64748B;")
        gq.addWidget(self.lbl_run_hint, 3, 0, 1, 4)
        gq.setColumnStretch(1, 1)
        gadv.addWidget(self.grp_run)

        # 分析数据来源（算完自动接上；也可手动指定）
        self.grp_input = QGroupBox()
        gi = QGridLayout(self.grp_input)
        gi.setContentsMargins(8, 8, 8, 8)
        gi.setHorizontalSpacing(6)
        gi.setVerticalSpacing(4)
        self.lbl_log = QLabel()
        self.edit_log = QLineEdit()
        self.edit_log.setReadOnly(True)
        self.btn_pick_log = QPushButton()
        self.btn_pick_log.clicked.connect(self._pick_log)
        gi.addWidget(self.lbl_log, 0, 0)
        gi.addWidget(self.edit_log, 0, 1)
        gi.addWidget(self.btn_pick_log, 0, 2)
        self.lbl_tensor = QLabel()
        self.lbl_tensor_info = QLabel("")
        self.lbl_tensor_info.setWordWrap(True)
        self.lbl_tensor_info.setStyleSheet("color:#64748B;")
        self.btn_pick_tensor = QPushButton()
        self.btn_pick_tensor.clicked.connect(self._pick_tensor)
        gi.addWidget(self.lbl_tensor, 1, 0)
        gi.addWidget(self.lbl_tensor_info, 1, 1)
        gi.addWidget(self.btn_pick_tensor, 1, 2)
        self.btn_gen_input = QPushButton()
        self.btn_gen_input.clicked.connect(self._generate_input)
        self.btn_gen_input.setVisible(False)   # 主流程的「生成输入…」在顶部
        gi.addWidget(self.btn_gen_input, 3, 0, 1, 3)
        self.btn_replot = QPushButton()
        self.btn_replot.clicked.connect(lambda: self._run())
        self.btn_replot.setEnabled(False)
        gi.addWidget(self.btn_replot, 2, 0, 1, 3)
        gi.setColumnStretch(1, 1)
        gadv.addWidget(self.grp_input)

        # 出图参数
        self.grp_params = QGroupBox()
        gp = QGridLayout(self.grp_params)
        gp.setContentsMargins(8, 8, 8, 8)
        gp.setHorizontalSpacing(6)
        gp.setVerticalSpacing(4)

        self.lbl_quantity = QLabel()
        self.cmb_quantity = QComboBox()
        self.cmb_quantity.addItems(list(A.QUANTITIES))
        gp.addWidget(self.lbl_quantity, 0, 0)
        gp.addWidget(self.cmb_quantity, 0, 1)

        self.lbl_field = QLabel()
        self.cmb_field = QComboBox()
        self.cmb_field.addItems([f[0] for f in _FIELDS])
        gp.addWidget(self.lbl_field, 0, 2)
        gp.addWidget(self.cmb_field, 0, 3)

        self.lbl_iso = QLabel()
        self.spn_iso = QDoubleSpinBox()
        self.spn_iso.setDecimals(4)
        self.spn_iso.setRange(0.0005, 2.0)
        self.spn_iso.setSingleStep(0.005)
        self.spn_iso.setValue(0.05)
        self.spn_iso.valueChanged.connect(self._on_iso_changed)
        gp.addWidget(self.lbl_iso, 1, 0)
        gp.addWidget(self.spn_iso, 1, 1)

        self.lbl_spacing = QLabel()
        self.spn_spacing = QDoubleSpinBox()
        self.spn_spacing.setDecimals(3)
        self.spn_spacing.setRange(0.05, 1.0)
        self.spn_spacing.setSingleStep(0.05)
        self.spn_spacing.setValue(0.15)
        gp.addWidget(self.lbl_spacing, 1, 2)
        gp.addWidget(self.spn_spacing, 1, 3)

        self.lbl_decimate = QLabel()
        self.spn_decimate = QSpinBox()
        self.spn_decimate.setRange(1, 8)
        self.spn_decimate.setValue(2)
        gp.addWidget(self.lbl_decimate, 2, 0)
        gp.addWidget(self.spn_decimate, 2, 1)

        self.lbl_arrow_len = QLabel()
        self.spn_arrow_len = QDoubleSpinBox()
        self.spn_arrow_len.setDecimals(2)
        self.spn_arrow_len.setRange(0.10, 2.0)
        self.spn_arrow_len.setSingleStep(0.05)
        self.spn_arrow_len.setValue(0.50)
        gp.addWidget(self.lbl_arrow_len, 2, 2)
        gp.addWidget(self.spn_arrow_len, 2, 3)

        self.lbl_max_arrow = QLabel()
        self.spn_max_arrow = QDoubleSpinBox()
        self.spn_max_arrow.setDecimals(2)
        self.spn_max_arrow.setRange(0.0, 20.0)
        self.spn_max_arrow.setSingleStep(0.5)
        self.spn_max_arrow.setValue(2.0)
        gp.addWidget(self.lbl_max_arrow, 3, 0)
        gp.addWidget(self.spn_max_arrow, 3, 1)

        self.lbl_smooth = QLabel()
        self.spn_smooth = QDoubleSpinBox()
        self.spn_smooth.setDecimals(2)
        self.spn_smooth.setRange(0.0, 5.0)
        self.spn_smooth.setSingleStep(0.2)
        self.spn_smooth.setValue(1.2)
        self.spn_smooth.valueChanged.connect(self._on_smooth_changed)
        gp.addWidget(self.lbl_smooth, 3, 2)
        gp.addWidget(self.spn_smooth, 3, 3)

        self.lbl_alpha = QLabel()
        self.spn_alpha = QDoubleSpinBox()
        self.spn_alpha.setDecimals(2)
        self.spn_alpha.setRange(0.10, 1.0)
        self.spn_alpha.setSingleStep(0.05)
        self.spn_alpha.setValue(0.90)
        gp.addWidget(self.lbl_alpha, 4, 0)
        gp.addWidget(self.spn_alpha, 4, 1)

        self.lbl_views = QLabel()
        self.cmb_views = QComboBox()
        self.cmb_views.addItems(["", "", ""])
        gp.addWidget(self.lbl_views, 4, 2)
        gp.addWidget(self.cmb_views, 4, 3)

        self.lbl_outdir = QLabel()
        self.edit_outdir = QLineEdit()
        self.btn_outdir = QPushButton()
        self.btn_outdir.clicked.connect(self._pick_outdir)
        gp.addWidget(self.lbl_outdir, 5, 0)
        gp.addWidget(self.edit_outdir, 5, 1, 1, 2)
        gp.addWidget(self.btn_outdir, 5, 3)

        self.chk_cube = QCheckBox()
        self.chk_cube.setChecked(True)
        gp.addWidget(self.chk_cube, 6, 0, 1, 4)

        self.chk_auto_canvas = QCheckBox()
        self.chk_auto_canvas.setChecked(True)
        gp.addWidget(self.chk_auto_canvas, 7, 0, 1, 2)
        self.chk_arrows = QCheckBox()
        self.chk_arrows.setChecked(True)
        self.chk_arrows.setEnabled(False)
        self.chk_arrows.toggled.connect(self._on_arrows_toggled)
        gp.addWidget(self.chk_arrows, 7, 2, 1, 2)
        self.chk_lock_iso = QCheckBox()
        self.chk_lock_iso.setChecked(True)
        self.chk_lock_iso.toggled.connect(self._on_lock_iso_toggled)
        gp.addWidget(self.chk_lock_iso, 8, 0, 1, 4)
        gp.setColumnStretch(1, 1)
        gp.setColumnStretch(3, 1)
        gadv.addWidget(self.grp_params)

        # 导出按钮（放在高级设置里；日常看图在「AICD 效果图」页）
        row = QHBoxLayout()
        self.btn_save_png = QPushButton()
        self.btn_save_png.clicked.connect(self._save_png)
        self.btn_save_cube = QPushButton()
        self.btn_save_cube.clicked.connect(self._save_cube)
        self.btn_open_canvas = QPushButton()
        self.btn_open_canvas.clicked.connect(self._open_on_canvas)
        row.addWidget(self.btn_save_png)
        row.addWidget(self.btn_save_cube)
        row.addWidget(self.btn_open_canvas)
        row.addStretch(1)
        gadv.addLayout(row)
        root.addWidget(self.grp_advanced)
        self.grp_advanced.setVisible(False)      # 默认收起：主流程只走上面 4 步
        for b in (self.btn_save_png, self.btn_save_cube, self.btn_open_canvas):
            b.setEnabled(False)

        # ── 页 2：AICD 效果图（独立查看/缩放/保存；也能打开任意 PNG） ──
        self.figure_view = AicdFigurePanel()
        self.subtabs.addTab(self.figure_view, "")

    # ── 输入 ──────────────────────────────────────────────────────────────
    def _refresh_structure_label(self):
        if self._struct_atoms:
            name = os.path.basename(self._struct_name) if self._struct_name else "-"
            self.lbl_structure.setText(
                self._t("structure_ready", n=len(self._struct_atoms), name=name))
            self.lbl_structure.setStyleSheet("color:#166534;")
        else:
            self.lbl_structure.setText(self._t("structure_none"))
            self.lbl_structure.setStyleSheet("color:#64748B;")

    # ── 计算范围：全部 / π / σ ──────────────────────────────────────────
    def _scope_key(self):
        idx = int(self.cmb_scope.currentIndex())
        if idx < 0 or idx >= len(_SCOPES):
            idx = 0
        return _SCOPES[idx]

    def _on_iso_changed(self, _value):
        if not self._syncing_iso:
            self._iso_auto = False

    def _set_iso_auto(self, value):
        self._syncing_iso = True
        try:
            self.spn_iso.setValue(float(value))
        finally:
            self._syncing_iso = False

    def _on_smooth_changed(self, _value):
        if not self._syncing_smooth:
            self._smooth_auto = False

    def _set_smooth_auto(self, value):
        self._syncing_smooth = True
        try:
            self.spn_smooth.setValue(float(value))
        finally:
            self._syncing_smooth = False

    def _current_scope(self):
        """输入实际是什么范围：all / pi / sigma / orbs（输入里自定义的轨道）。"""
        text = self.editor.toPlainText().replace(" ", "").lower()
        if "iop(10/93=2)" not in text:
            return "all"
        scope = self._scope_key()
        return scope if scope in ("pi", "sigma") else "orbs"

    def _set_scope_combo(self, idx):
        self._syncing_scope = True
        try:
            self.cmb_scope.setCurrentIndex(int(idx))
        finally:
            self._syncing_scope = False
        self._refresh_scope_info()

    def _refresh_scope_info(self):
        if not hasattr(self, "lbl_scope_info"):
            return
        if self._pi_str or self._sigma_str:
            self.lbl_scope_info.setText(self._t(
                "scope_info_ready", pi=self._pi_str or "-",
                sig=self._sigma_str or "-"))
            self.lbl_scope_info.setStyleSheet("color:#166534;")
        else:
            self.lbl_scope_info.setText(self._t("scope_info_none"))
            self.lbl_scope_info.setStyleSheet("color:#64748B;")

    def _scope_path(self, tag):
        """由全电子底稿路径派生 <base>_pi.gjf / <base>_sigma.gjf。"""
        base = self._base_gjf_path or self._gjf_path
        if not base:
            return ""
        folder, name = os.path.split(base)
        stem, ext = os.path.splitext(name)
        for suffix in ("_pi", "_sigma"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        if tag:
            stem += "_" + str(tag)
        return os.path.join(folder, stem + ext) if folder else stem + ext

    def _reset_result_for_scope(self):
        self._log_path = ""
        self._tensor_path = ""
        self.edit_log.clear()
        self._refresh_input_labels()

    def _remember_base_input(self, text, path):
        """记住全电子底稿；若载入的本身就是 iop=2，也留一份全电子版本。"""
        # 换体系：旧的 π/σ 轨道号不能带过去（否则会拿上一分子的轨道改写新输入）
        self._pi_str = ""
        self._sigma_str = ""
        self._pi_cubes = []
        self._refresh_pi_label()
        text = str(text or "")
        self._base_input_text = text
        self._base_gjf_path = path or ""
        low = text.replace(" ", "").lower()
        is_orbs = "iop(10/93=2)" in low
        if is_orbs:
            try:
                from molstudio.panels.aicd_input import rewrite_with_orbitals
                self._base_input_text = rewrite_with_orbitals(
                    text, "", mode="all", name_tag="")
            except Exception:                            # noqa: BLE001
                pass
        self._set_scope_combo(3 if is_orbs else 0)

    def _apply_scope_all(self):
        if not self.editor.toPlainText().strip():
            self._refresh_scope_info()
            return
        base = self._base_input_text or self.editor.toPlainText()
        if not self._base_input_text and "iop(10/93=2)" in base.replace(
                " ", "").lower():
            try:
                from molstudio.panels.aicd_input import rewrite_with_orbitals
                base = rewrite_with_orbitals(base, "", mode="all", name_tag="")
            except Exception:                            # noqa: BLE001
                pass
        self.editor.setPlainText(base)
        self._gjf_path = self._scope_path("")
        self.edit_gjf.setText(self._gjf_path)
        if self._iso_auto:
            self._set_iso_auto(0.05)
        if self._smooth_auto:
            self._set_smooth_auto(1.2)
        self._reset_result_for_scope()
        self.lbl_status.setText(self._t("scope_all_applied"))
        self._refresh_scope_info()
        self._refresh_editor_info()

    def _apply_scope_orbitals(self, scope):
        orbs = self._pi_str if scope == "pi" else self._sigma_str
        if not orbs:
            return False
        base = self._base_input_text or self.editor.toPlainText()
        tag = "pi" if scope == "pi" else "sigma"
        try:
            from molstudio.panels.aicd_input import rewrite_with_orbitals
            new = rewrite_with_orbitals(base, orbs, mode="orbs", name_tag=tag)
        except Exception as exc:                        # noqa: BLE001
            QMessageBox.warning(self, self._t("grp_editor"),
                                self._t("scope_switch_fail", err=str(exc)))
            self._set_scope_combo(0)
            return False
        self.editor.setPlainText(new)
        self._gjf_path = self._scope_path(tag)
        self.edit_gjf.setText(self._gjf_path)
        # π/σ 的电流密度比全电子弱，0.05 容易在五元环顶部断开；
        # 用户没手动改过 iso 时，默认降到 0.04 让它保持连续（可再手动改回）。
        if self._iso_auto:
            self._set_iso_auto(0.04)
        # AICD 的 -s 只磨圆三角面，不做场平滑；模块的高斯场平滑会让 π 带变瘦、
        # 六元环的颈部凹口更深。π/σ 默认关掉它，画出来才是连成一片的粗环。
        if self._smooth_auto:
            self._set_smooth_auto(0.0)
        self._reset_result_for_scope()
        key = "scope_pi_applied" if scope == "pi" else "scope_sigma_applied"
        self.lbl_status.setText(self._t(key, orbs=orbs))
        self._refresh_scope_info()
        self._refresh_editor_info()
        return True

    def _on_scope_changed(self, idx):
        if self._syncing_scope:
            return
        scope = self._scope_key()
        if scope == "all":
            self._apply_scope_all()
        elif scope in ("pi", "sigma"):
            self._start_scope_detection(scope)
        else:
            self.lbl_status.setText(self._t("scope_custom_applied"))

    @staticmethod
    def _fchk_natoms(path):
        """读 fchk 的原子数（用于检查主界面 fchk 是不是当前体系）。"""
        try:
            with open(path, "r", errors="replace") as fh:
                for line in fh:
                    if "Number of atoms" in line:
                        return int(line.split()[-1])
        except (OSError, ValueError):
            pass
        return 0

    def _find_fchk_for_orbitals(self):
        # 优先用本面板自己最近一次任务留下的 .chk（最可能是当前体系），
        # 其次主界面打开的 fchk，最后才猜同目录的 .chk。
        chk = self._last_chk
        if not chk and self._log_path:
            chk = GR.find_chk_file(self._log_path)
        if chk and os.path.isfile(chk):
            try:
                return GR.chk_to_fchk(chk)
            except Exception as exc:                    # noqa: BLE001
                self._log("[AICD] chk→fchk 失败：%s" % exc)
        fchk = str(self._get_fchk() or "")
        if fchk and os.path.isfile(fchk):
            return fchk
        if self._gjf_path:
            cand = os.path.splitext(self._gjf_path)[0] + ".chk"
            if os.path.isfile(cand):
                try:
                    return GR.chk_to_fchk(cand)
                except Exception as exc:                # noqa: BLE001
                    self._log("[AICD] chk→fchk 失败：%s" % exc)
        return ""

    def _set_scope_busy(self, busy):
        for b in (self.btn_run_gauss, self.btn_server, self.btn_run,
                  self.btn_load_gjf, self.btn_generator, self.btn_detect_orb):
            b.setEnabled(not busy)
        self.cmb_scope.setEnabled(not busy)
        self.grp_input.setEnabled(not busy)
        self.grp_run.setEnabled(not busy)
        if busy:
            self.lbl_status.setText(self._t("detect_running"))

    def _start_scope_detection(self, after_scope):
        if self._scope_worker is not None:
            return
        if not self.editor.toPlainText().strip():
            QMessageBox.information(self, self._t("grp_editor"),
                                    self._t("editor_missing"))
            self._set_scope_combo(0)
            return
        if self._pi_str and self._sigma_str:
            if after_scope in ("pi", "sigma"):
                self._apply_scope_orbitals(after_scope)
            else:
                self._refresh_scope_info()
            return
        fchk = self._find_fchk_for_orbitals()
        if not fchk:
            QMessageBox.information(self, self._t("grp_editor"),
                                    self._t("detect_need_fchk"))
            self._set_scope_combo(0)
            return
        n_fchk = self._fchk_natoms(fchk)
        n_struct = len(self._struct_atoms)
        if n_fchk and n_struct and n_fchk != n_struct:
            ret = QMessageBox.question(
                self, self._t("fchk_mismatch_title"),
                self._t("fchk_mismatch_msg", n_fchk=n_fchk, n_struct=n_struct),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                self._set_scope_combo(0)
                return
        mw = str(self._get_mw() or "")
        if not mw or not os.path.isfile(mw):
            QMessageBox.information(self, self._t("grp_editor"),
                                    self._t("detect_need_mw"))
            self._set_scope_combo(0)
            return
        planar = True
        if self._struct_atoms:
            try:
                planar = bool(A.guess_plane_normal(self._struct_atoms)["planar"])
            except Exception:                            # noqa: BLE001
                planar = True
        self._log("[AICD] 检测 π/σ 轨道：%s（%s）"
                  % (os.path.basename(fchk),
                     "平面法" if planar else "LMO 投影"))
        self._set_scope_busy(True)
        self._scope_worker = _ScopeWorker(fchk, mw, planar=planar, parent=self)
        self._scope_worker.log.connect(lambda m: self._log("[π] " + str(m)))
        self._scope_worker.done.connect(
            lambda info: self._on_scope_detected(info, after_scope))
        self._scope_worker.finished.connect(
            lambda: self._set_scope_busy(False))
        self._scope_worker.start()

    def _on_scope_detected(self, info, after_scope):
        self._scope_worker = None
        if not info.get("ok"):
            msg = self._t("detect_fail", err=info.get("error", ""))
            self._log("[AICD] " + msg)
            self.lbl_status.setText(msg)
            QMessageBox.warning(self, self._t("grp_editor"), msg)
            if after_scope in ("pi", "sigma"):
                self._set_scope_combo(0)
            return
        res = info.get("info") or {}
        self._pi_str = res.get("pi_occupied_str", "") or ""
        self._sigma_str = res.get("sigma_occupied_str", "") or ""
        self._refresh_pi_label()
        self._refresh_scope_info()
        self._log("[AICD] π/σ 轨道：π %s；σ %s"
                  % (self._pi_str or "-", self._sigma_str or "-"))
        if after_scope in ("pi", "sigma"):
            if not self._apply_scope_orbitals(after_scope):
                QMessageBox.information(
                    self, self._t("grp_editor"),
                    self._t("detect_fail", err="没有检测到可用的轨道"))
                self._set_scope_combo(0)
        else:
            self.lbl_status.setText(self._t(
                "scope_info_ready", pi=self._pi_str or "-",
                sig=self._sigma_str or "-"))

    def _detect_orbitals_now(self):
        scope = self._scope_key()
        self._start_scope_detection(scope if scope in ("pi", "sigma") else None)

    def _refresh_input_labels(self):
        if hasattr(self, "btn_replot"):
            self.btn_replot.setEnabled(bool(
                self._log_path and self._tensor_path
                and os.path.isfile(self._tensor_path)))
        if not self._log_path:
            self.lbl_tensor_info.setText("")
            self.lbl_tensor_info.setStyleSheet("color:#64748B;")
            if hasattr(self, "lbl_data"):
                self.lbl_data.setText(self._t("result_none"))
            return
        if self._tensor_path and os.path.isfile(self._tensor_path):
            self.lbl_tensor_info.setText(
                self._t("tensor_auto", name=os.path.basename(self._tensor_path)))
            self.lbl_tensor_info.setStyleSheet("color:#166534;")
            if hasattr(self, "lbl_data"):
                self.lbl_data.setText(self._t(
                    "result_ready", log=os.path.basename(self._log_path),
                    tensor=os.path.basename(self._tensor_path)))
        else:
            self.lbl_tensor_info.setText(self._t("tensor_missing"))
            self.lbl_tensor_info.setStyleSheet("color:#B91C1C;")
            if hasattr(self, "lbl_data"):
                self.lbl_data.setText(self._t("tensor_missing"))

    # ── 结构：解析 / 送画布 ───────────────────────────────────────────────
    def _atoms_from_text(self, text):
        """从 gjf 文本里读 [(符号, x, y, z)] Å；读不到返回 []。"""
        try:
            from molstudio.panels.aicd_input import parse_gjf_settings_text
            info = parse_gjf_settings_text(text)
        except Exception:                                  # noqa: BLE001
            return []
        return list(info.get("atoms") or [])

    def _show_on_canvas(self, atoms):
        """把结构画到主画布上（球棍模型），失败只记日志、不打断流程。"""
        glw = self.glw
        if not atoms or glw is None or not hasattr(glw, "set_molecule"):
            return
        try:
            packed = []
            for i, a in enumerate(atoms):
                sym = A.element_symbol(int(a[0])) if isinstance(a[0], (int, float)) \
                    else A.element_symbol(A.element_number(a[0]))
                packed.append((i + 1, sym, A.element_number(a[0]),
                               (float(a[1]), float(a[2]), float(a[3]))))
            glw.set_molecule(packed)
            if hasattr(glw, "frame_to_molecule"):
                glw.frame_to_molecule()
            self._log("[AICD] 已在画布显示结构（%d 个原子）" % len(packed))
        except Exception as exc:                           # noqa: BLE001
            self._log("[AICD] 画布显示结构失败：%s" % exc)

    def _set_structure(self, atoms, name=""):
        """登记当前结构：更新标签 + 画布。atoms 可为 (符号/序号, x, y, z)。"""
        self._struct_atoms = list(atoms or [])
        self._struct_name = name or self._struct_name
        self._show_on_canvas(self._struct_atoms)
        self._refresh_structure_label()

    def _pick_log(self):
        start = os.path.dirname(self._log_path) or self._outdir or ""
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("pick_log"), start,
            "Gaussian output (*.log *.out);;All files (*)")
        if not path:
            return
        self._log_path = path
        self.edit_log.setText(path)
        if not self._outdir:
            self._outdir = os.path.dirname(path)
            self.edit_outdir.setText(self._outdir)
        self._tensor_path = A.find_tensor_file(path) or ""
        self._refresh_input_labels()
        self._auto_pick_field()
        atoms = A.read_standard_orientation(path)
        if atoms:
            self._set_structure([(A.element_symbol(z), x, y, zz)
                                 for z, x, y, zz in atoms], path)
        if not self._tensor_path:
            self.lbl_status.setText(self._t("no_tensor"))

    @staticmethod
    def _log_scope(path):
        """从 log 开头判断任务是不是 iop(10/93=2)（轨道分解）。"""
        try:
            with open(path, "r", errors="replace") as fh:
                head = fh.read(20000)
        except OSError:
            return ""
        return "orbs" if "iop(10/93=2)" in head.replace(" ", "").lower() else ""

    def _load_result_and_run(self):
        """服务器算完的主入口：选 .log → 自动找张量 txt → 直接分析出图。"""
        start = os.path.dirname(self._log_path or self._gjf_path
                                or self._outdir or "")
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("pick_log"), start,
            "Gaussian output (*.log *.out);;All files (*)")
        if not path:
            return
        self._log_path = path
        self.edit_log.setText(path)
        self._last_chk = ""          # 服务器结果：不要拿上一分子的 chk 去检测
        # 结果默认就写在这个 .log 旁边（用户可在高级里改）
        self._outdir = os.path.dirname(path)
        self.edit_outdir.setText(self._outdir)
        self._tensor_path = A.find_tensor_file(path) or ""
        if not self._tensor_path:
            # 任务没跑到 NMR / 文件被改名：让用户手动指一下，别直接放弃
            ret = QMessageBox.question(
                self, self._t("tensor_pick_title"), self._t("tensor_pick_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                tpath, _ = QFileDialog.getOpenFileName(
                    self, self._t("pick_tensor"), os.path.dirname(path),
                    "Tensor dump (*.txt);;All files (*)")
                if tpath:
                    self._tensor_path = tpath
        if not self._tensor_path:
            self._refresh_input_labels()
            self.lbl_status.setText(self._t("no_tensor"))
            return
        self._auto_pick_field()
        atoms = A.read_standard_orientation(path)
        if atoms:
            self._set_structure([(A.element_symbol(z), x, y, zz)
                                 for z, x, y, zz in atoms], path)
        self._refresh_input_labels()
        self._log("[AICD] 载入结果：%s" % path)
        # 结果图上的范围标签：iop=2 时优先沿用当前下拉的 π/σ，否则标"指定轨道"
        loaded = self._log_scope(path)
        if loaded == "orbs":
            scope = self._current_scope()
            scope = scope if scope in ("pi", "sigma", "orbs") else "orbs"
            if self._iso_auto:
                self._set_iso_auto(0.04)
            if self._smooth_auto:
                self._set_smooth_auto(0.0)
        else:
            scope = "all"
            if self._iso_auto:
                self._set_iso_auto(0.05)
            if self._smooth_auto:
                self._set_smooth_auto(1.2)
        self._run(scope_override=scope)

    def _auto_pick_field(self):
        """按 log 里标准取向的分子平面，自动把磁场方向选成垂直环平面的那个轴。

        计算本身与分子怎么摆无关（Gaussian 会自己转到标准取向，AICD 张量也在
        那个坐标系里），但"磁场方向"是相对标准取向说的，用户没法凭画布判断，
        所以这里直接按最小二乘平面把 ``-b`` 预选好。

        优先级（配合物尤其重要）：
          1. 画布上选中的原子（用户明确指定了要考察哪几个原子）；
          2. 整个分子若共平面 → 用整体平面；
          3. 整体不共平面 → 自动找小环，取"最平的环"的法向（如苯环 + 金属/
             取代基的配合物）；
          4. 都判不出来 → 保留 +z 并提示自行确认。
        """
        if not self._log_path or not os.path.isfile(self._log_path):
            return
        try:
            atoms = A.read_standard_orientation(self._log_path)
        except Exception as exc:                            # noqa: BLE001
            self._log("[AICD] 判定分子平面失败：%s" % exc)
            return
        if not atoms:
            return

        info = None
        # 1) 画布选中的原子（索引按标准取向的原子顺序对应）
        selected = []
        glw = self.glw
        if glw is not None:
            try:
                selected = [i for i in list(glw._selected_atoms)
                            if 0 <= int(i) < len(atoms)]
            except Exception:                               # noqa: BLE001
                selected = []
        if len(selected) >= 3:
            info = A.guess_plane_normal([atoms[i] for i in selected])
            info["_kind"] = "selection"
            info["_n_sel"] = len(selected)
        else:
            whole = A.guess_plane_normal(atoms)
            if whole["planar"]:
                info = whole
                info["_kind"] = "whole"
            else:
                rings = A.planar_rings(atoms)
                if rings:
                    ring = dict(rings[0])
                    ring["planar"] = True
                    ring["_kind"] = "ring"
                    ring["_whole_rms"] = whole["rms"]
                    info = ring
                else:
                    whole["_kind"] = "none"
                    info = whole

        # 下拉顺序：+z −z +x −x +y −y（见 _FIELDS）
        index = {0: 2, 1: 4, 2: 0}[int(info["axis"])] + (0 if info["sign"] > 0 else 1)
        self.cmb_field.setCurrentIndex(index)
        label = _FIELDS[index][0]
        kind = info.get("_kind")
        if kind == "selection":
            msg = self._t("field_auto_selection", n=info.get("_n_sel", 0),
                          dir=label, rms=info["rms"])
        elif kind == "ring":
            elements = [A.element_symbol(int(atoms[i][0])) + str(i + 1)
                        for i in info["atoms"]]
            msg = self._t("field_auto_ring", rms=info.get("_whole_rms", 0.0),
                          dir=label, size=info["size"],
                          ring_rms=info["rms"], atoms=",".join(elements))
        elif kind == "whole" and info["planar"]:
            msg = self._t("field_auto", dir=label, rms=info["rms"])
        else:
            msg = self._t("field_auto_nonplanar", dir=label, rms=info["rms"])
        self.lbl_status.setText(msg)
        self._log("[AICD] " + msg)

    def _pick_tensor(self):
        start = os.path.dirname(self._tensor_path or self._log_path) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("pick_tensor"), start,
            "Tensor dump (*.txt);;All files (*)")
        if path:
            self._tensor_path = path
            self._refresh_input_labels()
            self._auto_pick_field()

    def _pick_outdir(self):
        path = QFileDialog.getExistingDirectory(
            self, self._t("outdir"), self._outdir or "")
        if path:
            self._outdir = path
            self.edit_outdir.setText(path)

    def _server_run(self):
        """服务器运行：把当前输入落盘，给出可复制的运行命令。

        不直接连服务器（项目里没有 SSH 依赖）——只负责准备输入和命令；
        算完把 .log + 张量 txt 拿回来，用「载入结果并出图」接上。
        """
        gjf = self._sync_editor_to_file(ask=True)
        if not gjf or not os.path.isfile(gjf):
            return
        # 这是新一轮任务：先摘掉上一轮的结果标签，避免误以为已经算过
        self._log_path = ""
        self._tensor_path = ""
        self.edit_log.clear()
        self._refresh_input_labels()
        info = {}
        try:
            from molstudio.panels.aicd_input import parse_gjf_settings_text
            info = parse_gjf_settings_text(self.editor.toPlainText())
        except Exception:                                  # noqa: BLE001
            pass
        tensor = info.get("tensor") or "test.txt"
        base = os.path.splitext(os.path.basename(gjf))[0]
        cmd = 'g16 < "%s" > "%s.log"' % (os.path.basename(gjf), base)
        folder = os.path.dirname(gjf) or self._outdir

        dlg = QDialog(self)
        dlg.setWindowTitle(self._t("server_title"))
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(14, 14, 14, 10)
        lay.setSpacing(8)

        lbl_path = QLabel(self._t("server_saved", path=gjf))
        lbl_path.setWordWrap(True)
        lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lbl_path)

        lay.addWidget(QLabel(self._t("server_cmd_hint")))
        edit_cmd = QLineEdit(cmd)
        edit_cmd.setReadOnly(True)
        edit_cmd.setCursorPosition(0)
        edit_cmd.setMinimumHeight(30)
        lay.addWidget(edit_cmd)

        lbl_back = QLabel(self._t("server_bring_back", tensor=tensor))
        lbl_back.setWordWrap(True)
        lbl_back.setStyleSheet("color:#475569;")
        lay.addWidget(lbl_back)

        lbl_note = QLabel(self._t("server_note"))
        lbl_note.setWordWrap(True)
        lbl_note.setStyleSheet("color:#94A3B8;")
        lay.addWidget(lbl_note)

        row = QHBoxLayout()
        btn_copy = QPushButton(self._t("copy_cmd"))
        btn_copy_path = QPushButton(self._t("copy_path"))
        btn_open = QPushButton(self._t("open_folder"))
        btn_close = QPushButton(self._t("close"))
        lbl_copied = QLabel("")
        lbl_copied.setStyleSheet("color:#166534;")
        row.addWidget(btn_copy)
        row.addWidget(btn_copy_path)
        row.addWidget(btn_open)
        row.addWidget(btn_close)
        row.addWidget(lbl_copied, 1)
        lay.addLayout(row)

        def _copy(text):
            QApplication.clipboard().setText(text)
            lbl_copied.setText(self._t("copied"))

        btn_copy.clicked.connect(lambda: _copy(cmd))
        btn_copy_path.clicked.connect(lambda: _copy(gjf))
        btn_close.clicked.connect(dlg.accept)

        def _open_folder():
            try:
                os.startfile(folder)                       # Windows
            except Exception:                              # noqa: BLE001
                QMessageBox.information(dlg, self._t("server_title"), folder)
        btn_open.clicked.connect(_open_folder)

        dlg.exec_()
        self._log("[AICD] 服务器输入已导出：%s" % gjf)
        self.lbl_status.setText(self._t("server_exported", path=gjf))
        self._refresh_input_labels()

    def _generate_input(self):
        """打开 Gaussian 输入生成器（结构默认取画布上的分子）。"""
        self._open_generator()

    def _open_generator(self, gjf_path=None):
        """打开输入生成器：结构/设置默认取画布上的分子，也可以从已有 gjf 预填。

        这是本页的主流程——**载入 gjf → 生成器里确认关键字 → 保存 → 运行**：
        生成器负责把 ``nmr=csgt iop(10/93=…)`` 这些必需关键字、张量文件名、
        轨道编号都写对，用户只需要确认。
        """
        from molstudio.panels.aicd_input import AicdInputDialog

        base = ""
        if gjf_path:
            base = os.path.splitext(os.path.basename(gjf_path))[0]
        elif self._gjf_path:
            base = os.path.splitext(os.path.basename(self._gjf_path))[0]
        elif self._log_path:
            base = os.path.splitext(os.path.basename(self._log_path))[0]
        base = base or "aicd"
        out_dir = (os.path.dirname(gjf_path) if gjf_path else "") or self._outdir \
            or (os.path.dirname(self._log_path) if self._log_path else "")
        dlg = AicdInputDialog(glw=self.glw, lang=self.lang, out_dir=out_dir,
                              base_name=base, get_fchk=self._get_fchk,
                              get_multiwfn=self._get_mw,
                              on_log=self._append_log, gjf_path=gjf_path,
                              parent=self)
        if dlg.exec_() != dlg.Accepted:
            return
        path = getattr(dlg, "_saved_path", "")
        if not path:
            return
        self._log("[AICD] " + self._t("gen_done", path=path))
        self.lbl_status.setText(self._t("gen_done", path=path))
        # 生成/保存后：把文件内容回填编辑器，并把结构画到画布上
        text = ""
        try:
            with open(path, "r", errors="replace") as fh:
                text = fh.read()
        except OSError:
            pass
        if text:
            self.editor.setPlainText(text)
        self._log_path = ""
        self._tensor_path = ""
        self._last_chk = ""
        self.edit_log.clear()
        self._refresh_input_labels()
        atoms = self._atoms_from_text(text) or list(getattr(dlg, "_atoms", []) or [])
        self._set_structure(atoms, path)
        self._refresh_editor_info()
        # 生成的输入就在旁边跑，顺手把输出目录指过去
        folder = os.path.dirname(path)
        if folder:
            self._outdir = folder
            self.edit_outdir.setText(folder)
        self.set_input_file(path)
        self._remember_base_input(text or self.editor.toPlainText(), path)
        if getattr(dlg, "run_after", False):
            self._run_gaussian()

    # ── 运行 ──────────────────────────────────────────────────────────────
    def _params(self):
        return {
            "quantity": self.cmb_quantity.currentText(),
            "field": _FIELDS[self.cmb_field.currentIndex()][1],
            "iso": float(self.spn_iso.value()),
            "spacing": float(self.spn_spacing.value()),
            "padding": 1.8,
            "decimate": int(self.spn_decimate.value()),
            "arrow_len": float(self.spn_arrow_len.value()),
            "max_arrow": float(self.spn_max_arrow.value()),
            "smooth": float(self.spn_smooth.value()),
            "alpha": float(self.spn_alpha.value()),
            "views": ("montage", "top", "oblique")[self.cmb_views.currentIndex()],
            "write_cube": bool(self.chk_cube.isChecked()),
            "scope": self._current_scope(),
        }

    def _run(self, scope_override=None):
        if not self._log_path:
            QMessageBox.information(self, self._t("grp_view"), self._t("need_log"))
            return
        if not self._tensor_path or not os.path.isfile(self._tensor_path):
            QMessageBox.warning(self, self._t("grp_view"), self._t("no_tensor"))
            return
        if not self._outdir:
            self._outdir = os.path.dirname(self._log_path)
            self.edit_outdir.setText(self._outdir)
        self._set_busy(True)
        self.lbl_status.setText(self._t("busy"))
        # 记下本次出图用的参数：画布箭头/等值面必须跟这张图一致，
        # 不能等用户改了「箭头抽稀」之后画布和已出的图对不上。
        params = self._params()
        if scope_override:
            params["scope"] = str(scope_override)
        self._params_used = dict(params)
        self._worker = AicdWorker(self._log_path, self._tensor_path,
                                  self._outdir, params, parent=self)
        self._worker.log.connect(self._append_log)
        self._worker.log.connect(self.lbl_status.setText)
        self._worker.done.connect(self._on_done)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _append_log(self, msg):
        self._log("[AICD] " + str(msg))

    def _cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.lbl_status.setText(self._t("cancel_done"))

    def _cancel_any(self):
        """一个取消按钮：Gaussian 在跑就取消它，AICD 在跑就取消它。"""
        if self._gauss_worker is not None:
            self._cancel_gaussian()
        if self._worker is not None:
            self._cancel()

    def _set_busy(self, busy):
        for b in (self.btn_run_gauss, self.btn_server, self.btn_run,
                  self.btn_load_gjf, self.btn_generator):
            b.setEnabled(not busy)
        self.btn_cancel.setVisible(busy)
        self.btn_cancel.setEnabled(busy)
        self.cmb_scope.setEnabled(not busy)
        self.btn_detect_orb.setEnabled(not busy)
        self.grp_params.setEnabled(not busy)
        self.grp_input.setEnabled(not busy)
        self.grp_run.setEnabled(not busy)
        has = bool(self._png)
        for b in (self.btn_save_png, self.btn_open_canvas):
            b.setEnabled(not busy and has)
        self.btn_save_cube.setEnabled(not busy and bool(self._cube))

    def _toggle_advanced(self, on):
        """展开/收起高级设置（默认收起，主流程只留 5 个按钮）。"""
        self.grp_advanced.setVisible(bool(on))
        self.btn_advanced.setText(
            self._t("btn_advanced_open" if on else "btn_advanced"))

    def _on_done(self, info):
        self._worker = None
        if info.get("cancelled"):
            self.lbl_status.setText(self._t("cancel_done"))
            return
        if not info.get("ok"):
            self.lbl_status.setText(self._t("failed", err=info.get("error", "")))
            if info.get("trace"):
                self._log(info["trace"])
            return
        self._png = info.get("png", "")
        self._cube = info.get("cube", "")
        self._vol = info.get("volume")
        # 换了结果就把画布上旧的箭头清掉，免得和新的对不上
        self._clear_canvas_arrows()
        self.lbl_status.setText(self._t(
            "done", n=info.get("n_grid", 0), na=info.get("n_arrow", 0),
            lo=info.get("lo", 0.0), hi=info.get("hi", 0.0),
            t=info.get("seconds", 0.0)))
        # 图送到独立的「AICD 效果图」页（主窗口负责切过去）
        scope = info.get("scope", "all")
        scope_label = self._t({
            "pi": "scope_short_pi", "sigma": "scope_short_sigma",
            "orbs": "scope_short_orbs"}.get(scope, "scope_short_all"))
        summary = "%s · %s · B=%s · iso %.3f · %d arrows" % (
            info.get("quantity", self.cmb_quantity.currentText()),
            scope_label,
            info.get("field_text", self.cmb_field.currentText()),
            float(info.get("iso", self.spn_iso.value())),
            int(info.get("n_arrow", 0)))
        # 直接显示在本页右侧的「AICD 效果图」子页签里
        if getattr(self, "figure_view", None) is not None:
            if self.figure_view.set_figure(self._png, summary):
                self.subtabs.setCurrentWidget(self.figure_view)
        self.figureReady.emit(self._png, summary)
        if self._cube:
            self._log(self._t("cube_done", path=self._cube))
        if self.chk_auto_canvas.isChecked():
            self._open_on_canvas()

    # ── 导出（图的浏览/保存已移到独立的「AICD 效果图」页） ──────────────
    def _save_png(self):
        if not self._png or not os.path.isfile(self._png):
            QMessageBox.information(self, self._t("grp_view"), self._t("no_result"))
            return
        default = os.path.join(self._outdir or "", os.path.basename(self._png))
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save_png"), default, "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            shutil.copyfile(self._png, path)
            self.lbl_status.setText(self._t("saved", path=path))
        except OSError:
            self.lbl_status.setText(self._t("failed", err=path))

    def _save_cube(self):
        if not self._cube or not os.path.isfile(self._cube):
            QMessageBox.information(self, self._t("grp_view"), self._t("no_cube"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save_cube"), self._cube, "Cube file (*.cub)")
        if not path:
            return
        if not path.lower().endswith(".cub"):
            path += ".cub"
        try:
            shutil.copyfile(self._cube, path)
            self._cube = path
            self.lbl_status.setText(self._t("cube_done", path=path))
        except OSError as exc:
            self.lbl_status.setText(self._t("failed", err=str(exc)))

    def _open_on_canvas(self):
        """把等值面（cube）+ 感应电流箭头一起送进左侧 OpenGL 画布。

        等值面走画布原有的 cube 通道（透明等值面），箭头走本项目新加的叠加层
        （``CubGLWidget.set_aicd_arrows``，不透明几何、顶点色杆绿头红）。顺带把
        等值面配色设成 AICD 黄，跟参考图一致。
        """
        cube = self._ensure_cube()
        if not cube:
            return
        iso = float(self._params_used.get("iso", self.spn_iso.value()))
        glw = self.glw
        if glw is None:
            self.lbl_status.setText(self._t("no_canvas"))
            return
        try:
            ok = None
            if self._on_open_cube is not None:
                ok = self._on_open_cube(cube, iso)
            if ok is None:
                ok = glw.load_orbitals([cube], iso)
            if not ok:
                self.lbl_status.setText(self._t("no_canvas"))
                return
            # 等值面配色 → AICD 黄（各向异性是单符号量，正/负都用黄）。
            # 勾了「锁定」的话，之后点任何一键样式也改不动它（画布侧负责兜住）。
            yellow = (int(round(AICD_FIGURE_STYLE["surface"][0] * 255)),
                      int(round(AICD_FIGURE_STYLE["surface"][1] * 255)),
                      int(round(AICD_FIGURE_STYLE["surface"][2] * 255)))
            if hasattr(glw, "set_phase_colors"):
                glw.set_phase_colors(pos_rgb=yellow, neg_rgb=yellow)
            n = self._push_arrows(glw, iso)
            self._apply_iso_lock()      # 箭头就位后再上锁（锁依赖叠加层在场）
            self.lbl_status.setText(
                self._t("arrows_shown", n=n) if n else
                self._t("loaded_canvas", name=os.path.basename(cube)))
        except Exception as exc:                        # noqa: BLE001
            self._log("[AICD] 送画布失败：%s" % exc)
            self.lbl_status.setText(self._t("failed", err=str(exc)))

    def _ensure_cube(self):
        """取 cube 路径；没导出过就临时生成一个（送画布需要）。"""
        if self._cube and os.path.isfile(self._cube):
            return self._cube
        vol = self._vol
        if vol is None:
            QMessageBox.information(self, self._t("grp_view"), self._t("no_volume"))
            return ""
        tmpdir = os.path.join(tempfile.gettempdir(), "molstudio_aicd")
        os.makedirs(tmpdir, exist_ok=True)
        base = os.path.splitext(os.path.basename(self._log_path))[0] or "aicd"
        path = os.path.join(tmpdir, base + "_AICD_Aniso.cub")
        try:
            A.write_cube(path, vol.origin, vol.spacing, vol.field, vol.atoms,
                         comment="AICD %s" % vol.quantity)
            self._cube = path
            return path
        except Exception as exc:                        # noqa: BLE001
            self._log("[AICD] 写 cube 失败：%s" % exc)
            return ""

    def _push_arrows(self, glw, iso):
        """按**最近一次出图**的参数把箭头网格推给画布，返回箭头数量。"""
        vol = self._vol
        if vol is None or not hasattr(glw, "set_aicd_arrows"):
            return 0
        p = self._params_used or self._params()
        surf = build_arrow_surface(
            vol, iso, decimate=int(p.get("decimate", 2)),
            magnitude_floor=0.02,
            arrow_mean_length=float(p.get("arrow_len", 0.5)),
            max_arrow=float(p.get("max_arrow", 2.0)), min_arrow=0.0,
            smooth_sigma=float(p.get("smooth", 0.0)))
        if surf is None:
            glw.clear_aicd_arrows() if hasattr(glw, "clear_aicd_arrows") else None
            self._arrows_pushed = 0
            self.chk_arrows.setEnabled(False)
            return 0
        glw.set_aicd_arrows(surf)
        glw.set_aicd_arrows_visible(self.chk_arrows.isChecked())
        self._arrows_pushed = surf.n_arrows
        self.chk_arrows.setEnabled(True)
        self._log("[AICD] 画布箭头：%d 支 / %d 个三角形 / %d 个顶点"
                  % (surf.n_arrows, surf.triangle_count, surf.vertex_count))
        return surf.n_arrows

    def _clear_canvas_arrows(self):
        glw = self.glw
        if glw is not None and hasattr(glw, "clear_aicd_arrows"):
            try:
                glw.clear_aicd_arrows()
            except Exception:                           # noqa: BLE001
                pass
        self._arrows_pushed = 0
        self.chk_arrows.setEnabled(False)

    def _on_arrows_toggled(self, on):
        glw = self.glw
        if glw is not None and hasattr(glw, "set_aicd_arrows_visible"):
            try:
                glw.set_aicd_arrows_visible(bool(on))
            except Exception:                           # noqa: BLE001
                pass

    def _apply_iso_lock(self):
        """按复选框把画布等值面钉成 AICD 黄 + 不透明（或解除锁定）。"""
        glw = self.glw
        want = bool(self.chk_lock_iso.isChecked())
        if glw is None or not hasattr(glw, "set_aicd_iso_lock"):
            return
        try:
            glw.set_aicd_iso_lock(want and glw.has_aicd_arrows())
            self._iso_locked = want and glw.has_aicd_arrows()
        except Exception:                               # noqa: BLE001
            self._iso_locked = False

    def _on_lock_iso_toggled(self, _on):
        self._apply_iso_lock()

    # ── 本机跑 Gaussian ───────────────────────────────────────────────────
    def _pick_gjf(self):
        """把已有 .gjf 读进上面的输入编辑器（结构/设置都会跟着预填）。"""
        self._load_gjf_into_editor()

    def _load_gjf_into_editor(self):
        start = os.path.dirname(self._gjf_path or self._log_path) or self._outdir
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("pick_gjf"), start or "",
            "Gaussian input (*.gjf *.com);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            QMessageBox.warning(self, self._t("grp_editor"), str(exc))
            return
        stem = os.path.splitext(os.path.basename(path))[0]
        # 没有 %chk 的 gjf：补一个同名 chk，后面「算完自动检测 π 轨道」才有
        # 检查点可用（AICD 本身不需要 chk，但这一步需要）
        try:
            from molstudio.panels.aicd_input import parse_gjf_settings_text
            if not parse_gjf_settings_text(text).get("chk"):
                text = "%%chk=%s_aicd.chk\n" % stem + text
        except Exception:                                  # noqa: BLE001
            pass
        # 补上 AICD 必需的关键字（nmr=csgt iop(10/93=1) 与张量名），
        # 几何/方法/连通性表保持不变
        try:
            from molstudio.panels.aicd_input import prepare_aicd_input
            prepared = prepare_aicd_input(text, name_tag="aicd")
        except Exception:                                  # noqa: BLE001
            prepared = text
        self.editor.setPlainText(prepared)
        # 换输入 = 换体系：把上一轮的结果先清掉，避免误拿旧 .log/张量出图
        self._log_path = ""
        self._tensor_path = ""
        self._last_chk = ""
        self.edit_log.clear()
        self._refresh_input_labels()
        self._set_structure(self._atoms_from_text(prepared), path)
        # 运行目标设成同目录的 <名字>_aicd.gjf（运行前自动写盘），
        # 绝不覆盖用户原始 gjf
        folder = os.path.dirname(path)
        if folder and not self._outdir:
            self._outdir = folder
            self.edit_outdir.setText(folder)
        out_stem = self._out_stem(stem)
        self._gjf_path = os.path.join(folder, out_stem + ".gjf") if folder else ""
        self.edit_gjf.setText(self._gjf_path)
        self._remember_base_input(prepared, self._gjf_path)
        self._log("[AICD] 载入输入：%s" % path)
        self.lbl_status.setText(self._t("editor_loaded",
                                        name=os.path.basename(path)))

    # ── 输入文件编辑器 ────────────────────────────────────────────────────
    @staticmethod
    def _out_stem(stem):
        """给"运行用的输入"起名：不覆盖用户原文件，也不重复加后缀。"""
        stem = stem or "aicd"
        return stem + ("_run" if stem.endswith("_aicd") else "_aicd")

    def _generate_from_canvas(self):
        """按画布上的分子生成一份带 AICD 关键字的 .gjf 文本，填进编辑器。"""
        atoms = []
        glw = self.glw
        if glw is not None:
            try:
                atoms = [(A.element_symbol(int(num)), x * A.BOHR,
                          y * A.BOHR, z * A.BOHR)
                         for num, (x, y, z) in glw._atom_list()]
            except Exception:                              # noqa: BLE001
                atoms = []
        if not atoms:
            QMessageBox.information(self, self._t("grp_editor"),
                                    self._t("no_canvas_mol"))
            return
        from molstudio.panels.aicd_input import build_aicd_input
        base = "aicd"
        if self._log_path:
            base = os.path.splitext(os.path.basename(self._log_path))[0]
        text = build_aicd_input(
            atoms, chk=base + ".chk", mem="4GB", nproc=4,
            tensor_name=base + "_aicd.txt", title="AICD " + base)
        self.editor.setPlainText(text)
        self._log_path = ""
        self._tensor_path = ""
        self._last_chk = ""
        self.edit_log.clear()
        self._refresh_input_labels()
        self._set_structure(atoms, "")
        # 运行目标：输出目录下的 <base>_aicd.gjf（运行前自动写）
        folder = self._outdir or (os.path.dirname(self._log_path)
                                  if self._log_path else "")
        out_base = self._out_stem(base)
        self._gjf_path = os.path.join(folder, out_base + ".gjf") if folder else ""
        self.edit_gjf.setText(self._gjf_path)
        self._remember_base_input(text, self._gjf_path)
        self._refresh_editor_info()

    def _open_generator_from_editor(self):
        """打开生成器：优先预填编辑器里的输入；编辑器空则从画布开始。"""
        src = self._sync_editor_to_file(ask=False)
        if not src:
            # 编辑器还没有保存过：先写到一个临时 .gjf 供生成器预填
            text = self.editor.toPlainText().strip()
            if not text:
                # 空编辑器 = 还没有输入：直接从画布建一份
                self._open_generator()
                return
            tmpdir = os.path.join(tempfile.gettempdir(), "molstudio_aicd")
            os.makedirs(tmpdir, exist_ok=True)
            src = os.path.join(tmpdir, "editor.gjf")
            try:
                with open(src, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            except OSError:
                return
        self._open_generator(gjf_path=src)

    def _file_text(self):
        """编辑器内容 + 文件末尾换行。

        ``iop(10/93=2)`` 的轨道列表后面**必须跟一个空行**：Gaussian 的 AICD
        patch 在列表后没有空行时会漏读最后一个轨道（输入 17,20,21，log 里只有
        ``Occupy MOs 17 20``），π 密度缺一块，等值面裂成六瓣。
        """
        text = self.editor.toPlainText().rstrip()
        if "iop(10/93=2)" in text.replace(" ", "").lower():
            return text + "\n\n"
        return text + "\n"

    def _save_editor(self):
        """把编辑器内容保存成 .gjf（之后运行 Gaussian 用的就是它）。"""
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.information(self, self._t("grp_editor"),
                                    self._t("editor_missing"))
            return ""
        default = self._gjf_path or os.path.join(
            self._outdir or "", "aicd.gjf")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save_gjf"), default, "Gaussian input (*.gjf)")
        if not path:
            return ""
        if not path.lower().endswith((".gjf", ".com")):
            path += ".gjf"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._file_text())
        except OSError as exc:
            QMessageBox.warning(self, self._t("grp_editor"), str(exc))
            return ""
        self.set_input_file(path)
        self.lbl_status.setText(self._t("saved_gjf", path=path))
        self._refresh_editor_info()
        return path

    def _sync_editor_to_file(self, ask=True):
        """把编辑器里的内容写回 .gjf（运行前调用），返回可用的路径。"""
        if not self.editor.toPlainText().strip():
            if ask:
                QMessageBox.information(self, self._t("grp_editor"),
                                        self._t("editor_missing"))
            return ""
        if self._gjf_path:
            try:
                with open(self._gjf_path, "w", encoding="utf-8") as fh:
                    fh.write(self._file_text())
                return self._gjf_path
            except OSError:
                pass
        # 没有目标路径：自动存到输出目录的 <base>_aicd.gjf（不弹窗，点了就跑）
        base = "aicd"
        if self._log_path:
            base = os.path.splitext(os.path.basename(self._log_path))[0]
        folder = self._outdir or (os.path.dirname(self._log_path)
                                  if self._log_path else "")
        if folder:
            out_base = self._out_stem(base)
            path = os.path.join(folder, out_base + ".gjf")
            try:
                os.makedirs(folder, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(self._file_text())
                self.set_input_file(path)
                return path
            except OSError:
                pass
        return self._save_editor() if ask else ""

    def _refresh_editor_info(self):
        """编辑器下方的校验行：原子数、路由、张量名；缺关键字直接标出来。"""
        text = self.editor.toPlainText()
        if not text.strip():
            self.lbl_editor_info.setText(self._t("editor_missing"))
            self.lbl_editor_info.setStyleSheet("color:#94A3B8;")
            return
        try:
            from molstudio.panels.aicd_input import parse_gjf_settings_text
            info = parse_gjf_settings_text(text)
        except Exception:                                  # noqa: BLE001
            info = {}
        low = text.lower().replace(" ", "")
        warnings = []
        if "nmr=csgt" not in low:
            warnings.append(self._t("editor_no_csgt"))
        if "iop(10/93" not in low:
            warnings.append(self._t("editor_no_iop"))
        tensor = (info or {}).get("tensor") or ""
        if not tensor:
            warnings.append(self._t("editor_no_tensor"))
        # 路由方法名拼写检查（真实踩过：b3lyp 打成 n3lyp，Gaussian 直接 QPErr）
        method = (info or {}).get("method") or ""
        func = method.split("/", 1)[0].strip().lower()
        if func and func not in _KNOWN_METHODS:
            import difflib
            suggestion = difflib.get_close_matches(
                func, sorted(_KNOWN_METHODS), n=2, cutoff=0.55)
            suggestion.sort(key=lambda s: (_METHOD_PRIORITY.get(s, 99), s))
            warn = self._t("editor_bad_method", name=func)
            if suggestion:
                warn += self._t("editor_suggest", alt=" / ".join(suggestion))
            warnings.append(warn)
        # NMR 链接预检：缺 l801.exe 时任务必失败（杀软隔离是常见原因）
        if self._needs_nmr():
            for name in self._missing_nmr_links():
                warnings.append(self._t("editor_missing_link", name=name))
        route = "# " + (info or {}).get("method", "") + (
            " " + info.get("extra") if (info or {}).get("extra") else "")
        route = route.strip()
        n = len((info or {}).get("atoms") or [])
        summary = self._t("editor_info", n=n, route=route or "-",
                          tensor=tensor or "-")
        if (info or {}).get("mode") == "orbs" and info.get("orbitals"):
            summary += "  ·  iop(10/93=2) 轨道 " + str(info["orbitals"])
        if warnings:
            summary += "  ·  " + "  ".join(warnings)
            self.lbl_editor_info.setStyleSheet("color:#B45309;")
        else:
            self.lbl_editor_info.setStyleSheet("color:#166534;")
        self.lbl_editor_info.setText(summary)

    def set_input_file(self, path):
        """登记要计算的 .gjf（生成器保存完也会走这里）。"""
        self._gjf_path = path or ""
        self.edit_gjf.setText(self._gjf_path)
        if self._gjf_path:
            folder = os.path.dirname(self._gjf_path)
            if folder and not self._outdir:
                self._outdir = folder
                self.edit_outdir.setText(folder)

    def _exe_path(self):
        getter = getattr(self, "_get_g16", None)
        exe = ""
        if callable(getter):
            try:
                exe = str(getter() or "")
            except Exception:                            # noqa: BLE001
                exe = ""
        return exe or GR.DEFAULT_GAUSSIAN

    def _missing_nmr_links(self):
        """Gaussian 的 NMR 链接是否缺失（缺了就别让用户白等一轮 SCF）。"""
        exe = self._exe_path()
        if not exe or not os.path.isfile(exe):
            return []
        return GR.missing_nmr_links(exe)

    def _needs_nmr(self):
        return "nmr=" in self.editor.toPlainText().lower()

    def _run_gaussian(self):
        # 运行前先把编辑器内容落盘：用户可能在编辑器里刚改过关键字
        gjf = self._sync_editor_to_file(ask=True)
        if not gjf or not os.path.isfile(gjf):
            return
        exe = self._exe_path()
        if not exe or not os.path.isfile(exe):
            QMessageBox.information(self, self._t("grp_run"), self._t("need_g16"))
            return
        # 预检：nmr=csgt 必须有 l801.exe；缺了直接说明原因，别等 SCF 跑完才失败
        if self._needs_nmr():
            missing = self._missing_nmr_links()
            if missing:
                QMessageBox.warning(
                    self, self._t("grp_run"),
                    self._t("missing_link_msg", name=missing[0],
                            folder=os.path.dirname(exe)))
                self.lbl_status.setText(
                    self._t("editor_missing_link", name=missing[0]))
                return
        # 新任务：旧的 .log/张量先摘掉，失败时不会留下上一轮的结果
        self._log_path = ""
        self._tensor_path = ""
        self.edit_log.clear()
        self._refresh_input_labels()
        self._set_busy(True)
        self._log("[AICD] 开始本机 Gaussian 计算：%s" % os.path.basename(gjf))
        self._gauss_started = time.time()
        self.lbl_status.setText(self._t("gauss_running", elapsed=0.0))
        self._gauss_worker = _GaussWorker(gjf, exe, parent=self)
        self._gauss_worker.line.connect(self._on_gauss_line)
        self._gauss_worker.milestone.connect(
            lambda m: self._log("[Gaussian] " + m))
        self._gauss_worker.done.connect(self._on_gauss_done)
        self._gauss_worker.finished.connect(self._on_gauss_finished)
        self._gauss_worker.start()

    def _on_gauss_line(self, text):
        # 只把最后一行显示在状态栏（日志全量在 .log 里；主日志只记里程碑）
        stripped = text.strip()
        if stripped:
            self.lbl_status.setText(self._t(
                "gauss_running", elapsed=time.time() - self._gauss_started)
                + "  " + stripped[:90])

    def _cancel_gaussian(self):
        if self._gauss_worker is not None:
            self._gauss_worker.cancel()
            self.lbl_status.setText(self._t("gauss_cancelled"))

    def _on_gauss_finished(self):
        self._gauss_worker = None
        # 算完自动出图时 _worker 已经在跑：保持「取消」可用、主按钮禁用
        if self._worker is None:
            self._set_busy(False)
        else:
            self.btn_cancel.setEnabled(True)

    # ── 算完的收尾：chk → fchk → π 轨道 → cube → 画布 ─────────────────────
    def _refresh_pi_label(self):
        if self._pi_str:
            self.lbl_pi.setText(self._t("pi_label", pi=self._pi_str))
            self.lbl_pi.setStyleSheet("color:#166534;")
        else:
            self.lbl_pi.setText(self._t("pi_none"))
            self.lbl_pi.setStyleSheet("color:#64748B;")

    def _start_pi_post(self):
        """启动收尾链（后台线程）。没有 Multiwfn 就跳过并说明原因。"""
        mw = ""
        try:
            mw = str(self._get_mw() or "")
        except Exception:                                  # noqa: BLE001
            mw = ""
        if not mw or not os.path.isfile(mw):
            self._log("[AICD] 跳过 π 轨道分析：Multiwfn 路径未配置")
            return
        if self._pi_worker is not None:
            return
        self.lbl_pi.setText(self._t("pi_running"))
        self._pi_worker = _PiPostWorker(self._log_path, mw, parent=self)
        self._pi_worker.log.connect(lambda m: self._log("[π] " + str(m)))
        self._pi_worker.done.connect(self._on_pi_done)
        self._pi_worker.finished.connect(
            lambda: setattr(self, "_pi_worker", None))
        self._pi_worker.start()

    def _on_pi_done(self, info):
        if not info.get("ok"):
            self.lbl_pi.setText("")
            self.lbl_pi.setStyleSheet("color:#B91C1C;")
            msg = self._t("pi_fail", err=info.get("error", ""))
            self.lbl_pi.setText(msg)
            self._log("[AICD] " + msg)
            return
        self._pi_str = info.get("pi_str", "") or ""
        self._sigma_str = info.get("sigma_str", "") or ""
        self._pi_cubes = list(info.get("cubes") or [])
        self._refresh_pi_label()
        self._refresh_scope_info()
        mode = "LMO 投影" if info.get("mode") == "projection" else "平面法"
        msg = self._t("pi_found", pi=self._pi_str or "-", mode=mode,
                      n=len(self._pi_cubes))
        self._log("[AICD] " + msg)
        self.lbl_status.setText(msg)
        # 可视化 π 键：把 π 轨道的 cube 叠加送进画布（每个轨道一套自动配色）
        if self._pi_cubes and self.glw is not None:
            try:
                self.glw.load_orbitals(self._pi_cubes, 0.05)
                self._log("[AICD] 已把 %d 个 π 轨道 cube 送进画布"
                          % len(self._pi_cubes))
            except Exception as exc:                       # noqa: BLE001
                self._log("[AICD] 送 π 轨道到画布失败：%s" % exc)

    def _write_orbitals(self, tag):
        """把检测到的 π/σ 轨道写进输入（切到 iop(10/93=2)），准备第二遍计算。"""
        scope = "pi" if tag == "π" else "sigma"
        orbs = self._pi_str if scope == "pi" else self._sigma_str
        if not orbs:
            QMessageBox.information(self, self._t("grp_run"),
                                    self._t("pi_need"))
            return
        self._set_scope_combo(1 if scope == "pi" else 2)
        if self._apply_scope_orbitals(scope):
            self._log("[AICD] " + self.lbl_status.text())

    def _on_gauss_done(self, info):
        if info.get("cancelled"):
            self.lbl_status.setText(self._t("gauss_cancelled"))
            return
        if not info.get("ok"):
            self.lbl_status.setText(
                self._t("gauss_failed", err=info.get("error", "")))
            return
        # 算完就把 .log 与张量接上，省得用户再手点一遍
        self._log_path = info.get("log", "") or ""
        self.edit_log.setText(self._log_path)
        if self._log_path and os.path.isfile(self._log_path):
            chk = GR.find_chk_file(self._log_path)
            if chk:
                self._last_chk = chk
        self._tensor_path = info.get("tensor", "") or ""
        self._refresh_input_labels()
        self._auto_pick_field()
        atoms = A.read_standard_orientation(self._log_path) \
            if self._log_path and os.path.isfile(self._log_path) else []
        if atoms:
            self._set_structure([(A.element_symbol(z), x, y, zz)
                                 for z, x, y, zz in atoms], self._log_path)
        seconds = float(info.get("seconds", 0.0))
        self._log(self._t("gauss_done", log=os.path.basename(self._log_path),
                          t=seconds,
                          tensor=os.path.basename(self._tensor_path) or "-"))
        # 收尾链：chk→fch（formchk）→ 找 π 轨道 → 生成 cube → 叠加到画布
        if self.chk_auto_pi.isChecked():
            self._start_pi_post()
        if not self._tensor_path:
            self.lbl_status.setText(self._t("no_tensor"))
            return
        # 主流程：本地算完直接分析出图
        self.lbl_status.setText(self._t("gauss_done_analyzing", t=seconds))
        self._run()
