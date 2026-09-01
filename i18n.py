"""
i18n: 国际化翻译模块
提供 TR 翻译字典 + tr() 翻译函数，支持中/英文切换。
"""

# ── Current language ──
_CURRENT_LANG = "zh"


def tr(key, **fmt):
    """翻译函数：根据全局 _CURRENT_LANG 返回对应语言的字符串。"""
    s = TR.get(key, {}).get(_CURRENT_LANG, key)
    return s.format(**fmt) if fmt else s


# ═══════════════════════════════════════════════════════════════
#  翻译字典
# ═══════════════════════════════════════════════════════════════
TR = {
    # ── Window title ──
    "win_title": {
        "zh": "MolStudio — 分子可视化与量子化学分析 [PyQt 中文版]",
        "en": "MolStudio — Molecular Visualization & Quantum Chemical Analysis [PyQt]"
    },
    # ── Header ──
    "title_label": {
        "zh": "◆  GXNU MolStudio  ◆",
        "en": "◆  GXNU MOLSTUDIO  ◆"
    },
    "subtitle_label": {
        "zh": "分子可视化与量子化学分析  |  v1.0 PyQt 中文版",
        "en": "Molecular Visualization & Quantum Chemical Analysis  |  v1.0 PyQt Edition"
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
    "tab_setup": {"zh": "轨道", "en": "MO"},
    "tab_style": {"zh": "VMD 渲染", "en": "VMD Render"},
    "tab_paths": {"zh": "⚙️  路径设置", "en": "⚙️  Path Settings"},
    "btn_paths": {"zh": "⚙️ 路径设置（Multiwfn&&VMD）", "en": "⚙️ Paths (Multiwfn&&VMD)"},
    "tab_preview": {"zh": "▶️  预览运行", "en": "▶️  Preview"},
    "tab_tools": {"zh": "🛠️  工具", "en": "🛠️  Tools"},
    "tab_log": {"zh": "📋  运行日志", "en": "📋  Log"},
    # ── GroupBox titles ──
    "grp_paths": {"zh": "软件路径", "en": "SOFTWARE PATHS"},
    "grp_acknowledgments": {"zh": "致谢", "en": "Acknowledgments"},
    "grp_input": {"zh": "输入文件", "en": "INPUT"},
    "grp_vmd": {"zh": "VMD 控制台", "en": "VMD CONSOLE"},
    "grp_canvas": {"zh": "可视化画布", "en": "VISUALIZATION CANVAS"},
    "grp_orbital": {"zh": "轨道选择", "en": "ORBITAL SELECTION"},
    "grp_render": {"zh": "渲染参数", "en": "RENDER PARAMETERS"},
    "grp_output": {"zh": "输出目录", "en": "OUTPUT DIRECTORY"},
    "grp_actions": {"zh": "操作", "en": "ACTIONS"},
    "grp_aim_vmd": {"zh": "AIM 期刊级出图", "en": "AIM PUBLICATION RENDER"},
    "aim_vmd_style": {"zh": "风格:", "en": "Style:"},
    "aim_vmd_hint": {
        "zh": "VMD / Tachyon 路径请在主窗口 ⚙️ 路径设置中配置",
        "en": "Set VMD / Tachyon paths in main-window ⚙️ Path Settings"
    },
    "aim_vmd_preview": {"zh": "在 VMD 中预览", "en": "Preview in VMD"},
    "aim_vmd_render": {"zh": "渲染当前视角为 PNG", "en": "Render Current View (PNG)"},
    "msg_aim_unavailable": {
        "zh": "AIM 模块当前不可用",
        "en": "AIM module is unavailable"
    },
    "grp_live": {"zh": "LIVE ADJUSTMENTS  (VMD 打开后可用)", "en": "LIVE ADJUSTMENTS  (available once VMD opens)"},
    "grp_hydrogen": {"zh": "隐藏氢原子", "en": "HIDE HYDROGEN"},
    "grp_draw_bond": {"zh": "绘制虚线键", "en": "DRAW DASHED LINE"},
    "grp_log": {"zh": "运行日志", "en": "LOG"},
    # ── Path panel ──
    "lbl_multiwfn": {"zh": "Multiwfn:", "en": "Multiwfn:"},
    "lbl_vmd": {"zh": "VMD:", "en": "VMD:"},
    "lbl_tachyon": {"zh": "Tachyon:", "en": "Tachyon:"},
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
    "btn_preview_both": {"zh": "预览", "en": "Preview"},
    "tab_orbit_hint": {"zh": "双击行在画布中渲染", "en": "Double-click row to render in canvas"},
    "lbl_orbit_hint": {"zh": "双击行可视化", "en": "Double-click row to visualize"},
    # ── 自旋密度 ──
    "spin_density_btn": {"zh": "自旋密度", "en": "Spin Density"},
    "spin_density_iso": {"zh": "等值面:", "en": "Isosurface:"},
    "spin_density_iso_tip": {"zh": "自旋密度等值面阈值，建议 0.0005 ~ 0.005", "en": "Spin density isosurface, suggest 0.0005~0.005"},
    "spin_density_gen": {"zh": "生成自旋密度（需开壳层 fchk）…", "en": "Generating spin density (open-shell fchk required)..."},
    "spin_density_done": {"zh": "自旋密度已显示：{name}", "en": "Spin density shown: {name}"},
    "spin_density_failed": {"zh": "自旋密度生成失败（请确认 fchk 为开壳层且 Multiwfn 路径正确）", "en": "Spin density generation failed (check open-shell fchk and Multiwfn path)"},
    "spin_density_need_fchk": {"zh": "请先选择 .fchk 文件（开壳层）", "en": "Select an open-shell .fchk file first"},
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
    "rb_full": {"zh": "有阴影", "en": "Shadows"},
    "rb_medium": {"zh": "无阴影", "en": "No Shadows"},
    "chk_auto": {"zh": "自动渲染 (无预览, 批处理模式)", "en": "Auto render (no preview, batch mode)"},
    "chk_open": {"zh": "完成后打开文件夹", "en": "Open folder after completion"},
    "chk_trans_raster": {"zh": "透明模式:", "en": "Transparency:"},
    "trans_off": {"zh": "关闭", "en": "Off"},
    "trans_vmd": {"zh": "VMD 一致", "en": "VMD-match"},
    "trans_raster3d": {"zh": "立体增强", "en": "Raster3D"},
    "trans_orig": {"zh": "传统算法", "en": "Orig"},
    "tooltip_full": {"zh": "开启阴影和环境光遮蔽，画面立体感强", "en": "Shadows and ambient occlusion on, strong 3D depth"},
    "tooltip_medium": {"zh": "关闭阴影，画面更干净，速度略快", "en": "Shadows off, cleaner look, slightly faster"},
    "tooltip_trans_raster": {"zh": "选择 Tachyon 透明渲染模式", "en": "Select Tachyon transparency rendering mode"},
    "lbl_threads": {"zh": "渲染线程数:", "en": "Render threads:"},
    "tooltip_threads": {"zh": "影响出图速度，根据自己电脑核心数设置", "en": "Affects rendering speed; set according to your CPU cores"},
    "vmd_console_title": {"zh": "VMD 控制台", "en": "VMD Console"},
    # ── Output panel ──
    "hint_output_default": {"zh": "(默认: 与输入相同)", "en": "(default: same as input)"},
    "placeholder_output": {"zh": "输出目录...", "en": "Output directory..."},
    # ── Buttons panel ──
    "btn_run_cubes": {"zh": "生成cub", "en": "Generate cub"},
    "btn_preview": {"zh": "预览", "en": "Preview"},
    "btn_render_view": {"zh": "渲染出图", "en": "Render Image"},
    "btn_flip_phase": {"zh": "翻转相位", "en": "Flip Phase"},
    "flip_choose": {"zh": "选择要翻转的轨道:", "en": "Select orbital to flip:"},
    "flip_all": {"zh": "翻转全部", "en": "Flip All"},
    "log_flip_all": {"zh": "已翻转全部 {n} 个轨道", "en": "Flipped all {n} orbitals"},
    "log_flip_one": {"zh": "已翻转轨道 {label}", "en": "Flipped orbital {label}"},
    "btn_preview_mol": {"zh": "VMD 预览分子", "en": "VMD Preview Mol"},
    "tab_charge": {"zh": "🧪  电荷分析", "en": "🧪  Charge"},
    "tab_bond_order": {"zh": "🔗  键级", "en": "🔗  Bond Order"},
    "tab_charge_bond": {"zh": "电荷键级", "en": "Charge"},
    "tab_nbo": {"zh": "NBO", "en": "NBO"},
    "tab_esp": {"zh": "ESP", "en": "ESP"},
    "tab_igmh": {"zh": "IGMH", "en": "IGMH"},
    "tab_aim": {"zh": "AIM", "en": "AIM"},
    "tab_etsnocv": {"zh": "NOCV", "en": "NOCV"},
    "tab_mpp": {"zh": "MPP", "en": "MPP"},
    "tab_viz": {"zh": "可视化", "en": "View"},
    "tab_log": {"zh": "日志", "en": "Log"},
    "tab_orbit_table": {"zh": "📊  轨道表", "en": "📊  Orbitals"},
    "btn_sync_vmd": {"zh": "同步到VMD", "en": "Sync to VMD"},
    "btn_sync_vmd_tip": {"zh": "弹出新窗口：左侧 VMD 可视化界面，右侧 VMD 控制台按钮，并把画布场景同步进去",
                        "en": "Open a window with the VMD view on the left and its controls on the right, then sync the canvas scene"},
    "msg_sync_no_molecule": {"zh": "画布中没有分子，请先载入 .fchk/.log 或可视化一个轨道",
                             "en": "No molecule in the canvas — load an .fchk/.log or visualize an orbital first"},
    "msg_no_vmd": {"zh": "未找到 VMD，请先在 ⚙️ 路径设置中配置",
                   "en": "VMD not found — configure it in ⚙️ Path Settings first"},
    "log_sync_vmd_start": {"zh": "同步画布场景到 VMD（{n} 个表面）…",
                           "en": "Syncing canvas scene to VMD ({n} surfaces)…"},
    "log_sync_vmd_ok": {"zh": "VMD 场景同步完成",
                        "en": "VMD scene synced"},
    "log_sync_vmd_fail": {"zh": "VMD 同步失败: {err}",
                          "en": "VMD sync failed: {err}"},
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
    "lbl_keep_indices": {"zh": "保留编号:", "en": "Keep H:"},
    "placeholder_h_indices": {"zh": "留空=全部", "en": "empty=all"},
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
    "msg_paths_save_fail": {
        "zh": "保存路径配置失败：{err}\n\n配置文件位置：{cfg}\n请检查该目录是否有写入权限（杀毒软件也可能拦截写入）。",
        "en": "Failed to save path config: {err}\n\nConfig file: {cfg}\nCheck write permission on that folder (antivirus may block it)."
    },
    "dlg_select_input_folder": {"zh": "选择输入文件夹", "en": "Select Input Folder"},
    "dlg_select_input_file": {"zh": "选择输入文件", "en": "Select Input File"},
    "dlg_input_filter": {
        "zh": "所有支持的 (*.fchk *.log *.out *.cub *.cube *.xyz *.molden *.molden.input);;格式化 Checkpoint (*.fchk);;Gaussian Log (*.log *.out);;XYZ (*.xyz);;Cube (*.cub *.cube);;所有文件 (*.*)",
        "en": "All Supported (*.fchk *.log *.out *.cub *.cube *.xyz *.molden *.molden.input);;Formatted Checkpoint (*.fchk);;Gaussian Log (*.log *.out);;XYZ (*.xyz);;Cube (*.cub *.cube);;All Files (*.*)"
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
    # ── Charge & bond order panel ──
    "grp_charge": {"zh": "原子电荷", "en": "ATOMIC CHARGES"},
    "grp_bond": {"zh": "Mayer 键级", "en": "MAYER BOND ORDERS"},
    # ── VMD live adjustments / misc (main window) ──
    "lbl_dg_iso": {"zh": "δg等值面:", "en": "δg isovalue:"},
    "lbl_ext_radius": {"zh": "极值点半径:", "en": "Extrema radius:"},
    "chk_ext_values": {"zh": "极值点数值", "en": "Extrema values"},
    "chk_colorbar": {"zh": "色标条", "en": "Color scale"},
    "tab_beta": {"zh": "β 轨道", "en": "β orbitals"},
    "msg_gl_unavailable": {
        "zh": "OpenGL 画布不可用",
        "en": "OpenGL canvas unavailable"},
    "msg_gl_install_hint": {
        "zh": "OpenGL 画布不可用\n请安装: pip install PyOpenGL PyOpenGL-accelerate",
        "en": "OpenGL canvas unavailable\nInstall: pip install PyOpenGL PyOpenGL-accelerate"},
    "msg_need_pyopengl": {
        "zh": "需要安装 PyOpenGL: pip install PyOpenGL",
        "en": "PyOpenGL required: pip install PyOpenGL"},
    "dlg_select_orb_gl": {"zh": "选择轨道", "en": "Select Orbitals"},
    "lbl_select_orb_gl": {
        "zh": "选择要在 OpenGL 中预览的轨道：",
        "en": "Select orbitals to preview in OpenGL:"},
    "msg_select_orbital_first": {
        "zh": "请先选中一个轨道",
        "en": "Please select an orbital first"},
    "msg_select_orbital_vis": {
        "zh": "请先选中一个轨道，或在画布中可视化轨道后再点此按钮",
        "en": "Select an orbital, or visualize one in the canvas first"},
}
