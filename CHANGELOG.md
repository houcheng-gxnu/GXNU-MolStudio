# Changelog

All notable changes to OrbitalViewer will be documented in this file.

---

## [Unreleased]

### 仓库结构规范化（2026-10-01）
- **源码全部收进 `molstudio/` 包**：根目录 31 个模块按职责迁入
  `molstudio/{core,ui,panels,render}` + `assets/`；`main.py` 变成薄入口，
  同时可用 `python -m molstudio` 启动。
- **导入统一为包内绝对导入**（`import file_dialogs` → `molstudio.ui.file_dialogs`），
  共重写 44 个文件；新增 `molstudio/paths.py` 统一资源与配置路径，
  `fchk_orbital.ini` 位置不变（源码=仓库根目录，打包=exe 同目录）。
- **打包配置去掉绝对路径**：`OrbitalViewer.spec` 以 spec 所在目录为基准，
  模块清单改由 `collect_submodules("molstudio")` 自动收集——新增面板不必再手工
  登记 hiddenimports（旧写法漏登记就会"打包版整个页签消失"）。同时排除
  jupyter / vtk / skimage 等未使用依赖，产物从 1.13 GB 降到 619 MB。
- **补齐工程元数据与自检**：`pyproject.toml`、`requirements.txt`、`tests/`
  （全子模块导入自检 + 离屏界面冒烟，`pytest tests -q`）；`.gitignore` 放行
  `molstudio/assets/*.png`（此前 `校徽.png` 被 `*.png` 规则挡住没入库，
  干净 clone 后直接打包会失败）。
- 实验性的 `wgpu_viewer.py`（依赖未安装的 wgpu 包）移入 `legacy/`；
  `etsnocv/__main__.py` 补 `if __name__ == "__main__"` 守卫（原先 import 即启动）。

### Build
- **启动时那个「只看得见滑块的小窗口」= 搜狗输入法状态条，已从程序侧规避**。

  承接上一条：撤掉品牌启动画面后用户仍能看到一个小窗口停一下、里面
  「只有一些滑块一样的东西」。继续排查：

  1. `main.py` 的窗口枚举（只记录**本进程**的顶层窗口）显示启动全程多出一个
     **`345x48 class='SoPY_Status'`、标题为空**的窗口。
  2. 换成**连拍截屏 + 程序化差分**（每 250ms 抓全屏，与最终稳定画面做差）：
     差异区域始终是主窗口自身在填充（1672×731），**没有独立的第三方窗口** ——
     说明那个小窗口在程序化的画面差分里不成立，更像是系统级覆盖层。
  3. 查环境：本机装了**搜狗输入法**
     （`SogouInput` 16.6.0.4952，`SGTool`/`SogouCloud`/
     `SogouImeBroker` 均在运行）。`SoPY` = **Sogou PinYin**，状态条窗口由输入法
     通过 IME 注入在**宿主进程内**创建，所以它属于本进程、标题为空。
  4. 触发条件确认：启动时 `app.focusWidget()` 是一个 **`QLineEdit`** ——
     文本输入框一拿到焦点，输入法就弹出状态条。

  **修法（`main.py`）**：不再让启动焦点落在文本输入框上，交给画布。
  ★ **顺序很关键：必须在 `window.show()` 之前 `canvas.setFocus()`。**
  放到 `show()` 之后再抢焦点是没用的 —— 实测那样 `SoPY_Status` 照样出现
  （QLineEdit 已经拿过焦点、输入法窗口已经弹出）。`show()` 之后另留一道
  兜底：若焦点仍是输入框则收回给画布。

  验证（源码运行与打包运行，看 `~/molstudio_dbg.log` 的窗口枚举）：

  | | 修复前 | 修复后 |
  |---|---|---|
  | 主窗口 1422×876 | 有 | 有 |
  | 1×1 Qt 内部窗口 | 有 | 有 |
  | 560×380 启动画面 | 有 | **无**（上一条已关） |
  | **345×48 `SoPY_Status`** | **有** | **无** |

  另记两个排除项，供以后参考：
  - 画布参数面板（`QFrame objectName=CubParams`，653×2611，**29 个滑块**）
    在 `main_window.py` 里被 `setParent(None)` 摘下来、几百行后才挂回右侧 tab，
    期间是「可见的无父控件」，理论上会被 Qt 当顶层窗口弹出来（内容被裁 →
    正好"只看得见滑块"）。`_startup_flash_probe.py` 钩住 `QWidget.setParent`
    与 `show()`、并在下一轮事件循环复查，实测**构建期间一个可见顶层窗口都没有**，
    这条路径清白。
  - 连拍截屏 + 差分脚本（`_startup_shots.ps1` / `_startup_shots_analyze.py`）
    与 28 张截图属一次性诊断产物，核对完已删除。

- **启动时的「控制面板一样的窗口」= 品牌启动画面，已默认关闭**（用户要求）。

  定位方式：`main.py` 自带一个**进程内顶层窗口枚举**（前 8 秒每 150ms 记录新
  窗口的尺寸/类名/标题到 `~/molstudio_dbg.log`）。打包版启动全程只出现 3 个
  窗口：**560×380 的启动画面**、一个 1×1 的 Qt 内部窗口（肉眼不可见）、主窗口。
  所以用户看到的那块"面板"就是启动画面本身 —— 它是一块 560×380 的白底独立
  顶层窗口（蓝色顶条 + 校徽 + 文案 + 加载条），并且**写死停留 5 秒**
  （加载条 `el/4600`，`el >= 5000` 才淡出），读起来就是"弹出一个面板、然后消失"。

  > 顺带排除了一条更可疑的路径：`main_window.py` 把画布参数面板
  > `setParent(None)` 摘下来、几百行之后才 `addWidget` 回右侧 tab，
  > 而这期间它是**可见的无父控件** —— 理论上会被 Qt 当成顶层窗口弹出来。
  > 写了 `_startup_flash_probe.py` 钩住 `QWidget.setParent` 实测：
  > **构建期间一个可见顶层窗口都没有**，这条路径是清白的。

  改动（`main.py`）：启动画面改为**默认不显示**，需要时设环境变量
  `MOLSTUDIO_SPLASH=1` 恢复；无启动画面时主窗口直接 `raise_()` +
  `activateWindow()` 后进事件循环。启动画面的绘制与淡出代码原样保留。

  验证：源码运行与打包运行的启动日志里都不再出现 560×380 窗口
  （`splash disabled (MOLSTUDIO_SPLASH not set)`），只剩主窗口 1422×876。

  另注：日志里那个 `345x48 class='SoPY_Status'` 是**搜狗输入法的状态条**
  （外部进程的窗口，不是本程序的）；启动画面撤掉后主窗口立即取得焦点，
  它才露出来。与本程序无关。

- **文件夹形式（onedir）打包完成**：`pyinstaller OrbitalViewer.spec` →
  `dist\MolStudio\`（`MolStudio.exe` 16.0 MB + `_internal\` 3057 文件 / 317 MB）。

  打包前核对：**37 个探针全通过（0 失败）**。打包后核对：

  - 启动冒烟：exe 起来后存活 35s、主窗口标题正常
    （`MolStudio — 分子可视化与量子化学分析 [PyQt 中文版]`）、内存 355 MB、
    `~/molstudio_dbg.log` 无异常。
  - `pyi-archive_viewer -l -r` 递归 1734 项，15 个关键模块
    （`esp_panel` / `esp_viewer` / `igmh_panel` / `main_window_clean` /
    `ovcanvas._glwidget` / `matplotlib` / `mcubes` / `vmd_embed` …）**全部在包内**。
  - Qt 运行库路径为 PyInstaller 6.x 的标准布局
    （`_internal\PyQt5\Qt5\bin\Qt5Svg.dll` 等）；图标与校徽落在 `_internal\`，
    `main.py` 同时尝试「exe 同目录」与 `sys._MEIPASS`，两处都能找到。
  - spec 里那段「360 拦截 DLL」的放回逻辑正常执行
    （`d3dcompiler_47.dll`、`ucrtbase.dll` 已放回）。

- **修掉一个「探针期望值过时」的假失败**（`_multibond_probe.py` 4 项）。
  失败表现是顶点数恰好是期望值的 **2 倍**（96 vs 48、288 vs 144），看着像
  键几何被重复追加。查清后**不是重复**：生产代码把键圆柱分段数从 12 提到了
  **24**（放大与高清导出时圆柱的棱可见，见 `_glwidget.py` 的注释），
  顶点数因此正好翻倍，而探针把 12 写死在断言里。

  处理：把分段数提成**单一来源常量** `BOND_CYL_SEG = 24`
  （`ovcanvas/_glwidget.py`），6 处使用点（`cyl_a/b`、`sub_a/b`、两处虚线几何）
  都改为引用它；探针也从常量推导期望值
  （单键 `2*2*BOND_CYL_SEG`、端盖圆柱每段 `4*BOND_CYL_SEG+2`、三键 `3*2*2*BOND_CYL_SEG`），
  以后再调分段不会假失败。

  顺便确认这个 2 倍**不影响渲染**：不是同位置两份网格，只是环向边数翻倍；
  真正「画两遍」的是有意设计的键二次上色 pass（`render_opaque` 用 `GL_LESS`、
  `render_bonds` 用 `GL_LEQUAL` 重绘，顶点数据逐位相同 → 深度相等、确定性通过，
  不会 z-fighting）。

### Fixed
- **NBO 页签「翻转相位」会变色 —— 用的是载入那一刻的旧配色**。
  用户路径：在 NBO 里可视化一个/两个轨道 → 之后换配色（套一键样式、色轮、
  选色）→ 点「翻转相位」，画面不是把**当前**正/负色对调，而是被拽回载入时的
  那一对色（看起来就是"一翻转就变色"）。

  根因在 `ovcanvas/_glwidget.py`：每条轨道记录 `(cube, pos, neg, pc, nc)` 里的
  `pc/nc` 是**载入当时**抄下的颜色；`set_phase_colors()`（换配色走的就是它）
  只把新色平铺到合并后的表面上，**没有回写各轨道的记录**。于是
  `flip_orbital()/flip_all_orbitals()` → `_rebuild_orbital_meshes()` 按记录重建时，
  用的还是旧色。顺带还有两个连带问题：多轨道下换配色会把两个轨道铺成同一对色
  （E(2) 里"受体反相"的区分被抹掉）；`_rebuild_orbital_meshes()` 结尾还把
  `self._pc/_nc` 回写成 `recs[0]` 的色，若第 0 条恰好是反相轨道，基准色就被带偏。

  修法（都在 `_glwidget.py`）：
  - 新增 `_orbital_pair_mode`：记录每条轨道的配色**来源**——
    `base`（跟随当前正/负基准色）、`swapped`（跟随基准的反相，NBO E(2) 受体就是
    这种）、`fixed`（该轨道自带独立配色，如 CUB 叠加面板的逐条调色，不跟基准）。
  - 新增 `_sync_rec_colors()`：把各轨道记录里的颜色按上面的模式对齐到**当前**
    基准色（`fixed` 的原样保留），几何不动。
  - `set_phase_colors()`：单轨道且 mode=base 走快路径（直接平铺 + 同步记录色，
    保持换配色时的流畅度）；多轨道则同步记录色后 `_rebuild_orbital_meshes()`
    按轨道重铺，E(2) 的"反相"关系因此保住。
  - `_rebuild_orbital_meshes()` 不再用 `recs[0]` 回写 `self._pc/_nc`。
  - 结果：「翻转相位」永远翻**当前**这套色，翻两次回到原样；换配色后各轨道仍
    彼此可区分。
  - 验证：新探针 `_phase_flip_probe.py`（单轨道 + E(2) 双轨道两条路径：
    载入 A → 换 B → 翻转，断言逐顶点色 = B 的对调而不是 A；再真渲染一张图确认
    紫/绿两族像素对调），以及 `_oneclick_style_probe.py`、
    `_style_roundtrip_probe.py`、`_vesta_style_check.py`、
    `_vesta_iso_color_probe.py` 全部通过。

- **NBO 可视化把画布配色打回 sob-art —— 一键样式各自的等值面配色被覆盖**。
  用户路径：点某个一键样式（VESTA / CYLview / IQmol …，每个样式都有自己的
  正/负相位色与材质）→ 进 NBO 可视化单 MO 或二阶微扰 E(2) 双 cub 叠加 →
  配色变成 sob-art 的绿/青。

  根因：`nbo_viewer.py` 在可视化前调用 `_apply_style()` →
  `glw.set_style(主窗口 VMD 风格下拉的值)`。那个下拉与画布的等值面样式**不是
  同一套东西**（不会随一键样式更新，默认还是 sob-art），而 `set_style()` 会把
  相位色、材质寄存器、不透明度**整体重置成该样式的默认值** —— 于是用户刚点的
  一键样式被覆盖。

  修法（`nbo_viewer.py`）：
  - `_apply_style()` 停用（保留空壳避免旧代码 AttributeError）；单 MO 路径
    `_on_cube_done()`、E(2) 路径 `_visualize_dual()` 都不再切换画布样式，
    只把 cube 交给画布，配色/材质沿用**当前**那套。
  - E(2) 双轨道的配色对改为在**真正载入 cube 的那一刻**（`_load_dual_cubes`）
    从画布当前相位色取（供体 = 当前正/负，受体 = 同一对色相位互换），既保持
    该样式自己的配色，又能区分两个轨道；也顺带修掉"生成 cube 期间用户换了样式
    导致配色对不上"的竞态。
  - 验证：新探针 `_nbo_style_probe.py`（在真实主窗口里套 VESTA 样式，
    分别走单 MO 与 E(2) 双 cub 两条载入路径）：相位色仍是 (0,255,255)/(255,255,0)
    而不是 sob-art；材质寄存器、不透明度 0.2、透明合成 WBOIT 均未被改；
    两轨道关系为 base / swapped；面板色块同步为当前样式。

- **等值面透明度滑块"一下从不透明变透明"——着色器里的端点断崖**。
  CYLview / VESTA（以及同源的 MolStudio）下拖动「透明度」滑块，表面在
  0% → 1% 之间直接从不透明跳到半透明，此后大半个滑块几乎看不出变化。
  实测（`_opacity_sweep_probe.py`，逐档导出算物体区域亮度）：

  | 透明度 0% → 1% | 其后相邻档中位 |
  |---|---|
  | 亮度差 **146**（MolStudio）/ **149**（CYLview）/ **132**（VESTA） | 约 **4** |

  即 35 倍跳变，而滑块其余部分只有缓慢变化。

  **根因（`ovcanvas/_glwidget.py` 的 `shade_base_color`）**：等值面 alpha 一直
  由两件事决定 —— 滑块值 `DiffuseColor.a` 乘上**光照调制**（漫反射强度的逐片元
  和，亮处 ≈1、暗处 ≈0）。而端点又写了

  ```glsl
  if (DiffuseColor.a >= 0.999) color.a = 1.0;
  ```

  于是滑块拉满时表面被强制全实，只要挪开一档，alpha 立刻掉到调制后的
  0.6~0.8（暗侧更低）—— 中间没有插值，就是那个"突然变透明"。这行本身不能
  直接删：原子与化学键的 `DiffuseColor.a` 恒为 1，靠它才是实心的。

  **修法**：把端点改成连续过渡，并给"默认全不透明"的样式一个线性开关。
  - 新增 uniform `u_AlphaMod`（样式键 `orb_alpha_mod`，可存档、随样式切换复位）：
    `1` = 保持光照调制（原观感），`0` = alpha 直接等于滑块值。
  - 着色器：`color.a = mix(调制值, DiffuseColor.a, 1 - u_AlphaMod)`；
    端点改为 `DiffuseColor.a >= 0.999 → 1`（原子/键照旧实心），
    其余在 0.95~1.0 之间用 `smoothstep` 平滑拉向 1 —— 断崖消失，
    且 0.95 以下与改动前**逐位一致**。
  - `_MOLSTUDIO_STYLE` / `_CYLVVIEW_STYLE`（VESTA 继承 MolStudio）设
    `orb_alpha_mod: 0`：这三个样式默认就是"完全不透明"，滑块因此全程线性 ——
    0% 全实、50% 半透、100% 全透。其余半透明样式（sob-art 0.30 /
    HoukMol 0.30 / HoukMol3d 0.48 / IBOview 0.5 / IQmol 0.95）默认档位
    渲染结果不变。
  - 验证：`_opacity_sweep_probe.py` 复测三个样式，0% → 100% 亮度单调爬升
    （MolStudio 57→255、CYLview 54→255、VESTA 76→255），相邻档差值不再有
    尖峰；`_oneclick_style_probe.py`、`_cylview_style_probe.py`、
    `_style_roundtrip_probe.py`（保存/载入样式往返，含新键）全部通过。

- **大网格"装回"时的那一下顿挫（分块上传这一轮）** —— 先量清了成本构成：
  一次 35 MB 网格上传里，**真正的 GL 传输只要 0.018 s**，另外 0.156 s 全是
  `GlMesh._build_chunks`（三角形中心 + Morton 排序 + 重排索引）。而查证发现
  这个分块结构**当前没有任何渲染路径在用**（透明回退自带逐三角形深度排序），
  属于历史遗留 —— 默认关掉（保留实现与 `GLMESH_BUILD_CHUNKS` 开关）。

  顺手把 `GlMesh.upload` 改成**复用缓冲名字**（不再 destroy→glGenBuffers），
  并修掉一个隐患：上传空网格时 `n_vtx/n_idx` 现在会归零（旧代码留着上一次的
  计数）。两者都做了像素级 A/B：**与原实现逐像素一致（0/986909 像素差异）**。

  ★ 中途试过"留 25% 余量 + glBufferSubData 复用"以避免反复 realloc：
  像素 A/B 直接抓出 **3.2% 像素差异（最大 247/255）**，**已回退**。这条
  正是"改渲染要拿像素说话"的实例。

  剩余情况：2000 原子级结构切换时仍有一次性 ~0.2–0.3 s 顿挫。定位为驱动侧
  在**绘制进行中修改缓冲/VAO 状态**的同步开销（同样 8 MB 在空闲上下文里只要
  18 ms，在 paint 路径里 60–140 ms；换用复用/SubData 都不改变它）。
  要彻底消掉只能减少传输量本身 —— 即下一步的 GPU 实例化。

- **大分子/晶体"建网格那一下"界面卡住** —— 几何生成先前是在 GUI 线程同步做的，
  几千原子要 0.3–1 s，期间窗口完全没响应（帧率其实一直没问题）。现在：
  - **异步建网格**：原子数 ≥ `MESH_ASYNC_MIN_ATOMS`（默认 400，可用环境变量
    `OV_MESH_ASYNC_MIN` 调）时把 `_gen_atoms` 派发到后台线程。几何生成是纯
    numpy/Python，不碰 GL/Qt，因此安全；算完通过 `_meshBuilt` 信号回 GUI 线程
    装回网格并上传。状态用"影子对象"在派发瞬间快照（容器浅拷贝），期间用户改
    设置不会算错——新请求按代际号作废旧结果，且**合并**成最多一次补算。
    快照漏字段会抛 AttributeError → 自动回退同步重建，功能不受影响。
    小分子仍走同步路径，保持"调用完即生效"（导出、各探针都依赖）；
    `export_image()` 开头会先把后台任务 flush 掉，保证导出的是最新几何。
  - **分块拼接**：网格最后要把几千个小数组拼成几十 MB 的大数组，单次
    `np.vstack` 会在 C 里长时间持有 GIL（实测后台算的时候 GUI 出现过 450 ms
    空档）。改为 `stack_chunked()` 分块拼接、每块之间 `time.sleep(0)` 让出 GIL。

  实测（2168 原子晶体，2168 → 161 万顶点）：`set_molecule()` 阻塞
  **353 ms → 2 ms**；后台计算期间 GUI 最长空档 **0 ms**；网格与同步路径
  **逐位一致**（顶点/法线/颜色/索引全部 `array_equal`）。
  剩下一次性 0.23–0.32 s 是**显存上传**（几十 MB，GL 只能在 GUI 线程做）——
  下一步要么分块上传、要么上 GPU 实例化，才能继续压。

- **原子一多就卡（建球棍模型的网格要好几秒）** —— 排查后是两处 O(n²)/重复计算的
  Python 开销，跟 GPU 关系不大（实测每帧只有 3–7 ms，卡的是"建网格"那一下）：
  1. `_gen_atoms` 给**每个原子**都调一次 `make_sphere(r, 3)`，而它内部是
     Python 循环 + 每加一个顶点就 `np.vstack` 一次（单球几千次小 numpy 调用）。
     改为缓存一个**单位球**（`unit_sphere`），原子只做「×半径 + 平移」。
     顶点仍走 float64→float32 的同一精度路径，与原实现**逐位一致**
     （已逐个半径比对 `make_sphere(r,3)` 的顶点/法线/索引，全部相等）。
  2. 成键判定是 n(n-1)/2 次 `np.linalg.norm`：2168 原子实测调用 236 万次、
     耗时 4.7 s（占建网格约八成）。改为先按"最大可能成键距离"做**空间分箱**，
     只对候选对算距离（判据一个字没改；手工指定的键额外保留，不会被筛掉）。
  3. 顺手加了球面 LOD：投影半径 < 8 px 的原子球用 sub=2（320 三角形，
     是 sub=3 的 1/4）。可用环境变量 `OV_SPHERE_LOD_PX` 调整，设 0 = 始终用
     sub=3（与改前完全一致）。实测 274 原子晶体：三角形 377k → 269k；
     2168 原子：每帧 12.5 ms → 5.2 ms。

  实测（同样场景、同样相机）：

  | 原子数 | 建网格（改前） | 建网格（改后） |
  |---|---|---|
  | 216 | 0.80 s | 0.06 s |
  | 1000 | 4.44 s | 0.32 s |
  | 1728 | 8.97 s | 0.53 s |
  | 7290（CIF 3×3×3） | —— | 1.02 s（每帧 5.4 ms） |

- **ESP 同步到 VMD 后金属原子没有配色（一片白）** —— 根因是 ESP/IGMH 场景
  用的「命名槽」色表（0..32）把 Sc..Zn / Y..Cd / Hf..Hg 这 **30 个过渡金属
  全部映射到 `silver`(0.85,0.85,0.85)**，在 VMD 里就是一片白；而球棍模型
  单独同步走的是 101+ 的逐元素 GaussView 配色，所以那条路看着正常。

  命名槽受限于 VMD：`color scale method`（ESP/IGMH 必须用）会把色标渐变写进
  33..1056 号色，而球棍模型用的 GaussView 配色（ColorID = 原子序数+100，
  见 Multiwfn 的 `gview_color.tcl`）正好落在这一段里，两边互相覆盖。

  改法（**只动金属**，非金属槽位不变）：
  - 把命名槽里没被非金属占用的 10 个槽（ochre/lime/iceblue/purple/
    yellow2,3/blue2,3/red2,3）组成「金属专用槽池」；
  - 同步时从场景的 `xyz_text` 读出**实际出现的金属**，逐个分一个专用槽，
    并把该槽的颜色写成它在 `gview_color.tcl` 里的**精确 RGB**；
  - 实测确认 0..32 命名槽的颜色**不受 `color scale method` 影响**
    （元素→槽映射与槽色都原样保留），所以金属色不会被色标冲掉；
    切样式/切色标时也会把这段重申一次。
  - 兜底：万一读不到元素表，金属退化为「在命名槽里就近取色」，
    不会回到一片白。金属一律避开 gray/tan/cyan（碳色槽）。

  ★ 中间踩过一次坑（第一版）：手工把 Cr 指到 `blue3`(0.05,0.15,0.95)，
  而它和 VMD「元素表被色标重置后回落的那种默认蓝」几乎一样，用户看到的是
  「现在所有金属都是蓝色」，反而以为没上色。教训：**不要另发明一套颜色，
  直接对齐球棍模型/画布那套**。

  实测（真实数据 COCr-NBO + 多金属合成场景，跑完整脚本后 VMD 读回，均与
  `gview_color.tcl` 逐位一致）：Cr `(0.85,0.85,0.85)` →
  **`(0.5373,0.6000,0.7765)`**，Co→`(0.3569,0.4275,1.0)`、
  Cu→`(1.0,0.4784,0.3765)`、Fe→`(0.4980,0.4784,0.7765)`、
  Mo→`(0.3294,0.7098,0.7098)`、Au→`(1.0,0.8196,0.1373)`；
  H/C/N/O/S 等非金属配色完全不变。IGMH 路径同步修好。
- **「球棍模型本来颜色正常，一加载静电势等值面就全变蓝（深蓝），只有碳还是金色」**
  —— 根因是 **VMD 的 `color scale method X` 会重置元素配色表**。

  用户的关键观察（"元素颜色有一瞬间是正常的，加载等值面后被覆盖"）把范围锁到了
  等值面那几行。用真 cube + 真渲染逐行二分（只统计原子像素，隐藏等值面 rep）：

  | 只加这一行 | 红 | 金/橙 | 灰 | 蓝 |
  |---|---|---|---|---|
  | 基准 | 2463 | 20700 | 11420 | **8953** |
  | `mol color Volume 0` | 2476 | 20718 | 11384 | 8938 |
  | **`color scale method RWG`** | **20985** | 20617 | 3959 | **76** |
  | EdgyGlass 材质块 | 2462 | 20722 | 11441 | 8941 |
  | `mol scaleminmax` | 2466 | 20700 | 11393 | 8959 |

  **只有 `color scale method` 会破坏元素配色**（蓝色 8953 → 76）。其余三行无害
  —— 所以问题不是"着色方式被改"，而是**颜色表本身被重置**。

  **为什么偏偏碳没事**：碳用的是**命名色** `color Element C tan`，不受色标方法
  重置影响；其余元素映射到数字色号 101+，被重置后就被色标颜色接管。用户那边
  色标是 `BWR`，于是"除碳金色外其他全蓝"。

  **为什么以前那段"防发蓝"兜底一直无效**：`_scene_tcl` 末尾本来就有
  ```python
  mol top 0
  mol modcolor 0 top Element      # 只补了着色方式
  ```
  但它**没有补颜色表本身** —— 重发 `mol modcolor` 解决不了颜色表被重置的问题。

  三处修复（都是「在最后一个 `color scale method` 之后把元素配色再发一次」）：

  | 位置 | 修法 |
  |---|---|
  | `_scene_tcl` 末尾兜底 | 在 `mol modcolor` 之前补发 `ATOM_COLORS` + 碳色 |
  | `_igmh_scene_tcl` | 从模板自身提取元素配色块，插到 `color scale method BGR` 之后，并补 `mol modcolor 0 top Element`（模板里色标方法原本排在元素配色**之后**，同一个坑） |
  | `_live_style_tcl` | 体着色场景下发完 `color scale method` 后紧接着补回 `ATOM_COLORS`，否则切一次样式原子颜色就没了 |

  实时切样式路径**不强制**重发 `mol modcolor`：二分已证明着色方式不会被改坏，
  强改反而会破坏 `atom_color="Name"` 的场景。

  校验：`_vmd_colorscale_order_probe.py`（断言四条路径里最后一处元素配色
  都排在最后一个色标方法之后）；`_vmd_esp_atomonly_probe.py` 用真 cube 复现并
  验证修复（修复前完整脚本下原子蓝色像素 **0**，修复后 **3553**）。

- **可视化 ESP 时，VMD 里的球棍模型不跟样式走（是 VMD 默认的配色和材质）**。

  根因在 `fchk_orbital._scene_tcl()` 的 **`bgr` 分支**（ESP / IGMH 走这条）里，
  原子那几行是残缺的：

  ```python
  lines.append("mol modmaterial 0 top _stl_atom\n")   # ← _stl_atom 从没被定义过
  lines.append("mol modcolor 0 top Element\n")        # ← 裸的 Element = VMD 自带元素色表
  ```

  对比非 ESP 分支（`orbital`），它少了三样东西：

  1. **`mat_atom`** —— `_stl_atom` 材质块的 `material add` + 9 个属性。没有它，
     `mol modmaterial 0 top _stl_atom` 找不到该材质，VMD 回落到默认 `Opaque`
     → 这就是「材质是 VMD 默认的」。
  2. **`ATOM_COLORS`** —— 本程序的元素色表（ColorID 101–175 的 GaussView 配色）。
     没有它，`mol modcolor 0 top Element` 用的是 VMD 自带那套
     → 这就是「配色是 VMD 默认的」。
  3. **样式碳色** `color Element C {c_color}` + `color change rgb {c_color} {c_rgb}`。

  而且它把配色**写死**成 `Element`，连 `scene["atom_color"]` 都没读 ——
  ESP 面板登记的 `atom_color="Name"`（ESPViewer2 的 VMD 默认 Name 配色）也没生效。

  修复：

  - `bgr` 分支补齐上面三样，并改为读 `atom_color`（与 `orbital` 分支同构）。
  - `esp_panel._register_vmd_scene()` **不再登记 `atom_color="Name"`** ——
    按用户要求，球棍改由 VMD 控制台选的样式决定（`atom_cpk` 半径 +
    `atom_mat` 材质 + 元素色表 + 样式碳色）。`atom_color` 机制保留，
    将来哪个面板想固定 Name 配色仍可用。
  - **实时切样式也顺带换球棍半径**：`_live_style_tcl` 新增 `atom_cpk` 形参
    （原先前只在首次同步时写 CPK 半径，切样式后半径停在上一个样式上）。
    ⚠ 这个形参**只能由调用方在确认 rep 0 是 CPK 原子 rep 时才传** ——
    MPP 的 `pqr` 场景 rep 0 是 `VDW 0.25` + Charge 着色，硬设成 CPK 会改坏画面。
    故新增 `main_window._vmd_atom_rep_is_cpk()`：扫已登记场景，遇 `type=="pqr"`
    返回 False，此时传 `None` 跳过。

  校验：`_vmd_atom_style_probe.py`（26 项全过）—— ESP 场景的材质定义/9 个属性/
  元素色表/碳色/CPK 半径、换样式后数值跟着换且不残留上一个样式的值、
  `atom_color` 的 Element/Name 两种语义、面板不再登记 `atom_color`、
  `atom_cpk` 传与不传的区别、以及 `_vmd_atom_rep_is_cpk()` 对
  ESP / pqr / orbital 三种场景的判定。另有 `_vmd_scene_check.py` 把生成的
  ESP 场景 Tcl 交给**真 VMD** 执行抓报错。

- **「景深雾化」的勾选小方块不见了 —— 顺带发现「后处理抗锯齿」「线性空间光照」
  两个勾选框也一起丢了**（用户报的是景深雾化，实际是三个）。

  根因：`_promote_chk(chk)`（`ovcanvas/_panel.py`）的本意是「把复选框的文字挪到
  行首标签列、复选框本体留空」，它**只返回那个标签**：

  ```python
  def _promote_chk(self, chk):
      text = chk.text()
      self._cv_reg = [e for e in self._cv_reg if e[0] is not chk]
      chk.setText("")
      return self._param_lbl(text)      # ← 返回 QLabel，不是 chk
  ```

  所以每个调用点都必须自己把 `chk` 也放进布局。6 个调用点里 3 个补了
  （`3491` 等量值面描边、`3572` 色轮、`3714` vdW 四个开关），**后处理节的 3 个漏了**：

  ```python
  gi_p.addWidget(self._promote_chk(self._fade_chk), 10, 0)    # ← 复选框从没进布局
  gi_p.addWidget(self._promote_chk(self._post_chk), 11, 0)
  gi_p.addWidget(self._promote_chk(self._linear_chk), 12, 0)
  ```

  控件对象本身还在、`isChecked()` / `isEnabled()` 照样能读写，所以**以前的探针
  全都没抓到**——只有肉眼看得见"小方块没了"。

  修复：把复选框本体放回同一行的控件列，且不挪动任何行号 ——

  - 景深雾化：`QHBoxLayout(复选框 + 强度滑块)` 放进 `(10, 1, 1, 2)`，
    外观回到「`景深雾化:` [✓] [━━滑块━━]」，同时标签仍在标签列（竖线对齐不丢）。
  - 后处理抗锯齿：`QHBoxLayout(复选框 + 倍率下拉)` 放进 `(11, 1)`。
  - 线性空间光照：复选框直接放回 `(12, 1)`。

  回归保护：新增 `_param_orphan_probe.py`，换判据 —— **凡是交互控件就必须真的有
  父窗口、真的可见、且有非零尺寸**（全量扫描参数区，并点名这三个复选框）；
  另加一条源码级契约断言：每个 `_promote_chk(…)` 调用点之后，同名复选框变量
  必须再出现至少一次（即真的被放进了布局）。
  佐证：`_viztab_probe` 的可见控件统计里 `QCheckBox` 由 10 变 13。

- **「VMD 控制台里切到别的样式、再切回 sob-art，VMD 没反应」——两个状态变量
  分叉导致的静默跳过**（用户报的现象只在 sob-art 上出现，其他样式都正常）。
  查明是三个缺陷叠加：

  1. `_on_style_changed`（`main_window.py`）的第一道闸门
     `if style_name == self._vmd_style_applied: return` —— **根本不调用**
     `set_style`，VMD 一条命令都收不到。
  2. `VMDOrbitalSession.set_style`（`orbital_viewer_lib.py`）的第二道闸门
     `if style_name == self._current_style: return True` —— 调用方把这声
     `True` 当成切换成功并记下 `_vmd_style_applied`，但它其实**一个命令都没发**。
  3. `_refresh_vmd_scene` 刷新场景时只更新了
     `self._vmd_session._current_style`，**漏了 `self._vmd_style_applied`**
     —— 这正是两者分叉的来源。

  一旦分叉，被 `_vmd_style_applied` 记住的那个样式就再也切不回去。**sob-art 是
  默认值**（既是一键样式的默认项，也是 `_get_style_name()` 的兜底返回值），所以
  最容易卡在这个位置，表现出来就是「只有 sob-art 没反应」。

  推波助澜的第四处：`send_cmd` 在 0.5s 内收不到回话时返回空串 `""`，而调用方
  判断的是 `resp is not None and "ERROR" not in resp` —— 空串会被当成功，
  于是「其实没执行」被记成「切换成功」，进一步加深分叉。

  修复：

  - `_on_style_changed` 去掉闸门 1（组合框只在真的换了选项时才发信号，
    这道判断本来就是多余的）。
  - `set_style` 去掉闸门 2：重发同一套样式是幂等的，代价只是一次写文件 +
    一次 socket 往返，换掉这一整类静默失败值得。
  - `_refresh_vmd_scene` 补上 `self._vmd_style_applied = style_name`，
    两个状态从此保持同步。
  - `send_cmd` 若一个字节都没收到则返回 `None`（不再是空串），
    读超时同时从 0.5s 放宽到 3.0s。

  回归保护：`_vmd_style_stale_probe.py` 直接构造「陈旧状态」这一前提
  （VMD 实际是 ao-shiny、本程序记的是 sob-art），验证切回 sob-art 一定送得到
  VMD；并用源码级断言保证两处赋值今后成对出现。

### Added
- **新界面「画布优先」（`main_window_canvas_first.py`，2026-09-27）** ——
  按 Layout Demo 01 号稿（`ui_demos/layout_2026-09/01_canvas_first.html`）
  落地，**新增文件、不改动老界面**：
  - 启动：`python main_window_canvas_first.py`，或 `python main.py --ui canvas`
    （也认环境变量 `MOLSTUDIO_UI=canvas`；`main.py` 只加了这一个分支，
    classic / clean / clean2 的行为一字未动）。
  - 左侧功能导航 122px 竖排文字 → **58px 图标 rail**：复用 Clean 皮肤的矢量
    图标（`ui_icons`），条目纯图标、悬停出全名；底部「☰」一键展开回
    「图标 + 文字」（122px）。补齐了 clean 皮肤没配到的两个 tab 图标
    （晶体 = cube、DI = sigma，只在本地图里生效）。
  - 右侧「设置 / 引文」抽屉**可整体收起**：Tab 栏右上角「▤」或 **Ctrl+B**，
    收起后画布吃满全宽（实测 611px → 1246px）；画布卡片里另有一个
    「▤ 设置面板」常驻入口负责展开。
  - 一键样式 8 个按钮 → **一个下拉菜单**（原按钮只隐藏、功能与状态完全复用，
    选完按钮文字显示当前样式名）。
  - 实现方式：继承 `MolStudioCleanWindow`，只覆写
    `_setup_ui / _apply_clean_skin / _setup_main_nav / _sync_main_nav` 四个钩子；
    所有布局改造都就地 try/except —— 失败最多是"回到底层界面"，不影响功能。
    注意 Clean 皮肤是 `QTimer.singleShot(60)` 延后套用的（会把导航卡钉成
    150px），所以本界面在皮肤套完之后再补一次布局。
  - 验证：探针 `_canvas_first_probe.py`（导航 58/122 切换、17 个条目都有图标、
    下拉 8 项且选中 VESTA 后配色真的变青/黄、抽屉收起画布 611→1246 再展开复原、
    Ctrl+B 已挂、三个老界面类仍可导入、main.py 已接入 canvas）全部通过；
    截图脚本 `_canvas_first_shot.py` 出三张实拍图（抽屉展开 / 收起 / 导航展开）。

- **右侧设置区新增「引文」页签 —— 按功能列出该引用的文献**。
  过去致谢是「一锅端」：Multiwfn / IboView / vcube / IGMH / VMD / Tachyon 全
  堆在路径设置与「关于」里，用户要发论文时得自己判断某个功能该引哪几篇。
  现在右侧设置区做成「设置 / 引文」两个页签，引文页签跟随左侧功能导航：
  - 数据表 `tab_references.py` 记录「tab → 文献」对照，共 27 条文献、17 个
    模块，编号与 `docs/chemrxiv_draft.md` 的参考文献表一致；每条还写明它在
    该模块里**具体用在哪一步**（如 IGMH 页 = Multiwfn 引擎 + IGMH 原文
    [7] + 可选的 IRI [16] + Multiwfn IGMH/IRI 教程 [8] + 前身 IGMH_Toolbox
    [15]），来源是 `docs/tabs_references.html`。
  - ESP 页补 3 条（编号 25–27，预印本长稿的参考文献表尚未收录）：**表面静电势
    分区面积统计**（本模块「📊 分区面积图」的画法）按 Multiwfn 官方教程
    （sobereva.com/196）的要求，除 Multiwfn 原文外还须引用首次提出并使用该图的
    两篇——Manzetti & Lu, *J. Phys. Org. Chem.* **2013**, *26*, 473–483
    (doi:10.1002/poc.3111) 与 Lu & Manzetti, *Struct. Chem.* **2014**, *25*,
    1521–1533 (doi:10.1007/s11224-014-0430-6)；另附该教程本身作为操作出处。
    文献题录经 Crossref 按卷/页核对（`api.crossref.org`）。
  - 界面：`CitationPanel` 显示当前功能的完整引用清单——标题写明功能名与篇数，
    正文按类别标签（方法/引擎/渲染/风格/本组）逐条给出 ACS 格式引用与用途，
    「复制全部引用」一键复制成可直接粘进稿件的纯文本。页签跟随左侧导航切换，
    停在引文页签时换功能也会就地更新。
  - 顺带修正一处引用事实：致谢里 IGMH 页码 539–553 → **539–555**（与
    2026-09-18 参考文献审计结论一致）。
  - 打包：`OrbitalViewer.spec` 的 hiddenimports 补 `tab_references`。
  - 探针 `_cite_tab_probe.py`：逐一切换 17 个功能校验引文页签内容、IGMH 的
    六条文献、复制粘贴、窄窗口、中英文切换，经典界面与 Clean/Bridge 皮肤各跑
    一遍。

- **一键样式新增「VESTA」** —— 基底用「MolStudio」那套（同一套几何/光照/材质），
  只换配色。配色**取自 VESTA 自己的资源文件**，不是凭印象配的：
  - **数据来源**：`<VESTA 安装目录>\elements.ini`（VESTA 自带元素表，7 列 =
    元素符号 / 共价半径 / 范德华半径 / 离子半径 / R G B）。本机两份 VESTA 安装
    里这个文件 **SHA256 完全一致**（2010-07-29），转成 `vesta_colors.py`
    （95 个元素，含 `self_check()` 与 ini 逐行比对，改过数据立刻报错），
    生成脚本 `_gen_vesta_table.py` 可随时刷新。
  - **原子**：新增原子配色轴 `VESTA`（与 Jmol / GaussView 同级，画布下方
    「原子配色」下拉的最后一项），**另外**还写了一份 95 条元素覆盖色 ——
    因为「同步到VMD」那条链路只认元素覆盖表、不认配色轴，不写这份会出现
    "画布是 VESTA 配色、VMD 里还是 GaussView 配色"。
  - **化学键**：**不设统一键色**，即两端原子各占一半 —— VESTA 手册里这叫
    "Bicolor cylinder"，默认画法就是它，与 MolStudio 相同。
    ★ 这条一开始判断错了：`style.ini` 的 `BONDP` 行末有三个 127，我当成
    "VESTA 的键是统一灰"；实际那是 "Unicolor cylinder / Color line" 那几种
    画法用的颜色，默认画法用不到。用户指出后按实际画法改正，并在
    `_vesta_style_check.py` 里加了"两端分色"的像素级断言：Fe–O 键靠 Fe 的
    半段实测 `(208,132,3)`、靠 O 的半段 `(255,7,3)`，两半相差 172。
  - 顺带把「统一键色 / 键光泽 / 键亮度」补进样式状态
    （原先漏存：设过统一键色后，保存样式再载入会丢；现在 `get_style_state()`
    会带上，实测设 `(0.2,0.3,0.4)` 能原样存取）。
  - **光照/材质**：采用作者在成品里调好、导出的那份 VESTA 样式状态。
    相对 MolStudio 基底实际只动了 7 处：
    灯 0 光晕 `0.79 → 3.0`、镜面模型 `1 → 2`（Clear-coat 清漆）、
    粗糙度 `0.45 → 0.55`、清漆 `0.10/0.80 → 0.15/1.78`、
    键收腰 `0.70 → 1.00`（直圆柱不收腰，与 VESTA 的 stick 一致），
    以及等值面那组着色寄存器。导出文件里其余多出来的键都是"完整状态"自带的
    默认值，没有并进来 —— 保持与其它一键样式同一套写法，也免得把用户的
    vdW / 元素半径设置一并清掉。
    ★ 有一处**没有**照搬：导出里景深雾化是**开着**的（`fade=true`），但本项目
    有条明文规则「一键样式一律不打开景深雾化」（`reset_molviewer_style()` 注释 +
    `_oneclick_style_probe.py` 强制检查），故按规则压回关闭；要恢复，
    把 `_VESTA_STYLE["fade"]` 改 `True` 并松掉那条判定即可。
  - 另记一笔参数观察：这版材质（清漆 1.78 + `spec_model=2`）下，键圆柱的
    **中心线会被高光打成纯白**（实测中线 `(255,255,255)`、上下 3px 才是本色
    `(225,152,30)`）。逐个参数试过：把 `spec_model` 改回 1 或把清漆降到 0.8
    就没有这条白线。是否保留由用户定，这里如实记下。
  - **不残留**：7 个一键样式字典统一改成 `{**_STYLE_NEUTRAL, ...}` 展开，
    显式声明"本样式不指定元素配色 / 统一键色"。`apply_style_state()` 对缺失键
    的语义是"保持当前值"，而元素配色是**字典**，不显式写空就会黏住 ——
    实测"先点 VESTA 再点 MolStudio"，原子会继续用 VESTA 配色，看着像按钮失灵。
  - 验证：`_vesta_style_check.py` 27 项全过（Fe 实测球面像素 VESTA =
    `(190,120,1)` 橙棕 vs MolStudio = `(134,128,208)` 蓝灰；O = `(255,4,0)` 红；
    S = `(255,255,0)` 黄；样式状态往返、切换不残留）。
    `_oneclick_style_probe.py` 已把 VESTA 纳入，与其余 7 套一键样式一起跑。
- **主程序新增「晶体」tab（CIF / POSCAR 晶体可视化）** —— 把 `crystal_demo.py`
  里的晶体功能并进主程序，共用主程序左侧那块 OpenGL 画布（同一套引擎与
  一键样式），面板为 `crystal_panel.py`：
  - **载入**：CIF（自动展开 `_space_group_symop_operation_xyz` /
    `_symmetry_equiv_pos_as_xyz` 对称操作、去重、多 `data_` 块取第一个完整结构、
    兼容 `18.5498(14)` 这类带不确定度的数值、分数或笛卡尔坐标）；VASP
    POSCAR / CONTCAR / .vasp（VASP5 元素行、Direct/Cartesian、Selective
    dynamics、负 scale 按体积；VASP4 缺元素行会明确提示）；**Tripos MOL2**
    （`@<TRIPOS>ATOM` 块；元素按 type 段判定 `C.3`→C、`Cl`→Cl、`N.pl3`→N，
    认不出再用 name 段；MOL2 是分子、没有晶胞 → 扩晶胞 / 边界补齐 / 晶胞框
    三组控件自动灰掉，信息条改显示笛卡尔坐标原子表）。CIF 里坐标为 `?`/`.`
    （未定值）的位点会**跳过**，不再当成原点上的原子。
  - **扩晶胞**：a/b/c 三个方向分别 1–6 倍（2×2×1 做板层、1×1×3 沿 c 拉长）+
    一键复位；换新结构自动回到 1×1×1；>8000 原子拒绝并回退倍数。
  - **边界原子补齐**（默认开）：晶胞顶点/棱/面上的原子在所有等价位置都画出来
    （bcc 铁 = 8 顶点 + 体心），按坐标去重避免重叠球。
  - **晶胞框**：QPainter 叠加画原胞 12 条棱；只在晶体 tab 可见时画，离开该
    tab、或画布上已换成别的结构（原子数不符）时自动不画，避免框错分子。
  - 代码结构：解析/晶胞/晶胞框等纯逻辑抽到 `crystal_lib.py`（面板与独立 demo
    共用），`crystal_demo.py` 仍可单独运行。
- **画布下方新增晶体信息条**（`CrystalInfoBar`）：
  - **导出图片**（下拉：PNG / JPG / TIFF / SVG）直接复用画布自己的
    `_export_image()`，所以 600 DPI、透明背景、以及**晶胞框**全都跟着进图
    （实测开/关晶胞框的导出图相差 743 个像素）；
  - **晶胞参数行**：a/b/c、α/β/γ、V；
  - **原子表**（可展开/收起）：原胞内每个原子的序号、元素、分数坐标（行
    tooltip 里给笛卡尔坐标）。

  ★ 排查过程中踩到一个真 bug 并顺手加固：`crystal_lib` 抽库时漏了
  `BOHR_TO_ANGSTROM` 的导入，导致晶胞框绘制抛 NameError —— 而这发生在
  QOpenGLWidget 的 paintGL 回调链上，**PyQt 会直接 abort 整个进程**
  （现象：切到晶体页后一帧内程序消失、没有任何 traceback）。
  现在叠加层整段包了 try/except：画不出来最多是"没框 + 提示一次"，
  不会再把主程序带走。

- **静电势表面上「五彩斑斓的点」修好了 —— 元素配色表与色标渐变抢同一批色号**。
  用户报：切换色标后，VMD 里静电势为负的区域表面出现五彩斑斓的点；
  刚同步过去时没有，一切色标就有。

  **实测出的机制**（`colorinfo rgb` 逐槽对比）：

  ```
  baseline:            33=(1.00,0.10,0.10) … 512=白 … 1000=(0.21,0.21,1.00)
  after BWR:           33=(0.10,0.10,1.00) … 512=白 … 1000=(1.00,0.21,0.21)
  after RWG:           33=(1.00,0.10,0.10) … 512=白 … 1000=(0.21,1.00,0.21)
  after ATOM_COLORS:   101=(0.80,0.80,0.80)  150=(0.90,0.00,0.00)   ← 在渐变上打洞
  ```

  **`color scale method X` 把色标渐变写进 33..1056 这些色号**，而本程序的
  `ATOM_COLORS` 正把元素色写进 **101–211** —— 两者完全重叠，谁后写谁赢：

  - 色标后写 → 元素色被冲掉（原子/键回落默认色）← 上一轮修的那个
  - 元素色后写 → **色标被打出洞，表面出现五彩斑斓的点** ← 这一轮这个

  即：**101+ 的元素表和色标渐变在原理上就不可能共存。**

  **修法**：给「会用到色标的场景」（ESP / IGMH）换一张**只用 VMD 命名色槽
  0–32** 的元素色表 `ATOM_COLORS_NAMED`。实测 0–32 **完全不受
  `color scale method` 影响**（设 BWR / RWG 前后逐槽比对一致）。

  | 位置 | 用哪张表 |
  |---|---|
  | `_scene_tcl` 的 `bgr` 分支（ESP/IGMH） | `ATOM_COLORS_NAMED` |
  | `_scene_tcl` 末尾兜底 | 按场景选：`bgr` → 命名槽表；纯轨道 → 原 101+ 表 |
  | `_live_style_tcl`（切样式） | `ATOM_COLORS_NAMED` |
  | `_vmd_cmap_script_lines`（切色标） | `ATOM_COLORS_NAMED` |
  | `_igmh_scene_tcl` | 剔掉模板里 101+ 的金属行，补命名槽表 |
  | 纯轨道场景 | 仍用 101+ 完整周期表（没有色标，不冲突，配色更精细） |

  `ATOM_COLORS_NAMED` 的取舍：常见主族/有机元素逐个指定（H/N/O/F/S/P/Cl/Br/I 等
  + 样式碳色），金属按区块归到代表性颜色（3d/4d/5d→银灰、p 区重元素→紫灰、
  镧锕系→赭黄），并**避开 8（白）与 16（黑）** —— 8 被
  `color Display Background white` 用着，改了背景就不是纯白。

  端到端验证（真 cube、真渲染、隐藏原子只看等值面）：

  | 做法 | 色相数 | 斑点度 |
  |---|---|---|
  | A 基准 | 7 | 2.03 |
  | B 只发色标方法 | 8 | 2.03 |
  | **C 旧 101+ 元素表** | **37** | **2.16** ← 五彩斑斓 |
  | **D 新命名槽元素表** | **7** | **2.04** ✓ 与基准一致 |

  校验：`_vmd_cmap_surface_speckle_probe.py`（隔离出是哪一步造成斑点）；
  相关探针同步加了「体着色路径不得出现 101+ 旧表」的断言。

  另记一个**同类隐患（未改，暂不影响）**：`MULTI_ORBIT_COLORS` 用的是
  33/34/35/36 号色，也在色标渐变区间内 —— 多轨道 + 体着色同时出现时会互相
  干扰。目前两者不会同时启用，故留待需要时再处理。

- **在 VMD 控制台切换色标时，原子与化学键的配色不再被改掉（二次上色）**。
  用户报：「切换色标，化学键的颜色还是会发生变化」。

  根因：上一轮补的元素色表只加在**切样式**那条路径（`_live_style_tcl`）上，
  而**切色标**走的是另一条 —— `_on_vmd_cmap_changed` 原先只发一条
  `color scale method X`。实测那条命令会重置元素配色表，于是原子和键的颜色
  一起跟着变。

  端到端验证（真 cube、真渲染、隐藏等值面只看球棍）：

  | 做法 | 色相数 | 与基准的平均像素差 |
  |---|---|---|
  | A 基准（不切色标） | 15 | — |
  | **B 只发 `color scale method`（旧）** | **26** | **1.481 / 255**（红色 1685 → 5428） |
  | **C 完整二次上色脚本（新）** | **14** | **0.265 / 255** |

  改动：

  - 新增 `main_window._vmd_cmap_script_lines()`（抽出来是为了可测）：一次生成
    `color scale method <选中的>` + `ATOM_COLORS` + 样式碳色 +
    `foreach _m [molinfo list] {catch {mol modcolor 0 $_m Element}}`；
    体着色场景再补 `mol modcolor 1 top Volume 0` 与紧跟的 `mol scaleminmax`
    （单发 modcolor 会重置量程，必须成对 —— 见上一轮实测）。
  - `_on_vmd_cmap_changed()` 把这段写成 `_vmd_cmap.tcl` 再 `source`
    （`ATOM_COLORS` 是多行，而 socket 一次只执行一行；与 `set_style` 发
    `_live_style.tcl` 同一套做法）。拿不到 `render_dir` 时退回逐条发，
    跳过无法单行发送的色表，并在日志里说明。

  校验：`_vmd_cmap_recolor_probe.py`（17 项全过：脚本内容、走文件下发、
  文件确实写出、VMD 未运行时不发命令）；`_vmd_cmap_recolor_vmd_probe.py`
  真 VMD 端到端比对像素差。

- **切样式时静电势表面的着色不再丢失**（用户需求：ESP 可视化时选不同原子风格，
  原子配色会变，但静电势表面的着色要保持）。

  实测定位（真 cube + 真渲染，隐藏原子只看等值面，统计色相数）：

  | 场景 | 色相数 | 结果 |
  |---|---|---|
  | A 基准（未切样式） | 25 | ESP 渐变正常 |
  | B `vol_color=True` + ao-shiny | 28 | 保持 ✓ |
  | **C `vol_color=False` + ao-shiny** | **4** | **拍平成单色** ← 故障 |
  | D C 之后再补 Volume 着色 | 28 | 恢复 ✓ |

  **两个根因：**

  1. **`_vmd_vol_color()` 判据错了**（`main_window.py`）。它读的是画布的
     `_surf_vcolor` —— 一个易变的 UI 状态位，切样式 / 重算表面 / 清表面都会
     把它置回 False。改读**已登记的 VMD 场景**（`glw.vmd_scene()`）：出现
     `type == "bgr"` 的表面才算体着色（`pqr` 是 Charge、`orbital` 是相位色，
     都不算）。状态位只作兜底。
  2. **`_live_style_tcl` 的体着色段以「样式带 volume_color」为条件**
     （`if vol_color and vc`，只有 sob-esp0/1 有 `vc`），于是切到任何普通样式
     时那几行全都不发。现在只要场景是体着色就无条件重申。

  **踩到的两个反直觉细节（都靠实测确认，不能想当然）：**

  - `color scale method <m>` 单发**无害**（色相数 25 → 25），但
    **`mol modcolor <rep> top Volume <n>` 单发有害** —— 它会把该 rep 的
    `scaleminmax` 重置成体积数据的全量程，表面着色被冲淡（25 → 2）。
    **必须紧跟一条 `mol scaleminmax`** 把量程设回去（实测 25 → 25）。
    所以新增 `vol_range` 形参：知道量程（从场景登记的 `cmin/cmax` 取）才重申
    `modcolor`，不知道就只发色标方法 —— 那样反而更安全。
  - ESP 场景只有 rep 0/1，而 `_live_style_tcl` 会发
    `mol modmaterial 2 top _stl_b` 等按 rep 的命令；**对不存在的 rep 发命令会让
    整个 proc 报错中断**，后面的碳色、元素色表、display distance 全都执行不到。
    现已全部用 `if {[molinfo top get numreps] > r}` 包起来。

  另外新增 `main_window._vmd_vol_range()`：从登记场景里取体着色表面的
  `cmin/cmax`，透传给 `set_style(..., vol_range=)`。

  校验：`_vmd_esp_surface_style_probe.py`（38 项全过，含 modcolor/scaleminmax
  必须成对且顺序正确、无 vol_range 时不发 modcolor、无裸的按 rep 命令、
  轨道场景不受影响、`_vmd_vol_color()` 对 bgr/orbital/pqr 三种场景的判定）；
  `_vmd_esp_surface_keep_probe.py` 用真 cube 端到端验证
  （B 28 / E 26 色相，均保持渐变）。

- **ESP 配色与 VMD 配色彻底解耦（按用户要求）**：
  **ESP tab 的「配色」只管 OpenGL 画布；VMD 的色标改在 VMD 控制台里单独设，
  两者互不相关。**

  之前的行为：ESP 面板的「配色」经 `esp_panel._vmd_cmap_name()` 折成 VMD 的
  色标方法，一路带进 VMD 场景 —— 所以改画布配色会连带改 VMD。

  现在：

  | 位置 | 归属 |
  |---|---|
  | ESP 面板「配色」+「反转」 | **只**作用于 OpenGL 画布（`_apply_surface` / 色彩刻度轴），不再写进 VMD 场景 |
  | VMD 控制台新增「VMD 色标:」下拉 | **唯一**的 VMD 体积着色色标来源（那 6 个方法，默认 `BWR`） |

  实现要点：

  - `esp_panel._register_vmd_scene()`：只登记 `kind="esp"`，**不再写 `cmap`**。
    （用已有的 `kind` 约定，IGMH 早就在用 `kind="igmh"`。）
  - `main_window` 收集场景时，把控制台选的色标注入到 `kind=="esp"` 的表面上；
    **IGMH 仍保持自己的 `BGR` 约定**，不受影响。
  - VMD 正在运行时改「VMD 色标」**即时生效**（立刻发 `color scale method X`），
    不需要重新同步；各 rep 的数值范围（`mol scaleminmax`）不变。
  - 实时切样式也把控制台的色标透传给 `_live_style_tcl(cmap=…)`，否则每切一次
    样式就会被样式自带的 `volume_color.cmap`（=BWR）冲回去。
  - `VMD_CMAP_METHODS = ("RGB","BGR","RWB","BWR","RWG","BWG")` 收敛成**单一来源**
    （`fchk_orbital.py`），两处白名单与控制台下拉都引用它，不再各写一份。

  **顺带修掉一个我上一轮埋下的隐患**：`_live_style_tcl` 原先用
  「样式有没有 `volume_color`」来决定「要不要发 `mol modcolor … ColorID`」。
  这两个概念本该分开 —— 只要**场景**是体积着色（`vol_color=True`），**任何**样式
  都不能发 ColorID，否则会把 Volume 着色改成固定色、等于把静电势表面拍平。
  按旧逻辑，「ESP 场景里切到 `sob-art`（无 `volume_color`）」就会中招。现已改为
  按 `vol_color` 判定；`vc` 只负责决定要不要补发色标方法 + 数值范围。

  校验：`_vmd_cmap_decouple_probe.py`（24 项全过）—— 面板配色变化不影响 VMD
  场景登记、控制台默认/取值、注入只命中 `kind=="esp"`、IGMH 不被覆盖、
  运行时即时生效、以及上面那条 `vol_color`/`vc` 分离的各种组合。

- **ESP 色标补齐 VMD 原生支持的 RWG / BWG（原来只有 4 种能传到 VMD）**。

  实测（VMD 1.9.3 逐个试 `color scale method`）VMD **只认 6 个色标方法**：

  | 方法 | 观感 | 程序原先 |
  |---|---|---|
  | `BWR` | 蓝→白→红 | 放行 |
  | `RWB` | 红→白→蓝 | 放行 |
  | `RGB` | 红→绿→蓝（彩虹） | 放行 |
  | `BGR` | 蓝→绿→红 | 放行 |
  | `RWG` | 红→白→绿 | **被强制改成 BWR** |
  | `BWG` | 蓝→白→绿 | **被强制改成 BWR** |

  被 VMD 拒绝的（实测报 `not recognized`）：`RG`、`GB`、`Gray`、`WG`、`RGW`、
  `BGRW`、`BWRG`，以及 `jet`/`coolwarm`/`viridis`/`RdBu`/`spectral` 等 matplotlib
  名字。所以**画布上的十几种配色最终只能落到这 6 个枚举上**，画布与 VMD 的
  ESP 配色不可能完全一致。

  改动（三处白名单 + 一处解析）：

  - `fchk_orbital._scene_tcl`、`_live_style_tcl`：白名单由 4 个扩到 6 个。
  - `esp_panel._vmd_cmap_name`：新增 `RWG`/`BWG` 直通；这两种在 VMD 里没有
    反向对应项，所以忽略「反转」勾选（BWR↔RWB 仍照旧互换）。
  - `esp_viewer.ESP_CMAPS`：新增 `RWG (红-白-绿)` / `BWG (蓝-白-绿)` 两项
    （共 16 种），ESP 面板下拉直接可选；matplotlib 里没有这两个同名色标，
    故在 `_CUSTOM_CMAP_COLORS` 里用 `LinearSegmentedColormap.from_list`
    现搭（不走 `colormaps.register`，那个接口要 matplotlib ≥3.5）。
  - `ovcanvas/_glwidget._resolve_cmap`：原先自己 `cm.get_cmap()` 解析，会漏掉
    自造色标（表现为色彩刻度轴拿不到配色），改为统一委托 `esp_viewer._mpl_cmap`。

  校验：`_cmap_passthrough_probe.py`（40 项全过）—— 自造色标的端点/中点颜色、
  面板名→VMD 方法映射（含 invert 语义）、两处白名单 6 种全放行且非法值回退
  `BWR`、画布色彩刻度轴与 ESP 面板下拉都能吃到新配色。

- **新增两个 vcube ESP 样式：`sob-esp0` / `sob-esp1`（一键样式下拉里可选）**。
  起因是核对「vcube 那 13 套样式本程序是不是都支持」，结论原本是 11/13 —— 缺的
  正是这两个 `.mstl`。现在补齐，名册覆盖 **13/13**。
  - 源文件是 `.mstl`（maps style），与前 11 个 `.stl` 的区别在于等值面**不是相位
    配色**，而是 `mol modcolor 1 top Volume 1` + `color scale method $color_scale`
    按体积数据（ESP cube）做红-白-蓝体着色。
  - 逐字搬了源文件的材质/灯光/CPK/碳色（`surface_mat` 9 值、`atom_mat` 9 值、
    `atom_cpk`、`c_color`/`c_rgb`、4 个灯全开、shadows/AO 关）。
  - **新增 `volume_color` 键，让这两个样式真正驱动「按静电势连续着色」**
    （按用户反馈修正：它们本来就是 ESP 配色，不是相位配色）：
    `"volume_color": {"cmap": "BWR", "cmin": -0.03, "cmax": 0.03}`
    （取 vcube 的 `color_scale` 默认值 `BWR` + `map_scale_value` 默认值
    `{-0.03 0.03}`）。三处消费者：
    | 位置 | 行为 |
    |---|---|
    | `_glwidget.set_style` | 当前有 ESP 顶点色表面（`_surf_vcolor`）时，把色彩刻度轴设成 BWR / ±0.03 a.u.；**没有 ESP 表面时一律不动色标**，不覆盖用户自己调好的 |
    | `fchk_orbital._live_style_tcl` | 新增 `vol_color` 参数。为 True 时**不发 `mol modcolor … ColorID`**（发了会把 Volume 着色冲掉、等于把静电势表面拍平成一整块颜色），改发 `color scale method BWR` + `mol scaleminmax top {rep} -0.03 0.03` |
    | `_scene_tcl` / ESP 面板 | 体着色本身照旧由 ESP 面板的 `bgr` 路径负责（`mol modcolor … Volume`），本键只补充色标与范围 |
  - `vol_color` 由主窗口 `_vmd_vol_color()` 从画布取（读 `glw._surf_vcolor`），
    经 `_on_style_changed` → `VMDOrbitalSession.set_style(..., vol_color=)` 透传。
  - `pos_color` / `neg_color` 仍保留，作为「手上没有 ESP 体积数据」时的兜底相位色。
  - 校验：`_esp_volume_style_probe.py`（26 项全过）—— 只有这两个样式带
    `volume_color`；体着色下发不发 ColorID / 发不发色标；普通样式即使
    `vol_color=True` 也不受影响；画布色标在有/无 ESP 表面两种情形下的行为；
    以及 ESP 顶点色不会被相位单色拍平。
  - `tachyon_options` 取 `-trans_vmd -shadow_filter_off`：源文件只写了
    `-shadow_filter_off`，但 `-trans_vmd` 是本程序「透明背景」的样式级默认值
    （62 套里 61 套都带，vcube 原件不一定有），为保持一致补上。用户导出时自己选的
    `-trans_*` 会覆盖它（`_render_with_tachyon` 里用户值后追加）。
  - `sob-esp0`：`surface_mat` = `0.0 0.66 0.5 0.75 0.0 0.62 0.4 0.94 1.0`，碳色 cyan。
    `sob-esp1`：`surface_mat` = `0.15 0.7 0.0 1.0 0.0 0.6 0.4 0.89 1.0`，碳色 gray(0.6)。
    两者 `atom_mat` 都是 `0.0 0.65 0.5 0.53 0.0 0.99 0.0 0.0 0.0`。
  - 校验：`_vcube_esp_style_probe.py`（45 项全过）—— 重新解析两个 `.mstl` 逐字段
    比对、15 个必需键完整性、`STYLE_NAMES`/`STYLE_DISPLAY` 接线、真跑
    `_gen_multi_orbital_tcl` 与 GL `set_style`、以及「点下拉真的切过去」。

- **（核对结论）vcube 13 套样式的覆盖情况**：`_style_coverage_audit.py` 给出
  **13/13 名册齐全**；`_style_equivalence_audit.py` 逐字段对照后 **真差异 0 处**：

  | 结论 | 套数 | 说明 |
  |---|---|---|
  | 数值完全一致 | 4 | sob-art、white-red、sob-esp0、sob-esp1 |
  | 源文件笔误 | 4 | morandi-blue/orange/red、vmwfn0 —— vcube 自己把 CPK 半径写成 `0.3.50000`（非法数字），`ao-shiny` 还写成 `0.3500000`；本程序的 `0.35` 才是原意 |
  | 仅 VMD transmode | 5 | ao-shiny、ao-chalky、white-green、morandi-green、vmwfn1 —— 等值面材质 `transmode` 本程序统一 `1.0`(Glass1)、源文件 `0`(Normal) |

  - transmode 这条**不影响本程序画面**：自带渲染器走 `style_params()`，只读
    `surface_mat[:6]`，第 8 位（transmode）根本不参与。差别只在送进 VMD 的 Tcl
    （`_gen_multi_orbital_tcl` / `_live_style_tcl` / `nocv_analyzer`）。其中
    morandi-green / vmwfn1 不透明度 = 1.0，Glass1 与 Normal 无差别；真正看得出的是
    ao-shiny(0.7) / ao-chalky(0.8) / white-green(0.7)。**用户本次未选择修此项**。
  - 另记：`ovcanvas/_molviewer_style.py` 里那套 `vcube-*` 预设（含
    `vcube-sob-esp0/1`）**全仓库无调用点** —— `apply_molviewer_preset()` 只被定义过、
    `MOLVIEWER_NAMES` 从未进过任何下拉框，整个 MolViewer 预设注册表（31 套）是死代码。
    本次新增的样式没有复用它，走的是 `STYLES`。

- **画布下方一键样式卡片：「出图观感」并入「分子显示」那一行**（按需求，先是从
  第一行挪到第三行，随后与第二行合并）。卡片现在的行序是：
  **一键样式 → 分子显示 + 出图观感 → 导出/标注**。
  改动只在装配处：`出图观感` 的标签与下拉框不再自成一行，改为
  `h2.addWidget(_hgroup(lbl_look, self._look_cb))` 并进 `h2`。
  - 必须用 `_hgroup()` 把标签和下拉框打包成一个整体 —— 不打包时换行正好落在
    两者之间（实测「出图观感:」留在第二行末尾、下拉框被甩到第三行独自一行）。
  - 1400×820 下卡片 371px、画布区 296px（合并前 369 / 298，差 2px：少了一处行间距、
    多了一处换行）。
  - 一键样式卡片仍是 FlowLayout，所以合并后这行在窄面板下自动排成 3 行
    （419 / 304 / 282px），不会压窄任何控件。

- **（调查记录，未改动）启动时的"小窗口" = 品牌启动画面，不是 bug**。
  用 `main.py` 自带的窗口枚举侦查（枚举本进程所有可见顶层窗口 → `~/molstudio_dbg.log`）
  跑了一次完整启动，整个过程中只有 **3 个**顶层窗口：

  | 时刻 | 尺寸 | 类名 | 说明 |
  |---|---|---|---|
  | +0.00s | 560×380 | `Qt5152QWindowToolSaveBits` | 启动画面（`_FadeSplash`） |
  | +1.15s | 1×1 | `Qt5152QWindowOwnDCIcon` | Qt 内部图标 DC 窗口，肉眼不可见 |
  | +1.35s | 1422×876 | `Qt5152QWindowIcon` | 主窗口 |

  8 秒轮询（每 150ms）也没抓到任何一闪而过的其他窗口。所以用户看到的
  "小窗口"就是启动画面；主窗口在 +1.35s 就已在它**背后**显示好，启动画面淡出后
  才露出来，读起来就是"小窗口出现 → 消失 → 主界面出现"。

  **关键在于启动画面被写死停留 5 秒**：`_splash_tick` 里进度条走 `el/4600`，
  到 `el >= 5000` 才 `fade_out`。本机 1.35s 就加载完了，剩下 ~3.6s 是纯干等。
  若以后要去掉或改短，动的是 `main.py` 这几个点：`splash = _FadeSplash(...)` /
  `splash.show()` / `_prog_timer` 的 5000ms 阈值 / `splash.fade_out(...)`。
  （本次按用户要求**保持现状**，待其打包后自行观察再定。）

- **（已撤回）出图观感曾新增 4 套**（暗底霓虹 / 经典 Houk 球 / 平面墨线 /
  粘土素模）。参数覆盖面确实存在空档（原 6 套共用同一基座：`gradient` 全是
  `""`、纯白底、暗角与边缘暗化全 0、灯数恒为 3），候选也做过两场景像素标定，
  但**用户实际看过之后认为这 4 套不行，已全部撤回**，`_looks.py` 恢复成原来的
  6 套（`LOOK_ORDER` 与下拉条目同步还原）。
  保留两个研究脚本备查：`_look_candidate_probe.py`（候选筛选：内存注入候选
  → 两场景两两色差矩阵）、`_look_edgecheck_probe.py`（查清"边缘暗化"只在
  主体内部生效——背景被改动像素 0，且 radius 需取 5 才看得出）。


- **「样式 保存 / 载入」补齐覆盖面**（原功能早就有，但只存了 44 个键，
  参数区里一大半设置保存后再载入对不上）。

  用 `_style_roundtrip_probe.py` 做逐控件往返审计（把每个控件推到可辨识的值 →
  存成 JSON 文件 → 全部搅乱 → 读回并应用 → 逐控件比对），实测改动前
  **79 个可调控件里有 30 个没能往返**。逐项补齐：

  - **渲染样式**（原先完全没存的）：等值面配色 `style_name`、透明合成
    `transparency_mode`、WBOIT 衰减 `oit_falloff`、剥离层数 `peel_layers`、
    键收腰 `bond_thinning`、虚线大小/间隔 `dot_size`/`dot_spacing`、
    选中标记 `sel_marker`、呼吸 `sel_pulse`、vdW 六项
    `vdw`（范德华半径/外壳/外壳透明度/半径比例/外壳描边/描边粗细）。
  - **对话框里的值**（快照测不到，查代码发现的）：元素颜色逐元素覆盖
    `element_colors`、元素半径逐元素倍率 `element_radii`、十字圆环
    `ring`（方位角/俯仰角/宽度/颜色/锁定）。注意 JSON 的对象键只能是字符串，
    读写时对原子序数做了 `int` ↔ `str` 转换。
  - **面板侧状态**（新增 `_panel_style_state()` / `_apply_panel_style_state()`）：
    正/负相位**颜色**本来就存了，但决定颜色的那几个控件（相位配色方案、
    翻转相位、启用色轮、色轮角度）在面板上，不一起存就会"画面对了、控件显示旧状态"，
    用户再碰一下就跳回去。回填时全部 `blockSignals` —— 载入的颜色已由
    `apply_style_state` 装好，不能让"按色轮重算颜色"再跑一遍把它算没。
  - **`_sync_style_ui()` 补齐回填**：等值面配色 / 键收腰 / 虚线大小·间隔 /
    选中标记 / 呼吸 / vdW 六项 这些控件原先不同步，画布状态换了界面还停在旧值。
  - **顺序坑**：`set_style()` 会整体重建 `_sp`（`style_params`），所以等值面配色的
    恢复必须放在**材质块之前**，否则文件里显式存的粗糙度/清漆/次表面会被样式预设覆盖。
    实测把它放最后会导致这几项载入后不对。

  **按设计不进样式文件**（已确认，与"逐键多重键指定属场景内容"同一条标准）：
  等值面阈值（跟 cube 数据单位绑定）、网格精度（生成 cube 的参数）、
  导出图片的透明背景（导出选项）、键长标注（交互模式）、
  vdW「仅选中片段」+ 片段编号（场景内容）。

  **验收**（`_style_roundtrip_probe.py`，全部自动化）：
  - 控件级：**73 / 73 项完整往返，意外丢失 0**（另 6 项按设计不存，脚本单列）
  - **像素级**：真渲染三张图比对 —— 保存前 vs 载入后 平均差 **0.0000/255**
    （逐位一致）；对照组（扰动前后）**73.9/255**，确认这个 0 不是"两边都没变"

- **「可视化」tab 右侧参数区重做：3 块平铺 → 6 个分节 + 顶部固定条，并统一到一套行栅格**
  （设计文档 `docs/viz_tab_redesign.md`，分 P0 栅格 / P1 分节两期落地）。
  改动前的实测问题（`_viztab_probe.py`）：
  - 面板 **653×2300px**，右栏视口只有 **665×681** → 打开这个 tab 要先滚 **3.4 屏**；
  - 同一件事用了**三套布局机制**：原「显示 / 等值面」是 `QVBox`+每行一个 `HBox`
    （标签列硬编码 `LBL_W=110`），原「球棍模型」是 `QGridLayout`（标签列自动 → 152），
    原「vdW 外壳」又是第三种写法（标签列 → 129）。于是同一个面板里
    **标签右边缘有 6 种取值**（110/118/122/194/281/343）、**控件左边缘有 4 种**
    （0/118/130/206）——没有一条共同的基准线，这是"看着乱"的主因；
  - 行高 **5 种**（39/37/32/27/26）、滑块宽度 **7 种**、数值框 **3 种**；
  - 「显示 / 等值面」一组里 **24 行平铺**，光照、材质、原子配色、等值面、相位配色、
    样式 I/O 全混在一起，找「粗糙度」要滚过 10 行光照参数；
  - **6 处"一行塞两组参数"**把栅格撕开：`天顶/地面色`（一行两组标签+色块）、
    `透明合成`（三段起点 x=118/248/457）、`等值面描边`（复选框当标签 + 行内
    「粗细:」+ 被限宽到 190px 的滑块 + 「描边颜色:」）、色轮行（四种东西一行）、
    `呼吸`+`重置视角`、`灯光`+`样式:保存/载入`（两组功能硬凑一行）。

  #### P0 —— 统一行栅格
  - 抽出面板级 `_param_lbl()` / `_param_row()` / `_note_row_widget()`，
    三套布局共用同一套行/标签工厂（原先 `_lbl`/`_row` 是 `_build_params` 里的
    局部闭包，球棍组和 vdW 组够不着，才各自另写了一套）。
  - **标签列**：`_param_lbl_w = 实测最长标签` + `setFixedWidth`（原来是
    `setMinimumWidth(110)`，允许长标签自己撑开，才出现 110/118/122/133 四种值）。
    `_refit_param_columns()` 在 show 之后再校一次——控件未 polish 时量到的
    sizeHint 偏小（'WBOIT 衰减:' 建时 117、显示后需要 122），只按建时宽度固定会裁字。
    切语言后也重算，并且**先松开固定宽度再量**，否则列宽只增不减
    （英文撑到 197 就回不到中文的 129）。
  - **行高**：取所有行内控件的自然高度上限后统一固定。为此在 `_CANVAS_QSS` 里给
    `QFrame#CubParams` 下的输入框/下拉/按钮收紧内边距（`padding: 3px 8px`）——
    全局主题给 `QLineEdit`/`QPushButton` 的 `minimumSizeHint` 是 **39px 硬下限**，
    不收紧就没法压到 33px。
  - **网格**：`_sec_grid()` 与行布局共用同一套 间距/标签列/控件列，两者混排时竖线仍对齐。
  - **滑块**一律 `stretch=1` 吃满剩余宽度；**数值框**统一 64px。
  - 7 处特殊行拆成标准行；复选框当行标签的行改用 `_promote_chk()`——把文字挪到
    行首标签列、复选框留空（同一个字符串仍然只显示一次，i18n 登记同步搬家，
    否则 `_apply_lang` 会把文字又写回复选框）。
  - 修掉两个让竖线断掉的坑：
    ① `_param_row` 在没有拉伸项时补一个**行尾弹性空白** —— 否则
    `QHBoxLayout` 会把"没人吸收的多余宽度"摊到控件之间的**间距**上
    （实测「剥离层数: [4]」这类行标签被推到 x=140、控件推到 x=405）；
    ② 去掉 `_grid_quality_cb` / `_peel_layers_spin` / `_post_scale_cb` 残留的
    `setMaximumWidth`（那是旧版一行塞三组时的紧凑写法，独占一行后同样会触发 ①）。

  #### P1 —— 分节 + 顶部固定条
  - 参数区从 3 块平铺改为 **6 个折叠分节**：等值面 / 相位与配色 / 光照与材质 /
    原子与键 / 背景与后处理 / vdW 外壳（`_PARAM_SECTIONS`）。
  - **默认只展开第一节**，展开状态持久化到 `fchk_orbital.ini` 的 `param_sections` 段；
    顶部固定条新增「全部展开 / 全部折叠」，并会跟着实际展开情况同步勾选态。
    → 打开这个 tab **首屏免滚动**（实测 671px ≤ 视口 681px；改动前是 2300px）。
  - **顶部固定条**：`样式: 保存… 载入…` 与 `重置视角` 从长列表第 ~1150 行 / 最底部
    提上来（原先要滚 1.7 屏才够得着）。
  - 内容区用普通 `QWidget#CubParamSection` + QSS 画白卡片，**不用 `QGroupBox`**：
    分节标题已在折叠按钮里，`QGroupBox` 的空标题仍会让出标题区与边框内缩，
    实测每节白吃 **48px** 高度（iso 节 444 → 396px）。
  - `main_window.py` 不再强制 `_btn_toggle_iso/_btn_toggle_ball` 全展开
    （全展开 2712px，视口才 681px）。

  #### 每节一张圆角矩形卡片
  - 分节外观做成 **一张圆角卡片把标题栏和内容一起包住**（标题在卡片顶部，
    不再是卡片外面一个悬空按钮）：
    ```
    ┌──────────────────────────┐
    │ ▾ 等值面                  │  ← 折叠按钮（卡片顶部，悬停有底色）
    ├──────────────────────────┤  ← 展开时一条细分隔线
    │  等值面配色:  [ … ]       │
    └──────────────────────────┘
    ```
    收起时只剩标题那一条，仍是一张圆角小卡。卡片 = 白底 + `1px #D8E0EA` +
    `border-radius: 8px`。顶部固定条用同一套视觉。
  - 标题栏样式移到面板级 QSS（原先按钮上挂内联 `setStyleSheet`，内联优先级更高，
    会把卡片的圆角/底色一起盖掉）。

  #### 修掉两个"样式/高度没生效"的坑（都是实测抓出来的）
  - **参数区的样式表挂在错的地方**：主窗口会把参数面板从画布面板里**摘出来**
    （`canvas_params.setParent(None)` 再 `addWidget` 到右侧 tab），摘出去之后它
    不再是 `CubCanvasPanel` 的后代 —— `_CANVAS_QSS` **再也作用不到它**。
    实测：把 `#CubParamCard` 规则留在 `_CANVAS_QSS` 里时，圆角/白底/边框
    **一个像素都没画**（抓像素全是 `#f0f0f0`），收紧输入框内边距的规则也没生效
    （`QLineEdit.minimumSizeHint` 仍是 39px）。现拆出 `_PARAMS_QSS` 直接
    `setStyleSheet` 到参数面板自己身上，随它去哪都跟着。
    （原 `QFrame#CubParams { background-color:#F5F6FA }` 也是同样的"死规则"。）
  - **行高会随"量得早还是晚"跳**：QSS 的内边距只有 polish 之后才反映到 `sizeHint`
    上。原先在 `_build_params` 里量，量到的是全局主题给输入框的 39px 下限，
    而 show 之后的重算又量到 33px —— 同一份代码两次运行默认高度 **673 / 723 不同**。
    现在量之前先对整棵子树 `ensurePolished()`，实测连跑 3 次都是 676px。
    另外把 `QLabel`/`QSpinBox` 排除出行高测量（标签钉多高都不会裁字；
    Fusion 给 QSpinBox 的 39px 是微调按钮的度量、不是文字需要），
    否则一个数字框就能把整张表单的行高顶起来。
  - **`_tabs_regress.py` 抓出的既有 bug**：`PagedScrollArea` 只在自身 resize /
    切页时重算内层栈高，页面内容**事后长高**（展开分节、切语言重算行高）
    不会被采纳 —— 加高的那截落在滚动范围之外，底部够不到（实测页固有高度
    2655px 而栈高只有 2542px）。现在参数区的 `paramsChanged` 会触发重算。

  #### 验收（`_viztab_grid_probe.py`，全部自动化断言）
  | 指标 | 改动前 | 改动后 |
  |---|---|---|
  | 行首标签右边缘取值 | 6 种 | **1 种（139）** |
  | 首个控件左边缘取值 | 4 种 | **1 种（147）** |
  | 行高取值 | 5 种 | **1 种（33）** |
  | 数值框宽度 | 3 种 | **1 种（64）** |
  | 滑块与其后数值框的间距 | 参差 | **1 种（8）** |
  | 默认展开高度 / 视口 | 2300 / 681（滚 3.4 屏） | **676 / 681（0 滚）** |

  60 行设置、中英文两种语言下栅格均唯一；**每个控件的行高都容得下它的文字、
  每个标签的宽度都容得下它的文字**（逐控件比对字体度量）；圆角卡片按**抓像素**
  验证（四角露出面板底色 `#f5f6fa`、边框 `#d8e0ea`、内部 `#ffffff`）。
  `_num_edits`/`_cv_reg`/控件数不变，`_sync_style_ui()` / `_sync_material_ui()` /
  `_sync_post_ui()` / 7 个一键样式与相位色块同步全部照常可调用；
  分节折叠仍发 `paramsChanged`。`_viz_layout_probe.py` 已按新结构重写
  （原版断言"两组折叠区"已失效），并新增 `_param_rowh_probe.py`
  （量各类控件的自然高度，用来定行高）。
  1280×760 这类比默认窗口还矮的尺寸下首屏必然要滚，脚本自动跳过该断言。

- **导出图片支持 PNG / JPG / TIFF / SVG 四种格式**。原先"导出图片"只会导出 PNG
  （保存对话框过滤器写死 `PNG (*.png)`），现在这一条链路上四端都打通：
  - **写入层**（`ovcanvas/_glwidget.py`）：新增 `save_export_image()` ——
    按**目标扩展名**选编码器，用 `QImageWriter` 写 PNG / JPG / TIFF，
    用 `QSvgGenerator` 写 SVG（QtSvg 缺失时回退到手工拼 XML）。
    `export_image()` / `screenshot()` 都改走它，因此"截图"按钮
    （`glw.screenshot()`）也顺带支持了这几种扩展名。
    - **JPG 没有 alpha 通道**：勾了「透明背景」时先把图**合成到画布底色**再编码，
      避免半透明区被看图器叠到黑底上发黑；导出后状态栏给一句说明。
    - PNG / TIFF / SVG 三种都支持真透明背景（背景像素 alpha=0）。
    - DPI 元数据（dotsPerMeter）对 PNG / JPG / TIFF 照旧写入；SVG 把
      `width/height` 按 DPI 换算成毫米、`viewBox` 用像素，排版软件里
      1:1 按所选 DPI 落版。
  - **格式判定优先级**：路径里明确的已知扩展名 > 保存对话框选中的过滤器 >
    菜单里点的格式；三者都没有时回落到 PNG。用户只打 "out" 会自动补后缀
    （`export_ensure_suffix`），打 ".jpeg" / ".TIFF" 这类别名也认。
  - **画布面板**（`ovcanvas/_panel.py`）：「导出图片」按钮加了格式下拉菜单
    （PNG / JPG / TIFF / SVG），中文说明「无损 / 有损 / 支持透明」。
    菜单文字随中英文切换（`_CV_EN` 新增 4 条）。
    之所以用**菜单**而不是在那一行再塞一个独立下拉框：这一行控件本来就多
    （同步到VMD / DPI / 透明背景 / 截图 / 导出图片 / 键长标注 / 清除），
    多一个下拉框会让换行更早发生；菜单只让按钮宽 +18px（98 → 116）。
  - **ESP 面板**（`esp_panel.py`）：`_export_png` → `_export_image(fmt)`，
    同样是四项下拉菜单，`_export_png` 保留为兼容别名；「透明背景」勾选框
    tooltip 与状态提示同步更新（中英文都补了文案）。
  - **独立 CubViewer**（`ovcanvas/_glwidget.py` 的 `CubViewer._export_image`）：
    保存对话框改为四格式过滤器 + 扩展名判定（这个窗口没有下拉菜单，
    格式就在对话框里选）。
  - `OrbitalViewer.spec` 的 `hiddenimports` 补 `PyQt5.QtSvg`：
    `Qt5Svg.dll` / `qsvg.dll` 与 `PyQt5\QtSvg.pyd` 是两回事，
    只靠 Qt 插件不会带上 Python 绑定，打包遗漏会让 SVG 导出走回退路径。
  - **SVG 的诚实说明**：3D 场景是 OpenGL 光栅化的结果，SVG 是**矢量容器 +
    内嵌满分辨率 PNG（base64 data URI）**。文件是标准 SVG（Inkscape /
    Illustrator / 浏览器 / LaTeX 都能直接排版，缩放不糊），但像素内容仍是
    位图；把几十万个着色三角形真正矢量化需要另写一套 2D 矢量渲染器，
    不在本次范围内。
  - 验证脚本：`_export_formats_probe.py`（写入层 47 项，含 QtSvg 缺失的
    回退路径与 JPG 压底）、`_export_e2e_probe.py`（真 OpenGL 画布端到端：
    四种格式像素尺寸一致、tif 与 png 平均差 0.000/255、svg 内嵌图与 png
    完全一致、jpg 0.097/255；UI 层用假对话框跑通菜单 → 过滤器 → 落盘，
    含手打 `.jpeg` / 无后缀补 `.tif` / JPG+透明的提示 / 中英文菜单切换）、
    `_export_esp_probe.py`（ESP 面板菜单与格式降级）。
    另有 `_stylebar_clip_probe.py` / `_stylebar_rows_probe.py` /
    `_stylebar_smoke_probe.py` 覆盖下面的换行布局改动。

- **一键样式「CYLview」**（画布样式栏，排在 MolStudio 之后）：与 MolStudio 完全
  同源，按 CYLview 观感改这几处 —— **关闭景深雾化**（`fade=False`，渲染时取
  `u_FogWidth=0`）、**关闭原子描边**、**原子半径 1.8**（MolStudio 为 1.5）、
  **化学键半径 3.79**（MolStudio 为 2.0）、**氢原子球与键一样粗**、
  **单光源按 `light_style.json`**（方向 `[-0.2687, 0.2687, 0.9250]`、
  `light_glow 0.5`、四灯槽 `[0.5, 0.5, 0.5, 0.5]`；MolStudio 为 0.1）。
  定义在 `ovcanvas/_panel.py` 的 `_CYLVVIEW_STYLE`，走
  `reset_molviewer_style()` → `apply_style_state()` 的既有流程；应用后左侧面板的
  半径滑块/输入框（180 / 379）、「景深雾化」与「原子描边」勾选框都会同步为实际
  状态。（`_sync_style_ui()` 原先漏同步雾化勾选，样式关掉雾化后面板仍显示
  "已开启"，本次一并补上。）
  实测（`_cylview_style_probe.py`，甲醇场景 640×480）：与 MolStudio 出图差异
  **24640 px**（主体平均 94/255，远超"一眼能看出"的 20 阈值）；主体像素
  10306 → **15527**，其中氧球红像素 2506 → **3970**（原子球仍清晰可辨），
  深灰（碳/键）占比 6.9% → **17.5%**（键明显变粗）。
- **「氢原子球与键一样粗」成为可保存的样式规则**（新状态键 `h_bond_radius`）：
  CYLview 的氢不用小球画，而是取**当前化学键圆柱半径**当球半径（实测两者都是
  0.28046（Bohr 系绘制单位），比值 1.0000），所以 H 与 C–H 键看起来就是一整根
  等粗的棍。
  - 取"当前键半径"而不是写死数值：改键粗细（3.79 → 2.50）时氢球半径同步
    0.28046 → 0.18500，永远和键一样粗。建键与拾取容差都改用同一个
    `_bond_radius()`，不会再出现两处算式各改一半。
  - 属于**样式属性**、不是手动微调：随样式文件保存/载入（`get_style_state()`
    导出 `h_bond_radius`，实测保存→读回→套用后逐项一致），**换分子/换文件后
    依然生效**（手动倍率表按设计不跨文件携带，此规则不受影响）。
  - 切到别的样式（MolStudio 等）会自动复位，不会残留到其它样式上；用户在
    「元素半径」对话框显式调过氢的倍率时以手动值为准（对话框会给出提示语）。
  - 单独开/关该规则的出图差异实测 **3059 px**（主体平均 56.8/255）。
- **出图观感预设（Look presets）**：画布上方新增「出图观感」下拉，一键把
  **布光 + 材质 + 后处理 + 景深雾化 + 背景**打包切换成整套观感。存在的理由：
  画布上几十个参数大多是"同一通道上的系数"，单点调整实测差异 < 2.5/255
  （清漆/光晕/粗糙度），而换整套观感能到 25–130/255——用户要的是台阶式变化。
  预设定义在 `ovcanvas/_looks.py`（每个预设是 `get_style_state()` 的**部分**状态，
  只覆盖观感相关键，不动等值面配色/原子配色/分子尺寸）：
  | 预设 | 特征 |
  |---|---|
  | 通透玻璃 | GGX 薄高光 + 淡景深雾化 + 纯白底（轨道图通用） |
  | 哑光纸感 | 无镜面高光 + 强环境补光 + 柔和明暗交界（黑白印刷友好） |
  | 高对比期刊 | 侧向双主光 + 硬明暗交界 + 强 AO/边缘暗化 + 轻微色调映射 |
  | 柔光雾面 | 强半球环境光 + 次表面散射 + 大景深雾化（氛围感） |
  | 金属光泽 | Matcap「金属」材质球（暗本体 + 亮反光条）+ 强暗角 |
  | 暖色影棚 | Clear-coat 清漆 + 暖顶光/冷地光 + 轻微色调映射与暗角 |

  六套预设**统一使用纯白背景**（出图/投稿首选）；雾化终色取自背景色，因此
  景深雾化会"远处淡入白底"。改白底后重测两两差异：分子场景最小 **25.3**、
  轨道场景最小 **25.1**，仍在"一眼能看出"的阈值之上。

  两两差异经实测标定（`_look_preset_probe.py` 输出主体像素上的差异矩阵）：
  6 套观感任意两套在主体上平均色差 **24.3–129.1**，最小也远超"一眼能看出"的
  20/255 阈值。下拉同时接 `currentIndexChanged` 与 `activated`，因此改乱参数后
  再选一次同一套也能回到预设原位。
- **样式可自带 GL 观感参数**：`STYLES` 条目新增三个可选键，用于让某个样式在 GL 画布上
  完全复现指定观感（VMD/Tachyon 出图通道仍用各自的 `surface_mat`）：
  `gl_model`（`blinn` / `ggx` / `clearcoat` / `matcap`）、`gl_regs`（原子/轨道
  `[漫反射指数, 漫反射强度, 镜面强度, 双瓣平衡]`）、`gl_lights`（布光方向与灯数）。
  样式文件（保存/载入样式）现一并保存着色寄存器，载入后高光形态原样复现。
- **导出图与屏幕观感统一**：`export_image` 现在走与实时预览**同一条后处理合成路径**
  （`_compose_post`），超采样抗锯齿、SSAO、边缘暗化、色调映射、暗角、每原子软阴影
  与原子标签都会随导出图一起生效。此前导出直接分块 `_render()`，整条后处理被跳过，
  造成"画布上调好的效果一导出就没了"。分块导出时投影仍按瓦片子窗口计算，多瓦片
  无接缝；后处理目标不可用时自动回退到原直出路径。
- **景深雾化强度可调**：画布面板「景深雾化」旁新增强度滑块（0..1，默认 0.50），
  经 `set_fog_strength()` / `fog_strength()` 读写，并随样式文件保存（`fog_strength`）。

- **化学键多重键可视化**：画布右键菜单支持把选中的两个原子设为**双键**（两根平行圆柱）、**三键**（三根平行圆柱）或**离域键 / 芳香键**（一根实线 + 一根虚线并列，等价于"双键里其中一根画成虚线"），与已有的实线/虚线/断键共用同一套逐键覆盖机制
  - **子键与普通单键等粗**（默认子键半径系数 1.00）：双键读起来就是"两根一样粗的键并排"，与化学制图习惯一致；子键中心距默认为 3 倍子键半径，保证等粗的两根线之间仍留出半条线宽的净空
  - 偏移方向取「相邻键方向垂直键轴的分量」`u = ref − (ref·axis)·axis`，使多根线**落在成键平面内**——平面型 sp² 体系（乙烯、苯环、羰基）即分子平面，俯视平面时能清楚读出重数；两端参考方向都取不到（直线型 sp 或孤立原子对）时退回世界轴的垂直方向
  - 离域键的虚线沿用既有的"黑色小圆点阵"画法，点的粗细默认放大到 0.70 倍子键半径，与同排的等粗实线观感匹配（点大小/间隔仍由面板的「虚线大小 / 虚线间隔」控制）
  - 子键端点自动内缩，避免圆柱戳进原子球；线间距随键长夹取，极短键不会宽过键长本身
  - 「键样式」对话框中新增「多重键」分组：可调**子键粗细**（子键半径/单键半径，默认 1.00）与**线间距**（中心距/子键半径，默认 3.00），随样式文件保存/载入
  - 逐键标注按原子序数签名判定保留：同一分子换几何（IRC 逐帧、优化步）保留标注，载入另一分子自动清空
- **虚线键新增「短圆柱段」样式**：「键样式」对话框可切换两种虚线画法——既有的**小圆球点阵**（细点，读作"部分键"）与新增的**短圆柱段**（一段段带平端盖的小圆柱排开，段与实线等粗，是真正的"虚线"画法）
  - 段数/间距沿用画布面板既有的「虚线间隔」滑块；「虚线大小」在点阵样式下缩放点半径、在短圆柱段样式下缩放段粗细（默认 1.0 = 与单键等粗）
  - 该设置同时作用于**离域键**里的那根虚线；随样式文件保存/载入（`dash_style` 字段）
  - 端盖是必需的：键渲染趟关闭了背面剔除（双面渲染），没有端盖的短圆柱从侧面会看进管子内部、显得是空心环
- **成键模式（两类）**：球棍模型面板新增「成键模式」下拉
  - **一律单键**（默认，既有行为）：检测到的键全部画成实线单键
  - **按键长自动判定键型**：用键长相对「单键共价半径和」的比值 `q = r/(r_i+r_j)` 分档，自动画出单键 / 离域键(1.5) / 双键 / 三键
    - 分档：`q ≥ 0.96` 单键、`0.90 ≤ q < 0.96` 离域键(1.5)、`0.80 ≤ q < 0.90` 双键、`q < 0.80` 三键（标定值：苯 C–C 0.914、酰胺 C–N 0.918、C=C 0.882、C=O 0.866、CO₂ 的 C=O 0.817、C≡C 与 C≡N 0.789、N≡N 0.775）
    - **只对 C/N/O 之间的键生效**：S/P/金属常有 d 轨道或配位效应（S=O 比值 0.918、P=O 0.855 都会被误判成多重键）、含 H 的键本来就只能是单键、卤素/硼缺少可靠标定，这些一律按单键处理
    - 右键逐键指定的键型**优先于**本模式；自动判定模式下右键菜单会显示判据（如「按键长自动判定：双键（键长比 0.875）」）
    - 随样式文件保存/载入（`bond_mode` 字段）

### Changed
- **CYLview 一键样式的等值面配色 / 材质 / 透明合成按导出的
  CYLview 样式状态更新**（2026-09-27）。逐项：

  | 键 | 旧值 | 新值（= 导出值） |
  |---|---|---|
  | `phase_pos` | `[0.95,0.95,0.95]` 近白 | **`[0,0,1]` 蓝** |
  | `phase_neg` | `[0.5,0.9,0.1]` 绿 | **`[1,1,0]` 黄** |
  | `orb_opacity` | `1` | 不变（默认全不透明） |
  | `orb_alpha_mod` | 未设（会被重置回 1 = 受光照调制） | **`0`**（透明度滑块线性） |
  | `style_name` | 未设 | **`ultra-glass`** |
  | `shader_regs` / `style_regs` | 未设 | **`orb=[0.85,0.70,0.065,0.82]`** / `None` |
  | `transparency_mode` | 未设（默认深度剥离） | **`oit`**（WBOIT 加权混合） |
  | `oit_falloff` | 未设（默认 4.0） | **`11.9`** |
  | `bond_thinning` | 未设（默认 0.70 收腰） | **`1.0`**（直圆柱，与 CYLview 的 stick 一致） |

  导出里 post / back_dim / fog_strength / multi_bond / dash_style / bond_mode
  六项的值与项目默认**完全相同**，照旧走默认、不进样式字典（MolStudio 字典也不写）。
  - 顺带解决两件事：① 显式声明 `shader_regs` 必须配 `style_regs: None`，否则
    上一个 IBOview 样式残留的基准会继续参与 gloss 换算（`_cylview_style_probe`
    的"先套 iboview-crystal 再点样式"复现性检查现在两边寄存器一致）；
    ② `orb_alpha_mod` 显式写 0 后，CYLview 的透明度滑块也是全程线性的。
  - 涉及：`ovcanvas/_panel.py` 的 `_CYLVVIEW_STYLE`（含段首注释）。
  - 验证：新探针 `_cylview_color_probe.py`（相位色/不透明度/寄存器/透明合成/
    键收腰 + 真渲染取样：蓝瓣中位 `#2B2BF4`、黄瓣 `#FFFF00`）；
    `_cylview_style_probe.py` 的差异键清单已同步更新，与
    `_oneclick_style_probe.py`、`_style_roundtrip_probe.py`、
    `_vesta_iso_color_probe.py`、`_phase_flip_probe.py`、`_nbo_style_probe.py`
    一起全部通过。

- **VESTA 一键样式的等值面配色 / 光照 / 透明合成整组对齐导出的
  VESTA 样式状态**（2026-09-27）。该文件里与本样式相关的差异，
  逐项落到 `_VESTA_STYLE`：

  | 键 | 旧值 | 新值（= 导出值） |
  |---|---|---|
  | `style_name` | 未设 | `ultra-glass`（等值面材质风格） |
  | `phase_pos` | `[1,1,0]` 黄 | `[0,1,1]` **青** |
  | `phase_neg` | `[0,0,1]` 蓝 | `[1,1,0]` **黄** |
  | `orb_opacity` | `0.6` | **`0.2`**（80% 透明） |
  | `transparency_mode` | 未设（默认深度剥离） | **`oit`**（WBOIT 加权混合） |
  | `oit_falloff` | 未设（默认 4.0） | **`11.9`** |
  | `orb_alpha_mod` / `shader_regs` | 已是 0 / `orb=[0.85,0.70,0.065,0.82]` | 与导出一致，不动 |

  其余（单光源方向与光晕 3.0、Clear-coat 0.15/1.78、粗糙度 0.55、半球环境光、
  95 条元素覆盖色、键两端分色、关雾化）与该导出逐条比对后确认本来就一致。
  - 说明 1（配色依据）：VESTA 手册 Objects → Properties → Isosurfaces 一节写的是
    *"Yellow and blue surfaces show positive and negative values, respectively."*，
    即黄=正、蓝=负；而这份导出是"**青=正、黄=负**"。样式照导出值设置（青/黄），
    要按手册口径对调只需把 `phase_pos` / `phase_neg` 互换。
    另注：VESTA 的等值面颜色**不写进任何配置文件**（`VESTA.ini` 只管窗口状态、
    `style\default.ini` 的 `ISURF` 一节只有 4 个 0），`VESTA.exe` 里内建的
    9 色调色板含纯 `#0000FF` / `#FFFF00` / `#00FFFF`，本次用色即出自其中。
  - 说明 2（上一步的连带改动保留）：等值面光照寄存器 `orb` 的漫反射强度
    `0.12 → 0.70`。0.12 那组是配合**旧 alpha 公式**的产物（旧公式里
    alpha ∝ 漫反射强度，压低 DiffStr 就等于"让面更透"，代价是颜色一起变暗）；
    本样式 alpha 现在由滑块线性决定，继续用 0.12 会把瓣渲染成暗橄榄 `#737347`。
  - 涉及：`ovcanvas/_panel.py` 的 `_VESTA_STYLE`、VESTA 按钮悬停说明与状态行。
  - 验证：`_vesta_iso_color_probe.py`（含正负两瓣的 `_demo_dz2.cub` 真渲染取样：
    青瓣中位 `#5DFFFF`、黄瓣 `#FFFF87`，相位色相正确且都被白底透亮）、
    `_vesta_style_check.py`（断言已换成青/黄 + 0.2 + WBOIT 11.9）、
    `_oneclick_style_probe.py`、`_cylview_style_probe.py`、
    `_style_roundtrip_probe.py` 全部通过；对比图 `_vesta_iso_before_after.png`。

- **「一键样式 → IBOview」光泽 10%、等值面透明度 50%**（按反馈），并**修掉上一轮
  引入的一处回归**：IBOview 字典原先没有声明自己的着色寄存器基准，上一轮把"未声明
  基准 = 无基准"的规则接上后，`set_style('iboview-purple-blue')` 刚建立的 IboView
  基准会被清掉，光泽落到通用映射（`a_reg[2]` 0.787 → 0.118、`o_reg[2]` 1.377 →
  0.059），等值面因此变得又平又白（实测差 **5556 px**）。现在把基准显式写进
  `_IBOVIEW_STYLE.style_regs`，按钮在任何前置状态下都还原 IboView 观感。
  - 数值：`gloss` 0.118 → **0.1**（IboView 系样式的滑块是基准倍率，k = gloss/0.06，
    故 0.1 = 原版高光的 1.67 倍 → `a_reg[2]` 0.667、`o_reg[2]` 1.167，与修复前
    0.118 时的 0.787 / 1.377 同一量级）；`orb_opacity` 0.75 → **0.5**。
    面板同步为 光泽 10、透明度 50。
  - 效果（轨道场景 560×420）：最大通道均值 224 → **228**、中位 245 → 239、
    过曝(≥250) 47.2% → **39.4%**（白底 + 50% 透明本身就会让等值面偏亮）；
    与改动前的出图差异 **8685 px**（平均 37.8/255）。
  - 备注：中途曾按字面把光泽设成 1.0 试过（= 原版高光的 16.7 倍），实测
    等值面会明显变深变硬（均值 158、过曝 5.9%、暗部 4.3%），已按反馈落回 0.1。
  - 可复现性：现在"先套 iboview-crystal 再点 IBOview"与"干净画布直接点"出图
    **逐像素一致**（0 px，阈值 8/255），已并入 `_cylview_style_probe.py` 的复现性
    小节（MolStudio / CYLview / IBOview 三条路径）。
- **七个「一键样式」统一默认不打开景深雾化，MolStudio 取消原子描边**（按反馈）：
  - 雾化：`reset_molviewer_style()` 里的默认由 `set_fade_enabled(True)` 改为
    **False**，同时把 `fade: False` 显式写进样式字典（`_SOBART_STYLE` /
    `_HOUKMOL_STYLE` / `_HOUKMOL3D_STYLE` / `_IBOVIEW_STYLE` / `_MOLSTUDIO_STYLE`
    / `_CYLVVIEW_STYLE` / `_IQMOL_STYLE`）。两处都改的原因：IQmol 按钮走的是
    逐步设置（没有整字典套用），只能靠 reset 的默认值；HoukMol 按钮不调 reset，
    只能靠字典。现在两条路径都覆盖到了。
  - MolStudio：`atom_outline` 由开（黑 0.35）改为**关**。sob-art 与 HoukMol
    的描边是各自风格的一部分，保持不动。
  - 实测（`_oneclick_style_probe.py`）：先故意把雾化/描边打开再点按钮，
    七个样式全部把雾化压回关闭，画布与面板勾选框一致（MolStudio 的描边也同步
    为未勾选）。MolStudio 自身雾化 关/开 的出图差异 **12466 px**（主体平均
    25.1/255）——这次改动是肉眼可见的。
  - 雾化没有被锁死：面板开关与强度滑块照常可用（实测手动打开 + 设 0.60 生效）。
  - **「出图观感」预设不受影响**：六套预设各自显式写 `fade: True` 和自己的雾化
    强度，是两个独立的轴。实测 MolStudio →「通透玻璃」雾化自动打开（0.35）、
    →「柔光雾面」打开（1.00），再点 MolStudio 又回到关闭。
- **「一键样式 → sob-art」改为外部 sob-art.json 的全量状态**（`ovcanvas/_panel.py`
  的 `_SOBART_STYLE`）：SobArt 原子配色 / 四灯（`light_glow 0.1`、逐灯
  `[0.88,0.88,0.88,0.1]`）/ **Blinn-Phong** 镜面模型 / 光泽 0.77 / 次表面散射 0.3 /
  等值面透明度 0.70 / 原子描边 0.35 / 白底 / **关景深雾化** / 着色寄存器
  `atom [0.85,0.7,0.77,-0.5]`、`orb [0.85,0.6,0.385,1.0]`。原「仅灯光」的子集升级为
  全量 `apply_style_state`（与 IBOview/MolStudio 两个按钮同一套流程），IQmol 按钮
  继续复用原光照（改名 `_SOBART_LIGHT`），行为不变。应用后与 JSON 逐键比对一致
  （仅相位色有 8bit 往返的 ±0.002 舍入）。
- 「金属光泽」按反馈再调**更亮更平**（磨砂铝）：竖直环境梯度暗端 0.18 → **0.62**
  （本体更亮、明暗差更小），反光条强度 0.40 → 0.10，去掉边缘反光。实测最大通道
  均值由 119–141 提到 **156–181**，锐闪点(>230) **0%**，对比度 std 25–41。
- **出图观感：去掉背景灰阶、金属收敛为缎面**（按反馈调整）：
  - 六套预设的**暗角全部清零**（`vignette = 0`）。暗角会在纯白底上把四角压暗，
    看起来就是"背景灰色渐变"；现在四角实测为纯白 255（此前 高对比期刊 0.18、
    柔光雾面 0.22、金属光泽 0.25、暖色影棚 0.25）。背景本身一直是纯白、无渐变。
  - 「金属光泽」由"暗本体 + 强反光条"改成**缎面/拉丝钢**：本体抬亮（最大通道
    均值 ~120–140 而不是 ~85），只留**一道柔和宽反光**、强度降到 0.40，去掉
    第二道锐反光条与锐闪点。锐闪点（最大通道 >230）占比从 4.5–5% 降到 **0.6–1.6%**，
    对比度 std 由 59 降到 34–41（塑料/哑光 17–28）——不再浮夸。
- **景深雾化明显加强**（原来"调了几乎看不出"）：
  - 映射改为铺满**整个物体深度**：`t` 从包围球最前面(0) → 最后面(1)，前面保持
    清晰、最后面按强度融入背景。旧写法以物体**中心**为零点，可见面大多落在中心
    之前，导致雾化几乎测不到（轨道场景开关差异 0.00；分子场景仅 15.7% 像素变化）。
  - 强度上限由 1.0 放宽到 **2.0**（1.0 = 最深处完全融入背景，>1 更快饱和），
    面板滑块相应改为 0–200%。
  - 默认强度 0.22 → **0.60**。
  - 雾化终色由固定**白色**改为**背景色**：白底时与旧观感逐像素一致，深色/彩色
    背景下不再"越远越白"。
  - 实测（导出路径，主体像素）：轨道场景雾化开→关差异 0.00 → **40.1**（99.3% 像素
    变化 >8）；分子场景 15.7% → **96.5%**；强度 0.0/0.3/0.6/1.0/2.0 时主体均色
    单调变化（[68,199,215] → [202,241,245]），滑块全程有力。
  - 注：IboView 原版 FadeWidth=9 约合本坐标系 0.35，想要那种淡雾把滑块调回 ~35% 即可。
- **IboView 系列样式按 IboView 原版着色复现**（`iboview-*` / `IQmol` / `Gaussview`）：
  这些样式此前在 GL 画布上走 GGX + 样式自带 shininess，而 IboView 原版画布用的是
  **双瓣 Blinn-Phong**，寄存器为原子 `[0.8, 0.7, 0.40, -0.5]`、轨道 `[0.8, 0.7, 0.70, -0.5]`
  （`ShaderReg3 = -0.5` 的负宽瓣正是它那种"紧致亮斑 + 外围略压暗"的晶体感），
  外加 Mayavi 标准三点布光。现把这套观感作为样式参数挂在 `STYLES` 上
  （`gl_model` / `gl_regs` / `gl_lights`），由 `style_params`、`set_style` 应用；
  无该声明的样式仍走原来的 GGX 路径。以旧版移植渲染器
  （`ovcanvas/_glwidget_iboview.py`）为基准逐像素比对：轨道画面整体平均差
  0.15–0.17、主体内部 9928 像素中仅 75 像素差 >8（最大 10），即观感复原。
  光泽滑块在样式基准上做倍率（默认档 = 1.0 即 IboView 原样，0 = 哑光）。
- 默认景深雾化强度 0.50 → **0.22**（对应 IboView `FadeWidth = 9` 的等效远端蒙白幅度），
  避免默认出图把远端冲淡。
- **SSAO 重做**：原实现用"邻域平均深度差"判据，采样到背景（深度 1.0）时均值被拉远、
  差值恒为负，实测在甲醇/苯环/轨道三个场景下 AO 图 **99.99% 像素为 0**，把灵敏度
  提高 100 倍仍全 0——滑块完全无效。现改为「深度范围检测（遮挡物比本像素更近）+
  横向衰减 + 背景样本剔除 + 法线背向剔除」，并引入 Vogel 盘采样与后处理里的 5 抽
  去噪；AO 采样半径、强度滑块现在都有真实反应（导出路径 AO 关→开主体色差 19.9/8.6）。
- **镜面高光能量重新标定**：GGX/Clear-coat 的 F0（0.04）决定了高光峰值只有 ~2% 亮度，
  实测把高光倍率放大 30 倍、粗糙度从 0.45 调到 0.05 都几乎看不出变化。现引入
  `SPEC_ENERGY`（8.0）艺术增益，并把 gloss→镜面强度映射由 0.30..2.00 的仿射改为
  从 0 起算的线性映射（`_GLOSS_SPEC_MAX`）；默认光泽同步降到 0.06 保持默认观感，
  滑块上端能给出清晰高光（主体色差 7.6/15.5，峰值差 78/182）。
- **景深雾化改用视图空间线性深度**：原公式基于 `gl_FragCoord.z`，正交投影下窗口深度
  被压扁到近乎常数，`FogWidth=8.0` 实测毫无作用（开关差异 0.00）。现按
  `u_FogDepth`/`u_FogRange`（相机距离 + 场景包围球半径）换算，雾化开关与强度滑块
  都可见（分子场景主体色差 3.1，约 2900 像素差异 >8）。
- **色调映射保持白底**：ACES 结果按 `ACES(1.0)≈0.803` 归一，白色背景仍是纯白，
  只让物体自身的中间调/高光走胶片曲线；此前开启后整幅画面被压到 0.80（灰），
  读数就是"一开就发灰、分子没变化"（全图色差 50 → 3.3，物体色差 54.8）。
- **原子/键也吃用户材质设置**：`set_surface_material(ambient=/spec_mul=)` 现在对原子与
  化学键同样生效（此前只作用于等值面，实测球棍模型上 0.00 变化）。样式自带的
  ambient/spec_mul 仍只作用于等值面，避免切换一键样式时改变球棍模型观感。
- 默认景深雾化强度由等效"失效"的 8.0（窗口深度斜率）改为 0.50（场景最远处蒙白幅度）；
  切样式时保留用户调过的光泽/粗糙度/雾化强度。

### Fixed
- **「一键样式」卡片文字被压没 —— 四行改成自动换行布局**。原先卡片里四行都是
  固定 `QHBoxLayout`，画布面板在默认 1400px 窗口下只有 557px 宽，而四行内容的
  固有宽度实测是 **276 / 928 / 682 / 702px**。QHBoxLayout 装不下时会把每个控件
  压到 `minimumSizeHint` 以下，`QPushButton` 又不会用省略号截断，文字就被直接
  裁掉。用 `_stylebar_clip_probe.py` 逐控件量「实际宽度 vs 文字所需宽度」：

  | 窗口 | 画布面板宽 | 文字被裁的控件数 |
  |---|---|---|
  | 1400×820（默认） | 557 | **17** |
  | 1600×900 | 648 | 14 |
  | 1920×1080 | 792 | **8**（全部是一键样式按钮） |
  | 2560×1440 | 1081 | 0 |

  最夸张的是「同步到VMD」需要 124px 只给了 60px（裁 64px）；1920px 下
  「HoukMol3d」需要 133px 只给了 105px —— 用户根本分不清那几个样式按钮。

  - 新增 `FlowLayout`（`ovcanvas/_panel.py`）：放不下就**换行**，控件永远保持
    自己的 `sizeHint`。四行（出图观感 / 一键样式 / 分子显示 / 导出+标注）全部改用它。
  - 新增 `_hgroup()`：把「标签 + 输入框」（`DPI:`+输入框、`保留H编号:`+输入框）
    包成一个整体，换行时不会被拆到两行。
  - **行内控件必须垂直居中**（用户反馈「分子显示:」这类标签"和后面的内容不在
    一条线上、没对齐"）。`QHBoxLayout` 默认就是垂直居中，而换行布局若按行顶
    对齐，同一行里 `QLabel`(≈20px) / `QCheckBox`(≈22px) / `QPushButton`(≈30px)
    高度不同，标签的文字就会比按钮文字高出约 5px —— 看着像被挪到了另一行。
    现在 `_layout()` 先分行、取本行最高控件作行高，再把其余控件按
    `(row_h - h) // 2` 居中。`_stylebar_align_probe.py` 量「同一行各控件
    矩形中心 y 的最大偏差」：修前标签比按钮高 **5px**，修后全部 **≤1px**。
  - **高度必须显式锁定**：换行行数随宽度变，而外层 `QVBoxLayout` 在垂直空间不够时
    会一路压到 `minimumSizeHint`（换行布局的最小高度只有"最宽的那个控件"），
    后几行就**互相重叠** —— 实测 1100×680（窗口最小尺寸）下重叠 **11 处**。
    所以 `CubCanvasPanel.resizeEvent` → `_sync_style_card_height()`，用
    `QVBoxLayout.totalHeightForWidth()` 算出该宽度下的真实高度并 `setFixedHeight`。
    （注意 `totalHeightForWidth()` 自己会扣 `contentsMargins`，传内容宽度会算多
    一行，1920px 下多出 43px 空白；要传卡片外框宽度。）切语言时标签宽度变了，
    `_apply_lang()` 里也要重算。另外给画布区加了 120px 的高度下限，免得窄窗口下
    画布被压成 0 高。
  - **代价（如实说明）**：卡片在窄窗口下会变高，画布区相应变矮。实测
    1400×820：卡片 198 → 369px，画布区 469 → 298px；1600×900 画布区 421px；
    1920×1080 画布区 644px；2560×1440 卡片仍是 198px、画布区 1059px（与改动前
    完全一致 —— 宽到能一行放下时换行布局不产生任何额外高度）。
    如果更看重画布高度，可以考虑的后续手段（未做）：① 把「分子显示」四个勾选
    移进「可视化控制」参数区（语义上也更合适，能省 2 行）；② 调
    `main_window._DEFAULT_SPLIT_SIZES` 把画布默认宽度从 560 提到 ~660（右栏
    680 → 620）；③ 给卡片加折叠开关。
  - 验证：`_stylebar_clip_probe.py` 在 1100/1280/1400/1600/1920/2560 六种窗口
    尺寸 × 中英文两种语言下，**裁字 0、重叠 0、宽度塌陷 0**；
    `_stylebar_align_probe.py` 同尺寸同语言下**同行业中心偏差 ≤1px、无孤立标签**；
    `_stylebar_smoke_probe.py` 覆盖连续 8 次改尺寸（无布局死循环，1.9s）、
    中英文来回切、加载 cube + 导出、以及 `OVCanvas` 独立使用。

- **一键样式观感不可复现（被上一个样式污染）**：`apply_style_state()` 原先按
  「先算 gloss → 后写着色寄存器基准」的顺序执行，而 `_apply_gloss()` 恰恰是用
  `_style_regs` 作基准把 gloss 换算进镜面槽 `a_reg[2] / o_reg[2]`。于是**先套任一
  IboView 等值面样式（自带 `gl_regs`）、再点一键样式**时，gloss 会按 IboView 基准
  换算（实测 a_reg[2] 0.13 → 0.867、o_reg[2] 0.065 → 1.517），同一个样式按钮在
  不同前置状态下出图不一致（实测差异 4635 px）。
  现把寄存器基准的确定提到 gloss 之前，并明确：**半量字典（一键样式，既无
  `style_regs` 也无 `shader_regs`）视为"无基准"**，清掉上一个样式残留的
  `_style_regs`。修好后「先套 iboview-crystal 再点样式」与「干净画布直接点」
  出图**逐像素完全一致**（差异 0 px，阈值 8/255），MolStudio 与 CYLview 均验过。
- **ESP 色标条单位文字被裁（例如 "ESP (kcal/mol)" 显示不全）**：
  - 直接原因：上一轮给画布色标条加的"离屏超采样贴图"框开得太窄，比按字体度量
    算出的单位文本框还小，贴回时把两端切掉了。现按文字宽度留足余量
    （纵向 ±130px、横向 ±90px）。
  - 同时把单位文字与刻度数字的绘制改成 **单行模式**（`Qt.TextSingleLine`）并按
    实际字宽开框，长数字（`-1234.56`）与长单位都不会再换行/裁切。
  - 验证：单位文字在"超采样路径"与"直接绘制"下的墨迹范围完全一致
    （43..170 / 20..43，落点与像素数 695 vs 696）。
- **色彩刻度轴设置入口**：原先只能"右键点画布上的色标条"才能改字体，不容易发现。
  ESP 面板参数区新增 **「色标轴设置…」** 按钮（中英双语），点开为字体对话框：
  字体族（QFontComboBox）+ 字号（6–48pt）+ **实时预览** + 「恢复默认」，
  改动即时作用到画布；点「取消」恢复打开时的字体。（刻度段数/方位/长度本来就在
  同一行，保持不变。）
- **画布上的 ESP 色彩刻度条文字发虚**（导出图正常）：根因是**分辨率**而非画笔——
  屏幕上的刻度数字只有十几个**设备像素**高（10pt 字号 + 画布逻辑分辨率），
  抗锯齿后笔画发糊；而导出图是 6 倍分辨率渲染、再缩小观看，所以同一个标签显得
  锐利。修法：把色标条叠加层渲染到 **3× 离屏图再缩放贴回**（等价于给叠加层做
  超采样，与场景的 SSAA 同一思路），并给标签字体显式打开完整字形微调（hinting）。
  超采样倍率随 `devicePixelRatio` 自适应（高分屏上画布本身已是高分渲染，倍率
  相应减小），且带缓存——只在色标条参数/画布尺寸/拖动位置变化时重建，旋转缩放
  场景不会触发重建。导出路径不受影响（它本来就在导出分辨率下直接绘制）。
  实测（640×480 画布，DPR=1）：刻度文字区"实心笔画占比" 4.50% → **5.80%**，
  "中间灰（发虚）占比" 1.82% → **1.19%**；DPR=1.5 下两者持平（本就足够清晰）。
- **物体边缘残留的一圈暗环**：上一轮 AO 修好后仍能看到剪影外沿有一圈发暗，实测
  来自两处，现已分别处理：
  - **SSAO 在深度断崖处**：凸面剪影邻域里仍有少量"更近"的采样点通过切平面判据，
    在环上留下峰值 37/255 的假暗环。现增加**深度断崖检测**（四邻域深度差超过采样
    半径就整像素不做 AO）。修后剪影环贡献 **0.00（峰值 0.3，纯抗锯齿噪声）**，
    而分子缝隙里的接触阴影保持有效（峰值 59，4.2% 主体像素变化 >8）。
  - **「边缘暗化」后处理**：会在剪影外沿按亮度梯度压暗一圈（哑光那套环上峰值 11/255）。
    六套观感的 `edge` 一律归零（面板滑块保留，需要时可自行打开）。
  哑光观感在 600 DPI 下的块状残差随之从 1.409% 降到 **0.214%**（其中 AO 仅贡献
  0.06%，其余是网格本身的 0.151%）。
- **哑光观感下等值面"一块一块、像多面体"**：排查后确认有两处来源，哑光最"平"
  （无高光 + 大环境光）所以最先暴露：
  - **SSAO 在凸面上误判自遮挡**（本轮 AO 的真 bug）：只用"邻域深度更近"判据时，
    光滑凸面（球、轨道波瓣）剪影附近的邻接点虽然更近，却位于切平面**下方**，
    被当成了遮挡物 → 在物体边缘糊出一圈大尺度暗环（实测哑光观感下 58% 的主体
    像素被整体压暗）。现加入**切平面（horizon）判据**只统计位于切平面上方的
    样本，并重标定增益/阈值/去噪核：哑光观感下折痕残差 **1.409% → 0.450%**，
    而缝隙里的接触遮蔽反而更强（AO 图峰值 102 → 255，集中在 0.9% 像素上）。
    参数：`_AO_SAMPLES=32`、`_AO_TANGENT_BIAS=0.35`、`_AO_GAIN=8.0`、
    `_AO_BLUR_SPACING=1.0`、`_AO_RES_SCALE=0.5`（均可在 `_glwidget.py` 顶部调整）。
  - **网格面片本身**：关掉 AO 后，密网格 cube 折痕残差 0.049%，而粗网格（每轴
    隔点取样，1354 顶点）是 0.462% —— 相差 9 倍。这一项属于 cube 网格精度
    （Multiwfn 网格精度建议用 3 / 更细间距），渲染器侧已在此前去掉会放大它的
    法线 Laplacian 平滑。自检脚本：`_matte_patch_probe.py`、`_ao_quality_probe.py`。
- **导出图片不刷新"延迟上传"，导致换材质后导出还是旧的**：网格（`_needs_upload`）与
  Matcap 纹理（`_matcap_dirty`）都只在 `paintGL` 里上传，`export_image` 之前没有补做，
  于是**切到 Matcap「金属」后直接导出，出来的还是上一个材质球**（实测导出 0 变化）。
  现在导出前会先补做这两项上传。
- **Matcap「金属」做不出金属感**：旧 LUT 是**单通道灰度**，着色时乘在固有色上，
  数学上最亮只能等于固有色——不可能出现"比本体更亮的白色反光"，所以永远像塑料。
  现改为**双通道**（`GL_RG8`）：R = 乘性环境明暗（金属染色本体），G = **加性白色反射**
  （柔光箱反光条 / 高光）。`metal` 材质球重新标定为「暗本体 + 少量极亮反光」
  （竖直环境反射：下暗上亮 + 地平线亮带 + 两道反光条），实测主体内部
  暗(<90) ≈ 61–65%、亮(>230) ≈ 4.5–5%、对比度 std ≈ 59（塑料/哑光只有 17–28）。
  其余材质球 `add_white=0`，渲染结果与改动前逐像素一致。
- 金属观感预设关掉色调映射（ACES 会把暗本体从 0.20 抬到 0.37，金属对比全靠暗本体）、
  雾化由 0.20 降到 0.10。改后它在六套观感里差异最大（与其他五套 61.7–141.9）。
- **导出图片时等值面出现"一格一格的色块 / 折痕"**：根因是 `marching_cubes` 里默认
  的那轮**顶点法线 Laplacian 平滑**——它把法线误差**集中到三角面尺度**，在数字上
  表现为可见的块状折痕；配上 IboView 那种强而锐的双瓣高光（以及高分屏导出）尤其明显。
  实测折痕残差（`|I − 高斯模糊| > 1` 的像素占比，等值面主体内部）：

  | 导出 DPI | 平滑 1 轮（旧默认） | 不平滑（新默认） |
  |---|---|---|
  | 96 | 3.03% | 0.50% |
  | 300 | 2.57% | 0.26% |
  | 600 | 0.90% | 0.07%（残差峰值 6.3 → 1.8） |

  两种做法的总高频能量接近（频谱均值 16.5 vs 15.6），区别只在于误差是"成块"还是
  "成噪声"。故 `_NORMAL_SMOOTH_ITERS` 默认改为 **0**；若遇到噪声特别大的数据源在
  掠射高光下出现规则条纹，可调回 1（≥2 会抹平 d 轨道环等小波瓣细节）。
- 后处理中的 SSAO 去噪由 5 抽改为 3×3（9 抽）：AO 图约为 0.75× 输出分辨率，
  直接双线性放大会在等值面表面留下块状斑（开启 AO 时折痕残差 3.75% → 2.12%，
  而不开 AO 为 0.07%）。
- 导出高分辨率图时不再丢失抗锯齿与后处理效果；透明背景导出与无后处理回退路径
  均已回归验证（回退路径与后处理路径在 1.0× 超采样下逐像素一致）。

---

## [6.0] — 2026-08

> **更新简介（6.0）**：IboView 在分子轨道等值面渲染上表现优异，其深度剥离透明合成与三向 Phong 光照模型可提供高质量、通透的视觉效果。然而 IboView **原生不支持 Gaussian `.fchk` 文件的直接解析**；即便经 Molden 格式转换导入，轨道可视化仍常出现渲染异常乃至轨道数据无法读取。本版本将 IboView 的渲染管线移植至 OrbitalViewer，并在 **AI 辅助**下完成了着色器重写与管线迁移，使程序在保留 IboView 级渲染质量的同时，支持 **`.fchk` 直接读取、cube 文件自动生成与一键出图**。需说明：本次开发**未采用 DeepSeek，而是基于腾讯混元（Hunyuan）大模型**，开发体验良好。此外，**原有 VMD / Tachyon 渲染流程完整保留**，经典预览与光线追踪出图功能不受影响。

### Added
- 全新内置 OpenGL 渲染引擎（深度剥离透明排序），接入 IboView 风格 Phong 光照着色器，轨道等值面与球棍模型实时高质量渲染，无需依赖 VMD/Tachyon 即可预览
- 画布参数面板：可调等值面正/负相颜色、透明度、键收腰、原子/键缩放等
- 塑料/亮面（plastic-bright）等新增材质样式
- 高清图片导出，支持透明背景

### Changed
- 版本号升级至 6.0，标志 IboView 风格引擎正式并入

## [5.3] — 2026-07

### Added
- 模块化重构：分离 UI 层（`main_window.py`, `widgets.py`, `dialogs.py`）、逻辑层（`fchk_orbital.py`, `fchk_parser.py`）、绘制层（`molcanvas.py`）
- 内置国际化支持（`i18n.py`），中/English 即时切换
- QSS 主题系统（`theme.py`），现代化深色界面
- QThread 异步后台任务（`workers.py`），UI 不再卡顿
- 2D 分子结构画布，拖放文件自动渲染原子与化学键
- 轨道表格双标签布局（α/β 分列），占据态 emoji 可视化
- 虚线绘制工具：8 种颜色 + 5 种线型
- 高级叠加模式：同时加载两条轨道对比
- 运行日志面板：彩色标签 + 时间戳

### Changed
- 入口统一为 `main.py`，兼容 GUI 与命令行两种模式
- 命令行参数命名更规范（`--mo`, `--iso`, `--style`, `--res`）
- 渲染风格扩展至 30+ 套

### Fixed
- 开壳层体系轨道识别与显示
- VMD 连接稳定性

---

## [1.0.0] — 2026-06

### Initial Release
- 基础 GUI：拖放 fchk、加载轨道、VMD 预览、Tachyon 渲染
- vcube2.0 11 套渲染风格集成
- 命令行批处理模式
- 中/英文双版本（`orbital_viewer_zh.py` / `orbital_viewer.py`）
- PyInstaller 单文件打包
