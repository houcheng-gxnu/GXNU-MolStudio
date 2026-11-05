# -*- coding: utf-8 -*-
"""启动诗词：数据完整性 + 环境开关行为。

    pytest tests -q

不依赖 Qt，也不联网——诗词文本是仓库内的静态数据（来源见
``molstudio/core/poems.py`` 的模块 docstring）。
"""

import os

from molstudio.core import poems


def _with_env(value):
    """临时设置 MOLSTUDIO_POEM，返回还原用的原值（None 表示本来没有）。"""
    old = os.environ.get("MOLSTUDIO_POEM")
    if value is None:
        os.environ.pop("MOLSTUDIO_POEM", None)
    else:
        os.environ["MOLSTUDIO_POEM"] = value
    return old


def _restore(old):
    if old is None:
        os.environ.pop("MOLSTUDIO_POEM", None)
    else:
        os.environ["MOLSTUDIO_POEM"] = old


def test_poems_data_is_wellformed():
    # 下限盯住"整首被误删"（诗词表变动时同步改这里；CHANGELOG 也写的是 16 首）
    assert len(poems.POEMS) >= 16, f"诗词数量过少：{len(poems.POEMS)}"
    titles = [p["title"] for p in poems.POEMS]
    assert len(titles) == len(set(titles)), "标题不应重复"
    for poem in poems.POEMS:
        assert set(poem) == {"title", "year", "lines"}, \
            f"{poem.get('title')} 的键不对：{sorted(poem)}"
        assert poem["title"].strip(), "缺标题"
        assert poem["year"].strip(), f"{poem['title']} 缺年份"
        assert poem["lines"], f"{poem['title']} 没有正文"
        for line in poem["lines"]:
            # 空串是「上下阕之间的空行」，其余必须是去掉首尾空白后仍有内容
            assert isinstance(line, str)
            assert line == line.strip(), f"{poem['title']} 的正文行有多余空白：{line!r}"
        assert any(line for line in poem["lines"]), f"{poem['title']} 只有空行"
        # 行首不应带排版用缩进（缩进由界面负责加）
        assert not any(line.startswith(" ") for line in poem["lines"]), \
            f"{poem['title']} 的正文行不应自带缩进"


def test_enabled_switch():
    old = _with_env(None)
    try:
        assert poems.enabled() is True          # 未设置 = 开启
        for off in ("0", "off", "OFF", "false", "no"):
            os.environ["MOLSTUDIO_POEM"] = off
            assert poems.enabled() is False, f"{off!r} 应当关闭启动诗词"
        for on in ("1", "on", "咏梅"):
            os.environ["MOLSTUDIO_POEM"] = on
            assert poems.enabled() is True, f"{on!r} 应当开启启动诗词"
    finally:
        _restore(old)


def test_pick_poem_by_title_substring():
    old = _with_env("咏梅")
    try:
        poem = poems.pick_poem()
        assert poem["title"] == "卜算子·咏梅", poem["title"]
    finally:
        _restore(old)


def test_pick_poem_random_falls_back_to_pool():
    old = _with_env("一个不存在的标题")
    try:
        picks = {poems.pick_poem()["title"] for _ in range(50)}
        assert picks, "必须总能挑到一首"
        assert picks <= {p["title"] for p in poems.POEMS}
    finally:
        _restore(old)


def test_pick_poem_is_reproducible_with_rng():
    import random

    old = _with_env(None)
    try:
        a = poems.pick_poem(random.Random(20261001))["title"]
        b = poems.pick_poem(random.Random(20261001))["title"]
        assert a == b, "同一个种子应当挑到同一首"
    finally:
        _restore(old)


# ── 字符边框版式 ───────────────────────────────────────────────

_FULLWIDTH_SPACE = "\u3000"


def test_framed_rows_are_uniform_and_fullwidth():
    """框线必须齐：每行等宽，且框内不许混入 ASCII（半角会破坏等宽）。"""
    for poem in poems.POEMS:
        rows = poems.frame_poem(poem)
        kinds = [k for k, _ in rows]
        assert kinds[0] == kinds[-1] == "border", f"{poem['title']} 缺少上下框线"
        assert kinds.count("border") == 2, f"{poem['title']} 框线数量不对：{kinds}"
        for want in ("title", "meta", "body"):
            assert want in kinds, f"{poem['title']} 缺少 {want} 行"

        widths = {len(text) for _, text in rows}
        assert len(widths) == 1, \
            f"{poem['title']} 各行宽度不一致（框会歪）：{sorted(widths)}"

        for kind, text in rows:
            assert not any(ord(ch) < 0x80 for ch in text), \
                f"{poem['title']} 的 {kind} 行混入了半角字符：{text!r}"
            assert text[0] in "┌│└" and text[-1] in "┐│┘", \
                f"{poem['title']} 的 {kind} 行边框不完整：{text!r}"


def test_framed_title_and_meta_are_centered():
    """标题与作者行在框内居中：左右留白差不超过一格。"""
    for poem in poems.POEMS:
        for kind, text in poems.frame_poem(poem):
            if kind not in ("title", "meta"):
                continue
            inner = text[1:-1]
            left = len(inner) - len(inner.lstrip(_FULLWIDTH_SPACE))
            right = len(inner) - len(inner.rstrip(_FULLWIDTH_SPACE))
            assert abs(left - right) <= 1, \
                f"{poem['title']} 的 {kind} 行没居中（左{left}/右{right}）：{text!r}"


def test_framed_rows_keep_the_whole_poem():
    """框内不能丢内容：正文每句都出现过一次，且顺序不变。"""
    for poem in poems.POEMS:
        framed = "".join(text for _, text in poems.frame_poem(poem))
        pos = 0
        for line in poem["lines"]:
            if not line:
                continue
            wrapped = poems._to_fullwidth(line)
            found = framed.find(wrapped, pos)
            assert found >= 0, f"{poem['title']} 丢了这一句：{line!r}"
            pos = found + len(wrapped)
        assert poems._to_fullwidth(poem["title"]) in framed
        assert poems._to_fullwidth("毛泽东 · " + poem["year"]) in framed
