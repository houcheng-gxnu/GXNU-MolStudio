#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GXNU MolStudio 启动入口。

    python main.py                              # 启动 GUI
    python main.py --ui canvas                  # 指定界面布局
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
