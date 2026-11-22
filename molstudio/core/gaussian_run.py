# -*- coding: utf-8 -*-
"""
在本机跑 Gaussian 任务（.gjf → .log + 张量 txt，全在同一个目录）
================================================================

AICD 的完整工作流是「建结构 → 生成 .gjf → 跑 Gaussian → 拿 .log 与张量 txt
分析」。本模块负责中间"跑"这一步：调本机 ``g16.exe``，把输出写成与输入同名的
``.log``（放在 **.gjf 所在目录**，这样 Gaussian 顺手写出的张量 txt 也落在同一个
目录，AICD 面板才找得到），并把日志逐行喂给回调，供界面显示进度。

Windows 上的两个坑（实测踩过）：

* ``g16.exe`` 自己不设环境变量的话会报 ``Search path GAUSS_EXEDIR is ""``
  然后 ``No executable for file l1.exe`` —— 必须显式给 ``GAUSS_EXEDIR``；
* 顺带给 ``GAUSS_SCRDIR``，否则会落到安装目录的默认 scratch（空间/权限都
  不一定合适）。

本模块不依赖 Qt（``run_gaussian`` 是同步阻塞的），界面里把它放进 QThread 即可。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from molstudio.core.fchk_orbital import DEFAULT_GAUSSIAN, find_gaussian

__all__ = ["run_gaussian", "GaussianJobResult", "gaussian_env",
           "find_gaussian", "find_formchk", "chk_to_fchk", "find_chk_file",
           "missing_nmr_links", "JOB_TYPES", "build_route", "build_gjf",
           "parse_output", "read_gjf_charge_mult",
           "DEFAULT_GAUSSIAN", "MILESTONES"]

#: 任务类型 → Gaussian 关键字 / 中英文名
JOB_TYPES = {
    "sp": {"gaussian": "", "zh": "单点能", "en": "Single point"},
    "opt": {"gaussian": "opt", "zh": "几何优化", "en": "Optimization"},
    "freq": {"gaussian": "freq", "zh": "频率", "en": "Frequencies"},
    "opt_freq": {"gaussian": "opt freq", "zh": "优化 + 频率",
                 "en": "Optimization + frequencies"},
    "ts": {"gaussian": "opt=(ts,calcfc,noeigentest)", "zh": "过渡态优化",
           "en": "Transition state optimization"},
    "ts_freq": {"gaussian": "opt=(ts,calcfc,noeigentest) freq",
                "zh": "过渡态优化 + 频率",
                "en": "Transition state optimization + frequencies"},
    "irc": {"gaussian": "irc=(forward,calcfc,maxpoints=30)",
            "zh": "IRC 反应路径", "en": "IRC path"},
    "td": {"gaussian": "td=(nstates=10)", "zh": "TD-DFT 激发态",
           "en": "TD-DFT excitations"},
    "custom": {"gaussian": "", "zh": "自定义", "en": "Custom"},
}

#: 常见泛函
COMMON_METHODS = (
    "B3LYP", "B3LYP-D3BJ", "PBE0", "M06-2X", "M06L", "wB97XD", "wB97X-D3",
    "r2SCAN-3c", "PBE", "TPSS", "HF", "MP2", "CCSD(T)", "APFD",
)

#: 常见基组
COMMON_BASES = ("6-31G(d)", "6-31+G(d,p)", "6-311+G(d,p)", "def2SVP",
                "def2TZVP", "def2TZVPP", "cc-pVDZ", "cc-pVTZ", "STO-3G")

#: 常见溶剂（Gaussian scrf 名称）
COMMON_SOLVENTS = ("water", "methanol", "ethanol", "acetonitrile",
                   "dichloromethane", "chloroform", "toluene", "thf",
                   "dmso", "acetone", "benzene")

_SCF_DONE_RE = re.compile(
    r"SCF Done:\s+E\([^)]*\)\s*=\s*([+-]?(?:\d+\.\d*|\.\d+))")
_OCC_RE = re.compile(r"^Alpha\s+occ\.\s+eigenvalues\s+--\s*(.*)$")
_VIRT_RE = re.compile(r"^Alpha\s+virt\.\s+eigenvalues\s+--\s*(.*)$")
_CHARGE_MULT_RE = re.compile(
    r"Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=\s*([+-]?\d+)")
_FREQ_RE = re.compile(r"^\s*Frequencies\s+--\s+(.*)$")
_ORIENTATION_HEADERS = ("Standard orientation:", "Input orientation:")


#: 日志里值得在界面上点出来的里程碑（前缀匹配）
MILESTONES = (
    ("entering link 1", "Gaussian 启动"),
    ("SCF Done", "SCF 收敛"),
    ("Writing AICD formatted file", "电流密度张量已写出"),
    ("Normal termination of Gaussian", "正常结束"),
    ("Error termination", "异常终止"),
)


class GaussianJobResult:
    """一次 Gaussian 任务的结果。"""

    def __init__(self, ok, log_path, returncode, tensor_path="", seconds=0.0,
                 cancelled=False, error=""):
        self.ok = bool(ok)
        self.log_path = log_path
        self.returncode = returncode
        self.tensor_path = tensor_path
        self.seconds = float(seconds)
        self.cancelled = bool(cancelled)
        self.error = error

    def __repr__(self):
        return (f"GaussianJobResult(ok={self.ok}, rc={self.returncode}, "
                f"log={os.path.basename(self.log_path or '')!r}, "
                f"tensor={os.path.basename(self.tensor_path or '')!r}, "
                f"cancelled={self.cancelled})")


def gaussian_env(exe_path):
    """给 g16.exe 准备好运行环境（GAUSS_EXEDIR / GAUSS_SCRDIR）。"""
    env = dict(os.environ)
    exe = os.path.abspath(exe_path)
    gauss_dir = os.path.dirname(exe)
    env["GAUSS_EXEDIR"] = gauss_dir
    # scratch：优先用安装目录里现成的 Scratch，其次系统临时目录下的专用子目录
    scratch = os.path.join(gauss_dir, "Scratch")
    if not os.path.isdir(scratch):
        scratch = os.path.join(os.environ.get("TEMP", gauss_dir),
                               "molstudio_gauss_scratch")
    try:
        os.makedirs(scratch, exist_ok=True)
    except OSError:
        scratch = gauss_dir
    env["GAUSS_SCRDIR"] = scratch
    return env


def _kill_tree(proc):
    """终止整个任务树：Gaussian 会派生子进程（l1/l502/…），只 kill 父进程不够。"""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=20)
        else:
            proc.terminate()
    except Exception:                                    # noqa: BLE001
        try:
            proc.kill()
        except Exception:                                # noqa: BLE001
            pass


def find_formchk(g16_exe=None):
    """找 ``formchk.exe``（Gaussian 安装目录里与 g16.exe 同放）。找不到返回空串。"""
    exe = g16_exe or DEFAULT_GAUSSIAN
    folder = os.path.dirname(exe) if exe else ""
    if folder:
        cand = os.path.join(folder, "formchk.exe")
        if os.path.isfile(cand):
            return cand
    return ""


def missing_nmr_links(g16_exe=None):
    """检查 Gaussian 的 NMR 链接是否齐全（G16W 需要同目录的 ``l801.exe``）。

    返回缺失的文件名列表。杀软（360/Defender 等）误报隔离是常见原因——
    缺了它，``nmr=csgt`` 任务会跑完 SCF 后立刻报 ``No executable for file
    l801.exe``，白等一轮。
    """
    exe = g16_exe or DEFAULT_GAUSSIAN
    folder = os.path.dirname(exe) if exe else ""
    if not folder or not os.path.isdir(folder):
        return []
    return [name for name in ("l801.exe",)
            if not os.path.isfile(os.path.join(folder, name))]


def find_chk_file(log_path):
    """从 Gaussian 输出里的 ``%chk=...`` 行找出检查点文件；找不到就按同名猜。"""
    stem = os.path.splitext(os.path.abspath(log_path))[0]
    chk = ""
    try:
        with open(log_path, "r", errors="replace") as fh:
            for line in fh:
                if line.strip().lower().startswith("%chk="):
                    chk = line.split("=", 1)[1].strip()
                    break
    except OSError:
        return ""
    candidates = []
    if chk:
        candidates.append(chk)
        if not os.path.isabs(chk):
            candidates.append(os.path.join(os.path.dirname(stem), chk))
    candidates.append(stem + ".chk")
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)
    return ""


def chk_to_fchk(chk_path, formchk_exe=None, timeout=300, output_path=None):
    """``formchk`` 把 .chk 转成 .fchk（Multiwfn 的 π 轨道分析要用）。

    ``output_path`` 可指定输出名；ETS-NOCV 流程用 ``.fch``，它与 ``.fchk``
    是同一格式。省略时保持原来的同名 ``.fchk`` 行为，兼容 AICD 等模块。

    返回 fchk 路径；失败抛 ``RuntimeError``（调用方负责显示）。
    """
    if not chk_path or not os.path.isfile(chk_path):
        raise RuntimeError("找不到 chk 文件")
    exe = formchk_exe or find_formchk()
    if not exe or not os.path.isfile(exe):
        raise RuntimeError("找不到 formchk.exe（应与 g16.exe 在同一目录）")
    fchk = (os.path.abspath(output_path) if output_path else
            os.path.splitext(os.path.abspath(chk_path))[0] + ".fchk")
    os.makedirs(os.path.dirname(fchk), exist_ok=True)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(
        [exe, os.path.basename(chk_path), os.path.basename(fchk)],
        cwd=os.path.dirname(os.path.abspath(chk_path)),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=creationflags, timeout=timeout,
        encoding="utf-8", errors="replace")
    if not os.path.isfile(fchk) or os.path.getsize(fchk) == 0:
        raise RuntimeError("formchk 失败：%s" % ((proc.stdout or "").strip()[:300]))
    return fchk


def _clean_line(text):
    return " ".join(str(text or "").split())


def build_route(method="B3LYP", basis="6-31G(d)", task="opt", dispersion="",
                solvent="", solvent_model="cpcm", extra_keywords="",
                include_method=True, td_nroots=10):
    """拼 Gaussian 路由行（``#p ...``）。

    ``include_method=False`` 用于**高斯 × xTB 联用**：路由里不能出现方法关键字，
    否则高斯会静默忽略 ``external`` 自己去跑 SCF（见
    :mod:`molstudio.core.xtb_bridge`）。
    """
    task = str(task or "sp").lower()
    if task not in JOB_TYPES:
        raise ValueError("未知任务类型：%s" % task)
    parts = ["#p"]
    if include_method:
        method = _clean_line(method)
        basis = _clean_line(basis)
        if not method:
            raise ValueError("方法不能为空")
        parts.append(method + ("/" + basis if basis else ""))
    job_kw = JOB_TYPES[task]["gaussian"]
    if task == "td" and int(td_nroots or 0) > 0:
        job_kw = "td=(nstates=%d)" % int(td_nroots)
    if job_kw:
        parts.append(job_kw)
    dispersion = _clean_line(dispersion).upper()
    if dispersion:
        parts.append("empiricaldispersion=%s" % dispersion.lower())
    if solvent:
        model = "smd" if str(solvent_model).lower() == "smd" else "cpcm"
        parts.append("scrf=(%s,solvent=%s)"
                     % (model, _clean_line(solvent).lower()))
    extra = _clean_line(extra_keywords)
    if extra:
        parts.append(extra)
    return " ".join(parts)


def build_gjf(symbols, coords, charge=0, mult=1, route="#p hf/sto-3g",
              title="MolStudio", nproc=4, mem_gb=8, chk_name=""):
    """生成 Gaussian 输入文本（``%nprocshared`` / ``%mem`` / ``%chk`` + 坐标）。"""
    symbols = [str(s).strip() for s in (symbols or [])]
    if not symbols:
        raise ValueError("没有原子：请先载入结构")
    if len(symbols) != len(coords or []):
        raise ValueError("原子符号与坐标数量不一致")
    try:
        charge = int(charge)
        mult = int(mult)
        nproc = int(nproc)
        mem_gb = int(mem_gb)
    except (TypeError, ValueError) as exc:
        raise ValueError("电荷/多重度/核数/内存必须是整数") from exc
    if mult < 1:
        raise ValueError("多重度至少为 1")
    rows = []
    for symbol, xyz in zip(symbols, coords):
        if len(xyz) != 3:
            raise ValueError("坐标必须是三维：%r" % (xyz,))
        rows.append((symbol, float(xyz[0]), float(xyz[1]), float(xyz[2])))

    lines = []
    if nproc > 0:
        lines.append("%%nprocshared=%d" % nproc)
    if mem_gb > 0:
        lines.append("%%mem=%dGB" % mem_gb)
    if chk_name:
        lines.append("%%chk=%s" % chk_name)
    lines.append(str(route or "").strip() or "#p hf/sto-3g")
    lines.extend(["", str(title or "MolStudio").replace("\n", " "), "",
                  "%d %d" % (charge, mult)])
    for symbol, x, y, z in rows:
        lines.append("%-2s %16.10f %16.10f %16.10f" % (symbol, x, y, z))
    lines.append("")
    return "\n".join(lines) + "\n"


_GJF_CM_RE = re.compile(r"^\s*([+-]?\d+)\s+([+-]?\d+)\s*$")


def read_gjf_charge_mult(path):
    """读 Gaussian ``.gjf/.com`` 的电荷与多重度；读不到返回 ``(None, None)``。"""
    path = str(path)
    if os.path.splitext(path)[1].lower() not in (".gjf", ".com"):
        return None, None
    try:
        text = open(path, "r", encoding="utf-8", errors="ignore").read()
    except OSError:
        return None, None
    for line in text.splitlines():
        match = _GJF_CM_RE.match(line)
        if not match:
            continue
        charge, mult = int(match.group(1)), int(match.group(2))
        if mult < 1:
            continue
        return charge, mult
    return None, None


def _orientation_numbers(text):
    """取最后一个 orientation 表的 ``(原子序数, 坐标/Å)``（跳过中心原子号）。"""
    lines = (text or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() in _ORIENTATION_HEADERS:
            start = index
    if start is None:
        return [], []
    numbers, coords = [], []
    rows_started = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            if rows_started:
                break
            continue
        if set(stripped) <= {"-"} and len(stripped) >= 3:
            if rows_started:
                break
            continue
        parts = stripped.split()
        if len(parts) < 6:
            if rows_started:
                break
            continue
        try:
            znum = int(parts[1])
            x, y, z = float(parts[3]), float(parts[4]), float(parts[5])
        except (ValueError, IndexError):
            if rows_started:
                break
            continue
        rows_started = True
        numbers.append(znum)
        coords.append([x, y, z])
    return numbers, coords


def parse_output(text):
    """解析 Gaussian 输出文本，返回常用结果字典（缺失项为空）。

    联用（``external=''``）时能量行是 ``Recovered energy= ...``，这里也一并
    收集，``steps`` 就是已经走过的优化步数。
    """
    text = text or ""
    res = dict(
        energies=[], final_energy=None, recovered_energies=[],
        terminated_normally=False, opt_converged=False, frequencies=[],
        imaginary=[], symbols=[], geometry=[], charge=None, multiplicity=None,
        homo=None, lumo=None, homo_lumo_gap_ev=None, errors=[],
        steps=0, bridge=False,
    )
    res["energies"] = [float(m.group(1))
                       for m in _SCF_DONE_RE.finditer(text)]
    res["recovered_energies"] = [
        float(value) for value in
        re.findall(r"Recovered energy=\s*([+-]?\d+\.\d+)", text)]
    res["bridge"] = bool(res["recovered_energies"])
    if res["energies"]:
        res["final_energy"] = res["energies"][-1]
    elif res["recovered_energies"]:
        res["final_energy"] = res["recovered_energies"][-1]
    res["steps"] = (len(res["recovered_energies"]) if res["bridge"]
                    else len(res["energies"]))
    res["terminated_normally"] = "Normal termination of Gaussian" in text
    res["opt_converged"] = ("Stationary point found" in text
                            or "Optimization completed" in text)

    # 只取最后一次打印的占据/空轨道：看到空轨道之后再遇到占据行 → 新的一组
    occ, virt = [], []
    seen_virt = False
    for line in text.splitlines():
        stripped = line.strip()
        match = _OCC_RE.match(stripped)
        if match:
            if seen_virt:
                occ, virt, seen_virt = [], [], False
            occ.extend(float(v) for v in match.group(1).split()
                       if _is_float(v))
            continue
        match = _VIRT_RE.match(stripped)
        if match:
            seen_virt = True
            virt.extend(float(v) for v in match.group(1).split()
                        if _is_float(v))
    if occ:
        res["homo"] = occ[-1]
    if virt:
        res["lumo"] = virt[0]
    if res["homo"] is not None and res["lumo"] is not None:
        res["homo_lumo_gap_ev"] = round(
            (res["lumo"] - res["homo"]) * 27.211386245988, 6)

    freqs = []
    for line in text.splitlines():
        match = _FREQ_RE.match(line)
        if not match:
            continue
        freqs.extend(float(v) for v in match.group(1).split() if _is_float(v))
    res["frequencies"] = [f for f in freqs if abs(f) > 1.0]
    res["imaginary"] = [f for f in freqs if f < -1.0]

    for match in _CHARGE_MULT_RE.finditer(text):
        res["charge"] = int(match.group(1))
        res["multiplicity"] = int(match.group(2))

    numbers, coords = _orientation_numbers(text)
    for znum, xyz in zip(numbers, coords):
        try:
            from molstudio.core.surface_projection import element_symbol
            res["symbols"].append(element_symbol(znum))
        except Exception:                                     # noqa: BLE001
            res["symbols"].append(str(znum))
    res["geometry"] = coords

    for line in text.splitlines():
        stripped = line.strip()
        if ("Error termination" in stripped or "Erroneous" in stripped
                or stripped.startswith("===")):
            if "Error termination" in stripped or "Erroneous" in stripped:
                res["errors"].append(stripped)
    return res


def _is_float(token):
    try:
        float(token)
        return True
    except (TypeError, ValueError):
        return False


def run_gaussian(gjf_path, g16_exe=None, log_path=None, on_line=None,
                 cancel=None, timeout=None, extra_env=None):
    """同步跑一个 Gaussian 任务，返回 :class:`GaussianJobResult`。

    Parameters
    ----------
    gjf_path : str
        输入文件；输出 ``.log`` 与张量 txt 都写在**它所在目录**。
    g16_exe : str, optional
        Gaussian 可执行文件；默认取配置里的路径。
    log_path : str, optional
        输出日志路径；默认与输入同名（改后缀为 .log）。
    on_line : callable, optional
        每读到一行日志回调一次 ``on_line(line)``（界面用来滚动显示进度）。
    cancel : callable, optional
        返回 True 时终止任务（连同子进程）。
    timeout : float, optional
        秒；超时按取消处理。

    Returns
    -------
    GaussianJobResult
        ``ok`` 以日志里出现 ``Normal termination of Gaussian`` 为准（**不是**
        以返回码为准：Gaussian 正常结束的返回码不一定是 0）。
    """
    g16_exe = g16_exe or DEFAULT_GAUSSIAN
    if not g16_exe or not os.path.isfile(g16_exe):
        return GaussianJobResult(False, "", -1, error="找不到 Gaussian 可执行文件"
                                                      "（请在 ⚙️ 路径设置里配置）")
    if not gjf_path or not os.path.isfile(gjf_path):
        return GaussianJobResult(False, "", -1, error="找不到输入文件")

    workdir = os.path.dirname(os.path.abspath(gjf_path)) or "."
    stem = os.path.splitext(os.path.basename(gjf_path))[0]
    log_path = log_path or os.path.join(workdir, stem + ".log")
    started = time.time()

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    # ★ g16.exe 的控制台输出是空的（它把一切写进 .log 文件），所以进度只能
    #   跟着 .log 尾巴读——stdout 直接丢弃。
    env = gaussian_env(g16_exe)
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    proc = subprocess.Popen(
        [g16_exe, os.path.basename(gjf_path), os.path.basename(log_path)],
        cwd=workdir, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags)

    state = {"pos": 0, "buf": "", "normal": False}

    def drain():
        """把 .log 里新写出的完整行喂给 on_line（不完整的尾巴留到下次）。"""
        if not os.path.isfile(log_path):
            return
        try:
            with open(log_path, "r", errors="replace") as fh:
                fh.seek(state["pos"])
                chunk = fh.read()
                state["pos"] = fh.tell()
        except OSError:
            return
        if not chunk:
            return
        text = state["buf"] + chunk
        lines = text.split("\n")
        state["buf"] = lines.pop()          # 最后一段可能还没写完
        for line in lines:
            if on_line:
                on_line(line)
            if "Normal termination of Gaussian" in line:
                state["normal"] = True

    cancelled = False
    try:
        while proc.poll() is None:
            drain()
            if cancel is not None and cancel():
                cancelled = True
                _kill_tree(proc)
                break
            if timeout and (time.time() - started) > float(timeout):
                cancelled = True
                _kill_tree(proc)
                break
            time.sleep(0.3)
    finally:
        drain()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

    normal = state["normal"]
    if not normal and os.path.isfile(log_path):
        try:
            with open(log_path, "r", errors="replace") as fh:
                normal = "Normal termination of Gaussian" in fh.read()
        except OSError:
            normal = False

    tensor = ""
    try:
        from molstudio.core.aicd import find_tensor_file
        tensor = find_tensor_file(log_path) or ""
    except Exception:                                    # noqa: BLE001
        tensor = ""

    return GaussianJobResult(
        ok=normal and not cancelled, log_path=log_path,
        returncode=proc.returncode if proc.returncode is not None else -1,
        tensor_path=tensor, seconds=time.time() - started, cancelled=cancelled,
        error="" if (normal or cancelled) else "Gaussian 未正常结束（详见日志）")
