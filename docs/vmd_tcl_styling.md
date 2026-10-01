# VMD 样式控制：Tcl 脚本怎么写、vcube 怎么组织、和本程序怎么对应

> 研究对象：vcube 2.0 的 `vcube.tcl`（武汉大学钟诚，2021-01）
> + 同一套件 `styles\` 目录下 13 个样式文件；对照本程序 `fchk_orbital.py`
> 的 `STYLES` / `_scene_tcl` / `_socket_server_tcl` 与 `vmd_embed.py`。
>
> 文中标 **[实测]** 的是在 VMD 1.9.3（本机安装版）上跑脚本验证过的结论，
> 复现脚本见 `_vmd_rep_probe.tcl` / `_vmd_vocab_probe.tcl` /
> `_vcube_style_audit.py`；标 **[手册]** 的引自 VMD User's Guide。

---

## 1. 一句话总览

VMD 的"样式"不是配置文件，而是**一串 Tcl 命令**；所有命令都围着两个索引转：
**分子号 molid** 和 **表示号 rep**。所谓"换一套样式"，就是把同一串命令换成另一串。

```
mol new  data.cub type cube      ← 造一个分子（molid=0）
mol addrep top                   ← 给它加一个"表示"（rep=1）
mol modstyle 1 top Isosurface …  ← 第 1 个表示画什么、怎么画
mol modmaterial 1 top sob-art_a  ← 这个表示用哪个材质
mol modcolor 1 top ColorID 31    ← 这个表示用什么颜色
material change opacity …        ← 材质本身的属性
color change rgb 31 …            ← 改颜色槽
light 0..3 on/off                ← 光照
display …                        ← 背景/投影/雾化/渲染模式
render Tachyon out.dat           ← 交给 Tachyon 出图
```

Tcl 在这里只干两件事：**把命令排好序**，以及**用变量/循环批量生成命令**。
没有任何"样式引擎"——`source` 一个 .tcl 就等于执行里面所有命令。

---

## 2. 控制面：三层命令 + 两个索引

| 层 | 命令 | 管什么 |
|---|---|---|
| 场景级 | `display` | 背景/投影/渲染模式/雾化(深度线索)/阴影/AO/抗锯齿 |
| | `light 0..3` | 4 盏灯（VMD 固定 4 盏槽位）：开关、方向、颜色 |
| | `color` | 颜色槽的 RGB、元素→颜色映射、Volume 色标 |
| | `material` | 材质库的增删改（9 个数值属性） |
| 分子级 | `mol new/addfile/addrep/delrep` | 造分子、加/删表示 |
| | `mol modstyle <rep> <molid> <类型> <参数…>` | 表示类型与几何参数 |
| | `mol modmaterial <rep> <molid> <材质名>` | 表示用哪个材质 |
| | `mol modcolor <rep> <molid> <方式> <参数>` | 表示怎么上色 |
| | `mol modselect <rep> <molid> <选择串>` | 表示作用于哪些原子 |
| 输出级 | `render Tachyon/TachyonLOptiXInternal …` | 光线追踪出图 |

**两个索引是所有混乱的根源**，也是所有技巧的来源：

- **molid**：一个 .cub 就是一个 molid；多个 cube 叠加出图时每个都是独立 molid。
- **rep**：一个 molid 可以有任意多个表示，各自独立设 样式/材质/颜色/选择。
  `mol top <molid>` 把"当前分子"切过去，之后不带 molid 的命令都作用于它。

**[实测] rep 设置可以读回来**（这条很关键，写脚本时常用来保存/恢复状态）：

```tcl
molinfo 0 get {{rep 1}}      ;# → {Isosurface 0.05 0 0 0 1 1}
```

⚠ **必须是双层花括号**。写 `{rep 1}`（单层）VMD 1.9.3 会报
`molinfo: cannot find molinfo attribute '1'`。原因：VMD 要的属性名**字面上**是
带花括号的 `{rep 1}`，而单层花括号在 Tcl 里是"分组"，传过去只剩 `rep 1`。
所以读出来的形态是"一个元素的列表，里面是 样式名 + 全部位置参数"：

```tcl
set st    [molinfo 0 get {{rep 1}}]      ;# {{Isosurface 0.05 0 0 0 1 1}}
set inner [lindex $st 0]                 ;# {Isosurface 0.05 0 0 0 1 1}
set iso   [lindex $inner 1]              ;# 0.05  ← 等值面值
```

---

## 3. vcube 的样式机制：`.stl` = 一个固定签名的 proc

这是整个 vcube 里最值得学的一招。**每个样式文件只定义一个 proc，名字固定**：

```tcl
# styles/sob-art.stl
proc ::vcube::Vapply_style {m_name} {
    light 0 on ; light 2 off
    display shadows off
    color Display Background white
    display projection Orthographic
    display rendermode GLSL
    if {[lsearch [material list] ${m_name}a] < 0} {material add ${m_name}a}
    set mprop  {ambient diffuse specular shininess mirror opacity outline outlinewidth transmode}
    set mvalue {0.1     0.6     1.0      1.0       0.0    0.75    0.0     0.0          1.0}
    foreach mp $mprop mv $mvalue {material change $mp ${m_name}a $mv}
    mol modmaterial 1 top ${m_name}a
    mol modcolor 1 top ColorID 12
    …
}
```

调度端（`vcube.tcl` 的 `vstyle`，357–413 行）：

```tcl
source [file join $style_dir $current_style]   ;# ← 仅仅 source，就"装载"了样式
foreach i $mol_id {
    mol top $i
    Vapply_style vcube$i                       ;# ← 用固定名字调用
}
```

**为什么这样能work**：`source` 会**覆盖**同名 proc，所以 `Vapply_style` 永远指向
"最后一次 source 的那个文件"。于是：

- 加样式 = 往 `styles/` 丢一个 .stl，**不用改 vcube.tcl 一行**；
- 样式文件第一行 `# 注释` 被 `vstyle`（无参数时）读出来当列表说明用；
- 样式文件里可以写任意 Tcl（循环、if、glob），不止是键值对——
  这是它比"配置格式"强的地方，也是比"配置格式"难维护的地方。

**`m_name` 参数 = 材质名隔离**。`Vapply_style vcube$i` 传进去的是 `vcube0` /
`vcube1`…，样式里就写 `${m_name}a` / `${m_name}b`（正/负相位两个材质）。
于是**每个 molid 有自己的材质实例，多分子同框时互不覆盖**。
`valpha` 也靠这个命名去改对应材质：

```tcl
material change opacity vcube${i}a $alpha_value     ;# 改"某分子的表面 a"的不透明度
```

> ## ⚠ `vstyle` 的两个坑（"sob-art 用不了"就是这个）
>
> `vstyle`（357–392 行）解析样式名的逻辑是：
>
> ```tcl
> variable surface_type
> if {$surface_type == "map"} {        # 367 行：先读，再决定扩展名
>     set ext .mstl
> } elseif {$surface_type == "norm"} {
>     set ext .stl
> }
> ...
> if {[file exists [file join $style_dir $style_name]] == 1} {
>     set full_name $style_name                      # ① 原样（带扩展名时命中这条）
> } elseif {[file exists [file join $style_dir $style_name$ext]] == 1} {
>     set full_name $style_name$ext                  # ② 补扩展名
> } else {
>     puts "$style_name not found in $style_dir"     # ③ 静默失败，什么也不做
> }
> ```
>
> **坑 1 —— 在 ESP(map) 模式下打 `vstyle sob-art` 会失败。**
> 此时 `ext = .mstl`，于是去找 `styles/sob-art.mstl` —— 而 `styles/` 里只有
> `sob-esp0.mstl` / `sob-esp1.mstl` 两个 `.mstl`，**没有 `sob-art.mstl`**，
> 于是走到 ③：打印一句 `sob-art not found in ...` 就结束了，样式完全没变。
> 反过来在普通模式（`ext = .stl`）下打 `vstyle sob-esp0` 同样失败
> （去找不存在的 `sob-esp0.stl`）。
> **解法：把扩展名写全 —— `vstyle sob-art.stl`**，走 ① 这条分支，与当前模式无关。
> vcube 自己的帮助（108 行）和 `vcube` 函数（254 行）都是这么写的。
>
> **坑 2 —— 从没跑过 `vcube` / `vmol` 时，`vstyle` 直接报 Tcl 错误。**
> 命名空间初始化那里（49 行）写的是：
>
> ```tcl
> variable suface_type ""   # ← 少了一个 r！注释还写着 "normal or map"
> ```
>
> 于是 `surface_type` **从未被初始化**。而 `vstyle` 在 367 行第一件事就是读它，
> 一旦你 source 完 `vcube.tcl` 就直接打 `vstyle sob-art.stl`，得到的是
> `can't read "surface_type": no such variable`，而不是"样式没找到"。
> 逃出来只有三条路：先跑一次 `vcube a.cub`（置 `norm`）或
> `vcube dens.cub map esp.cub`（置 `map`）、或者手动
> `set ::vcube::surface_type norm`。
> 注意 `Vnav_style`（460–473 行）**有**兜底：它发现变量不存在时，会去数当前分子
> 有几个 rep 来猜（1 或 3 → `norm`，2 → `map`）——`vstyle` 没有这个兜底。
>
> **附带结论：两套样式是互斥菜单。**
> `Vnav_style` 用键盘 n/p 翻样式时，map 模式只 glob `*.mstl`（2 个 ESP 样式），
> norm 模式只 glob `*.stl`（11 个普通样式）。所以 `sob-esp*.mstl` 和
> `sob-art.stl` 这类**永远不会出现在同一个列表里**——这不是 bug，是设计：
> 前者要求等值面按 Volume（静电势）着色，后者要求按两个相位各自配色，两者冲突。


---

## 4. 样式词汇表：13 个样式文件实测对照

`_vcube_style_audit.py` 把 13 个样式文件解析成表的结论——**它们只在 6 个维度上做区分**。

### ① 光照 / 阴影 / AO

| 样式 | 灯0 | 灯1 | 灯2 | 灯3 | shadows | AO | aoambient | aodirect | tachyon_options |
|---|---|---|---|---|---|---|---|---|---|
| sob-art | on | on | off | on | off | off | 0.8 | 0.3 | -trans_raster3d |
| ao-shiny | on | on | on | off | **on** | **on** | 0.8 | 0.3 | -trans_raster3d |
| ao-chalky | on | on | off | off | **on** | **on** | 0.8 | 0.3 | -trans_raster3d |
| morandi-* | on | on | on/off | on | off | off | 0.8 | 0.3 | -trans_raster3d |
| vmwfn0 | on | on | on | on | off | off | 0.8 | 0.3 | (空) |
| vmwfn1 / white-* | on | on | off | off | off | off | 0.8 | 0.3 | -trans_raster3d |
| sob-esp0/1 | on | on | on | on | off | off | 0.8 | 0.3 | -shadow_filter_* |

要点：**VMD 只有 4 盏灯**，样式之间就是"开哪几盏"。AO（`display ambientocclusion on`）
只在 `ao-*` 两个样式里开——因为**它慢**（vcube 的样式描述里直接标了 `AO(slow)`）。

### ② 显示设置（这一维度**几乎没用**）

13 个样式**全部**是：`bg=white`、`projection=Orthographic`、`rendermode=GLSL`、
`depthcue=off`。也就是说这套样式库是**为投稿出图定死的一套固定视角设定**，
不做"透视/雾化/深色底"的花样。

> `display rendermode GLSL` 是必须的：材质的高光/描边只有 GLSL 渲染模式才算得对，
> 老式内置渲染器（`display rendermode Normal`）不吃材质。

### ③ 材质（核心，见下节）

### ④ 表示 rep 布局：**约定俗成的固定分工**

```
rep 0  = CPK 原子球        mol modstyle 0 top CPK 0.6 0.4 30 30
rep 1  = 正相位等值面       mol modstyle 1 top Isosurface <iso> <vol> …
rep 2  = 负相位等值面       mol modstyle 2 top Isosurface <iso> <vol> …
```

`vcube.tcl` 的 `vcube` 函数就是照这个顺序建的（`mol addrep` 两次，分别 `modstyle 1` / `modstyle 2`），
样式文件里直接 `mol modmaterial 1 top …`、`mol modcolor 1 top …` 假设 rep 1/2 存在。
**样式与建分子的代码之间是隐式契约**——样式文件不能单独看懂，得配 `vcube` 一起看。

### ⑤ 配色：ColorID 31/32 的约定

12 个样式里有 11 个这么写：

```tcl
mol modcolor 1 top ColorID 31      ;# 正相位用 31 号色
mol modcolor 2 top ColorID 32      ;# 负相位用 32 号色
color change rgb 31 0.760000 0.720000 0.650000   ;# 再改 31 号的 RGB
color change rgb 32 0.470000 0.490000 0.520000
```

VMD 的颜色是**固定的 33 个槽位（0–32）**，不能新增，只能改 RGB。
槽位大致是「0–16 基础色 + 17–32 各色的 2/3 号变体」，
**[实测]** 本机 31 号 = `(0.89, 0.35, 0.0)`、32 号 = `(0.96, 0.72, 0.0)`
（就是内置的 orange2 / orange3）。

"元素颜色"不是独立的一套色，而是一张**元素 → 槽位**的映射表
（**[实测]** 默认 `C→cyan`、`H→white`、`N→blue`、`O→red`、`S→yellow`、
`F/Cl/Br/I/B→ochre`、`P→tan`）。所以 `color Element C gray` 是"把 C 指到 gray 槽"，
`color change rgb gray …` 才是"改 gray 槽本身"。

样式们统一占用**最高的两个槽 31/32** 当正/负相位色，好处是：
**改它不会碰到元素配色**（元素用的是 0–17 那批），而且换样式只需要重定义这两个槽，
`mol modcolor 1/2 top ColorID 31/32` 那两行都不用重写。

例外：`sob-art` 直接用内置色 `ColorID 12`(lime) / `ColorID 22`(cyan3)；
两个 `.mstl`（ESP 映射）用 `mol modcolor 1 top Volume 1` + `color scale method BWR`
走**体积色标**而不是单色。

### ⑥ 体积色标：VMD 只认 6 个枚举（实测）

`color scale method` **不是**「给我一个色标名」，而是一个**固定枚举**。在本机
VMD 1.9.3 上逐个试过，**只有这 6 个被接受**：

| 方法 | 观感 |
|---|---|
| `BWR` | 蓝 → 白 → 红 |
| `RWB` | 红 → 白 → 蓝 |
| `RGB` | 红 → 绿 → 蓝（彩虹，中间过绿） |
| `BGR` | 蓝 → 绿 → 红 |
| `RWG` | 红 → 白 → 绿 |
| `BWG` | 蓝 → 白 → 绿 |

实测被拒（`color scale method 'XX' not recognized`）：`RG`、`GB`、`Gray`、
`WG`、`RGW`、`BGRW`、`BWRG`，以及 `jet`/`coolwarm`/`viridis`/`RdBu`/`spectral`
等 matplotlib 名字。**VMD 不支持任意色标**，所以想让 VMD 侧的 ESP 配色和画布
完全一致是做不到的，只能在上面 6 个里挑最接近的。

配套子命令（同一条 `color scale` 家族）：
`color scale method <m>` / `color scale midpoint <v>` / `color scale min <v>` /
`color scale max <v>`。其中 `midpoint` 决定双色标的白点落在哪 —— ESP 想让 0
落在白色就必须配 `mol scaleminmax` 把范围取对称（本程序发的是 `-0.03 0.03`）。

本程序的做法（**画布与 VMD 的配色已彻底解耦**）：

- **ESP 面板的「配色」下拉只管 OpenGL 画布**（16 种 matplotlib 配色 +
  「反转」勾选），**不再传给 VMD**。面板登记 VMD 场景时只写 `kind="esp"`。
- **VMD 侧的色标在「VMD 控制台」里单独选**（`VMD 色标:` 下拉，就是上面那 6 个
  方法，默认 `BWR`）。主窗口收集场景时把它注入到 `kind=="esp"` 的表面；
  VMD 正在运行时改它**即时生效**（立刻发 `color scale method X`），
  各 rep 的数值范围（`mol scaleminmax`）不变。
- 两边不再有映射关系 —— `esp_panel._vmd_cmap_name()` 那套「画布配色 → VMD 方法」
  的折叠逻辑（BWR/Coolwarm/RdBu→`BWR`，RWB/IceFire→`RWB`，Jet→`RGB`）已不再
  参与 ESP 的同步。想直接用某个方法，也可以在 VMD 的 TkConsole 里手打
  `color scale method RWG`。
- **IGMH 不受影响**：它走自己的 `kind="igmh"` + `BGR` 约定（sign(λ₂)ρ 的
  diverging 色标），不会被 VMD 控制台的设置覆盖。

配套常量：`fchk_orbital.VMD_CMAP_METHODS = ("RGB","BGR","RWB","BWR","RWG","BWG")`
是这 6 个方法的**单一来源**，两处白名单与控制台下拉都引用它。

### 球棍模型也跟样式走（ESP / IGMH 的 `bgr` 分支）

`_scene_tcl()` 的 `bgr` 分支（ESP / IGMH 走这条）原先**原子那几行是残缺的**：
只写了 `mol modmaterial 0 top _stl_atom`（但 `_stl_atom` 从没被 `material add`
定义过 → VMD 回落默认 `Opaque`）和裸的 `mol modcolor 0 top Element`
（→ VMD 自带元素色表）。所以 ESP 场景里球棍是「VMD 默认材质 + 默认配色」。

现在补齐成与 `orbital` 分支同构的四件事，**全部取自 VMD 控制台选中的样式**：

| 项 | 取自 |
|---|---|
| 球半径 / 键半径 | `STYLES[style]["atom_cpk"]`（CPK 四参数） |
| 球与键的材质 | `mat_atom` → `material add _stl_atom` + 9 个 `material change` |
| 元素配色 | `ATOM_COLORS`（ColorID 101–175 的 GaussView 配色） |
| 碳色 | `color Element C {c_color}` + `color change rgb {c_color} {c_rgb}` |

`scene["atom_color"]` 仍然生效：`"Element"`（默认，本程序色表）或 `"Name"`
（VMD 自带 Name 配色，ESPViewer2 的做法）。ESP 面板已不再强制 `"Name"`，
所以默认就是跟样式走。

**实时切样式**也顺带换半径：`_live_style_tcl(..., atom_cpk=…)`。但这个形参
**只能由调用方在确认 rep 0 是 CPK 原子 rep 时才传** —— MPP 的 `pqr` 场景
rep 0 是 `VDW 0.25` + Charge 着色，硬设成 CPK 会改坏画面；主窗口用
`_vmd_atom_rep_is_cpk()` 判断（遇 `type=="pqr"` 传 `None` 跳过）。

原子配色统一是 `mol modcolor 0 top Element` + 逐元素覆盖，例如：

```tcl
color Element C tan
color change rgb tan 0.700000 0.560000 0.360000   ;# tan 槽位改成暖灰棕
color Element H white
color Element Cl yellow3
color change rgb 18  0.500000 1.000000 0.000000   ;# 18 号（=Cl 的元素槽）改亮绿
```

> 元素名（`C`/`H`/`Cl`…）和颜色名（`tan`/`white`/`yellow3`…）都是 VMD 内置表；
> `color change rgb <名字或编号> r g b` 两种写法都行。

### ⑥ Tachyon 渲染选项

样式文件里用一行 `set tachyon_options "-trans_raster3d"` 声明，`vrender` 再拼成
完整命令行。**[实测]** `render options Tachyon` 在本机返回的模板是：

```
"...\tachyon_WIN32.exe" -aasamples 12 %s -format BMP -o %s.bmp
```

`vrender` 的做法是把它抠出来，再拼自己的 `-res WxH -numthreads N <tachyon_options>`，
**为每个 molid 生成一行**写进 `renderall.bat`，最后整体调用一次批处理。

---

## 5. 材质：9 个属性，样式的"手感"全在这里

```tcl
material add  <名字>                      ;# 新建（同名则跳过：if {[lsearch [material list] …] < 0}）
material change <属性> <名字> <值>
mol modmaterial <rep> <molid> <名字>      ;# 把这个材质挂到某个表示上
```

| 属性 | 含义 | 典型手感 |
|---|---|---|
| `ambient` | 环境光占比 | 调大 → 暗部发灰、立体感变弱 |
| `specular` | 高光强度 | 调大 → 亮点更亮（`sob-art` 表面用 1.0） |
| `diffuse` | 漫反射强度 | 调小 → 整体变暗 |
| `shininess` | 高光锐度 | 调大 → 高光更集中、更"塑料" |
| `mirror` | 镜面反射 | 调大 → 反光带（原子球常用 0.15） |
| `opacity` | **不透明度** | 表面透明度的正主（见下） |
| `outline` | 描边 | 调大 → 物体外沿一圈黑边 |
| `outlinewidth` | 描边宽度 | 与上一条配套 |
| `transmode` | 透明混合模型 | 与 `tachyon_options` 的 `-trans_*` 配套 |

**[实测] 读取顺序的坑**：`material settings <名字>` 返回 9 个数，**顺序不是**
样式文件里写的那个，而是：

```
ambient  specular  diffuse  shininess  mirror  opacity  outline  outlinewidth  transmode
  0         1         2         3         4        5        6          7           8
```

（实测：设 ambient=0.11 / diffuse=0.22 / specular=0.33，回读得到
`0.11 0.33 0.22 …` —— 第 1 位是 specular、第 2 位才是 diffuse。）

**写的时候不用担心**：`material change <属性名> <材质> <值>` 是**按名字**赋值的，
样式文件里 `mprop {ambient diffuse specular …}` 的顺序只是它自己的书写习惯。
**只有按位置读** `material settings` 时才必须用上面那个顺序——
vcube 的 `valpha` 读 `[lindex … 5]` 拿 opacity，索引 5 在两种顺序下都正好是 opacity，
所以侥幸没出错。

**[实测] VMD 内置 23 个材质**，可以直接 `mol modmaterial 1 top <名字>`，
也可以用样式文件那种"自建 + 覆盖"的方式：

```
Opaque Transparent BrushedMetal Diffuse Ghost Glass1 Glass2 Glass3 Glossy
HardPlastic MetallicPastel Steel Translucent Edgy EdgyShiny EdgyGlass Goodsell
AOShiny AOChalky AOEdgy BlownGlass GlassBubble RTChrome
```

（vcube 的 `ao-shiny` / `ao-chalky` 命名显然就是对着 `AOShiny` / `AOChalky` 去的。）

**透明度为什么改材质而不是改 rep**：等值面 rep 自己没有"整体透明度"参数，
透明度属于**材质**。所以 vcube 的 `valpha` 长这样：

```tcl
proc ::vcube::valpha {{alpha_value ""} args} {
    …
    material change opacity vcube${i}a $alpha_value     ;# 正相位表面
    material change opacity vcube${i}b $alpha_value     ;# 负相位表面
}
```

好处：一次改两个相位、所有分子统一；代价：一个材质只能有一个透明度，
想让正负相位透明度不同就得建两个材质。

---

## 6. `mol modstyle` 的位置参数

**CPK**（原子球）4 个参数：

```tcl
mol modstyle 0 top CPK 0.6 0.4 30 30
#                        │   │   │  └ 键的圆柱分辨率
#                        │   │   └─── 球的分辨率
#                        │   └─────── 球半径倍率
#                        └─────────── 球半径
```

**Isosurface**（等值面）6 个参数。**[实测]** 第 2 个是 **volume（数据集编号）**：
传 `… Isosurface 0.05 11 …` 时 VMD 直接报 `No volume data loaded at index 11`。

```tcl
mol modstyle 1 top Isosurface 0.05 0 0 0 1 1
#                            │    │ │ │ │ └ ┐
#                            │    │ │ │ │   └ 后四位：vcube 与本程序都写 0 0 1 1
#                            │    │ │ │ └────┘
#                            │    └─┴─┴────── [手册] 手册列为 Data Set / Isovalue /
#                            │                Draw / Boundary / Step / Size 六项
#                            └────────────── 等值面值
```

**[手册]**（[VMD User's Guide · Isosurface](http://calgary.ks.uiuc.edu/Research/vmd/vmd-1.8.6/ug/node68.html#4230)）
Isosurface 的设置项是：Data Set、Isovalue、Draw（Points / Shaded Points / Wireframe /
Solid Surface）、Boundary、Step、Size。

> 诚实说明：我只**实测确认了前两位**（isovalue、volume）。后四位的顺序是手册列的
> 那四项，但 VMD 对多传的参数是"存下来不报错"（实测传 6 个它原样存 6 个），
> 所以"第几位对应哪个"没法靠报错反推。**想确认就自己读回来**：
> 改一个位置 → `molinfo 0 get {{rep 1}}` → 看画面/render 结果有没有按预期变。

---

## 7. vcube 的批量出图流水线

```
vcube dens*.cub            ← 入口：每个 cub 一个 molid，各加 rep1/rep2 等值面
  └ vstyle sob-art.stl     ← source + 逐 molid 调 Vapply_style
  └ vgroup                 ← 按文件名分组（同名不同编号归一组）
vc 3                       ← "只看 3 号"：mol free/on 切一个出来
valpha 0.7                 ← material change opacity vcube3a/b 0.7
viso 0.03 -0.03            ← mol modstyle 1/2 … Isosurface
vrender _moh 4             ← 逐个 molid：display resize 4 倍 → render Tachyon x.dat
                             + 生成 renderall.bat/.sh → 调 tachyon → .bmp
```

`vshowalways`（823 行）是"某几个分子永远显出来"的开关（比如只看等值面时把骨架留住），
`Vnav_mol/iso/alpha/cscale/mscale` 是键盘快捷键（`n`/`p` 上一个下一个），
`Vgroup` 让整组一起动。这套"分子列表 + 分组 + 键盘导航"是它"high throughput"的来源。

---

## 8. 对照：本程序（GXNU MolStudio）的做法

本程序**没有用 .stl 那套**，而是把同一件事拆成三段：

| 环节 | vcube | 本程序 |
|---|---|---|
| 样式数据 | `styles/*.stl`（Tcl 代码） | `fchk_orbital.STYLES`（Python dict） |
| 生成命令 | `source` 样式文件 | `_scene_tcl()` 按 dict 生成 Tcl 字符串 |
| 怎么送到 VMD | 用户手动 `vmd -e vcube` | `subprocess` 起 `vmd -e _sync.tcl` |
| 实时改参数 | 无（改完重跑） | **socket 服务器**：Python 发一行 Tcl，VMD `uplevel #0` 执行 |
| 窗口 | 用户自己开 | `vmd_embed.py` 用 Win32 `SetParent` 把 VMD 窗口嵌进 Qt |

**样式字典的字段几乎一一对应 vcube 的样式文件**：

```python
"sob-art": {
    "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},   # ← light N on/off
    "shadows": "off", "ao": "off",
    "aoambient": "0.8", "aodirect": "0.3",
    # Material: ambient, diffuse, specular, shininess, mirror, opacity,
    #           outline, outlinewidth, transmode      ← 就是那 9 个属性
    "surface_mat": [0.1, 0.6, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0],
    "pos_color": [12, None, None],      # ← mol modcolor 1 top ColorID 12
    "neg_color": [22, None, None],
    "atom_cpk": "0.600000 0.400000 30.000000 30.000000",   # ← CPK 的 4 个参数
    "atom_mat": [0.0, 0.65, 0.5, 0.53, 0.15, 1.0, 2.0, 0.3, 0.0],
    "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
}
```

> **覆盖情况核对**：vcube 的 13 个样式文件在本程序 `STYLES` 里**都有对应项**
> （`_style_coverage_audit.py` → **13/13**）。其中 11 个 `.stl` 是相位配色的普通样式；
> 2 个 `.mstl`（`sob-esp0` / `sob-esp1`）在 vcube 里是**体着色**样式——
> 它们不写 `mol modcolor 1 top ColorID …`，而是
> `mol modcolor 1 top Volume 1` + `color scale method $color_scale`
> 把静电势体积数据映射成红-白-蓝。
>
> 本程序用一个**独立的 `volume_color` 键**表达这件事，而不是硬塞进相位色：
>
> ```python
> "volume_color": {"cmap": "BWR", "cmin": -0.03, "cmax": 0.03},
> ```
>
> 它的语义是「这个样式要按体积数据连续着色」。三处消费者：
>
> | 位置 | 行为 |
> |---|---|
> | 画布 `_glwidget.set_style` | 有 ESP 顶点色表面时把色彩刻度轴设成 BWR / ±0.03 a.u.；没有则一律不动色标 |
> | `_live_style_tcl`（VMD 实时切样式） | 传 `vol_color=True` 时**不发 ColorID**，改发 `color scale method` + `mol scaleminmax` |
> | ESP 面板的 `bgr` 路径 | 体着色本身（`mol modcolor … Volume`）照旧由它负责 |
>
> **为什么不发 ColorID 是关键**：`mol modcolor <rep> top ColorID N` 会把该 rep 的
> 着色方式从 `Volume` 改成固定色，等于把静电势表面拍平成一整块颜色。所以
> 「体着色场景 + ESP 样式」这一组合下必须跳过相位色那几行。
> 逐字段对照脚本：`_style_equivalence_audit.py`（结论：真差异 0 处）；
> 接线校验：`_esp_volume_style_probe.py`。

**socket 服务器**（`_socket_server_tcl`）是本程序比 vcube 强的地方，
也是"VMD 控制台"的实现基础：

```tcl
set serverSocket [socket -server _vmd_accept -myaddr 127.0.0.1 <port>]
proc _vmd_accept {chan addr port} {
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _vmd_handle $chan]
}
proc _vmd_handle {chan} {
    if [eof $chan] { close $chan; return }
    gets $chan cmd                       ;# 读一行
    if [catch {uplevel #0 $cmd} err] {   ;# ★ 在全局作用域执行
        puts $chan "ERROR: $err"
    } else {
        puts $chan "OK"
    }
    flush $chan
}
```

要点：
- **`uplevel #0 $cmd`** 是全部威力所在——Python 端发什么字符串，VMD 就当顶层命令执行，
  于是**任何** VMD 命令都能远程调用（本质上是个远程 Tcl 控制台）。
- 回一个 `OK` / `ERROR: …` 当同步信号，Python 端 `sendall` 后 `recv` 就知道成没成。
- 本程序实际发的是：
  `mol modstyle {rp} top Isosurface {iso} {vol} 0 0 1 1`（`main_window.py` 里翻转相位/改 iso 就是这条）。

**`vmd_embed.py`** 则是另一条路：`subprocess` 起 VMD → 枚举它进程的顶层窗口
（`VMD 1.9.3 OpenGL Display` / `VMD Main` / `VMD TkConsole`）→ `SetParent` 嵌进 Qt。
它和 socket 是互补的：**socket 管命令，SetParent 管窗口**。

---

## 9. 可以借鉴什么（针对本程序）

1. **样式文件里的"自建材质 + 按分子编号命名"值得抄（目前还没咬到，但是个隐患）**。
   本程序用的是固定名 `_stl_a`/`_stl_b`/`_stl_atom`/`_stl_bgr`，
   而 `aim_visualize.py` 已经会**在同一个 VMD 会话里 `mol new` 三次**
   （cps / paths / mol 三个 pdb）。目前那三个分子只用内置 VDW/CPK + ColorID，
   不碰 `_stl_*`，所以没出问题；但一旦想让"某个分子单独调透明度/材质"，
   固定名就做不到——`_scene_tcl` 里的透明度覆盖就是
   `for m in ("_stl_a", "_stl_b", "_stl_bgr", "EdgyGlass")` 一把全改。
   vcube 的 `vcube<molid>a` 命名天然支持按分子区分。

2. **31/32 号颜色槽的约定值得抄**。本程序 `pos_color`/`neg_color` 用的是
   `[cid, r, g, b]` 显式带编号，能自定义；但没有"固定占 31/32"的约定，
   不同样式可能挑到不同的位（`sob-art` 用 12/22，其余多用 31/32），
   混用两套样式时正/负相位色的来源就不一致。统一占 31/32 会更稳。

3. **`gradient`/`outline` 这类"一个属性一个台阶"的观感，
   在 VMD 里比在自己的 GL 渲染器里更容易做出差异**——因为
   `outline` + `outlinewidth` 是材质自带功能，不用自己写描边着色器。

4. **vcube 的"样式 = 一个 proc"设计**如果要用，注意它的代价：
   `source` 会执行任意 Tcl，样式文件等于**可执行代码**，
   从网上下载的 .stl 有不安全风险；调试时也难知道"到底哪一行改了参数"。
   本程序用 Python dict 换来了可校验、可 diff、可 JSON 往返（见
   「样式 保存/载入」），这个取舍是对的。

5. **`molinfo get {{rep N}}` 双层花括号**这条记住，
   想在 VMD 控制台里"读出当前等值面值/当前材质"时会用到。

---

## 附：复现实验

| 脚本 | 干什么 |
|---|---|
| `_vcube_style_audit.py` | 解析 13 个 .stl/.mstl，输出光照/材质/配色/rep 对照表 |
| `_vmd_rep_probe.tcl` | 确认 `molinfo get {{rep N}}` 语法 + Isosurface 位置参数（volume 在第 2 位） |
| `_vmd_vocab_probe.tcl` | 确认 material 9 属性顺序、23 个内置材质、Tachyon 选项模板 |

跑法（VMD 已装在 `C:\Program Files (x86)\University of Illinois\VMD`）：

```powershell
& "C:\Program Files (x86)\University of Illinois\VMD\vmd.exe" `
  -dispdev text -e _vmd_rep_probe.tcl
python _vcube_style_audit.py <vcube2.0 目录>\styles
```
