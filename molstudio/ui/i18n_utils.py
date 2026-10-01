# -*- coding: utf-8 -*-
"""面板中英文字切换工具。

给「没有 i18n 骨架、文字直接写在代码里」的面板用：维护一份 ``{中文: English}``
映射表，切语言时按控件原文整树替换即可::

    from molstudio.ui.i18n_utils import apply_text_map

    _LANG_MAP = {"清空": "Clear", "载入 CUB…": "Load CUB…"}

    class MyPanel(QWidget):
        def set_lang(self, lang):
            apply_text_map(self, _LANG_MAP, lang)

要点：

* 首次切到英文时把原中文记在控件属性 ``_i18n_<槽位>`` 上，切回中文时按记录还原，
  因此不需要维护反向映射，反复切换也不会「翻丢」文字；
* 覆盖：标签/按钮/分组框的 text、窗口标题、toolTip、占位提示、下拉框条目、
  QTabWidget 页签、表头、QAction 文本；
* 只翻译能``set`` 的槽位，且 text 只对标签类控件生效 —— QLineEdit 等输入控件里
  的用户数据不会被改动。
"""

from PyQt5.QtWidgets import (QAbstractButton, QAction, QComboBox, QGroupBox,
                             QLabel, QMenu, QTabWidget, QTableWidget, QWidget)

__all__ = ["apply_text_map", "combined_map"]


def combined_map():
    """汇总各面板的补充对照表（延迟导入，避免与面板形成循环依赖）。"""
    from molstudio.render.ovcanvas._cv_en_extra import CV_EN_EXTRA
    from molstudio.panels import (asm_irc_panel, crystal_panel, cub_stack_panel,
                                  di_analysis_panel, energy_span_panel, esp_panel,
                                  etsnocv_panel, igmh_panel, irc_panel, ircsplit_panel,
                                  mpp_panel)

    merged = {}
    for module in (asm_irc_panel, crystal_panel, cub_stack_panel, di_analysis_panel,
                   energy_span_panel, esp_panel, etsnocv_panel, igmh_panel, irc_panel,
                   ircsplit_panel, mpp_panel):
        merged.update(getattr(module, "_LANG_EXTRA", {}) or {})
    merged.update(CV_EN_EXTRA)
    return merged


def _slots(widget):
    """产出控件上所有可翻译文字的 ``(键, 读取器, 写入器)``。"""
    # 标签类控件的 text
    if isinstance(widget, (QLabel, QAbstractButton, QGroupBox)):
        getter, setter = getattr(widget, "text", None), getattr(widget, "setText", None)
        if callable(getter) and callable(setter):
            yield "text", getter, setter
    elif isinstance(widget, QMenu):
        getter, setter = getattr(widget, "title", None), getattr(widget, "setTitle", None)
        if callable(getter) and callable(setter):
            yield "title", getter, setter

    for attr, setter_name in (("toolTip", "setToolTip"),
                              ("windowTitle", "setWindowTitle"),
                              ("placeholderText", "setPlaceholderText")):
        getter, setter = getattr(widget, attr, None), getattr(widget, setter_name, None)
        if callable(getter) and callable(setter):
            yield attr, getter, setter

    if isinstance(widget, QComboBox):
        for i in range(widget.count()):
            yield (f"item:{i}",
                   (lambda i=i: widget.itemText(i)),
                   (lambda v, i=i: widget.setItemText(i, v)))

    if isinstance(widget, QTabWidget):
        for i in range(widget.count()):
            yield (f"tab:{i}",
                   (lambda i=i: widget.tabText(i)),
                   (lambda v, i=i: widget.setTabText(i, v)))

    if isinstance(widget, QTableWidget):
        for c in range(widget.columnCount()):
            item = widget.horizontalHeaderItem(c)
            if item is not None:
                yield (f"header:{c}",
                       (lambda c=c: widget.horizontalHeaderItem(c).text()),
                       (lambda v, c=c: widget.horizontalHeaderItem(c).setText(v)))


def _actions(root):
    items = []
    try:
        items = root.findChildren(QAction)
    except RuntimeError:
        return []
    return items


def apply_text_map(root, mapping, lang):
    """按 ``mapping`` 把 ``root`` 及其子控件的文字切到 ``lang``（"zh" / "en"）。"""
    if root is None or not mapping:
        return
    lang = "zh" if lang == "zh" else "en"
    widgets = [root]
    try:
        widgets += root.findChildren(QWidget)
    except RuntimeError:
        return

    for widget in widgets:
        try:
            slots = list(_slots(widget))
        except RuntimeError:
            continue
        for key, getter, setter in slots:
            prop = "_i18n_" + key
            try:
                current = getter()
            except RuntimeError:
                continue
            if not isinstance(current, str) or not current:
                continue
            saved = widget.property(prop)
            if lang == "zh":
                # 只有「我们确实翻译过」的控件才需要还原（属性里存着原中文）
                if isinstance(saved, str) and saved and current != saved:
                    setter(saved)
                continue
            text = mapping.get(current)
            if text and text != current:
                if not isinstance(saved, str) or not saved:
                    widget.setProperty(prop, current)   # 记住中文原文
                setter(text)

    for action in _actions(root):
        for key, getter, setter in (("text", action.text, action.setText),
                                    ("toolTip", action.toolTip, action.setToolTip)):
            prop = "_i18n_act_" + key
            current = getter()
            if not isinstance(current, str) or not current:
                continue
            saved = action.property(prop)
            if lang == "zh":
                if isinstance(saved, str) and saved and current != saved:
                    setter(saved)
                continue
            text = mapping.get(current)
            if text and text != current:
                if not isinstance(saved, str) or not saved:
                    action.setProperty(prop, current)
                setter(text)
