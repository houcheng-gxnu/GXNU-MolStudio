# -*- coding: utf-8 -*-
"""画布下方「四张工具卡片」自检（offscreen）。

覆盖 ``molstudio/ui/canvas_cards_bar.py`` 的对外契约：

* ``install_canvas_cards(win)`` 把 ``QWidget#CanvasCardsBar`` 插到紧凑工具条
  （``win._studio_canvas_bar``）正下方、同一个父布局里，默认隐藏、幂等；
* 四张 ``QFrame#CanvasCard`` 卡片 + ≥12 个转发按钮；
* ``set_lang("en"/"zh")`` 切换卡片标题与自建按钮文字，``refresh()`` 可重复调用；
* 点「渲染风格」卡片里的按钮会转发给原 ``_CanvasBar._apply_style``（不崩）。

跑法::

    python -m pytest tests/test_canvas_cards.py -q
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QToolButton  # noqa: E402

# 与 tests/test_classic_nav_ui.py 保持一致：关掉 MSAA，避免 offscreen 下
# OpenGL 上下文申请失败时报一堆警告（控件仍然照常存在）。
_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = None
_window = None


def _pump(ms=80):
    """跑事件循环 ms 毫秒（处理延迟初始化 / 画布工具条安装）。"""
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        _app.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def win():
    """整个模块复用一个 MolStudioClassicNavWindow（窗口创建约 2s）。"""
    global _app, _window
    _app = QApplication.instance() or QApplication(sys.argv)
    _app.setStyle("Fusion")
    from molstudio.ui.main_window_classic_nav import MolStudioClassicNavWindow

    _window = MolStudioClassicNavWindow()
    _window.resize(1600, 1000)
    _window.setAttribute(Qt.WA_DontShowOnScreen, True)
    _window.show()
    # 画布 + 紧凑工具条是 QTimer.singleShot(0) 延迟安装的；1.5s 足够
    _pump(1500)
    yield _window
    try:
        _window.close()
    except Exception:
        pass


def _cards(win):
    """安装（幂等）并返回四张卡片控件；顺带断言紧凑工具条已就绪。"""
    from molstudio.ui.canvas_cards_bar import install_canvas_cards

    bar = getattr(win, "_studio_canvas_bar", None)
    assert bar is not None, "MolStudioClassicNavWindow 必须先装好紧凑工具条"
    cards = install_canvas_cards(win)
    assert cards is not None, "四张工具卡片安装失败（返回 None）"
    return bar, cards


def _card_frames(cards):
    return cards.findChildren(QFrame, "CanvasCard")


def _buttons(cards):
    return cards.findChildren(QToolButton, "CanvasCardsBtn")


def _titles(cards):
    return [lab.text() for lab in cards.findChildren(QLabel, "CanvasCardTitle")]


# ══════════════════════════════════════════════════════════════════════════ #
#  1. 安装位置 / 结构 / 默认隐藏
# ══════════════════════════════════════════════════════════════════════════ #
def test_install_below_compact_bar_and_hidden(win):
    bar, cards = _cards(win)
    assert cards.objectName() == "CanvasCardsBar"

    # 插在紧凑工具条下面一层，且在同一个父布局里
    parent = bar.parentWidget()
    assert parent is not None
    assert cards.parentWidget() is parent
    lay = parent.layout()
    assert lay is not None
    assert lay.indexOf(cards) == lay.indexOf(bar) + 1, \
        f"卡片必须在工具条正下方：bar={lay.indexOf(bar)} cards={lay.indexOf(cards)}"

    # 默认隐藏（由窗口的「工具 ▾」开关显隐）
    assert cards.isHidden()
    assert not cards.isVisible()

    # 四张卡片 + 至少 12 个转发按钮
    assert len(_card_frames(cards)) == 4, "必须是四张卡片"
    assert len(_buttons(cards)) >= 12, f"按钮太少：{len(_buttons(cards))}"

    # 幂等：重复安装返回同一个控件
    from molstudio.ui.canvas_cards_bar import install_canvas_cards

    assert install_canvas_cards(win) is cards

    # 缺少前置条件（没有紧凑工具条）时安全返回 None
    assert install_canvas_cards(object()) is None
    assert install_canvas_cards(None) is None


def test_four_cards_have_expected_titles(win):
    _bar, cards = _cards(win)
    cards.set_lang("zh")           # 不依赖上次运行残留的语言设置
    assert _titles(cards) == ["渲染风格", "显示设置", "测量与分析", "文件导出"]


def test_refresh_tolerates_missing_bar_internals(win):
    """``refresh()`` 在紧凑工具条内部属性缺失时也只能降级、不能崩。"""
    from molstudio.ui.canvas_cards_bar import CanvasCardsBar

    bare = CanvasCardsBar(win, object())      # 没有 _chips/_kind_acts/菜单的桩件
    try:
        assert len(_card_frames(bare)) == 4
        bare.refresh()
        bare.set_lang("en")
        bare.refresh()
        bare.set_lang("zh")
        bare.refresh()
    finally:
        bare.deleteLater()
        _pump(30)


# ══════════════════════════════════════════════════════════════════════════ #
#  2. 显示 / 语言切换 / refresh 重复调用
# ══════════════════════════════════════════════════════════════════════════ #
def test_show_and_language_roundtrip(win):
    _bar, cards = _cards(win)
    cards.setVisible(True)
    _pump(200)
    assert cards.isVisible()
    assert cards.height() >= 80, f"显示后高度异常：{cards.height()}"
    assert cards.height() <= 140, f"显示后太高，会挤画布：{cards.height()}"

    # 中文 → 英文
    cards.set_lang("en")
    _pump(60)
    assert _titles(cards) == ["Render Style", "Display",
                              "Measure & Analyze", "File Export"]
    texts = {b.text() for b in _buttons(cards)}
    for want in ("More", "Measure", "Surface", "3D Model", "More Export"):
        assert want in texts, f"英文按钮缺失：{want} / {texts}"
    # 源控件文字（样式名等）不翻译，仍在
    assert "sob-art" in texts

    # 英文 → 中文
    cards.set_lang("zh")
    _pump(60)
    assert _titles(cards) == ["渲染风格", "显示设置", "测量与分析", "文件导出"]
    texts = {b.text() for b in _buttons(cards)}
    for want in ("更多", "测量开关", "清除测量", "表面分析", "3D 模型", "更多导出"):
        assert want in texts, f"中文按钮缺失：{want} / {texts}"

    # refresh 可重复调用，且状态不变
    cards.refresh()
    cards.refresh()
    assert _titles(cards) == ["渲染风格", "显示设置", "测量与分析", "文件导出"]
    assert len(_buttons(cards)) >= 12


# ══════════════════════════════════════════════════════════════════════════ #
#  3. 渲染风格按钮真实转发到原工具条
# ══════════════════════════════════════════════════════════════════════════ #
def test_render_button_forwards_style_click(win):
    bar, cards = _cards(win)
    cards.setVisible(True)
    cards.set_lang("zh")
    _pump(120)

    style_btn = next(b for b in _buttons(cards) if b.text() == "sob-art")
    assert style_btn.isCheckable(), "样式按钮要能反映当前样式的高亮"

    style_btn.click()
    _pump(250)

    # 原画布风格真的变了（转发链路通），且卡片高亮跟随原工具条
    style_name = str(getattr(win.cub_canvas.glw, "_style_name", "")).lower()
    assert "sob" in style_name.replace("-", ""), f"样式没切过去：{style_name!r}"
    assert style_btn.isChecked()
    # 「渲染风格」卡片里同时只能有一个样式高亮（测量类型的高亮不算）
    style_names = {"sob-art", "HoukMol3d", "2D 平涂", "IQmol"}
    active = [b.text() for b in _buttons(cards)
              if b.isChecked() and b.text() in style_names]
    assert active == ["sob-art"], f"样式高亮应只有一个：{active}"

    # 原紧凑工具条自己的胶囊也同步了（同一份状态，不是两套）
    chip_active = [chip.text() for chip, _src in bar._chips
                   if bool(chip.property("active"))]
    assert chip_active == ["sob-art"], f"原胶囊没同步：{chip_active}"


# ══════════════════════════════════════════════════════════════════════════ #
#  4. 测量与分析 / 文件导出卡片：转发目标存在而不是空壳
# ══════════════════════════════════════════════════════════════════════════ #
def test_measure_and_export_buttons_forward(win):
    _bar, cards = _cards(win)
    texts = [b.text() for b in _buttons(cards)]
    for want in ("距离", "键角", "二面角", "截图", "导出图片"):
        assert want in texts, f"缺少 {want} 按钮：{texts}"

    def _find(text):
        return next(b for b in _buttons(cards) if b.text() == text)

    # 距离按钮 → 原测量类型下拉应切回 0（转发链路通）
    win.cub_canvas._measure_kind_cb.setCurrentIndex(2)
    _pump(60)
    _find("距离").click()
    _pump(120)
    assert int(win.cub_canvas._measure_kind_cb.currentIndex()) == 0

    # 截图 / 导出图片是文字转发按钮（点下去会弹模态保存框，测试只验证可用）
    assert _find("截图").isEnabled()
    assert _find("导出图片").isEnabled()
