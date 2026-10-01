"""
出图观感预设（Look presets）
================================================================
一键把**布光 + 材质 + 后处理 + 景深雾化 + 背景**打包成一套连贯的观感。
存在的理由：画布上几十个参数大多是"同一通道上的系数"，单独调一个几乎看不出来
（实测：清漆/光晕/粗糙度在主体像素上的差异 < 2.5/255，而换整套观感能到 30+）。
用户要的是"台阶式"变化，而不是再添一个滑块。

每个预设是 :meth:`CubGLWidget.get_style_state` 的一份**部分**状态字典——
只写需要改的键，其余保持画布当前值（所以预设不会清掉你已选的等值面配色、
原子配色、分子尺寸等）。键的含义见该方法的返回值：

    gloss / spec_model / matcap / roughness / coat_* / sss_strength / soft_term
    light_count / light_dirs / light_glow / light_glows / gradient
    hemi_enabled / hemi_top / hemi_bottom / hemi_intensity
    post = [enabled, scale, edge, edge_radius, tone, vignette, ao, ao_radius, ao_depth]
    fade / fog_strength / bg / bg_grad / orb_opacity

数值经渲染实测标定（见 _look_preset_probe.py：两两差异矩阵），
保证任意两套观感在主体像素上的平均色差 ≥ 20/255——即"一眼能看出换了一套"。
"""

# ── 公用子参数（避免各预设重复写）──────────────────────────────
_POST_OFF = [True, 1.5, 0.0, 2.0, 0.0, 0.0, 0.0, 8.0, 0.03]
_IBO_DIRS = [(0.5, 0.5, 0.70710678),
             (-0.4330127, -0.25, 0.8660254),
             (0.4330127, -0.25, 0.8660254),
             (0.0, 0.0, 1.0)]
# 所有预设统一用纯白背景（出图/投稿首选）。雾化终色取自背景色，因此会一并
# 变成白色（"远处淡入白底"），这也正是景深雾化在投稿图里应有的行为。
_WHITE = [1.0, 1.0, 1.0, 1.0]


LOOK_PRESETS = {
    # ── 1. 通透玻璃：明亮、低环境对比、淡景深，轨道图通用 ──
    "glass": {
        "display": "通透玻璃",
        "display_en": "Clear Glass",
        "tip": "明亮通透：GGX 薄高光 + 淡景深雾化 + 纯白底，轨道/弱相互作用通用",
        "state": {
            "spec_model": 1, "gloss": 0.12, "roughness": 0.30,
            "coat_strength": 0.80, "coat_roughness": 0.10,
            "sss_strength": 0.0, "soft_term": 0.10,
            "hemi_enabled": True, "hemi_top": [0.18, 0.20, 0.24],
            "hemi_bottom": [0.04, 0.04, 0.05], "hemi_intensity": 0.28,
            "light_count": 3, "light_dirs": _IBO_DIRS,
            "light_glow": 1.0, "light_glows": [1.0, 1.0, 1.0, 1.0],
            "gradient": "",
            "post": list(_POST_OFF),
            "fade": True, "fog_strength": 0.35,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.70,
        },
    },
    # ── 2. 哑光纸感：无高光、柔过渡、低对比，黑白论文最稳 ──
    "matte": {
        "display": "哑光纸感",
        "display_en": "Matte Paper",
        "tip": "哑光纸感：无镜面高光 + 强环境补光 + 柔和明暗交界，黑白印刷友好",
        "state": {
            "spec_model": 1, "gloss": 0.0, "roughness": 1.00,
            "coat_strength": 0.0, "coat_roughness": 0.10,
            "sss_strength": 0.0, "soft_term": 0.75,
            "hemi_enabled": True, "hemi_top": [0.28, 0.28, 0.30],
            "hemi_bottom": [0.12, 0.12, 0.13], "hemi_intensity": 0.70,
            "light_count": 3, "light_dirs": _IBO_DIRS,
            "light_glow": 1.8, "light_glows": [1.8, 1.8, 1.8, 1.8],
            "gradient": "",
            # edge=0：边缘暗化会在剪影外沿留一圈暗环（实测环上峰值 11/255），
            # 用户明确不要；需要时可在面板单独打开「边缘暗化」滑块。
            "post": [True, 1.5, 0.0, 3.5, 0.0, 0.0, 0.45, 8.0, 0.03],
            "fade": True, "fog_strength": 0.10,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.92,
        },
    },
    # ── 3. 高对比期刊：硬调、强轮廓、深阴影，缩到单栏也认得清 ──
    "journal": {
        "display": "高对比期刊",
        "display_en": "Journal Contrast",
        "tip": "高对比：侧向双主光 + 硬明暗交界 + 强 AO/描边边暗 + 轻微色调映射",
        "state": {
            "spec_model": 1, "gloss": 0.18, "roughness": 0.18,
            "coat_strength": 0.80, "coat_roughness": 0.10,
            "sss_strength": 0.0, "soft_term": 0.0,
            "hemi_enabled": False, "hemi_top": [0.18, 0.18, 0.18],
            "hemi_bottom": [0.035, 0.035, 0.035], "hemi_intensity": 0.25,
            "light_count": 3,
            "light_dirs": [(0.62, 0.42, 0.66), (-0.75, -0.20, 0.63),
                           (0.10, -0.80, 0.59), (0.0, 0.0, 1.0)],
            "light_glow": 1.0, "light_glows": [1.0, 1.0, 1.0, 1.0],
            "gradient": "",
            # vignette=0：白底四角被压暗会形成灰色渐变，出图要干净白底
            "post": [True, 2.0, 0.0, 1.5, 0.35, 0.0, 0.50, 8.0, 0.03],
            "fade": True, "fog_strength": 0.15,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.80,
        },
    },
    # ── 4. 柔光雾面：大雾化 + 强环境光 + 次表面散射，通透但柔 ──
    "soft": {
        "display": "柔光雾面",
        "display_en": "Soft Haze",
        "tip": "柔光雾面：强半球环境光 + 次表面散射 + 大景深雾化，氛围感/大分子群",
        "state": {
            "spec_model": 1, "gloss": 0.05, "roughness": 0.60,
            "coat_strength": 0.80, "coat_roughness": 0.10,
            "sss_strength": 0.25, "soft_term": 0.50,
            "hemi_enabled": True, "hemi_top": [0.22, 0.24, 0.30],
            "hemi_bottom": [0.12, 0.12, 0.14], "hemi_intensity": 0.75,
            "light_count": 3, "light_dirs": _IBO_DIRS,
            "light_glow": 2.2, "light_glows": [2.2, 2.2, 2.2, 2.2],
            "gradient": "",
            "post": [True, 1.5, 0.0, 2.0, 0.35, 0.0, 0.25, 10.0, 0.03],
            "fade": True, "fog_strength": 1.00,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.70,
        },
    },
    # ── 5. 金属光泽：材质球着色 + 深底 + 强暗角，最"产品图"的一套 ──
    "metal": {
        "display": "金属光泽",
        "display_en": "Metallic",
        "tip": "金属光泽：Matcap 材质球（metal）+ 高分光不透明度 + 强暗角，漆面金属球观感",
        "state": {
            "spec_model": 3, "matcap": "metal", "gloss": 0.50, "roughness": 0.15,
            "sss_strength": 0.0, "soft_term": 0.0,
            "hemi_enabled": False, "hemi_top": [0.18, 0.18, 0.18],
            "hemi_bottom": [0.035, 0.035, 0.035], "hemi_intensity": 0.25,
            "light_count": 3, "light_dirs": _IBO_DIRS,
            "light_glow": 1.0, "light_glows": [1.0, 1.0, 1.0, 1.0],
            "gradient": "",
            # 金属不能开色调映射：ACES 会把暗本体整体抬亮（0.2→0.37），
            # 金属的对比就靠"暗本体 + 亮反光"，所以这里 tone=0、雾化也压低。
            "post": [True, 2.0, 0.0, 2.0, 0.0, 0.0, 0.40, 8.0, 0.03],
            "fade": True, "fog_strength": 0.10,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.95,
        },
    },
    # ── 6. 暖色影棚：清漆层 + 暖顶光冷地光 + 竖向背景渐变 ──
    "studio": {
        "display": "暖色影棚",
        "display_en": "Warm Studio",
        "tip": "暖色影棚：Clear-coat 清漆 + 暖顶光/冷地光 + 轻微色调映射与暗角",
        "state": {
            "spec_model": 2, "gloss": 0.15, "roughness": 0.35,
            "coat_strength": 1.50, "coat_roughness": 0.06,
            "sss_strength": 0.0, "soft_term": 0.20,
            "hemi_enabled": True, "hemi_top": [0.28, 0.22, 0.16],
            "hemi_bottom": [0.05, 0.06, 0.09], "hemi_intensity": 0.40,
            "light_count": 3,
            "light_dirs": [(0.55, 0.45, 0.70), (-0.45, -0.30, 0.84),
                           (0.40, -0.35, 0.85), (0.0, 0.0, 1.0)],
            "light_glow": 1.2, "light_glows": [1.2, 1.2, 1.2, 1.2],
            "gradient": "",
            "post": [True, 1.5, 0.0, 2.0, 0.45, 0.0, 0.30, 8.0, 0.03],
            "fade": True, "fog_strength": 0.30,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.85,
        },
    },
}

# 下拉框顺序
LOOK_ORDER = ("glass", "matte", "journal", "soft", "metal", "studio")

# 下拉框条目：(显示名, key)；key 为空表示"不改变现有观感"
LOOK_ITEMS = [("（保持当前观感）", "")] + [
    (LOOK_PRESETS[k]["display"], k) for k in LOOK_ORDER
]

LOOK_ITEMS_EN = [("(Keep current look)", "")] + [
    (LOOK_PRESETS[k]["display_en"], k) for k in LOOK_ORDER
]


def look_items(lang="zh"):
    """按语言取下拉条目 [(显示名, key), ...]。"""
    return LOOK_ITEMS_EN if str(lang).startswith("en") else LOOK_ITEMS


def look_state(key):
    """取某个观感预设的状态字典（副本，调用方可安全修改）。"""
    entry = LOOK_PRESETS.get(key)
    if not entry:
        return None
    st = dict(entry["state"])
    for k, v in list(st.items()):
        if isinstance(v, list):
            st[k] = [list(x) if isinstance(x, (list, tuple)) else x for x in v]
    return st


def look_tip(key):
    entry = LOOK_PRESETS.get(key)
    return entry["tip"] if entry else ""
