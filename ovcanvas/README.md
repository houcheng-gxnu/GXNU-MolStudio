# ovcanvas — OrbitalViewer 画布可视化库

将 OrbitalViewer 的 OpenGL 画布（等值面 + 球棍模型渲染，IboView 移植管线：
depth peeling 透明合成 + 三向 Phong 光照）封装为可复用包。

## 依赖

- Python 3.8+
- PyQt5
- PyOpenGL（`pip install PyOpenGL PyOpenGL_accelerate`）
- NumPy
- 项目级共享模块（需随包一起放置，或加入 `PYTHONPATH`）：
  - `fchk_orbital.py`（样式表 `STYLES`、元素符号）
  - `marching_cubes.py`（cube 解析与等值面生成）

> 把 `ovcanvas/` 目录连同 `fchk_orbital.py`、`marching_cubes.py` 一起拷到你的项目即可，
> 无需安装，直接 `import ovcanvas`。`export_image` 等需要真实 OpenGL 上下文，
> 须在带 GUI 的 Qt 应用（或 `QApplication`）中调用，纯 offscreen 环境下导出会失败。

## 快速开始

```python
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from ovcanvas import OVCanvas

app = QApplication(sys.argv)
win = QMainWindow()
central = QWidget()
win.setCentralWidget(central)
layout = QVBoxLayout(central)

canvas = OVCanvas()          # 即 CubCanvasPanel，含画布 + 参数区 + 色轮
layout.addWidget(canvas)

# 加载 .cub 文件
canvas.load_cube_files(["H2O_orb1_pos.cub"])   # 单文件：正负相位同色
# 或 canvas.load_cube_files(["x_pos.cub", "x_neg.cub"])  # 双文件：正负分离配色

# 渲染参数（也可在 UI 里手动调）
canvas.set_positive_color("#ff2222")   # 正相位颜色 (#rrggbb 或 (r,g,b))
canvas.set_negative_color("#2222ff")   # 负相位颜色
canvas.set_iso(0.03)                    # 等值面阈值（绝对 a.u.）
canvas.set_transparency(0.85)           # 透明度 0–1
canvas.set_render_quality("high")       # low / medium / high
canvas.set_mol_style_name("Ball and Stick")  # 球棍 / 飘带 / 仅球 等
canvas.set_shininess_name("reasonably shiny")  # 光泽预设
canvas.set_background_color("#ffffff")  # 背景色

win.show()
sys.exit(app.exec_())
```

## 一键出图

```python
canvas.export_image("output.png", dpi=600.0)   # 离屏高分渲染到文件
# 也可用 UI 里的「导出 PNG」按钮 / screenshot()
```

## 对外 API（摘要）

| 符号 | 说明 |
| --- | --- |
| `OVCanvas` | 统一入口，**= `CubCanvasPanel`**，可直接嵌入布局 |
| `CubCanvasPanel` | 完整面板（Qt 控件 + `CubGLWidget` 画布） |
| `CubGLWidget` | 底层 OpenGL 渲染部件 |
| `ColorWheelWidget` | HSV 色轮部件 |
| `STYLE_NAMES` / `STYLE_DISPLAY` | fchk 渲染风格列表 |
| `MOL_STYLE_NAMES` / `MOL_STYLE_DISPLAY` | 分子风格列表 |
| `SHININESS_PRESETS` / `SHININESS_DEFAULT` | 光泽预设 |
| `IBOVIEW_DEFAULTS` | IboView 默认 shader 寄存器 |
| `_ensure_pyopengl()` | 检查/补全 PyOpenGL（首次构造自动触发） |

### `OVCanvas` 常用方法

加载与分子：
- `load_cube_files(paths: list[str])` — 加载 .cub（1 或 2 个文件）
- `load_cube(path, iso=None, style_name=None)` — 加载单个 .cub
- `set_molecule(atoms, bonds=None)` — 推入分子结构显示球棍模型
- `clear()` — 清空画布

等值面与配色：
- `set_iso(value)` / `get_iso()` — 等值面绝对阈值（a.u.）
- `set_positive_color(color)` / `set_negative_color(color)` — 正/负相位配色
- `set_transparency(value: 0–1)` — 透明度
- `set_style_name(name)` — 轨道渲染风格
- `set_mol_style_name(name)` — 分子风格（球棍/飘带/仅球…）
- `set_shininess_name(name)` — 光泽预设

渲染与相机：
- `set_render_quality("low"|"medium"|"high")` — 渲染质量（low 关 depth peeling）
- `set_background_color(color)` — 背景色
- `reset_view()` — 重置相机视角

出图：
- `export_image(path, dpi=600.0)` — 离屏高分渲染导出
- `screenshot(path, scale=2.0)` — 帧缓冲截图

底层（`CubGLWidget`）还提供 `set_phase_colors`、`set_opacity`、`set_depth_peeling`、
`set_atom_scale`、`set_bond_scale` 等，可通过 `canvas.glw` 直接调用。

## 许可证

GPLv3。本包部分渲染参数 / 着色器 / 原子表逐字移植自
IboView（Copyright (c) 2015 Gerald Knizia）。作为 IboView 衍生作品发布。
