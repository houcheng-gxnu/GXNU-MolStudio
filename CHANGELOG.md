# Changelog

All notable changes to OrbitalViewer will be documented in this file.

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
