#!/usr/bin/env python3
"""
GXNU MolStudio 分子可视化与量子化学分析工具 v1.0 — 入口模块
用法:
    python main.py                        # 启动 GUI
    python main.py input.fchk --mo h     # 命令行批处理模式
"""

import os
import re
import sys
import glob

# 确保当前目录在 sys.path 中，以便能找到本地模块和 backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main_window import OrbitalVisApp


def main():
    if len(sys.argv) > 1:
        import argparse
        import fchk_orbital as backend

        p = argparse.ArgumentParser(
            description="GXNU MolStudio v1.0 — Molecular Visualization & Quantum Chemical Analysis")
        p.add_argument("input", help="fchk file or folder")
        p.add_argument("--mo", default="h", help="Orbital (h/l/h-1/number)")
        p.add_argument("--iso", type=float, default=0.05, help="Isosurface threshold")
        p.add_argument("--grid", default="2", help="Grid quality (1/2/3)")
        p.add_argument("--style", default="sob-art",
                       choices=list(backend.STYLES.keys()), help="Render style")
        p.add_argument("--res", default="2000,1500", help="Resolution width,height")
        p.add_argument("--no-render", action="store_true", help="Generate cube only")
        p.add_argument("--out", default=None)
        a = p.parse_args()

        files = (sorted(glob.glob(os.path.join(a.input, "*.fchk")))
                 if os.path.isdir(a.input) else [a.input])
        if not files:
            print("未找到任何 .fchk 文件")
            sys.exit(1)
        out = a.out or (os.path.dirname(a.input)
                        if os.path.isfile(a.input) else a.input)
        if not out:
            out = os.getcwd()
        os.makedirs(out, exist_ok=True)

        # 批处理同样读取用户在 GUI ⚙️ 里配置的 exe 路径，而不是硬编码默认值
        paths = backend.load_config()
        multiwfn_exe = paths["multiwfn"]
        vmd_exe = paths["vmd"]
        tachyon_exe = paths["tachyon"]

        w, h = [int(x) for x in re.split(r"[x,]", a.res)]

        for i, f in enumerate(files):
            print(f"[{i+1}/{len(files)}] {os.path.basename(f)}")
            cube = backend.gen_cube(f, orbital=a.mo, grid_quality=int(a.grid),
                                    work_dir=out, multiwfn_exe=multiwfn_exe)
            if cube:
                print(f"  cube: {os.path.basename(cube)}")
                if not a.no_render:
                    png = backend.render_cube_auto(
                        cube, isovalue=a.iso, style_name=a.style,
                        resolution=(w, h), vmd_exe=vmd_exe,
                        tachyon_exe=tachyon_exe)
                    if png:
                        print(f"  png:  {os.path.basename(png)}")
            else:
                print(f"  Failed")
    else:
        from PyQt5.QtWidgets import QApplication, QSplashScreen
        from PyQt5.QtGui import QColor, QPalette, QSurfaceFormat

        # 内嵌 QOpenGLWidget 必须在 QApplication 创建前设置默认 GL 格式，
        # 否则画布拿不到 3.3 Core Profile 上下文。
        _fmt = QSurfaceFormat()
        _fmt.setSamples(0)
        _fmt.setDepthBufferSize(24)
        _fmt.setVersion(3, 3)
        _fmt.setProfile(QSurfaceFormat.CoreProfile)
        QSurfaceFormat.setDefaultFormat(_fmt)

        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        # Uniform tooltip background
        tip_pal = app.palette()
        tip_pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
        tip_pal.setColor(QPalette.ToolTipText, QColor("#2C3E50"))
        app.setPalette(tip_pal)

        # Splash screen: covers the brief blank/empty window that appears while
        # the bootloader + Qt layout + GL context are initialising, so the user
        # never sees the small-to-large window flash.
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QPixmap
        splash_pix = QPixmap(480, 300)
        splash_pix.fill(QColor("#1B2A3A"))
        splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
        splash.show()
        app.processEvents()

        window = OrbitalVisApp()
        # Fix the final geometry before the first paint so no tiny placeholder
        # frame is ever shown.
        window.resize(1400, 820)
        window.ensurePolished()
        window.show()
        splash.finish(window)
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
