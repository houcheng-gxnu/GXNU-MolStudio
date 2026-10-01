# -*- coding: utf-8 -*-
"""路径解析集中地。

源码运行与 PyInstaller 打包（onedir / onefile）两种情形的目录约定都收敛在这里，
其它模块不要再各自拼 ``os.path.dirname(__file__)``。

约定：

* 仓库根目录（源码运行）= 本包的上一级目录，``fchk_orbital.ini`` 等用户配置写在这里；
* exe 目录（打包运行）= ``sys.executable`` 所在目录，配置写在这里，assets 也从这里找；
* 内置资源统一放在 ``molstudio/assets/``，打包时原样带进 ``_internal/molstudio/assets``。
"""

import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    """是否运行在 PyInstaller 打包环境里。"""
    return bool(getattr(sys, "frozen", False))


def package_dir():
    """本包（molstudio/）所在目录。"""
    return _PKG_DIR


def project_root():
    """源码运行时返回仓库根目录；打包后返回 exe 所在目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(_PKG_DIR)


def assets_dirs():
    """按优先级返回可能存放内置资源的目录列表。"""
    dirs = [os.path.join(_PKG_DIR, "assets")]
    if is_frozen():
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.insert(0, os.path.join(meipass, "molstudio", "assets"))
            dirs.insert(1, meipass)
        dirs.insert(0, exe_dir)
        dirs.insert(1, os.path.join(exe_dir, "molstudio", "assets"))
    dirs.append(os.getcwd())
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def find_asset(*names):
    """在候选目录中按顺序查找资源文件，返回第一个存在的绝对路径，找不到返回 None。"""
    for d in assets_dirs():
        for name in names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


def config_file(name="fchk_orbital.ini"):
    """用户可写的配置文件路径（源码运行时在仓库根目录，打包后在 exe 同目录）。"""
    return os.path.join(project_root(), name)


def entry_script():
    """启动脚本 ``main.py`` 的路径（用于另起进程重启界面）。"""
    return os.path.join(project_root(), "main.py")
