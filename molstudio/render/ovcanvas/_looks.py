"""
出图观感预设（Look presets）
================================================================
一键把**布光 + 材质 + 后处理 + 背景**打包成一套连贯的观感。景深雾化
默认关闭，用户仍可在画布参数中手动开启。
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
# 所有预设统一用纯白背景（出图/投稿首选）。若用户手动开启雾化，终色仍取自
# 背景色，深色背景不会错误地混成白色。
_WHITE = [1.0, 1.0, 1.0, 1.0]


LOOK_PRESETS = {
    # ── 1. 通透玻璃：明亮、低环境对比，轨道图通用 ──
    "glass": {
        "display": "通透玻璃",
        "display_en": "Clear Glass",
        "tip": "明亮通透：GGX 薄高光 + 纯白底，轨道/弱相互作用通用",
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
            "fade": False, "fog_strength": 0.35,
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
            "fade": False, "fog_strength": 0.10,
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
            "fade": False, "fog_strength": 0.15,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.80,
        },
    },
    # ── 4. 柔光雾面：强环境光 + 次表面散射，通透但柔 ──
    "soft": {
        "display": "柔光雾面",
        "display_en": "Soft Haze",
        "tip": "柔光雾面：强半球环境光 + 次表面散射，氛围感/大分子群",
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
            "fade": False, "fog_strength": 1.00,
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
            "fade": False, "fog_strength": 0.10,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.95,
        },
    },
    # ── 6. 暖色影棚：清漆层 + 暖顶光冷地光 + 竖向背景渐变 ──
    # ── 7. Orbital Studio：浅紫底 + 近不透明饱和瓣 + 明显镜面高光 ──
    # 目标观感：轨道瓣光滑、有成形高光、正负相位对比强；球棍像抛光塑料。
    # 与其它预设的区别：按程序分别给粗糙度（orb/atom/bond），并压低背面调暗。
    "orbital-studio": {
        "display": "Orbital Studio",
        "display_en": "Orbital Studio",
        "tip": "浅紫影棚：等值面 0.38 粗糙度 + 0.88 不透明度 + 克制的环境高光；"
               "原子 0.34 / 键 0.40；SSAA 2× + 轻 SSAO；背面调暗减弱到 0.92",
        "state": {
            "spec_model": 1, "gloss": 0.28, "roughness": 0.34,
            "orb_roughness": 0.38, "atom_roughness": 0.34,
            "bond_roughness": 0.40,
            "coat_strength": 0.0, "coat_roughness": 0.10,
            "sss_strength": 0.0, "soft_term": 0.10,
            "hemi_enabled": True,
            "hemi_top": [0.34, 0.31, 0.40],
            "hemi_bottom": [0.14, 0.13, 0.18],
            "hemi_intensity": 0.55,
            "light_count": 3,
            "light_dirs": [(0.42, 0.56, 0.72),
                           (-0.55, 0.30, 0.78),
                           (0.08, -0.62, -0.78),
                           (0.0, 0.0, 1.0)],
            "light_glow": 1.90, "light_glows": [1.90, 1.90, 1.90, 1.0],
            "gradient": "",
            # post = [enabled, scale, edge, edge_radius, tone, vignette, ao, ao_radius, ao_depth]
            "post": [True, 2.0, 0.0, 2.0, 0.0, 0.0, 0.22, 8.0, 0.03],
            "fade": False, "fog_strength": 0.12,
            "bg": [0.72, 0.66, 0.80, 1.0], "bg_grad": None,
            "orb_opacity": 0.88,
            # 环境反射（IBL-lite）：主柔光箱在左上前，侧补光在右前，
            # 背后一盏轮廓箱把剪影"打亮"，与淡紫背景同一色温。
            "env_on": 1, "env_str": 0.50, "env_f0": 0.045,
            "env_amb": [0.15, 0.135, 0.175],
            "env_key_dir": [-0.28, 0.56, 0.78], "env_key_col": [1.00, 0.99, 0.96],
            "env_fill_dir": [0.80, 0.20, 0.50], "env_fill_col": [0.55, 0.58, 0.66],
            "env_rim_dir": [0.10, -0.35, -0.93], "env_rim_col": [0.70, 0.66, 0.74],
            "orb_alpha_mod": 0,
            "back_dim": 0.92,
            "phase_pos": [0.12, 0.22, 0.85],
            "phase_neg": [0.86, 0.12, 0.12],
            "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
            "atom_outline": [True, [0.0, 0.0, 0.0], 0.22],
        },
    },
    # ── 8. Softbox Gloss：参考图放大细节中的镜面反光 ──
    # 与 orbital-studio 的区别不是"把高光调亮"，而是把环境反射换成
    # 长条形柔光箱：外圈宽反光 + 内圈窄亮带 + 独立补光 catchlight；
    # 同时用 3× SSAA 和 4×4 降采样，专门照顾斜边/轨道剪影的锯齿。
    "reference-gloss": {
        "display": "柔光箱高光",
        "display_en": "Softbox Gloss",
        "tip": "参考图高光：纯白背景 + 长条柔光箱倒影 + 锐利补光点；"
               "GGX 低粗糙度、银灰键、正红负蓝，3× SSAA 高精度抗锯齿",
        "state": {
            "spec_model": 1, "gloss": 0.32,
            "roughness": 0.16, "orb_roughness": 0.12,
            "atom_roughness": 0.11, "bond_roughness": 0.20,
            "coat_strength": 0.0, "coat_roughness": 0.10,
            "sss_strength": 0.0, "soft_term": 0.10,
            "hemi_enabled": True,
            "hemi_top": [0.34, 0.31, 0.40],
            "hemi_bottom": [0.14, 0.13, 0.18],
            "hemi_intensity": 0.58,
            "light_count": 3,
            "light_dirs": [(-0.58, 0.70, 0.58),
                           (0.80, 0.18, 0.42),
                           (0.08, -0.50, -0.86),
                           (0.0, 0.0, 1.0)],
            "light_glow": 1.65,
            "light_glows": [1.65, 1.65, 1.65, 1.0],
            "gradient": "",
            # 4×4 降采样由 FRAG_POST 统一完成；这里的 3× 只提高离屏源分辨率。
            # SSAO 保持轻量，避免柔光箱反射的宽亮带被局部压脏。
            "post": [True, 3.0, 0.0, 2.0, 0.12, 0.0, 0.20, 8.0, 0.03],
            "fade": False, "fog_strength": 0.10,
            "bg": list(_WHITE), "bg_grad": None,
            "linear_space": True,
            "orb_opacity": 0.94, "orb_alpha_mod": 0.0,
            # 长条柔光箱反射。env_softbox 打开 _glwidget.py 中的各向异性
            # 反光路径；关掉它时其余环境方向/颜色仍可用于旧式圆形反光。
            "env_on": 1, "env_softbox": 1,
            "env_str": 1.35, "env_f0": 0.10,
            "env_amb": [0.30, 0.27, 0.34],
            "env_key_dir": [-0.30, 0.72, 0.72],
            "env_key_col": [0.96, 0.96, 0.99],
            "env_fill_dir": [0.80, 0.20, 0.52],
            "env_fill_col": [0.92, 0.91, 0.95],
            "env_rim_dir": [0.10, -0.35, -0.93],
            "env_rim_col": [0.76, 0.72, 0.80],
            "back_dim": 0.92,
            "phase_pos": [0.86, 0.035, 0.075],
            "phase_neg": [0.035, 0.105, 0.80],
            "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
            "atom_outline": [False, [0.0, 0.0, 0.0], 0.14],
            "atom_scale": 1.62, "bond_scale": 1.45,
            "bond_color": [0.72, 0.71, 0.74],
            "bond_gloss": 0.22, "bond_diffuse": 0.76,
            "transparency_mode": "oit", "oit_falloff": 4.0,
        },
    },
    # ── 9. Lemon Orbital：文献插图里的柠檬黄 / 浅绿轨道配色 ──
    # 白色底、低对比灰色球棍、半透明奶油黄主相与嫩绿副相。 轨道高光
    # 保持柔和，不做 Softbox 那样的大面积镜面白条，接近期刊图的彩铅质感。
    "lemon-orbital": {
        "display": "柠檬轨道",
        "display_en": "Lemon Orbital",
        "tip": "白底期刊风：深灰碳、银灰键、半透明柠檬黄主相 + 浅绿副相；"
               "柔和 GGX、轻雾化、3× SSAA 高精度抗锯齿",
        "state": {
            "spec_model": 1, "gloss": 0.25, "orb_spec_mul": 0.25,
            "roughness": 0.34, "orb_roughness": 0.48,
            "atom_roughness": 0.24, "bond_roughness": 0.36,
            "coat_strength": 0.0, "coat_roughness": 0.10,
            "sss_strength": 0.0, "soft_term": 0.18,
            "hemi_enabled": True,
            "hemi_top": [0.31, 0.32, 0.33],
            "hemi_bottom": [0.16, 0.16, 0.17],
            "hemi_intensity": 0.62,
            # One key light gives each atom exactly one clean catchlight.
            "light_count": 1,
            "light_dirs": [(-0.58, 0.70, 0.58),
                           (0.0, 0.0, 1.0),
                           (0.0, 0.0, 1.0),
                           (0.0, 0.0, 1.0)],
            "light_glow": 2.10,
            "light_glows": [2.10, 1.0, 1.0, 1.0],
            "gradient": "",
            "post": [True, 3.0, 0.0, 2.0, 0.0, 0.0, 0.12, 8.0, 0.03],
            "fade": False, "fog_strength": 0.08,
            "bg": list(_WHITE), "bg_grad": None,
            "linear_space": True,
            "orb_opacity": 0.80, "orb_alpha_mod": 0.0,
            # A single direct key avoids a second/third specular dot.  The
            # reference reader sees one white catchlight per sphere.
            "env_on": 0, "env_softbox": 0,
            "env_str": 0.42, "env_f0": 0.055,
            "env_amb": [0.18, 0.18, 0.19],
            "env_key_dir": [-0.32, 0.64, 0.70],
            "env_key_col": [1.00, 0.99, 0.94],
            "env_fill_dir": [0.72, 0.10, 0.68],
            "env_fill_col": [0.82, 0.86, 0.90],
            "env_rim_dir": [0.12, -0.48, -0.87],
            "env_rim_col": [0.72, 0.74, 0.72],
            "back_dim": 0.94,
            "phase_pos": [0.96, 0.90, 0.36],
            "phase_neg": [0.50, 0.84, 0.46],
            "mol_style": "GaussView",
            "carbon": [0.36, 0.36, 0.38],
            "hydrogen": [0.93, 0.93, 0.92],
            "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
            "atom_outline": [False, [0.0, 0.0, 0.0], 0.16],
            "atom_scale": 1.55, "bond_scale": 1.25,
            "bond_color": [0.72, 0.72, 0.74],
            "bond_gloss": 0.12, "bond_diffuse": 0.82,
            "transparency_mode": "oit", "oit_falloff": 5.0,
        },
    },
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
            "fade": False, "fog_strength": 0.30,
            "bg": list(_WHITE), "bg_grad": None,
            "orb_opacity": 0.85,
        },
    },
}

# 下拉框顺序
LOOK_ORDER = ("glass", "matte", "journal", "soft", "metal", "studio",
              "orbital-studio", "reference-gloss", "lemon-orbital")

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
