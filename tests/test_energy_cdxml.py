# -*- coding: utf-8 -*-
"""Regression tests for the editable ChemDraw energy-profile export."""

import xml.etree.ElementTree as ET

from molstudio.core.energy_cdxml import write_energy_diagram_cdxml


def _cross_cycle_fixture():
    species = [
        {"name": "IM0", "type": "Int", "G": 0.0},
        {"name": "TS1", "type": "TS", "G": 20.0},
        {"name": "IM1 & 返回", "type": "Int", "G": -10.0},
    ]
    cycle2 = [
        {"name": "IM0_C2", "type": "Int", "G": -10.0},
        {"name": "TS1_C2", "type": "TS", "G": 10.0},
        {"name": "IM1_C2", "type": "Int", "G": -20.0},
    ]
    result = {
        "deltaE": 20.0,
        "TDI_idx": 2,
        "TDTS_idx": 1,
        "deltaG_cycle": -10.0,
        "needCycle2": True,
        "cycle2Species": cycle2,
        "TOF": 1.0,
        "T": 298.15,
    }
    return species, result


def test_cross_cycle_export_is_editable_cdxml(tmp_path):
    species, result = _cross_cycle_fixture()
    path = write_energy_diagram_cdxml(
        tmp_path / "cross_cycle",
        species,
        result,
        show_values=True,
        show_tags=True,
        show_grid=True,
        show_span=True,
        line_width=3.0,
        tag_size=12,
    )

    assert path.endswith(".cdxml")
    root = ET.parse(path).getroot()
    assert root.tag == "CDXML"
    assert root.attrib["CreationProgram"] == "GXNU MolStudio"
    assert root.find("page") is not None
    assert root.find("colortable") is not None
    assert root.find("fonttable/font[@name='Arial']") is not None

    # The diagram consists of vector objects, not an embedded image.
    assert len(root.findall(".//graphic")) >= 20
    assert not root.findall(".//bitmap")
    assert not root.findall(".//image")

    texts = ["".join(item.itertext()) for item in root.findall(".//t")]
    assert "IM0_C2" in texts
    assert "IM1 & 返回" in texts
    assert "δE = 20.0" in texts
    assert "Reaction Coordinate" in texts

    # Both catalytic cycles and the span marker are integral editable groups.
    assert len(root.findall(".//group")) == 3
    ids = [item.attrib["id"] for item in root.iter() if "id" in item.attrib]
    assert len(ids) == len(set(ids))
    arrow_ids = {item.attrib["id"] for item in root.findall(".//arrow")}
    graphics = root.findall(".//graphic")
    assert all(item.attrib["SupersededBy"] in arrow_ids for item in graphics)


def test_export_respects_label_visibility_settings(tmp_path):
    species = [
        {"name": "Reactant", "type": "Int", "G": 0.0},
        {"name": "TS1", "type": "TS", "G": 25.0},
        {"name": "Product", "type": "Int", "G": -10.0},
    ]
    result = {
        "deltaE": 25.0,
        "TDI_idx": 0,
        "TDTS_idx": 1,
        "deltaG_cycle": -10.0,
        "needCycle2": False,
        "cycle2Species": [],
        "TOF": 1.0,
        "T": 298.15,
    }
    path = write_energy_diagram_cdxml(
        tmp_path / "simple.cdxml",
        species,
        result,
        show_values=False,
        show_tags=False,
        show_grid=False,
        show_span=False,
    )
    root = ET.parse(path).getroot()
    texts = ["".join(item.itertext()) for item in root.findall(".//t")]

    assert "Reactant" not in texts
    assert "25.0" not in texts
    assert not any(text.startswith("δE =") for text in texts)
    assert len(root.findall(".//group[@Integral='yes']")) == 1
    assert root.find("page").attrib["HeightPages"] == "1"


def test_export_rejects_missing_result(tmp_path):
    species = [
        {"name": "A", "type": "Int", "G": 0.0},
        {"name": "TS", "type": "TS", "G": 10.0},
    ]
    try:
        write_energy_diagram_cdxml(tmp_path / "bad.cdxml", species, None)
    except ValueError as exc:
        assert "result" in str(exc).lower()
    else:
        raise AssertionError("Missing energy-span result must be rejected")


def test_chemdraw_bonds_state_span_labels_and_dashed_links(tmp_path):
    species, result = _cross_cycle_fixture()
    path = write_energy_diagram_cdxml(
        tmp_path / "bonds.cdxml",
        species,
        result,
        chemdraw_objects="bonds",
        link_style="dashed",
        state_span=0.85,
        value_decimals=0,
        y_label="Solvated free energy (kcal/mol)",
    )
    root = ET.parse(path).getroot()

    assert len(root.findall(".//fragment")) == 2
    assert len(root.findall(".//n")) == 12
    assert len(root.findall(".//b")) == 10
    assert len(root.findall(".//b[@Display='Bold']")) == 6
    assert len(root.findall(".//b[@Display='Dash']")) == 4

    texts = ["".join(item.itertext()) for item in root.findall(".//t")]
    assert "Solvated free energy (kcal/mol)" in texts
    assert "0" in texts
    assert "20" in texts
    assert "δE = 20" in texts

    first_group_nodes = root.findall(".//group")[0].findall(".//n")
    x1, x2 = [
        float(node.attrib["p"].split()[0]) for node in first_group_nodes[:2]
    ]
    assert x2 - x1 > 60


def test_lines_mode_does_not_emit_chemdraw_bonds(tmp_path):
    species, result = _cross_cycle_fixture()
    path = write_energy_diagram_cdxml(
        tmp_path / "lines.cdxml",
        species,
        result,
        chemdraw_objects="lines",
        link_style="dashed",
    )
    root = ET.parse(path).getroot()
    assert not root.findall(".//fragment")
    assert not root.findall(".//n")
    assert not root.findall(".//b")
