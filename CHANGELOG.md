# Changelog

All notable changes to OrbitalViewer will be documented in this file.

---

## [6.0] — 2026-08

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
