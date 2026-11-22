# -*- coding: utf-8 -*-
"""microkinetics.py — 线性催化循环的解析稳态微观动力学（AUTOF 算法移植）。

模型来源（公式本身为公开文献结果，本文件为独立实现，未复制 VBA 源码）：
  Uhe, A.; Kozuch, S.; Shaik, S. *J. Comput. Chem.* 2011, 32, 978-985.
  Kozuch, S.; Shaik, S. *Acc. Chem. Res.* 2011, 44, 101-110.
  Kozuch, S. *WIREs Comput. Mol. Sci.* 2011（AUTOF 程序）。

假设：单一线性催化循环 I1 -> TS1 -> I2 -> ... -> TSn -> I(n+1)；
每步服从 Eyring 过渡态理论与详细平衡；中间体处于稳态且催化剂总量守恒；
反应物/产物浓度为外部给料量（M）；理想溶液、恒温、1 M 标准态。

核心公式（i = TS 序号, j = 中间体序号, 均从 1 开始）：
  M_ij = exp((T_i - I_j - ΔG_r)/RT) · Π_{k=j}^{i-1}[P_k] · Π[R] / Π_{k=j}^{i}[R_k]   (i >= j)
  M_ij = exp((T_i - I_j)/RT)      · (Π[P] / Π_{k=i}^{j-1}[P_k]) · Π_{k=i+1}^{j-1}[R_k] (i < j)
  TOF  = (k_B T/h) · (exp(-ΔG_r/RT)·Π[R] - Π[P]) / Σ_ij M_ij

即 TOF = (k_B T/h)·(Π[R] - Π[P]·exp(ΔG_r/RT)) / Σ_ij exp(span_ij/RT)·C_ij，
其中 span_ij 与能量跨度模型 (ESM) 枚举的 (TS - Int [+ ΔG_r]) 完全相同。
因此 ESM 的 TOF = (k_B T/h)·exp(-δE/RT) 是本式在「标准浓度 + 强放能 +
单一主导项」条件下的近似。

数值实现用 log-sum-exp：VBA 直接对 M_ij 取 Exp 会在能量跨度较大时溢出，
这里全程使用 log M，只在最后一步取指数。

本模块只依赖标准库 + scipy（时间演化），不含任何 Qt / GUI 代码。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence

KB = 1.380649e-23                 # J/K
H_PLANCK = 6.62607015e-34         # J·s
R_J = 8.31446261815324            # J/(mol·K)
J_PER_KCAL = 4184.0
J_PER_KJ = 1000.0

# AUTOF Excel 版使用的常数（仅供数值回归/对照，默认不启用）
LEGACY_R_KCAL = 0.0019872         # kcal/(mol·K)
LEGACY_R_KJ = 0.0083145           # kJ/(mol·K)
LEGACY_KB_OVER_H = 2.08366e10     # K^-1 s^-1

MIN_CONC = 1e-100                 # VBA 把耗尽的浓度钳到 1e-100
ENERGY_UNITS = ("kcal/mol", "kJ/mol")


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Deactivation:
    """催化剂失活支路（AUTOF 的 Cx / Td / [Rd]）。"""
    step: int                     # 从该中间体开始失活，1-based
    ts_energy: float              # 失活过渡态 G⁰，与剖面同单位
    reactant_conc: float = 1.0    # 作用在失活步上的反应物浓度，M


@dataclass
class CycleProfile:
    """一条催化循环的输入数据。

    reactants / products 中 None 表示该步没有外部给料（AUTOF 的空单元格）：
    公式里按 1 M 处理，且时间演化时该物质浓度保持不变（缓冲）。
    """
    intermediates: List[float]                       # n+1 个中间体 G⁰
    transition_states: List[float]                   # n 个 TS G⁰
    reactants: Optional[Sequence[Optional[float]]] = None
    products: Optional[Sequence[Optional[float]]] = None
    temperature: float = 298.15
    energy_unit: str = "kcal/mol"
    catalyst_total: float = 1.0                      # [Ct], M
    deactivation: Optional[Deactivation] = None
    preactivation_barrier: Optional[float] = None    # ΔG‡_pre，同能量单位
    require_exergonic: bool = True                   # AUTOF 要求 ΔG_r < 0
    legacy_constants: bool = False                   # 用 Excel 版物理常数做回归

    def __post_init__(self):
        self.intermediates = [float(v) for v in self.intermediates]
        self.transition_states = [float(v) for v in self.transition_states]
        n = len(self.transition_states)
        if n < 1:
            raise ValueError("催化循环至少需要一个过渡态")
        if len(self.intermediates) != n + 1:
            raise ValueError("中间体数目必须比过渡态多 1（I1..I(n+1) 与 TS1..TSn）")
        if self.temperature <= 0:
            raise ValueError("温度必须大于 0 K")
        if self.energy_unit not in ENERGY_UNITS:
            raise ValueError("能量单位只支持 kcal/mol 或 kJ/mol")
        if self.catalyst_total <= 0:
            raise ValueError("催化剂总浓度必须大于 0")
        self.reactants = self._norm_conc(self.reactants, n)
        self.products = self._norm_conc(self.products, n)
        if self.require_exergonic and self.intermediates[-1] >= self.intermediates[0]:
            raise ValueError("反应必须放能：末态中间体 G⁰ 应低于首态（ΔG_r < 0）")
        if self.deactivation is not None:
            d = self.deactivation
            if not 1 <= d.step <= n:
                raise ValueError("失活起始步号必须在 1..n 之间")
            if d.reactant_conc <= 0:
                raise ValueError("失活步反应物浓度必须大于 0")
        if self.preactivation_barrier is not None and self.preactivation_barrier < 0:
            raise ValueError("预活化能垒不能为负")

    @staticmethod
    def _norm_conc(values, n):
        if values is None:
            return [None] * n
        out = list(values)
        if len(out) != n:
            raise ValueError("反应物/产物浓度数组长度必须等于步数")
        for v in out:
            if v is not None and float(v) <= 0:
                raise ValueError("浓度必须为正数（空单元格表示该步无外部给料）")
        return [None if v is None else float(v) for v in out]

    @property
    def n(self):
        return len(self.transition_states)

    @property
    def delta_g_reaction(self):
        """ΔG_r = G(I_n+1) - G(I_1)，即整个催化反应的自由能变化。"""
        return self.intermediates[-1] - self.intermediates[0]

    def with_concentrations(self, reactants, products):
        """返回只在浓度上不同的副本（时间演化内部使用）。"""
        return replace(self, reactants=list(reactants), products=list(products))


@dataclass
class SteadyState:
    """一次稳态求解的全部结果。索引均为 0-based 步号。"""
    tof: float                     # s^-1
    delta_e: float                 # XTOF 判据给出的能量跨度（输入能量单位）
    max_span: float                # 遍历所有 (Int, TS) 的最大跨度（ESM 口径）
    delta_g_reaction: float
    drive: float                   # exp(-ΔG_r/RT)·Π[R] - Π[P]
    x_int: List[float]             # 各中间体的 X_TOF
    x_ts: List[float]              # 各过渡态的 X_TOF
    x_react: List[float]           # 各反应物的 X_TOF
    x_prod: List[float]            # 各产物的 X_TOF
    coverages: List[float]         # [Cat_i] = X_Int,i · [Ct]
    potentials: List[Optional[float]]   # 非标准 Gibbs 势能 G≠0（含末态，共 n+1 个）
    tdi_step: int
    tdts_step: int
    tdi_steps: List[int]
    tdts_steps: List[int]
    log_m: List[List[float]]
    log_sum_m: float
    rt: float
    kbht: float
    esm_tof: float                 # 同一剖面下 ESM 近似的 TOF，便于对照


@dataclass
class KineticTrajectory:
    """拟稳态时间演化的结果（时间单位为秒）。"""
    times: List[float]
    tof: List[float]
    turnovers: List[float]
    cat_active: List[float]
    reactants: List[List[float]]   # [t][step]
    products: List[List[float]]
    t_end: float
    success: bool
    message: str = ""

    @property
    def final(self):
        """终态摘要，便于 UI / 测试读取。"""
        if not self.times:
            return {}
        return {
            "time": self.times[-1],
            "tof": self.tof[-1],
            "turnovers": self.turnovers[-1],
            "cat_active": self.cat_active[-1],
            "reactants": self.reactants[-1],
            "products": self.products[-1],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 物理量与数值工具
# ─────────────────────────────────────────────────────────────────────────────

def rt_value(profile):
    """RT，单位与剖面能量单位一致。"""
    if profile.legacy_constants:
        r = LEGACY_R_KCAL if profile.energy_unit == "kcal/mol" else LEGACY_R_KJ
    else:
        r = R_J / (J_PER_KCAL if profile.energy_unit == "kcal/mol" else J_PER_KJ)
    return r * profile.temperature


def kbht_value(profile):
    """Eyring 前因子 k_B T / h，s^-1。"""
    if profile.legacy_constants:
        return LEGACY_KB_OVER_H * profile.temperature
    return KB / H_PLANCK * profile.temperature


def eyring_rate(barrier, profile):
    """单个基元步的 Eyring 速率常数（一阶，s^-1）。"""
    return kbht_value(profile) * math.exp(-barrier / rt_value(profile))


def _conc(profile, reactants, products):
    """返回 (数值浓度, 是否参与物料衡算) 两组列表。"""
    r_src = profile.reactants if reactants is None else reactants
    p_src = profile.products if products is None else products
    r = [1.0 if v is None else max(float(v), MIN_CONC) for v in r_src]
    p = [1.0 if v is None else max(float(v), MIN_CONC) for v in p_src]
    r_mask = [v is not None for v in r_src]
    p_mask = [v is not None for v in p_src]
    return r, p, r_mask, p_mask


def _log_prod(values):
    return sum(math.log(max(v, MIN_CONC)) for v in values)


def _log_sum_exp(values):
    top = max(values)
    if top == float("-inf"):
        return top
    return top + math.log(sum(math.exp(v - top) for v in values))


def _safe_exp(x):
    try:
        return math.exp(x)
    except OverflowError:
        return float("inf")


def _log_m_matrix(profile, r, p):
    """log M_ij，逐项对应 AUTOF 的 s_mab（i = TS, j = Int，1-based）。"""
    n = profile.n
    ts, inter = profile.transition_states, profile.intermediates
    dg, rt = profile.delta_g_reaction, rt_value(profile)
    log_preact, log_pprod = _log_prod(r), _log_prod(p)
    out = [[0.0] * n for _ in range(n)]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if i >= j:
                # Π_{k=j}^{i-1} P_k 与 Π[R] / Π_{k=j}^{i} R_k
                log_pp = _log_prod(p[j - 1:i - 1])
                log_pr = log_preact - _log_prod(r[j - 1:i])
                log_span = (ts[i - 1] - inter[j - 1] - dg) / rt
            else:
                # Π[P] / Π_{k=i}^{j-1} P_k 与 Π_{k=i+1}^{j-1} R_k
                log_pp = log_pprod - _log_prod(p[i - 1:j - 1])
                log_pr = _log_prod(r[i:j - 1])
                log_span = (ts[i - 1] - inter[j - 1]) / rt
            out[i - 1][j - 1] = log_span + log_pp + log_pr
    return out


def _log_drive(profile, r, p):
    """返回 (log drive, log A, log B)；A = exp(-ΔG_r/RT)Π[R], B = Π[P]。

    drive <= 0 时返回 (None, log A, log B)：净反应不再正向进行。
    """
    dg, rt = profile.delta_g_reaction, rt_value(profile)
    log_a = -dg / rt + _log_prod(r)
    log_b = _log_prod(p)
    if log_a <= log_b:
        return None, log_a, log_b
    # A - B = A·(1 - exp(log B - log A))
    return log_a + math.log(-math.expm1(log_b - log_a)), log_a, log_b


def _max_span(profile):
    """ESM 口径的最大能量跨度（含末态中间体作为 TDI 的可能）。"""
    ts, inter = profile.transition_states, profile.intermediates
    dg = profile.delta_g_reaction
    best = -float("inf")
    for i, t in enumerate(ts, start=1):
        for j, g in enumerate(inter, start=1):
            span = t - g + (dg if i < j else 0.0)
            best = max(best, span)
    return best


# ─────────────────────────────────────────────────────────────────────────────
# 稳态解析解
# ─────────────────────────────────────────────────────────────────────────────

def steady_state(profile, reactants=None, products=None):
    """求解稳态 TOF、X_TOF、覆盖度与非标准势能。"""
    n = profile.n
    r, p, r_mask, p_mask = _conc(profile, reactants, products)
    rt = rt_value(profile)
    log_drive, log_a, log_b = _log_drive(profile, r, p)
    if log_drive is None:
        raise ValueError("净反应驱动力非正（产物积累或反应接近/越过平衡），TOF 不适用")

    log_m = _log_m_matrix(profile, r, p)
    log_sum = _log_sum_exp([v for row in log_m for v in row])
    w = [[math.exp(v - log_sum) for v in row] for row in log_m]

    tof = kbht_value(profile) * _safe_exp(log_drive - log_sum)
    drive = _safe_exp(log_drive)
    term1r = _safe_exp(log_a - log_drive)
    term1p = -_safe_exp(log_b - log_drive)

    x_int = [sum(w[i][k] for i in range(n)) for k in range(n)]
    x_ts = [sum(w[k][j] for j in range(n)) for k in range(n)]

    # X_TOF(R) / X_TOF(P)：按 AUTOF s_xtof 的 (i,j) 分区求和
    x_react, x_prod = [0.0] * n, [0.0] * n
    for k in range(1, n + 1):
        sumatr = sumatp = 0.0
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                wij = w[i - 1][j - 1]
                if i >= j:
                    if i < k or j > k:
                        sumatr += wij
                    if i > k and j <= k:
                        sumatp += wij
                else:
                    if j > k and i < k:
                        sumatr += wij
                    if ((i + n > k and j <= k)
                            or (i + n > k + n and j <= k + n)):
                        sumatp += wij
        x_react[k - 1] = term1r - sumatr if r_mask[k - 1] else 0.0
        x_prod[k - 1] = term1p - sumatp if p_mask[k - 1] else 0.0

    max_i, max_t = max(x_int), max(x_ts)
    tdi_step = x_int.index(max_i)
    tdts_step = x_ts.index(max_t)
    # AUTOF 用「距最大值 0.1 以内」标记多个决速物种
    tdi_steps = [k for k, v in enumerate(x_int) if v > max_i - 0.1]
    tdts_steps = [k for k, v in enumerate(x_ts) if v > max_t - 0.1]

    ts, inter = profile.transition_states, profile.intermediates
    dg = profile.delta_g_reaction
    delta_e = ts[tdts_step] - inter[tdi_step] + (dg if tdts_step < tdi_step else 0.0)
    max_span = _max_span(profile)

    coverages = [v * profile.catalyst_total for v in x_int]
    potentials = []
    for k in range(1, n + 1):
        preact_pot = math.prod(r[k - 1:n])
        pprod_pot = math.prod(p[0:k - 1])
        arg = coverages[k - 1] * preact_pot * pprod_pot
        potentials.append(inter[k - 1] + rt * math.log(arg) if arg > 0 else None)
    arg_final = coverages[0] * math.prod(p)
    potentials.append(inter[n] + rt * math.log(arg_final) if arg_final > 0 else None)

    return SteadyState(
        tof=tof, delta_e=delta_e, max_span=max_span,
        delta_g_reaction=dg, drive=drive,
        x_int=x_int, x_ts=x_ts, x_react=x_react, x_prod=x_prod,
        coverages=coverages, potentials=potentials,
        tdi_step=tdi_step, tdts_step=tdts_step,
        tdi_steps=tdi_steps, tdts_steps=tdts_steps,
        log_m=log_m, log_sum_m=log_sum, rt=rt,
        kbht=kbht_value(profile),
        esm_tof=kbht_value(profile) * math.exp(-max_span / rt),
    )


def ton_until_deactivation(profile, state=None):
    """催化剂失活前的总周转数 TON（无失活支路时返回 None）。"""
    d = profile.deactivation
    if d is None:
        return None
    state = state or steady_state(profile)
    r, p, _, _ = _conc(profile, None, None)
    ts, inter = profile.transition_states, profile.intermediates
    rt, dg = rt_value(profile), profile.delta_g_reaction
    log_preact, log_pprod = _log_prod(r), _log_prod(p)
    cx, td = d.step, d.ts_energy
    logs = []
    for i in range(1, profile.n + 1):
        if i >= cx:
            log_pp = _log_prod(p[cx - 1:i - 1])
            log_pr = log_preact - _log_prod(r[cx - 1:i])
            log_e = (ts[i - 1] - td - dg) / rt
        else:
            log_pp = log_pprod - _log_prod(p[i - 1:cx - 1])
            log_pr = _log_prod(r[i:cx - 1])
            log_e = (ts[i - 1] - td) / rt
        logs.append(log_e + log_pp + log_pr)
    log_sum = _log_sum_exp(logs)
    log_drive, _, _ = _log_drive(profile, r, p)
    if log_drive is None:
        return 0.0
    return _safe_exp(log_drive - math.log(max(d.reactant_conc, MIN_CONC)) - log_sum)


def deactivation_rate(profile):
    """失活支路的速率常数 k_deact（s^-1），无失活支路时返回 0。"""
    d = profile.deactivation
    if d is None:
        return 0.0
    barrier = d.ts_energy - profile.intermediates[d.step - 1]
    return d.reactant_conc * kbht_value(profile) * math.exp(-barrier / rt_value(profile))


# ─────────────────────────────────────────────────────────────────────────────
# 时间演化（拟稳态 + 外部浓度积分）
# ─────────────────────────────────────────────────────────────────────────────

def simulate(profile, t_end, n_points=101, method="BDF", rtol=1e-7, atol=1e-12):
    """对反应物/产物浓度、催化剂活性与累计 TON 做时间推进。

    中间体覆盖度每个时刻由 :func:`steady_state` 的解析稳态解给出（拟稳态近似，
    与 AUTOF 一致）；外部量用 scipy 的刚性安全积分器推进，替代 VBA 的经验式
    显式 Euler + 变步长。

    t_end / 返回的 times 单位均为秒。
    """
    from scipy.integrate import solve_ivp

    if t_end <= 0:
        raise ValueError("演化时间必须大于 0 秒")
    n_points = max(int(n_points), 2)
    n = profile.n
    r0, p0, r_mask, p_mask = _conc(profile, None, None)
    cat_total = profile.catalyst_total

    pre = profile.preactivation_barrier
    k_act = eyring_rate(pre, profile) if pre is not None else 0.0
    # AUTOF 只在 t < ln(10000)/k_act 内考虑预活化
    end_act = math.log(10000.0) / k_act if k_act > 0 else 0.0
    k_deact = deactivation_rate(profile)
    cx = profile.deactivation.step if profile.deactivation else 0

    cat_active0 = 0.0 if k_act > 0 else cat_total
    y0 = list(r0) + list(p0) + [cat_active0, cat_total - cat_active0, 0.0]
    t_eval = [t_end * k / (n_points - 1) for k in range(n_points)]

    def rhs(_t, y):
        r = [max(v, MIN_CONC) for v in y[:n]]
        p = [max(v, MIN_CONC) for v in y[n:2 * n]]
        cat_active = max(y[2 * n], 0.0)
        cat_inactive = max(y[2 * n + 1], 0.0)
        try:
            st = steady_state(profile.with_concentrations(r, p), r, p)
            tof = st.tof * cat_active / cat_total
            x_cx = st.x_int[cx - 1] if cx else 0.0
        except ValueError:
            tof, x_cx = 0.0, 0.0
        dy = [0.0] * (2 * n + 3)
        for k in range(n):
            if r_mask[k]:
                dy[k] = -tof * cat_total
            if p_mask[k]:
                dy[n + k] = tof * cat_total
        if k_act > 0 and _t < end_act:
            flux = k_act * cat_inactive
            dy[2 * n] += flux
            dy[2 * n + 1] -= flux
        if k_deact > 0:
            dy[2 * n] -= x_cx * cat_active * k_deact
        dy[2 * n + 2] = tof
        return dy

    sol = solve_ivp(rhs, (0.0, float(t_end)), y0, method=method, t_eval=t_eval,
                    rtol=rtol, atol=atol)
    if not sol.success:
        return KineticTrajectory([], [], [], [], [], [], float(t_end),
                                 False, str(sol.message))

    times = list(sol.t)
    tof, reactants, products = [], [], []
    for k, t in enumerate(times):
        r = [max(v, MIN_CONC) for v in sol.y[:n, k]]
        p = [max(v, MIN_CONC) for v in sol.y[n:2 * n, k]]
        reactants.append(r)
        products.append(p)
        try:
            st = steady_state(profile.with_concentrations(r, p), r, p)
            tof.append(st.tof * max(sol.y[2 * n, k], 0.0) / cat_total)
        except ValueError:
            tof.append(0.0)
    return KineticTrajectory(
        times=times, tof=tof,
        turnovers=list(sol.y[2 * n + 2]),
        cat_active=[max(v, 0.0) for v in sol.y[2 * n]],
        reactants=reactants, products=products,
        t_end=float(t_end), success=True,
    )
