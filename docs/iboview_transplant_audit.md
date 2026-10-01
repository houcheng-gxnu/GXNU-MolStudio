# MolStudio GL 渲染内核：IboView 移植部分盘点（行号级）

> 范围：`ovcanvas/_glwidget.py`（渲染内核，约 6290 行；原版快照 `ovcanvas/_glwidget_iboview.py`）
> 目的：合规自查 —— 区分「IboView 逐字移植的表达」（重写候选）与「自研/通用算法/其他来源」。
> 依据：IboView © 2015 Gerald Knizia, GPLv3（**GPLv3-only**，源文件头写 "version 3"，无 "or later"）。

---

## ⚠️ 当前状态（2026-09-03 复核，请以此为准）

**结论：本文件构成 IboView 的衍生作品，项目按 GPLv3 分发即可合规；但"重写"远未完成。**

### 1. 「重写表达层」的实际结果：只完成了 8 项中的 1 项

2026 年的 `2ca52e0`（重写表达层）+ `11800c4`（观感参数调校）两次提交，做的是
**改名 + 注释改写 + 数值微调**，不是重写。实测（对照 IboView RevA 源码）：

| 项目 | plan 编号 | 实际状态 |
|---|---|---|
| 元素颜色表 `_IBO_ELEMENT_COLORS_HEX` | 1.1 | ✅ **已完成** —— 删除，改用 `_CPK_COLORS`（Jmol/CPK 公开配色） |
| 共价半径表 `_COV_RADII_BOHR` | 1.2 | ✅ **已完成（2026-09-03）** —— 改为 Cordero et al. *Dalton Trans.* **2008**, 2832–2838 单键共价半径（Å→Bohr），数据取自仓库内 `etsnocv/config.py` 的课题组 Cordero 副本；前 54 号经 `ELEMENT_SYMBOLS` 顺序交叉校验，103 项无缺失。引用原为 IboView `g_CovalentRadii` 的注释已整段改写 |
| 原子绘制半径表 `_DRAW_RADII` | 1.3 | ✅ **已完成（2026-09-03）** —— 不再逐字抄 IboView `AtomicRadii[104]`；改为由上面的 Cordero 共价半径表 × `COV_TO_DRAW`（按碳标定，整体球大小与改动前一致）。相对碳的半径比例与旧表偏差：C/N/O/P/S/Cl/Br/I 及多数金属 ±5% 内，F −15%、H −33%。**H 已于 2026-09-04 单独 ×`HYDROGEN_DRAW_SCALE`=1.5**（显示系数，绝对值 0.875 ≈ 旧表 0.87），共价半径仍用于成键判定、未改动|
| `IBO_DEFAULT_A/O` + `SHININESS_PRESETS` | 1.4 | ✅ **已完成（2026-09-04）** —— 改名 `_REG_DEFAULT_A/O` 并重标定数值；`SHININESS_PRESETS` 5 档预设（IboView 风格命名）已删除，改为 `gloss` 滑块（`set_gloss` 0..1 连续调节镜面强度），旧预设名经 `_LEGACY_SHININESS_TO_GLOSS` 兼容映射 |
| GLSL `FRAG_COMBINE_DP` | — | ✅ **已解决** —— 自研 WBOIT 路径（McGuire & Bavoil 2013）已等价替代；**depth-peeling 路径已于 2026-09-03 整条删除**，最后一份逐字符相同的着色器（`FRAG_COMBINE_DP`）随之移除 |
| `_GLSL_COMMON` 光照/雾化公式 | — | ✅ **已完成（2026-09-04）**：`ShaderReg0-3`→`u_DiffusePow/Str`+`u_SpecStr/Sharp`、`Fade*`→`u_FogWidth/Bias`、三灯硬编码方向（死代码 `D_L0-2`+`u_UseCustomLights` 分支）已删、`0.12` 截止提取为具名常量、**材质数值自定重标定**（`_REG_DEFAULT_A/O`、`SHININESS_PRESETS`、`FogWidth/Bias`、投影 near/far 系数） |
| `IBOVIEW_DEFAULTS` 参数字典 | — | ✅ **已完成（2026-09-04）**：改名为 `_RENDER_DEFAULTS`，`FadeType` 已删、`FadeWidth/FadeBias`→`FogWidth/FogBias`、死键已删、`FogWidth/Bias` 数值自定 |
| 选中标记 | — | ✅ **已重做**：改为「原子本体染琥珀高亮 + 1.10× 贴合半透明包裹壳」，参数全部自定；二十面体形状与 IboView 三常数（`1.8×`、`0.4:0.6`、`alpha 0.5`）一并移除 |
| 二十面体表 | `_ICOSA_COORDS/_ICOSA_TRIS` | ✅ **已删除**：随二十面体形状一同移除，`make_icosahedron` 已删 |
| 相机常量 | — | ✅ **已改为项目自定**（2026-09-03）：`CAM_DIST=105`、`BASE_EXTENT=7.8`（原 100/8.0）|

整体量化：新旧两版代码骨架（剥离注释/字符串后）相似度 **98.93%**；152 个同名函数相似度
**中位数 100%**，其中 150 个 ≥90%。

### 2. 已纠正的合规事故

`2ca52e0`/`11800c4` 同时删除了文件头的 `Copyright (c) 2015 Gerald Knizia` 声明，并写入两处
**与事实不符**的说明（"着色器/几何/参数均为本项目实现"、"数据来自 Bondi/Cordero 2008"）。

这触犯了 GPLv3 §5(c)（保留版权声明），并依 §8 使授权**自动终止**。2026-09-03 已修复：

- 恢复 `ovcanvas/_glwidget.py` 文件头的 IboView 版权与 GPLv3 声明
- 改正 `_DRAW_RADII`、`_COV_RADII_BOHR`、`FRAG_COMBINE_DP`、`SHININESS_PRESETS` 的来源标注
- 本文件改为如实记录进度

依 GPLv3 §8，停止违规后授权**临时恢复**；停止后 60 天权利人未主张则**永久恢复**。

### 3. 法律定性（供参考，非法律意见）

- **分发修改版本身完全合法**：GPLv3 §5 授予该权利。IboView README 中
  "Do not fork / 请勿分发修改版" 属于 **further restriction**，依 GPLv3 §10 无效，
  且 §7 末段明文允许接收方移除该条款。
- **风险来自未满足 §5 条件**，尤其 §5(c) 保留版权声明。
- ✅ §5(d) 要求 GUI 程序显示 Appropriate Legal Notices —— **已完成**
  （`main_window.py` 中 `AboutDialog` 已含 GPLv3 声明、IboView 版权署名与第三方归属，
  经「关于」按钮 `btn_about` → `_open_about_dialog()` 打开；双语 `_LEGAL_CN`/`_LEGAL_EN`）。
- IboView 为 **GPLv3-only**，故本项目整体**不得**改称 "GPLv3 or later"。

---

## ✅ 已完成并观感验证：WBOIT 透明合成（2026-09-03）

**这是本项目第一个从 IboView 路径中彻底剥离、并经逐场景观感验证的渲染组件。**

> ### ✅ 验证结论（2026-09-03）
> 与 Depth peeling 逐场景对照：**观感几乎一致**。
> 原本由 `FRAG_COMBINE_DP`（与 IboView `pixel5_combine_dp.glsl` **9/12 行逐字符
> 相同**）承担的透明合成，现已可由本项目自研的 WBOIT 路径**等价替代**。
> 至此 A 类清单中的「depth-peeling 合成着色器」一项**实际已解决**。

`ovcanvas/_glwidget.py` 新增了一条**自研**的顺序无关透明路径，与 IboView 无关：

| | Depth peeling（IboView 方案） | **WBOIT（本项目自研）** |
|---|---|---|
| 趟数 | N 趟（层数越多越慢） | **1 趟** |
| 缓冲 | 2 组 color+depth，FBO ping-pong | MRT：累积(RGBA16F) + 显现(R16F) + 深度 |
| 层数上限 | 受 `DepthPeelingLayers` 限制（默认 4） | 无上限 |
| 开销 | 随层数线性增长 | 恒定 |

- **算法来源**：Morgan McGuire, Louis Bavoil, *"Weighted Blended Order-Independent
  Transparency"*, Journal of Computer Graphics Techniques **2**(2):122–141, **2013**。
  公开发表的算法，GLSL 为本项目按论文公式**自行实现**，未参考任何现有实现的源码。
- **新增内容**：`FRAG_ORB_OIT`、`FRAG_COMBINE_OIT` 着色器；`OitTarget` 类（MRT，
  含浮点渲染能力探测与逐级降级）；`render_transparent_oit()`；
  `_render_transparency()` 分派（oit / peel / sorted 三选一，失败自动回退）。
- **能力门槛**：需要 `glBlendFunci`（GL 4.0 或 `GL_ARB_draw_buffers_blend`）与可渲染
  浮点纹理；任一不具备则自动回退到 depth peeling，再不行回退排序混合。
- **UI**：参数面板「透明合成」下拉框切换三种模式；另有「WBOIT 衰减」滑块
  （0–12，默认 4.0）用于微调前/后层权重比。
- **默认**：`oit`（自研路径优先）。

### 踩过的坑：论文公式的隐含前提

初版照搬论文 eq.10 的 `1e8 * pow(1 - z*0.9, 3)`，结果**观感偏暗**。根因是
该系数为**透视投影**标定；本项目是**正交投影**（`CAM_DIST` 固定 105，
near/far = 2.1/210），全场景 `gl_FragCoord.z ≈ 0.495`，`pow(1-0.9z,3) ≈ 0.17`
是个"大"数，乘 1e8 后**所有片元一律顶到 3e3 上限**，深度权重彻底失效，
退化为等权平均（前后比 1:1）。

修正：按包围球直径归一化 z 到 [0,1]（0=最前、1=最后），改用 `exp(-k·t)`
指数衰减。实测前后权重比：

| k | 0（bug 态） | 2 | 3 | **4（默认）** | 6 | 8 |
|---|---|---|---|---|---|---|
| 前:后 | 1:1 | 7.4:1 | 20:1 | **54.6:1** | 403:1 | 2981:1 |

> **教训**：论文公式常带隐含前提。移植算法前必须核对其标定假设是否与自身
> 场景匹配 —— 后续重写光照/雾化表达式时同样要逐常数检查。

### 选中高亮已重做（2026-09-03）

原方案沿用 IboView `IvView3D.cpp`：半径 **1.8–1.9×** 原子绘制半径的**正二十面体**
外壳，颜色 `0.4×原子色 + 0.6×白`、`alpha 0.5`，**原子本体不着色**。两个问题：

1. 多边形壳离原子很远且边角生硬，观感像"外面套了个盒子"而非"这颗原子被选中"；
2. 那几个比例与配色常数是 IboView 的调参结果。

**新方案（本项目自定）**：

| 项 | 取值 | 依据 |
|---|---|---|
| `SEL_TINT_DEFAULT` | 琥珀 `(1.00, 0.72, 0.18)` | 对 CPK/GaussView 常见配色（灰碳、红氧、蓝氮、白氢）区分度最好；不会像纯红与氧混、纯蓝与氮混 |
| `SEL_TINT_MIX` | `0.5` | 原子本体向高亮色混合一半：既一眼可辨，又保留元素身份 |
| `SEL_WRAP_SCALE` | `1.10` | 只比球面大 10%：不会 z-fighting，也不显得是独立物体 |
| `SEL_WRAP_ALPHA` | `0.38` | 半透明，能透出本体颜色 |

实测混合效果（`_mix_toward`，亮度 = 0.2126R+0.7152G+0.0722B）：

| 原子 | 原色 → 混合后 | 亮度变化 |
|---|---|---|
| 碳 灰 | (0.56,0.56,0.56) → (0.78,0.64,0.37) | 0.560 → 0.650 ↑ |
| 氧 红 | (0.90,0.00,0.00) → (0.95,0.36,0.09) | 0.191 → 0.466 ↑ |
| 氮 蓝 | (0.19,0.31,0.97) → (0.59,0.52,0.57) | 0.332 → 0.536 ↑ |
| 氢 白 | (1.00,1.00,1.00) → (1.00,0.86,0.59) | 1.000 → 0.870（转为琥珀，仍清晰可辨）|

伴随清理：`make_icosahedron()` 与 `_ICOSA_COORDS/_ICOSA_TRIS` 已删除
（二十面体形状移除后成为死代码）。顺带说明：该表虽在早期审计中记为
"取自 `IvMesh.cpp`"，但正二十面体是数学对象（顶点由黄金比 φ 唯一确定），
任何人实现都得到同一组数值——所以删除它属于**代码清理**而非合规必需。

新增 API：`set_selection_tint()` / `get_selection_tint()` /
`set_selection_wrap_alpha()`。面板下拉项改为「包裹 / 透明球 / 圆环 / 光晕」，
默认「包裹」。

### 遗留：Depth peeling 路径已删除（2026-09-03）

`render_transparent_depth_peeling()`、`FRAG_ORB_DP` / `FRAG_COMBINE_DP` 以及
depth-peeling 专用的双缓冲 `PeelTarget` 已**整条删除**（WBOIT 合成趟复用了同一
全屏 quad VAO，故该 VAO 保留）。最后一份与 IboView 逐字符相同的着色器
（`FRAG_COMBINE_DP`）随之移除。透明模式现仅 `"oit"` / `"sorted"` 两种，
历史 `"peel"` 模式在分派时落到排序混合（旧样式文件兼容）。

> **2026 更新**：depth peeling 作为**可选项**重新加入，但为**独立实现**——
> 按 Everitt (2001) 白皮书自行编写（`FRAG_PEEL_ORB` / `FRAG_PEEL_COMBINE`
> 着色器、`PeelTargets` FBO 组、`render_transparent_peel()`，层数上限
> `_peel_layers` 默认 4），未参考 IboView 的 `pixel5_orb_dp/combine_dp` 移植
> 文本（git 历史与 `_glwidget_iboview.py` 快照中的旧实现均不参与）。透明模式
> 现为 `"oit"` / `"peel"` / `"sorted"` 三选，运行失败时在 `_render_transparency`
> 内逐级回退（peel ↔ oit 互备，最后落到排序混合）。算法本身为公开方法，
> 与 IboView 无表达层关联。

> 此改动替换了透明合成算法，并清除了使 `_DRAW_RADII` / `_COV_RADII_BOHR`
> 替换得以成立的障碍。仍待重写的是 `_GLSL_COMMON` 光照/雾化公式（清单 #4）。

---

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

## 汇总（2026-09-03 修订：变量名已按现版本更新，并标注完成状态）

> 改名对照：`_ATOM_DRAW_RADII`→`_DRAW_RADII`、`_COVALENT_RADII_BOHR`→`_COV_RADII_BOHR`、
> `_COVALENT_RADII`→`_COV_RADII`、`IBO_DEFAULT_A/O`→`_REG_DEFAULT_A/O`。

- **A 类（数值/表达照抄）—— 重写候选，估 ~350–450 行**：

  | # | 内容 | 现变量名 | 完成状态 |
  |---|---|---|---|
  | 1 | 元素颜色表 | ~~`_IBO_ELEMENT_COLORS_HEX`~~ → `_CPK_COLORS` | ✅ 已替换 |
  | 2 | 共价半径表 | `_COV_RADII_BOHR` | ✅ 已替换为 Cordero 2008（2026-09-03） |
  | 3 | 原子绘制半径表 | `_DRAW_RADII` | ✅ 已由 Cordero 共价半径导出（2026-09-03） |
  | 4 | 缩放/键判定常量 | `BOND_RADIUS_FACTOR` 等 | ✅ 已改项目自定（2026-09-03；原 1.3→1.32 等微调，注释重写） |
  | 5 | 默认参数字典 | 拆散引用（原 `IBOVIEW_DEFAULTS`）→ `_RENDER_DEFAULTS` | ✅ 已改名 + `Fade*`→`Fog*` + 数值自定（2026-09-04） |
  | 6 | shader 寄存器与光泽预设 | `_REG_DEFAULT_A/O`、`SHININESS_PRESETS` | ✅ 已语义化命名 + 数值自定重标定（2026-09-04） |
  | 7 | `pixel_common.glsl` 移植段 | `_GLSL_COMMON` | ✅ **已完成**（命名/结构/雾化参数/材质数值全部自定） |
  | 8 | depth-peeling 合成着色器 | `FRAG_COMBINE_DP` | ✅ 已由自研 WBOIT 替代；**depth-peeling 路径整条删除**（2026-09-03） |
  | 9 | 二十面体顶点/面表 | ~~`_ICOSA_COORDS/_ICOSA_TRIS`~~ | ✅ **已删除**（随二十面体形状移除） |
  | 10 | 相机常量与投影 | `CAM_DIST`/`BASE_EXTENT` | ✅ 已改项目自定（2026-09-03：105 / 7.8） |
  | 11 | 选中标记 | `1.8×`、`0.4:0.6`、`alpha 0.5` | ✅ **已重做**：琥珀高亮 `SEL_TINT_*` + 1.10× 包裹壳，全部自定 |

- **B 类（算法思路复刻、可辩护）**：depth peeling 循环、GenerateBonds 判定、选中标记形状/动画、
  shader 翻译函数、uniforms 上传、相对阈值实现
- **D 类（自研/其他公开来源，无 IboView 问题）**：MolViewer 球体渐变（MolCanvas 自研，含
  Houk/gau_default）、vdW 半径（Bondi 1964 公开表）、元素配色（Jmol/CPK、GaussView、
  MolCanvas）、虚线键、torus、画家回退、分块高分导出、所有 UI 布局、全部分析面板与 VMD 通道

### 法律要点（2026-09-03 修订）

- **合规路径已确定**：本项目按 **GPLv3** 分发即完全合规，无需完成重写。
  「重写」的目的只是**摆脱衍生身份**（从而可以选择其他许可证），不是为了满足 GPLv3。
- **分发修改版是权利，不是违约**：GPLv3 §5 明文授予。IboView README 的
  "Do not fork / 请勿分发修改版" 依 §10 无效，且 §7 末段允许移除该条款。
- **真正的违规点是 §5(c) 保留版权声明** —— 已修复（见文首「当前状态」）。
  §5(d) 的 GUI 法律声明 —— **已完成**：`main_window.py::AboutDialog` 显示 GPLv3 声明、
  IboView 版权署名与第三方归属（「关于」按钮打开，双语）。
- A 类中的半径/配色表本质是科学数据，**单独看版权保护弱**；真正构成"表达"的是
  shader 文本 + preset 数值集 + 默认参数集。若日后要脱离衍生身份，优先重写这三类。
- 已确认**非** IboView 来源：vdW 半径（Bondi 1964）、`_GVIEW_COLORS`（卢天 gview_color.tcl）、
  `_CPK_COLORS`（Jmol/CPK）、MolCanvas 自研配色与渐变。
- 若日后要改称 "GPLv3 or later"，必须先把 IboView 部分彻底重写剥离 —— IboView 是 **GPLv3-only**。

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

### 待重写清单（仅当目标是摆脱 GPLv3 衍生身份时才需要做）

| # | 内容 | IboView 来源 | 替代方案 |
|---|---|---|---|
| 1 | `_COV_RADII_BOHR` | `CxAtomData.cpp::g_CovalentRadii` | Cordero et al., *Dalton Trans.* **2008**, 2832–2838（Å），自行换算 Bohr |
| 2 | `_DRAW_RADII` | `IvDataOptions.cpp::AtomicRadii[104]` | 基于 Bondi vdW 表 × 项目自定系数，或自拟合绘制半径表 |
| 3 | ~~`FRAG_COMBINE_DP`~~ | ~~`shader/pixel5_combine_dp.glsl`~~ | ✅ **已完成**：改用 McGuire & Bavoil 2013 的 WBOIT，单趟实现，观感验证一致；**depth-peeling 路径已于 2026-09-03 整条删除** |
| 4 | `_GLSL_COMMON` 光照/雾化公式 | `shader/pixel_common.glsl` | ✅ **已完成**：语义化命名 + 材质数值自定重标定 |
| 5 | `_REG_DEFAULT_A/O`、`SHININESS_PRESETS` | `preset_*.js`、`prop_FView3d.cpp.inl` | ✅ **已完成**：数值自定重标定 |
| 6 | 默认参数字典 | `prop_FView3d.cpp.inl` | ✅ **已完成**：项目自有默认值（`FogWidth/Bias` 等） |
| 7 | 相机常量 `CAM_DIST`/`BASE_EXTENT` | `FView3d::ResetProjectionAndZoom` | 自定义 |
| 8 | 选中标记三常数 | `IvView3D.cpp` | 自定义 |

> 说明：原清单第 1 项（元素颜色表）已完成，不在上表。
> 第 6 项 `_ICOSA_COORDS/_ICOSA_TRIS` 虽取自 `IvMesh.cpp`，但二十面体是通用几何、
> 表达空间极小，风险可忽略，优先级最低。

**重要**：重写必须由**未接触过 IboView 源码的人**完成才构成 clean room。
本项目 git 历史已记录了 access（`2ca52e0`、`11800c4` 等提交信息），
由同一批人"重写"在法律上不构成独立创作。

（核对由主核对 + 独立子核对共同完成；2026-09-03 由第三次复核补充完成状态与法律定性。
行号以旧版快照 `ovcanvas/_glwidget_iboview.py` 为准，现版本 `ovcanvas/_glwidget.py`
已改名，内容对照见文首「当前状态」表。）
