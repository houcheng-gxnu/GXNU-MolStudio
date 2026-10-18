# -*- coding: utf-8 -*-
"""生成公众号文章（Markdown + DOCX），图片用 docs/images 下的自有截图。"""

from __future__ import annotations

import os
import re
import html
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
IMG = ROOT / "images"
MD = ROOT / "公众号_感应电流与表面投影更新.md"
DOCX = ROOT / "公众号_感应电流与表面投影更新.docx"
HTML = ROOT / "公众号_感应电流与表面投影更新.html"

TITLE = "AICD 与表面距离投影：这次更新了两个实用功能"
SUBTITLE = "把 Gaussian + Multiwfn 的常用分析，收进一个看图工作流"
META = "文 / GXNU MolStudio　2026-10"

BLOCKS = [
    ("p", "做芳香性或位阻分析时，有两类图很常用：AICD 感应电流图，用黄色等值面 + 箭头看外磁场下电子怎么走；表面距离投影图，用颜色看分子表面离参考平面有多深。"),
    ("p", "这两类图背后的计算都不复杂，麻烦的是流程：改 Gaussian 输入、等 NMR、装 AICD、跑 POV-Ray、调视角；或者打开 Multiwfn 300 → 8，设范围、等扫描、导数据、再画图。"),
    ("p", "这次 GXNU MolStudio 更新了两个功能：**AICD 的五个按钮流程 + 一键 π/σ**，以及**更好画、更好调的表面距离投影**。原理和参数细节不在这里展开，文末直接放卢天老师（Sobereva）的三篇原文，建议对照阅读。"),

    ("h2", "一、AICD：五个按钮，一键切换 π / σ"),
    ("p", "AICD 分析被收成五步：**载入 GJF → 生成输入 → 本地运行 / 服务器运行 → 载入结果并出图**。本地算完自动出图；服务器模式会导出输入和一条可复制的 `g16 < job.gjf > job.log`，算完把 `.log` 和同目录的张量 `.txt` 拿回来即可。"),
    ("p", "输入编辑器上方新增「计算范围」：全部电子、只看 π、只看 σ、输入里的轨道（`iop(10/93=2)`）。选 π/σ 时，程序用 Multiwfn 自动检测占据 π 轨道，改写输入并加 `_pi` / `_sigma` 后缀；也可以直接手填轨道号（苯是 17、20、21）。**不需要先跑一遍 AICD 全电子任务**：有同体系 fchk/chk 就能检测，知道编号则连 Multiwfn 都不用跑。"),
    ("p", "π/σ 图默认 iso 0.04、关闭场平滑，让 π 环更容易连成完整的一圈；六视图会按磁场方向旋转，B 箭头指向 +B。"),
    ("img", "images/aicd_all_vs_pi.png", "苯的 AICD：全电子（左）与只看 π（右，17/20/21）。"),
    ("p", "全电子图里 σ 的局部环流让等值面呈六角星形；只看 π 时是一圈连续的环电流。做芳香性讨论时，π 图通常更干净。"),

    ("h2", "二、表面距离投影：更光滑、更好调"),
    ("p", "这个功能对应 Multiwfn 的主功能 300 → 8：你在画布上把分子转到想要的朝向，点「绘制投影图」，程序跑 Multiwfn、读 `distmap.txt`，再把同一朝向的原子叠上去。"),
    ("p", "这次主要改善出图：双三次插值、等值线在高一档网格上计算，轮廓和色带不再沿原始格子走台阶；修正了等高线与结构错位/横竖颠倒的问题；新增「显示分子结构」开关，关掉只留色带和等高线；配色增加到 14 种（Jet、Turbo、Viridis、Plasma、Inferno、Magma、Cividis、Coolwarm 等）；保存默认 300 dpi。"),
    ("img", "images/sdm_options_pair.png", "二茂铁的表面距离投影：Turbo + 显示结构（左）；Viridis + 隐藏结构（右）。"),
    ("p", "切换配色、显示结构、留白和背景色会立即重画，不会重算 Multiwfn；插值只影响显示，`distmap.txt` 里的数值不变。"),

    ("h2", "三、怎么用"),
    ("p", "**AICD：** 载入 gjf → 生成输入 → 本地/服务器运行 → 选 π/σ → 载入结果出图。"),
    ("p", "**表面投影：** 画布转到合适朝向 → 打开「表面投影」页 → 设表面/等值面/网格 → 绘制 → 调配色/结构/留白 → 保存 300 dpi 图片。"),

    ("h2", "四、也可以让智能体帮你更新"),
    ("p", "项目代码托管在 CNB：https://cnb.cool/chem311/GXNU-MolStudio（仓库名 GXNU-MolStudio）。如果你在用豆包等支持在本机执行命令/调用工具的智能体，可以把仓库地址直接给它，让它 clone、按 `requirements.txt` 装依赖、`python main.py` 启动；以后每次说「把 GXNU MolStudio 更新到最新」，它执行 `git pull`、补装新增依赖、重启程序。"),
    ("p", "手动更新也很简单：在仓库目录执行 `git pull`。注意 Git 是拉取式更新，push 到 CNB 后，别人/智能体要 pull 才生效，不是自动推送到每台机器；前提是智能体能在这台机器上执行命令并联网。Gaussian、Multiwfn、VMD 等本地程序仍需自己装好，并在程序的路径设置里配好——智能体负责代码同步和启动，不替代这些计算软件。"),

    ("h2", "五、原理与细节请看卢天老师原文"),
    ("p", "本文只介绍这次更新的功能和用法；AICD 的理论、AICD 1.5/2.0 的安装与参数、Multiwfn 300→8 的扫描原理和设置，请直接读卢天老师（Sobereva）的三篇原文："),
    ("ref", "[1] Sobereva（卢天）. 使用AICD程序研究电子离域性和磁感应电流密度. http://sobereva.com/147"),
    ("ref", "[2] Sobereva（卢天）. 使用AICD 2.0绘制磁感应电流图. http://sobereva.com/294"),
    ("ref", "[3] Sobereva（卢天）. 使用Multiwfn绘制分子和固体表面的距离投影图. http://sobereva.com/589"),
    ("p", "文中截图由 GXNU MolStudio 生成；二茂铁为 Multiwfn 自带示例结构，仅作演示。"),
]


def _runs(par, text, size=10.5, color=None, bold_color=None):
    """把 **bold** 拆成 run；支持中文 eastAsia 字体。

    Markdown 里的行内 code 反引号在 Word 里不该原样出现，这里统一去掉；
    正文仍用统一字体，避免中英文混排时字号跳变。
    """
    text = text.replace("`", "")
    parts = text.split("**")
    for i, part in enumerate(parts):
        if not part:
            continue
        run = par.add_run(part)
        run.font.name = "Microsoft YaHei"
        run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),
                                                "Microsoft YaHei")
        run.font.size = Pt(size)
        if i % 2 == 1:
            run.bold = True
            if bold_color:
                run.font.color.rgb = RGBColor(*bold_color)
        elif color:
            run.font.color.rgb = RGBColor(*color)


def build_docx():
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.8)
    sec.bottom_margin = Inches(0.8)
    sec.left_margin = Inches(0.85)
    sec.right_margin = Inches(0.85)

    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.paragraph_format.line_spacing = 1.55
    normal.paragraph_format.space_after = Pt(6)

    # 标题：在冒号处手动断行，避免 Word 自动换行把“这次”拆开
    head, tail = TITLE.split("：", 1)
    for idx, line in enumerate((head + "：", tail)):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6 if idx == 0 else 0)
        p.paragraph_format.space_after = Pt(2 if idx == 0 else 4)
        _runs(p, line, size=19, bold_color=(20, 70, 45))
        for r in p.runs:
            r.bold = True

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    _runs(p, SUBTITLE, size=11, color=(90, 100, 110))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(12)
    _runs(p, META, size=9, color=(130, 140, 150))

    for kind, value, *rest in BLOCKS:
        if kind == "h2":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(4)
            _runs(p, value, size=14, bold_color=(20, 90, 55))
            for r in p.runs:
                r.bold = True
        elif kind == "p":
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(0)
            _runs(p, value)
        elif kind == "quote":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.3)
            p.paragraph_format.space_after = Pt(8)
            _runs(p, value, size=9.5, color=(85, 95, 105))
            for r in p.runs:
                r.font.name = "Consolas"
                r._element.get_or_add_rPr().rFonts.set(
                    qn("w:eastAsia"), "Microsoft YaHei")
        elif kind == "ul":
            for item in value:
                p = doc.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(2)
                _runs(p, item)
        elif kind == "img":
            path = IMG / os.path.basename(value)
            doc.add_picture(str(path), width=Inches(6.3))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.paragraph_format.space_after = Pt(10)
            _runs(cap, rest[0] if rest else "", size=8.5,
                  color=(110, 120, 130))
        elif kind == "ref":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.2)
            p.paragraph_format.space_after = Pt(2)
            _runs(p, value, size=9, color=(60, 70, 80))

    doc.save(DOCX)


def build_md():
    out = [f"# {TITLE}", "", f"*{SUBTITLE}*", "", META, ""]
    for kind, value, *rest in BLOCKS:
        if kind == "h2":
            out += [f"## {value}", ""]
        elif kind == "p":
            out += [value, ""]
        elif kind == "quote":
            out += [f"> {value}", ""]
        elif kind == "ul":
            out += [f"- {item}" for item in value]
            out += [""]
        elif kind == "img":
            alt = (rest[0] if rest else "").replace("[", "").replace("]", "")
            out += [f"![{alt}]({value})", ""]
        elif kind == "ref":
            out += [value, ""]
    MD.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _html_inline(text: str) -> str:
    """把 **bold** 与 `code` 转成内联 HTML，并转义尖括号。"""
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    code_style = ("background:#edf2f7;padding:2px 6px;border-radius:3px;"
                  "font-family:'Consolas','Courier New',monospace;"
                  "font-size:13.5px;color:#1a202c;")
    s = re.sub(r"`([^`]+)`", lambda m: f'<code style="{code_style}">{m.group(1)}</code>', s)
    return s


def build_html():
    """生成公众号可直接预览/复制用的 HTML（全部内联样式，无 JS）。"""
    body_style = (
        "max-width:680px;margin:0 auto;padding:20px 16px 40px;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif;"
        "font-size:15px;line-height:1.8;color:#2d2d2d;background:#fff;")
    out = [
        '<!DOCTYPE html>',
        '<html lang="zh-CN">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'<title>{html.escape(TITLE)}</title>',
        '</head>',
        f'<body style="{body_style}">',
    ]
    head, tail = TITLE.split("：", 1)
    out.append(
        '<h1 style="font-size:20px;text-align:center;margin:10px 0 14px;'
        'line-height:1.5;color:#111;">'
        f'{html.escape(head)}：<br>{html.escape(tail)}</h1>')
    out.append(
        '<p style="text-align:center;color:#888;font-size:14px;'
        'margin:0 0 6px;line-height:1.6;">'
        f'{html.escape(SUBTITLE)}</p>')
    out.append(
        '<p style="text-align:center;color:#aaa;font-size:12px;'
        'margin:0 0 24px;">' + html.escape(META) + '</p>')

    for kind, value, *rest in BLOCKS:
        if kind == "h2":
            out.append(
                '<h2 style="font-size:17px;margin:28px 0 12px;padding-left:10px;'
                'border-left:3px solid #2b6cb0;color:#2b6cb0;">'
                f'{_html_inline(value)}</h2>')
        elif kind == "p":
            out.append(f'<p style="margin:12px 0;">{_html_inline(value)}</p>')
        elif kind == "quote":
            out.append(
                '<blockquote style="margin:12px 0;padding:10px 14px;'
                'background:#f7f8fa;border-left:3px solid #a0aec0;color:#555;'
                'font-size:13.5px;font-family:\'Consolas\',\'Courier New\',monospace;'
                'white-space:pre-wrap;">'
                f'{_html_inline(value)}</blockquote>')
        elif kind == "ul":
            out.append('<ul style="margin:12px 0;padding-left:22px;">')
            for item in value:
                out.append(
                    '<li style="margin-bottom:4px;">'
                    f'{_html_inline(item)}</li>')
            out.append('</ul>')
        elif kind == "img":
            cap = rest[0] if rest else ""
            out.append(
                f'<img src="{html.escape(value)}" alt="{html.escape(cap)}" '
                'style="width:100%;height:auto;display:block;margin:16px auto 6px;'
                'border-radius:4px;">')
            out.append(
                '<p style="text-align:center;color:#888;font-size:12.5px;'
                'line-height:1.6;margin:0 0 18px;">'
                f'{html.escape(cap)}</p>')
        elif kind == "ref":
            s = html.escape(value)
            s = re.sub(
                r"(https?://[^\s<]+)",
                r'<a href="\1" style="color:#2b6cb0;text-decoration:none;'
                r'border-bottom:1px dashed #2b6cb0;">\1</a>', s)
            out.append(
                '<p style="font-size:13px;color:#555;margin:4px 0;'
                'padding-left:8px;line-height:1.7;">' + s + '</p>')

    out += ["</body>", "</html>", ""]
    HTML.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    build_docx()
    build_md()
    build_html()
    print(DOCX)
    print(MD)
    print(HTML)
