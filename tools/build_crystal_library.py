# -*- coding: utf-8 -*-
"""Build the bundled high-school crystal library from Avogadro2's COD CIF set.

Source: ``C:\\Program Files\\Avogadro2\\share\\avogadro2\\crystals``
(Open Chemistry "crystals" data plugin, public-domain COD / AMCSD / IZA
structures; each CIF keeps its original citation header).

Only the structures a Chinese high-school teacher actually needs are copied
into ``molstudio/assets/crystal_library`` so the shipped application stays
small and completely offline.  Two structures missing from the COD set
(simple-cubic Po and a teaching dry-ice cell) are generated as minimal CIFs
and clearly labelled as teaching models.

Run again after editing ENTRIES::

    python tools/build_crystal_library.py
"""
from __future__ import annotations

import json
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = r"C:\Program Files\Avogadro2\share\avogadro2\crystals"
DEST = os.path.join(ROOT, "molstudio", "assets", "crystal_library")
CIF_DIR = os.path.join(DEST, "cif")
PNG_DIR = os.path.join(DEST, "preview")

CATEGORY_ORDER = ("molecular", "covalent", "ionic", "metallic",
                  "mixed", "advanced")
CATEGORY_LABELS = {
    "molecular": ("分子晶体", "Molecular crystals"),
    "covalent": ("共价晶体", "Covalent crystals"),
    "ionic": ("离子晶体", "Ionic crystals"),
    "metallic": ("金属晶体", "Metallic crystals"),
    "mixed": ("混合型与过渡晶体", "Mixed / transition crystals"),
    "advanced": ("高考常考与新材料", "Exam cells & advanced materials"),
}
LEVEL_LABELS = {1: ("课本必建", "Textbook"),
                2: ("高考常考", "Exam"),
                3: ("拓展", "Extension")}

# (source path, id, name_zh, name_en, formula, category, level,
#  structure_type, coordination, cell_contents, teaching_point, description_zh,
#  aliases)
ENTRIES = [
    ("halides/NaCl-Halite.cif", "nacl-halite", "氯化钠（岩盐）",
     "Sodium chloride (halite)", "NaCl", "ionic", 1,
     "面心立方，Na⁺ 与 Cl⁻ 各自构成面心格子", "6:6", "4 Na⁺ + 4 Cl⁻",
     "均摊法入门、配位数 6、a³ρN_A = 4M",
     "离子晶体最经典的代表。每个离子被 6 个异号离子包围，晶胞里含 4 个 NaCl。",
     ["NaCl", "食盐", "岩盐", "Halite"]),
    ("halides/CsCl.cif", "cscl", "氯化铯", "Caesium chloride", "CsCl",
     "ionic", 1, "简单立方，Cs⁺ 在体心、Cl⁻ 在顶点（不是体心立方格子）",
     "8:8", "1 Cs⁺ + 1 Cl⁻", "与 NaCl 对比；别把两种不同原子答成体心立方堆积",
     "配位数 8 的离子晶体。两套简单立方格子互相穿插，晶胞里只有 1 个 CsCl。",
     ["CsCl", "氯化铯"]),
    ("elements/C-Diamond.cif", "c-diamond", "金刚石", "Diamond", "C",
     "covalent", 1, "金刚石型立方 Fd-3m", "4", "8 C",
     "sp³、键角 109°28′、最小六元环、C 与 C—C 键数 1:2",
     "每个碳与 4 个碳以共价键相连形成三维网络，是共价晶体硬度的来源。",
     ["金刚石", "钻石", "Diamond"]),
    ("elements/Si-Silicon.cif", "si-silicon", "晶体硅", "Silicon", "Si",
     "covalent", 1, "金刚石型立方 Fd-3m", "4", "8 Si",
     "与金刚石同构、半导体材料、熔沸点比较",
     "与金刚石同构的共价晶体，Si—Si 键更长更弱，熔点低于金刚石。",
     ["硅", "晶体硅", "Silicon"]),
    ("oxides/SiO2-Quartz-alpha.cif", "sio2-quartz-alpha", "低温石英 α-SiO₂",
     "alpha-Quartz", "SiO2", "covalent", 1, "三方 P3₂21，SiO₄ 四面体共顶连接",
     "Si 4 / O 2", "Si:O = 1:2", "每个 Si 占 4 个「半个 O」；最小环 12 原子",
     "教材用的「低温石英」。每个硅连 4 个氧、每个氧连 2 个硅，不存在 SiO₂ 分子。",
     ["石英", "二氧化硅", "Quartz", "SiO2"]),
    ("ice/H2O-Ice-Ih.cif", "h2o-ice-ih", "冰 Ih", "Ice Ih", "H2O",
     "molecular", 1, "六方，氢键四面体网络", "氢键 4", "约 2 mol 氢键 / mol H₂O",
     "氢键的方向性与饱和性、冰的密度小于水",
     "水分子靠氢键形成疏松的四面体网络，所以冰能浮在水面上。",
     ["冰", "Ice", "H2O"]),
    ("__generated__/dry-ice.cif", "dry-ice", "干冰（教学模型）",
     "Dry ice (teaching model)", "CO2", "molecular", 1,
     "面心立方分子中心，4 个 CO₂ / 晶胞", "12", "4 CO₂",
     "配位数 12、范德华力、与冰的氢键对比",
     "教学简化模型：4 个 CO₂ 分子按面心立方排布，分子取向统一；真实干冰为 Pa3 交错取向。",
     ["干冰", "固体二氧化碳", "Dry ice", "CO2"]),
    ("elements/I-Iodine.cif", "i-iodine", "碘", "Iodine", "I2",
     "molecular", 1, "正交分子晶体，I₂ 分子有序排列", "—", "I₂ 分子",
     "分子晶体熔沸点低、范德华力随相对分子质量增大",
     "卤素单质分子晶体的代表，升华时破坏的是分子间作用力而非 I—I 键。",
     ["碘", "I2", "Iodine"]),
    ("elements/S8-Sulfur-alpha.cif", "s8-sulfur-alpha", "斜方硫 S₈",
     "alpha-Sulfur", "S8", "molecular", 1, "正交分子晶体，皇冠状 S₈ 环",
     "—", "S₈ 分子", "分子晶体与共价晶体的区分、S₈ 环状分子",
     "由 S₈ 环状分子堆砌而成，是分子晶体而非共价晶体。",
     ["硫", "斜方硫", "S8"]),
    ("__generated__/white-phosphorus.cif", "p4-white-phosphorus",
     "白磷 P₄（教学模型）", "White phosphorus P4 (teaching model)", "P4",
     "molecular", 1, "正四面体 P₄ 分子置于立方晶胞中心", "P—P 四面体",
     "1 个 P₄ 分子", "分子晶体、P₄ 正四面体、键角 60°",
     "教学模型：一个 P₄ 正四面体分子，P—P 键长约 2.21 Å；不是白磷晶体的"
     "真实周期性结构，只用来讲清「分子晶体由独立分子组成」。",
     ["白磷", "P4", "White phosphorus"]),
    ("elements/Cu-Copper.cif", "cu-copper", "铜（面心立方最密堆积）",
     "Copper (fcc)", "Cu", "metallic", 1, "A1 型面心立方最密堆积",
     "12", "4 Cu", "ABCABC、空间利用率 74%、4r = √2 a",
     "金属晶体最密堆积的代表，电子气理论解释导电与延展性。",
     ["铜", "Cu", "Copper", "fcc"]),
    ("elements/Fe-Iron-alpha.cif", "fe-iron-alpha", "α-铁（体心立方）",
     "alpha-Iron (bcc)", "Fe", "metallic", 1, "A2 型体心立方堆积",
     "8", "2 Fe", "空间利用率 68%、4r = √3 a",
     "常温下铁的堆积方式，与 γ-铁的面心立方对比可讲钢的热处理。",
     ["铁", "α-Fe", "bcc"]),
    ("elements/Mg-Magnesium.cif", "mg-magnesium", "镁（六方最密堆积）",
     "Magnesium (hcp)", "Mg", "metallic", 1, "A3 型六方最密堆积",
     "12", "六棱柱 6 原子（原胞 2）", "ABAB、六棱柱顶点按 1/6 均摊",
     "六方最密堆积的代表，与面心立方同为 74% 空间利用率。",
     ["镁", "Mg", "hcp"]),
    ("__generated__/po-simple-cubic.cif", "po-simple-cubic",
     "钋（简单立方，教学模型）", "Polonium (simple cubic, model)", "Po",
     "metallic", 1, "简单立方堆积", "6", "1 Po",
     "空间利用率 52%、配位数 6，四种金属堆积模型里最疏松的一种",
     "教学模型：唯一采取简单立方堆积的金属，用来讲清堆积模型的配位数差别。",
     ["钋", "Po", "简单立方"]),
    ("elements/Al-Aluminum.cif", "al-aluminum", "铝（面心立方）",
     "Aluminum (fcc)", "Al", "metallic", 1, "A1 型面心立方最密堆积",
     "12", "4 Al", "与铜同构、金属键强弱比较",
     "常见的面心立方金属，可与 Na、Mg 一起比较金属键与熔点。",
     ["铝", "Al"]),
    ("elements/Na-Sodium.cif", "na-sodium", "钠（体心立方）",
     "Sodium (bcc)", "Na", "metallic", 1, "A2 型体心立方堆积", "8",
     "2 Na", "与 α-铁同构、碱金属熔点递变",
     "体心立方堆积的碱金属代表。",
     ["钠", "Na", "bcc"]),
    ("elements/Zn-Zinc.cif", "zn-zinc", "锌（六方最密堆积）",
     "Zinc (hcp)", "Zn", "metallic", 1, "A3 型六方最密堆积", "12",
     "六棱柱 6 原子", "与镁同构", "六方最密堆积的另一常见例子。",
     ["锌", "Zn", "hcp"]),
    ("elements/C-Graphite.cif", "c-graphite", "石墨（混合型晶体）",
     "Graphite", "C", "mixed", 1, "六方层状，层内 sp² 六元环",
     "层内 3", "每个六元环 2 C", "sp²、层间范德华力、导电、混合型晶体",
     "层内共价键、层间范德华力、还有类似金属键的离域电子，兼具三类晶体特征。",
     ["石墨", "Graphite"]),
    ("oxides/Al2O3-Corundum.cif", "al2o3-corundum", "刚玉 α-Al₂O₃",
     "Corundum", "Al2O3", "mixed", 1, "三方 R-3c，O 密堆积 + Al 填八面体空隙",
     "Al 6 / O 4", "Z = 6", "教材「过渡晶体」概念、电解铝与冰晶石",
     "偏向共价晶体的过渡晶体，性质上常按共价晶体处理。",
     ["刚玉", "氧化铝", "Corundum"]),
    ("oxides/Na2O.cif", "na2o", "氧化钠", "Sodium oxide", "Na2O",
     "mixed", 1, "反萤石型", "Na 4 / O 8", "Z = 4",
     "偏向离子晶体的过渡晶体",
     "教材用来说明「过渡晶体」：通常当作离子晶体处理。",
     ["氧化钠", "Na2O"]),

    ("halides/CaF2-Fluorite.cif", "caf2-fluorite", "萤石 CaF₂",
     "Fluorite", "CaF2", "advanced", 2, "立方 Fm-3m，F⁻ 填满全部四面体空隙",
     "Ca 8 / F 4", "4 Ca²⁺ + 8 F⁻", "均摊法反推化学式、四面体空隙",
     "高考高频晶胞：钙离子面心立方，氟离子占满 8 个四面体空隙。",
     ["萤石", "氟化钙", "CaF2"]),
    ("sulfides/ZnS-Sphalerite.cif", "zns-sphalerite", "闪锌矿 ZnS",
     "Sphalerite (zinc blende)", "ZnS", "advanced", 2,
     "立方 F-43m，Zn 占半数四面体空隙", "4:4", "4 Zn²⁺ + 4 S²⁻",
     "与金刚石同构、四面体空隙占据率",
     "高考高频晶胞，结构可看成金刚石中的 C 交替换成 Zn 和 S。",
     ["闪锌矿", "ZnS", "Zinc blende"]),
    ("sulfides/ZnS-Wurtzite-2H.cif", "zns-wurtzite", "纤锌矿 ZnS",
     "Wurtzite", "ZnS", "advanced", 2, "六方 P6₃mc", "4:4",
     "2 ZnS / 原胞", "六方晶胞均摊、与闪锌矿对比",
     "同一种化合物的六方多晶型，用来讲「组成相同、结构不同」。",
     ["纤锌矿", "Wurtzite"]),
    ("titanates/SrTiO3-Tausonite.cif", "srtio3-perovskite",
     "钛酸锶（理想立方钙钛矿）", "Strontium titanate (cubic perovskite)",
     "SrTiO3", "advanced", 2, "立方 Pm-3m，ABO₃", "Ti 6 / Sr 12",
     "1 Sr + 1 Ti + 3 O", "分数坐标、密度、晶胞参数",
     "高考钙钛矿题的理想立方模型：A 在顶点、B 在体心、O 在面心。",
     ["钙钛矿", "SrTiO3", "Perovskite"]),
    ("titanates/CaTiO3-Perovskite.cif", "catio3-perovskite",
     "钛酸钙（真实正交钙钛矿）", "Calcium titanate (orthorhombic)",
     "CaTiO3", "advanced", 2, "正交 Pbnm（实温相）", "Ti 6 / Ca 12",
     "Z = 4", "与理想立方模型对比、八面体倾斜",
     "真实矿物室温下是正交畸变结构；教材和高考题常用理想化的立方模型。",
     ["钙钛矿", "CaTiO3"]),
    ("carbides/SiC-3C-beta.cif", "sic-3c", "碳化硅 3C-SiC",
     "beta-Silicon carbide", "SiC", "advanced", 2,
     "立方 F-43m，闪锌矿型", "4:4", "4 Si + 4 C",
     "与金刚石同构、密度计算、共价晶体熔点比较",
     "俗称金刚砂，硬度高，是共价晶体与半导体材料的常考例子。",
     ["碳化硅", "金刚砂", "SiC"]),
    ("nitrides/BN.cif", "bn-hexagonal", "六方氮化硼（白石墨）",
     "Hexagonal boron nitride", "BN", "advanced", 2,
     "六方 P6₃/mmc，类石墨层状", "层内 3", "层状", "六元环计数、与石墨对比",
     "结构与石墨类似的层状氮化硼，常称「白石墨」，是高频情境题材料。",
     ["六方氮化硼", "白石墨", "h-BN"]),
    ("nitrides/AlN.cif", "aln", "氮化铝", "Aluminum nitride", "AlN",
     "advanced", 2, "六方纤锌矿型", "4:4", "2 AlN / 原胞",
     "晶胞密度、配位数、第三代半导体",
     "常与 BP、GaAs 一起出现在高考晶胞计算题里。",
     ["氮化铝", "AlN"]),
    ("phosphides/BP.cif", "bp", "磷化硼", "Boron phosphide", "BP",
     "advanced", 2, "立方闪锌矿型", "4:4", "4 B + 4 P",
     "密度计算、与金刚石同构", "教材与考题中常与 SiC、AlN 并列的四面体结构。",
     ["磷化硼", "BP"]),
    ("arsenides/GaAs.cif", "gaas", "砷化镓", "Gallium arsenide", "GaAs",
     "advanced", 2, "立方闪锌矿型", "4:4", "4 Ga + 4 As",
     "与 ZnS 同构、半导体情境", "闪锌矿型半导体，晶胞计算高频材料。",
     ["砷化镓", "GaAs"]),
    ("oxides/CaO-Lime.cif", "cao-lime", "氧化钙（NaCl 型）",
     "Calcium oxide (rock salt)", "CaO", "advanced", 2, "立方 Fm-3m",
     "6:6", "4 CaO", "与 NaCl 同构、离子半径与熔点比较",
     "与 NaCl 同构，高考常用来比较离子半径对晶格能和熔点的影响。",
     ["氧化钙", "CaO"]),
    ("halides/AlNa3F6-Cryolite.cif", "cryolite", "冰晶石 Na₃AlF₆",
     "Cryolite", "Na3AlF6", "advanced", 2, "单斜，AlF₆ 八面体",
     "Al 6", "Z = 2", "电解铝情境、配合物 [AlF₆]³⁻",
     "电解氧化铝时用来降低熔点的熔剂，可联系配位键与配合物。",
     ["冰晶石", "Cryolite"]),
    ("oxides/SiO2-Cristobalite.cif", "sio2-cristobalite", "方石英 SiO₂",
     "Cristobalite", "SiO2", "advanced", 2, "立方 / 四方，SiO₄ 四面体网络",
     "Si 4 / O 2", "Si:O = 1:2", "与低温石英对比、SiO₂ 多晶型",
     "二氧化硅的高温晶型，适合讲同素异形与多晶型。",
     ["方石英", "Cristobalite"]),

    ("elements/Ag-Silver.cif", "ag-silver", "银（面心立方）", "Silver (fcc)",
     "Ag", "metallic", 3, "A1 型面心立方最密堆积", "12", "4 Ag",
     "与铜、金同为 fcc", "面心立方金属的补充例子。", ["银", "Ag"]),
    ("elements/Au-Gold.cif", "au-gold", "金（面心立方）", "Gold (fcc)",
     "Au", "metallic", 3, "A1 型面心立方最密堆积", "12", "4 Au",
     "与铜、银同为 fcc", "面心立方金属的补充例子。", ["金", "Au"]),
    ("elements/K-Potassium.cif", "k-potassium", "钾（体心立方）",
     "Potassium (bcc)", "K", "metallic", 3, "A2 型体心立方堆积", "8",
     "2 K", "碱金属堆积与熔点递变", "与钠同构的碱金属。", ["钾", "K"]),
    ("elements/Ti-Titanium-alpha.cif", "ti-titanium-alpha",
     "α-钛（六方最密堆积）", "alpha-Titanium (hcp)", "Ti", "metallic", 3,
     "A3 型六方最密堆积", "12", "六棱柱 6 原子", "与镁、锌同为 hcp",
     "六方最密堆积的第三个例子。", ["钛", "Ti"]),
    ("elements/Fe-Iron-gamma.cif", "fe-iron-gamma", "γ-铁（面心立方）",
     "gamma-Iron (fcc)", "Fe", "metallic", 3, "A1 型面心立方最密堆积",
     "12", "4 Fe", "与 α-铁对比、钢的热处理",
     "高温相铁，与 α-铁对比可讲同素异构转变与碳原子间隙。", ["γ-Fe"]),
    ("elements/C-Lonsdaleite.cif", "c-lonsdaleite", "六方金刚石",
     "Lonsdaleite", "C", "covalent", 3, "六方，类纤锌矿网络", "4",
     "4 C / 原胞", "与金刚石对比、sp³ 网络",
     "碳的另一种 sp³ 三维网络结构，适合做同素异形体拓展。",
     ["六方金刚石", "Lonsdaleite"]),
    ("carbonates/CaCO3-Calcite.cif", "caco3-calcite", "方解石 CaCO₃",
     "Calcite", "CaCO3", "advanced", 3, "三方 R-3c", "Ca 6", "Z = 6",
     "碳酸根平面三角、离子晶体中的原子团",
     "含原子团的离子晶体，可联系碳酸根的空间构型与双折射。",
     ["方解石", "Calcite"]),
    ("oxides/TiO2-Rutile.cif", "tio2-rutile", "金红石 TiO₂",
     "Rutile", "TiO2", "advanced", 3, "四方 P4₂/mnm", "Ti 6 / O 3",
     "Z = 2", "配位数 6:3、空隙占据",
     "常见氧化物晶胞，适合讲非 1:1 配位与四方晶系。",
     ["金红石", "Rutile"]),
    ("elements/P-Phosphorus.cif", "p-phosphorus-black", "黑磷（正交层状）",
     "Black phosphorus", "P", "mixed", 3, "正交层状 Bmeb", "层内 3", "层状",
     "层状半导体、与石墨及白磷对比",
     "层状单质磷，近年二维材料情境题常见；与上面的白磷 P₄ 分子正好构成"
     "同素异形体对比。", ["黑磷", "Black phosphorus"]),
    ("ice/H2O-Ice-II.cif", "h2o-ice-ii", "冰 II（高压相）",
     "Ice II", "H2O", "molecular", 3, "三方 R-3", "氢键 4", "高压相",
     "同种分子、不同氢键网络", "冰的多晶型，说明氢键网络可以有很多种排布。",
     ["冰 II"]),
]

PO_CIF = """\
# MolStudio teaching model: simple-cubic polonium.
# This is NOT an experimental COD structure; it is a minimal teaching cell.
data_molstudio_po
_chemical_formula_sum 'Po'
_chemical_name_common 'Polonium (simple cubic teaching model)'
_symmetry_space_group_name_H-M 'P m -3 m'
_space_group_IT_number 221
_cell_length_a 3.345
_cell_length_b 3.345
_cell_length_c 3.345
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_space_group_symop_operation_xyz
'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Po Po 0.0 0.0 0.0
"""

DRY_ICE_CIF = """\
# MolStudio teaching model: dry ice, four CO2 molecules on an fcc lattice.
# Simplified: all molecules share one body-diagonal orientation; real dry ice
# (Pa3) uses alternating orientations.  Not an experimental COD structure.
data_molstudio_dry_ice
_chemical_formula_sum 'C O2'
_chemical_name_common 'Dry ice (fcc teaching model)'
_symmetry_space_group_name_H-M 'P 1'
_space_group_IT_number 1
_cell_length_a 5.62
_cell_length_b 5.62
_cell_length_c 5.62
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_space_group_symop_operation_xyz
'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
C1 C 0.000 0.000 0.000
O1 O 0.119 0.119 0.119
O2 O -0.119 -0.119 -0.119
C2 C 0.500 0.500 0.000
O3 O 0.619 0.619 0.119
O4 O 0.381 0.381 -0.119
C3 C 0.500 0.000 0.500
O5 O 0.619 0.119 0.619
O6 O 0.381 -0.119 0.381
C4 C 0.000 0.500 0.500
O7 O 0.119 0.619 0.619
O8 O -0.119 0.381 0.381
"""

def _white_phosphorus_cif():
    """One P4 tetrahedron (P-P 2.21 A) centred in an 8 A cubic cell."""
    a = 8.0
    bond = 2.21
    unit = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
            (0.5, 0.8660254, 0.0), (0.5, 0.2886751, 0.8164966)]
    points = [[v * bond for v in vertex] for vertex in unit]
    centre = [sum(p[i] for p in points) / 4.0 for i in range(3)]
    frac = [[(p[i] - centre[i] + a / 2.0) / a for i in range(3)]
            for p in points]
    rows = "\n".join(
        "P%d P %.6f %.6f %.6f" % (i + 1, *f)
        for i, f in enumerate(frac))
    return """\
# MolStudio teaching model: one P4 tetrahedron, NOT the real white-P crystal.
data_molstudio_white_phosphorus
_chemical_formula_sum 'P4'
_chemical_name_common 'White phosphorus P4 (teaching model)'
_symmetry_space_group_name_H-M 'P 1'
_space_group_IT_number 1
_cell_length_a 8.0
_cell_length_b 8.0
_cell_length_c 8.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_space_group_symop_operation_xyz
'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
%s
""" % rows


GENERATED = {
    "__generated__/po-simple-cubic.cif": PO_CIF,
    "__generated__/dry-ice.cif": DRY_ICE_CIF,
    "__generated__/white-phosphorus.cif": _white_phosphorus_cif(),
}

# CIF tags may contain hyphens, e.g. _symmetry_space_group_name_H-M
_TAG_RE = re.compile(r"^(_[A-Za-z0-9_-]+)\s+(.+?)\s*$", re.M)


def cif_metadata(path):
    """Pull the crystallographic facts straight out of the CIF header."""
    text = open(path, encoding="utf-8", errors="replace").read()
    tags = {}
    for key, value in _TAG_RE.findall(text):
        low = key.lower()
        if low not in tags:
            tags[low] = value.strip().strip("'\"")
    def num(key):
        raw = re.sub(r"\(.*?\)", "", tags.get(key, ""))
        try:
            return float(raw)
        except ValueError:
            return None
    cell = [num("_cell_length_a"), num("_cell_length_b"),
            num("_cell_length_c"), num("_cell_angle_alpha"),
            num("_cell_angle_beta"), num("_cell_angle_gamma")]
    lengths = [v for v in cell[:3] if v is not None]
    if lengths and max(lengths) - min(lengths) < 1e-6:
        cell_text = "a = %.3f Å" % lengths[0]
    elif lengths:
        cell_text = "a=%.3f b=%.3f c=%.3f Å" % tuple(lengths[:3])
    else:
        cell_text = ""
    sg = tags.get("_symmetry_space_group_name_h-m", "")
    it = tags.get("_space_group_it_number", "")
    space_group = ("%s (%s)" % (sg, it)).strip() if sg or it else ""
    return {
        "space_group": space_group,
        "cell": cell_text,
        "cod": tags.get("_cod_database_code", ""),
        "formula_cif": tags.get("_chemical_formula_sum", ""),
    }


def main():
    os.makedirs(CIF_DIR, exist_ok=True)
    os.makedirs(PNG_DIR, exist_ok=True)
    out = []
    for row in ENTRIES:
        (src, cid, name_zh, name_en, formula, category, level,
         structure_type, coordination, contents, point, desc, aliases) = row
        generated = src in GENERATED
        if generated:
            cif_name = os.path.basename(src)
            with open(os.path.join(CIF_DIR, cif_name), "w",
                      encoding="utf-8") as fh:
                fh.write(GENERATED[src])
            png_src = None
        else:
            src_path = os.path.join(SOURCE, *src.split("/"))
            if not os.path.isfile(src_path):
                raise SystemExit("missing source CIF: " + src_path)
            cif_name = os.path.basename(src)
            shutil.copy2(src_path, os.path.join(CIF_DIR, cif_name))
            png_src = os.path.splitext(src_path)[0] + ".png"
        png_name = ""
        if png_src and os.path.isfile(png_src):
            png_name = os.path.splitext(cif_name)[0] + ".png"
            shutil.copy2(png_src, os.path.join(PNG_DIR, png_name))
        meta = cif_metadata(os.path.join(CIF_DIR, cif_name))
        source_note = (
            "MolStudio 教学模型（非实验结构）" if generated else
            ("Avogadro2 crystals / COD %s" % meta["cod"] if meta["cod"]
             else "Avogadro2 crystals / COD"))
        out.append({
            "id": cid,
            "name_zh": name_zh,
            "name_en": name_en,
            "formula": formula,
            "category": category,
            "level": level,
            "file": "cif/" + cif_name,
            "preview": ("preview/" + png_name) if png_name else "",
            "aliases": aliases,
            "structure_type": structure_type,
            "coordination": coordination,
            "cell_contents": contents,
            "teaching_point": point,
            "description_zh": desc,
            "description_en": "",
            "space_group": meta["space_group"],
            "cell": meta["cell"],
            "source": source_note,
            "generated": generated,
        })
        print("  %-28s %-10s %s" % (cid, category, meta["cell"]),
              flush=True)

    manifest = {
        "version": 1,
        "title_zh": "中学晶体结构库",
        "title_en": "School crystal structure library",
        "source_note": (
            "Curated from the Avogadro2 'crystals' data plugin "
            "(https://github.com/openchemistry/crystals, public-domain "
            "structures from the Crystallography Open Database / AMCSD / IZA). "
            "Each CIF keeps its original citation header. Two cells are "
            "clearly labelled MolStudio teaching models, not experimental data."),
        "categories": [
            {"key": key,
             "label_zh": CATEGORY_LABELS[key][0],
             "label_en": CATEGORY_LABELS[key][1]}
            for key in CATEGORY_ORDER
        ],
        "levels": [
            {"value": k, "label_zh": v[0], "label_en": v[1]}
            for k, v in LEVEL_LABELS.items()
        ],
        "crystals": out,
    }
    with open(os.path.join(DEST, "manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    # Drop assets left over from an older curation (e.g. a renamed CIF).
    keep_cif = {os.path.basename(item["file"]) for item in out}
    keep_png = {os.path.basename(item["preview"])
                for item in out if item["preview"]}
    for folder, keep in ((CIF_DIR, keep_cif), (PNG_DIR, keep_png)):
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name not in keep and os.path.isfile(path):
                os.remove(path)
                print("  removed stale asset:", name, flush=True)

    readme = os.path.join(DEST, "README.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(
            "# 中学晶体结构库\n\n"
            "本目录是 MolStudio「结构库 → 晶体」页的离线数据，共 %d 个晶胞。\n"
            "运行时只读静态 CIF 与 PNG 预览，不需要联网，也不依赖 Avogadro2。\n\n"
            "## 数据来源与致谢\n\n"
            "绝大多数 CIF 来自 Avogadro2 自带的 `crystals` 数据插件：\n"
            "Geoffrey Hutchison 等，Open Chemistry crystals data set，"
            "https://github.com/openchemistry/crystals（public domain）。\n"
            "原始结构来自 Crystallography Open Database（COD，"
            "http://www.crystallography.net/）、American Mineralogist "
            "Crystal Structure Database（AMCSD）与 International Zeolite "
            "Association。每个 CIF 都保留了原始文件头里的文献与数据库编号，"
            "在此向 COD、AMCSD 及原结构测定者致谢。\n\n"
            "其中 `po-simple-cubic.cif`（简单立方钋）、`dry-ice.cif`（干冰）"
            "与 `white-phosphorus.cif`（白磷 P₄）是 MolStudio 为教学补写的"
            "**简化模型**，不是实验结构：干冰把 4 个 CO₂ 分子按面心立方排布"
            "并统一取向（真实 Pa3 结构分子取向交错），白磷只放了一个 P₄ "
            "四面体分子。请在课堂上说明这一点。\n\n"
            "冰 Ih、α-石英、CaTiO₃ 等 CIF 是实测结构，与教材里的理想化模型"
            "（例如理想立方钙钛矿、P6₃/mmc 冰）可能略有差别；"
            "库里另收 `SrTiO3-Tausonite.cif` 作为理想立方钙钛矿模型。\n\n"
            "## 重新生成\n\n"
            "```powershell\npython tools/build_crystal_library.py\n```\n"
            % len(out))
    print("WROTE %d crystals -> %s" % (len(out), DEST), flush=True)


if __name__ == "__main__":
    main()
