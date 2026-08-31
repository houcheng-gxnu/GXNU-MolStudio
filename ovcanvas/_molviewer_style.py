# -*- coding: utf-8 -*-
"""
_molviewer_style.py — MolViewer「MolCanvas」样式预设 → ovcanvas OpenGL 参数映射
===============================================================================

把 D:\\MolViewer\\molcanvas.py 的 STYLE_PRESETS（纯 QPainter 伪 3D 渲染风格）
翻译成 ovcanvas.CubGLWidget 的 OpenGL 渲染参数。核心是 :func:`apply_molviewer_preset`，
一键把某预设的全部观感（背景渐变、球体质感/光泽、描边、键色/键宽、原子缩放、
阴影、十字、原子标签、景深雾化）应用到画布。

每个预设字段（均已是 ovcanvas 可直接消费的形式）：
    mol_style       MOL_STYLE_NAMES 之一（球棍配色方案）
    shininess       SHININESS_PRESETS 之一（Phong 高光质感，近似 QPainter 径向渐变）
    bg_gradient     bool，是否用三段竖向背景渐变
    bg_colors       (top, mid, bot) 十六进制色（bg_gradient=False 时用 mid 作纯色）
    bond_color      统一键色 hex 或 None（None=两端各用端点元素色的半色键）
    bond_scale      键圆柱半径倍率
    atom_scale      原子球半径倍率
    outline         球体剪影描边开关
    outline_color   描边色 hex
    outline_width   描边带宽（0..1）
    shadows         每原子软阴影
    crosshair       原子十字环
    label_mode      0=元素符号 / 1=原子序号 / 2=关闭
    fade            景深雾化
"""

from ._glwidget import MOL_STYLE_NAMES, SHININESS_PRESETS


def _hex(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


# MolCanvas 的 bond_width / atom_scale 换算到 ovcanvas 的倍率（默认 3.0 → 2.0、
# 0.32 → 1.68），并做合理钳制避免极端。
def _bond_scale(w):
    return max(0.8, min(4.0, w / 3.0 * 2.0))


def _atom_scale(s):
    return max(0.85, min(1.85, s / 0.32 * 1.68))


MOLVIEWER_PRESETS = {
    "Houk": dict(
        mol_style="CPK", shininess="extra shiny", gradient="full",
        bg_gradient=True, bg_colors=("#E8EDF5", "#F5F7FB", "#FFFFFF"),
        bond_color="#000000", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#000000", outline_width=0.3,
        shadows=True, crosshair=True, label_mode=2, fade=True,
    ),
    "Academic": dict(
        mol_style="CPK", shininess="reasonably shiny", gradient="soft_matte",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color="#B0B8C4", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#5F6B7A", outline_width=0.3,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "Publication": dict(
        mol_style="CPK", shininess="reasonably shiny", gradient="subtle",
        bg_gradient=False, bg_colors=("#FAFBFD", "#FAFBFD", "#FAFBFD"),
        bond_color="#7A8694", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#5F6B7A", outline_width=0.3,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "CYLView": dict(
        mol_style="CPK", shininess="not very shiny", gradient="flat",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color="#505050", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#141414", outline_width=0.4,
        shadows=False, crosshair=True, label_mode=2, fade=False,
    ),
    "AppleGlass": dict(
        mol_style="CPK", shininess="reasonably shiny", gradient="soft_matte",
        bg_gradient=True, bg_colors=("#F3F7FB", "#FFFFFF", "#F8FAFC"),
        bond_color="#C0C7D1", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#FFFFFF", outline_width=0.25,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "DarkPro": dict(
        mol_style="VMD single", shininess="reasonably shiny", gradient="soft_matte",
        bg_gradient=False, bg_colors=("#121417", "#121417", "#121417"),
        bond_color="#707780", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#000000", outline_width=0.3,
        shadows=False, crosshair=False, label_mode=2, fade=True,
    ),
    "SobArt": dict(
        mol_style="SobArt", shininess="reasonably shiny", gradient="sob_art",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.5), atom_scale=_atom_scale(0.30),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
    ),
    "AppleLiquid": dict(
        mol_style="CPK", shininess="extra shiny", gradient="apple_liquid",
        bg_gradient=True, bg_colors=("#EEF4FF", "#F8FBFF", "#FFFFFF"),
        bond_color="#C7D2E0", bond_scale=_bond_scale(3.2), atom_scale=_atom_scale(0.19),
        outline=False, outline_color="#FFFFFF", outline_width=0.25,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "ModernPaper": dict(
        mol_style="CPK", shininess="not very shiny", gradient="paper_matte",
        bg_gradient=True, bg_colors=("#F8FAFC", "#FFFFFF", "#F1F5F9"),
        bond_color="#D6DEE8", bond_scale=_bond_scale(2.6), atom_scale=_atom_scale(0.30),
        outline=True, outline_color="#5C6F84", outline_width=0.25,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "HoukPremium": dict(
        mol_style="CPK", shininess="extra shiny", gradient="premium_full",
        bg_gradient=True, bg_colors=("#EAF0F8", "#F8FBFF", "#FFFFFF"),
        bond_color="#28323D", bond_scale=_bond_scale(2.8), atom_scale=_atom_scale(0.31),
        outline=True, outline_color="#18222E", outline_width=0.3,
        shadows=True, crosshair=True, label_mode=2, fade=True,
    ),
    "SoftClay": dict(
        mol_style="CPK", shininess="not very shiny", gradient="clay_matte",
        bg_gradient=True, bg_colors=("#F6F7F4", "#FFFFFF", "#EEF1ED"),
        bond_color="#BBC5C0", bond_scale=_bond_scale(3.1), atom_scale=_atom_scale(0.33),
        outline=True, outline_color="#5C5046", outline_width=0.3,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "GlassPlus": dict(
        mol_style="CPK", shininess="sooooo shiny", gradient="glass_plus",
        bg_gradient=True, bg_colors=("#EEF6FF", "#FFFFFF", "#F6FAFF"),
        bond_color="#D3DEEA", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.24),
        outline=True, outline_color="#FFFFFF", outline_width=0.25,
        shadows=True, crosshair=False, label_mode=2, fade=True,
    ),
    "DarkNeon": dict(
        mol_style="Neon", shininess="extra shiny", gradient="neon_glow",
        bg_gradient=True, bg_colors=("#10151D", "#161D27", "#0B0F14"),
        bond_color="#65758A", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.30),
        outline=True, outline_color="#5B7FE8", outline_width=0.3,
        shadows=False, crosshair=False, label_mode=2, fade=True,
    ),
    "InkMinimal": dict(
        mol_style="CPK", shininess="not very shiny", gradient="ink_flat",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color="#222222", bond_scale=_bond_scale(1.8), atom_scale=_atom_scale(0.25),
        outline=True, outline_color="#191919", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        c_color="#B8B8B8",   # 碳色比 CPK 默认灰 (0.6) 更浅
    ),
    "VMD": dict(
        mol_style="VMD single", shininess="not very shiny", gradient="flat",
        bg_gradient=False, bg_colors=("#202020", "#202020", "#202020"),
        bond_color="#FFFFFF", bond_scale=_bond_scale(3.2), atom_scale=_atom_scale(0.30),
        outline=True, outline_color="#0A0A0A", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
    ),
    "HoukMol": dict(
        mol_style="HoukMol", shininess="reasonably shiny", gradient="gau_default",
        bg_gradient=True, bg_colors=("#E8EDF5", "#F5F7FB", "#FFFFFF"),
        bond_color="#000000", bond_scale=_bond_scale(10.0), atom_scale=_atom_scale(0.30),
        outline=False, outline_color="#000000", outline_width=0.3,
        shadows=True, crosshair=False, label_mode=2, fade=True,
        c_color="#D6D6D6",   # 碳色浅灰（更浅）
        h_color="#FFFFFF",   # 氢原子纯白
    ),
    # 双光源（ovcanvas 扩展，非 MolCanvas 原生）：主光左上 + 辅光右下
    "TwoLight": dict(
        mol_style="CPK", shininess="reasonably shiny", gradient="two_light",
        bg_gradient=True, bg_colors=("#E8EDF5", "#F5F7FB", "#FFFFFF"),
        bond_color="#000000", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#000000", outline_width=0.3,
        shadows=False, crosshair=False, label_mode=2, fade=True,
    ),
    # 四光源（ovcanvas 扩展）：主左上 + 辅右下 + 左右填充
    "FourLight": dict(
        mol_style="CPK", shininess="reasonably shiny", gradient="four_light",
        bg_gradient=True, bg_colors=("#E8EDF5", "#F5F7FB", "#FFFFFF"),
        bond_color="#000000", bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=False, outline_color="#000000", outline_width=0.3,
        shadows=False, crosshair=False, label_mode=2, fade=True,
    ),

    # ═══════════════════════════════════════════════════════════════
    # vcube2.0（VMD 渲染管线）样式——走 IboView Phong 模式（gradient=""，
    # 与 VMD 多灯渲染一致），逐字取各 .stl/.mstl 的相位色/透明度/碳色/材质。
    # ═══════════════════════════════════════════════════════════════
    "vcube-sob-art": dict(
        mol_style="Vcube", shininess="extra shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#4DFF66", neg_color="#6699FF", orb_opacity=0.75,
        c_color="#C8AB7F", surface_ambient=0.1, surface_spec=1.0,
        orb_outline_on=False,
        # 三光点整体往左上移，仍排成斜线；三灯都偏左上区 → 球面左上亮、右下暗
        # （类似单光源的明暗渐变）。高光屏幕位置 ≈ 右上(0.14,-0.55)/中(-0.35,-0.25)/左下(-0.62,0.09)
        light_dirs=[(0.15, 0.60, 0.90), (-0.35, 0.25, 0.90), (-0.70, -0.10, 0.88)],
    ),
    "vcube-sob-esp0": dict(
        mol_style="Vcube", shininess="reasonably shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        orb_opacity=0.62, c_color="#00CCFF", surface_ambient=0.0, surface_spec=0.5,
        orb_outline_on=True, orb_outline_width=0.06,
    ),
    "vcube-sob-esp1": dict(
        mol_style="Vcube", shininess="reasonably shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        orb_opacity=0.6, c_color="#999999", surface_ambient=0.15, surface_spec=0.0,
        orb_outline_on=True, orb_outline_width=0.06,
    ),
    "vcube-ao-chalky": dict(
        mol_style="Vcube", shininess="not very shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#99E680", neg_color="#00B3E6", orb_opacity=0.8,
        c_color="#999999", surface_ambient=0.1, surface_spec=0.2,
        orb_outline_on=False,
    ),
    "vcube-ao-shiny": dict(
        mol_style="Vcube", shininess="reasonably shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#E68033", neg_color="#0099CC", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.2, surface_spec=0.7,
        orb_outline_on=False,
    ),
    "vcube-morandi-blue": dict(
        mol_style="Vcube", shininess="not very shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#C2B8A6", neg_color="#787D85", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.5, surface_spec=0.0,
    ),
    "vcube-morandi-green": dict(
        mol_style="Vcube", shininess="not very shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#739966", neg_color="#D9CCBF", orb_opacity=1.0,
        c_color="#999999", surface_ambient=0.6, surface_spec=0.1,
    ),
    "vcube-morandi-orange": dict(
        mol_style="Vcube", shininess="not very shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#C29161", neg_color="#B0D6E3", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.5, surface_spec=0.0,
    ),
    "vcube-morandi-red": dict(
        mol_style="Vcube", shininess="not very shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#A86959", neg_color="#D1BFA6", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.5, surface_spec=0.0,
    ),
    "vcube-vmwfn0": dict(
        mol_style="Vcube", shininess="sooooo shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#66738C", neg_color="#D9D1BF", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.6, surface_spec=1.0,
    ),
    "vcube-vmwfn1": dict(
        mol_style="Vcube", shininess="extra shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#D9D9BF", neg_color="#99334D", orb_opacity=1.0,
        c_color="#999999", surface_ambient=0.4, surface_spec=1.0,
    ),
    "vcube-white-green": dict(
        mol_style="Vcube", shininess="extra shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#F2F2F2", neg_color="#80E61A", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.2, surface_spec=0.6,
    ),
    "vcube-white-red": dict(
        mol_style="Vcube", shininess="not very shiny", gradient="",
        bg_gradient=False, bg_colors=("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        bond_color=None, bond_scale=_bond_scale(3.0), atom_scale=_atom_scale(0.32),
        outline=True, outline_color="#000000", outline_width=0.4,
        shadows=False, crosshair=False, label_mode=2, fade=False,
        pos_color="#F2F2F2", neg_color="#FF7042", orb_opacity=0.7,
        c_color="#999999", surface_ambient=0.2, surface_spec=0.05,
    ),
}

# 用户要求：暂不需要原子软阴影，全部关闭（绘制代码保留，便于以后恢复）。
# 十字圆环由面板「十字圆环」复选框主控（预设不再强制开启）。
# 同时所有 MolViewer 预设统一观感：原子半径 1.68、键宽 2.0、
# 黑色描边（原子 + 等值面）、描边取细档 0.4（窄带公式下 ≈1px 细线）、
# 画布背景固定纯白（忽略预设自带的渐变/深色背景）。
for _p in MOLVIEWER_PRESETS.values():
    _p["shadows"] = False
    _p["atom_scale"] = 1.68
    _p["bond_scale"] = 2.0
    _p["outline"] = True
    _p["outline_color"] = "#000000"
    _p["outline_width"] = 0.4
    _p["bg_gradient"] = False
    _p["bg_colors"] = ("#FFFFFF", "#FFFFFF", "#FFFFFF")

MOLVIEWER_NAMES = {
    "Houk": "Houk 经典",
    "Academic": "学术论文",
    "Publication": "期刊插图",
    "CYLView": "CYLView",
    "AppleGlass": "Apple Glass",
    "DarkPro": "深色专业",
    "SobArt": "Chem311",
    "AppleLiquid": "Apple Liquid Glass",
    "ModernPaper": "Modern Paper",
    "HoukPremium": "Houk Premium",
    "SoftClay": "Soft Clay",
    "GlassPlus": "Glass Plus",
    "DarkNeon": "Dark Neon",
    "InkMinimal": "Ink Minimal",
    "VMD": "VMD 默认",
    "HoukMol": "HoukMol",
    "TwoLight": "双光源",
    "FourLight": "四光源",
    "vcube-sob-art": "vcube: sob-art (Chem3D)",
    "vcube-sob-esp0": "vcube: sob-esp0 (BWR)",
    "vcube-sob-esp1": "vcube: sob-esp1 (BWR)",
    "vcube-ao-chalky": "vcube: ao-chalky (AO)",
    "vcube-ao-shiny": "vcube: ao-shiny (AO)",
    "vcube-morandi-blue": "vcube: morandi-blue",
    "vcube-morandi-green": "vcube: morandi-green",
    "vcube-morandi-orange": "vcube: morandi-orange",
    "vcube-morandi-red": "vcube: morandi-red",
    "vcube-vmwfn0": "vcube: vmwfn0 (冰蓝)",
    "vcube-vmwfn1": "vcube: vmwfn1 (亮漆)",
    "vcube-white-green": "vcube: white-green",
    "vcube-white-red": "vcube: white-red",
}


def apply_molviewer_preset(glw, name):
    """把一个 MolViewer 样式预设应用到 CubGLWidget（球棍模型观感）。

    返回 True 表示成功；未知预设返回 False。不影响等值面（轨道）风格与相位配色。
    """
    p = MOLVIEWER_PRESETS.get(name)
    if p is None or glw is None:
        return False

    mol_style = p["mol_style"]
    if mol_style in MOL_STYLE_NAMES:
        glw.set_mol_style(mol_style)

    shiny = p["shininess"]
    if shiny in SHININESS_PRESETS:
        glw.set_shininess(shiny)

    # 球体径向渐变（MolCanvas 逐字停靠曲线）——这是观感的核心
    glw.set_mv_gradient(p.get("gradient", ""))

    if p["bg_gradient"]:
        t, m, b = (_hex(c) for c in p["bg_colors"])
        glw.set_background_gradient(t, m, b)
    else:
        _, m, _ = p["bg_colors"]
        glw.set_background(_hex(m))

    glw.set_bond_color(p["bond_color"])
    glw.set_bond_scale(p["bond_scale"])
    glw.set_atom_scale(p["atom_scale"])
    glw.set_atom_outline(p["outline"], _hex(p["outline_color"]), p["outline_width"])
    # 等值面描边跟随预设的 rim：同色、窄带细描边（0.03~0.2 清晰勾边）
    glw.set_orb_outline(p["outline"], _hex(p["outline_color"]),
                        max(0.03, min(0.2, p["outline_width"] * 0.2)))
    glw.set_shadows(p["shadows"])
    glw.set_crosshair(p["crosshair"])
    glw.set_atom_labels(p["label_mode"])
    glw.set_fade_enabled(p["fade"])

    # ── vcube / VMD 扩展字段（可选） ──
    pc = p.get("pos_color")
    if pc:
        glw.set_phase_colors(pos_rgb=tuple(int(c * 255) for c in _hex(pc)))
    nc = p.get("neg_color")
    if nc:
        glw.set_phase_colors(neg_rgb=tuple(int(c * 255) for c in _hex(nc)))
    if "orb_opacity" in p:
        glw.set_opacity(p["orb_opacity"])
    if "surface_ambient" in p or "surface_spec" in p:
        glw.set_surface_material(ambient=p.get("surface_ambient"),
                                 spec_mul=p.get("surface_spec"))
    cc = p.get("c_color")
    if cc:
        glw.set_carbon_color(_hex(cc))
    hc = p.get("h_color")
    if hc:
        glw.set_hydrogen_color(_hex(hc))
    # 表面描边可单独覆盖（优先级高于上面的 rim 派生值）
    if "orb_outline_on" in p:
        glw.set_orb_outline(p["orb_outline_on"],
                            _hex(p.get("orb_outline_color", "#000000")),
                            p.get("orb_outline_width", 0.08))
    # 自定义三光源方向（把球面高光点排成指定布局；无 light_dirs 的预设恢复默认）
    glw.set_light_dirs(p.get("light_dirs"))
    return True
