# -*- coding: utf-8 -*-
"""微观动力学核心的回归测试。

基准数值取自 Sebastian Kozuch 的 AUTOF_Excel_v0.9.xlsm 自带示例
（298.15 K，kcal/mol，三步循环，含失活与预活化）：
    TOF = 1.6204439733395484 s^-1, δE = 18.5 kcal/mol,
    TDI = 第 2 个中间体, TDTS = 第 3 个过渡态, TON = 19358.721058165655。
工作簿在 20 min 的动态计算给出 TOF(t) = 0.0298952965 s^-1、
TON(t) = 77.4368979524、活性催化剂 0.0068392560 M；
VBA 用经验式显式 Euler，本实现用 solve_ivp，允许 2% 以内的离散误差。

    pytest tests/test_microkinetics.py -q
"""

import math

import pytest

from molstudio.core.microkinetics import (
    CycleProfile, Deactivation, deactivation_rate, eyring_rate,
    rt_value, simulate, steady_state, ton_until_deactivation,
)


def autof_example(**kwargs):
    """AUTOF 工作簿示例（legacy_constants 使物理常数与 Excel 完全一致）。"""
    params = dict(
        intermediates=[0.0, -7.0, 5.0, -10.0],
        transition_states=[15.0, 8.0, 11.5],
        reactants=[1.0, None, 1.0],
        products=[None, 0.1, 0.1],
        temperature=298.15,
        catalyst_total=0.01,
        deactivation=Deactivation(step=2, ts_energy=16.0, reactant_conc=1.0),
        preactivation_barrier=21.5,
        legacy_constants=True,
    )
    params.update(kwargs)
    return CycleProfile(**params)


def simple_cycle(**kwargs):
    params = dict(
        intermediates=[0.0, -7.0, 5.0, -10.0],
        transition_states=[15.0, 8.0, 11.5],
        temperature=298.15,
    )
    params.update(kwargs)
    return CycleProfile(**params)


# ── 稳态解析解 ───────────────────────────────────────────────────────────────

def test_steady_state_matches_autof_workbook():
    st = steady_state(autof_example())
    assert st.tof == pytest.approx(1.6204439733395484, rel=1e-10)
    assert st.delta_e == pytest.approx(18.5, abs=1e-9)
    assert st.max_span == pytest.approx(18.5, abs=1e-9)
    assert st.delta_g_reaction == pytest.approx(-10.0)
    assert st.tdi_step == 1          # 第 2 个中间体
    assert st.tdts_step == 2         # 第 3 个过渡态
    assert st.tdi_steps == [1]
    assert st.tdts_steps == [2]


def test_xtof_coverages_and_potentials_match_workbook():
    st = steady_state(autof_example())
    assert st.x_int == pytest.approx([0.0257984439613383, 0.974201540871079,
                                      1.5167582730820976e-08], rel=1e-6, abs=1e-9)
    assert st.x_ts == pytest.approx([0.0257928704941106, 0.0257914302334407,
                                     0.948415699272449], rel=1e-6)
    assert st.x_react[0] == pytest.approx(0.0258000754225716, rel=1e-5)
    assert st.x_react[2] == pytest.approx(0.9484173307336818, rel=1e-5)
    assert st.x_prod[1] == pytest.approx(-0.9484173155660992, rel=1e-5)
    assert st.coverages == pytest.approx(
        [0.00025798443961338335, 0.00974201540871079, 1.516758273082e-10], rel=1e-6)
    assert st.potentials[:3] == pytest.approx(
        [-4.895462341398027, -9.743973969753474, -9.75987089170661], rel=1e-9)
    assert st.potentials[3] == pytest.approx(-17.623950520218536, rel=1e-9)


def test_ton_and_deactivation_rate_match_workbook():
    p = autof_example()
    assert ton_until_deactivation(p) == pytest.approx(19358.721058165655, rel=1e-9)
    assert ton_until_deactivation(simple_cycle()) is None
    assert deactivation_rate(simple_cycle()) == 0.0
    assert deactivation_rate(p) == pytest.approx(8.59228e-05, rel=1e-4)
    # Eyring 常数与温度的关系
    assert eyring_rate(0.0, p) == pytest.approx(2.08366e10 * 298.15, rel=1e-12)
    assert rt_value(p) == pytest.approx(0.0019872 * 298.15, rel=1e-12)


def test_esm_is_single_dominant_term_approximation():
    st = steady_state(simple_cycle(legacy_constants=True))
    # 标准浓度 + 强放能时，精确稳态式与 (kBT/h)·exp(-δE/RT) 相差不到 1%
    assert st.tof == pytest.approx(0.169930835, rel=1e-8)
    assert st.esm_tof == pytest.approx(0.170859253, rel=1e-8)
    assert abs(st.tof / st.esm_tof - 1.0) < 0.01


def test_concentrations_change_tof_but_not_energetic_span():
    a = steady_state(simple_cycle(products=[None, 0.1, 0.1]))
    b = steady_state(simple_cycle(products=[None, 0.01, 0.01]))
    assert a.delta_e == b.delta_e == pytest.approx(18.5)
    assert b.tof > 5 * a.tof       # 产物移走使 TOF 提高约 7 倍
    assert a.esm_tof == b.esm_tof  # ESM 近似完全看不到浓度


def test_energy_unit_kj_matches_kcal():
    # 用 SI 常数：VBA 的 0.0019872/0.0083145 是互不精确的四位近似，
    # 默认实现里 R_J/4184 与 R_J/1000 严格按 4.184 换算。
    kcal = simple_cycle()
    kj = simple_cycle(
        intermediates=[v * 4.184 for v in kcal.intermediates],
        transition_states=[v * 4.184 for v in kcal.transition_states],
        energy_unit="kJ/mol")
    a, b = steady_state(kcal), steady_state(kj)
    assert b.tof == pytest.approx(a.tof, rel=1e-12)
    assert b.delta_e == pytest.approx(a.delta_e * 4.184, rel=1e-12)
    assert b.potentials[0] == pytest.approx(a.potentials[0] * 4.184, rel=1e-12)


def test_log_sum_exp_avoids_overflow_for_large_profile():
    p = simple_cycle(
        intermediates=[0.0, -200.0, 100.0, -300.0],
        transition_states=[250.0, 180.0, 400.0])
    st = steady_state(p)
    assert math.isfinite(st.tof)
    assert st.tof >= 0.0
    assert math.isfinite(st.log_sum_m)
    assert sum(sum(math.exp(v - st.log_sum_m) for v in row)
               for row in st.log_m) == pytest.approx(1.0, rel=1e-12)


# ── 输入校验 ─────────────────────────────────────────────────────────────────

def test_profile_validation():
    with pytest.raises(ValueError, match="多 1"):
        CycleProfile([0.0, -1.0], [10.0, 12.0])
    with pytest.raises(ValueError, match="至少"):
        CycleProfile([0.0], [])
    with pytest.raises(ValueError, match="放能"):
        CycleProfile([0.0, 5.0], [10.0])
    with pytest.raises(ValueError, match="温度"):
        CycleProfile([0.0, -1.0], [10.0], temperature=0)
    with pytest.raises(ValueError, match="单位"):
        CycleProfile([0.0, -1.0], [10.0], energy_unit="eV")
    with pytest.raises(ValueError, match="浓度"):
        CycleProfile([0.0, -1.0], [10.0], reactants=[0.0])
    with pytest.raises(ValueError, match="失活"):
        CycleProfile([0.0, -1.0], [10.0], deactivation=Deactivation(3, 20.0))
    # 关闭放能约束后可以研究近平衡循环
    p = CycleProfile([0.0, -0.2], [10.0], require_exergonic=False)
    assert steady_state(p).tof > 0


def test_nonpositive_driving_force_is_rejected():
    # ΔG_r = -10 kcal/mol 时 exp(-ΔG_r/RT) ≈ 2.1e7，需 P2·P3 超过它才逆反应
    p = simple_cycle(products=[None, 5000.0, 5000.0], legacy_constants=True)
    with pytest.raises(ValueError, match="驱动力"):
        steady_state(p)


# ── 时间演化 ─────────────────────────────────────────────────────────────────

def test_trajectory_matches_autof_dynamic_sheet():
    tr = simulate(autof_example(), 20.0 * 60.0, n_points=101)
    assert tr.success, tr.message
    assert len(tr.times) == 101
    assert tr.times[0] == 0.0 and tr.times[-1] == pytest.approx(1200.0)
    f = tr.final
    assert f["tof"] == pytest.approx(0.029895296461868184, rel=0.02)
    assert f["turnovers"] == pytest.approx(77.43689795239146, rel=0.02)
    assert f["cat_active"] == pytest.approx(0.006839256036196023, rel=0.02)
    assert f["reactants"][0] == pytest.approx(0.22478337192130796, rel=0.02)
    assert f["products"][1] == pytest.approx(0.8752166280786912, rel=0.02)
    assert tr.turnovers == sorted(tr.turnovers)
    assert all(v >= 0.0 for v in tr.cat_active)


def test_trajectory_without_optional_branches():
    p = simple_cycle(reactants=[1.0, None, None], products=[None, 0.1, 0.1])
    tr = simulate(p, 30.0, n_points=11)
    assert tr.success
    assert tr.final["turnovers"] > 0
    assert tr.final["cat_active"] == pytest.approx(p.catalyst_total)
    with pytest.raises(ValueError, match="演化时间"):
        simulate(p, 0.0)
