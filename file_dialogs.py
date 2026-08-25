# -*- coding: utf-8 -*-
"""文件对话框助手：记住上次使用的目录，跨会话保存到 fchk_orbital.ini。

用法：把 QFileDialog.getOpenFileName / getSaveFileName / getOpenFileNames /
getExistingDirectory 换成这里的 open_file / save_file / open_files /
existing_directory（参数与 QFileDialog 同名同序，返回值一致）。
"""
import os
import sys
import configparser

from PyQt5.QtWidgets import QFileDialog

# 与 fchk_orbital.CONFIG_FILE 保持同一解析规则（frozen 时取 exe 目录），
# 否则 PyInstaller 打包后两处会各写各的 ini，记忆功能失效。
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(
        sys.argv[0] if getattr(sys, "frozen", False) else __file__)),
    "fchk_orbital.ini")


def get_last_dir():
    """返回上次使用的目录（不存在或无效时返回空串）。"""
    try:
        cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            cfg.read(CONFIG_FILE, encoding="utf-8")
            d = cfg.get("dialogs", "last_dir", fallback="").strip()
            if d and os.path.isdir(d):
                return d
    except Exception:
        pass
    return ""


def set_last_dir(path):
    """记录一个已选择文件/目录的父目录作为"上次目录"。"""
    if not path:
        return
    d = os.path.dirname(path) if not os.path.isdir(path) else path
    if not os.path.isdir(d):
        return
    try:
        cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            cfg.read(CONFIG_FILE, encoding="utf-8")
        if "dialogs" not in cfg:
            cfg["dialogs"] = {}
        cfg["dialogs"]["last_dir"] = d
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception:
        pass


def _initial(dir_or_name):
    """把调用方给的初始目录/默认文件名与记忆目录合并成对话框初始路径。"""
    d = get_last_dir()
    if not d:
        return dir_or_name or ""
    if dir_or_name:
        if os.path.dirname(dir_or_name):
            return dir_or_name          # 调用方给了明确路径，优先
        return os.path.join(d, dir_or_name)   # 默认文件名 → 拼到记忆目录
    return d


def open_file(parent=None, caption="", directory="", filter_str=""):
    path, sel = QFileDialog.getOpenFileName(parent, caption,
                                            _initial(directory), filter_str)
    if path:
        set_last_dir(path)
    return path, sel


def open_files(parent=None, caption="", directory="", filter_str=""):
    paths, sel = QFileDialog.getOpenFileNames(parent, caption,
                                              _initial(directory), filter_str)
    for p in paths:
        set_last_dir(p)
        break
    return paths, sel


def save_file(parent=None, caption="", directory="", filter_str=""):
    path, sel = QFileDialog.getSaveFileName(parent, caption,
                                            _initial(directory), filter_str)
    if path:
        set_last_dir(path)
    return path, sel


def existing_directory(parent=None, caption="", directory=""):
    d = QFileDialog.getExistingDirectory(parent, caption, _initial(directory))
    if d:
        set_last_dir(d)
    return d
