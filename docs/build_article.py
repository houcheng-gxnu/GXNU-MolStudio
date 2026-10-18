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

TITLE = "AICD 与表面距离投影：本次更新包含两个功能"
SUBTITLE = "Gaussian 与 Multiwfn 常用分析流程的界面集成"
META = "文 / GXNU MolStudio　2026-10"

BLOCKS = [
    ("p", "AICD 感应电流图用于显示外磁场下的电流密度分布；表面距离投影图用于显示分子表面相对参考平面的深度。两类图的计算涉及 Gaussian、AICD/POV-Ray 或 Multiwfn 等多个步骤。"),
    ("p", "本次 GXNU MolStudio 更新包含两个功能：AICD 的五步流程与 π/σ 选择；表面距离投影的插值与显示选项。原理和参数说明见文末卢天老师（Sobereva）的三篇原文。"),

    ("h2", "一、AICD：五步流程与 π/σ 选择"),
    ("p", "AICD 分析流程为五步：载入 GJF、生成输入、本地运行或服务器运行、载入结果并出图。本地运行完成后自动生成图像。服务器运行导出输入文件和 `g16 < job.gjf > job.log` 命令；计算完成后，载入 `.log` 与同目录的张量 `.txt`。"),
    ("p", "输入编辑器上方提供「计算范围」选项：全部电子、只看 π、只看 σ、输入中的轨道（`iop(10/93=2)`）。选择 π/σ 时，程序调用 Multiwfn 检测占据 π 轨道，改写输入并添加 `_pi` / `_sigma` 后缀；也可手动输入轨道编号（苯为 17、20、21）。该流程不要求先执行 AICD 全电子任务：存在同体系 fchk/chk 时可进行检测；已知轨道编号时，可不调用 Multiwfn。"),
    ("p", "π/σ 的默认参数为 iso 0.04、关闭场平滑；六视图按磁场方向旋转，B 箭头指向 +B。"),
    ("img", "images/aicd_all_vs_pi.png", "苯的 AICD：全电子（左）与只看 π（右，17/20/21）。"),
    ("p", "全电子图的等值面包含 σ 局部环流，呈六角星形；π 图显示连续环电流。"),

    ("h2", "二、表面距离投影：插值与显示选项"),
    ("p", "该功能对应 Multiwfn 主功能 300 → 8。在画布中调整分子朝向，点击「绘制投影图」；程序调用 Multiwfn、读取 `distmap.txt`，并叠加同朝向的原子。"),
    ("p", "本次更新包括：双三次插值；等值线在更高倍率网格上计算；修正等高线与结构错位/横竖颠倒；新增「显示分子结构」开关；配色增至 14 种（Jet、Turbo、Viridis、Plasma、Inferno、Magma、Cividis、Coolwarm 等）；保存默认 300 dpi。"),
    ("img", "images/sdm_options_pair.png", "二茂铁的表面距离投影：Turbo + 显示结构（左）；Viridis + 隐藏结构（右）。"),
    ("p", "切换配色、结构显示、留白或背景色时，程序重绘图像，不重新运行 Multiwfn。插值仅影响显示，`distmap.txt` 中的数值不变。"),

    ("h2", "三、使用方法"),
    ("p", "**AICD：** 载入 gjf → 生成输入 → 本地/服务器运行 → 选择 π/σ → 载入结果出图。"),
    ("p", "**表面投影：** 调整画布朝向 → 打开「表面投影」页 → 设置表面/等值面/网格 → 绘制 → 设置配色/结构/留白 → 保存 300 dpi 图片。"),

    ("h2", "四、通过智能体更新代码"),
    ("p", "项目代码托管于 CNB：https://cnb.cool/chem311/GXNU-MolStudio（仓库名 GXNU-MolStudio）。支持本机命令执行的智能体（如豆包）可用于代码同步：将仓库地址提供给智能体，执行 clone、按 `requirements.txt` 安装依赖、运行 `python main.py`；后续更新执行 `git pull`、安装新增依赖并重启程序。"),
    ("p", "也可在仓库目录手动执行 `git pull`。Git 为拉取式更新：代码推送至 CNB 后，其他副本需执行 pull 才会更新。智能体需具备本机命令执行权限和网络访问；Gaussian、Multiwfn、VMD 等本地程序需自行安装并配置路径，智能体仅负责代码同步和启动。"),

    ("h2", "五、原理与参数说明"),
    ("p", "本文介绍更新功能与用法。AICD 理论、AICD 1.5/2.0 的安装与参数、Multiwfn 300 → 8 的扫描原理与设置，参见卢天老师（Sobereva）的原文："),
    ("ref", "[1] Sobereva（卢天）. 使用AICD程序研究电子离域性和磁感应电流密度. http://sobereva.com/147"),
    ("ref", "[2] Sobereva（卢天）. 使用AICD 2.0绘制磁感应电流图. http://sobereva.com/294"),
    ("ref", "[3] Sobereva（卢天）. 使用Multiwfn绘制分子和固体表面的距离投影图. http://sobereva.com/589"),
    ("p", "截图由 GXNU MolStudio 生成；二茂铁为 Multiwfn 自带示例结构。"),
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
