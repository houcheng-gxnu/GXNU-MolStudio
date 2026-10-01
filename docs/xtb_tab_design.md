# 新增「xTB 计算」tab —— 评估与界面设计

> 需求：在 MolStudio（OrbitalViewer 5.3）里加一个新 tab，把
> xTBridge Lite（`xtbridge/lite.py`）的 xTB 计算功能整合进来。
>
> 本文只做**评估 + 设计**，不含实现。设计稿出图脚本：`_xtb_tab_mock.py`
> （`_xtb_tab_mock.png` 就绪态 / `_xtb_tab_mock_done.png` 算完态）。

---

## 0. 结论

| 问题 | 结论 |
|---|---|
| 能不能做 | **能**，而且比预想便宜：Lite 里 90% 是**不依赖 PyQt5 的纯逻辑**，可以整段搬过来 |
| 界面能不能照搬 | **不能**。LiteWindow 是 1180×880 的独立窗口，MolStudio 的 tab 是**实测 665 px 宽的右栏一页**，控件排布与文案必须重画（设计见 §3） |
| 新增外部依赖 | 只有 **xtb.exe** 一个（不打包、走路径设置）。本机已实测存在多份可用副本，路径各异，统一由设置项配置 |
| 联用模式（高斯×xTB） | 需要 g16.exe（本机已装）+ gview.exe（可选）。建议做成**默认收起**的进阶区块 |
| 授权 | xtbridge 是 **MIT**（见其仓库 LICENSE，Copyright (c) 2026 houcheng-gxnu），并入本 GPLv3 项目只需在 `THIRD-PARTY-NOTICES.md` 加一段署名，无兼容问题 |
| 工作量 | 一期（单点/优化/频率 + 日志 + 结果回画布）≈ 一个 `xtb_panel.py` + 一个 worker；二期接电荷/键级/曲线；三期联用 |

---

## 1. `lite.py` 拆解：哪些能搬，哪些要重画

Lite 的代码在文件里分得比想象中干净：**上半个文件（1–330 行）全是无 GUI 依赖的逻辑**，
下半个文件（`_build_window()` 以内）才是界面。

### 1.1 可直接复用（不 import PyQt5，原样搬或改个 import）

| 来源 | 内容 | 用途 |
|---|---|---|
| `xtbridge/scan_utils.py` | `parse_gjf_atoms` / `parse_gaussian_scan_constraints` / `gaussian_to_xtb_scan` | .gjf 解析、约束 → xTB `$constrain`/`$scan` |
| ↑ | `prepare_bridge_route` | **联用模式的命门**：自动去掉路由里的方法关键字、给重元素补基组 |
| ↑ | `charge_mult_problem` | 电荷/多重度自洽性**提前拦截**（xTB 不一致会直接 fatal） |
| ↑ | `XTB_METHODS` / `SOLVATION_MODELS` / `ALPB_SOLVENTS` / `GBSA_SOLVENTS` | 方法、溶剂化下拉的全部数据 |
| ↑ | `compose_calc_args` / `xtb_bridge_argv` / `format_argv` | 拼命令行 + 拼"人能读的命令预览" |
| ↑ | `inject_external` / `patch_charge_mult` | 往 .gjf 注入 `external=`、改电荷/多重度 |
| `xtbridge/client.py` | `write_client_bat` / `build_bridge_env` | 联用模式的 External 包装脚本与环境变量 |
| `xtbridge/workers.py` | `XtbWorker`（跑独立 xtb）/ `GaussianWorker`（跑高斯并 tail 输出文件） | 后台线程，**改名后**并入本项目的 `workers.py`（本机已有同名类，需避免冲突） |
| `xtbridge/file_parser.py` | `parse_xtb_hessian_output` / `parse_xtb_vibspectrum` | 虚频个数与频率值 |
| ↑ | `parse_last_standard_orientation` / `summarize_gaussian_optimization` | 联用模式取末结构 / 收敛判定 |

### 1.2 只能用思路、不能搬代码

| 来源 | 原因 |
|---|---|
| `lite.py` 的 `LiteWindow`（UI 全部） | 独立 QMainWindow + 自己的 `LITE_QSS_EXTRA`；尺寸（1180×880）、顶栏、"输入/输出"大页签都是为单窗口应用设计的 |
| `LITE_QSS_EXTRA` | 配色与本项目 Bridge 皮肤（`main_window_clean2.py`）**同源**，但本项目由全局 QSS 统一管，面板里不应再叠一层 |
| 日志节流（`_log` / `_flush_log` / `_drain_log`） | 逻辑要抄，但本项目 `_append_log` 是**逐条写 QTextCursor**（无节流、无上限），直接喂高斯输出会卡界面 —— 见 §4.4 |

### 1.3 Lite 已经解决的三个"血泪坑"（照抄结论即可）

1. **路由里不能有方法关键字**：写了 `b3lyp` / `pbe1pbe` 之类，高斯会**静默忽略 `external=`** 自己去跑 SCF，返回码还正常、日志无提示 → `prepare_bridge_route` 负责删掉。
2. **含 Z>54 元素必须先给基组**：高斯建基组这一步（Link 301）永远执行，默认 STO-3G 只覆盖到 Xe，含 Ir/Pt 时会在调用 external **之前**就 `IA out of range in STO` 退出 → 自动补 `sdd`。
3. **频率要用 `--hess` 而不是 `--ohess`**：后者会先把结构优化到极小点，过渡态候选的虚频会被抹掉。

---

## 2. 整合点：新 tab 与本项目现有面板怎么接

这是本次整合**真正有价值的部分** —— xTB 算出来的东西，本项目的面板几乎都能直接用：

| # | 接口 | 落点（已核对的现有实现） | 说明 |
|---|---|---|---|
| 1 | 输入：直接用**当前载入的分子** | `main_window._load_molecule` / `mol_canvas.set_data` | 原子格式 `(idx, sym, an, (x,y,z))`；`.xyz` 由 `_parse_xyz` 解析 |
| 2 | 电荷/多重度**自动带入** | fchk 里有 `Charge` / `Multiplicity` 字段（已在 `_irc_test\irc_pt1.fchk` 实测：0 / 1） | 不用用户手填，手改也能覆盖 |
| 3 | 结果回 3D 画布 | `MolCanvas.set_data(atoms, bonds)` | 优化末结构 / 逐帧轨迹都能推；轨迹播放复用画布重绘 |
| 4 | xTB 电荷 → 「电荷分析」 | `charge_viewer.parse_chg_file` + `ChargePanel._load_chg` | 把 xTB 的 `charges` 文件写成 `.chg`（格式 `元素 x y z q`，与 `benzene.chg` 一致）→ 表格、CPK→电荷着色、CSV 导出**全部现成** |
| 5 | xTB 键级 → 「键级」 | `BondOrderPanel._populate_table(dict)` | xTB 的 `wbo` 文件就是 `i j bo` 三元组，直接转 `{(i,j): bo}`；建议加一个公开入口 `set_bond_orders()` |
| 6 | 能量曲线 | `energy_span_panel` 已在用 `matplotlib` + `FigureCanvasQTAgg` | 优化过程 E–step 小图，风格可照抄该面板 |
| 7 | 联用模式生成 .gjf | `etsnocv.gaussian_generator.GjfGeneratorWidget`（可直接嵌入式复用） | 需要"从画布生成 .gjf"时用它，不必自己写 |

> 也就是说：**加这一页的收益不只是"多一个算 xTB 的地方"**，而是让 xTB 成为
> 现有电荷/键级/画布/离子分析的"前置引擎"（秒级预优化 → 再上 Multiwfn/高斯）。

---

## 3. 界面设计

### 3.1 放在哪

* 导航条（左侧 `MainNav`）**插在「轨道」之后**（成为第 3 项），i18n key `tab_xtb`，文字「xTB」。
* **不进 `_NO_CANVAS_KEYS`**：这一页需要一直看得见左侧画布（看结构、看轨迹、看电荷着色）。
* 三套皮肤（classic / clean / clean2）都走 `OrbitalVisApp._setup_ui` 的 `_add_tab`，
  因此只要按现有约定加一页，**三套皮肤自动都有**，无需分别改。

### 3.2 面板结构（6 张卡，单列自上而下）

![就绪态](../_xtb_tab_mock.png)

| # | 卡片 | 内容 | 设计理由 |
|---|---|---|---|
| 1 | **计算任务** | 任务下拉（几何优化 / 单点能 / 频率检查 / 优化+频率）+ `▶ 开始计算` / `终止`；卡片标题行右侧是**状态胶囊**（`● 就绪 · GFN2-xTB · 气相 · 8 线程`） | 与 Lite 顶部操作条同构：主按钮和状态永远在同一处，不用翻找。胶囊顺带把"当前会用什么参数算"写出来 |
| 2 | **体系与输入** | `输入 [当前载入的分子 ▾] [打开…]` + 只读摘要条（`benzene.fchk · C₆H₆ · 12 个原子`）+ 电荷 / 多重度 | 默认吃当前载入的分子，"所见即所算"；摘要条让用户一眼确认没算错对象 |
| 3 | **方法与参数** | xTB 方法 / 溶剂化 / 溶剂 / 参考态 / SCF 精度 `--acc` / 电子温度 `--etemp` / 并行线程 / 附加参数 + **命令预览条**（等宽字体，显示 `xtb … --gfn 2 --opt --parallel 8`） | 参数全部来自 `scan_utils` 的数据表；命令预览是 Lite 日志里最有用的一行，把它提前到**运行前** |
| 4 | **算完之后** | 4 个勾选：结构送回画布 / 电荷送「电荷分析」/ 键级送「键级」/ 自动跑频率检查报虚频 | 对齐 §2 的 4 个整合点；默认全开 |
| 5 | **结果** | 指标格（总能量 / HOMO–LUMO / 优化步数 / 末步 ΔE / 虚频个数 / 判定）+ 按钮行（打开输出目录 / 导出结构·电荷 / 画能量曲线）+ 内嵌日志 | 结论用"人话"给（极小点 / 候选过渡态 / 不是过渡态），数字只是佐证 |
| 6 | **进阶：高斯 × xTB 联用** | 默认**收起**（一行说明 + ▾）。展开后：g16.exe / gview.exe / 高斯关键字 / "算完用 GaussView 打开"，以及路由注意事项 | 需要高斯的人少；展开后功能与 Lite 的主线完全一致 |

算完之后（结果指标 + 日志，联用区块展开）：

![算完态](../_xtb_tab_mock_done.png)

### 3.3 尺寸预算（实测，不是估计）

右栏滚动视口（本次实测，`OrbitalVisApp` + `WA_DontShowOnScreen`，窗口不弹出）：

| 窗口尺寸 | 右栏滚动视口 |
|---|---|
| 1400 × 820（默认） | **665 × 681** |
| 1920 × 1080（最大化） | **950 × 941** |

导航条现有 **17** 项（可视化 / 轨道 / 电荷键级 / NBO / ESP / IGMH / AIM / ETS-NOCV / MPP /
IRC 分析 / DI 分析 / ASM 扫描 / CUB 叠加 / 晶体 / 能量跨度 / IRC 拆分 / 日志），新增后 18 项。

因为宽度在 665–950 px 之间浮动，本设计的控件一律**给固定宽或上限宽**
（下拉 150/210、数值框 64–80），窗口变宽时只是右边多留白，不会把控件横着抻开。
本设计稿的实测高度：

| 状态 | 面板总高 | 卡片高度（自上而下） |
|---|---|---|
| 就绪 | **865 px** | 计算任务 90 / 体系与输入 148 / **方法与参数 230** / 算完之后 76 / 结果 198 / 联用（收起）68 |
| 算完（联用展开） | **1213 px** | …结果 370 / 联用 244 |

即：**默认窗口下滚一屏内、最大化后一屏放得下**；算完并把联用展开时需要滚动。
对比现有「可视化」页的参数区（653 × 2300 px），这一页已经相当克制。

### 3.4 三种任务的交互

```
几何优化   载入分子 → 选「几何优化」→ 开始
            → 日志实时滚 → 算完自动：末结构送画布 + 电荷/键级送面板 + 虚频体检
单点能     同上，只是不落轨迹；用于"快速看一眼能量/轨道能级"
频率检查   在现有几何上跑 --hess（不预先优化），用于判断 TS 候选（虚频 1 个）
联用       展开「进阶」→ 填 g16 → 高斯关键字（opt(nomicro)）→ 开始
           → xTB 每步供能/梯度驱动高斯 → 末结构可选 GaussView 打开
```

### 3.5 运行中的反馈与失败处理

* 运行中：`▶ 开始计算` 置灰 → `终止` 可点；状态胶囊切「运行中…」并显示已跑步数与当前能量；日志区自动滚。
* 无 xtb.exe / 无 g16.exe：**点开始时就弹提示**（不等到跑一半），并给"去路径设置"的跳转。
* 电荷/多重度不自洽：用 `scan_utils.charge_mult_problem` 的话术**在开始前**拦住（原文："多重度 4 与电子数不匹配：体系 91 个电子（奇数）…xTB 会直接报错退出"）。
* 退出码非 0：按 Lite 的做法**先解析结构再判定**（`Number of steps exceeded` 这类情况结构仍然可用），日志给一句人话原因。
* 日志：节流刷新 + 只留最近 5000 行 + 完整输出写 `<工作目录>\<结构名>_xtb.out`（见 §4.4）。

### 3.6 语言与皮肤

* 面板自带 `zh/en` 文案表（照 `charge_viewer` / `esp_panel` 的写法），实现 `set_lang()`；nav 文字走全局 `i18n` 新增 key `tab_xtb`。
* 不使用 Lite 的 `LITE_QSS_EXTRA`；只给卡片/命令预览条补最少几条 objectName 规则（`Card` / `CmdPreview` / `StatusPill`），与 Bridge 皮肤同色。

---

## 4. 风险与坑（已核实的部分）

### 4.1 外部程序路径
xtb.exe / g16.exe **不进安装包**（体积 + 授权），必须靠路径设置。建议在
`PathsDialog`（现 Multiwfn / VMD / Tachyon 三项）里增加 **xTB** 与 **Gaussian(g16)** 两栏，
`fchk_orbital.load_config/save_config` 同步扩字段（现函数签名是 3 个位置参数，扩成 keyword 兼容旧 ini）。

### 4.2 xTB 版本参数差异
`XTB_METHODS` 里 GFN-FF 必须写 `--gfnff`（写成 `--gfn -1` 会被静默当 GFN2 算错）；
g-xTB 走 tblite，**不支持溶剂化**（`--gxtb --alpb water` 直接 fatal），且能量与 GFN1/GFN2 不可比 —— 界面上要做联动禁用 + 提示。

### 4.3 中文路径与空格
Lite 全程用 argv 列表（不用 shell 字符串），本项目也应保持；高斯/xtb 的 `cwd` 用工作目录本身。

### 4.4 日志洪泛（本项目的现存差异）
`main_window._append_log` 是**逐条 append + 自动滚动**，而高斯一次优化能刷十几万行。
Lite 专门为此做了三层限流（120 ms 定时器 / 每次最多 400 行 / 缓冲 2000 行）。
xTB 的 `--opt` 输出量不大，但**联用模式 = 高斯输出**，必须走节流通道，
否则就是本项目历史上遇到过的"界面卡死"。建议给新面板一条独立的节流日志通道，不要去挤全局日志。

### 4.5 打包
新增模块要进 `OrbitalViewer.spec` 的 `hiddenimports`；`scan_utils` / `client` 等
如果以子包形式引入（`xtbridge/…`），还要注意 PyInstaller 的包收集。
建议**只搬需要的文件进本项目顶层**（如 `xtb_logic.py`），不做 `import xtbridge`（否则会连带 PyQt5 顶层窗口等无关模块）。

### 4.6 线程与杀软
子进程一律 `CREATE_NO_WINDOW` + QThread（本机 360 会拦外部 exe 的直接写入，Lite 里已实测过 `PermissionError` 的处理）；工作目录不可写时退到临时目录（Lite `write_client_bat` 的做法）。

---

## 5. 分期落地建议

| 期 | 内容 | 验收 |
|---|---|---|
| **P0** | 新 tab + 计算任务卡 + 方法与参数卡 + 节流日志 + 结果指标；支持单点 / 优化 / 频率；结果结构送回画布 | 拿 benzene：GFN2 优化 12 步收敛、末结构上画布、虚频 0 个 |
| **P1** | 电荷 → 「电荷分析」、WBO → 「键级」、能量曲线、轨迹逐帧 | 电荷着色与键级表数值与 xtb 输出一致 |
| **P2** | 高斯 × xTB 联用（.gjf 注入 external、路由整理、GaussView 打开、后续精算输入）+ 约束扫描（`gaussian_to_xtb_scan` / `$scan`，可接现有 ESM 曲线） | 含 Ir 的体系不报 STO 错；`opt(nomicro)` 正常收敛 |

---

## 6. 需要你确认的三件事

1. **这一页的主线**：以「独立 xTB 快速计算（预优化 / 频率 / 能量）」为主、联用作为进阶（本设计稿的取法），还是反过来以「高斯 × xTB 联用」为主？
2. **算完的默认动作**：默认就把结构送回画布、电荷送「电荷分析」、键级送「键级」全开，还是只在日志里提示、由用户点按钮？（现设计是全开）
3. **xtb.exe / g16.exe 的路径**：进「⚙️ 路径设置」对话框（推荐，和 Multiwfn/VMD 并列），还是这一页自己一个路径栏？
