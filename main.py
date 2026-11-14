#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GXNU MolStudio 启动入口。

    python main.py                              # 启动 GUI（默认经典蓝色主题 + 分级侧栏）
    python main.py --ui classic                 # 纯经典版（左侧 27 项平铺）
    python main.py --ui focus                   # 保留的灰色卡片主题（备用）
    python main.py --ui studio                  # Studio 完整界面（另有 clean/clean2/canvas）
    python main.py input.fchk --mo h --out DIR  # 命令行批处理

等价入口：``python -m molstudio``。
"""

import os
import sys

# 让 `python main.py` / 打包后的入口都能找到 molstudio 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from molstudio.app import main  # noqa: E402

if __name__ == "__main__":
    main()
