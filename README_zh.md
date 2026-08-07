<p align="center">
  <img src="https://img.shields.io/badge/version-5.3-blue.svg" alt="Version 5.3">
  <img src="https://img.shields.io/badge/python-3.8+-green.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/license-GPLv3-blue.svg" alt="GPLv3 License">
</p>

<h1 align="center">OrbitalViewer（轨道查看器）</h1>

<p align="center">
  <b>Multiwfn → VMD → Tachyon 一键串联，从 fchk 到期刊精美轨道图，两分钟搞定。</b>
  <br>
  <sub>侯成课题组 · 广西师范大学</sub>
</p>

<p align="center">
  <a href="./README.md">English / 英文版</a>
</p>

---

## 为什么选择 OrbitalViewer？

传统的轨道可视化流程需要手动操作 Multiwfn 生成 cube，再用 VMD 加载、调参、渲染，步骤繁琐且容易出错。OrbitalViewer 将整个流程自动化封装，提供直观的 GUI 和 30+ 种预置渲染风格，让你专注于科研本身。

| | 传统流程 | OrbitalViewer |
|---|---|---|
| cube 生成 | 手动输命令 | 双击轨道自动生成 |
| VMD 预览 | 手动 load、调等值面 | 自动加载，滑块实时调整 |
| 渲染出图 | 手动调灯光、材质 | 下拉选风格，一键出图 |
| 批量处理 | 逐个文件重复操作 | 拖入文件夹，全自动批处理 |
| 双语支持 | — | 中 / English 即时切换 |

---

## 功能特性

### 🧬 智能文件加载
- **拖放即用** — 支持 `.fchk`、`.log`、`.out`、`.cub`、`.cube`、`.xyz`，自动识别文件类型
- **自动成键** — 导入结构后自动计算化学键，2D 画布实时预览

### 📊 轨道浏览器
- **双标签布局** — 开壳层 α/β 电子自动分标签紧邻排列
- **占据态可视化** — ⬆️⬇️ 双占据 / ⬆️ α 单电子 / ⬇️ β 单电子 / ⬜⬜ 空轨道
- **完整信息展示** — 轨道编号、能量 (a.u.)、能量 (eV)、占据数
- **双击即生成** — 双击任意行，自动调用 Multiwfn 生成 cube 并发送至 VMD

### 🎬 VMD 实时预览
- **等值面滑块** — 拖动滑块，VMD 中等值面实时同步（0.01 ~ 0.10）
- **透明度控制** — 独立调整正/负相等值面透明度
- **多轨道同时显示** — 支持同时加载多条轨道，各自独立配色
- **一键隐藏氢原子** — 突出重原子骨架，可保留指定 H

### 🎨 30+ 内置渲染风格

| 类别 | 风格 | 数量 |
|------|------|:---:|
| **vcube2.0（钟成）** | sob-art, ao-shiny, ao-chalky, white-green, white-red, morandi-blue, morandi-green, morandi-orange, morandi-red, vmwfn0, vmwfn1, IQmol | 12 |
| **IboView 风格** | iboview-crystal, iboview-dark, iboview-green-pink, iboview-purple-blue, iboview-cyan-yellow, iboview-orange-teal, iboview-rainbow | 7 |
| **原创精选** | aurora-teal, midnight-gold, lavender-mint, sunset-fire, ocean-depth, rose-quartz, forest-emerald, neon-cyber, cherry-blossom, graphite-ink, lakers, blood-orange, Gaussview | 13+ |

### 🖼️ Tachyon 光线追踪渲染
- **4 种渲染模式** — Solid, CPK, Sob-Multi, Sob-Art
- **高分辨率输出** — 支持 BMP/PNG，分辨率可达 3000+
- **可选透明背景** — 便于后期排版拼接
- **阴影控制** — 开关阴影、AO（环境光遮蔽）
- **Tachyon 路径自定义** — 支持选择任意版本的 Tachyon 渲染器

### ✏️ 虚线绘制工具
- **一键锁定原子对** — 画布与 VMD 同步绘制虚线键
- **8 种颜色 + 5 种线型** — 圆点、虚线、圆柱、锥形、线段，下拉即时生效
- **标注氢键与分子间相互作用**

### 🔄 高级叠加模式
- 选中两条轨道，同步生成 cube 并叠加渲染
- 方便对比 HOMO/LUMO 或不同等值面阈值

### 📦 批量处理
- 拖入文件夹，自动遍历所有 fchk 文件
- 支持命令行批处理，可自定义轨道、风格、分辨率

### 🌐 中英双语
- UI 即时切换，无需重启
- 完整覆盖所有界面文字与提示

### 📋 运行日志
- 16px 等宽字体，彩色标签（`VMD` / `OK` / `ERR` / `GEN`）
- 带时间戳，可复制导出

---

## 快速开始

### 环境要求

| 组件 | 用途 | 安装 |
|------|------|------|
| Python 3.8+ | 运行环境 | [python.org](https://www.python.org/) |
| PyQt5 | GUI 界面 | `pip install PyQt5` |
| NumPy | 数值计算 | `pip install numpy` |
| [Multiwfn](http://sobereva.com/multiwfn/) | fchk → cube | 下载后配置路径 |
| [VMD](https://www.ks.uiuc.edu/Research/vmd/) | 3D 预览 + 渲染 | 安装后配置路径 |
| Tachyon | 光线追踪 | 随 VMD 附带 |

### 安装

```bash
git clone https://github.com/houcheng-gxnu/OrbitalViewer.git
cd OrbitalViewer
pip install PyQt5 numpy
```

### 配置工具路径

首次启动时在 GUI 中浏览选择，或手动编辑 `fchk_orbital.ini`：

```ini
[paths]
multiwfn = E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe
vmd      = C:\Program Files (x86)\University of Illinois\VMD\vmd.exe
tachyon  = C:\Program Files (x86)\University of Illinois\VMD\tachyon_WIN64.exe
```

> **提示**：Multiwfn 和 VMD 均可通过 GUI 设置界面浏览选择路径，配置自动保存。

### 启动

```bash
# GUI 模式（默认中文）
python main.py

# 英文界面 — 启动后从菜单切换 Language / 语言 → English
```

### 命令行模式

```bash
# 单个文件，HOMO 轨道，soba 推荐风格
python main.py input.fchk --mo h --iso 0.05 --style sob-art

# 批量处理文件夹，HOMO + LUMO
python main.py ./fchk_folder/ --mo h,l --iso 0.05

# 指定轨道、风格、高分辨率
python main.py input.fchk --mo h-1,h,l,l+1 --iso 0.04 --style lakers --res 3000,2250

# 仅生成 cube，不渲染（用于调试）
python main.py ./folder/ --mo h --grid 3 --no-render
```

### 命令行参数详解

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input` | str | — | fchk 文件路径或文件夹路径 |
| `--mo` | str | `h` | 轨道选择，支持：`h` (HOMO), `l` (LUMO), `h-1` (HOMO-1), 数字编号, 逗号分隔多项 |
| `--iso` | float | `0.05` | 等值面阈值 |
| `--grid` | int | `2` | 网格质量：1=低, 2=中, 3=高 |
| `--style` | str | `sob-art` | 渲染风格，可选值见 `fchk_orbital.py` 中 `STYLES` 字典 key |
| `--res` | str | `2000,1500` | 输出分辨率 `宽,高` |
| `--no-render` | flag | — | 仅生成 cube 文件，不渲染出图 |
| `--out` | str | 输入同目录 | 输出目录 |

---

## 项目结构

```
OrbitalViewer/
├── main.py                # 入口模块（GUI 启动 + 命令行批处理）
├── main_window.py         # 主窗口（UI 布局、信号/槽交互逻辑）
├── molcanvas.py           # 2D 分子结构画布（Qt 自定义 QPainter 绘制）
├── fchk_orbital.py        # 后端核心引擎（cube 生成、VMD 控制、Tachyon 渲染管道、30+ 风格定义）
├── fchk_parser.py         # fchk 文件解析（提取轨道能量、占据数等）
├── orbital_viewer_lib.py  # 共享工具函数库
├── orbital_viewer_v53.py  # 旧版兼容层
├── cub_viewer.py          # OpenGL 渲染引擎（深度剥离 + Phong 光照，IboView 风格）
├── cub_canvas.py          # 球棍模型 / 等值面画布控件
├── color_wheel.py         # 色轮配色控件
├── orbital_gl_widget.py   # OpenGL 窗口部件
├── glsl_shaders.py        # GLSL 着色器源码
├── marching_cubes.py      # Marching Cubes 等值面提取
├── esp_viewer.py          # ESP 势视图
├── workers.py             # QThread 后台工作线程（异步 cube 生成与渲染）
├── widgets.py             # 自定义 QSS 控件（滑块、组合框、按钮等）
├── dialogs.py             # 对话框（设置、关于、路径配置）
├── i18n.py                # 国际化翻译模块（中/English 字典）
├── theme.py               # QSS 主题样式表
├── OrbitalViewer.spec     # PyInstaller 打包配置
└── README.md
```

---

## 打包为独立 EXE

无需安装 Python 即可运行，适合分发给非技术用户。

```bash
pip install pyinstaller
pyinstaller OrbitalViewer.spec --clean
```

输出：`dist/OrbitalViewer.exe`（单文件，无控制台窗口）

---

## 致谢

OrbitalViewer 站在巨人的肩膀上：

- **[Multiwfn](http://sobereva.com/multiwfn/)** — 卢天老师开发的量子化学波函数分析程序，引用超 4 万篇论文。OrbitalViewer 使用其从 fchk 生成 cube 文件。
- **[vcube2.0](https://github.com/Zhong-Cheng-2020/vcube2.0)** — 钟成提供的 11 套精美 VMD 轨道渲染配置，大部分内置风格来自 vcube2.0。
- **[VMD](https://www.ks.uiuc.edu/Research/vmd/)** — Humphrey, W., Dalke, A. and Schulten, K., "VMD: Visual Molecular Dynamics", J. Molec. Graphics, 1996, 14, 33–38.
- **[Tachyon](http://jedi.ks.uiuc.edu/~johns/raytracer/)** — Stone, J. E., "An Efficient Library for Parallel Ray Tracing and Animation", M.Sc. Thesis, 1998.
- **虚线绘制** — 来自 KeinSci 论坛 Eming 的 `draw_bond` Tcl 脚本。
- **[IboView](https://www.iboview.org)** — Gerald Knizia 开发的量子化学可视化程序。本项目的 OpenGL 渲染引擎（深度剥离透明合成、三向 Phong 光照、球棍模型几何与原子半径/颜色表）参考并部分移植自 IboView（Copyright (c) 2015 Gerald Knizia, GPLv3），特此致谢。

---

## 引用

如果 OrbitalViewer 对你的研究有帮助，请在论文中引用：

```bibtex
@software{OrbitalViewer2026,
  title        = {OrbitalViewer: A Molecular Orbital Isosurface Visualization Tool},
  author       = {Hou Cheng},
  year         = {2026},
  version      = {5.3},
  url          = {https://github.com/houcheng-gxnu/OrbitalViewer},
}
```

同时请引用上述致谢中的对应工具文献。

另见 [CITATION.cff](./CITATION.cff) 和 [CITATION.bib](./CITATION.bib)。

---

## 许可证

本项目作为 IboView 的衍生作品，依 **GNU General Public License v3 (GPLv3)** 发布，详见 [LICENSE](./LICENSE) 文件。

---

<p align="center">
  <sub>Made with ❤️ by Hou Cheng Research Group @ Guangxi Normal University</sub>
</p>
