# -*- coding: utf-8 -*-
"""导入自检：molstudio 包下所有子模块都必须能 import 成功。

这类问题以前只能靠打包后"某个页签不见了"才发现，现在一条命令就能挡在前面。

    pytest tests -q
"""

import importlib
import os
import pkgutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import molstudio  # noqa: E402


def _iter_modules():
    for info in pkgutil.walk_packages(molstudio.__path__, prefix="molstudio."):
        yield info.name


def test_all_submodules_import():
    failed = []
    names = list(_iter_modules())
    assert len(names) > 20, f"收集到的子模块过少：{names}"
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failed, "以下模块导入失败：\n" + "\n".join(failed)


def test_entry_points_exist():
    from molstudio.app import main as app_main
    from molstudio.paths import find_asset, project_root

    assert callable(app_main)
    assert os.path.isdir(project_root())
    # 启动画面/图标资源必须在仓库里找得到（曾经因为 *.png 被忽略而缺失）
    assert find_asset("molstudio.ico"), "找不到 molstudio.ico"
    assert find_asset("校徽.png"), "找不到 校徽.png"
