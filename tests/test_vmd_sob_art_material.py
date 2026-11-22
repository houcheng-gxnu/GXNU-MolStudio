# -*- coding: utf-8 -*-
"""VMD 控制台的 sob-art 原子材质必须逐项还原 vcube2.0。"""

from molstudio.core import fchk_orbital as backend


VCUBE_ATOM_CPK = "0.600000 0.400000 30.000000 30.000000"
VCUBE_ATOM_MAT = [
    0.0,   # ambient
    0.65,  # diffuse
    0.5,   # specular
    0.53,  # shininess
    0.15,  # mirror
    1.0,   # opacity
    2.0,   # outline
    0.3,   # outlinewidth
    0.0,   # transmode
]


def _assert_material_defined_before_bind(tcl):
    add = tcl.find("material add _stl_atom")
    bind = tcl.find("mol modmaterial 0 top _stl_atom")
    assert add >= 0
    assert bind > add, "必须先定义原子材质，再把它绑定到 CPK rep"


def test_sob_art_atom_properties_match_vcube_style():
    style = backend.STYLES["sob-art"]
    assert style["atom_cpk"] == VCUBE_ATOM_CPK
    assert style["atom_mat"] == VCUBE_ATOM_MAT
    assert style["lights"] == {
        "0": "on", "1": "on", "2": "off", "3": "on"}
    assert style["c_color"] == "tan"
    assert style["c_rgb"] == "0.700000 0.560000 0.360000"


def test_single_cube_tcl_defines_atom_material_before_binding():
    tcl = backend._style_tcl("sample.cub", 0.05, "sob-art")
    _assert_material_defined_before_bind(tcl)
    assert "mol modstyle 0 top CPK " + VCUBE_ATOM_CPK in tcl
    assert "material change ambient _stl_atom 0.0" in tcl
    assert "material change diffuse _stl_atom 0.65" in tcl
    assert "material change specular _stl_atom 0.5" in tcl
    assert "material change shininess _stl_atom 0.53" in tcl
    assert "material change mirror _stl_atom 0.15" in tcl
    assert "material change outline _stl_atom 2.0" in tcl
    assert "material change outlinewidth _stl_atom 0.3" in tcl


def test_multi_cube_and_molecule_tcl_fix_atom_order():
    multi = backend._gen_multi_orbital_tcl(
        [("sample.cub", "HOMO")], [0.05], "sob-art")
    molecule = backend._style_tcl_mol("sample.xyz", "sob-art")
    _assert_material_defined_before_bind(multi)
    _assert_material_defined_before_bind(molecule)


def test_live_style_recreates_vcube_atom_material():
    tcl = backend._live_style_tcl("sob-art")
    assert "if {[lsearch [material list] _stl_atom] >= 0} {material delete _stl_atom}" in tcl
    _assert_material_defined_before_bind(tcl)
    for prop, value in zip(
            ("ambient", "diffuse", "specular", "shininess", "mirror",
             "opacity", "outline", "outlinewidth", "transmode"),
            VCUBE_ATOM_MAT):
        assert "material change %s _stl_atom %s" % (prop, value) in tcl


def test_igmh_scene_template_also_binds_after_material_definition():
    tcl = backend._IGMH_SCENE_TPL.replace("\\n", "\n")
    _assert_material_defined_before_bind(tcl)


def test_softbox_vmd_style_contract():
    style = backend.STYLES["softbox"]
    assert style["lights"] == {
        "0": "on", "1": "on", "2": "on", "3": "off"}
    assert style["light_positions"] == [
        [-0.58, 0.70, 0.58],
        [0.80, 0.18, 0.42],
        [0.08, -0.50, -0.86],
        [0.0, 0.0, 1.0],
    ]
    assert style["atom_cpk"] == "0.650000 0.290000 30.000000 30.000000"
    assert style["atom_mat"] == [
        0.08, 0.62, 1.0, 0.50, 0.20, 1.0, 0.0, 0.0, 0.0]
    assert style["c_color"] == "gray"
    assert style["c_rgb"] == "0.556900 0.556900 0.556900"
    assert style["pos_color"] == [31, 0.86, 0.035, 0.075]
    assert style["neg_color"] == [32, 0.035, 0.105, 0.80]

    tcl = backend._style_tcl("sample.cub", 0.05, "softbox")
    _assert_material_defined_before_bind(tcl)
    assert "light 0 pos {-0.580000 0.700000 0.580000}" in tcl
    assert "light 1 pos {0.800000 0.180000 0.420000}" in tcl
    assert "light 2 pos {0.080000 -0.500000 -0.860000}" in tcl
    assert "display ambientocclusion on" in tcl
    assert "color Element C gray" in tcl
    assert "color change rgb gray 0.556900 0.556900 0.556900" in tcl
    assert "color change rgb 31 0.86 0.035 0.075" in tcl
    assert "color change rgb 32 0.035 0.105 0.8" in tcl

    molecule = backend._style_tcl_mol("sample.xyz", "softbox")
    multi = backend._gen_multi_orbital_tcl(
        [("sample.cub", "HOMO")], [0.05], "softbox")
    for generated in (molecule, multi):
        assert "light 0 pos {-0.580000 0.700000 0.580000}" in generated
        assert "light 0 on" in generated


def test_switching_back_from_softbox_resets_light_positions():
    tcl = backend._live_style_tcl("sob-art")
    for index in range(4):
        assert "light %d pos default" % index in tcl
    assert "light 0 pos {-0.580000" not in tcl
