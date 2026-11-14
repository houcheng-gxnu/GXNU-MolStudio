# -*- coding: utf-8 -*-
"""``quick_info`` 解析器与 ``PropertyCard`` 属性卡片的测试。

- quick_info：合成 fchk/log/gjf/xyz 文本 + 真实 ``D:\\test-est\\DA-5.fchk``；
- PropertyCard：offscreen 模式下的 QApplication，验证填值/清空/中英切换/刷新信号。
"""

import os
import sys
import time

# 必须在创建 QApplication 之前设置 offscreen
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from molstudio.core.quick_info import INFO_KEYS, quick_info  # noqa: E402
from molstudio.ui.property_card import PropertyCard  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

_APP = None


def _app():
    """离屏 QApplication（与仓库其他 Qt 测试一致，延迟创建）。"""
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture()
def card():
    _app()
    widget = PropertyCard()
    yield widget
    widget.deleteLater()

FCHK_PATH = r"D:\test-est\DA-5.fchk"
TS_LOG_PATH = r"D:\test-est\di_local_test\ts_opt\DA-5_TS.log"

_needs_fchk = pytest.mark.skipif(
    not os.path.isfile(FCHK_PATH), reason="缺少测试数据 %s" % FCHK_PATH)
_needs_ts_log = pytest.mark.skipif(
    not os.path.isfile(TS_LOG_PATH), reason="缺少测试数据 %s" % TS_LOG_PATH)


# ── 合成文件内容 ─────────────────────────────────────────────────────

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _int_block(values, per_line=6):
    return "\n".join(
        "".join("%12d" % value for value in values[start:start + per_line])
        for start in range(0, len(values), per_line))


def _float_block(values, per_line=5):
    return "\n".join(
        "".join("%16.8E" % value for value in values[start:start + per_line])
        for start in range(0, len(values), per_line))


def _synthetic_fchk(numbers=(6, 1), real_weights=None, energy=-76.123456789,
                    n_alpha=2, orbitals=(-0.8, -0.5, 0.1, 0.3),
                    charge=0, multiplicity=1, standard_columns=True):
    line2 = ("%-10s%-30s%-30s" % ("SP", "RB3LYP", "6-31G(d)")
             if standard_columns else
             "%-10s%-60s%-20s" % ("SP", "RM06L", "def2SVP"))
    lines = [
        "synthetic fchk",
        line2,
        "Number of atoms                            I               %2d"
        % len(numbers),
        "Charge                                     I                %d" % charge,
        "Multiplicity                               I                %d" % multiplicity,
        "Number of alpha electrons                  I                %d" % n_alpha,
        "Atomic numbers                             I   N=          %3d"
        % len(numbers),
        _int_block(numbers),
    ]
    if real_weights:
        lines.append("Real atomic weights                        R   N=          %3d"
                     % len(real_weights))
        lines.append(_float_block(real_weights))
    lines.append("Total Energy                               R     %22.12E" % energy)
    lines.append("Alpha Orbital Energies                     R   N=          %3d"
                 % len(orbitals))
    lines.append(_float_block(orbitals))
    return "\n".join(lines) + "\n"


def _log_orientation(kind, rows):
    """Gaussian orientation 表（rows: center, atomic_number, x, y, z）。"""
    lines = [
        kind + ":",
        " ---------------------------------------------------------------------",
        " Center     Atomic      Atomic             Coordinates (Angstroms)",
        " Number     Number       Type             X           Y           Z",
        " ---------------------------------------------------------------------",
    ]
    for center, atomic_number, x, y, z in rows:
        lines.append(" %6d %6d %6d %14.6f %14.6f %14.6f" %
                     (center, atomic_number, 0, x, y, z))
    lines.append(" ---------------------------------------------------------------------")
    lines.append("")
    return "\n".join(lines)


def _synthetic_log(scf_energies=(-76.4,),
                   orbitals=(((-0.8, -0.5), (0.1, 0.3)),),
                   charge=0, multiplicity=1, zpe_lines=True, normal=True,
                   orientation=True, thermal_energy=True):
    blocks = []
    for index, energy in enumerate(scf_energies):
        blocks.append(" SCF Done:  E(RM06L) = %s     A.U. after    1 cycles"
                      % ("%.9f" % energy))
        occ, virt = orbitals[index]
        blocks.append(" Alpha  occ. eigenvalues -- " +
                      " ".join("%10.5f" % value for value in occ))
        blocks.append(" Alpha virt. eigenvalues -- " +
                      " ".join("%10.5f" % value for value in virt))
    text = (
        " Entering Gaussian System\n"
        " --------------------------------------------------------------\n"
        " #p opt freq m06l/def2svp int=ultrafine\n"
        " --------------------------------------------------------------\n"
        " 1/5=1,10=4,11=1,18=20;\n"
        " Charge =  %d Multiplicity = %d\n" % (charge, multiplicity) +
        "\n".join(blocks) + "\n"
    )
    if zpe_lines:
        text += (
            " Zero-point correction=                           0.050000 (Hartree/Particle)\n"
        )
        if thermal_energy:
            text += (
                " Thermal correction to Energy=                    0.060000\n"
                " Thermal correction to Enthalpy=                  0.061000\n"
            )
        text += (
            " Thermal correction to Gibbs Free Energy=         0.020000\n"
        )
    if orientation:
        text += _log_orientation("Standard orientation",
                                 [(1, 6, 0.0, 0.0, 0.0),
                                  (2, 1, 1.0, 0.0, 0.0)])
    if normal:
        text += " Normal termination of Gaussian 16 at Fri Nov 13 09:00:00 2026.\n"
    return text


def _synthetic_gjf():
    return (
        "%chk=in.chk\n"
        "#p opt freq b3lyp/6-31g(d) int=ultrafine\n"
        "\n"
        "title\n"
        "\n"
        "0 1\n"
        " C 0.0 0.0 0.0\n"
        " H 1.0 0.0 0.0\n"
        "\n"
    )


# ── quick_info: 通用约定 ─────────────────────────────────────────────

def test_quick_info_returns_fixed_key_set(tmp_path):
    info = quick_info(_write(tmp_path, "x.xyz", "1\nH\nH 0 0 0\n"))
    assert set(info) == set(INFO_KEYS)
    assert info["path"] == str(tmp_path / "x.xyz")


def test_quick_info_unreadable_returns_only_path(tmp_path):
    missing = str(tmp_path / "missing.fchk")
    info = quick_info(missing)
    assert info["path"] == missing
    for key in INFO_KEYS:
        if key != "path":
            assert info[key] is None, key


def test_quick_info_task_time_matches_mtime(tmp_path):
    path = _write(tmp_path, "sys.xyz", "1\nH\nH 0 0 0\n")
    info = quick_info(path)
    expected = time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(os.path.getmtime(path)))
    assert info["task_time"] == expected


# ── quick_info: fchk ────────────────────────────────────────────────

def test_quick_info_fchk_synthetic(tmp_path):
    path = _write(tmp_path, "synth.fchk", _synthetic_fchk())
    info = quick_info(path)
    assert info["formula"] == "CH"
    assert info["mol_weight"] == pytest.approx(12.011 + 1.008, abs=1e-9)
    assert info["n_atoms"] == 2
    assert info["energy"] == pytest.approx(-76.123456789, abs=1e-12)
    assert info["homo"] == pytest.approx(-0.5, abs=1e-12)
    assert info["lumo"] == pytest.approx(0.1, abs=1e-12)
    assert info["gap"] == pytest.approx(0.6, abs=1e-12)
    assert info["method"] == "RB3LYP/6-31G(d)"
    assert info["charge"] == 0
    assert info["multiplicity"] == 1
    assert info["state"] == "已载入"
    assert info["zpe"] is None and info["gibbs_corr"] is None


def test_quick_info_fchk_method_real_layout(tmp_path):
    # 实测 G16 formchk：方法字段 60 列，基组从第 71 列开始
    path = _write(tmp_path, "real_layout.fchk",
                  _synthetic_fchk(standard_columns=False))
    assert quick_info(path)["method"] == "RM06L/def2SVP"


def test_quick_info_fchk_unknown_element_weight_falls_back_to_zero(tmp_path):
    # 61 号元素不在标准原子量表里，且没有 Real atomic weights → 质量按 0 计
    path = _write(tmp_path, "unknown.fchk",
                  _synthetic_fchk(numbers=(6, 61), n_alpha=2,
                                  orbitals=(-0.8, -0.5, 0.1, 0.3)))
    info = quick_info(path)
    assert info["n_atoms"] == 2
    assert info["mol_weight"] == pytest.approx(12.011, abs=1e-9)


@_needs_fchk
def test_quick_info_real_fchk():
    info = quick_info(FCHK_PATH)
    assert info["formula"] == "C6H10"
    assert info["mol_weight"] == pytest.approx(82.14, abs=0.05)
    assert info["n_atoms"] == 16
    assert info["energy"] == pytest.approx(-234.335136146, abs=1e-6)
    assert info["method"] is not None
    assert "M06L" in info["method"] and "def2SVP" in info["method"]
    assert info["homo"] is not None and info["lumo"] is not None
    assert info["homo"] == pytest.approx(-0.208349661, abs=1e-6)
    assert info["lumo"] == pytest.approx(-0.0424966056, abs=1e-6)
    assert info["gap"] == pytest.approx(0.1658530554, abs=1e-6)
    assert info["charge"] == 0
    assert info["multiplicity"] == 1
    assert info["state"] == "已载入"


# ── quick_info: log ─────────────────────────────────────────────────

def test_quick_info_log_synthetic(tmp_path):
    path = _write(tmp_path, "job.log", _synthetic_log())
    info = quick_info(path)
    assert info["energy"] == pytest.approx(-76.4, abs=1e-12)
    assert info["homo"] == pytest.approx(-0.5, abs=1e-12)
    assert info["lumo"] == pytest.approx(0.1, abs=1e-12)
    assert info["gap"] == pytest.approx(0.6, abs=1e-12)
    # zpe 优先取 Thermal correction to Energy
    assert info["zpe"] == pytest.approx(0.06, abs=1e-12)
    assert info["gibbs_corr"] == pytest.approx(0.02, abs=1e-12)
    assert info["charge"] == 0
    assert info["multiplicity"] == 1
    assert info["method"] == "m06l/def2svp"
    assert info["state"] == "已完成"
    # 顺带从最后一个 orientation 取结构信息
    assert info["formula"] == "CH"
    assert info["n_atoms"] == 2


def test_quick_info_log_uses_last_scf_and_orbital_block(tmp_path):
    path = _write(tmp_path, "multi.log", _synthetic_log(
        scf_energies=(-76.1, -76.5),
        orbitals=(((-0.9, -0.6), (0.2, 0.4)),
                  ((-0.7, -0.3), (0.05, 0.25)))))
    info = quick_info(path)
    assert info["energy"] == pytest.approx(-76.5, abs=1e-12)
    assert info["homo"] == pytest.approx(-0.3, abs=1e-12)
    assert info["lumo"] == pytest.approx(0.05, abs=1e-12)


def test_quick_info_log_zero_point_fallback_and_unfinished(tmp_path):
    path = _write(tmp_path, "unfinished.log",
                  _synthetic_log(zpe_lines=False, normal=False))
    info = quick_info(path)
    assert info["state"] == "未完成"
    assert info["zpe"] is None


def test_quick_info_log_zero_point_correction_fallback(tmp_path):
    # 只有 Zero-point correction= 行时（没有 Thermal correction to Energy）
    path = _write(tmp_path, "zpe_only.log",
                  _synthetic_log(thermal_energy=False))
    info = quick_info(path)
    assert info["zpe"] == pytest.approx(0.05, abs=1e-12)
    assert info["gibbs_corr"] == pytest.approx(0.02, abs=1e-12)


def test_quick_info_log_without_geometry(tmp_path):
    path = _write(tmp_path, "no_geom.log", _synthetic_log(orientation=False))
    info = quick_info(path)
    assert info["formula"] is None
    assert info["n_atoms"] is None
    assert info["energy"] == pytest.approx(-76.4, abs=1e-12)


@_needs_ts_log
def test_quick_info_real_ts_log():
    info = quick_info(TS_LOG_PATH)
    assert info["energy"] == pytest.approx(-234.335136146, abs=1e-6)
    assert info["zpe"] == pytest.approx(0.145258, abs=1e-6)
    assert info["gibbs_corr"] == pytest.approx(0.108662, abs=1e-6)
    assert info["homo"] == pytest.approx(-0.20835, abs=1e-6)
    assert info["lumo"] == pytest.approx(-0.04250, abs=1e-6)
    assert info["method"] is not None
    assert "m06l" in info["method"].lower()
    assert info["state"] == "已完成"
    assert info["formula"] == "C6H10"


# ── quick_info: gjf / xyz ───────────────────────────────────────────

def test_quick_info_gjf_synthetic(tmp_path):
    path = _write(tmp_path, "in.gjf", _synthetic_gjf())
    info = quick_info(path)
    assert info["method"] == "b3lyp/6-31g(d)"
    assert info["formula"] == "CH"
    assert info["mol_weight"] == pytest.approx(13.019, abs=1e-9)
    assert info["n_atoms"] == 2
    assert info["charge"] == 0
    assert info["multiplicity"] == 1
    assert info["state"] == "已载入"
    assert info["energy"] is None


def test_quick_info_xyz_synthetic(tmp_path):
    path = _write(tmp_path, "water.xyz",
                  "3\nwater\nO 0.0 0.0 0.0\nH 1.0 0.0 0.0\nH 0.0 1.0 0.0\n")
    info = quick_info(path)
    assert info["formula"] == "H2O"
    assert info["mol_weight"] == pytest.approx(15.999 + 2 * 1.008, abs=1e-9)
    assert info["n_atoms"] == 3
    assert info["state"] == "已载入"


def test_quick_info_hill_order_without_carbon(tmp_path):
    path = _write(tmp_path, "mix.xyz",
                  "3\nmix\nO 0.0 0.0 0.0\nH 1.0 0.0 0.0\nN 0.0 1.0 0.0\n")
    assert quick_info(path)["formula"] == "HNO"


def test_quick_info_hill_order_with_carbon_and_others(tmp_path):
    path = _write(tmp_path, "mix.xyz",
                  "4\nmix\nC 0.0 0.0 0.0\nH 1.0 0.0 0.0\n"
                  "N 0.0 1.0 0.0\nO 0.0 0.0 1.0\n")
    assert quick_info(path)["formula"] == "CHNO"


# ── PropertyCard ────────────────────────────────────────────────────

def _full_info():
    return {
        "path": r"D:\data\DA-5.fchk",
        "formula": "C6H10",
        "mol_weight": 82.14,
        "n_atoms": 16,
        "energy": -234.335136,
        "zpe": 0.145258,
        "gibbs_corr": 0.108662,
        "homo": -0.21,
        "lumo": 0.04,
        "gap": 0.25,
        "method": "RM06L/def2SVP",
        "charge": 0,
        "multiplicity": 1,
        "state": "已完成",
        "task_time": "2026-11-13 09:48:15",
    }


def test_property_card_basics(card):
    assert card.objectName() == "PropertyCard"
    assert card.current_info is None
    assert set(card.value_labels) == {
        "energy", "zpe", "gibbs_corr", "homo", "lumo", "gap",
        "formula", "mol_weight", "method", "state", "task_time"}
    for label in card.value_labels.values():
        assert label.text() == "—"
    assert card.value_labels["energy"].objectName() == "PropertyCardValue"
    assert card.sizeHint().width() == 360
    assert card.sizeHint().height() == 300

    style = card.styleSheet()
    assert "#FFFFFF" in style
    assert "#E5E9F0" in style
    assert "border-radius: 10px" in style
    assert "padding: 10px" in style


def test_property_card_set_info(card):
    info = _full_info()
    card.set_info(info)
    assert card.current_info == info
    assert card.value_labels["energy"].text() == "-234.335136 Hartree"
    assert card.value_labels["zpe"].text() == "0.145258 Hartree"
    assert card.value_labels["gibbs_corr"].text() == "0.108662 Hartree"
    assert card.value_labels["homo"].text() == "-0.2100 a.u."
    assert card.value_labels["lumo"].text() == "0.0400 a.u."
    assert card.value_labels["gap"].text() == "0.2500 a.u."
    assert card.value_labels["formula"].text() == "C6H10"
    assert card.value_labels["mol_weight"].text() == "82.14"
    assert card.value_labels["method"].text() == "RM06L/def2SVP"
    assert card.value_labels["state"].text() == "已完成"
    assert card.value_labels["task_time"].text() == "2026-11-13 09:48:15"


def test_property_card_missing_values_show_placeholder(card):
    card.set_info({"formula": "CH", "energy": None})
    assert card.value_labels["formula"].text() == "CH"
    assert card.value_labels["energy"].text() == "—"
    assert card.value_labels["homo"].text() == "—"
    assert card.value_labels["method"].text() == "—"


def test_property_card_clear(card):
    card.set_info(_full_info())
    card.clear()
    assert card.current_info is None
    for label in card.value_labels.values():
        assert label.text() == "—"


def test_property_card_set_lang_english_and_back(card):
    card.set_info(_full_info())
    card.set_lang("en")
    assert card.title_label.text() == "Property info"
    assert card.section_label.text() == "Basic info"
    assert card.refresh_button.toolTip() == "Refresh current structure info"
    assert card.label_labels["energy"].text() == "Total energy"
    assert card.label_labels["zpe"].text() == "Zero-point energy"
    assert card.label_labels["gibbs_corr"].text() == "Gibbs correction"
    assert card.label_labels["gap"].text() == "HOMO-LUMO gap"
    assert card.label_labels["formula"].text() == "Formula"
    assert card.label_labels["mol_weight"].text() == "Molecular weight"
    assert card.label_labels["method"].text() == "Method"
    assert card.label_labels["state"].text() == "State"
    assert card.label_labels["task_time"].text() == "Task time"
    # 数值不受语言切换影响
    assert card.value_labels["formula"].text() == "C6H10"

    card.set_lang("zh")
    assert card.title_label.text() == "属性信息"
    assert card.section_label.text() == "基本信息"
    assert card.refresh_button.toolTip() == "刷新当前结构信息"
    assert card.label_labels["energy"].text() == "总能量"
    assert card.label_labels["formula"].text() == "分子式"


def test_property_card_refresh_signal(card):
    emitted = []
    card.refreshRequested.connect(lambda: emitted.append(True))
    assert card.refresh_button.toolTip() == "刷新当前结构信息"
    card.refresh_button.click()
    assert emitted == [True]
