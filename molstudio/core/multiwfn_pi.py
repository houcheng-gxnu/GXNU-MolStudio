# -*- coding: utf-8 -*-
"""
用 Multiwfn 找出 π / σ 轨道编号（给 AICD 的 ``IOp(10/93=2)`` 用）
=================================================================

AICD 想做"只看 π 电子"的图，必须在 Gaussian 输入里写 ``IOp(10/93=2)`` 并在
末尾列出**轨道编号**。让人自己挨个看轨道图找编号是不现实的——sobereva 的
《使用AICD 2.0绘制磁感应电流图》(sobereva.com/294) 给的办法是用 Multiwfn：

    主功能 100（Other functions Part 1）→ 子功能 22
    （Detect pi orbitals, set occupation numbers and calculate pi composition）
    → 0（轨道是离域的，体系严格共平面）

Multiwfn 会打印全部 π 轨道（编号 / 占据数 / 能量），并直接给出
``Indices of occupied pi orbitals:`` 那一行——那串数字就是 gjf 末尾要抄的。
σ 轨道则是"占据轨道里除掉 π 的那部分"，本模块顺手算好并压缩成区间写法。

注意事项（同一篇博文与 Multiwfn 手册）：

* 只有体系**严格共平面**时这个判定才严格成立（Multiwfn 会自己挑平面并打印
  "This system is expected to be in XY plane" 之类）；非平面体系给的是近似
  结果，按 sob 的说法"π 成份超过阈值（比如 80%）的可以姑且当作 π"。
* 开壳层（U）计算里 α/β 轨道编号写法不同（β 占据轨道的序号排在 α 占据轨道
  之后），本模块只负责闭壳层共平面这一常见情形。

本模块不依赖 Qt，可直接单测；``parse_pi_output()`` 是纯文本解析。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


#: Multiwfn 命令序列：主功能 100 → 子功能 22 → 0（离域轨道/共平面）
#: → 0（不动占据数）→ 退出。开头的空行用于吃掉 "Press ENTER button to
#: continue"（缺 settings.ini 时会出现），与项目里其它 Multiwfn 流程
#: （见 fchk_orbital 里各 CMD_* 常量）的写法一致。
PI_DETECT_SEQUENCE = "\n100\n22\n0\n0\nq\n"

#: 非平面/扭曲体系用的流程（Multiwfn 手册 4.100.22 的例子）：
#:   19 → 1        定域化占据轨道（Pipek-Mezey），生成并载入含 LMO 的 new.fch
#:   100 → 22      进入 π 检测；此时轨道是定域轨道，菜单变成 LMO 专用
#:   -1            Detect pi orbitals and then evaluate pi composition for
#:                 orbitals in another wavefunction file
#:   -1            同上（第二级菜单里的那一项）
#:   文件名        提供"另一批轨道"（原始的 MO / NTO / 自然轨道文件）
#:   阈值          π 成份打印阈值（%，直接回车 = 50）
#:
#: 为什么非平面体系要这么绕：平面体系那套（``0``）要求体系严格共平面；体系扭曲
#: 时 σ/π 会混合，没有客观判据。定域化后把 π 型 LMO 投影到 MO 上得到的"π 成份"
#: 才是可量化的判据（sobereva 的《Multiwfn已支持计算任意轨道的pi成份》）。
PI_PROJECTION_SEQUENCE = "\n19\n1\n100\n22\n-1\n-1\n{molecule}\n{threshold}\nq\n"


def _run_multiwfn(args, inputs, cwd, timeout=600):
    """跑一次 Multiwfn 并返回 stdout（windowed 模式下必须显式给管道）。"""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (subprocess.CREATE_NO_WINDOW
                         | subprocess.CREATE_NEW_PROCESS_GROUP)
    proc = subprocess.run(
        args, input=inputs, cwd=cwd, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=creationflags, encoding="utf-8", errors="replace")
    return proc.stdout or ""


def format_orbital_ranges(numbers):
    """把轨道编号列表压成 gjf 里常用的区间写法：``[1..16,18,19]`` → ``1-16,18-19``。"""
    nums = sorted({int(n) for n in numbers})
    if not nums:
        return ""
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}-{prev}" if prev > start else f"{start}")
        start = prev = n
    parts.append(f"{start}-{prev}" if prev > start else f"{start}")
    return ",".join(parts)


def parse_pi_output(text):
    """从 Multiwfn 的输出里解析 π / σ 轨道信息。

    Returns
    -------
    dict
        ``{"pi_all": [(no, occ, energy_eV), ...], "pi_occupied": [int, ...],
        "pi_occupied_str": "17,20,21", "sigma_occupied": [...],
        "sigma_occupied_str": "1-16,18-19", "n_occupied": 21,
        "n_pi_all": 24, "plane_hint": "XY"}``；解析不到的字段留空。
    """
    out = {"pi_all": [], "pi_occupied": [], "pi_occupied_str": "",
           "sigma_occupied": [], "sigma_occupied_str": "",
           "n_occupied": 0, "n_pi_all": 0, "plane_hint": ""}

    m = re.search(r"This system is expected to be in\s+(\w+)\s+plane", text)
    if m:
        out["plane_hint"] = m.group(1)
    m = re.search(r"Orbitals from\s+1 to\s+(\d+)\s+are occupied", text)
    if m:
        out["n_occupied"] = int(m.group(1))
    m = re.search(r"Total number of pi orbitals:\s+(\d+)", text)
    if m:
        out["n_pi_all"] = int(m.group(1))

    # π 轨道表：编号 + 占据数 + 能量(eV)
    block = re.search(
        r"Expected pi orbitals, occupation numbers and orbital energies.*?\n"
        r"(.*?)Total number of pi orbitals", text, re.S)
    if block:
        for line in block.group(1).splitlines():
            row = re.match(r"\s*(\d+)\s+([\d.]+)\s+(-?[\d.]+)\s*$", line)
            if row:
                out["pi_all"].append((int(row.group(1)), float(row.group(2)),
                                      float(row.group(3))))

    # 权威结果：Multiwfn 自己列出的"占据 π 轨道"编号
    m = re.search(r"Indices of occupied pi orbitals:\s*\n?([\d,\-\s]+)", text)
    if m:
        nums = []
        for chunk in m.group(1).replace("\n", " ").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                low, high = chunk.split("-", 1)
                if low.strip().isdigit() and high.strip().isdigit():
                    nums.extend(range(int(low), int(high) + 1))
            elif chunk.isdigit():
                nums.append(int(chunk))
        out["pi_occupied"] = sorted(set(nums))
    elif out["pi_all"]:
        # 兜底：按占据数 > 0 判断
        out["pi_occupied"] = sorted(n for n, occ, _ in out["pi_all"] if occ > 0)

    out["pi_occupied_str"] = ",".join(str(n) for n in out["pi_occupied"])
    if out["n_occupied"] and out["pi_occupied"]:
        pi = set(out["pi_occupied"])
        sigma = [n for n in range(1, out["n_occupied"] + 1) if n not in pi]
        out["sigma_occupied"] = sigma
        out["sigma_occupied_str"] = format_orbital_ranges(sigma)
    return out


def detect_pi_orbitals(fchk_path, multiwfn_exe, timeout=600, on_log=None):
    """对 ``fchk_path`` 跑一遍 Multiwfn 的 π 轨道检测，返回 :func:`parse_pi_output` 的结果。

    ``fchk_path`` 会先复制到一个临时 ASCII 目录（Multiwfn 对非 ASCII 路径与
    空格不友好，项目里其它流程也是这么做的）。失败时抛 ``RuntimeError``。
    """
    def log(msg):
        if on_log:
            on_log(str(msg))

    if not fchk_path or not os.path.isfile(fchk_path):
        raise RuntimeError("找不到 fchk 文件（先在主界面打开体系的 fchk）")
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise RuntimeError("Multiwfn 路径未设置或不存在")

    work = os.path.join(os.path.dirname(os.path.abspath(fchk_path)),
                        "_multiwfn_pi")
    os.makedirs(work, exist_ok=True)
    local = os.path.join(work, "sys.fchk")
    shutil.copy2(fchk_path, local)

    log("运行 Multiwfn：主功能 100 → 22（检测 π 轨道）…")
    try:
        # 把输入文件作为参数传（与 esp/aim 面板的写法一致；序列开头那个空行
        # 用来吃掉缺 settings.ini 时的 "Press ENTER button to continue"）
        text = _run_multiwfn([multiwfn_exe, "sys.fchk"], PI_DETECT_SEQUENCE,
                             cwd=work, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError(f"Multiwfn 运行失败：{exc}") from exc

    result = parse_pi_output(text)
    if not result["pi_all"] and not result["n_pi_all"]:
        raise RuntimeError("没能从 Multiwfn 输出里解析到 π 轨道信息"
                           "（体系可能不是共平面，或 Multiwfn 版本较旧）")
    result["log"] = text
    log("检测到 π 轨道 %d 个（其中占据 %d 个：%s）"
        % (result["n_pi_all"] or len(result["pi_all"]),
           len(result["pi_occupied"]), result["pi_occupied_str"] or "-"))
    return result


def parse_pi_projection(text):
    """解析 LMO 投影流程的输出：每个轨道的 π 成份。

    输出里会有若干行::

        Orbital    17 (Occ= 2.00000)   pi composition: 100.000%

    只有 π 成份不低于阈值的轨道才会被打印（阈值由输入给定）。

    Returns
    -------
    dict
        ``{"composition": {轨道号: (占据数, π 成份 %)}, "n_occupied": int,
        "n_pi_all": int}``
    """
    comp = {}
    for m in re.finditer(
            r"Orbital\s+(\d+)\s+\(Occ=\s*(-?[\d.]+)\)\s+"
            r"pi composition:\s*([\d.]+)\s*%", text):
        comp[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    base = parse_pi_output(text)
    return {"composition": comp, "n_occupied": base["n_occupied"],
            "n_pi_all": base["n_pi_all"]}


def detect_pi_by_projection(fchk_path, multiwfn_exe, threshold=80,
                            timeout=1800, on_log=None):
    """**非平面 / 扭曲体系**用：定域化 + π 型 LMO 投影，得到每个轨道的 π 成份。

    流程（Multiwfn 手册 4.100.22 的例子，由 sobereva 的《Multiwfn已支持计算任意
    轨道的pi成份》介绍）：先做 Pipek-Mezey 定域化得到 LMO，再判定哪些 LMO 是
    π 型，然后把目标波函数（原始的 MO / NTO / 自然轨道）向这些 π 型 LMO 投影，
    投影贡献即该轨道的 π 成份。体系扭曲时 σ/π 有混合、平面判据失效，这时用
    阈值（sob 建议 80%）挑 π 轨道最客观。

    Returns
    -------
    dict
        与 :func:`detect_pi_orbitals` 同形，另加 ``mode="projection"``、
        ``threshold``、``composition``（轨道号 → (占据数, π 成份 %)）。
        ``pi_occupied`` 是"占据且 π 成份 ≥ threshold"的轨道编号。
    """
    def log(msg):
        if on_log:
            on_log(str(msg))

    if not fchk_path or not os.path.isfile(fchk_path):
        raise RuntimeError("找不到 fchk 文件（先在主界面打开体系的 fchk）")
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise RuntimeError("Multiwfn 路径未设置或不存在")

    work = os.path.join(os.path.dirname(os.path.abspath(fchk_path)),
                        "_multiwfn_pi")
    os.makedirs(work, exist_ok=True)
    local = os.path.join(work, "sys.fchk")
    shutil.copy2(fchk_path, local)

    log("运行 Multiwfn：定域化轨道 → 检测 π 型 LMO → 投影出各轨道 π 成份"
        "（阈值 %s%%）…" % threshold)
    seq = PI_PROJECTION_SEQUENCE.format(molecule="sys.fchk",
                                        threshold=int(threshold))
    try:
        text = _run_multiwfn([multiwfn_exe, "sys.fchk"], seq, cwd=work,
                             timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError(f"Multiwfn 运行失败：{exc}") from exc

    parsed = parse_pi_projection(text)
    comp = parsed["composition"]
    if not comp:
        raise RuntimeError("没能从 Multiwfn 输出里解析到 π 成份"
                           "（可能是 Multiwfn 版本较旧，或定域化没收敛）")
    n_occ = parsed["n_occupied"]
    pi_occ = sorted(o for o, (occ, pct) in comp.items()
                    if occ > 0 and pct >= float(threshold))
    result = {
        "mode": "projection",
        "threshold": float(threshold),
        "composition": comp,
        "pi_all": [(o, comp[o][0], 0.0) for o in sorted(comp)],
        "n_pi_all": len(comp),
        "n_occupied": n_occ,
        "pi_occupied": pi_occ,
        "pi_occupied_str": ",".join(str(o) for o in pi_occ),
        "plane_hint": "",
        "log": text,
    }
    if n_occ and pi_occ:
        pi = set(pi_occ)
        sigma = [n for n in range(1, n_occ + 1) if n not in pi]
        result["sigma_occupied"] = sigma
        result["sigma_occupied_str"] = format_orbital_ranges(sigma)
    else:
        result["sigma_occupied"] = []
        result["sigma_occupied_str"] = ""
    log("π 成份 ≥ %s%% 的占据轨道：%s"
        % (threshold, result["pi_occupied_str"] or "-"))
    return result
