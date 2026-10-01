# -*- coding: utf-8 -*-
"""
tab_references.py — 各分析 tab 的引用文献对照表 + 界面底部「引用」提示条。

用途
====
Multiwfn / IboView / vcube 等在软件里被大量复用，但每个分析功能要引用的
文章并不相同：IGMH 页除了 Multiwfn 引擎文献，还必须引用 IGMH（以及可选的
IRI）方法学原文。这里把「功能 → 应引用文献」的对照关系集中成一份数据表，
主窗口在右侧设置区做成「设置 / 引文」两个页签：第一个页签是功能本身的面板，
第二个页签（CitationPanel）显示当前功能的完整引用清单，可一键复制。

文献编号与预印本长稿 `docs/chemrxiv_draft.md` 的参考文献表一致（1–24），
逐模块的条目与用法说明见 `docs/tabs_references.html`。

数据更新方式
============
1. 新增/修订文献 → 改 REFS；
2. 某模块的引用清单有变 → 改 TABS（refs 里是 (编号, 类别, 用途说明)）。
两处都是纯数据，界面代码无需改动。
"""

import html as _html

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QVBoxLayout, QWidget,
)

import molstudio.core.i18n as i18n


# ═══════════════════════════════════════════════════════════════
#  类别（小标签的颜色与中英文名）
# ═══════════════════════════════════════════════════════════════
CATEGORIES = {
    "method": {"zh": "方法", "en": "Method", "fg": "#0F6B58", "bg": "#E4F3EE"},
    "engine": {"zh": "引擎", "en": "Engine", "fg": "#2B6CB0", "bg": "#E7F0FB"},
    "render": {"zh": "渲染", "en": "Render", "fg": "#6B46A8", "bg": "#F0EBFA"},
    "style":  {"zh": "风格", "en": "Style",  "fg": "#A86E00", "bg": "#FCF2DF"},
    "own":    {"zh": "本组", "en": "In-house", "fg": "#5F6B7A", "bg": "#EDF0F4"},
}


# ═══════════════════════════════════════════════════════════════
#  文献表（编号 / 简短名 / ACS 格式完整引用）
# ═══════════════════════════════════════════════════════════════
REFS = {
    1: {
        "tag": "VMD",
        "text": "Humphrey, W.; Dalke, A.; Schulten, K. VMD: Visual Molecular "
                "Dynamics. J. Mol. Graphics 1996, 14, 33–38.",
    },
    2: {
        "tag": "Avogadro",
        "text": "Hanwell, M. D.; Curtis, D. E.; Lonie, D. C.; Vandermeersch, T.; "
                "Zurek, E.; Hutchison, G. R. Avogadro: An Advanced Semantic "
                "Chemical Editor, Visualization, and Analysis Platform. "
                "J. Cheminform. 2012, 4, 17. doi:10.1186/1758-2946-4-17",
    },
    3: {
        "tag": "IboView",
        "text": "Knizia, G. IboView — A program for chemical analysis; "
                "http://www.iboview.org/ (accessed 2026). The port was made against "
                "the IboView v20211019-RevA distribution (labelled a pre-release by "
                "its author; the last official release is v20150427).",
    },
    4: {
        "tag": "IAO/IBO",
        "text": "Knizia, G. Intrinsic Atomic Orbitals: An Unbiased Bridge between "
                "Quantum Theory and Chemical Concepts. J. Chem. Theory Comput. "
                "2013, 9, 4834–4843.",
    },
    5: {
        "tag": "Multiwfn 2012/2024",
        "text": "Lu, T.; Chen, F. Multiwfn: A Multifunctional Wavefunction "
                "Analyzer. J. Comput. Chem. 2012, 33, 580–592. See also: Lu, T. "
                "A Comprehensive Electron Wavefunction Analysis Toolbox for "
                "Chemists, Multiwfn. J. Chem. Phys. 2024, 161, 082503. "
                "doi:10.1063/5.0216272",
    },
    6: {
        "tag": "Multiwfn 软件",
        "tag_en": "Multiwfn (software)",
        "text": "Lu, T. Multiwfn, version 2026.4.10 [computer software]; "
                "http://sobereva.com/multiwfn/ (accessed 2026).",
    },
    7: {
        "tag": "IGMH",
        "text": "Lu, T.; Chen, Q. Independent Gradient Model Based on Hirshfeld "
                "Partition (IGMH): A New Method for Visual Study of Interactions "
                "in Chemical Systems. J. Comput. Chem. 2022, 43, 539–555. "
                "doi:10.1002/jcc.26812",
    },
    8: {
        "tag": "IGMH/IRI 教程",
        "tag_en": "IGMH/IRI tutorials",
        "text": "Lu, T. Tutorials on IGMH and IRI analysis in Multiwfn; "
                "http://sobereva.com/621 (IGMH) and http://sobereva.com/598 (IRI) "
                "(accessed 2026).",
    },
    9: {
        "tag": "ETS-NOCV",
        "text": "Mitoraj, M. P.; Michalak, A.; Ziegler, T. A Combined Charge and "
                "Energy Decomposition Scheme for Bond Analysis. "
                "J. Chem. Theory Comput. 2009, 5, 962–975.",
    },
    10: {
        "tag": "Tachyon",
        "text": "Stone, J. E. An Efficient Library for Parallel Ray Tracing and "
                "Animation. M.S. Thesis, University of Missouri—Rolla, 1998.",
    },
    11: {
        "tag": "vcube 2.0",
        "text": "Zhong, C. vcube 2.0 — Tcl scripts for batch rendering of Gaussian "
                "cube files with VMD; 计算化学公社 (Computational Chemistry "
                "Commune), thread 18150; "
                "http://bbs.keinsci.com/thread-18150-1-1.html (accessed 2026).",
    },
    12: {
        "tag": "能量跨度",
        "tag_en": "Energetic span",
        "text": "Kozuch, S.; Shaik, S. How to Conceptualize Catalytic Cycles? The "
                "Energetic Span Model. Acc. Chem. Res. 2011, 44, 101–110.",
    },
    13: {
        "tag": "扭曲/相互作用",
        "tag_en": "Distortion/interaction",
        "text": "Bickelhaupt, F. M.; Houk, K. N. Analyzing Reaction Rates with the "
                "Distortion/Interaction–Activation Strain Model. "
                "Angew. Chem. Int. Ed. 2017, 56, 10070–10086.",
    },
    14: {
        "tag": "ADCH",
        "text": "Lu, T.; Chen, F. Atomic Dipole Moment Corrected Hirshfeld (ADCH) "
                "Population Method. J. Theor. Comput. Chem. 2012, 11, 163–183. "
                "doi:10.1142/S0219633612500113",
    },
    15: {
        "tag": "IGMH_Toolbox",
        "text": "Hou, C. IGMH_Toolbox (Version 1.0.0) [Computer software]. Zenodo, "
                "2026. doi:10.5281/zenodo.20791253",
    },
    16: {
        "tag": "IRI",
        "text": "Lu, T.; Chen, Q. Interaction Region Indicator (IRI): A Simple Real "
                "Space Function Clearly Revealing Both Chemical Bonds and Weak "
                "Interactions. Chemistry–Methods 2021, 1, 231–239. "
                "doi:10.1002/cmtd.202100007",
    },
    17: {
        "tag": "电子流",
        "tag_en": "Electron flow",
        "text": "Knizia, G.; Klein, J. E. M. N. Electron Flow in Reaction "
                "Mechanisms — Revealed from First Principles. "
                "Angew. Chem. Int. Ed. 2015, 54, 5518–5522.",
    },
    18: {
        "tag": "iboview (patched)",
        "text": "KoehnLab. iboview — patched source code of IboView; "
                "https://github.com/KoehnLab/iboview (accessed 2026).",
    },
    19: {
        "tag": "Mayer 键级",
        "tag_en": "Mayer bond order",
        "text": "Mayer, I. Charge, Bond Order and Valence in the Ab Initio SCF "
                "Theory. Chem. Phys. Lett. 1983, 97, 270–274. See also: Mayer, I. "
                "On Bond Orders and Bond Valences in the Ab Initio Quantum "
                "Chemical Theory. Int. J. Quantum Chem. 1986, 29, 73–84.",
    },
    20: {
        "tag": "NBO",
        "text": "Weinhold, F.; Landis, C. R. Valency and Bonding: A Natural Bond "
                "Orbital Donor–Acceptor Perspective; Cambridge University Press: "
                "Cambridge, 2005.",
    },
    21: {
        "tag": "ESP",
        "text": "Murray, J. S.; Politzer, P. The Electrostatic Potential: An "
                "Overview. WIREs Comput. Mol. Sci. 2011, 1, 153–163.",
    },
    22: {
        "tag": "QTAIM",
        "text": "Bader, R. F. W. Atoms in Molecules: A Quantum Theory; Oxford "
                "University Press: Oxford, 1990.",
    },
    23: {
        "tag": "IRC",
        "text": "Fukui, K. The Path of Chemical Reactions — The IRC Approach. "
                "Acc. Chem. Res. 1981, 14, 363–368.",
    },
    24: {
        "tag": "MPP/SDP",
        "text": "Lu, T. Simple, Reliable, and Universal Metrics of Molecular "
                "Planarity. J. Mol. Model. 2021, 27, 263. "
                "doi:10.1007/s00894-021-04884-0",
    },
    # ── 25 起：ESP 表面分区面积统计（分区柱状图）相关，25–27 为本软件后补条目 ──
    25: {
        "tag": "ESP 面积统计",
        "tag_en": "ESP area statistics",
        "text": "Manzetti, S.; Lu, T. The Geometry and Electronic Structure of "
                "Aristolochic Acid: Possible Implications for a Frozen Resonance. "
                "J. Phys. Org. Chem. 2013, 26, 473–483. doi:10.1002/poc.3111",
    },
    26: {
        "tag": "ESP 面积统计 2014",
        "tag_en": "ESP area statistics (2014)",
        "text": "Lu, T.; Manzetti, S. Wavefunction and Reactivity Study of "
                "Benzo[a]pyrene Diol Epoxide and Its Enantiomeric Forms. "
                "Struct. Chem. 2014, 25, 1521–1533. "
                "doi:10.1007/s11224-014-0430-6",
    },
    27: {
        "tag": "ESP/VMD 教程",
        "tag_en": "ESP/VMD tutorial",
        "text": "Lu, T. 使用 Multiwfn 结合 VMD 分析和绘制分子表面静电势分布 "
                "(Analyzing and plotting the molecular surface electrostatic "
                "potential distribution with Multiwfn and VMD); "
                "http://sobereva.com/196 (accessed 2026).",
    },
}


def _r(no, cat, zh, en):
    """一条「模块 → 文献」关系：编号 + 类别 + 该模块里的具体用途。"""
    return {"no": no, "cat": cat, "zh": zh, "en": en}


# ═══════════════════════════════════════════════════════════════
#  各 tab 的引用清单（key 与 main_window._add_tab 的 key 一一对应）
# ═══════════════════════════════════════════════════════════════
TABS = {
    "tab_viz": {
        "zh": "可视化", "en": "View",
        "refs": [
            _r(3, "render", "整个渲染管线的移植来源（深度剥离透明、光照、球棍几何、"
                            "共价半径表）；一键样式「IBOview」",
               "Source of the whole rendering pipeline (depth-peeling transparency, "
               "lighting, ball-and-stick geometry, covalent radii); the “IBOview” "
               "one-click style."),
            _r(4, "method", "IboView 所实现的内禀原子轨道（IAO/IBO）分析，渲染管线的"
                            "理论背景",
               "The IAO/IBO analysis implemented by IboView; theoretical background "
               "of the rendering pipeline."),
            _r(17, "method", "内禀成键轨道在反应机理中的应用，轨道显示方式的依据之一",
               "Intrinsic bonding orbitals in reaction mechanisms; basis of the "
               "orbital display style."),
            _r(18, "render", "移植过程中的参照实现（正式依据仍为官方发布版 [3]）",
               "Reference implementation consulted during porting (the port itself "
               "follows the official distribution [3])."),
            _r(1, "engine", "兼容渲染通道的宿主程序；「同步到 VMD」把画布视角镜像过去",
               "Host of the compatible rendering channel; “Sync to VMD” mirrors the "
               "canvas view."),
            _r(10, "engine", "Tachyon 光线追踪器，产出高分辨率期刊级插图",
               "Tachyon ray tracer used for high-resolution journal-quality "
               "figures."),
            _r(11, "style", "VMD 渲染风格预设的来源（sob-art 等配色 / 材质 / 光照）",
               "Source of the VMD rendering-style presets (colour, material and "
               "lighting of sob-art and others)."),
        ],
        "note_zh": "另需致谢但未单列条目：范德华半径取自 Bondi, J. Phys. Chem. "
                   "1964, 68, 441–451；元素配色为公开的 Jmol/CPK 与 GaussView 调色板。",
        "note_en": "Also acknowledged without a numbered entry: van der Waals radii "
                   "from Bondi, J. Phys. Chem. 1964, 68, 441–451; element colours "
                   "from the public Jmol/CPK and GaussView palettes.",
    },
    "tab_setup": {
        "zh": "轨道", "en": "MO",
        "refs": [
            _r(5, "engine", "由 .fchk 生成轨道与自旋密度的 cube 网格",
               "Generation of orbital and spin-density cube grids from .fchk."),
            _r(6, "engine", "本开发周期实测所用版本，方法部分应注明以便复现",
               "The build tested in this cycle; state the version for "
               "reproducibility."),
        ],
    },
    "tab_charge_bond": {
        "zh": "电荷键级", "en": "Charge / Bond order",
        "refs": [
            _r(14, "method", "ADCH 电荷方案", "The ADCH charge scheme."),
            _r(19, "method", "Mayer 键级的原始定义",
               "Original definition of the Mayer bond order."),
            _r(5, "engine", "Hirshfeld / Mulliken / CM5 / SCPA / VDD 五种电荷方案与"
                            "键级的实际计算",
               "Actual computation of the five charge schemes and of bond orders."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
        ],
    },
    "tab_nbo": {
        "zh": "NBO", "en": "NBO",
        "refs": [
            _r(20, "method", "自然键轨道图像与 E(2) 给体–受体相互作用的解释框架",
               "NBO picture and the donor–acceptor E(2) interpretation framework."),
        ],
        "note_zh": "本模块直接解析 Gaussian pop=nbo 的输出，不经过 Multiwfn，因此没有"
                   "引擎文献；若方法部分需交代计算来源，应引用 Gaussian 程序本身。",
        "note_en": "This tab parses Gaussian pop=nbo output directly and does not go "
                   "through Multiwfn, so there is no engine citation; cite the "
                   "Gaussian program itself for the underlying calculation.",
    },
    "tab_esp": {
        "zh": "ESP", "en": "ESP",
        "refs": [
            _r(21, "method", "分子静电势的物理含义与表面分析的标准诠释",
               "Physical meaning of the ESP and standard interpretation of surface "
               "analysis."),
            _r(25, "method", "表面静电势分区面积统计（分区柱状图）的思想首次提出与"
                             "使用——凡在论文里用这张图，除 Multiwfn 原文外也应引用",
               "First proposal and use of the surface-ESP binned-area statistics "
               "(the binned bar chart) — cite it alongside Multiwfn whenever this "
               "plot is used."),
            _r(26, "method", "同一分区面积统计思想在致癌物多环芳烃体系中的应用与"
                             "展示，与 [25] 一并引用",
               "Application and presentation of the same binned-area statistics for "
               "a carcinogenic polycyclic aromatic system; cite together with [25]."),
            _r(5, "engine", "电子密度与 ESP 网格生成、范德华等值面提取",
               "Electron-density and ESP grid generation, van der Waals isosurface "
               "extraction."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
            _r(27, "engine", "分区面积统计的操作流程与推荐作图参数（Multiwfn + VMD "
                             "教程，本模块「📊 分区面积图」即按此流程实现）",
               "Working procedure and recommended plotting parameters for the "
               "binned-area analysis (Multiwfn + VMD tutorial; this tab's "
               "“Area Chart” follows it)."),
        ],
    },
    "tab_igmh": {
        "zh": "IGMH", "en": "IGMH",
        "refs": [
            _r(7, "method", "IGMH 方法本身；等值面几何由片段间 dg_inter 场决定",
               "The IGMH method itself; the isosurface geometry follows the "
               "inter-fragment dg_inter field."),
            _r(16, "method", "IRI 指标——本模块可切换使用的第二个弱相互作用指示函数",
               "The IRI descriptor, the second weak-interaction indicator available "
               "in this tab."),
            _r(5, "engine", "Multiwfn 原理论文，作者要求与 2024 年 JCP 介绍文同时引用",
               "Multiwfn origin paper; must be cited together with the 2024 JCP "
               "paper."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
            _r(8, "engine", "本模块实际调用的 Multiwfn 子程序（生成 dg_inter / "
                            "dg_intra / dg / sl2r 网格）",
               "The Multiwfn routines actually driven by this tab (dg_inter / "
               "dg_intra / dg / sl2r grids)."),
            _r(15, "own", "该面板的前身（IGMH_Toolbox），已在 GPLv3 下一并重新许可",
               "Predecessor of this panel (IGMH_Toolbox), relicensed under GPLv3."),
        ],
    },
    "tab_aim": {
        "zh": "AIM", "en": "AIM",
        "refs": [
            _r(22, "method", "分子中原子量子理论（QTAIM）与键临界点、键径的定义",
               "QTAIM and the definition of bond critical points and bond paths."),
            _r(5, "engine", "完整的拓扑分析实现（临界点搜索与键径追踪）",
               "The full topological analysis (critical-point search and bond-path "
               "tracing)."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
        ],
    },
    "tab_etsnocv": {
        "zh": "ETS-NOCV", "en": "ETS-NOCV",
        "refs": [
            _r(9, "method", "ETS-NOCV 电荷与能量联合分解方案",
               "The combined charge and energy decomposition scheme."),
            _r(5, "engine", "能量分解与形变密度生成（Multiwfn 持久会话）",
               "Energy decomposition and deformation-density generation in a "
               "persistent Multiwfn session."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
        ],
    },
    "tab_mpp": {
        "zh": "MPP", "en": "MPP",
        "refs": [
            _r(24, "method", "分子平面性参数（MPP）与带符号平面偏离跨度（SDP）的定义与"
                             "推荐用法",
               "Definition and recommended use of the MPP and the signed deviation "
               "of planarity (SDP)."),
            _r(5, "engine", "MPP 子程序；输入文件在内部转为 XYZ 后交给 Multiwfn",
               "The MPP routine; the input is converted to XYZ and handed to "
               "Multiwfn."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
        ],
    },
    "tab_irc": {
        "zh": "IRC 分析", "en": "IRC",
        "refs": [
            _r(23, "method", "内禀反应坐标（IRC）方法，横轴反应坐标的物理含义",
               "The IRC method and the physical meaning of the reaction-coordinate "
               "axis."),
            _r(19, "method", "沿路径逐点计算的 Mayer 键级",
               "Mayer bond orders computed point by point along the path."),
            _r(5, "engine", "每个 IRC 点的键级计算（结果按文件路径 MD5 缓存）",
               "Bond-order evaluation at every IRC point (cached by file-path MD5)."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
        ],
    },
    "tab_di": {
        "zh": "DI 分析", "en": "DI",
        "refs": [
            _r(13, "method", "扭曲/相互作用–活化张力模型；ΔE_strain,1、ΔE_strain,2、"
                             "ΔE_int 与 ΔE‡ = ΔE_strain + ΔE_int",
               "The distortion/interaction–activation strain model; ΔE_strain,1, "
               "ΔE_strain,2, ΔE_int and ΔE‡ = ΔE_strain + ΔE_int."),
        ],
        "note_zh": "本模块只解析 Gaussian 输出的 SCF 能量（可选 ZPE 或 Gibbs 校正），"
                   "不调用 Multiwfn，故无引擎文献。",
        "note_en": "This tab only parses SCF energies (optionally ZPE- or "
                   "Gibbs-corrected) from Gaussian output and does not call "
                   "Multiwfn, so there is no engine citation.",
    },
    "tab_asm_irc": {
        "zh": "ASM 扫描", "en": "ASM",
        "refs": [
            _r(13, "method", "活化张力模型；公式与 DI 面板完全一致，只是沿 IRC 逐点重复",
               "The activation strain model; identical formulae to the DI panel, "
               "repeated point by point along the IRC."),
            _r(23, "method", "扫描所沿的 IRC 路径本身", "The IRC path being scanned."),
        ],
    },
    "tab_cub_stack": {
        "zh": "CUB 叠加", "en": "CUB Stack",
        "refs": [
            _r(5, "engine", "上游的 cube 网格生成；本模块本身负责可视化",
               "Upstream cube-grid generation; this tab only visualises them."),
            _r(6, "engine", "本开发周期实测所用版本", "The build tested in this cycle."),
        ],
        "note_zh": "本模块是纯可视化功能，方法学上无独立文献；等值面提取由第三方库 "
                   "PyMCubes 完成，其版本与许可见仓库 THIRD-PARTY-NOTICES.md。",
        "note_en": "Purely a visualisation feature with no independent methodology "
                   "paper; isosurface extraction uses the third-party PyMCubes "
                   "(see THIRD-PARTY-NOTICES.md).",
    },
    "tab_crystal": {
        "zh": "晶体", "en": "Crystal",
        "refs": [
            _r(3, "render", "晶体显示沿用同一套画布渲染管线",
               "Crystal rendering reuses the same canvas rendering pipeline."),
        ],
        "note_zh": "CIF / POSCAR 解析与晶胞绘制为本项目自有实现，无专属方法学文献。",
        "note_en": "CIF / POSCAR parsing and unit-cell drawing are original to this "
                   "project and have no dedicated methodology citation.",
    },
    "tab_esm": {
        "zh": "能量跨度", "en": "ESM",
        "refs": [
            _r(12, "method", "能量跨度模型：TDI/TDTS 识别、δE 与 "
                             "TOF = (kBT/h)·exp(−δE/RT)",
               "The energetic span model: TDI/TDTS identification, δE and "
               "TOF = (kBT/h)·exp(−δE/RT)."),
        ],
    },
    "tab_ircsplit": {
        "zh": "IRC 拆分", "en": "IRC Split",
        "refs": [
            _r(23, "method", "IRC 点的物理含义（TS + 正向点 + 反向点）与排序依据",
               "Physical meaning and ordering of the IRC points (TS + forward + "
               "reverse)."),
            _r(6, "engine", "解析与编号逻辑参考了 Multiwfn 作者卢天的 IRCsplit 思路"
                            "（仅思路，未使用其代码）",
               "Parsing and numbering follow the IRCsplit idea of Multiwfn's author "
               "(idea only; no code used)."),
        ],
    },
    "tab_log": {
        "zh": "日志", "en": "Log",
        "refs": [],
        "note_zh": "纯运行状态输出，无文献依赖。",
        "note_en": "Plain run-status output; no citation dependency.",
    },
}


# ═══════════════════════════════════════════════════════════════
#  文本生成
# ═══════════════════════════════════════════════════════════════
def _lang(lang=None):
    return lang or i18n._CURRENT_LANG


def _t(key, lang, **fmt):
    """按指定语言取词条（不依赖 i18n 的全局当前语言，便于离线生成文本）。"""
    s = i18n.TR.get(key, {}).get(lang, key)
    return s.format(**fmt) if fmt else s


def module_title(key, lang=None):
    data = TABS.get(key)
    if not data:
        return ""
    lang = _lang(lang)
    return data.get("zh" if lang == "zh" else "en", "")


def _cat_name(cat, lang):
    c = CATEGORIES.get(cat)
    if not c:
        return cat
    return c["zh"] if lang == "zh" else c["en"]


def tab_ref_numbers(key):
    """该 tab 用到的文献编号（去重、按出现顺序）。"""
    data = TABS.get(key) or {}
    out = []
    for r in data.get("refs", []):
        if r["no"] not in out:
            out.append(r["no"])
    return out


def ref_tags(key, lang=None):
    """该 tab 的文献短名（按语言取别名），用于标题悬停提示。"""
    lang = _lang(lang)
    out = []
    for no in tab_ref_numbers(key):
        ref = REFS.get(no)
        if ref is None:
            continue
        out.append(ref["tag_en"] if (lang != "zh" and ref.get("tag_en"))
                   else ref["tag"])
    return out


def details_html(key, lang=None):
    """展开后的完整引用（按类别标色的小标签 + 编号 + 用途说明）。"""
    lang = _lang(lang)
    data = TABS.get(key)
    if not data:
        return ""
    refs = data.get("refs", [])
    if not refs:
        note = data.get("note_zh" if lang == "zh" else "note_en", "")
        return "<p style='color:#7A8798'>%s</p>" % _html.escape(note)

    parts = []
    for r in refs:
        ref = REFS.get(r["no"])
        if ref is None:
            continue
        cat = CATEGORIES.get(r["cat"], CATEGORIES["engine"])
        note = r["zh"] if lang == "zh" else r["en"]
        parts.append(
            "<p style='margin:2px 0 6px 0'>"
            "<span style='color:%(fg)s;background:%(bg)s;font-size:8pt;"
            "font-weight:600;padding:0 5px;border-radius:3px'>%(cat)s</span> "
            "<b style='color:#0F6B58'>[%(no)d]</b> "
            "<span style='color:#2F2F2F'>%(text)s</span><br>"
            "<span style='color:#8A93A0;font-size:8.5pt'>▸ %(use)s</span></p>"
            % {"fg": cat["fg"], "bg": cat["bg"],
               "cat": _html.escape(_cat_name(r["cat"], lang)), "no": r["no"],
               "text": _html.escape(ref["text"]), "use": _html.escape(note)}
        )
    note = data.get("note_zh" if lang == "zh" else "note_en", "")
    if note:
        parts.append("<p style='color:#8A6A10;background:#FFFAF0;padding:5px 8px;"
                     "border-radius:4px;font-size:8.5pt'>%s</p>"
                     % _html.escape(note))
    parts.append("<p style='color:#A7AFB9;font-size:8pt;margin:4px 0 0 0'>%s</p>"
                 % _html.escape(_t("cite_number_note", lang)))
    return "".join(parts)


def plain_text(key, lang=None):
    """复制到剪贴板的纯文本：完整引用 + 用途说明。"""
    lang = _lang(lang)
    data = TABS.get(key)
    if not data:
        return ""
    lines = [_t("cite_copy_head", lang, module=module_title(key, lang)), ""]
    for r in data.get("refs", []):
        ref = REFS.get(r["no"])
        if ref is None:
            continue
        lines.append("[%d] (%s) %s"
                     % (r["no"], _cat_name(r["cat"], lang), ref["text"]))
        lines.append("    → " + (r["zh"] if lang == "zh" else r["en"]))
        lines.append("")
    note = data.get("note_zh" if lang == "zh" else "note_en", "")
    if note:
        lines.append(note)
    return "\n".join(lines).strip() + "\n"


def has_entry(key):
    return key in TABS


# ═══════════════════════════════════════════════════════════════
#  界面：右侧「引文」页签
# ═══════════════════════════════════════════════════════════════
class CitationPanel(QWidget):
    """右侧「引文」页签：显示当前功能应引用的完整文献清单。

    内容随左侧功能导航切换（set_tab），标题写明功能名与篇数，正文按类别
    逐条给出 ACS 格式完整引用与「用在哪个步骤」，右上角「复制」把整页
    变成可直接粘进稿件的纯文本。
    """

    _QSS = """
    QWidget#CitationPanel { background: transparent; }
    QFrame#CiteCard {
        background: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 10px;
    }
    QLabel#CiteTitle { font-size: 12.5px; font-weight: 600; color: #14524A; }
    QLabel#CiteHint  { font-size: 11px; color: #7A8798; }
    QPushButton#CiteCopy {
        font-size: 11px;
        padding: 2px 10px;
        border: 1px solid #C6D8D3;
        border-radius: 4px;
        background: #FFFFFF;
        color: #226B5B;
    }
    QPushButton#CiteCopy:hover { background: #E7F3EF; }
    QPushButton#CiteCopy:disabled { color: #A9B4B0; border-color: #DDE5E2; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CitationPanel")
        self.setStyleSheet(self._QSS)
        self._key = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("CiteCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(6)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("CiteTitle")
        self.lbl_title.setWordWrap(True)
        row.addWidget(self.lbl_title, 1)
        self.btn_copy = QPushButton()
        self.btn_copy.setObjectName("CiteCopy")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy)
        row.addWidget(self.btn_copy, 0, Qt.AlignTop)
        cv.addLayout(row)

        self.lbl_hint = QLabel()
        self.lbl_hint.setObjectName("CiteHint")
        self.lbl_hint.setWordWrap(True)
        cv.addWidget(self.lbl_hint)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setMinimumHeight(120)
        self.browser.setStyleSheet(
            "QTextBrowser{border:none;background:transparent;font-size:9.5pt;}")
        cv.addWidget(self.browser, 1)
        root.addWidget(card, 1)

        self.set_tab("")

    # ── 对外接口 ──────────────────────────────────────────────
    def set_tab(self, key):
        """切到某个功能页：刷新标题、提示与引用正文。"""
        self._key = key or ""
        self.refresh()

    def refresh(self):
        """按当前语言重刷内容（语言切换后调用，也用于初始化）。"""
        lang = i18n._CURRENT_LANG
        key = self._key
        if not has_entry(key):
            self.lbl_title.setText(_t("cite_panel_empty", lang))
            self.lbl_hint.clear()
            self.browser.clear()
            self.btn_copy.setEnabled(False)
            self.btn_copy.setText("⧉ " + _t("cite_btn_copy_all", lang))
            return

        n = len(tab_ref_numbers(key))
        module = module_title(key, lang)
        self.lbl_title.setText(
            _t("cite_panel_title", lang, module=module, n=n) if n
            else _t("cite_panel_title_none", lang, module=module))
        self.lbl_hint.setText(_t("cite_panel_hint", lang))
        self.browser.setHtml(details_html(key, lang))
        self.browser.verticalScrollBar().setValue(0)
        self.btn_copy.setEnabled(n > 0)
        self.btn_copy.setText("⧉ " + _t("cite_btn_copy_all", lang))
        self.lbl_title.setToolTip(" · ".join(ref_tags(key, lang)))

    # ── 内部 ──────────────────────────────────────────────────
    def _copy(self):
        txt = plain_text(self._key, i18n._CURRENT_LANG)
        if not txt:
            return
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(txt)
        # 即时反馈：按钮文字短暂变成「已复制」
        self.btn_copy.setText("✓ " + i18n.tr("cite_copied"))
        QTimer.singleShot(
            1200,
            lambda: self.btn_copy.setText("⧉ " + i18n.tr("cite_btn_copy_all")))
