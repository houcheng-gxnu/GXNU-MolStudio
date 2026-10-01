# GXNU MolStudio：分子可视化与量子化学分析一体化开源平台

<!-- ══════════════════════════════════════════════════════════════════
     ChemRxiv 预印本中文稿 — GXNU MolStudio v1.0 (2026)
     本稿为英文投稿稿（docs/chemrxiv_draft.md）的中文对照版，
     供课题组内部审阅与中文传播使用。参考文献保留原文，引用编号与英文稿一致。
     ── 提交前必填（作者提供）─────────────────────────────────────
     [x] 作者姓名 / 单位 / ORCID / 通讯邮箱（侯成，单一作者）
     [x] 基金资助信息（国家自然科学基金 22463001）
     [ ] 图 2–6 截图替换占位
     [x] 参考文献已按作者 2026-09-18 审计逐条修订（详见文末清单）
     ══════════════════════════════════════════════════════════════════ -->

**作者：**侯成<sup>1,\*</sup>

<sup>1</sup> 广西师范大学化学与药学学院，桂林 541004，中国

<sup>\*</sup> 通讯作者，邮箱：houcheng@gxnu.edu.cn；ORCID：0000-0003-2967-0326

**关键词：**分子可视化；波函数分析；图形界面软件；量子化学；Multiwfn

## 摘要

我们报道 **GXNU MolStudio** —— 一款开源、中英双语的桌面应用软件，它在单一交互环境中把实时分子可视化与一套覆盖面很广的量子化学分析整合在一起。MolStudio 内嵌自研的 OpenGL 3.3 渲染器，以面向出版的风格呈现分子、轨道与按性质着色的等值面，并与外部波函数分析程序 Multiwfn 的脚本化调用相耦合。当前版本提供 **14 个面板**（11 个分析面板 + 3 个流程面板），涵盖：轨道浏览与等值面生成（含开壳层体系的自旋密度可视化）、6 种原子电荷方案（ADCH、Hirshfeld、Mulliken、CM5、SCPA、VDD）、Mayer 键级、NBO 给体–受体（E(2)）分析、带极值点与表面积分布的静电势（ESP）表面、IGMH/IRI 弱相互作用分析、QTAIM 拓扑、ETS-NOCV 能量分解、分子平面性参数（MPP）、IRC 能量/键级剖面、扭曲–相互作用（DI）分解、能量跨度模型（ESM），以及沿 IRC 的活化张力扫描（ASM）、多 CUB 叠加与 IRC 拆分。所有面板共享同一张画布与同一套原子拾取协议，因此不同分析的结果可以在同一结构上即时对照。一条保留的 VMD/Tachyon 通道提供 30 余种精选风格的光线追踪级期刊插图。MolStudio 以 Python 源码（PyQt5，Python ≥ 3.8）以及 Windows 独立可执行程序两种形式，依 **GNU 通用公共许可证第 3 版（GPLv3-only）** 发布。其渲染管线是 GPLv3 授权的 IboView 引擎的 Python 移植 —— 这一衍生关系在第 7 节中明确声明，并在代码仓库中逐项备案 —— 所有第三方组件均已署名。软件免费获取：https://cnb.cool/chem311/GXNU-MolStudio

## 1. 引言

量子化学计算在今天的化学研究中已属常规，然而把原始输出 —— 格式化检查点（`.fchk`）文件、Gaussian cube 网格、日志文件 —— 转化为有化学意义的认识，仍然需要拼凑一整套工具。VMD、[1] Avogadro、[2] IboView[3,4] 与 GaussView 一类程序负责显示结构与等值面；而定量分析（原子电荷、键级、NBO 相互作用、ESP 表面、弱相互作用、QTAIM 拓扑、能量分解）则由专门程序完成，其中最具代表性的是 Multiwfn。[5,6] 要复现一张文献风格的插图，或回答一个机理问题，研究者通常不得不在多个界面之间搬运数据、手工对齐几何结构与轨道序号，并反复为同一场景重新配色。

针对单项分析，目前已经存在若干成熟工具 —— 例如 IGMH/IRI 方法及其配套工具箱、[7,8] 各类 ETS-NOCV 查看器、[9] 以及 ESP 表面查看器。但对许多研究组和教学实验室而言，仍然缺少这样一种低摩擦的环境：**分子只需载入一次**，即可用上述任意方法加以考察而无需重新导入几何；并且每一个数值结果都有与之对应的、可直接导出用于稿件的图形呈现。

GXNU MolStudio 由广西师范大学侯成课题组开发，正是为填补这一空缺而设计。其指导原则有三：

1. **一张画布，多种分析。** 所有结构、轨道、等值面与按性质着色的场都绘制在同一个嵌入式 OpenGL 视口中。每个分析面板都作用于同一张画布，因此用户例如可以叠加 ESP 表面、定位其极值点，随即查询对应的 NBO 相互作用或 QTAIM 临界点，全程无需重新载入任何东西。
2. **以 Multiwfn 为计算引擎。** 凡是需要波函数派生量的场合，MolStudio 都通过脚本化命令序列驱动 Multiwfn，自动完成 cube 生成与性质计算，同时保留用户对网格质量与文件管理的控制。用户面对的是化学问题，而不是控制台提示符。
3. **面向出版的输出。** 每个模块都能导出插图（PNG/SVG/PDF）、数据（CSV）或格式化报告（HTML）。一条通往 VMD/Tachyon 的兼容通道提供高分辨率光线追踪图像，并配有精选的配色与光照预设，可满足期刊封面与插图需求。

MolStudio 支持中英双语（可即时切换）、接受拖拽输入、提供命令行批处理模式，并打包为 Windows 独立可执行程序，供没有 Python 环境的用户使用。软件依 GNU 通用公共许可证第 3 版（GPLv3-only，见第 7 节）发布。

## 2. 软件架构

### 2.1 技术栈

MolStudio 使用 Python 3.8+ 编写，图形界面基于 Qt5 的 PyQt5 绑定，内嵌图表用 matplotlib。实时视口是一个 OpenGL 3.3 Core 渲染器（PyOpenGL），绘制球棍模型与等值面，具备 Phong 风格光照、按元素配色表、用于半透明表面顺序无关透明的**深度剥离**（depth peeling，不可用时自动回退到深度排序混合），以及画布内可拖拽的色标条。渲染引擎是 **IboView[3,4] 管线的 Python 移植**（深度剥离透明、三光源 Phong 着色、球棍模型几何，以及 IboView 的原子半径表与共价半径表）。元素配色表在最初的移植中同样取自 IboView，但作为一项持续的**去衍生化**工作，现已替换为公开的 Jmol/CPK 配色（第 7 节）。IboView 由 Gerald Knizia 享有著作权并以 GPLv3 发布；因此 MolStudio 构成 IboView 的衍生作品，并以同一许可证发布（见第 7 节及仓库中的第三方声明）。

网格数据由原生的 Gaussian-cube 读取器解析，等值面网格通过一层轻量封装（`marching_cubes.py`）调用 PyMCubes 提取，该封装同时计算顶点法向。所有耗时的数值任务都在工作线程（`QThread`）中运行并上报进度，外部进程可被干净地中断。

分析后端是外部程序 **Multiwfn**（3.8 版，2026 年 1 月 7 日发布，以及此后按日期命名的版本；本开发周期针对 2026.4.10 二进制做过测试）[5,6]，其路径在设置对话框中配置一次后存入 `fchk_orbital.ini`。旧的出版通道可选地使用 VMD[1] 与 Tachyon 光线追踪器[10]；它们仅对该通道需要，内置画布从不依赖。

**为何选择调用 Multiwfn 而非自行实现。** MolStudio 中每一个波函数派生量，都是通过把 Multiwfn 作为外部进程驱动而获得的，而不是在 MolStudio 内部重新实现底层算法。这一选择出于三点考虑。第一，它保证界面上显示的任何一个数字，都与社区已在验证、已在引用的参考实现所产生的值完全一致，因此通过图形界面得到的结果可以直接与文献比对，无需另作验证。第二，分析后端由此得以跟随 Multiwfn 的更新 —— 新的电荷定义、新的实空间函数、修订后的默认值 —— 而 MolStudio 自身无需改动。第三，它避免在边界情形（开壳层处理、有效核势、积分网格选择）上与参考实现发生不易察觉的分叉 —— 这类实现差异极易引入，却极难发现。这一设计的代价是 Multiwfn 必须单独安装：它以独立进程方式调用，不随 MolStudio 分发，其使用受自身条款约束（第 7 节）。

### 2.2 程序布局

主窗口由三个区域构成（图 1）：左侧列出各面板的导航栏、中间的画布列，以及右侧承载当前分析面板的堆叠区。画布与面板堆叠区之间由可拖拽的分隔条分开，导航列表与堆叠区保持联动。所有面板都拿到同一个 `glw` 句柄并注册原子拾取回调，由此在整个软件中形成一致的行为，例如"点击一个原子即可查询其电荷、将其选入键级计算，或把它加入 IGMH 片段"。

```
┌──────────┬──────────────────────────┬───────────────────────────────┐
│  导航    │                          │   可视化（轨道表、等值面设置）│
│  栏      │      OpenGL 画布         │   电荷与键级                  │
│ （标签） │      （共享 glw）        │   NBO / ESP / IGMH / AIM      │
│          │                          │   ETS-NOCV / MPP / IRC        │
│          │                          │   DI / 能量跨度 / 自旋密度    │
│          │                          │   运行日志                    │
└──────────┴──────────────────────────┴───────────────────────────────┘
```

![图 1](paper_figures/fig1_main_window.png){ width=6.5in }

**图 1.** GXNU MolStudio 的工作区：左侧导航栏、中间共享 OpenGL 画布、右侧当前分析面板。面板组织方式见上方示意图。

代码库刻意保持模块化：`main.py`（入口、启动画面、命令行批处理）、`main_window.py`（应用外壳与面板编排）、`fchk_orbital.py`（cube 生成、风格预设、VMD/Tachyon 控制）、`ovcanvas/` 包（OpenGL 渲染器与画布面板）、`marching_cubes.py`（cube 解析与等值面提取），再加上每个分析面板各一个模块（`charge_bond_panel.py`、`nbo_viewer.py`、`esp_panel.py`、`igmh_panel.py`、`aim_panel.py`、`etsnocv_panel.py`、`mpp_panel.py`、`irc_panel.py`、`di_analysis_panel.py`、`energy_span_panel.py`）。共享的解析器把 `.fchk`、`.log/.out`、`.cub/.cube`、`.xyz` 以及 Molden 输入统一转换为画布与所有面板共用的原子/键表示。自旋密度可视化位于轨道面板内，由专门的工作线程驱动。

### 2.3 响应性与启动

耗时的 Multiwfn 任务在工作线程中运行，进度同时输出到共享运行日志与进度条；所有外部进程都可中断。为消除着色器即时编译所导致的、众所周知的首次交互延迟，MolStudio 在启动画面期间即完成全部 GLSL 着色器的编译，之后主窗口才进入可交互状态。

## 3. 可视化能力

### 3.1 交互式 OpenGL 画布

内嵌画布提供：

- **精选视图风格。** 一键预设复现 sob-art、IBOview、HoukMol 与 IQmol 的视觉惯例；按原子的配色方案（CPK、SobArt、HoukMol、Vcube、自定义）与正交的光照设置（1 至 4 盏灯，每盏灯的光晕可调）自由组合。
- **正确的透明。** 深度剥离渲染相互重叠的半透明等值面，不会出现朴素 alpha 混合的伪影；当深度剥离不可用时，MolStudio 回退到深度排序混合。
- **分子显示辅助。** 隐藏氢原子（支持"保留指定 H"）、按原子的序号或元素符号标签、分子平面上的 Houk 风格十字准环，以及完整的旋转/平移/缩放交互。
- **按性质着色。** 原子电荷映射到发散色标；按原子的带符号偏差（如 MPP 平面性）；ESP 与 IGMH 场的逐顶点着色等值面；画布内可移动、可定制的色标条。
- **原子拾取。** 点击原子会高亮它，并在当前面板中触发相应分析（电荷查询、成键选择、片段定义）；Shift+左键拖拽提供框选，用于 IGMH 类分析的片段定义。

### 3.2 保留的 VMD/Tachyon 通道

为获得光线追踪级的出版用图，MolStudio 保留了一条兼容通道：以脚本方式驱动 VMD，[1] 提供 30 余套精选的配色/材质/光照预设（改编自 vcube 2.0 风格集[11] 与 IboView 风格配置[3]），并用 Tachyon 光线追踪器[10] 以任意高分辨率输出最终图像（已测试至 3000 px 以上），背景可选透明。所有 VMD 交互 —— 分子载入、样式设置、相机控制、渲染 —— 都由 MolStudio 以脚本编排；可选的"同步到 VMD"按钮把画布内视角镜像过去，使用户可以先在 OpenGL 场景中调整，再产出等价的 VMD 插图，而无需重做设置。

## 4. 分析模块

MolStudio 提供 14 个面板（11 个分析面板 + 3 个流程面板）。每个面板要么读取当前已载入的分子，要么读取自己的输入文件，执行分析（通常通过脚本驱动 Multiwfn），并同时给出数值结果与画布或内嵌图表的即时更新。本节逐一简述各模块；方法层面的文献统一列于参考文献。

### 4.1 轨道浏览与等值面生成

格式化检查点文件被解析为带占据数与 HOMO/LUMO 标记的轨道能量表。双击任一轨道即通过 Multiwfn 生成其 cube 网格，并在画布中以常规的正/负相位配色渲染等值面；多个轨道（如 HOMO 与 LUMO）可同时显示并各自独立配色。命令行批处理模式（`python main.py folder/ --mo h,l --iso 0.05 --style sob-art`）可对整个目录自动完成 cube 生成与渲染，最终插图可由内嵌渲染器或 VMD/Tachyon 通道产出。

### 4.2 原子电荷与键级

电荷面板通过脚本驱动 Multiwfn，计算 6 种广泛使用的原子电荷方案 —— **ADCH**、[14] Hirshfeld、Mulliken、CM5、SCPA 与 VDD[5,6] —— 显示在可排序表格中并可导出 CSV。电荷可映射到画布中的原子上，使用方向可调的蓝–白–红发散色标。配套的键级面板计算用户选定原子对的 **Mayer 键级**[19]（通过拾取原子或输入序号）。两个面板都在共享画布上注册了原子拾取行为。

### 4.3 NBO 分析

读取 Gaussian `pop=nbo` 的日志输出，并遵循自然键轨道（NBO）的给体–受体图像，[20] NBO 面板列出各自然轨道及其占据数，以及 E(2) 二阶微扰给体–受体相互作用（给体/受体对及能量，单位 kcal mol⁻¹）。NBO 能级与配套 `.fchk` 中的分子轨道序号相匹配，因此任意 NBO 轨道都可按需生成，并作为等值面显示在共享画布上。

### 4.4 ESP 表面与极值点

从 `.fchk` 出发，并遵循分子静电势的标准诠释，[21] MolStudio 用 Multiwfn 生成电子密度与 ESP 的 cube 网格，从密度场中提取范德华等值面（默认 ρ = 0.001 a.u.），并按每个顶点处的 ESP 取值连续着色。提供四种显示模式：**ISO**（等值面网格）、**PT**（逐顶点着色的点云）、**EXT**（极值点标记；金色球为局部极大，浅蓝为局部极小）与 **ALL**（表面 + 极值点）。默认发散色标为 RWB（红 = 负 ESP，即富电子区；蓝 = 正 ESP，即缺电子区），遵循教科书与化学文献中的通行约定；**反色**开关可反转任一所选色标的方向，并提供一整套发散与顺序色标（BWR、Coolwarm、Seismic、RdBu、Turbo 及其他彩虹变体、Viridis、Plasma、Cividis、IceFire）。画布内色标条、ESP 极值范围自动探测、ESP 表面积分布直方图，以及多分子叠加图表共同构成该模块。预先算好的 cube 文件对（`density*.cub` / `ESP*.cub`）可直接载入渲染，无需重跑 Multiwfn。

### 4.5 IGMH / IRI 弱相互作用分析

片段通过在画布上点击原子（Shift+左键框选）或输入原子范围（如 "1–12,15"）来定义。脚本化的 Multiwfn 运行产出 IGMH 或 IRI 指示量所需的 `dg_inter`、`dg_intra`、`dg` 与 `sl2r` cube 网格。片段间的 `dg_inter` 场决定弱相互作用等值面的几何，该等值面按 sign(λ₂)ρ 场以 BGR 色标着色（蓝 = 吸引、绿 = 弱、红 = 排斥），复现标准的 IGMH 可视化。与之配套的是可交互的 IGM Map 散点图（sign(λ₂)ρ 对 δg），支持 PNG 导出。IGMH 与 IRI 指示量遵循卢天与陈沁雪的工作。[7,16]

### 4.6 QTAIM 拓扑（AIM）

在分子中原子的量子理论（QTAIM）[22] 框架下，MolStudio 驱动 Multiwfn 完成完整的拓扑分析（临界点搜索与键径追踪），按类型为临界点着色，并把键径以点云形式绘入画布。点击临界点可查询其性质（ρ、∇²ρ、动能/能量密度、椭率等）。VMD/Tachyon 的"期刊预览"模式可为最终插图渲染拓扑。

### 4.7 ETS-NOCV 能量分解

给定复合物及其两个片段（3 个 `.fchk` 文件），ETS-NOCV 面板启动一个持久的 Multiwfn 会话执行 ETS-NOCV 能量分解，并列出 NOCV 对表格（ΔE_pair、轨道标签、本征值、能量）。选中某一对即按需生成相应的形变密度 cube，并以用户可选的蓝–红相位约定在画布上显示正/负瓣。另提供 Gaussian `.gjf` 输入生成器，辅助准备片段与复合物的计算。

### 4.8 分子平面性参数（MPP）

MPP 面板接受多种分子文件（fchk/log/out/wfn/pdb/xyz；log 文件在内部转为 XYZ 后交给 Multiwfn），在画布上或通过序号范围选择原子，调用 Multiwfn 的 MPP 子程序，得到分子平面性参数与带符号的平面偏离跨度（SDP，单位 Å）。[24]原子按到拟合平面的带符号距离着色（画布中，也可选在 VMD 中），使用 ±0.5 Å 的发散色标（平面下方蓝、平面内白、平面上方红）。

### 4.9 IRC 能量与键级剖面

给定一批内禀反应坐标（IRC）[23] 点的 `.fchk` 文件目录，IRC 面板批量提取总能量，并通过 Multiwfn 计算所选原子对在每一点的 Mayer 键级[19]（结果按文件路径的 MD5 缓存，因此重复分析是瞬时的）。matplotlib 双轴图以键级（左轴）与能量（右轴）对反应坐标作图；单个数据点可点击，并把对应的 IRC 结构载入画布。键级/电荷列表可编辑，图例可拖拽，图表设置（标题、轴标签、网格、能量填充）完全可配。多条电荷曲线（6 种电荷类型任选）可叠加，且为保证清晰与键级曲线互斥。支持 CSV 与 PNG 导出。

### 4.10 扭曲–相互作用（DI）分解

基于 5 个 Gaussian `.log` 文件（两个优化后的片段、两个处于过渡态几何的片段，以及过渡态复合物），DI 面板解析 SCF 能量（可选用频率计算中的 ZPE 或 Gibbs 校正），并按 Bickelhaupt 与 Houk 的表述[13]执行扭曲/相互作用——活化张力分析：计算扭曲能 ΔE_strain,1 与 ΔE_strain,2、相互作用能 ΔE_int，以及总活化能 ΔE‡ = ΔE_strain + ΔE_int，以彩色编码的表格（Hartree 与 kcal mol⁻¹）呈现，并配有经典的 DI 能量阶梯箭头图与分解条形图。5 个结构中的任意一个都可显示在画布上，并可导出格式化的 HTML 报告。

### 4.11 能量跨度模型（ESM）

能量跨度面板实现 Kozuch–Shaik 的催化循环能量跨度分析。[12] 用户输入循环中各个物种（中间体与过渡态）的 Gibbs 自由能（ΔG，kcal mol⁻¹）以及温度；面板识别出转化频率决定中间体（TDI）与决定过渡态（TDTS），计算能量跨度 δE 与转化频率 TOF = (k_BT/h)·exp(−δE/RT)，并绘制带能量跨度箭头的逐级自由能剖面，当 TDTS 位于 TDI 之前时自动处理双循环情形。图表可导出为 PNG、SVG 与 PDF。

### 4.12 自旋密度可视化

对开壳层体系，轨道面板提供专门的自旋密度功能，通过 Multiwfn 计算 α−β 自旋密度 cube，并以等值面形式可视化，具备轨道管线全套的色标、风格、等值面阈值与导出控制。

### 4.13 沿 IRC 的活化张力（ASM）扫描

ASM 面板把第 4.10 节的扭曲–相互作用分解应用到内禀反应坐标的**每一个点**，而不只是过渡态几何。给定两个优化好的参考片段，以及每个 IRC 点对应的复合物与该几何下两个片段，面板计算

  ΔE_strain(i) = [E_def_A(i) − E_opt_A] + [E_def_B(i) − E_opt_B]
  ΔE_int(i)    = E_complex(i) − E_def_A(i) − E_def_B(i)
  ΔE(i)        = ΔE_strain(i) + ΔE_int(i)

能量口径与 DI 面板一致（纯电子能，或加入 ZPE / Gibbs 校正），并把三条曲线对反应坐标作图。参考态以各自优化后的 log 输入，IRC 点列表可由「自动扫描」批量填充；图片设置（曲线、散点形状、线型、图例、峰值标注、导出 DPI）沿用 ESP 面积分布图的那一套。

### 4.14 多 CUB 叠加

CUB 叠加面板载入多个 Gaussian cube 文件，在**同一个分子结构**上叠加显示各自的等值面（原子坐标取自第一个启用的 cub），从而把同一体系的不同性质 —— 多个分子轨道、自旋密度、密度差 —— 放在同一场景中比较。等值与不透明度为全局共用（渲染管线把各轨道合并成单张网格、一次 draw call），而正/负相位配色与相位翻转则**逐轨道独立**设置。

### 4.15 IRC 拆分

IRC 拆分面板把 Gaussian IRC 输出文件（`.out`/`.log`）解析为逐个结构点 —— 过渡态、正向点与反向点 —— 让用户在共享画布上用鼠标或方向键逐点浏览结构，并把整条路径一键导出为逐点单点能计算的 `.gjf`（含 `%chk`、`%mem`、`%nproc`，泛函与基组由用户填写）。点的排列顺序（反向点倒序 + TS + 正向点）可翻转。

## 5. 文件格式与互操作性

| 格式 | 在 MolStudio 中的角色 |
|---|---|
| Gaussian 格式化检查点（`.fchk`） | 主要输入：结构、轨道、能量、波函数 |
| Gaussian `.log` / `.out` | 几何与 SCF 能量（DI、IRC、MPP 经 XYZ 转换后使用） |
| Gaussian cube（`.cub` / `.cube`） | 直接渲染等值面/ESP，无需重算 |
| XYZ（`.xyz`） | 快速结构输入 |
| Molden（`.molden`、`.molden.input`） | 额外的结构来源 |
| PQR / PDB / WFN | 经面板对话框作为 AIM、MPP 输入 |

主窗口任意位置都接受这些格式的拖拽投放。原生解析器把原子坐标从 Bohr 转换为 Å，依据共价半径判断成键，并一步填充画布与轨道表。

## 6. 示例工作流程

<!-- TODO: 插入真实截图。
   图 2 — 主窗口 + 轨道等值面（HOMO/LUMO）。
   图 3 — ESP 表面（RWB 默认配色 + 极值点 + 色标条）。
   图 4 — IGMH 弱相互作用等值面（BGR 着色）与 IGM Map 散点图。
   图 5 — IRC 双轴剖面（键级/能量）。
   图 6 — ESM 自由能剖面与 DI 能量阶梯图。 -->

三个典型使用场景说明了设计意图：

1. **常规可视化与教学。** 载入 `.fchk`，在轨道表中查看 HOMO–LUMO 能隙，双击 HOMO 生成其等值面，在一键风格之间切换，导出 PNG —— 全程无需接触终端。
2. **电荷与成键分析。** 计算 Hirshfeld（或任意其他）电荷与 Mayer 键级；按电荷为分子着色；点击原子读取单个数值；把表格导出为 CSV 用于支撑材料。
3. **机理研究。** 导入 IRC 目录，把关键键级叠加到能量剖面上，点击过渡态点在画布上查看几何，随后在同一条反应路径上运行 DI 面板（5 个 log）与 ESM 面板（循环能量），得到反应完整的能量图像。

## 7. 许可、第三方声明与衍生作品声明

MolStudio 是自由软件，依 **GNU 通用公共许可证第 3 版（GPLv3-only）** 发布；完整的许可证文本随仓库提供（`LICENSE`）。由于 IboView 仅以 GPLv3 **本身**授权（不含"或更高版本"），MolStudio 在仍包含源自 IboView 的代码期间同样是 GPLv3-only，不得重新声明为适用该许可证的更高版本。

**渲染引擎（IboView 的衍生作品）。** MolStudio 的 OpenGL 渲染管线 —— 包括其深度剥离透明、Phong 光照模型、球棍模型几何、着色器寄存器模型，以及原子半径与共价半径数据表 —— 是 **IboView 程序的 Python 移植**（http://iboview.org/；移植所依据的是 IboView v20211019-RevA 发行版——该版本由作者标注为 pre-release，最后一个官方正式版本为 v20150427）；另有一个经过补丁的源码分支可供参考[18]）。IboView 由 Gerald Knizia 享有著作权（Copyright © 2015，GPLv3），实现的是 Knizia 及其合作者提出的内禀原子轨道（IBO）与内禀成键轨道分析。[3,4,17]

因此 MolStudio 构成 **IboView 的衍生作品**。我们明确陈述这一衍生关系的具体范围，因为它可以由源码直接核验：原子半径表（104 项）与共价半径表（110 项中的 108 项）在数值上与 IboView 的 `AtomicRadii`、`g_CovalentRadii` 完全相同；深度剥离合成着色器与着色器寄存器/雾化表达式同样为移植而来，若干默认渲染参数亦然。逐项审计记录维护在 `docs/iboview_transplant_audit.md` 中。**并非**源自 IboView 的组成部分包括：范德华半径（Bondi, 1964）、元素配色方案（Jmol/CPK、GaussView 以及本组自研的 MolCanvas 配色）、等值面网格化、分块高分导出路径、整个用户界面，以及全部 14 个面板。

依 GPLv3 §5，原始版权声明与修改声明已在受影响的源文件中以及仓库的第三方声明中保留，完整的对应源码已公开发布，作品整体以同一许可证分发。用户与下游再分发者必须保留这些声明，并使任何修改版本继续适用 GPLv3-only。我们恳请在衍生出版物中引用 IboView。

**其他第三方组件。** MolStudio 的分析依赖外部程序 Multiwfn（卢天，http://sobereva.com/multiwfn/）[5,6]，它以**独立进程**方式调用，不随 MolStudio 分发；VMD[1] 与 Tachyon[10] 是可选外部可执行程序，仅用于旧的渲染通道。VMD 的风格集改编自钟成的 vcube 2.0，[11] VMD 的虚线成键绘制遵循 KeinSci 论坛 Eming 的 `draw_bond` Tcl 脚本。PyQt5、PyOpenGL、NumPy、SciPy、PyMCubes 与 matplotlib 各按其自身许可证使用。仓库中维护完整的 `THIRD-PARTY-NOTICES.md`。

**本组自有组件。** 若干面板改编自本课题组早先开发的工具，并在此与 MolStudio 一并重新许可为 GPLv3：IGMH/IRI 面板源自 IGMH_Toolbox V4（Zenodo，doi:10.5281/zenodo.20791253）[15]，电荷面板源自本组早先的 ChargeViewer 工具，分子平面性面板源自 `mpp_auto_qt.py`。相关署名列于 `THIRD-PARTY-NOTICES.md`。

## 8. 结论与展望

GXNU MolStudio 提供了一个单一的中英双语桌面环境，把交互式 OpenGL 可视化器与一套全面的、由 Multiwfn 驱动的量子化学分析 —— 从电荷与键级，到 NBO、ESP、弱相互作用、QTAIM 拓扑、能量分解与催化循环动力学 —— 耦合在一起。其单画布架构、对外部引擎的脚本化集成，以及面向出版的导出，降低了科研与教学的门槛；而其 GPLv3 许可则确保社区能够审查、扩展与再分发它。后续开发将增加更多轨道与波函数分析、更多期刊风格导出模板、对更多量子化学程序包的支持，并扩充跨泛函与跨文件方言的自动化回归算例。

## 数据与代码可用性

GXNU MolStudio v1.0 以 GPLv3-only 开源。源码仓库公开于：

- GitHub（主）：https://github.com/houcheng-gxnu/GXNU-MolStudio
- CNB 镜像：https://cnb.cool/chem311/GXNU-MolStudio

Windows 独立可执行程序与本预印本同步发布。本文所述版本的可引用存档快照已存入 Zenodo（doi:10.5281/zenodo.22821586）。第三方声明、IboView 渲染引擎的衍生作品声明，以及逐项移植审计，分别见仓库中的 `THIRD-PARTY-NOTICES.md` 与 `docs/iboview_transplant_audit.md`。软件本身的引用格式：

> Hou, C. *GXNU MolStudio: Molecular Visualization and Quantum Chemical Analysis*, version 1.0.0; Zenodo, 2026. doi:10.5281/zenodo.22821586

## 作者贡献

侯成构思并指导本项目，开发代码、集成各分析模块，并制备插图与稿件。

## 利益冲突

作者声明不存在竞争性财务利益。

## 致谢

本工作得到国家自然科学基金（22463001）资助。感谢卢天博士开发 Multiwfn、Gerald Knizia 教授开发 IboView（其渲染管线在 GPLv3 下构成 MolStudio 画布的基础），以及钟成博士提供的 vcube 2.0 风格集。

## 参考文献

1. Humphrey, W.; Dalke, A.; Schulten, K. VMD: Visual Molecular Dynamics. *J. Mol. Graphics* **1996**, *14*, 33–38.
2. Hanwell, M. D.; Curtis, D. E.; Lonie, D. C.; Vandermeersch, T.; Zurek, E.; Hutchison, G. R. Avogadro: An Advanced Semantic Chemical Editor, Visualization, and Analysis Platform. *J. Cheminform.* **2012**, *4*, 17.
3. Knizia, G. IboView — A program for chemical analysis; http://www.iboview.org/ (accessed 2026). 移植所依据的是 IboView v20211019-RevA 发行版（作者标注为 pre-release；最后一个官方正式版本为 v20150427）。
4. Knizia, G. Intrinsic Atomic Orbitals: An Unbiased Bridge between Quantum Theory and Chemical Concepts. *J. Chem. Theory Comput.* **2013**, *9*, 4834–4843.
5. Lu, T.; Chen, F. Multiwfn: A Multifunctional Wavefunction Analyzer. *J. Comput. Chem.* **2012**, *33*, 580–592. 另见：Lu, T. A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn. *J. Chem. Phys.* **2024**, *161*,.
6. Lu, T. Multiwfn, version 2026.4.10 [computer software]; http://sobereva.com/multiwfn/ (accessed 2026).
7. Lu, T.; Chen, Q. Independent Gradient Model Based on Hirshfeld Partition (IGMH): A New Method for Visual Study of Interactions in Chemical Systems. *J. Comput. Chem.* **2022**, *43*, 539–555.
8. Lu, T. Tutorials on IGMH and IRI analysis in Multiwfn; http://sobereva.com/621 (IGMH) and http://sobereva.com/598 (IRI) (accessed 2026).
9. Mitoraj, M. P.; Michalak, A.; Ziegler, T. A Combined Charge and Energy Decomposition Scheme for Bond Analysis. *J. Chem. Theory Comput.* **2009**, *5*, 962–975.
10. Stone, J. E. An Efficient Library for Parallel Ray Tracing and Animation. M.S. Thesis, University of Missouri—Rolla, 1998.
11. Zhong, C. vcube 2.0 — Tcl scripts for batch rendering of Gaussian cube files with VMD; 计算化学公社 (Computational Chemistry Commune), thread 18150; http://bbs.keinsci.com/thread-18150-1-1.html (accessed 2026).
12. Kozuch, S.; Shaik, S. How to Conceptualize Catalytic Cycles? The Energetic Span Model. *Acc. Chem. Res.* **2011**, *44*, 101–110.
13. Bickelhaupt, F. M.; Houk, K. N. Analyzing Reaction Rates with the Distortion/Interaction-Activation Strain Model. *Angew. Chem. Int. Ed.* **2017**, *56*, 10070–10086.
14. Lu, T.; Chen, F. Atomic Dipole Moment Corrected Hirshfeld (ADCH) Population Method. *J. Theor. Comput. Chem.* **2012**, *11*, 163–183.
15. Hou, C. IGMH_Toolbox (Version 1.0.0) [Computer software]. Zenodo, 2026.
16. Lu, T.; Chen, Q. Interaction Region Indicator (IRI): A Simple Real Space Function Clearly Revealing Both Chemical Bonds and Weak Interactions. *Chemistry–Methods* **2021**, *1*, 231–239.
17. Knizia, G.; Klein, J. E. M. N. Electron Flow in Reaction Mechanisms — Revealed from First Principles. *Angew. Chem. Int. Ed.* **2015**, *54*, 5518–5522.
18. KoehnLab. iboview — patched source code of IboView; https://github.com/KoehnLab/iboview (accessed 2026). 仅供参照；移植所依据的是 v20211019-RevA 发行版（文献 3）。
19. Mayer, I. Charge, Bond Order and Valence in the Ab Initio SCF Theory. *Chem. Phys. Lett.* **1983**, *97*, 270–274. 另见：Mayer, I. On Bond Orders and Bond Valences in the Ab Initio Quantum Chemical Theory. *Int. J. Quantum Chem.* **1986**, *29*, 73–84.
20. Weinhold, F.; Landis, C. R. *Valency and Bonding: A Natural Bond Orbital Donor–Acceptor Perspective*; Cambridge University Press: Cambridge, 2005.
21. Murray, J. S.; Politzer, P. The Electrostatic Potential: An Overview. *WIREs Comput. Mol. Sci.* **2011**, *1*, 153–163.
22. Bader, R. F. W. *Atoms in Molecules: A Quantum Theory*; Oxford University Press: Oxford, 1990.
23. Fukui, K. The Path of Chemical Reactions — The IRC Approach. *Acc. Chem. Res.* **1981**, *14*, 363–368.

24. Lu, T. Simple, Reliable, and Universal Metrics of Molecular Planarity. *J. Mol. Model.* **2021**, *27*, 263.

---

<!-- ═══════════════ 提交前清单（请逐项处理）═══════════════
[x] 作者：侯成（单一作者），ORCID 0000-0003-2967-0326，
    通讯 houcheng@gxnu.edu.cn，广西师范大学化学与药学学院
[x] 资助号：国家自然科学基金 22463001
[ ] 图 2–6（含图注）；文中"布局示意图"仍为占位
[x] 参考文献审计同步完成（与英文稿一致，编号 1–23）
[x] Zenodo DOI 已回填 10.5281/zenodo.22821586
[ ] 确认 ESM(§4.11) 与 DI(§4.10) 内部公式与代码一致（含 ZPE/Gibbs 处理、双循环）
[ ] 本中文稿与英文稿需保持同步：若改动英文稿，请同步至本文件
── 2026-09-18 同步修订明细 ──
  · 面板数 11 → 14；§4 新增 4.13 ASM 扫描、4.14 多 CUB 叠加、4.15 IRC 拆分
  · Ref 3 IboView 官方题名；Ref 7 IGMH 页码 539–555 + DOI
  · Ref 11 vcube 2.0 改引计算化学公社论坛帖 18150（原 GitHub 链接无依据）
  · 补 DOI：Ref 2 / 14 / 16；Ref 6 加 [computer software]；Ref 9 删多余标题片段
  · 删除 Ref 16 ChargeViewer，原 17–24 升位为 16–23，正文引用同步重编号
  · 作者/ORCID/基金/作者贡献占位已填实
════════════════════════════════════════════════════════ -->
