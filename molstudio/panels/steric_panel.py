# -*- coding: utf-8 -*-
"""位阻地图 / 包埋体积（%VBur）功能页。

面板内部分为两个页签：

  * 「绘图」：matplotlib 画布（2D 位阻地图 / 3D 地形），占用完整工作区；
  * 「参数与结果」：结构、计算参数、%VBur / 象限 / 体积诊断与导出。

计算全部由 ``molstudio.core.steric``（SambVca 官方算法复刻）完成，本面板只负责
取结构、传参数、显示结果、导出文件。结构默认取自**左侧画布当前分子**，也可以
直接打开 xyz / gjf / com / log / out / inp 文件（.inp 会回填官方参数）。

注意：本模块不 import OpenGL / ovcanvas，可在 ``QT_QPA_PLATFORM=offscreen``
下构建、计算、出图与保存。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

from matplotlib import colormaps                          # noqa: E402
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg   # noqa: E402
from matplotlib.figure import Figure                      # noqa: E402
from matplotlib.patches import Circle                     # noqa: E402

from PyQt5.QtCore import QRect, QSize, Qt, QThread, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QFont, QImage                            # noqa: E402
from PyQt5.QtWidgets import (                              # noqa: E402
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from molstudio.core.steric import (                        # noqa: E402
    DEFAULT_ENGINE, StericCancelled, StericError, auto_roles,
    available_engines, compute, format_diag, format_orientation_report,
    parse_gaussian_log, parse_xyz, read_inp, save_grid_csv, save_json,
    save_oriented_xyz, validate, write_inp,
)

# ── 出图模块契约（molstudio.core.steric.render）──────────────────────────
# 该模块由出图侧维护；未落地/导入失败时，本文件保留旧的 matplotlib 绘图
# 路径兜底，保证面板在任何时候都能构建、计算、出图与测试。
try:                                                        # pragma: no cover
    from molstudio.core.steric.render import (
        MAP_STYLES as _RENDER_MAP_STYLES,
        PALETTE_LABELS as _RENDER_PALETTE_LABELS,
        draw_map as _RENDER_DRAW_MAP,
        draw_terrain_3d as _RENDER_DRAW_TERRAIN_3D,
    )
    try:                                  # 风格显示名（较新的出图模块才导出）
        from molstudio.core.steric.render import (
            MAP_STYLE_LABELS as _RENDER_MAP_STYLE_LABELS,
        )
    except Exception:                                        # noqa: BLE001
        _RENDER_MAP_STYLE_LABELS = {}
except Exception:                                            # noqa: BLE001
    _RENDER_MAP_STYLES = ()
    _RENDER_PALETTE_LABELS = {}
    _RENDER_MAP_STYLE_LABELS = {}
    _RENDER_DRAW_MAP = None
    _RENDER_DRAW_TERRAIN_3D = None


# ══════════════════════════════════════════════════════════════════════
#  双语文字表（所有控件文案都必须走这里）
# ══════════════════════════════════════════════════════════════════════
_TR = {
    "zh": {
        # 出图区
        "grp_view": "位阻地图 / 包埋体积",
        "lbl_view": "视图",
        "view_2d": "2D 地图",
        "view_3d": "3D 地形",
        "chk_quad": "象限标签",
        "chk_quad_tip": "在地图上画出 x=0 / y=0 的象限分隔线，并标出 NE / NW / SW / SE",
        "chk_contours": "等高线",
        "tip_contours": "在位阻地图上叠加等值线（StericRender 风格更明显）",
        "chk_skeleton": "后方球棍结构",
        "tip_skeleton": "把定向后的球棍分子画在地图后方，再以半透明地形色块覆盖；"
                        "这是 StericRender 叠层图的默认效果",
        "lbl_map_opacity": "地图透明度",
        "tip_map_opacity": "地图色块覆盖后方球棍结构的不透明度；0.72 近似 StericRender 默认值",
        "lbl_molecule_scope": "分子显示范围",
        "molecule_clip_sphere": "仅显示球内（裁切）",
        "molecule_clip_full": "显示完整分子",
        "tip_molecule_scope": "球内模式把分子裁切到位阻地图圆盘内；"
                              "完整分子模式保留圆外配体并自动扩大绘图范围。",
        "chk_axes": "轴指示",
        "tip_axes": "在地图角落画出定向后的 x / y / z 轴指示，用来判断朝向是否正确",
        "lbl_style": "地图风格",
        "tip_style": "StericRender：平滑插值 + 半透明等高线；SambVca 官方：分阶色块 + 等高线",
        "hint_empty": "还没有结构。\n在左侧画布打开分子后点「刷新画布结构」，\n或点「打开文件…」载入 xyz / gjf / log / inp。",
        "hint_ready": "结构已载入。\n设置球心 / z 轴 / xz 原子（或点「自动推荐」），\n然后点「计算位阻地图 / 包埋体积」。",
        "hint_need_map": "计算结果里没有位阻地图网格（DoMap=0？）",
        # 结果区
        "grp_result": "计算结果",
        "vbur_fmt": "%VBur = {v:.2f} %",
        "vbur_none": "%VBur = —",
        "engine_fmt": "引擎：{name}",
        "quad_title": "四象限",
        "oct_title": "八分区",
        "vol_title": "体积明细",
        "atoms_title": "原子统计",
        "diag_title": "定向诊断",
        "warn_title": "定向自检提示",
        "vol_buried": "埋藏体积",
        "vol_free": "自由体积",
        "vol_sphere": "球体积",
        "vol_fmt": "{name} {v:.1f} Å³",
        "atoms_sel": "参与原子数 {n}",
        "atoms_del": "排除原子数 {n}",
        "diag_axis": "轴向长度 {v}",
        "diag_cons": "轴向一致性 {v}",
        "diag_roll": "滚转角 {v}",
        "diag_xz": "xz 水平投影 {v}",
        "diag_none": "—",
        # 参数区
        "grp_params": "参数设置",
        "tab_plot": "绘图",
        "tab_settings": "参数与结果",
        "lbl_source": "结构来源",
        "btn_canvas": "刷新画布结构",
        "btn_canvas_tip": "从左侧画布重新读取当前分子的原子与坐标",
        "btn_open": "打开文件…",
        "btn_open_tip": "支持 .xyz / .gjf / .com / .log / .out / .inp；.inp 会同时回填官方参数",
        "btn_auto": "自动推荐",
        "btn_auto_tip": "按元素与几何自动推荐球心 / z 轴 / xz 原子（1-based）",
        "src_canvas": "画布：{n} 个原子",
        "src_canvas_empty": "画布无结构",
        "src_file": "文件：{name}（{n} 个原子）",
        "lbl_centre": "球心原子",
        "lbl_zaxis": "z 轴原子",
        "lbl_xz": "xz 平面原子",
        "lbl_del": "删除原子",
        "tip_index": "1-based 原子序号，支持 1,3-5 写法（官方 .inp 同义）",
        "lbl_engine": "计算引擎",
        "lbl_radii": "半径集",
        "radii_bondi_scaled": "Bondi×1.17（官方）",
        "radii_bondi": "Bondi",
        "tip_radii": "官方默认使用 Bondi 半径 ×1.17 缩放；Bondi 为未缩放原始半径",
        "lbl_R": "球半径 (Å)",
        "lbl_mapR": "地图半径 (Å)",
        "lbl_mesh": "网格 mesh (Å)",
        "tip_R": "计算 %VBur 的球半径，官方推荐 3.5 Å",
        "tip_mapR": "绘制位阻地图的球半径，一般与球半径相同",
        "tip_mesh": "体素边长；越小越精细，但内存与时间按三次方增长",
        "lbl_align": "AlignZ",
        "align_0": "0 · 配体在 −z",
        "align_1": "1 · 配体在 +z",
        "tip_align": "官方 AlignZ：0 = 配体朝向 −z（默认），1 = 朝向 +z",
        "lbl_disp": "Disp (Å)",
        "tip_disp": "沿 z 轴平移配位点的距离（官方 Disp）",
        "chk_remove_h": "去除氢原子",
        "tip_remove_h": "官方 RemoveH：从体积计算中剔除 H 原子",
        "lbl_cmap": "配色",
        "tip_cmap": "位阻地图配色（只影响显示，不改数值）",
        "lbl_auto_color": "色标按数据范围",
        "tip_auto_color": "默认不勾选：色标固定 ±地图半径（与官方 SambVca / StericRender 一致）；"
                          "勾选后用网格数据范围，并可手动改上下限",
        "lbl_cmin": "最小",
        "lbl_cmax": "最大",
        "tip_cmin": "色标下限，单位 Å（z 轴为定向后的高度）",
        "tip_cmax": "色标上限，单位 Å",
        # 画布点选 / 原子删除
        "lbl_pick": "画布点选",
        "tip_pick": "打开后可直接在左侧画布点击原子，把原子号填进上面的球心 / z 轴 / xz / 删除字段",
        "pick_off": "关闭",
        "pick_centre": "设球心",
        "pick_zaxis": "设 z 轴",
        "pick_xz": "设 xz 平面",
        "pick_delete": "删除原子",
        "pick_restore": "恢复原子",
        "pick_hint_off": "点选已关闭",
        "pick_hint_centre": "在左侧画布点击原子 → 设为球心",
        "pick_hint_zaxis": "在左侧画布点击原子 → 加入 / 移出 z 轴列表",
        "pick_hint_xz": "在左侧画布点击原子 → 加入 / 移出 xz 列表",
        "pick_hint_delete": "在左侧画布点击原子（可多选）→ 同步为删除列表",
        "pick_hint_restore": "在左侧画布点击原子 → 从删除列表恢复",
        "pick_stat_fmt": "当前：{ids}",
        "btn_pick_delete": "选中→删除列表",
        "tip_pick_delete": "把画布当前选中的全部原子写成删除列表（左键点击原子可多选）",
        "btn_pick_clear_del": "清空删除",
        "tip_pick_clear_del": "清空删除原子列表（不改动画布里的分子）",
        "btn_pick_clear_sel": "清空选择",
        "tip_pick_clear_sel": "只清除画布上被选中的高亮，不改动删除列表",
        # 定向方式
        "lbl_orient": "定向方式",
        "orient_sambvca": "SambVca 官方定向（文献可比）",
        "orient_view": "按当前画布视角（默认）",
        "tip_orient": "按当前画布视角（默认）：地图朝向 = 左侧画布当前朝向，"
                      "所见即所得；SambVca 官方定向：用球心 / z 轴 / xz 原子构造"
                      "坐标系，%VBur 与文献/官方 SambVca 可比，但与画布朝向无关。"
                      "后者可点「同步画布朝向」把画布转到同一朝向。",
        "orient_view_hint": "计算时读取左侧画布当前朝向：地图朝向与画布一致",
        "orient_sambvca_hint": "官方定向：%VBur 与文献可比；与画布当前朝向无关。"
                               "点「同步画布朝向」可把左侧画布转到该朝向",
        "btn_sync_canvas": "同步画布朝向",
        "tip_sync_canvas": "把左侧画布旋转并平移到本次计算使用的定向（球心居中），"
                           "让画布与地图朝向完全一致",
        "st_sync_canvas_ok": "已将左侧画布切到本次计算的定向",
        "st_sync_canvas_fail": "同步画布朝向失败：{err}",
        "diag_orient": "定向方式 {v}",
        "diag_view_tilt": "视图倾角 {v}",
        "orient_short_sambvca": "SambVca 官方",
        "orient_short_view": "画布视角",
        "st_view_no_camera": "取不到画布朝向：请先在左侧打开分子（或等画布就绪）再计算",
        "st_view_unsupported": "当前引擎不支持按画布视角定向：请改用「SambVca 原子定向」",
        # 画布点选状态行
        "st_pick_centre": "球心原子设为 {idx}",
        "st_pick_zaxis": "z 轴原子：{ids}",
        "st_pick_xz": "xz 平面原子：{ids}",
        "st_pick_delete": "删除列表：{ids}",
        "st_pick_restore": "已从删除列表移除 {idx}",
        "st_pick_cleared": "已清空画布选择",
        "st_pick_no_glw": "当前没有可交互的画布",
        "st_pick_off": "画布点选已关闭",
        # 按钮 / 状态
        "btn_run": "计算位阻地图 / 包埋体积",
        "btn_cancel": "取消计算",
        "btn_save_img": "保存图片…",
        "btn_export_data": "导出数据…",
        "btn_export_inp": "导出 .inp",
        "btn_export_xyz": "导出定向 XYZ",
        "tip_save_img": "按当前视图导出 PNG / PDF / SVG（300 dpi）",
        "tip_export_data": "导出网格 CSV（x,y,z）或完整 JSON（可复现参数）",
        "tip_export_inp": "写出官方 SambVca 可读的 .inp",
        "tip_inp_view_mode": "视图定向无法写进官方 .inp（官方格式只支持 SambVca "
                             "原子定向）；请用「导出数据…」的 JSON（含旋转矩阵）复现",
        "st_inp_view_mode": "视图定向结果不能导出官方 .inp；请导出 JSON（含旋转矩阵）",
        "tip_export_xyz": "写出定向后坐标的 XYZ 文件",
        "st_ready": "就绪",
        "st_busy": "正在{step}…",
        "st_cancelling": "正在取消…",
        "st_cancel": "已取消计算",
        "st_done": "完成：%VBur = {v:.2f} %，用时 {t:.2f} s",
        "st_failed": "失败：{err}",
        "st_saved": "已保存：{path}",
        "st_no_struct": "还没有结构：请先刷新左侧画布，或用「打开文件…」载入",
        "st_auto_roles": "自动推荐：球心 {centre}，z 轴 {z}，xz {xz}，删除 {del}",
        "st_auto_roles_fail": "自动推荐失败：{err}",
        "st_open_fail": "打开文件失败：{err}",
        "st_load_ok": "已载入 {n} 个原子",
        "st_need_result": "还没有计算结果",
        "err_title": "位阻地图 / 包埋体积",
        # 文件对话框
        "dlg_open": "打开结构文件",
        "dlg_save_img": "保存位阻地图图片",
        "dlg_save_data": "导出位阻地图数据",
        "dlg_save_inp": "导出 SambVca .inp",
        "dlg_save_xyz": "导出定向结构 XYZ",
        "filter_struct": "结构文件 (*.xyz *.gjf *.com *.log *.out *.inp);;"
                         "XYZ (*.xyz);;Gaussian (*.gjf *.com *.log *.out);;"
                         "SambVca 参数 (*.inp);;所有文件 (*)",
        "filter_img": "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)",
        "filter_data": "CSV 网格 (*.csv);;JSON 结果 (*.json)",
        "filter_inp": "SambVca 参数 (*.inp)",
        "filter_xyz": "XYZ (*.xyz)",
        # 计算步骤（引擎 on_progress 的 step 名）
        "step_orient": "定向",
        "step_select": "筛选原子",
        "step_volume": "体积积分",
        "step_map": "生成地图",
        "step_done": "完成",
        # 引擎名
        "engine_native": "官方算法·内置",
        "engine_stericrender": "StericRender",
        # 日志
        "log_header": "\n━━━ 位阻地图 / 包埋体积 ━━━",
        "log_start": "  结构: {n} 个原子   引擎: {engine}   球半径: {r:g} Å   "
                     "地图半径: {m:g} Å   mesh: {mesh:g} Å",
        "log_roles": "  球心: {centre}   z 轴: {z}   xz: {xz}   删除: {del}",
        "log_done": "  %VBur = {v:.2f} %  NE {ne:.2f}  NW {nw:.2f}  "
                    "SW {sw:.2f}  SE {se:.2f}",
        "log_saved": "  已保存: {path}",
        "log_cancel": "  计算已取消",
        # 定向自检文案（format_diag 的 tr 回调）
        "warn_axis_cancel": "所选 z 轴原子相对球心的方向接近相互抵消（一致性 {ratio:.2f}，"
                            "轴向长度 {len:.3f} Å）：建议改选其他原子",
        "warn_xz_parallel": "xz 原子方向几乎与 z 轴平行（水平投影 {proj:.3f} Å，仅为向量长度的 "
                            "{frac:.0%}，夹角 {angle:.1f}°）：滚转角不可靠，请改选其他原子",
        "warn_no_xz": "未指定 xz 平面原子：绕 z 轴的滚转未被锁定，不同次计算的地图/象限朝向可能不一致",
        "warn_empty_delete": "删除列表为空：配合物中其它配体、反离子、溶剂都会计入体积"
                             "（官方要求把不属于目标配体的原子全部删除）",
        "warn_centre_not_deleted": "球心原子（{ids} 号）未在删除列表中：官方要求把它一并删除；"
                                   "当前结果仍会把它计入体积，如需严格对照文献请加入删除列表",
        "warn_radius_nonstandard": "球半径 R = {r:g} Å 不是官方推荐的 3.5 Å，"
                                   "与文献 %VBur 不可直接比较",
        "note_axis_short_ok": "轴向量较短（{len:.3f} Å），但方向稳健（一致性 {ratio:.2f}），可以使用",
    },
    "en": {
        # view
        "grp_view": "Steric Map / Buried Volume",
        "lbl_view": "View",
        "view_2d": "2D map",
        "view_3d": "3D terrain",
        "chk_quad": "Quadrant labels",
        "chk_quad_tip": "Draw the x=0 / y=0 separators and label NE / NW / SW / SE",
        "chk_contours": "Contours",
        "tip_contours": "Overlay iso-lines on the steric map (more visible in StericRender style)",
        "chk_skeleton": "Molecule behind map",
        "tip_skeleton": "Render the oriented ball-and-stick molecule behind the map, then cover "
                        "it with a translucent topographic layer (StericRender-style)",
        "lbl_map_opacity": "Map opacity",
        "tip_map_opacity": "Opacity of the map over the ball-and-stick structure; "
                           "0.72 matches StericRender's default",
        "lbl_molecule_scope": "Molecule display",
        "molecule_clip_sphere": "Inside sphere (clipped)",
        "molecule_clip_full": "Full molecule",
        "tip_molecule_scope": "Sphere mode clips the molecule to the steric-map disk. "
                              "Full-molecule mode keeps substituents outside the disk "
                              "and expands the plot bounds.",
        "chk_axes": "Axis indicator",
        "tip_axes": "Draw the oriented x / y / z axes in a map corner to check the orientation",
        "lbl_style": "Map style",
        "tip_style": "StericRender: smooth interpolation + translucent contours; "
                     "SambVca official: stepped colour bands + contours",
        "hint_empty": "No structure yet.\nOpen a molecule on the left canvas and click "
                      "\"Refresh canvas\", or click \"Open file...\" to load xyz / gjf / log / inp.",
        "hint_ready": "Structure loaded.\nSet the centre / z-axis / xz atoms (or click "
                      "\"Auto roles\"), then click \"Compute steric map / buried volume\".",
        "hint_need_map": "The result has no steric map grid (DoMap=0?)",
        # results
        "grp_result": "Results",
        "vbur_fmt": "%VBur = {v:.2f} %",
        "vbur_none": "%VBur = —",
        "engine_fmt": "Engine: {name}",
        "quad_title": "Quadrants",
        "oct_title": "Octants",
        "vol_title": "Volumes",
        "atoms_title": "Atom counts",
        "diag_title": "Orientation diagnostics",
        "warn_title": "Orientation self-checks",
        "vol_buried": "Buried",
        "vol_free": "Free",
        "vol_sphere": "Sphere",
        "vol_fmt": "{name} {v:.1f} Å³",
        "atoms_sel": "Selected atoms {n}",
        "atoms_del": "Excluded atoms {n}",
        "diag_axis": "Axis length {v}",
        "diag_cons": "Axis consistency {v}",
        "diag_roll": "Roll {v}",
        "diag_xz": "xz in-plane projection {v}",
        "diag_none": "—",
        # params
        "grp_params": "Parameters",
        "tab_plot": "Plot",
        "tab_settings": "Parameters & results",
        "lbl_source": "Structure",
        "btn_canvas": "Refresh canvas",
        "btn_canvas_tip": "Re-read the current molecule (atoms and coordinates) from the left canvas",
        "btn_open": "Open file...",
        "btn_open_tip": "Supports .xyz / .gjf / .com / .log / .out / .inp; "
                        ".inp also fills in the official parameters",
        "btn_auto": "Auto roles",
        "btn_auto_tip": "Pick centre / z-axis / xz atoms automatically (1-based)",
        "src_canvas": "Canvas: {n} atoms",
        "src_canvas_empty": "No structure on the canvas",
        "src_file": "File: {name} ({n} atoms)",
        "lbl_centre": "Centre atom",
        "lbl_zaxis": "z-axis atom",
        "lbl_xz": "xz-plane atom",
        "lbl_del": "Delete atoms",
        "tip_index": "1-based atom indices; supports 1,3-5 (same as the official .inp)",
        "lbl_engine": "Engine",
        "lbl_radii": "Radii set",
        "radii_bondi_scaled": "Bondi x1.17 (official)",
        "radii_bondi": "Bondi",
        "tip_radii": "The official default scales Bondi radii by 1.17; Bondi uses the raw radii",
        "lbl_R": "Sphere R (Å)",
        "lbl_mapR": "Map radius (Å)",
        "lbl_mesh": "Mesh (Å)",
        "tip_R": "Sphere radius for %VBur; the official value is 3.5 Å",
        "tip_mapR": "Sphere radius for the map; usually the same as the sphere radius",
        "tip_mesh": "Voxel edge length; finer grids cost memory and time cubically",
        "lbl_align": "AlignZ",
        "align_0": "0 · ligand on -z",
        "align_1": "1 · ligand on +z",
        "tip_align": "Official AlignZ: 0 = ligand points to -z (default), 1 = to +z",
        "lbl_disp": "Disp (Å)",
        "tip_disp": "Shift of the coordination point along z (official Disp)",
        "chk_remove_h": "Remove H",
        "tip_remove_h": "Official RemoveH: leave H atoms out of the volume integration",
        "lbl_cmap": "Colour map",
        "tip_cmap": "Colours for the steric map (display only)",
        "lbl_auto_color": "Colour range from data",
        "tip_auto_color": "Unchecked by default: the colour scale is fixed to ±map radius "
                          "(matching official SambVca / StericRender); when checked, the grid "
                          "data range is used and the limits can be edited",
        "lbl_cmin": "min",
        "lbl_cmax": "max",
        "tip_cmin": "Lower colour limit in Å (z is the height after orientation)",
        "tip_cmax": "Upper colour limit in Å",
        # canvas picking / atom deletion
        "lbl_pick": "Canvas picking",
        "tip_pick": "When enabled, click atoms on the left canvas to fill the centre / z-axis / "
                    "xz / delete fields above",
        "pick_off": "Off",
        "pick_centre": "Set centre",
        "pick_zaxis": "Set z-axis",
        "pick_xz": "Set xz plane",
        "pick_delete": "Delete atoms",
        "pick_restore": "Restore atoms",
        "pick_hint_off": "Canvas picking is off",
        "pick_hint_centre": "Click an atom on the left canvas to set the centre",
        "pick_hint_zaxis": "Click atoms on the left canvas to add / remove them from the z-axis list",
        "pick_hint_xz": "Click atoms on the left canvas to add / remove them from the xz list",
        "pick_hint_delete": "Click atoms on the left canvas (multi-select) to sync the delete list",
        "pick_hint_restore": "Click an atom on the left canvas to restore it from the delete list",
        "pick_stat_fmt": "Current: {ids}",
        "btn_pick_delete": "Selection → delete",
        "tip_pick_delete": "Write every atom currently selected on the canvas into the delete list "
                           "(left-click atoms to multi-select)",
        "btn_pick_clear_del": "Clear delete",
        "tip_pick_clear_del": "Empty the delete-atom list (the molecule on the canvas is untouched)",
        "btn_pick_clear_sel": "Clear selection",
        "tip_pick_clear_sel": "Only clear the highlighted canvas selection; the delete list is kept",
        # orientation
        "lbl_orient": "Orientation",
        "orient_sambvca": "SambVca official (literature)",
        "orient_view": "Current canvas view (default)",
        "tip_orient": "Current canvas view (default): the map uses the left canvas orientation "
                      "as seen on screen. SambVca official: build the frame from the centre / z-axis "
                      "/ xz atoms; %VBur is comparable with the literature/SambVca, but unrelated to "
                      "the canvas orientation. Use \"Match canvas view\" to rotate the canvas to it.",
        "orient_view_hint": "Reads the current left-canvas orientation at compute time: the map "
                            "matches what you see on the canvas",
        "orient_sambvca_hint": "Official orientation: %VBur is literature-comparable but unrelated "
                               "to the current canvas orientation; click \"Match canvas view\" to "
                               "rotate the canvas to this orientation",
        "btn_sync_canvas": "Match canvas view",
        "tip_sync_canvas": "Rotate/translate the left canvas to the orientation used by this "
                           "calculation (sphere centre in the middle), so canvas and map agree",
        "st_sync_canvas_ok": "Left canvas rotated to the orientation used by this calculation",
        "st_sync_canvas_fail": "Could not match the canvas view: {err}",
        "diag_orient": "Orientation {v}",
        "diag_view_tilt": "View tilt {v}",
        "orient_short_sambvca": "SambVca official",
        "orient_short_view": "canvas",
        "st_view_no_camera": "Cannot read the canvas orientation: open a molecule on the left "
                             "canvas (or wait until it is ready) and compute again",
        "st_view_unsupported": "The current engine does not support view orientation: "
                               "please use \"SambVca atom-based\"",
        # canvas picking status
        "st_pick_centre": "Centre atom set to {idx}",
        "st_pick_zaxis": "z-axis atoms: {ids}",
        "st_pick_xz": "xz-plane atoms: {ids}",
        "st_pick_delete": "Delete list: {ids}",
        "st_pick_restore": "Removed {idx} from the delete list",
        "st_pick_cleared": "Canvas selection cleared",
        "st_pick_no_glw": "No interactive canvas is available",
        "st_pick_off": "Canvas picking turned off",
        # buttons / status
        "btn_run": "Compute steric map / buried volume",
        "btn_cancel": "Cancel",
        "btn_save_img": "Save image...",
        "btn_export_data": "Export data...",
        "btn_export_inp": "Export .inp",
        "btn_export_xyz": "Export oriented XYZ",
        "tip_save_img": "Save the current view as PNG / PDF / SVG (300 dpi)",
        "tip_export_data": "Export the map grid as CSV (x,y,z) or the full JSON (reproducible params)",
        "tip_export_inp": "Write an official SambVca-compatible .inp",
        "tip_inp_view_mode": "A canvas-view orientation cannot be stored in an official "
                             ".inp (that format only supports SambVca atom-based "
                             "orientation); use the JSON export (includes the rotation "
                             "matrix) to reproduce it",
        "st_inp_view_mode": "A canvas-view result cannot be exported as an official .inp; "
                            "use the JSON export (includes the rotation matrix)",
        "tip_export_xyz": "Write an XYZ file with the oriented coordinates",
        "st_ready": "Ready",
        "st_busy": "Running {step}...",
        "st_cancelling": "Cancelling...",
        "st_cancel": "Computation cancelled",
        "st_done": "Done: %VBur = {v:.2f} %, {t:.2f} s",
        "st_failed": "Failed: {err}",
        "st_saved": "Saved: {path}",
        "st_no_struct": "No structure yet: refresh the left canvas or use \"Open file...\"",
        "st_auto_roles": "Auto roles: centre {centre}, z-axis {z}, xz {xz}, delete {del}",
        "st_auto_roles_fail": "Auto roles failed: {err}",
        "st_open_fail": "Could not open the file: {err}",
        "st_load_ok": "Loaded {n} atoms",
        "st_need_result": "No result yet",
        "err_title": "Steric Map / Buried Volume",
        # dialogs
        "dlg_open": "Open structure file",
        "dlg_save_img": "Save steric map image",
        "dlg_save_data": "Export steric map data",
        "dlg_save_inp": "Export SambVca .inp",
        "dlg_save_xyz": "Export oriented structure XYZ",
        "filter_struct": "Structure files (*.xyz *.gjf *.com *.log *.out *.inp);;"
                         "XYZ (*.xyz);;Gaussian (*.gjf *.com *.log *.out);;"
                         "SambVca input (*.inp);;All files (*)",
        "filter_img": "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)",
        "filter_data": "CSV grid (*.csv);;JSON result (*.json)",
        "filter_inp": "SambVca input (*.inp)",
        "filter_xyz": "XYZ (*.xyz)",
        # compute steps
        "step_orient": "orientation",
        "step_select": "atom selection",
        "step_volume": "volume integration",
        "step_map": "map generation",
        "step_done": "done",
        # engine names
        "engine_native": "Official (built-in)",
        "engine_stericrender": "StericRender",
        # log
        "log_header": "\n━━━ Steric Map / Buried Volume ━━━",
        "log_start": "  structure: {n} atoms   engine: {engine}   sphere R: {r:g} Å   "
                     "map R: {m:g} Å   mesh: {mesh:g} Å",
        "log_roles": "  centre: {centre}   z-axis: {z}   xz: {xz}   delete: {del}",
        "log_done": "  %VBur = {v:.2f} %  NE {ne:.2f}  NW {nw:.2f}  SW {sw:.2f}  SE {se:.2f}",
        "log_saved": "  saved: {path}",
        "log_cancel": "  computation cancelled",
        # orientation self-check text (tr callback of format_diag)
        "warn_axis_cancel": "The z-axis atoms point in nearly opposite directions from the centre "
                            "(consistency {ratio:.2f}, axis length {len:.3f} Å): pick other atoms",
        "warn_xz_parallel": "The xz atom is almost parallel to the z-axis (in-plane projection "
                            "{proj:.3f} Å, only {frac:.0%} of the vector, angle {angle:.1f}°): "
                            "the roll is unreliable, pick another atom",
        "warn_no_xz": "No xz-plane atom given: the roll about z is not locked, so maps/quadrants "
                      "may differ between runs",
        "warn_empty_delete": "The delete list is empty: other ligands, counter-ions and solvent all "
                             "count towards the volume (the official workflow deletes every atom "
                             "that is not part of the target ligand)",
        "warn_centre_not_deleted": "The centre atom ({ids}) is not in the delete list: the official "
                                   "workflow deletes it too; the current result still counts it in "
                                   "the volume — add it to the delete list for literature comparison",
        "warn_radius_nonstandard": "Sphere radius R = {r:g} Å is not the official 3.5 Å, so the "
                                   "%VBur is not directly comparable with literature values",
        "note_axis_short_ok": "The axis vector is short ({len:.3f} Å) but its direction is robust "
                              "(consistency {ratio:.2f}); it is usable",
    },
}

#: 地图风格（兜底标签；``MAP_STYLES`` 落地后优先用它给的文案）
MAP_STYLE_LABELS = {
    "stericrender": ("StericRender（平滑 + 等高线）", "StericRender (smooth + contours)"),
    "sambvca": ("SambVca 官方（分阶 + 等高线）", "SambVca official (stepped + contours)"),
}

#: 配色下拉顺序：官方 SambVca 配色在前，其余为 matplotlib 常用色
PALETTE_ORDER = (
    "sambvca", "turbo", "viridis", "plasma", "inferno", "magma", "cividis",
    "coolwarm", "RdBu", "RdYlBu", "Spectral", "jet",
)

#: 配色兜底标签（``PALETTE_LABELS`` 落地后优先用它给的文案）
PALETTE_FALLBACK_LABELS = {
    "sambvca": ("SambVca 官方", "SambVca official"),
    "turbo": ("Turbo", "Turbo"),
    "viridis": ("Viridis", "Viridis"),
    "plasma": ("Plasma", "Plasma"),
    "inferno": ("Inferno", "Inferno"),
    "magma": ("Magma", "Magma"),
    "cividis": ("Cividis", "Cividis"),
    "coolwarm": ("Coolwarm（冷暖）", "Coolwarm"),
    "RdBu": ("RdBu（红蓝）", "RdBu (red-blue)"),
    "RdYlBu": ("RdYlBu（红黄蓝）", "RdYlBu (red-yellow-blue)"),
    "Spectral": ("Spectral（光谱）", "Spectral"),
    "jet": ("Jet（经典）", "Jet (classic)"),
}

#: 「按当前画布视角」定向时计算视图倾角要用的世界 z 轴
_WORLD_Z = np.array([0.0, 0.0, 1.0], dtype=float)

#: 画布点选目标：(内部值, i18n 键)
PICK_MODES = (
    ("off", "pick_off"),
    ("centre", "pick_centre"),
    ("z_axis", "pick_zaxis"),
    ("xz", "pick_xz"),
    ("delete", "pick_delete"),
    ("restore", "pick_restore"),
)

#: 每种点选目标对应的状态提示键
PICK_HINT_KEYS = {
    "off": "pick_hint_off",
    "centre": "pick_hint_centre",
    "z_axis": "pick_hint_zaxis",
    "xz": "pick_hint_xz",
    "delete": "pick_hint_delete",
    "restore": "pick_hint_restore",
}


def _coerce_label(raw, name, lang):
    """把 ``PALETTE_LABELS`` / ``MAP_STYLES`` 里的标签统一成当前语言文字。

    出图侧可能给字符串、``(zh, en)`` 或 ``{'zh':…, 'en':…}``，这里都兼容。
    """
    if isinstance(raw, dict):
        zh = raw.get("zh") or raw.get("label") or raw.get("name")
        en = raw.get("en") or raw.get("label") or zh
    elif isinstance(raw, (tuple, list)):
        zh = raw[0] if raw else None
        en = raw[1] if len(raw) > 1 else zh
    elif isinstance(raw, str) and raw:
        zh = en = raw
    else:
        return str(name)
    return str(zh if lang == "zh" else en)


def _palette_label(name, lang):
    raw = _RENDER_PALETTE_LABELS.get(name) if isinstance(_RENDER_PALETTE_LABELS, dict) else None
    return _coerce_label(raw, name, lang) if raw is not None else \
        _coerce_label(PALETTE_FALLBACK_LABELS.get(name), name, lang)


def _palette_options():
    """配色下拉的键顺序：官方色在前，再接 PALETTE_LABELS 里的额外条目。"""
    options = list(PALETTE_ORDER)
    if isinstance(_RENDER_PALETTE_LABELS, dict):
        for name in _RENDER_PALETTE_LABELS:
            if name not in options:
                options.append(str(name))
    return tuple(options)


def _style_options():
    """地图风格下拉的键顺序：``MAP_STYLES`` 的键优先，缺的补默认两种。"""
    options = []
    if isinstance(_RENDER_MAP_STYLES, dict):
        options.extend(str(k) for k in _RENDER_MAP_STYLES)
    elif isinstance(_RENDER_MAP_STYLES, (tuple, list)):
        options.extend(str(k) for k in _RENDER_MAP_STYLES)
    for key in ("stericrender", "sambvca"):
        if key not in options:
            options.append(key)
    return tuple(options)


def _style_label(name, lang):
    raw = None
    if isinstance(_RENDER_MAP_STYLE_LABELS, dict):
        raw = _RENDER_MAP_STYLE_LABELS.get(name)
    if raw is None and isinstance(_RENDER_MAP_STYLES, dict):
        raw = _RENDER_MAP_STYLES.get(name)
    return _coerce_label(raw, name, lang) if raw is not None else \
        _coerce_label(MAP_STYLE_LABELS.get(name), name, lang)


def _render_api():
    """返回 (draw_map, draw_terrain_3d)；出图模块未落地时返回 None。

    运行时再解析一次，这样即使面板先于 ``steric.render`` 被 import 也能接上。
    """
    try:
        from molstudio.core.steric import render as _render
    except Exception:                                          # noqa: BLE001
        _render = None
    if _render is not None:
        dm = getattr(_render, "draw_map", None)
        dt = getattr(_render, "draw_terrain_3d", None)
        if callable(dm) and callable(dt):
            return dm, dt
    if callable(_RENDER_DRAW_MAP) and callable(_RENDER_DRAW_TERRAIN_3D):
        return _RENDER_DRAW_MAP, _RENDER_DRAW_TERRAIN_3D
    return None


def _ids_from_text(text):
    """把 ``"1,3-5"`` 解析成 [1,3,4,5]；非法片段忽略（只用于 UI 高亮同步）。"""
    out = []
    for part in str(text or "").replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            lo_s, _, hi_s = part.partition("-")
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            out.extend(range(lo, hi + 1))
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return sorted({i for i in out if i > 0})

#: 半径集：(值, 中文标签键, 英文标签键)
RADII_OPTIONS = (
    ("bondi-scaled", "radii_bondi_scaled", "radii_bondi_scaled"),
    ("bondi", "radii_bondi", "radii_bondi"),
)

#: 引擎显示名
ENGINE_LABEL_KEY = {"native": "engine_native", "stericrender": "engine_stericrender"}

#: 2D 地图上的元素配色（CPK 风格）
ELEMENT_COLORS = {
    "H": "#f2f2f2", "C": "#3d3d3d", "N": "#3050f8", "O": "#ff0d0d",
    "F": "#90e050", "P": "#ff8000", "S": "#d8c800", "Cl": "#1ff01f",
    "Br": "#a62929", "I": "#940094", "B": "#ffb5b5", "Si": "#c8a078",
    "Fe": "#e06633", "Co": "#f090a0", "Ni": "#50d050", "Cu": "#c88033",
    "Zn": "#7d80b0", "Ru": "#248f8f", "Rh": "#0a7d8c", "Pd": "#006985",
    "Ag": "#c0c0c0", "Os": "#266696", "Ir": "#175487", "Pt": "#c8c8e0",
    "Au": "#ffd123", "Mo": "#54b5b5", "W": "#2194d6", "Re": "#267dab",
}

#: 八分区的显示顺序（列 → 行）
OCTANT_ORDER = (
    ("NE+z", "NE-z"),
    ("NW+z", "NW-z"),
    ("SW+z", "SW-z"),
    ("SE+z", "SE-z"),
)

#: 四象限的 2×2 排布（行 → 列）
QUADRANT_GRID = (("NW", "NE"), ("SW", "SE"))

#: 1 Å 对应的 Bohr 数（画布 ``glw`` 内部坐标用 Bohr，相机平移量也是 Bohr）
_ANGSTROM_IN_BOHR = 1.8897261254578281


def _quaternion_from_matrix(R):
    """3×3 旋转矩阵 → ``[x, y, z, w]`` 四元数（与 ovcanvas ``_q2m`` 同一约定）。

    用于「同步画布朝向」：把引擎算出的定向矩阵直接写进画布相机。
    """
    R = np.asarray(R, dtype=float).reshape(3, 3)
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = np.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = np.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = np.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = np.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], dtype=float)
    n = float(np.linalg.norm(q))
    return q / n if n > 1e-12 else np.array([0.0, 0.0, 0.0, 1.0])

_STATUS_COLORS = {
    "normal": "#3b4450",
    "ok": "#1a7a4c",
    "warn": "#c26a00",
    "error": "#c62828",
}


class _MapCanvas(FigureCanvasQTAgg):
    """随控件尺寸缩放的 matplotlib 画布。

    matplotlib 的 Qt 画布不会自动跟随控件大小（figure 保持固定英寸尺寸），
    所以在 resize 时把 figure 尺寸同步过去，图才会铺满出图区。
    """

    def __init__(self, figure):
        super().__init__(figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(300)
        # 画布不能按 figure 的英寸尺寸索取宽度：右栏只有约 680px，
        # 3D 视图下 tight_layout 会把画布的 sizeHint 顶宽，导致整页横向溢出。
        self.setMinimumWidth(0)

    def sizeHint(self):                                            # noqa: N802
        return QSize(560, 380)

    def minimumSizeHint(self):                                     # noqa: N802
        return QSize(240, 280)

    def resizeEvent(self, event):                                   # noqa: N802
        super().resizeEvent(event)
        w = max(self.width(), 60)
        h = max(self.height(), 60)
        dpi = float(self.figure.get_dpi()) or 100.0
        self.figure.set_size_inches(w / dpi, h / dpi, forward=False)
        self.draw_idle()


class StericWorker(QThread):
    """后台跑 ``compute``：主线程不阻塞，结果 / 日志 / 进度通过信号回传。"""

    log = pyqtSignal(str)
    progress = pyqtSignal(str, str)          # (step, 本地化文字)
    done = pyqtSignal(dict)

    def __init__(self, symbols, coords, params, engine, lang, parent=None,
                 view_rotation=None):
        super().__init__(parent)
        self._symbols = [str(s) for s in symbols]
        self._coords = np.array(coords, dtype=float)
        self._params = dict(params)
        self._engine = str(engine or DEFAULT_ENGINE)
        self._lang = str(lang or "zh")
        self._cancelled = False
        self._view_rotation = (None if view_rotation is None
                               else np.asarray(view_rotation, dtype=float))

    # ── 取消 ─────────────────────────────────────────────────────────
    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return bool(self._cancelled)

    # ── 线程入口 ─────────────────────────────────────────────────────
    def run(self):
        try:
            kwargs = dict(
                engine=self._engine, lang=self._lang,
                on_log=self.log.emit,
                on_progress=lambda step, text: self.progress.emit(str(step), str(text)),
                should_cancel=self.is_cancelled,
            )
            if self._view_rotation is not None:
                kwargs["view_rotation"] = self._view_rotation
            try:
                result = compute(self._symbols, self._coords, self._params, **kwargs)
            except TypeError as exc:
                # 引擎还没实现 view_rotation 时优雅退回复算（面板侧已先行拦截，
                # 这里只是防止契约漂移直接把线程打挂）。
                if self._view_rotation is not None and "view_rotation" in str(exc):
                    kwargs.pop("view_rotation", None)
                    result = compute(self._symbols, self._coords, self._params, **kwargs)
                else:
                    raise
            self.done.emit({"ok": True, "result": result})
        except StericCancelled:
            self.done.emit({"ok": False, "cancelled": True, "error": "cancelled"})
        except StericError as exc:                                # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc)})
        except Exception as exc:                                  # noqa: BLE001
            import traceback
            self.done.emit({"ok": False, "error": str(exc),
                            "traceback": traceback.format_exc()})


def _parse_cartesian_block(path):
    """从 .gjf / .com 里抓第一段笛卡尔坐标（引擎只提供 xyz / log 解析器）。"""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    def _is_int(tok):
        try:
            int(tok)
            return True
        except (TypeError, ValueError):
            return False

    i = 0
    while i < len(lines) - 1:
        parts = lines[i].split()
        if len(parts) == 2 and all(_is_int(p) for p in parts):
            symbols, xyz = [], []
            j = i + 1
            while j < len(lines):
                ln = lines[j].strip()
                if not ln:
                    break
                ps = ln.split()
                if len(ps) < 4:
                    break
                try:
                    xyz.append([float(ps[1]), float(ps[2]), float(ps[3])])
                except ValueError:
                    break
                symbols.append(ps[0])
                j += 1
            if symbols:
                return symbols, np.array(xyz, dtype=float)
        i += 1
    raise ValueError("no Cartesian coordinate block found")


class StericPanel(QWidget):
    """「位阻地图 / 包埋体积」页：绘图与参数结果双页签。"""

    #: 主程序右栏内容宽约 680px（滚动条之外）。对外声明的最小宽度不超过这个值：
    #: 布局本身按内容自适应，这里只是保证换字体/缺字体时也不会把整页横向撑破。
    MIN_WIDTH_CAP = 620

    def __init__(self, get_structure=None, log_func=None, glw=None, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self._get_structure = get_structure if callable(get_structure) else (lambda: None)
        self._log_func = log_func
        #: 左侧 OpenGL 画布（主窗口传入；单独使用/测试时可以为 None）
        self.glw = glw

        self._worker = None
        self._result = None
        self._symbols = []                  # 当前结构的元素符号
        self._coords = None                 # 当前结构的坐标 (n,3)
        self._source_kind = "canvas"        # 'canvas' | 'file'
        self._source_path = ""
        self._status_error = False
        # 状态行状态：key 形式可随 set_lang 重译；literal 形式用于引擎错误原文
        self._status_key = None
        self._status_fmt = {}
        self._status_literal = None
        self._status_level = "normal"
        # 画布点选：'off' | 'centre' | 'z_axis' | 'xz' | 'delete' | 'restore'
        self._pick_mode = "off"
        self._pick_cb_registered = False
        # 最近一次「按画布视角」计算用到的 3×3 旋转（诊断区显示视图倾角）
        self._last_view_rotation = None

        self._build_ui()
        self._apply_lang()
        self._register_pick_callback()
        self._refresh_from_canvas(initial=True)
        self._update_result_labels()
        self._show_placeholder()
        self._tabs.setCurrentIndex(1)

    def _register_pick_callback(self):
        if self.glw is None:
            return
        try:
            self.glw.add_atom_pick_callback(self._on_canvas_atom_picked)
            self._pick_cb_registered = True
        except Exception:                                          # noqa: BLE001
            self._pick_cb_registered = False

    # ── 尺寸 ─────────────────────────────────────────────────────────────
    def sizeHint(self):                                           # noqa: N802
        """Let the host page fill the available height; tabs handle scrolling."""
        hint = super().sizeHint()
        return QSize(hint.width(), 1)

    def minimumSizeHint(self):                                    # noqa: N802
        """对外声明的最小宽度按右栏宽度封顶（见 ``MIN_WIDTH_CAP``）。"""
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.MIN_WIDTH_CAP), 1)

    # ── i18n ─────────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        table = _TR.get(self.lang) or _TR["zh"]
        s = table.get(key)
        if s is None:
            s = _TR["zh"].get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._apply_lang()
        self._update_result_labels()
        if self._result is None:
            self._show_placeholder()
        else:
            self._redraw()
        # 结构来源状态行也要按语言重刷
        self._refresh_source_label()

    def _apply_lang(self):
        self._tabs.setTabText(0, self._t("tab_plot"))
        self._tabs.setTabText(1, self._t("tab_settings"))
        self.grp_view.setTitle(self._t("grp_view"))
        self.grp_result.setTitle(self._t("grp_result"))
        self.grp_params.setTitle(self._t("grp_params"))

        self.lbl_view.setText(self._t("lbl_view"))
        self.cmb_view.setItemText(0, self._t("view_2d"))
        self.cmb_view.setItemText(1, self._t("view_3d"))
        self.chk_quad.setText(self._t("chk_quad"))
        self.chk_quad.setToolTip(self._t("chk_quad_tip"))
        self.chk_contours.setText(self._t("chk_contours"))
        self.chk_contours.setToolTip(self._t("tip_contours"))
        self.chk_skeleton.setText(self._t("chk_skeleton"))
        self.chk_skeleton.setToolTip(self._t("tip_skeleton"))
        self.lbl_molecule_scope.setText(self._t("lbl_molecule_scope"))
        self.lbl_molecule_scope.setToolTip(self._t("tip_molecule_scope"))
        self.cmb_molecule_scope.setItemText(0, self._t("molecule_clip_sphere"))
        self.cmb_molecule_scope.setItemText(1, self._t("molecule_clip_full"))
        self.cmb_molecule_scope.setToolTip(self._t("tip_molecule_scope"))
        self.lbl_map_opacity.setText(self._t("lbl_map_opacity"))
        self.spn_map_opacity.setToolTip(self._t("tip_map_opacity"))
        self.chk_axes.setText(self._t("chk_axes"))
        self.chk_axes.setToolTip(self._t("tip_axes"))
        self.lbl_style.setText(self._t("lbl_style"))
        self.lbl_style.setToolTip(self._t("tip_style"))
        self.cmb_style.setToolTip(self._t("tip_style"))
        for i, key in enumerate(self._style_options):
            self.cmb_style.setItemText(i, _style_label(key, self.lang))
        # 画布点选
        self.lbl_pick.setText(self._t("lbl_pick"))
        self.lbl_pick.setToolTip(self._t("tip_pick"))
        self.cmb_pick.setToolTip(self._t("tip_pick"))
        for i, (key, label_key) in enumerate(PICK_MODES):
            self.cmb_pick.setItemText(i, self._t(label_key))
        self.btn_pick_delete.setText(self._t("btn_pick_delete"))
        self.btn_pick_delete.setToolTip(self._t("tip_pick_delete"))
        self.btn_pick_clear_del.setText(self._t("btn_pick_clear_del"))
        self.btn_pick_clear_del.setToolTip(self._t("tip_pick_clear_del"))
        self.btn_pick_clear_sel.setText(self._t("btn_pick_clear_sel"))
        self.btn_pick_clear_sel.setToolTip(self._t("tip_pick_clear_sel"))
        self._refresh_pick_hint()

        # 定向方式
        self.lbl_orient.setText(self._t("lbl_orient"))
        self.lbl_orient.setToolTip(self._t("tip_orient"))
        self.cmb_orient.setToolTip(self._t("tip_orient"))
        self.cmb_orient.setItemText(0, self._t("orient_sambvca"))
        self.cmb_orient.setItemText(1, self._t("orient_view"))
        if getattr(self, "btn_sync_canvas", None) is not None:
            self.btn_sync_canvas.setText(self._t("btn_sync_canvas"))
            self.btn_sync_canvas.setToolTip(self._t("tip_sync_canvas"))
        self._refresh_orient_hint()

        for i, key in enumerate(self._palette_options):
            self.cmb_cmap.setItemText(i, _palette_label(key, self.lang))
        self.lbl_cmap.setText(self._t("lbl_cmap"))
        self.lbl_cmap.setToolTip(self._t("tip_cmap"))
        self.cmb_cmap.setToolTip(self._t("tip_cmap"))
        self.chk_auto_color.setText(self._t("lbl_auto_color"))
        self.chk_auto_color.setToolTip(self._t("tip_auto_color"))
        self.lbl_cmin.setText(self._t("lbl_cmin"))
        self.lbl_cmin.setToolTip(self._t("tip_cmin"))
        self.spn_cmin.setToolTip(self._t("tip_cmin"))
        self.lbl_cmax.setText(self._t("lbl_cmax"))
        self.lbl_cmax.setToolTip(self._t("tip_cmax"))
        self.spn_cmax.setToolTip(self._t("tip_cmax"))

        self.lbl_quad_title.setText(self._t("quad_title"))
        self.lbl_oct_title.setText(self._t("oct_title"))
        self.lbl_vol_title.setText(self._t("vol_title"))
        self.lbl_atoms_title.setText(self._t("atoms_title"))
        self.lbl_diag_title.setText(self._t("diag_title"))
        self.lbl_warn_title.setText(self._t("warn_title"))

        self.lbl_source_title.setText(self._t("lbl_source"))
        self.btn_canvas.setText(self._t("btn_canvas"))
        self.btn_canvas.setToolTip(self._t("btn_canvas_tip"))
        self.btn_open.setText(self._t("btn_open"))
        self.btn_open.setToolTip(self._t("btn_open_tip"))
        self.btn_auto.setText(self._t("btn_auto"))
        self.btn_auto.setToolTip(self._t("btn_auto_tip"))
        self.lbl_centre.setText(self._t("lbl_centre"))
        self.lbl_zaxis.setText(self._t("lbl_zaxis"))
        self.lbl_xz.setText(self._t("lbl_xz"))
        self.lbl_del.setText(self._t("lbl_del"))
        for w in (self.edit_centre, self.edit_zaxis, self.edit_xz, self.edit_del):
            w.setToolTip(self._t("tip_index"))
        self.lbl_engine.setText(self._t("lbl_engine"))
        for i in range(self.cmb_engine.count()):
            self.cmb_engine.setItemText(i, self._engine_label(self.cmb_engine.itemData(i)))
        self.lbl_radii.setText(self._t("lbl_radii"))
        self.lbl_radii.setToolTip(self._t("tip_radii"))
        self.cmb_radii.setToolTip(self._t("tip_radii"))
        for i in range(self.cmb_radii.count()):
            data = self.cmb_radii.itemData(i)
            key = data.get("label_key") if isinstance(data, dict) else None
            self.cmb_radii.setItemText(i, self._t(key or "radii_bondi_scaled"))
        self.lbl_R.setText(self._t("lbl_R"))
        self.lbl_R.setToolTip(self._t("tip_R"))
        self.spn_R.setToolTip(self._t("tip_R"))
        self.lbl_mapR.setText(self._t("lbl_mapR"))
        self.lbl_mapR.setToolTip(self._t("tip_mapR"))
        self.spn_mapR.setToolTip(self._t("tip_mapR"))
        self.lbl_mesh.setText(self._t("lbl_mesh"))
        self.lbl_mesh.setToolTip(self._t("tip_mesh"))
        self.spn_mesh.setToolTip(self._t("tip_mesh"))
        self.lbl_align.setText(self._t("lbl_align"))
        self.lbl_align.setToolTip(self._t("tip_align"))
        self.cmb_align.setItemText(0, self._t("align_0"))
        self.cmb_align.setItemText(1, self._t("align_1"))
        self.cmb_align.setToolTip(self._t("tip_align"))
        self.lbl_disp.setText(self._t("lbl_disp"))
        self.lbl_disp.setToolTip(self._t("tip_disp"))
        self.spn_disp.setToolTip(self._t("tip_disp"))
        self.chk_remove_h.setText(self._t("chk_remove_h"))
        self.chk_remove_h.setToolTip(self._t("tip_remove_h"))

        self.btn_run.setText(self._t("btn_run"))
        self.btn_cancel.setText(self._t("btn_cancel"))
        self.btn_save_img.setText(self._t("btn_save_img"))
        self.btn_save_img.setToolTip(self._t("tip_save_img"))
        self.btn_export_data.setText(self._t("btn_export_data"))
        self.btn_export_data.setToolTip(self._t("tip_export_data"))
        self.btn_export_inp.setText(self._t("btn_export_inp"))
        self.btn_export_inp.setToolTip(self._t("tip_export_inp"))
        self.btn_export_xyz.setText(self._t("btn_export_xyz"))
        self.btn_export_xyz.setToolTip(self._t("tip_export_xyz"))

        self._refresh_source_label()
        if self._status_key is None and self._status_literal is None:
            self._set_status_i18n("st_ready")
        else:
            self._render_status()

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(5)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Tab 1 is deliberately plot-only so the map receives the full height
        # instead of competing with results and a long parameter form.
        plot_page = QWidget()
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.setContentsMargins(0, 4, 0, 0)
        plot_layout.setSpacing(0)
        plot_layout.addWidget(self._build_view_group(), 1)
        self._plot_tab = plot_page
        self._tabs.addTab(plot_page, "")

        # Tab 2 owns all setup, calculation, results and exports. It scrolls
        # independently, so a short window no longer makes the map tiny.
        settings_page = QWidget()
        settings_page_layout = QVBoxLayout(settings_page)
        settings_page_layout.setContentsMargins(0, 4, 0, 0)
        settings_page_layout.setSpacing(0)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QScrollArea.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        settings_content = QWidget()
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(2, 2, 2, 4)
        settings_layout.setSpacing(8)
        settings_layout.addWidget(self._build_params_group())
        settings_layout.addWidget(self._build_result_group())
        settings_layout.addLayout(self._build_action_rows())
        settings_layout.addStretch(1)
        settings_scroll.setWidget(settings_content)
        settings_page_layout.addWidget(settings_scroll)
        self._settings_scroll = settings_scroll
        self._settings_content = settings_content
        self._settings_tab = settings_page
        self._tabs.addTab(settings_page, "")
        self._tabs.currentChanged.connect(self._on_inner_tab_changed)

        root.addWidget(self._tabs, 1)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_status)

    def _host_window(self):
        """Find the MolStudio window without importing it (keeps panel standalone)."""
        node = self.parent()
        while node is not None:
            if hasattr(node, "_tab_keys") and hasattr(node, "_left_widget"):
                return node
            node = node.parent()
        return None

    def _sync_host_canvas_visibility(self):
        """Plot tab gets the full workspace; settings tab keeps the 3D canvas."""
        host = self._host_window()
        if host is None:
            return
        try:
            if host.tabs.currentWidget() is not self:
                return
            left = host._left_widget
            if self._tabs.currentIndex() == 0:
                left.hide()
            else:
                left.show()
        except Exception:                                      # noqa: BLE001
            pass

    def _on_inner_tab_changed(self, _index):
        self._sync_host_canvas_visibility()

    # ── 出图区 ───────────────────────────────────────────────────────────
    def _build_view_group(self):
        self.grp_view = QGroupBox()
        gv = QVBoxLayout(self.grp_view)
        gv.setContentsMargins(6, 6, 6, 6)
        gv.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_view = QLabel()
        self.cmb_view = QComboBox()
        self.cmb_view.setMinimumWidth(108)          # 防止 "3D terrain" 被省略号截断
        self.cmb_view.addItem("", 0)
        self.cmb_view.addItem("", 1)
        self.cmb_view.currentIndexChanged.connect(self._refresh_draw)
        row.addWidget(self.lbl_view)
        row.addWidget(self.cmb_view)
        row.addStretch(1)
        # 「同步画布朝向」：官方定向与画布朝向无关，可一键把左侧画布转到计算所用定向
        self.btn_sync_canvas = QPushButton()
        self.btn_sync_canvas.clicked.connect(self._sync_canvas_orientation)
        self.btn_sync_canvas.setEnabled(False)
        row.addWidget(self.btn_sync_canvas)
        gv.addLayout(row)

        self.figure = Figure(figsize=(6.4, 4.0), dpi=100)
        self._canvas = _MapCanvas(self.figure)
        gv.addWidget(self._canvas, 1)
        return self.grp_view

    # ── 结果区 ───────────────────────────────────────────────────────────
    def _build_result_group(self):
        self.grp_result = QGroupBox()
        g = QGridLayout(self.grp_result)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(3)

        self.lbl_vbur = QLabel()
        f = QFont(self.font())
        base_pt = f.pointSize() if f.pointSize() > 0 else 9
        f.setPointSize(max(12, base_pt + 6))
        f.setBold(True)
        self.lbl_vbur.setFont(f)
        self.lbl_vbur.setStyleSheet("color:#1a7a4c;")
        g.addWidget(self.lbl_vbur, 0, 0, 1, 3)

        self.lbl_res_engine = QLabel()
        self.lbl_res_engine.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_res_engine.setStyleSheet("color:#7a8595;")
        g.addWidget(self.lbl_res_engine, 0, 3, 1, 1)

        # 四象限（2×2，方位与实际几何一致）
        self.lbl_quad_title = self._section_label()
        g.addWidget(self.lbl_quad_title, 1, 0, Qt.AlignTop)
        quad_box = QWidget()
        qg = QGridLayout(quad_box)
        qg.setContentsMargins(0, 0, 0, 0)
        qg.setHorizontalSpacing(14)
        qg.setVerticalSpacing(1)
        self.quad_labels = {}
        for r, row_keys in enumerate(QUADRANT_GRID):
            for c, key in enumerate(row_keys):
                lab = QLabel()
                lab.setMinimumWidth(110)
                self.quad_labels[key] = lab
                qg.addWidget(lab, r, c)
        g.addWidget(quad_box, 1, 1, 1, 3)

        # 八分区（4 行 × 2 列：+z / −z）
        self.lbl_oct_title = self._section_label()
        g.addWidget(self.lbl_oct_title, 2, 0, Qt.AlignTop)
        oct_box = QWidget()
        og = QGridLayout(oct_box)
        og.setContentsMargins(0, 0, 0, 0)
        og.setHorizontalSpacing(14)
        og.setVerticalSpacing(1)
        self.oct_labels = {}
        self._oct_header_labels = {}
        for r, pair in enumerate(OCTANT_ORDER):
            for c, key in enumerate(pair):
                lab = QLabel()
                lab.setMinimumWidth(112)
                self.oct_labels[key] = lab
                og.addWidget(lab, r, c)
        g.addWidget(oct_box, 2, 1, 1, 3)

        # 体积明细
        self.lbl_vol_title = self._section_label()
        g.addWidget(self.lbl_vol_title, 3, 0, Qt.AlignTop)
        self.lbl_vol_buried = QLabel()
        self.lbl_vol_free = QLabel()
        self.lbl_vol_sphere = QLabel()
        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(14)
        for w in (self.lbl_vol_buried, self.lbl_vol_free, self.lbl_vol_sphere):
            w.setMinimumWidth(0)
            w.setWordWrap(True)
            vol_row.addWidget(w)
        vol_row.addStretch(1)
        g.addLayout(vol_row, 3, 1, 1, 3)

        # 原子统计
        self.lbl_atoms_title = self._section_label()
        g.addWidget(self.lbl_atoms_title, 4, 0, Qt.AlignTop)
        self.lbl_atoms_sel = QLabel()
        self.lbl_atoms_del = QLabel()
        at_row = QHBoxLayout()
        at_row.setContentsMargins(0, 0, 0, 0)
        at_row.setSpacing(18)
        at_row.addWidget(self.lbl_atoms_sel)
        at_row.addWidget(self.lbl_atoms_del)
        at_row.addStretch(1)
        g.addLayout(at_row, 4, 1, 1, 3)

        # 定向诊断
        self.lbl_diag_title = self._section_label()
        g.addWidget(self.lbl_diag_title, 5, 0, Qt.AlignTop)
        diag_box = QWidget()
        dg = QGridLayout(diag_box)
        dg.setContentsMargins(0, 0, 0, 0)
        dg.setHorizontalSpacing(18)
        dg.setVerticalSpacing(1)
        self.lbl_diag_axis = QLabel()
        self.lbl_diag_cons = QLabel()
        self.lbl_diag_roll = QLabel()
        self.lbl_diag_xz = QLabel()
        self.lbl_diag_disp = QLabel()
        self.lbl_diag_orient = QLabel()
        self.lbl_diag_view = QLabel()
        dg.addWidget(self.lbl_diag_axis, 0, 0)
        dg.addWidget(self.lbl_diag_cons, 0, 1)
        dg.addWidget(self.lbl_diag_roll, 1, 0)
        dg.addWidget(self.lbl_diag_xz, 1, 1)
        dg.addWidget(self.lbl_diag_disp, 2, 0)
        dg.addWidget(self.lbl_diag_orient, 3, 0)
        dg.addWidget(self.lbl_diag_view, 3, 1)
        g.addWidget(diag_box, 5, 1, 1, 3)

        # 定向自检提示（橙色，逐条）
        self.lbl_warn_title = self._section_label()
        g.addWidget(self.lbl_warn_title, 6, 0, Qt.AlignTop)
        warn_host = QWidget()
        self._warn_layout = QVBoxLayout(warn_host)
        self._warn_layout.setContentsMargins(0, 0, 0, 0)
        self._warn_layout.setSpacing(1)
        g.addWidget(warn_host, 6, 1, 1, 3)

        g.setColumnStretch(1, 1)
        return self.grp_result

    def _section_label(self):
        lab = QLabel()
        lab.setStyleSheet("color:#5b6573;")
        return lab

    # ── 参数区 ───────────────────────────────────────────────────────────
    def _build_params_group(self):
        self.grp_params = QGroupBox()
        gp = QVBoxLayout(self.grp_params)
        gp.setContentsMargins(8, 6, 8, 6)
        gp.setSpacing(5)

        src = QVBoxLayout()
        src.setSpacing(5)
        self.lbl_source_title = QLabel()
        self.btn_canvas = QPushButton()
        self.btn_canvas.clicked.connect(self._refresh_from_canvas)
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self._open_file_dialog)
        self.btn_auto = QPushButton()
        self.btn_auto.clicked.connect(self._auto_roles)
        self.lbl_source = QLabel()
        self.lbl_source.setStyleSheet("color:#5b6573;")
        self.lbl_source.setWordWrap(True)
        self.lbl_source_title.setText(self._t("lbl_source"))
        src_head = QHBoxLayout()
        src_head.addWidget(self.lbl_source_title)
        src_head.addWidget(self.lbl_source, 1)
        src.addLayout(src_head)
        src_actions = QHBoxLayout()
        src_actions.setSpacing(6)
        src_actions.addWidget(self.btn_canvas, 1)
        src_actions.addWidget(self.btn_open, 1)
        src_actions.addWidget(self.btn_auto, 1)
        src.addLayout(src_actions)
        gp.addLayout(src)

        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(7)
        g.setVerticalSpacing(4)

        # ── 原子角色（1-based）+ 画布点选 ──
        self.lbl_centre = QLabel()
        self.edit_centre = self._index_edit()
        self.lbl_zaxis = QLabel()
        self.edit_zaxis = self._index_edit()
        self.lbl_xz = QLabel()
        self.edit_xz = self._index_edit()
        self.lbl_del = QLabel()
        self.edit_del = self._index_edit()

        g.addWidget(self.lbl_centre, 0, 0)
        g.addWidget(self.edit_centre, 0, 1)
        g.addWidget(self.lbl_zaxis, 1, 0)
        g.addWidget(self.edit_zaxis, 1, 1)
        g.addWidget(self.lbl_xz, 2, 0)
        g.addWidget(self.edit_xz, 2, 1)
        g.addWidget(self.lbl_del, 3, 0)
        g.addWidget(self.edit_del, 3, 1)

        # 画布点选：目标下拉 + 状态提示
        self.lbl_pick = QLabel()
        self.cmb_pick = QComboBox()
        for _key, _label_key in PICK_MODES:
            self.cmb_pick.addItem("", _key)
        self.cmb_pick.setCurrentIndex(0)
        self.cmb_pick.currentIndexChanged.connect(self._on_pick_target_changed)
        self.lbl_pick_hint = QLabel()
        self.lbl_pick_hint.setStyleSheet("color:#5b6573;")
        self.lbl_pick_hint.setWordWrap(True)
        g.addWidget(self.lbl_pick, 4, 0)
        g.addWidget(self.cmb_pick, 4, 1)
        # hint 单独占一整行（wordWrap），避免挤在 combo 右边折成三行
        g.addWidget(self.lbl_pick_hint, 5, 0, 1, 2)

        self.btn_pick_delete = QPushButton()
        self.btn_pick_delete.clicked.connect(self._use_canvas_selection_as_delete)
        self.btn_pick_clear_del = QPushButton()
        self.btn_pick_clear_del.clicked.connect(self._clear_delete_list)
        self.btn_pick_clear_sel = QPushButton()
        self.btn_pick_clear_sel.clicked.connect(self._clear_canvas_selection)
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.setSpacing(6)
        pick_row.addWidget(self.btn_pick_delete, 1)
        g.addLayout(pick_row, 6, 0, 1, 2)
        clear_row = QHBoxLayout()
        clear_row.setContentsMargins(0, 0, 0, 0)
        clear_row.setSpacing(6)
        clear_row.addWidget(self.btn_pick_clear_del, 1)
        clear_row.addWidget(self.btn_pick_clear_sel, 1)
        g.addLayout(clear_row, 7, 0, 1, 2)
        for _edit in (self.edit_centre, self.edit_zaxis, self.edit_xz, self.edit_del):
            _edit.textChanged.connect(self._refresh_pick_hint)

        # ── 计算参数 ──
        self.lbl_engine = QLabel()
        self.cmb_engine = QComboBox()
        self.cmb_engine.setMinimumWidth(150)
        try:
            engines = tuple(available_engines())
        except Exception:                                        # noqa: BLE001
            engines = ()
        if not engines:
            engines = (DEFAULT_ENGINE,)
        for name in engines:
            self.cmb_engine.addItem(self._engine_label(name), str(name))
        idx = self.cmb_engine.findData(str(DEFAULT_ENGINE))
        self.cmb_engine.setCurrentIndex(max(0, idx))
        self.lbl_radii = QLabel()
        self.cmb_radii = QComboBox()
        self.cmb_radii.setMinimumWidth(150)
        for value, zh_key, en_key in RADII_OPTIONS:
            self.cmb_radii.addItem("", {"value": value, "label_key": zh_key})
        self.cmb_radii.setCurrentIndex(0)

        g.addWidget(self.lbl_engine, 8, 0)
        g.addWidget(self.cmb_engine, 8, 1)
        g.addWidget(self.lbl_radii, 9, 0)
        g.addWidget(self.cmb_radii, 9, 1)

        self.lbl_R = QLabel()
        self.spn_R = self._radius_spin(3.5)
        self.lbl_mapR = QLabel()
        self.spn_mapR = self._radius_spin(3.5)
        g.addWidget(self.lbl_R, 10, 0)
        g.addWidget(self.spn_R, 10, 1)
        g.addWidget(self.lbl_mapR, 11, 0)
        g.addWidget(self.spn_mapR, 11, 1)

        self.lbl_mesh = QLabel()
        self.spn_mesh = QDoubleSpinBox()
        # 3 位小数 + 与引擎 validate 相同下限（0.005 Å），否则载入 mesh=0.005 的
        # .inp 会被静默夹成 0.01，重算结果和文件不一致。
        self.spn_mesh.setDecimals(3)
        self.spn_mesh.setRange(0.005, 1.0)
        self.spn_mesh.setSingleStep(0.005)
        self.spn_mesh.setValue(0.10)
        self.spn_mesh.setSuffix(" Å")
        self.spn_mesh.setMinimumWidth(92)
        self.lbl_align = QLabel()
        self.cmb_align = QComboBox()
        self.cmb_align.addItem("", 0)
        self.cmb_align.addItem("", 1)
        self.cmb_align.setMinimumWidth(150)
        g.addWidget(self.lbl_mesh, 12, 0)
        g.addWidget(self.spn_mesh, 12, 1)
        g.addWidget(self.lbl_align, 13, 0)
        g.addWidget(self.cmb_align, 13, 1)

        self.lbl_disp = QLabel()
        self.spn_disp = QDoubleSpinBox()
        self.spn_disp.setDecimals(2)
        self.spn_disp.setRange(-20.0, 20.0)      # 与引擎 validate 的 ±20 Å 一致
        self.spn_disp.setSingleStep(0.1)
        self.spn_disp.setValue(0.0)
        self.spn_disp.setSuffix(" Å")
        self.spn_disp.setMinimumWidth(92)
        self.chk_remove_h = QCheckBox()
        self.chk_remove_h.setChecked(True)
        g.addWidget(self.lbl_disp, 14, 0)
        g.addWidget(self.spn_disp, 14, 1)
        g.addWidget(self.chk_remove_h, 15, 0, 1, 2)

        # ── 定向方式（SambVca 原子 / 当前画布视角）──
        self.lbl_orient = QLabel()
        self.cmb_orient = QComboBox()
        self.cmb_orient.addItem("", "sambvca")
        self.cmb_orient.addItem("", "view")
        # 默认「按当前画布视角」（有画布时）：地图朝向与左侧画布一致；没有画布
        # （单独使用/测试）时退回官方原子定向，否则算不了。
        self.cmb_orient.setCurrentIndex(1 if self.glw is not None else 0)
        self.cmb_orient.currentIndexChanged.connect(self._on_orient_changed)
        self.lbl_orient_hint = QLabel()
        self.lbl_orient_hint.setStyleSheet("color:#5b6573;")
        self.lbl_orient_hint.setWordWrap(True)
        g.addWidget(self.lbl_orient, 16, 0)
        g.addWidget(self.cmb_orient, 16, 1)
        g.addWidget(self.lbl_orient_hint, 17, 0, 1, 2)

        # ── 出图样式（替换原来的「配色方案 / 色标自动」一带）──
        self._style_options = _style_options()
        self._palette_options = _palette_options()
        self.lbl_style = QLabel()
        self.cmb_style = QComboBox()
        for key in self._style_options:
            self.cmb_style.addItem("", key)
        self.cmb_style.setCurrentIndex(0)          # 默认 StericRender
        self.cmb_style.currentIndexChanged.connect(self._refresh_draw)
        self.lbl_cmap = QLabel()
        self.cmb_cmap = QComboBox()
        for key in self._palette_options:
            self.cmb_cmap.addItem("", key)
        self.cmb_cmap.setCurrentIndex(0)           # 默认 SambVca 官方配色
        self.cmb_cmap.currentIndexChanged.connect(self._refresh_draw)
        # 风格 / 配色各占一整行（下拉能完整显示 StericRender / SambVca 名称）
        g.addWidget(self.lbl_style, 18, 0)
        g.addWidget(self.cmb_style, 18, 1)
        g.addWidget(self.lbl_cmap, 19, 0)
        g.addWidget(self.cmb_cmap, 19, 1)

        self.chk_contours = QCheckBox()
        self.chk_contours.setChecked(True)
        self.chk_contours.toggled.connect(self._refresh_draw)
        self.chk_skeleton = QCheckBox()
        self.chk_skeleton.setChecked(True)
        self.chk_skeleton.toggled.connect(self._refresh_draw)
        self.chk_skeleton.toggled.connect(self._sync_molecule_scope_enabled)
        # 兼容旧接口/旧测试：原「显示原子投影」复选框已并入「显示分子骨架」
        # （两者语义重叠，统一放在地图风格区）。
        self.chk_atoms = self.chk_skeleton
        self.chk_quad = QCheckBox()
        self.chk_quad.setChecked(True)
        self.chk_quad.toggled.connect(self._refresh_draw)
        self.chk_axes = QCheckBox()
        self.chk_axes.setChecked(True)
        self.chk_axes.toggled.connect(self._refresh_draw)
        g.addWidget(self.chk_contours, 20, 0)
        g.addWidget(self.chk_skeleton, 20, 1)
        g.addWidget(self.chk_quad, 21, 0)
        g.addWidget(self.chk_axes, 21, 1)

        self.lbl_molecule_scope = QLabel()
        self.cmb_molecule_scope = QComboBox()
        self.cmb_molecule_scope.addItem("", True)
        self.cmb_molecule_scope.addItem("", False)
        self.cmb_molecule_scope.currentIndexChanged.connect(
            self._on_molecule_scope_changed)
        g.addWidget(self.lbl_molecule_scope, 22, 0)
        g.addWidget(self.cmb_molecule_scope, 22, 1)

        self.lbl_map_opacity = QLabel()
        self.spn_map_opacity = QDoubleSpinBox()
        self.spn_map_opacity.setDecimals(2)
        self.spn_map_opacity.setRange(0.15, 1.00)
        self.spn_map_opacity.setSingleStep(0.05)
        self.spn_map_opacity.setValue(0.72)
        self.spn_map_opacity.setMinimumWidth(92)
        self.spn_map_opacity.valueChanged.connect(self._refresh_draw)
        g.addWidget(self.lbl_map_opacity, 25, 0)
        g.addWidget(self.spn_map_opacity, 25, 1)

        # 色标：默认固定 ±地图半径；勾选后按数据范围并可手改
        self.chk_auto_color = QCheckBox()
        self.chk_auto_color.setChecked(False)
        self.chk_auto_color.toggled.connect(self._on_auto_color_toggled)
        self.lbl_cmin = QLabel()
        self.spn_cmin = self._color_spin(-3.5)
        self.lbl_cmax = QLabel()
        self.spn_cmax = self._color_spin(3.5)
        limits_row = QHBoxLayout()
        limits_row.setContentsMargins(0, 0, 0, 0)
        limits_row.setSpacing(4)
        for _w in (self.lbl_cmin, self.spn_cmin, self.lbl_cmax, self.spn_cmax):
            limits_row.addWidget(_w)
        limits_row.addStretch(1)
        g.addWidget(self.chk_auto_color, 23, 0, 1, 2)
        g.addLayout(limits_row, 24, 0, 1, 2)

        g.setColumnStretch(1, 1)
        gp.addLayout(g)
        # 下拉框按「固定字符数」算最小宽度：否则像「Bondi×1.17（官方默认）」这种
        # 长文案会把整页最小宽度顶到 700px 以上，右栏就横向溢出了。
        for combo in (self.cmb_engine, self.cmb_radii, self.cmb_cmap, self.cmb_align,
                      self.cmb_style, self.cmb_orient, self.cmb_pick,
                      self.cmb_molecule_scope):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.setMinimumWidth(0)
        self.cmb_align.setMinimumWidth(108)

        self._on_auto_color_toggled(self.chk_auto_color.isChecked())
        self._on_orient_changed()
        self._sync_molecule_scope_enabled()
        return self.grp_params

    def _index_edit(self):
        w = QLineEdit()
        w.setMinimumWidth(88)
        w.setPlaceholderText("1")
        return w

    def _radius_spin(self, value):
        w = QDoubleSpinBox()
        w.setDecimals(2)
        # 与引擎 validate 的范围一致（(0, 100] Å）；真正过密的组合由引擎给出
        # 「网格过密」提示，而不是在这里静默夹值。
        w.setRange(0.10, 100.0)
        w.setSingleStep(0.1)
        w.setValue(value)
        w.setSuffix(" Å")
        w.setMinimumWidth(92)
        return w

    def _color_spin(self, value):
        w = QDoubleSpinBox()
        w.setDecimals(2)
        w.setRange(-20.0, 20.0)
        w.setSingleStep(0.10)
        w.setValue(value)
        w.setMinimumWidth(74)
        return w

    # ── 按钮行 ───────────────────────────────────────────────────────────
    def _build_action_rows(self):
        box = QVBoxLayout()
        box.setSpacing(5)

        run_row = QHBoxLayout()
        run_row.setSpacing(6)
        self.btn_run = QPushButton()
        self.btn_run.setDefault(True)
        self.btn_run.setMinimumHeight(32)
        self.btn_run.clicked.connect(self.start)
        self.btn_cancel = QPushButton()
        self.btn_cancel.setMinimumHeight(32)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setEnabled(False)
        run_row.addWidget(self.btn_run, 1)
        run_row.addWidget(self.btn_cancel)
        box.addLayout(run_row)

        exp_grid = QGridLayout()
        exp_grid.setContentsMargins(0, 0, 0, 0)
        exp_grid.setHorizontalSpacing(6)
        exp_grid.setVerticalSpacing(5)
        self.btn_save_img = QPushButton()
        self.btn_save_img.clicked.connect(self._save_image)
        self.btn_export_data = QPushButton()
        self.btn_export_data.clicked.connect(self._export_data)
        self.btn_export_inp = QPushButton()
        self.btn_export_inp.clicked.connect(self._export_inp)
        self.btn_export_xyz = QPushButton()
        self.btn_export_xyz.clicked.connect(self._export_oriented_xyz)
        for index, w in enumerate(
                (self.btn_save_img, self.btn_export_data,
                 self.btn_export_inp, self.btn_export_xyz)):
            w.setEnabled(False)
            exp_grid.addWidget(w, index // 2, index % 2)
        box.addLayout(exp_grid)
        return box

    # ── 小工具 ───────────────────────────────────────────────────────────
    def _log(self, msg):
        if callable(self._log_func):
            try:
                self._log_func(str(msg))
            except Exception:                                     # noqa: BLE001
                pass

    def _set_status(self, text, level="normal"):
        """直接显示一段已经成型的文字（引擎/系统错误消息等）。"""
        self._status_key = None
        self._status_fmt = {}
        self._status_literal = str(text)
        self._status_level = level
        self._render_status()

    def _set_status_i18n(self, key, level="normal", **fmt):
        """按 i18n 键设置状态行；切语言时会自动重译。"""
        self._status_key = key
        self._status_fmt = dict(fmt)
        self._status_literal = None
        self._status_level = level
        self._render_status()

    def _render_status(self):
        if self._status_key is not None:
            try:
                text = self._t(self._status_key, **self._status_fmt)
            except (KeyError, IndexError, ValueError):
                text = self._status_key
            level = self._status_level
        else:
            text = self._status_literal or ""
            level = self._status_level
        self._status_error = (level == "error")
        self.lbl_status.setText(str(text))
        self.lbl_status.setStyleSheet(
            "color:%s;" % _STATUS_COLORS.get(level, _STATUS_COLORS["normal"]))

    def _engine_label(self, name) -> str:
        key = ENGINE_LABEL_KEY.get(str(name))
        return self._t(key) if key else str(name)

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _default_dir(self) -> Path:
        if self._source_kind == "file" and self._source_path:
            return Path(self._source_path).parent
        return Path(tempfile.gettempdir()) / "MolStudio_steric"

    # ── 结构来源 ─────────────────────────────────────────────────────────
    def _refresh_source_label(self):
        n = len(self._symbols)
        if n == 0:
            self.lbl_source.setText(self._t("src_canvas_empty"))
            return
        if self._source_kind == "file":
            self.lbl_source.setText(self._t("src_file",
                                            name=Path(self._source_path).name, n=n))
        else:
            self.lbl_source.setText(self._t("src_canvas", n=n))

    def refresh_canvas(self):
        """公开入口：从左侧画布重新取结构（同「刷新画布结构」按钮）。"""
        self._refresh_from_canvas()

    def showEvent(self, event):                                    # noqa: N802
        """切到本页时自动同步左侧画布的结构。

        用户通常是「打开分子 → 再点到这一页」；没有这一步的话，面板会一直停在
        建面板时的空画布提示上，得手动点一次「刷新画布结构」。用户显式打开过
        文件（``_source_kind == "file"``）时不覆盖，保持文件优先。
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_host_canvas_visibility)
        if self._busy() or self._source_kind == "file":
            return
        try:
            got = self._get_structure()
        except Exception:                                          # noqa: BLE001
            got = None
        if not got or len(got) < 2:
            if self._symbols:
                self._clear_structure()
            return
        symbols, coords = got
        try:
            coords = np.asarray(coords, dtype=float)
            same = (self._symbols and self._coords is not None
                    and len(symbols) == len(self._symbols)
                    and coords.shape == self._coords.shape
                    and np.array_equal(coords, self._coords))
        except Exception:                                          # noqa: BLE001
            same = False
        if not same:
            self._refresh_from_canvas()

    def hideEvent(self, event):                                    # noqa: N802
        """离开本页时自动关掉画布点选，避免继续抢占画布的左键点击。"""
        try:
            if self._pick_mode != "off":
                self.cmb_pick.setCurrentIndex(0)   # 触发 _on_pick_target_changed('off')
                self._pick_mode = "off"
                self._clear_canvas_selection_quiet()
                self._refresh_pick_hint()
        except Exception:                                          # noqa: BLE001
            pass
        super().hideEvent(event)

    def _refresh_from_canvas(self, *_args, initial=False):
        if self._busy():
            return
        try:
            got = self._get_structure()
        except Exception as exc:                                  # noqa: BLE001
            self._log(self._t("st_open_fail", err=exc))
            got = None
        if not got or len(got) < 2:
            self._clear_structure()
            if not initial:
                self._set_status_i18n("src_canvas_empty", "warn")
            return
        symbols, coords = got
        self._set_structure(symbols, coords, kind="canvas")

    def _same_structure(self, symbols, coords) -> bool:
        """当前面板里的结构与传入的是否完全一致（元素序列 + 坐标）。"""
        if not self._symbols or self._coords is None:
            return False
        if len(symbols) != len(self._symbols) or list(symbols) != list(self._symbols):
            return False
        try:
            return (self._coords.shape == coords.shape
                    and bool(np.array_equal(self._coords, coords)))
        except Exception:                                          # noqa: BLE001
            return False

    def _set_structure(self, symbols, coords, kind="canvas", path=""):
        symbols = [str(s) for s in symbols]
        coords = np.asarray(coords, dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 3 or coords.shape[0] != len(symbols):
            self._clear_structure()
            self._set_status(self._t("st_open_fail", err="bad coordinates"), "error")
            return False
        # 换了分子（元素序列或坐标不同）→ 旧的球心 / z 轴 / xz / 删除序号全部作废。
        # 否则会自动把上一个分子的序号套到新分子上，算出一个"看起来合理"的错值。
        structure_changed = not self._same_structure(symbols, coords)
        self._symbols = symbols
        self._coords = coords
        self._source_kind = kind
        self._source_path = str(path or "")
        if structure_changed:
            for _edit in (self.edit_centre, self.edit_zaxis,
                          self.edit_xz, self.edit_del):
                _edit.clear()
        # 结构变了，旧结果作废
        self._clear_result(redraw=False)
        # 角色字段为空时先自动推荐，省一次点击（.inp 随后会覆盖）
        if not self.edit_centre.text().strip():
            self._auto_roles(silent=True)
        self._refresh_source_label()
        self._show_placeholder()
        self._set_status_i18n("st_load_ok", n=len(symbols))
        self._log(self._t("log_header"))
        self._log(self._t("log_start", n=len(symbols),
                          engine=self._engine_label(self._engine_name()),
                          r=float(self.spn_R.value()),
                          m=float(self.spn_mapR.value()),
                          mesh=float(self.spn_mesh.value())))
        return True

    def _clear_structure(self):
        self._symbols = []
        self._coords = None
        self._source_path = ""
        for _edit in (self.edit_centre, self.edit_zaxis,
                      self.edit_xz, self.edit_del):
            _edit.clear()
        self._clear_result(redraw=False)
        self._refresh_source_label()
        self._show_placeholder()

    def _clear_result(self, redraw=True):
        self._result = None
        self._set_export_enabled(False)
        self._update_result_labels()
        if redraw:
            self._show_placeholder()

    def _open_file_dialog(self):
        if self._busy():
            return
        start = str(self._default_dir())
        path, _f = QFileDialog.getOpenFileName(self, self._t("dlg_open"), start,
                                               self._t("filter_struct"))
        if path:
            self.load_file(path)

    def load_file(self, path) -> bool:
        """载入结构文件；.inp 会同时回填官方参数。供文件对话框与测试使用。"""
        if self._busy():
            return False
        path = str(path)
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".inp":
                job, symbols, positions, _title = read_inp(path)
                ok = self._set_structure(symbols, positions, kind="file", path=path)
                if ok:
                    self._fill_from_job(job)
            elif suffix == ".xyz":
                mol = parse_xyz(path)
                self._set_structure(mol.symbols, np.asarray(mol.positions), kind="file",
                                    path=path)
            elif suffix in (".log", ".out"):
                mol = parse_gaussian_log(path)
                self._set_structure(mol.symbols, np.asarray(mol.positions), kind="file",
                                    path=path)
            elif suffix in (".gjf", ".com"):
                symbols, positions = _parse_cartesian_block(path)
                self._set_structure(symbols, positions, kind="file", path=path)
            else:
                raise ValueError("unsupported file type: %s" % suffix)
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_open_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            QMessageBox.warning(self, self._t("err_title"), msg)
            return False
        if suffix == ".inp":
            self._set_status_i18n("st_load_ok", n=len(self._symbols))
        self._log(self._t("log_roles",
                          centre=self.edit_centre.text().strip() or "—",
                          z=self.edit_zaxis.text().strip() or "—",
                          xz=self.edit_xz.text().strip() or "—",
                          **{"del": self.edit_del.text().strip() or "—"}))
        return True

    def _fill_from_job(self, job):
        """把 SambVcaJob 的参数回填到各输入框（.inp 载入时用）。"""
        def _spec(atoms):
            return ",".join(str(int(i)) for i in (atoms or []))

        def _set(edit, text):
            edit.setText(text)

        _set(self.edit_centre, _spec(job.centre_atoms))
        _set(self.edit_zaxis, _spec(job.z_axis_atoms))
        _set(self.edit_xz, _spec(getattr(job, "xz_plane_atoms", [])))
        _set(self.edit_del, _spec(job.delete_atoms))
        self.spn_R.setValue(abs(float(job.sphere_radius)))
        map_r = getattr(job, "map_radius", None)
        self.spn_mapR.setValue(abs(float(map_r)) if map_r else abs(float(job.sphere_radius)))
        self.spn_mesh.setValue(abs(float(job.mesh)))
        self.spn_disp.setValue(float(job.displacement))
        self.chk_remove_h.setChecked(bool(job.remove_h))
        self.cmb_align.setCurrentIndex(1 if int(job.align_z) else 0)
        radii = str(getattr(job, "radii_set", "bondi-scaled") or "bondi-scaled")
        for i in range(self.cmb_radii.count()):
            data = self.cmb_radii.itemData(i)
            if isinstance(data, dict) and data.get("value") == radii:
                self.cmb_radii.setCurrentIndex(i)
                break
        self.lbl_source.setText(self._t("src_file",
                                        name=Path(self._source_path).name,
                                        n=len(self._symbols)))

    def _auto_roles(self, *_args, silent=False):
        if not self._symbols:
            if not silent:
                self._warn(self._t("st_no_struct"))
            return
        try:
            roles = auto_roles(self._symbols, self._coords)
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_auto_roles_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            if not silent:
                QMessageBox.warning(self, self._t("err_title"), msg)
            return
        if not isinstance(roles, dict):
            roles = {}
        centre = str(roles.get("centre", "") or "")
        zaxis = str(roles.get("z_axis", "") or "")
        xz = str(roles.get("xz", "") or "")
        dele = str(roles.get("delete", "") or "")
        self.edit_centre.setText(centre)
        self.edit_zaxis.setText(zaxis)
        self.edit_xz.setText(xz)
        self.edit_del.setText(dele)
        self._set_status_i18n("st_auto_roles", centre=centre or "—",
                              z=zaxis or "—", xz=xz or "—",
                              **{"del": dele or "—"})
        self._log("  " + self.lbl_status.text())

    def _warn(self, msg):
        self._set_status(msg, "error")
        QMessageBox.warning(self, self._t("err_title"), msg)

    # ── 定向方式 / 画布视角 ──────────────────────────────────────────────
    def _orient_mode(self) -> str:
        data = self.cmb_orient.currentData()
        if data is None:
            # 没有画布时无法做视角定向，退回官方原子定向
            return "view" if self.glw is not None else "sambvca"
        return "sambvca" if str(data) == "sambvca" else "view"

    def _on_orient_changed(self, *_args):
        view = self._orient_mode() == "view"
        # 置灰（值保留）：view 模式不用这些字段，但切回原子模式时要能继续用。
        # Disp 是 SambVca 定向沿 z 的平移，视图定向下引擎直接忽略，故一并置灰，
        # 避免"填了 2.1 却毫无变化"的困惑。
        for w in (self.edit_zaxis, self.edit_xz, self.cmb_align, self.spn_disp):
            w.setEnabled(not view)
        self._refresh_orient_hint()

    def _refresh_orient_hint(self):
        view = self._orient_mode() == "view"
        key = "orient_view_hint" if view else "orient_sambvca_hint"
        self.lbl_orient_hint.setText(self._t(key))
        self.lbl_orient_hint.setVisible(True)

    def _view_rotation(self):
        """读画布当前朝向（世界 → 屏幕的 3×3）；取不到返回 None。"""
        if self.glw is None:
            return None
        try:
            from molstudio.core.surface_projection import camera_rotation
        except Exception:                                          # noqa: BLE001
            return None
        try:
            R = camera_rotation(self.glw)
        except Exception:                                          # noqa: BLE001
            return None
        if R is None:
            return None
        try:
            R = np.asarray(R, dtype=float)
        except (TypeError, ValueError):
            return None
        if R.shape != (3, 3) or not np.all(np.isfinite(R)):
            return None
        return R

    def _sync_canvas_orientation(self):
        """把左侧画布旋转/平移到本次计算所用的定向（球心居中）。

        「SambVca 官方定向」与画布当前朝向无关，这一步让画布和地图朝向完全一致；
        「按画布视角」下也能用（相当于把球心原子移到画面中心）。
        """
        res = self._result
        if res is None:
            self._set_status_i18n("st_need_result", "warn")
            return
        if self.glw is None:
            self._set_status_i18n("st_sync_canvas_fail", "warn", err="no canvas")
            return
        orient = dict(getattr(res, "orientation", None) or {})
        R = orient.get("rotation_matrix")
        if R is None:
            self._set_status_i18n("st_sync_canvas_fail", "warn",
                                  err="no rotation matrix")
            return
        try:
            R = np.asarray(R, dtype=float).reshape(3, 3)
            cam = getattr(self.glw, "cam", None)
            if cam is None:
                raise RuntimeError("no camera on the canvas")
            centre = np.asarray(orient.get("centre") or [0.0, 0.0, 0.0],
                                dtype=float)
            # 画布内部坐标用 Bohr：把球心投到画面中心（view_x = view_y = 0）
            view_centre = R @ (centre * _ANGSTROM_IN_BOHR)
            cam.q = _quaternion_from_matrix(R)
            cam.t = np.array([-view_centre[0], -view_centre[1], 0.0],
                             dtype=float)
            if hasattr(self.glw, "update"):
                self.glw.update()
            self._set_status_i18n("st_sync_canvas_ok", "ok")
            self._log("  " + self._t("st_sync_canvas_ok"))
        except Exception as exc:                                   # noqa: BLE001
            self._set_status_i18n("st_sync_canvas_fail", "warn", err=exc)
            self._log("  " + self.lbl_status.text())

    def _engine_supports_view(self) -> bool:
        """引擎 ``compute`` 是否已支持 ``view_rotation``（契约由 core 侧提供）。"""
        try:
            import inspect
            sig = inspect.signature(compute)
        except (TypeError, ValueError):                            # pragma: no cover
            return True
        params = sig.parameters
        if "view_rotation" in params:
            return True
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

    def _view_tilt_deg(self, res=None):
        """视图倾角：相机法线与世界 z 轴的夹角（度）。identity → 0°。"""
        orient = dict(getattr(res, "orientation", None) or {}) if res is not None else {}
        raw = orient.get("view_tilt_deg")
        try:
            if raw is not None and np.isfinite(float(raw)):
                return float(raw)
        except (TypeError, ValueError):
            pass
        R = getattr(res, "view_rotation", None) if res is not None else None
        if R is None:
            R = self._last_view_rotation
        if R is None:
            return None
        try:
            R = np.asarray(R, dtype=float)
        except (TypeError, ValueError):
            return None
        if R.shape != (3, 3) or not np.all(np.isfinite(R)):
            return None
        # view()[:3,:3] 把世界映射到屏幕：第 3 行第 3 列 = 世界 z 与相机轴的余弦
        c = float(np.clip(R[2, 2], -1.0, 1.0))
        return float(np.degrees(np.arccos(c)))

    # ── 画布点选原子 ─────────────────────────────────────────────────────
    def _ids_from_edit(self, edit):
        return _ids_from_text(edit.text())

    def _ids_text(self, ids):
        items = [str(int(i)) for i in (ids or [])]
        if not items:
            return "—"
        if len(items) > 12:                 # 状态行/提示里别塞满几百个号
            return "%s, … (%d)" % (", ".join(items[:10]), len(items))
        return ", ".join(items)

    def _canvas_selection_1based(self):
        if self.glw is None:
            return []
        try:
            sel = list(getattr(self.glw, "_selected_atoms", []) or [])
        except Exception:                                          # noqa: BLE001
            return []
        out = []
        for v in sel:
            try:
                out.append(int(v) + 1)
            except (TypeError, ValueError):
                continue
        return sorted({i for i in out if i > 0})

    def _sync_canvas_highlight(self, ids_1based):
        """把 1-based 原子号写回画布选中集（0-based）并刷新高亮。"""
        if self.glw is None:
            return
        try:
            idx = sorted({int(i) - 1 for i in (ids_1based or []) if int(i) > 0})
        except (TypeError, ValueError):
            idx = []
        try:
            self.glw._selected_atoms = idx
        except Exception:                                          # noqa: BLE001
            try:
                self.glw._selected_atoms[:] = idx
            except Exception:                                  # noqa: BLE001
                return
        try:
            self.glw._regenerate_atoms()
        except Exception:                                          # noqa: BLE001
            pass
        upd = getattr(self.glw, "update", None)
        if callable(upd):
            try:
                upd()
            except Exception:                                      # noqa: BLE001
                pass

    def _clear_canvas_selection_quiet(self):
        if self.glw is None:
            return
        try:
            self.glw._clear_selection()
        except Exception:                                          # noqa: BLE001
            self._sync_canvas_highlight([])

    def _clear_canvas_selection(self):
        """按钮：清空画布选择（不动删除列表）。"""
        if self.glw is None:
            self._set_status_i18n("st_pick_no_glw", "warn")
            self._refresh_pick_hint()
            return
        self._clear_canvas_selection_quiet()
        self._set_status_i18n("st_pick_cleared")
        self._refresh_pick_hint()

    def _pick_target_ids(self, mode=None):
        mode = self._pick_mode if mode is None else mode
        if mode == "centre":
            return self._ids_from_edit(self.edit_centre)
        if mode == "z_axis":
            return self._ids_from_edit(self.edit_zaxis)
        if mode == "xz":
            return self._ids_from_edit(self.edit_xz)
        if mode in ("delete", "restore"):
            return self._ids_from_edit(self.edit_del)
        return []

    def _on_pick_target_changed(self, *_args):
        mode = str(self.cmb_pick.currentData() or "off")
        self._pick_mode = mode
        if mode == "off":
            self._clear_canvas_selection_quiet()
            self._set_status_i18n("st_pick_off")
        else:
            # 进入某个目标时先把该字段现有的原子号高亮出来，用户能对上号
            self._sync_canvas_highlight(self._pick_target_ids(mode))
        self._refresh_pick_hint()

    def _refresh_pick_hint(self, *_args):
        mode = self._pick_mode
        key = PICK_HINT_KEYS.get(mode, "pick_hint_off")
        text = self._t(key)
        if mode != "off":
            ids = self._pick_target_ids(mode)
            if ids:
                text = "%s  %s" % (text, self._t("pick_stat_fmt", ids=self._ids_text(ids)))
        if hasattr(self, "lbl_pick_hint"):
            self.lbl_pick_hint.setText(text)

    def _toggle_index(self, edit, idx):
        ids = self._ids_from_edit(edit)
        if idx in ids:
            ids.remove(idx)
        else:
            ids.append(idx)
        ids = sorted(set(ids))
        edit.setText(",".join(str(i) for i in ids))
        return ids

    def _on_canvas_atom_picked(self, idx_1based):
        """画布左键点击原子的回调（1-based，多面板共用）。

        画布左键点击本身就是 toggle 多选（选中集在 ``glw._selected_atoms``，
        0-based），所以这里只做「按当前目标同步字段 + 高亮」。
        """
        if self._pick_mode == "off" or self.glw is None:
            return
        try:
            if not self.isVisible():
                return
        except Exception:                                          # noqa: BLE001
            pass
        try:
            idx = int(idx_1based)
        except (TypeError, ValueError):
            return
        if idx <= 0:
            return
        if self._symbols and idx > len(self._symbols):
            return

        mode = self._pick_mode
        if mode == "centre":
            self.edit_centre.setText(str(idx))
            ids = [idx]
            self._sync_canvas_highlight(ids)
            self._set_status_i18n("st_pick_centre", "ok", idx=idx)
        elif mode == "z_axis":
            ids = self._toggle_index(self.edit_zaxis, idx)
            self._sync_canvas_highlight(ids)
            self._set_status_i18n("st_pick_zaxis", "ok", ids=self._ids_text(ids))
        elif mode == "xz":
            ids = self._toggle_index(self.edit_xz, idx)
            self._sync_canvas_highlight(ids)
            self._set_status_i18n("st_pick_xz", "ok", ids=self._ids_text(ids))
        elif mode == "delete":
            # 画布当前选中集（多选）就是删除列表；左键点击已经 toggle 过了
            ids = self._canvas_selection_1based()
            self.edit_del.setText(",".join(str(i) for i in ids))
            self._sync_canvas_highlight(ids)
            self._set_status_i18n("st_pick_delete", "ok", ids=self._ids_text(ids))
        elif mode == "restore":
            ids = [i for i in self._ids_from_edit(self.edit_del) if i != idx]
            self.edit_del.setText(",".join(str(i) for i in ids))
            self._sync_canvas_highlight(ids)
            self._set_status_i18n("st_pick_restore", "ok", idx=idx)
        self._refresh_pick_hint()

    def _use_canvas_selection_as_delete(self):
        """按钮：把画布当前选中集写成删除列表（用户要的「选原子 → 删除」）。"""
        if self.glw is None:
            self._set_status_i18n("st_pick_no_glw", "warn")
            return
        ids = self._canvas_selection_1based()
        self.edit_del.setText(",".join(str(i) for i in ids))
        self._sync_canvas_highlight(ids)
        self._set_status_i18n("st_pick_delete",
                              "ok" if ids else "warn", ids=self._ids_text(ids))
        self._refresh_pick_hint()

    def _clear_delete_list(self):
        self.edit_del.clear()
        self._sync_canvas_highlight([])
        self._set_status_i18n("st_pick_delete", "ok", ids="—")
        self._refresh_pick_hint()

    # ── 参数收集 ─────────────────────────────────────────────────────────
    def _engine_name(self) -> str:
        data = self.cmb_engine.currentData()
        return str(data or DEFAULT_ENGINE)

    def _params(self) -> dict:
        radii_data = self.cmb_radii.currentData()
        radii = (radii_data.get("value") if isinstance(radii_data, dict)
                 else "bondi-scaled")
        return {
            "centre": self.edit_centre.text().strip(),
            "z_axis": self.edit_zaxis.text().strip(),
            "xz": self.edit_xz.text().strip(),
            "delete": self.edit_del.text().strip(),
            "sphere_radius": float(self.spn_R.value()),
            "map_radius": float(self.spn_mapR.value()),
            "mesh": float(self.spn_mesh.value()),
            "remove_h": bool(self.chk_remove_h.isChecked()),
            "align_z": int(self.cmb_align.currentData() or 0),
            "displacement": float(self.spn_disp.value()),
            "radii_set": str(radii or "bondi-scaled"),
            "orient_mode": self._orient_mode(),
        }

    # ── 出图选项 ─────────────────────────────────────────────────────────
    def _cmap_name(self) -> str:
        return str(self.cmb_cmap.currentData() or "sambvca")

    def _map_style(self) -> str:
        return str(self.cmb_style.currentData() or "stericrender")

    def _fixed_range(self, res=None):
        """官方 / StericRender 一致的固定色标：±地图半径。"""
        res = self._result if res is None else res
        radius = 0.0
        if res is not None:
            try:
                radius = abs(float(getattr(res, "map_radius", 0.0) or 0.0))
            except (TypeError, ValueError):
                radius = 0.0
        if not np.isfinite(radius) or radius <= 0.0:
            try:
                radius = abs(float(self.spn_mapR.value()))
            except (TypeError, ValueError):
                radius = 0.0
        if not np.isfinite(radius) or radius <= 0.0:
            radius = 3.5
        return -radius, radius

    def _data_limits(self, res=None):
        """网格数据的真实 z 范围（勾选「色标按数据范围」时用）。"""
        res = self._result if res is None else res
        lo = hi = None
        cr = getattr(res, "color_range", None) if res is not None else None
        if cr is not None and len(cr) == 2:
            try:
                lo, hi = float(cr[0]), float(cr[1])
            except (TypeError, ValueError):
                lo = hi = None
        if lo is None or hi is None or not np.isfinite(lo) or not np.isfinite(hi) \
                or hi <= lo:
            grid = getattr(res, "map", None) if res is not None else None
            z = np.asarray(getattr(grid, "z", []), dtype=float)
            finite = z[np.isfinite(z)] if z.size else z
            if finite.size:
                lo, hi = float(finite.min()), float(finite.max())
            else:
                return self._fixed_range(res)
        if hi <= lo:
            hi = lo + 1e-6
        return lo, hi

    def _color_range(self):
        """给 render / 旧绘图路径的 color_range：None = 固定 ±R（官方一致）。"""
        if not self.chk_auto_color.isChecked() or self._result is None:
            return None
        lo = float(self.spn_cmin.value())
        hi = float(self.spn_cmax.value())
        if hi <= lo:
            hi = lo + 1e-6
        return lo, hi

    def _clip_molecule(self):
        """True = StericRender-style disk clip; False = retain the whole molecule."""
        value = self.cmb_molecule_scope.currentData()
        return True if value is None else bool(value)

    def _sync_molecule_scope_enabled(self, *_args):
        enabled = self.chk_skeleton.isChecked()
        self.lbl_molecule_scope.setEnabled(enabled)
        self.cmb_molecule_scope.setEnabled(enabled)

    def _on_molecule_scope_changed(self, *_args):
        self._refresh_draw()

    def _on_auto_color_toggled(self, checked):
        checked = bool(checked)
        # 只有勾选「按数据范围」后，min/max 才可编辑
        self.spn_cmin.setEnabled(checked)
        self.spn_cmax.setEnabled(checked)
        self._sync_color_spins()
        self._refresh_draw()

    def _sync_color_spins(self):
        if self._result is None:
            lo, hi = self._fixed_range()
        elif self.chk_auto_color.isChecked():
            lo, hi = self._data_limits()
        else:
            lo, hi = self._fixed_range()
        for spin, val in ((self.spn_cmin, lo), (self.spn_cmax, hi)):
            spin.blockSignals(True)
            spin.setValue(float(val))
            spin.blockSignals(False)

    def _fill_color_spins(self):
        """兼容旧调用点：按当前色标模式刷新 min/max。"""
        self._sync_color_spins()

    # ── 计算 ─────────────────────────────────────────────────────────────
    def start(self):
        if self._busy():
            return
        if not self._symbols or self._coords is None:
            self._warn(self._t("st_no_struct"))
            return

        params = self._params()
        engine = self._engine_name()
        # 「按当前画布视角」定向：计算前必须从画布相机拿到 3×3 旋转
        view_rotation = None
        if params.get("orient_mode") == "view":
            view_rotation = self._view_rotation()
            if view_rotation is None:
                self._warn(self._t("st_view_no_camera"))
                return
            if not self._engine_supports_view():
                self._warn(self._t("st_view_unsupported"))
                return
        self._last_view_rotation = view_rotation

        try:
            try:
                err, _parsed = validate(self._symbols, self._coords, params,
                                        lang=self.lang, view_rotation=view_rotation)
            except TypeError as exc:
                # 旧版引擎 validate 还没有 view_rotation 形参
                if "view_rotation" not in str(exc):
                    raise
                err, _parsed = validate(self._symbols, self._coords, params,
                                        lang=self.lang)
        except StericError as exc:
            err = str(exc)
        except Exception as exc:                                  # noqa: BLE001
            err = str(exc)
        if err:
            msg = self._t("st_failed", err=err)
            self._set_status(msg, "error")
            self._log("  " + msg)
            QMessageBox.warning(self, self._t("err_title"), err)
            return

        self._log(self._t("log_header"))
        self._log(self._t("log_start", n=len(self._symbols),
                          engine=self._engine_label(engine),
                          r=params["sphere_radius"], m=params["map_radius"],
                          mesh=params["mesh"]))
        self._log(self._t("log_roles", centre=params["centre"] or "—",
                          z=params["z_axis"] or "—", xz=params["xz"] or "—",
                          **{"del": params["delete"] or "—"}))

        self._set_busy(True)
        self._set_status(self._t("st_busy", step=self._t("step_orient")))

        self._worker = StericWorker(self._symbols, self._coords, params,
                                    engine, self.lang, parent=self,
                                    view_rotation=view_rotation)
        self._worker.log.connect(self._on_worker_log)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.done.connect(self._on_worker_done)
        self._worker.start()

    def cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._set_status(self._t("st_cancelling"), "warn")
            self._log("  " + self._t("st_cancelling"))

    def _on_worker_log(self, text):
        self._log(str(text).rstrip("\n"))

    def _on_worker_progress(self, step, text):
        step = str(step or "")
        key = "step_" + step
        label = self._t(key) if key in _TR["zh"] else (text or step)
        self._set_status(self._t("st_busy", step=label))

    def _on_worker_done(self, payload):
        self._worker = None
        self._set_busy(False)
        if not payload.get("ok"):
            if payload.get("cancelled"):
                self._set_status_i18n("st_cancel", "warn")
                self._log("  " + self._t("log_cancel"))
                return
            err = payload.get("error", "?")
            msg = self._t("st_failed", err=err)
            self._set_status(msg, "error")
            self._log("  " + msg)
            if payload.get("traceback"):
                self._log(payload["traceback"])
            QMessageBox.warning(self, self._t("err_title"), err)
            return

        result = payload.get("result")
        self._result = result
        try:
            self._sync_color_spins()
        except Exception:                                         # noqa: BLE001
            pass
        self._update_result_labels()
        self._redraw()
        self._tabs.setCurrentIndex(0)
        self._set_export_enabled(True)

        elapsed = getattr(result, "elapsed", None) or {}
        try:
            t_total = float(elapsed.get("total", 0.0) or 0.0)
        except (TypeError, ValueError):
            t_total = 0.0
        v = float(getattr(result, "percent_buried", float("nan")))
        self._set_status_i18n("st_done", "ok", v=v, t=t_total)
        self._log(self._t("log_done", v=v,
                          ne=float(result.quadrant_percent.get("NE", float("nan"))),
                          nw=float(result.quadrant_percent.get("NW", float("nan"))),
                          sw=float(result.quadrant_percent.get("SW", float("nan"))),
                          se=float(result.quadrant_percent.get("SE", float("nan")))))

    def _set_busy(self, busy):
        self.btn_run.setEnabled(not busy)
        self.btn_cancel.setEnabled(bool(busy))
        self.btn_canvas.setEnabled(not busy)
        self.btn_open.setEnabled(not busy)
        self.btn_auto.setEnabled(not busy)
        # 计算中不要改原子角色 / 点选目标
        for w in (self.cmb_pick, self.btn_pick_delete, self.btn_pick_clear_del,
                  self.btn_pick_clear_sel, self.cmb_orient):
            w.setEnabled(not busy)
        if busy:
            self._set_export_enabled(False)
        else:
            self._set_export_enabled(self._result is not None)
            # 恢复「定向方式」对 z 轴 / xz / AlignZ 的置灰状态
            self._on_orient_changed()

    def _set_export_enabled(self, enabled):
        has = bool(enabled) and self._result is not None
        for w in (self.btn_save_img, self.btn_export_data,
                  self.btn_export_inp, self.btn_export_xyz):
            w.setEnabled(has)
        # 「同步画布朝向」需要结果 + 可交互的画布
        if getattr(self, "btn_sync_canvas", None) is not None:
            self.btn_sync_canvas.setEnabled(has and self.glw is not None)
        # 视图定向（ViewProj）无法写进官方 .inp：官方格式只有 SambVca 的
        # 球心 / z 轴 / xz 原子字段，导出的文件既不能复现结果、z 轴为空时
        # 官方程序还会报错。此时禁用 .inp 导出并提示改用 JSON（含旋转矩阵）。
        view_mode = str(getattr(self._result, "orient_mode", "sambvca")) == "view"
        if has and view_mode:
            self.btn_export_inp.setEnabled(False)
            self.btn_export_inp.setToolTip(self._t("tip_inp_view_mode"))
        else:
            self.btn_export_inp.setToolTip(self._t("tip_export_inp"))

    # ── 结果文字 ─────────────────────────────────────────────────────────
    def _update_result_labels(self):
        res = self._result
        if res is None:
            self.lbl_vbur.setText(self._t("vbur_none"))
            self.lbl_res_engine.setText("")
            for axis, lab in self.quad_labels.items():
                lab.setText("%s  %s" % (axis, self._t("diag_none")))
            self._fill_octant_labels(None)
            for lab in (self.lbl_vol_buried, self.lbl_vol_free, self.lbl_vol_sphere):
                lab.setText("")
            self.lbl_atoms_sel.setText("")
            self.lbl_atoms_del.setText("")
            for lab in (self.lbl_diag_axis, self.lbl_diag_cons, self.lbl_diag_roll,
                        self.lbl_diag_xz, self.lbl_diag_disp,
                        self.lbl_diag_orient, self.lbl_diag_view):
                lab.setText("")
            self.lbl_diag_view.setVisible(False)
            self._rebuild_warnings(None)
            return

        self.lbl_vbur.setText(self._t("vbur_fmt",
                                      v=float(getattr(res, "percent_buried",
                                                      float("nan")))))
        self.lbl_res_engine.setText(self._t("engine_fmt",
                                            name=self._engine_label(getattr(res, "engine", ""))))
        self._fill_quadrant_labels(res)
        self._fill_octant_labels(res)
        self._fill_volume_labels(res)
        self._fill_atom_counts(res)
        self._fill_diag_labels(res)
        self._rebuild_warnings(res)

        try:
            self.grp_result.setToolTip(format_orientation_report(res, self.lang))
        except Exception:                                         # noqa: BLE001
            self.grp_result.setToolTip("")

    def _fill_quadrant_labels(self, res):
        quad = dict(getattr(res, "quadrant_percent", None) or {})
        for axis, lab in self.quad_labels.items():
            lab.setText("%s  %s" % (axis, self._fmt_pct(quad.get(axis))))

    def _fill_octant_labels(self, res):
        octants = dict(getattr(res, "octant_percent", None) or {}) if res is not None else {}
        for key, lab in self.oct_labels.items():
            val = octants.get(key)
            lab.setText("%s  %s" % (key, self._fmt_pct(val)))

    def _fill_volume_labels(self, res):
        self.lbl_vol_buried.setText(self._t(
            "vol_fmt", name=self._t("vol_buried"),
            v=float(getattr(res, "buried_volume", float("nan")))))
        self.lbl_vol_free.setText(self._t(
            "vol_fmt", name=self._t("vol_free"),
            v=float(getattr(res, "free_volume", float("nan")))))
        self.lbl_vol_sphere.setText(self._t(
            "vol_fmt", name=self._t("vol_sphere"),
            v=float(getattr(res, "sphere_volume", float("nan")))))

    def _fill_atom_counts(self, res):
        sel = getattr(res, "selected_atoms", None) or []
        exc = getattr(res, "excluded_atoms", None) or []
        self.lbl_atoms_sel.setText(self._t("atoms_sel", n=len(sel)))
        self.lbl_atoms_del.setText(self._t("atoms_del", n=len(exc)))

    def _fill_diag_labels(self, res):
        orient = dict(getattr(res, "orientation", None) or {})
        axis_len = orient.get("axis_length")
        cons = orient.get("axis_consistency")
        roll = orient.get("roll_deg")
        xz_frac = orient.get("xz_projection_fraction")
        disp = orient.get("displacement_shift")
        self.lbl_diag_axis.setText(self._t(
            "diag_axis", v=self._fmt(axis_len, "%.3f Å")))
        self.lbl_diag_cons.setText(self._t(
            "diag_cons", v=self._fmt(cons, "%.2f")))
        self.lbl_diag_roll.setText(self._t(
            "diag_roll", v=self._fmt(roll, "%.1f°")))
        try:
            fv = float(xz_frac)
            if np.isfinite(fv):
                self.lbl_diag_xz.setText(self._t("diag_xz", v="%.0f %%" % (fv * 100.0)))
            else:
                self.lbl_diag_xz.setText(self._t("diag_xz", v=self._t("diag_none")))
        except (TypeError, ValueError):
            self.lbl_diag_xz.setText(self._t("diag_xz", v=self._t("diag_none")))
        self.lbl_diag_disp.setText("Disp  " + self._fmt(disp, "%.2f Å"))

        # 定向方式：view 模式显示「视图倾角」，原子模式保留原有诊断
        mode = str(getattr(res, "orient_mode", "") or "").lower()
        view_mode = mode == "view"
        mode_key = "orient_short_view" if view_mode else "orient_short_sambvca"
        self.lbl_diag_orient.setText(
            self._t("diag_orient", v=self._t(mode_key)))
        tilt = self._view_tilt_deg(res) if view_mode else None
        if tilt is not None:
            self.lbl_diag_view.setText(self._t("diag_view_tilt", v="%.1f°" % tilt))
            self.lbl_diag_view.setVisible(True)
        else:
            self.lbl_diag_view.setText("")
            self.lbl_diag_view.setVisible(False)

    def _fmt(self, val, spec):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return self._t("diag_none")
        if not np.isfinite(v):
            return self._t("diag_none")
        if v == 0.0:                       # 把 -0.0 归一成正零，避免输出 "-0.00"
            v = 0.0
        return spec % v

    def _fmt_pct(self, val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return self._t("diag_none")
        if not np.isfinite(v):
            return self._t("diag_none")
        return "%.2f %%" % v

    def _rebuild_warnings(self, res):
        # 清空旧提示
        while self._warn_layout.count():
            item = self._warn_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if res is None:
            self.lbl_warn_title.setVisible(False)
            return
        items = list(getattr(res, "warnings", None) or [])
        orient = dict(getattr(res, "orientation", None) or {})
        if not items:
            for raw in orient.get("warnings") or []:
                if isinstance(raw, (list, tuple)) and raw:
                    items.append((raw[0], raw[1] if len(raw) > 1 else {}))
        notes = []
        for raw in orient.get("notes") or []:
            if isinstance(raw, (list, tuple)) and raw:
                notes.append((raw[0], raw[1] if len(raw) > 1 else {}))

        for item in items:
            self._append_warning(item, warning=True)
        for item in notes:
            self._append_warning(item, warning=False)
        self.lbl_warn_title.setVisible(bool(items or notes))

    def _append_warning(self, item, warning=True):
        try:
            text = format_diag(item, self._t, lang=self.lang)
        except TypeError:
            try:
                text = format_diag(item, self._t)
            except Exception:                                     # noqa: BLE001
                text = str(item)
        except Exception:                                         # noqa: BLE001
            text = str(item)
        prefix = "⚠ " if warning else "· "
        lab = QLabel(prefix + str(text))
        lab.setWordWrap(True)
        if warning:
            lab.setStyleSheet("color:#c26a00;")
        else:
            lab.setStyleSheet("color:#7a8595;")
        self._warn_layout.addWidget(lab)

    # ── 出图 ─────────────────────────────────────────────────────────────
    def _refresh_draw(self, *_args):
        if self._busy():
            return
        if self._result is None:
            return
        self._redraw()

    def _redraw(self):
        """按当前视图 / 出图样式重画（2D 与 3D 共用同一份 result.map，不重算）。"""
        if self._result is None:
            self._show_placeholder()
            return
        res = self._result
        mode3d = int(self.cmb_view.currentData() or 0) == 1
        drawn_by_render = False
        try:
            drawn_by_render = self._draw_with_render(res, mode3d)
        except Exception as exc:                                  # noqa: BLE001
            # 出图模块异常 → 退回内置 matplotlib 路径，保证页面上始终有图
            self._log("  render fallback: %s" % exc)
        if not drawn_by_render:
            try:
                if mode3d:
                    self._draw_3d(res)
                else:
                    self._draw_2d(res)
            except Exception as exc:                              # noqa: BLE001
                self._draw_placeholder_text(self._t("st_failed", err=exc))
                self._log("  " + self._t("st_failed", err=exc))
        elif mode3d:
            # 3D 地形右侧的色标已经标了 z (Å)；再画一份 z 轴标题会和 0.0/−0.5
            # 的刻度叠在一起。这里统一去掉 3D 的 zlabel（出图模块侧也可能画）。
            self._hide_3d_zlabel()
        self._canvas.draw_idle()

    def _hide_3d_zlabel(self):
        try:
            for ax in self.figure.axes:
                if getattr(ax, "name", "") == "3d":
                    ax.set_zlabel("")
        except Exception:                                          # noqa: BLE001
            pass

    def _draw_with_render(self, res, mode3d) -> bool:
        """优先用 ``molstudio.core.steric.render``；不可用时返回 False。"""
        api = _render_api()
        if api is None:
            return False
        draw_map, draw_terrain_3d = api
        figure = self.figure
        figure.clear()
        color_range = self._color_range()
        palette = self._cmap_name()
        if mode3d:
            draw_terrain_3d(figure, res, palette=palette, color_range=color_range,
                            show_contours=self.chk_contours.isChecked(),
                            lang=self.lang, title=None)
        else:
            clip_skeleton = self._clip_molecule()
            background, extent = (self._canvas_map_background(res)
                                  if self.chk_skeleton.isChecked() and clip_skeleton
                                  else (None, None))
            draw_map(figure, res, palette=palette, style=self._map_style(),
                     color_range=color_range,
                     show_contours=self.chk_contours.isChecked(),
                     contour_levels=15,
                     show_skeleton=self.chk_skeleton.isChecked(),
                     clip_skeleton=clip_skeleton,
                     show_quadrants=self.chk_quad.isChecked(),
                     show_colorbar=True,
                     show_axes_triad=self.chk_axes.isChecked(),
                     map_opacity=self.spn_map_opacity.value(),
                     background_image=background,
                     background_extent=extent,
                     lang=self.lang, title=None)
        return True

    def _canvas_map_background(self, res):
        """裁出与地图同一相机、同一尺度下的画布快照。

        快照只用于 2D 显示。只有当前相机与计算定向一致时才使用，避免旋转
        画布后把旧朝向的分子硬贴到新地图上。裁剪范围与 ``draw_map`` 的
        ±1.06R 坐标轴一致，球心落在裁剪框中心。
        """
        glw = self.glw
        if glw is None or not self._clip_molecule():
            return None, None
        orient = dict(getattr(res, "orientation", None) or {})
        calc_r = orient.get("rotation_matrix")
        current_r = self._view_rotation()
        if calc_r is None or current_r is None:
            return None, None
        try:
            calc_r = np.asarray(calc_r, dtype=float).reshape(3, 3)
            if not np.allclose(calc_r, current_r, atol=2e-3):
                return None, None
            image = glw.grabFramebuffer()
            if not isinstance(image, QImage) or image.isNull():
                return None, None
            logical_w = max(1, int(glw.width()))
            logical_h = max(1, int(glw.height()))
            dpr_x = float(image.width()) / logical_w
            dpr_y = float(image.height()) / logical_h
            if abs(dpr_x - dpr_y) > 0.05:
                return None, None
            dpr = dpr_y

            radius = float(getattr(res, "map_radius", 0.0) or 0.0)
            if radius <= 0:
                grid = getattr(res, "map", None)
                x = np.asarray(getattr(grid, "x", []), dtype=float)
                radius = float(np.nanmax(np.abs(x))) if x.size else 1.0
            lim = 1.06 * radius

            centre = np.asarray(orient.get("centre") or [0.0, 0.0, 0.0],
                                dtype=float) * _ANGSTROM_IN_BOHR
            sx, sy, _visible = glw._world_to_screen(*centre.tolist())
            half_height_bohr = float(glw.cam.half_height())
            px_per_angstrom = logical_h / (2.0 * half_height_bohr / _ANGSTROM_IN_BOHR)
            half_px = int(round(lim * px_per_angstrom * dpr))
            cx = int(round(float(sx) * dpr))
            cy = int(round(float(sy) * dpr))
            side = half_px * 2
            if side < 16 or cx - half_px < 0 or cy - half_px < 0:
                return None, None
            if cx + half_px > image.width() or cy + half_px > image.height():
                return None, None

            crop = image.copy(QRect(cx - half_px, cy - half_px, side, side))
            crop = crop.convertToFormat(QImage.Format_RGBA8888)
            if crop.isNull():
                return None, None
            bpl = int(crop.bytesPerLine())
            ptr = crop.bits()
            if ptr is None:
                return None, None
            ptr.setsize(bpl * crop.height())
            rgba = np.frombuffer(ptr, dtype=np.uint8)
            rgba = rgba.reshape(crop.height(), bpl)[:, :crop.width() * 4]
            rgba = rgba.reshape(crop.height(), crop.width(), 4).copy()
            return rgba, (-lim, lim, -lim, lim)
        except Exception:                                  # noqa: BLE001
            return None, None

    def _legacy_colormap(self):
        """旧绘图路径的配色：``sambvca`` 等非 matplotlib 名称退到 turbo。"""
        name = self._cmap_name()
        try:
            return colormaps[name].copy()
        except Exception:                                          # noqa: BLE001
            pass
        for fallback in ("turbo", "jet"):
            try:
                return colormaps[fallback].copy()
            except Exception:                                      # noqa: BLE001
                continue
        from matplotlib.colors import LinearSegmentedColormap       # 极端兜底
        return LinearSegmentedColormap.from_list(
            "sambvca", ["#2166ac", "#67a9cf", "#f7f7f7", "#fddbc7", "#b2182b"])

    def _placeholder_text(self) -> str:
        if not self._symbols:
            return self._t("hint_empty")
        return self._t("hint_ready")

    def _draw_placeholder_text(self, text=None):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_axis_off()
        ax.text(0.5, 0.5, text if text is not None else self._placeholder_text(),
                ha="center", va="center", fontsize=10, color="#7a8595",
                transform=ax.transAxes, linespacing=1.6)

    def _show_placeholder(self):
        if self._result is None:
            self._draw_placeholder_text()
            self._canvas.draw_idle()

    def _map_arrays(self, res):
        grid = getattr(res, "map", None)
        x = np.asarray(getattr(grid, "x", []), dtype=float).reshape(-1)
        y = np.asarray(getattr(grid, "y", []), dtype=float).reshape(-1)
        z = np.asarray(getattr(grid, "z", []), dtype=float)
        if z.ndim != 2:
            return None
        if z.shape != (y.size, x.size) and z.shape == (x.size, y.size):
            z = z.T
        if z.shape != (y.size, x.size):
            return None
        return x, y, z

    def _draw_2d(self, res):
        arrays = self._map_arrays(res)
        fig = self.figure
        fig.clear()
        if arrays is None:
            self._draw_placeholder_text(self._t("hint_need_map"))
            return
        x, y, z = arrays
        ax = fig.add_subplot(111)
        zm = np.ma.masked_invalid(z)
        color_range = self._color_range()
        vmin, vmax = color_range if color_range is not None else self._fixed_range(res)
        cmap = self._legacy_colormap()
        cmap.set_bad("#e6e9ee")
        dx = float(x[1] - x[0]) if x.size > 1 else 0.1
        dy = float(y[1] - y[0]) if y.size > 1 else 0.1
        extent = [x[0] - dx / 2.0, x[-1] + dx / 2.0,
                  y[0] - dy / 2.0, y[-1] + dy / 2.0]
        im = ax.imshow(zm, origin="lower", extent=extent, cmap=cmap,
                       vmin=vmin, vmax=vmax, aspect="equal",
                       interpolation="bilinear", zorder=1)
        ax.set_facecolor("#f7f8fa")
        if self.chk_contours.isChecked():
            try:
                finite = z[np.isfinite(z)]
                if finite.size:
                    lo = max(float(finite.min()), float(vmin))
                    hi = min(float(finite.max()), float(vmax))
                    if hi > lo:
                        X, Y = np.meshgrid(x, y)
                        ax.contour(X, Y, zm, levels=np.linspace(lo, hi, 9),
                                   colors="#3b4450", linewidths=0.45,
                                   alpha=0.55, zorder=2)
            except Exception:                                     # noqa: BLE001
                pass

        radius = float(getattr(res, "map_radius", 0.0) or 0.0)
        if radius <= 0:
            radius = max(abs(float(x[0])), abs(float(x[-1])),
                         abs(float(y[0])), abs(float(y[-1]))) or 1.0
        view_radius = radius
        if not self._clip_molecule():
            pos = np.asarray(getattr(res, "oriented_positions", None), dtype=float)
            if pos.ndim == 2 and pos.shape[1] == 3 and pos.size:
                finite_xy = pos[:, :2][np.isfinite(pos[:, :2])]
                if finite_xy.size:
                    view_radius = max(radius,
                                      float(np.max(np.abs(finite_xy))) + 0.45)
        lim = view_radius * 1.02
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_xlabel("x (Å)", fontsize=9)
        ax.set_ylabel("y (Å)", fontsize=9)
        ax.tick_params(labelsize=8)

        if self.chk_quad.isChecked():
            ax.axhline(0.0, color="#5b6573", lw=0.8, ls=(0, (4, 3)), zorder=3)
            ax.axvline(0.0, color="#5b6573", lw=0.8, ls=(0, (4, 3)), zorder=3)
            r = radius * 0.70
            for label, (px, py) in (("NE", (r, r)), ("NW", (-r, r)),
                                    ("SW", (-r, -r)), ("SE", (r, -r))):
                ax.text(px, py, label, ha="center", va="center", fontsize=8,
                        color="#3b4450", fontweight="bold", zorder=6,
                        bbox=dict(boxstyle="round,pad=0.16", fc="white",
                                  ec="none", alpha=0.55))

        ax.add_patch(Circle((0.0, 0.0), radius, fill=False, ec="#8a94a3",
                            lw=0.8, ls=(0, (2, 2)), zorder=4))

        if self.chk_skeleton.isChecked():
            clip_patch = None
            if self._clip_molecule():
                clip_patch = Circle((0.0, 0.0), radius, transform=ax.transData)
            self._plot_projection(ax, res, clip_patch=clip_patch)

        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.set_label("z (Å)", fontsize=9)
        cb.ax.tick_params(labelsize=8)
        try:
            fig.tight_layout(pad=0.2)
        except Exception:                                         # noqa: BLE001
            pass

    def _plot_projection(self, ax, res, clip_patch=None):
        pos = getattr(res, "oriented_positions", None)
        if pos is None:
            return
        pos = np.asarray(pos, dtype=float)
        if pos.ndim != 2 or pos.shape[1] != 3:
            return
        symbols = list(getattr(res, "symbols", None) or self._symbols)
        for sym, xyz in zip(symbols, pos):
            s = str(sym)
            if s.upper() == "H":
                continue                     # 氢原子投影太密，只标重原子
            color = ELEMENT_COLORS.get(s, ELEMENT_COLORS.get(s.capitalize(), "#9aa4b2"))
            point = ax.scatter([xyz[0]], [xyz[1]], s=62, c=[color],
                               edgecolors="#1f2937", linewidths=0.6, zorder=5)
            label = ax.text(xyz[0], xyz[1], s, ha="center", va="center",
                            fontsize=7.0, color="#111827", zorder=6,
                            clip_on=True)
            if clip_patch is not None:
                point.set_clip_path(clip_patch)
                label.set_clip_path(clip_patch)

    def _draw_3d(self, res):
        arrays = self._map_arrays(res)
        fig = self.figure
        fig.clear()
        if arrays is None:
            self._draw_placeholder_text(self._t("hint_need_map"))
            return
        x, y, z = arrays
        ax = fig.add_subplot(111, projection="3d")
        zm = np.ma.masked_invalid(z)
        color_range = self._color_range()
        vmin, vmax = color_range if color_range is not None else self._fixed_range(res)
        cmap = self._legacy_colormap()
        cmap.set_bad("#e6e9ee")
        X, Y = np.meshgrid(x, y)
        surf = ax.plot_surface(X, Y, zm.filled(np.nan), cmap=cmap,
                               vmin=vmin, vmax=vmax,
                               linewidth=0, antialiased=False,
                               rstride=1, cstride=1)
        radius = float(getattr(res, "map_radius", 0.0) or 0.0)
        if radius <= 0:
            radius = max(abs(float(x[0])), abs(float(x[-1]))) or 1.0
        ax.set_xlim(-radius, radius)
        ax.set_ylim(-radius, radius)
        # z 范围按网格里有限值的实际 min/max（不是球半径）：否则高处的峰顶会被切掉
        finite = z[np.isfinite(z)]
        if finite.size:
            zlo, zhi = float(finite.min()), float(finite.max())
        else:
            zlo, zhi = -radius, 0.0
        span = zhi - zlo
        pad = 0.06 * span if span > 1e-9 else 0.1
        ax.set_zlim(zlo - pad, zhi + pad)
        ax.set_xlabel("x (Å)", fontsize=9, labelpad=6)
        ax.set_ylabel("y (Å)", fontsize=9, labelpad=6)
        ax.tick_params(labelsize=7)
        ax.view_init(elev=32, azim=-58)
        try:
            ax.set_box_aspect((1.0, 1.0, 0.55))
        except Exception:                                         # noqa: BLE001
            pass
        cb = fig.colorbar(surf, ax=ax, shrink=0.62, pad=0.04)
        cb.set_label("z (Å)", fontsize=8)
        cb.ax.tick_params(labelsize=7)
        try:
            fig.tight_layout(pad=0.2)
        except Exception:                                         # noqa: BLE001
            pass

    # ── 导出 ─────────────────────────────────────────────────────────────
    def _need_result(self) -> bool:
        if self._result is None:
            self._set_status_i18n("st_need_result", "warn")
            return False
        return True

    def _save_image(self):
        if not self._need_result():
            return
        default = str(self._default_dir() / "steric_map.png")
        path, _f = QFileDialog.getSaveFileName(self, self._t("dlg_save_img"),
                                               default, self._t("filter_img"))
        if not path:
            return
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".png")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            self._redraw()
            self.figure.savefig(str(p), dpi=300, facecolor="white",
                                bbox_inches="tight")
        except Exception as exc:                                  # noqa: BLE001
            QMessageBox.warning(self, self._t("dlg_save_img"), str(exc))
            return
        self._saved(p)

    def _export_data(self):
        if not self._need_result():
            return
        default = str(self._default_dir() / "steric_map.csv")
        path, _f = QFileDialog.getSaveFileName(self, self._t("dlg_save_data"),
                                               default, self._t("filter_data"))
        if not path:
            return
        p = Path(path)
        suffix = p.suffix.lower()
        if not suffix:
            p = p.with_suffix(".csv")
            suffix = ".csv"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if suffix == ".json":
                save_json(self._result, p)
            else:
                save_grid_csv(self._result, p)
        except Exception as exc:                                  # noqa: BLE001
            QMessageBox.warning(self, self._t("dlg_save_data"), str(exc))
            return
        self._saved(p)

    def _export_inp(self):
        if not self._need_result():
            return
        res = self._result
        if str(getattr(res, "orient_mode", "sambvca")) == "view":
            # 兜底：按钮本应已禁用，防止通过快捷键/旧状态导出不可复现的文件
            self._set_status_i18n("st_inp_view_mode", "warn")
            self._log("  " + self._t("st_inp_view_mode"))
            return
        symbols, positions = self._result_structure(res)
        if not symbols or positions is None:
            self._set_status_i18n("st_need_result", "warn")
            return
        default = str(self._default_dir() / "steric_job.inp")
        path, _f = QFileDialog.getSaveFileName(self, self._t("dlg_save_inp"),
                                               default, self._t("filter_inp"))
        if not path:
            return
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".inp")
        title = Path(self._source_path).name if self._source_path else "MolStudio steric map"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            job = getattr(res, "job", None)
            write_inp(p, job, symbols, positions, title=title)
        except Exception as exc:                                  # noqa: BLE001
            QMessageBox.warning(self, self._t("dlg_save_inp"), str(exc))
            return
        self._saved(p)

    def _export_oriented_xyz(self):
        if not self._need_result():
            return
        default = str(self._default_dir() / "steric_oriented.xyz")
        path, _f = QFileDialog.getSaveFileName(self, self._t("dlg_save_xyz"),
                                               default, self._t("filter_xyz"))
        if not path:
            return
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".xyz")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            save_oriented_xyz(self._result, p)
        except Exception as exc:                                  # noqa: BLE001
            QMessageBox.warning(self, self._t("dlg_save_xyz"), str(exc))
            return
        self._saved(p)

    def _result_structure(self, res):
        symbols = list(getattr(res, "symbols", None) or self._symbols)
        positions = getattr(res, "positions", None)
        if positions is None:
            positions = self._coords
        if positions is None:
            return symbols, None
        return symbols, np.asarray(positions, dtype=float)

    def _saved(self, path):
        self._set_status_i18n("st_saved", "ok", path=path)
        self._log(self._t("log_saved", path=path))

    # ── 生命周期 ─────────────────────────────────────────────────────────
    def shutdown(self):
        """停后台线程。引擎单次计算受内存上限约束（体素 < 5e7，实测 ≤3 s），
        cancel 后 8 s 仍未退出属于异常；此时 terminate() 只是进程退出前的
        兜底（numpy 计算中强制结束线程本身不安全，正常路径不会走到）。"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            if not self._worker.wait(8000):
                self._worker.terminate()
                self._worker.wait(2000)
        self._worker = None
