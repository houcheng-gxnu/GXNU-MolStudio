# GL 渲染内核重写方案（A 级替换任务清单）

> 目标：把 `ovcanvas/_glwidget.py` 中 **A 类（逐字照抄 IboView）** 的内容替换为独立实现，
> 使渲染内核不再构成 IboView 的衍生作品（脱离 README "请勿分发修改版" 的争议）。
> **原则：原 IboView 移植方案整体保留**（git 分支 + 运行时开关），见 §0。
> 范围：A 类 8 项 + 必要的 B 类联动项；D 类（MolCanvas/HoukMol/Chem311/GaussView/Bondi）不动。

---

## §0. 原方案保留策略（先做，零风险）

1. **Git 打分支**：`git checkout -b feature/render-rewrite`，当前 `_glwidget.py` 的 IboView 移植版完整留在 `main`（以及新分支的初始 commit 里可随时回退）。
2. **运行时开关（推荐做）**：新增环境变量/设置项 `MOLSTUDIO_RENDERER = iboview|native`（默认 `native`）：
   - `native`：走重写后的独立渲染路径（新文件 `ovcanvas/_native_render.py`，见 §1）
   - `iboview`：保留现有移植实现（不删除任何代码），供对照观感 / 回归测试 / 出问题回退
   - 实现方式：`_glwidget.py` 顶部按开关选择 import；或把新渲染器做成 `_glwidget.py` 内的一套独立函数/类，旧代码仅保留在 `iboview` 分支文件 `ovcanvas/_glwidget_iboview.py`（原文件改名保留）。
3. **回归对照**：同一 cube + 同视角，新旧两版各出一张 PNG（用现有 `export_image`/`screenshot`），肉眼与直方图对照，观感接近即可（不追求逐像素一致，见 §3）。

> 推荐文件结构（最小侵入）：
> ```
> ovcanvas/
> ├── _glwidget.py            # 薄分发层：读开关 → 实例化 native 或 iboview 渲染器
> ├── _glwidget_iboview.py    # 原 IboView 移植实现（现状原样迁入，git 历史保留）
> └── _native_render.py       # 新：独立渲染内核（本清单要写的东西）
> ```
> 面板层 `_panel.py`、分析面板、VMD 通道全部零改动（它们只依赖 `glw` 公开接口）。

---

## §1. A 级 8 项替换方案

### 1.1 元素颜色表 `_IBO_ELEMENT_COLORS_HEX`（169–183）

- **问题**：110 项逐字抄自 `IvDataOptions.cpp ElementColors[110]`（Rasmol CPK-new，碳改灰）。
- **替代来源（项目内已有，零新依赖）**：
  - **默认改用 MolCanvas 的 `SOB_ART_CPK`**（`molcanvas.py` 295–299，你们 Chem311 自研配色，D 类）——H/C/N/O/S/P/F/Cl/Br/I 十元素，化学常规分子足够；
  - 或补全用 **`_GVIEW_COLORS`**（`_glwidget.py` 366–404，卢天 `gview_color.tcl` 转写，覆盖 1–111 全元素，已在本文件、D 类）——这是目前 `_atom_color()` 的 GaussView/HoukMol 分支数据源，直接复用即可；
  - 其余可选：MolCanvas `APPLE_CPK`/`PAPER_CPK`/`CLAY_CPK`（301–316）、`_JMOL_COLORS`（407–413）。
- **做法**：`_atom_color()` 的 CPK 分支改查 `_GVIEW_COLORS`（或 `SOB_ART_CPK` + 回退 `_GVIEW_COLORS`）；删除 `_IBO_ELEMENT_COLORS_HEX` 或仅留作 iboview 模式数据。**注**：Rasmol CPK-new 与 GaussView 配色视觉接近，观感几乎无感变化。

### 1.2 共价半径表 `_COVALENT_RADII_BOHR`（262–274）

- **问题**：110 项 Bohr 值抄自 `CxAtomData.cpp g_CovalentRadii`，用于 `GenerateBonds` 键判定。
- **替代来源**：
  - **文献公开数据**：Cordero et al., *Covalent radii revisited*, *Dalton Trans.* **2008**, 2832–2838（高精度、最常引用，覆盖 1–96 元素）；
  - 或 Pyykkö & Atsumi 系列（*Chem. Eur. J.* 2009）；
  - 或简单方案：**复用 `molcanvas.ATOM_RADII`**（`molcanvas.py` 24–47，你们已有的 Å 单位半径表，D 类）——但该表只覆盖常见元素（含 H…I 及部分金属），对过渡金属需补。
- **做法**：新建 `_COVALENT_RADII_A`（Å，标注来源 "Cordero 2008 / Pyykkö 2009"），换算逻辑照旧（Å→Bohr 或直接改在 Å 帧比键距）。Bohr 帧下的键判定公式 `r ≤ 0.5(bf_i+bf_j)(cov_i+cov_j)` 是通用化学几何启发式（B 类，可保留），只换数据表。
- **保留**：`BOHR_TO_ANGSTROM = 0.529177` 是通用物理常数（D），不动。

### 1.3 原子绘制半径表 `_ATOM_DRAW_RADII`（90–102）+ 金属缩放（104–128）

- **问题**：104 项 vdW 类半径抄自 `AtomicRadii`；但项目已在 104–128 加了**自研金属缩放**（缩小 1/3、下限 2.15）。
- **替代来源**：
  - **vdW 半径已有公开表 `_VDW_RADII_A`（Bondi 1964，281–293，D 类）**——但 Bondi 是 vdW 半径（偏大），IboView 表是"绘制用经验半径"（更小）。若直接换 Bondi，球会明显偏大，需重新定 `ATOM_DRAW_SCALE`。
  - 更贴观感的方案：**用 `_VDW_RADII` 乘一个项目自定系数**（如 0.55–0.65，滚动条调），或给常见元素手工拟合一版"绘制半径"并标注为 MolStudio 自有数据。
- **做法**：`_atom_base_radius()` 改为查 MolStudio 自有绘制半径表（来源标注 Bondi 派生 + 课题组自定系数），删除对 IboView 表的引用。球比例观感靠 §3 的 `ATOM_DRAW_SCALE` 重调收敛。

### 1.4 `IBO_DEFAULT_A/O`（65–66）+ `SHININESS_PRESETS`（74–80）

- **问题**：5 组 ShaderReg 四元数组逐字抄自 `preset_*.js`。
- **替代**：定义 MolStudio 自有高光档位（命名改 `GLOSS_*`），数值**从观感反推自定**：
  - 档位结构保留（diffuse 指数/强度、specular 强度、平衡 4 个寄存器），但每档数值手工微调至观感满意（参照 §3 对照流程）；
  - 例：`GLOSS_MATTE=[0.7,0.7,0.25,-0.5]`、`GLOSS_STANDARD=[0.8,0.7,0.45,-0.5]`、`GLOSS_SHINY=[1.0,0.7,1.6,-0.5]`（初始猜测，须按实际渲染微调；同观感目标下数值落在相近区间是正常收敛，不是"抄"）。
- **注**：`u_Ambient/u_Fx/自定义光源` 等扩展通道（D 类自研）保留不动。

### 1.5 `IBOVIEW_DEFAULTS` 整 dict（331–342）

- **问题**：整 dict 1:1 抄自 `prop_FView3d.cpp.inl`。
- **替代**：改名 `_RENDER_DEFAULTS`，只保留**真正使用的键**（实测哪些被读：`FadeWidth/FadeBias/DepthPeelingLayers/OrbitalOpacity/IsoThreshold` 等），**删掉未用的**（SuperSample/FakeAntiAliasing 等是 UI 文案引用）；数值按项目需要自定（如 DP 层数 4 是合理默认、FadeWidth 可改 8.0 等），并加注释"MolStudio 渲染默认参数"。
- 涉及引用处（`_glwidget.py` 多处 `IBOVIEW_DEFAULTS[...]`、UI 文案 5861/5893/5904、`reset_molviewer_style` 2771–2793）统一改查新 dict 名；UI 上"相对阈值模式"复选框文案去掉 "IboView" 前缀（如改"相对阈值 (默认 80%)"）。

### 1.6 二十面体 `_ICOSA_COORDS/_ICOSA_TRIS`（1006–1026）

- **问题**：12 顶点 + 20 三角逐字抄自 `IvMesh.cpp`。
- **替代**：**数学生成**——正二十面体顶点由黄金比 φ=(1+√5)/2 解析给出：
  `(±1, ±1/φ, 0)`、`(±1/φ, 0, ±1)`、`(0, ±1, ±1/φ)` 归一化即得 12 顶点；三角面索引可用标准构造（或保留 20 面拓扑由顶点凸包计算）。这是**纯几何常识公式**，不构成 IboView 表达。
- 已有 `make_sphere`（972–1001）也是通用构造（D），可参照其写法；`make_icosahedron`（1029–1051）函数体本身自写，只换数据来源。

### 1.7 `_GLSL_COMMON`（478–562）+ FRAG_ORB_DP（707–729）/ FRAG_COMBINE_DP（933–946）

- **问题**：pixel_common.glsl 1:1 移植（三灯方向、light_term 公式、calc_base_color、alpha/=clamp(|N.z|) 边缘增强、FadeType=1 雾化）；DP 两个 shader 骨架 mirror pixel5_*.glsl。
- **替代（重写 shader，保持观感目标）**：
  - **三灯 Phong 是通用模型**：按标准 Blinn-Phong 重写 `light_term`（用 `n·h` 半程向量或保留 `n·l` 幂次，变量名/结构自拟）；漫反射/镜面分离是教科书写法；
  - **边缘 alpha 增强** `color[3] /= clamp(|N.z|,0.1,1)`：这是"掠射角提升不透明度"的通用技巧，换等价实现（如 `alpha *= 1 + (1-|N.z|)*k`）并用自己变量；
  - **Fade 景深雾化**：`mix(rgb, white, clamp(FadeWidth*(z-0.5)+FadeBias))` 是通用线性雾化，自写等价式；
  - **DP shader**：`texelFetch(Depth1)+gl_FragCoord.z 比较` 是 depth peeling 的标准写法（Everitt 2001 公开配方），重写变量名与结构、注释标注 "OIT: front-to-back depth peeling (Everitt 2001)" 而非 pixel5_*.glsl；
  - **灯方向常量**（D_L0..2，497–499）：默认三灯方向是常见对称取光（0.5,0.5,0.707 / ±0.433…），可按自定角度重算或保留（对称光照方向属通用配置）。
- **保留**：`u_MvGrad` MolViewer 渐变通道（690 起、D 类，含 Houk 渐变）与 FRAG shader 里 `mv_orb_color` 分支、orb_outline（自研描边）。

### 1.8 选中标记常数（4299–4304）

- **问题**：`1.8×原子半径`、颜色 `0.4×原子色+0.6×白`、`alpha=0.5` 照抄 IvView3D.cpp。
- **替代**：改自研参数（如 `2.0×`、`0.5×原子色+0.5×白`、alpha 0.45）并注释"MolStudio 选中标记默认"；形状切换（sphere/torus/glow）与呼吸动画本就是自研扩展（D），保留。
- **观感影响**：仅选中态外观微变，分子本体不受影响。

---

## §2. B 类联动项（不重写也可辩护，但建议顺手清理）

| 位置 | 现状 | 建议 |
|---|---|---|
| 行 1220–1270 `style_params` | 注释转述 IboView 公式，映射自写 | 删除注释里 IboView 公式原文，改写为"MolStudio 材质寄存器语义"；映射逻辑不变 |
| 行 1537–1623 `Camera` | CAM_DIST=100/BASE_EXTENT=8.0 照抄（常量 C） | 改自定常量（如 CAM_DIST=50、BASE_EXTENT=10）并注释为 MolStudio 正交投影参数；arcball 自写不动 |
| 行 5189–5217 `_projection` | half-height=BASE_EXTENT/zoom 镜像 | 随 §2 相机常量联动 |
| 行 3937–4010 `_gen_atoms` 键判定 | GenerateBonds 公式 `r≤0.5(bf_i+bf_j)(cov_i+cov_j)` + 灰色键 DiffuseColor(0.2,0.2,0.2,1) | 公式是通用几何启发式（可留，注释改写"共价半径和判键"）；灰色键色改项目默认并注释；数据表换 §1.2/1.3 |
| 行 5426–5510 DP 渲染 | docstring "following FView3d::RenderScene" | 改注释为 "front-to-back OIT (Everitt 2001)"；代码结构自写不动 |
| 行 5860–5865 等 UI | "IboView 相对阈值" 文案 | 去掉 IboView 前缀（功能保留） |

---

## §3. 观感收敛流程（重写后必须做的调校）

目标：重写版与旧版"放一起看不出是两套引擎"，不追求逐像素 diff=0。

1. 固定测试集：2–3 个代表性体系（如 CO 轨道、苯 HOMO、一个含金属的 LUMO），同 isovalue/视角。
2. 对照渲染：`native` vs `iboview` 各出一张 PNG，并排看。
3. 调校旋钮（都在新参数集里）：
   - 球比例 → `ATOM_DRAW_SCALE`（现 0.225，来源替换后按实际微调 0.20–0.25）
   - 高光强度 → `GLOSS_*` 档位 specular 项
   - 边缘不透明度 → alpha 增强系数
   - 雾化 → `FadeWidth`（8–10 区间）
   - 键粗细 → `BOND_DRAW_SCALE`
4. 验收：正负叶实色、白高光边缘、透明白边、景深淡出四要素齐备即可；**数值落在相近区间属正常收敛**（同观感目标），与"照抄数值"有本质区别——前者有自研调校记录，后者是 1:1 复制。

---

## §4. 工作量与顺序

| 步骤 | 内容 | 估时 |
|---|---|---|
| 0 | git 分支 + `_glwidget_iboview.py` 迁移 + 开关 | 0.5–1 天 |
| 1 | §1.1–1.6 数据/常量替换（表 + 默认 dict + 二十面体） | 0.5–1 天 |
| 2 | §1.7 shader 重写（GLSL_COMMON + DP 两个） | 1–2 天 |
| 3 | §1.8 + §2 联动清理（选中标记、注释、相机常量） | 0.5 天 |
| 4 | §3 观感收敛（对照渲染 + 调参） | 1–2 天 |
| 5 | 全功能回归（13 面板 + VMD 通道 + 导出） | 1 天 |
| 合计 | | **约 5–7 天**（一人） |

**完成判据**：`native` 模式下全项目无 `_IBO_ELEMENT_COLORS`/`IBOVIEW_DEFAULTS`/`SHININESS_PRESETS`/`_GLSL_COMMON`(IboView 来源) 等符号引用；`_glwidget.py` 头注释改为"独立渲染内核"；论文 §7 衍生声明改写为"渲染引擎独立实现"（VMD 通道与 MolCanvas 渐变不受影响）。

---

## §5. 交付物清单

- [ ] git 分支 + 开关（`MOLSTUDIO_RENDERER` 或设置项）
- [ ] `_glwidget_iboview.py`（原版保留，含原版权声明）
- [ ] `_native_render.py` 或 `_glwidget.py` 内重写（含新数据来源注释）
- [ ] 观感对照 PNG 组（native vs iboview）
- [ ] 更新 `ovcanvas/README.md` 许可证段、根 `LICENSE`/THIRD-PARTY-NOTICES、论文 §7
- [ ] 回归测试通过（13 面板 + VMD + 导出 + 命令行）

> 备注：若最终选择不重写（保留 GPLv3 衍生发布），则本清单仅作备用；原版声明与 §7 论文措辞继续有效。
