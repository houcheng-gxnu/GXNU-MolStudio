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
import subprocess
import sys
import time

from molstudio.core.fchk_orbital import DEFAULT_GAUSSIAN, find_gaussian

__all__ = ["run_gaussian", "GaussianJobResult", "gaussian_env",
           "find_gaussian", "find_formchk", "chk_to_fchk", "find_chk_file",
           "missing_nmr_links",
           "DEFAULT_GAUSSIAN", "MILESTONES"]

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


def chk_to_fchk(chk_path, formchk_exe=None, timeout=300):
    """``formchk`` 把 .chk 转成 .fchk（Multiwfn 的 π 轨道分析要用）。

    返回 fchk 路径；失败抛 ``RuntimeError``（调用方负责显示）。
    """
    if not chk_path or not os.path.isfile(chk_path):
        raise RuntimeError("找不到 chk 文件")
    exe = formchk_exe or find_formchk()
    if not exe or not os.path.isfile(exe):
        raise RuntimeError("找不到 formchk.exe（应与 g16.exe 在同一目录）")
    fchk = os.path.splitext(os.path.abspath(chk_path))[0] + ".fchk"
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


def run_gaussian(gjf_path, g16_exe=None, log_path=None, on_line=None,
                 cancel=None, timeout=None):
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
    proc = subprocess.Popen(
        [g16_exe, os.path.basename(gjf_path), os.path.basename(log_path)],
        cwd=workdir, env=gaussian_env(g16_exe),
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
