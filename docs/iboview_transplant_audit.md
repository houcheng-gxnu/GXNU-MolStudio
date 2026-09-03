# MolStudio GL 渲染内核：IboView 移植部分盘点（行号级）

> 范围：`ovcanvas/_glwidget.py`（渲染内核，约 6290 行）
> 目的：合规自查 —— 区分「IboView 逐字移植的表达」（重写候选）与「自研/通用算法/其他来源」。
> 依据：IboView © 2015 Gerald Knizia, GPLv3；官方 README 含"请勿分发修改版"的意愿声明。
> 状态：**已由主核对 + 独立子核对完成**（子核对 16 项 + 全文 grep 补充，见文末附注）

## 图例

- **A = 数值/结构逐字照抄**（IboView 表达，衍生风险高，重写候选）
- **B = 算法思路复刻、代码自写**（方法本身不受版权保护，可辩护；观感若靠 A 类数值则需联动重写）
- **C = 仅取用默认参数/常量或注释引用**（低风险）
- **D = 非 IboView**（MolCanvas/课题组自研、GaussView/Jmol/CPK/Bondi 等公开来源）

> ⚠️ 前提声明：文件头 7–11 行已自认"部分 shader/原子表/默认参数逐字移植自 IboView (GPLv3)，
> 本项目作为 IboView 衍生作品依 GPLv3 发布"。以下分级用于评估"重写哪些可脱离衍生身份"；
> 在重写完成前，项目整体仍按该声明以 GPLv3 衍生作品对待。

---

## 第一类：数据表（A 类主体，重写工作量小但必须处理）

| 行号区间 | 内容 | 判定 | 证据 |
|---|---|---|---|
| 90–102 | `_ATOM_DRAW_RADII` 原子绘制半径表（104 项） | **A** | 注释：copied 1:1 from `IvDataOptions.cpp`, GetAtomDrawRadius() |
| 169–183 | `_IBO_ELEMENT_COLORS_HEX` 元素颜色表（110 项，Rasmol CPK-new） | **A** | 注释：`IvDataOptions.cpp, ElementColors[110]`；碳改灰 |
| 262–275 | `_COVALENT_RADII_BOHR` 共价半径表（Bohr，~110 项） | **A** | 注释：IboView's g_CovalentRadii，`src/Common/CxAtomData.cpp`；Bohr→Å 换算后用于 GenerateBonds |
| 281–294 | `_VDW_RADII_A` vdW 半径表 | **D** | 注释：标准 **Bondi (1964)** 公开单键表（H 1.20, C 1.70…），非 IboView 独有 |
| 315–327 | `ATOM_DRAW_SCALE=0.225`、`BOND_DRAW_SCALE=0.18`、`BOND_RADIUS_FACTOR=1.3`、`BOND_THINNING_DEFAULT=0.72`、键距上限 1.8/1.3 | **A** | 注释：IboView drawing scales / default BondRadiusFactor / m_BondThinning |
| 331–342 | `IBOVIEW_DEFAULTS` dict（IsoResolution/IsoThreshold/FadeType/FadeWidth/FadeBias/DepthPeelingLayers=4/OrbitalOpacity=0.8…） | **A** | 注释：from `prop_FView3d.cpp.inl` |
| 1006–1026 | `_ICOSA_COORDS` / `_ICOSA_TRIS` 二十面体顶点+三角面 | **A** | 注释：取自 IboView `IvMesh.cpp` MakeIcosahedron |

## 第二类：着色器与光照（A/B 混合，重写核心）

| 行号区间 | 内容 | 判定 | 证据 |
|---|---|---|---|
| 58–81 | 注释 + `IBO_DEFAULT_A/O`、`SHININESS_PRESETS`（not very/reasonably/extra/sooooo shiny 等 5 组 ShaderReg 数值） | **A** | 注释：transplanted verbatim from `preset_*.js` |
| 472–562 | `_GLSL_COMMON`：pixel_common.glsl 移植（灯方向 D_L0-2、light_term 公式、calc_base_color、Fade、边缘 alpha 增强） | **A** | 注释：1:1 from `shader/pixel_common.glsl`；含 IboView 公式行 |
| 501–508 | `light_term`：cDiffuse/cSpecular 公式（ShaderReg0-3、pow 16/64） | **A** | IboView 光照模型逐条注释 |
| 515–560 | `calc_base_color`：三灯循环、alpha/N.z 增强、FadeType=1 雾化 | **A** | IboView 移植 |
| 564–602 | `_MV_GRAD_STOPS`/`_MV_GRAD_IDS`：MolViewer 球体径向渐变（13+ 类） | **D** | 注释：逐字换算自 molcanvas（MolCanvas = 侯成课题组自研），含 Houk/gau_default 渐变 |
| 604–629+ | `_gen_mv_ramp_glsl`：把 MolCanvas 渐变编译成 GLSL | **D** | MolCanvas 来源 |
| 690–732+ | 注释区：u_MvGrad=0 → IboView 三灯 Phong；>0 → MolViewer 渐变 | **B** | 双通道设计，其中 IboView 通道依赖第一类数值 |
| 692–705 | `FRAG_ORB`：轨道片元着色器（u_MvGrad>0 → MolViewer 渐变，否则 calc_base_color） | **B** | 组合 _GLSL_COMMON（A 类）+ 自研渐变，主框架自写 |
| 707–719+ | `FRAG_ORB_DP`：depth-peeling 变体（注释 "mirrors pixel5_orb_dp.glsl"） | **A/B** | 深度比较逻辑（texelFetch 与 gl_FragCoord.z 比较）为标准 depth-peeling 写法；是否逐字待查原文 |

## 第三类：几何生成与交互（B/C/D 混合）

| 行号区间 | 内容 | 判定 | 证据 |
|---|---|---|---|
| 1029–1051 | `make_icosahedron`：flat 面法线，60 顶点（选中标记形状） | **B** | 复用 IboView 表但生成逻辑通用；形状可换（注释：可换形状） |
| 1054–1080+ | `make_torus`：参数圆环（选中标记另一形状） | **D** | 参数化通用几何 |
| 1114–1152 | `make_cylinder` / `make_tapered_cylinder`：键圆柱（收尾锥形半键） | **B** | 注释提及 IboView ball-and-stick 观感；几何生成自写 |
| 1155–1209 | `make_dashed_bond_geometry`：点状虚线键（小球串） | **D** | 自研替代实现 |
| ~1220–1270 | `style_params`：vcube surface_mat → IboView shader registers 映射（o_reg/a_reg 基值取 IBO_DEFAULT_O/A）+ 扩展材质默认 | **A/B** | 注释 "defaults reproduce IboView exactly"；映射逻辑自写，基值与默认值照抄 |
| 1537–1623 | `Camera`：arcball + IboView 风格正交投影（CAM_DIST=100、BASE_EXTENT=8.0、half_height=8/zoom） | **A/B** | 注释：mirror IboView FView3d::ResetProjectionAndZoom；算法通用但常量照抄 |
| 3937–4014+ | `_gen_atoms`：原子球（AtomicRadii×ATOM_DRAW_SCALE）+ `_gen_bonds` 键生成（GenerateBonds 几何启发式 r≤0.5(bf_i+bf_j)(cov_i+cov_j)；双阈值 rf_tight/rf_loose；收尾半圆柱） | **A/B** | 注释：IboView GenerateBonds heuristic；判定公式照抄，实现自写 |
| 4262–4312 | `_gen_selection_marker`：选中标记（默认二十面体 1.8×原子半径；颜色 0.4×原子色+0.6×白、alpha 0.5；支持 sphere/torus/glow 形状与呼吸动画） | **A/B** | 注释：IboView 移植（IvView3D.cpp，MakeIcosahedron(1.8)）；几何形状已可换，但默认形状与配色规则照 IboView |

## 第四类：渲染主循环与状态管理（B/C）

| 行号区间 | 内容 | 判定 | 证据 |
|---|---|---|---|
| 1724–1729 | depth peeling 层数初始化（=IBOVIEW_DEFAULTS['DepthPeelingLayers']=4） | **C** | 默认参数引用 |
| 2294–2315 | `set_phase_colors`：逐相位覆盖等值面配色（延迟上传模式，注释提及 IboView deferred upload） | **B/C** | 功能自写；"延迟上传"是通用 GL 模式 |
| 2317–2332 | `flip_phase`：交换正/负相位色（等价 IboView chkBox_FlipPhase 的 swap(cIsoMinus,cIsoPlus)） | **B/C** | 功能等价、实现自写 |
| 2417–2436 | `_apply_shininess` / `set_shininess`：应用 SHININESS_PRESETS 覆盖 a_reg/o_reg | **C** | 查表调用（数值表属 A 类） |
| 2964–3004+ | `export_image`：分块(tile)离屏高分辨率重渲染导出（600 DPI、透明背景、glReadPixels 拼图） | **B/D** | 注释：参照 IboView 导出**思路**（真高分重渲而非拉伸）；实现为自研分块方案 |
| 5189–5217 | `_projection`：IboView-style 正交投影（half-height=BASE_EXTENT/zoom，near=0.02·d，far=2·d） | **A/B** | 注释：mirrors FView3d::ResetProjectionAndZoom；常量照抄，正交投影本身通用 |
| 5426–5510 | `render_transparent_depth_peeling`：front-to-back depth peeling | **B** | 注释：following FView3d::RenderScene；算法公开（2001），结构自写 |
| 5511–5580+ | `render_transparent_sorted_fallback`：画家算法回退 | **D** | 自研回退 |
| 5593–5635 | `set_iboview_uniforms`：上传 ShaderReg/Fade/DiffuseColor + 扩展材质 | **B** | 函数名自明；依赖第一/二类数值 |

## 第五类：UI 控件默认值（C）

| 行号区间 | 内容 | 判定 |
|---|---|---|
| 5852–5878 | 等值面组：IboView 相对阈值模式（IsoThreshold 默认 80.0%，50–99 滑块） | C（默认值+功能开关，语义引用） |
| 5880–5899 | 绝对 isovalue 控件 + 不透明度默认 0.8（=OrbitalOpacity） | C（默认值） |
| 5939–5969 | 键检测阈值滑块默认（bf×1.30、dash 0.40、键距上限） | C（默认值） |

## 汇总

- **A 类（数值/表达照抄，重写候选，估 ~350–450 行）**：
  1. `_ATOM_DRAW_RADII`（90–102）+ 金属缩放逻辑（104–128）
  2. `_IBO_ELEMENT_COLORS_HEX`（169–183）
  3. `_COVALENT_RADII_BOHR`（262–274）
  4. 缩放常量 ATOM_DRAW_SCALE/BOND_DRAW_SCALE/BOND_RADIUS_FACTOR/BOND_THINNING_DEFAULT（315–327）
  5. `IBOVIEW_DEFAULTS`（331–342）
  6. `IBO_DEFAULT_A/O`、`SHININESS_PRESETS`（65–80）
  7. `_GLSL_COMMON` pixel_common.glsl 移植段（472–562）
  8. `_ICOSA_COORDS/_ICOSA_TRIS`（1006–1026）
  9. 相机常量 CAM_DIST/BASE_EXTENT 与投影 near/far（1547–1548、1594–1596、5198–5216）
- **B 类（算法思路复刻、可辩护；若需彻底脱离衍生身份建议连带重写观感相关处）**：depth peeling 循环、GenerateBonds 判定、选中标记、shader 翻译函数、uniforms 上传、相对阈值实现
- **D 类（自研/其他公开来源，无 IboView 问题）**：MolViewer 球体渐变（MolCanvas 自研，含 Houk/gau_default）、vdW 半径（Bondi 1964 公开表）、虚线键、torus、画家回退、分块高分导出、所有 UI 布局、全部分析面板与 VMD 通道

### 法律要点
- A 类中的元素色/半径表本质是科学常数/配色，**单独看版权保护弱**；真正构成"表达"的是 shader 文本 + preset 数值集 + IBOVIEW_DEFAULTS 参数集。
- 只需重写 shader 文本、SHININESS_PRESETS/IBOVIEW_DEFAULTS/相机常量这些"配方"，并**自洽重调观感**，即可大幅降低衍生身份；三张元素/半径表可换用公开 CPK/Bondi/文献数据（MolCanvas 与 GaussView 配色已是另一来源，见 `_SOB_ART_COLORS`、`_GVIEW_COLORS`）。
- vdW 半径表（Bondi 1964）与 `_GVIEW_COLORS`（卢天 gview_color.tcl）**不属于 IboView**，是公开/第三方来源。

---

## 附注：独立子核对修正（更细粒度，与上表主判定对照）

以下为第二遍逐段核对对个别条目的修正/细化，主表未改处即二者一致：

| 位置 | 子核对判定 | 修正说明 |
|---|---|---|
| 262–275 共价半径 | A（数值）| 确认逐字（H 0.7181、K 3.7039…）；Bohr 常量本身 D |
| 277–301 vdW 表 | **D**（主表已 D）| 确认 Bondi 1964 公开数据 |
| 312–327 | **C/B 拆分**（主表记 A 偏严）| ATOM_DRAW_SCALE=0.225、BOND_DRAW_SCALE=0.18 是**项目自定归一化系数**（≈D）；BOND_RADIUS_FACTOR=1.3（317）、BOND_THINNING=0.72（326）是**默认参数照抄（C）**；BOND_MAX_DIST 1.8/1.3 自创上限（D）|
| 329–342 IBOVIEW_DEFAULTS | A（整 dict 1:1）| 若只视为"界面默认值"可辩护 C，但结构+数值整块照抄记 A |
| 1004–1051 | 数据 A / 代码自写 | 1006–1026 表逐字（17 位小数）；1029–1051 make_icosahedron 自写；972–1001 make_sphere 通用二十面体（非 IboView）|
| 1114–1152 键圆柱 | **D**（主表记 B）| docstring 提及 IboView 仅为动机引用；几何代码通用自写。真正的 B 级复刻点在 4008–4010（两段收腰半圆柱拼中点）|
| 1220–1270 style_params | B | 注释转述 IboView 公式，映射自写 + 自有扩展通道 |
| 1537–1623 Camera | B（常量 C）| CAM_DIST=100/BASE_EXTENT=8.0 数值照抄（C）；arcball 自写；ortho 矩阵教科书级（D）|
| 2294–2332 | C/B | 延迟上传/FlipPhase 仅注释类比，实现自写 |
| 2417–2436 | 方法 D/B，**数据源 A** | `SHININESS_PRESETS`（74–81）逐字抄 preset_*.js |
| 2964–3004 导出 | **D**（注释 C）| 仅借"按目标分辨率重渲"思想；分块 FBO 实现自写 |
| 3937–4010 _gen_atoms | B（数据 A）| 原子球/GenerateBonds 公式复刻（B），键灰色 DiffuseColor (0.2,0.2,0.2,1) 数据 A；4046–4066 tight/loose 双阈值+氢规则为项目自创（D）|
| 4262–4312 选中标记 | **A（常数）+B（代码）**（主表同）| 1.8×、0.4/0.6、alpha 0.5 数值照抄（A）；形状切换/呼吸动画自研（D）|
| 5189–5217 投影 | B（near/far 自选 D）| half-height=BASE_EXTENT/zoom 镜像（B）|
| 5426–5510 DP 渲染 | B（贴 A 边缘）| 结构复刻 IboView 双缓冲 ping-pong + FRAG_ORB_DP 骨架（707–729，"mirrors pixel5_orb_dp.glsl"）+ FRAG_COMBINE_DP（933–946，"mirrors pixel5_combine_dp.glsl"）；depth peeling 本身是公开算法（Everitt 2001）；GLSL 文本严格比对可能升 A |
| 5850–5970 滑块 | C | 默认参数+注释；双阈值体系是自创扩展（D）|

**子核对补充的遗漏点（全部并入上述分级）**：文件头 7–11 行自我披露声明；707–729 / 898–946（FRAG_ORB_DP / FRAG_COMBINE_DP 骨架，A/B）；972–1001（make_sphere 通用，D）；1296–1299、1651–1652、1724、2932、3101–3102（概念注释 C）；1769–1779（球棍默认块 _bond_rf_loose=1.3、_dash_weight=0.4，C）；2771–2793（reset_molviewer_style 回填 IBOVIEW_DEFAULTS，C）；3743–3765（render_plane_fill 自研 D）；3769–3778（RenderBacksides 行为对照注释 C）；5339–5361（render_selection_markers pass 自写 B/C）；5514–5516（排序回退 docstring 注释 C）；5588–5591（_set_regs 循环封装 D）。

### 高风险（A 级）最终清单（8 项，重写优先级）
1. `_IBO_ELEMENT_COLORS_HEX`（169–183）→ 源 IvDataOptions.cpp ElementColors[110]
2. `_COVALENT_RADII_BOHR`（262–274）→ 源 CxAtomData.cpp g_CovalentRadii
3. `_ATOM_DRAW_RADII`（90–102）→ 源 IvDataOptions.cpp AtomicRadii
4. `IBO_DEFAULT_A/O`（65–66）+ `SHININESS_PRESETS`（74–80）→ 源 preset_*.js
5. `IBOVIEW_DEFAULTS` 整 dict（331–342）→ 源 prop_FView3d.cpp.inl
6. `_ICOSA_COORDS/_ICOSA_TRIS`（1006–1026）→ 源 IvMesh.cpp
7. `_GLSL_COMMON` 主体（478–562，源 pixel_common.glsl）+ FRAG_ORB_DP / FRAG_COMBINE_DP 骨架（707–729 / 933–946，mirror pixel5_*.glsl）
8. 选中标记三常数 1.8×、0.4/0.6、alpha 0.5（4299–4304）→ 源 IvView3D.cpp

（核对由主核对 + 独立子核对共同完成，双方对 A 类 8 项结论一致；行号以 `ovcanvas/_glwidget.py` 2026 版本为准。）
