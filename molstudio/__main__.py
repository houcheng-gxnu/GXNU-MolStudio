# -*- coding: utf-8 -*-
"""程序入口。

推荐用法（在仓库根目录执行）::

    python main.py          # 或 python -m molstudio

直接 ``python molstudio/__main__.py`` 也能跑：下面这段兜底会把仓库根目录
补进 sys.path（否则按文件路径运行时只有 molstudio\\ 在搜索路径上）。
"""

if __package__ in (None, ""):
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from molstudio.app import main

if __name__ == "__main__":
    main()
