# -*- coding: utf-8 -*-
"""高斯 × xTB 联用（Gaussian External 接口）的纯逻辑。

联用原理
--------
高斯支持 ``#p opt external='命令'``：每走一步优化，就把当前几何（Bohr）、
电荷、多重度写进一个文本文件，调用 ``命令 layer Input Output Msg FChk MatEl``，
读回外部程序算出的**能量 / 梯度 / Hessian**，再继续优化。于是"高斯只当优化器，
能量和梯度由 xTB 提供"，可以用 GFN2-xTB 的速度跑大体系预优化。

本模块只负责"把这条路铺好"：

* :func:`prepare_bridge_route` —— 清掉路由里的方法关键字（有方法时高斯会
  **静默忽略 external** 自己去跑 SCF），并给含 Z>54 的体系补一个合法基组
  （高斯建基组这一步永远执行，默认 STO-3G 只覆盖到 Xe）；
* :func:`inject_external` —— 把 ``external='...'`` 注入 .gjf；
* :func:`write_client_bat` —— 写高斯要调用的包装 bat（``python gau_xtb.py %*``）；
* :func:`build_bridge_env` —— 组装 ``GAU_XTB_*`` 环境变量；
* :func:`xtb_bridge_argv` —— 复现每一步真正执行的 xTB 命令行（界面预览用）。

真正被高斯调用的脚本是 :mod:`molstudio.tools.gau_xtb`（xTBridge，MIT），
移植时未改协议；本模块与它通过环境变量通信，两边必须保持一致。
"""

from __future__ import annotations

import ctypes
import os
import re
import shlex
import sys
from pathlib import Path

__all__ = [
    "STO3G_MAX_Z", "DEFAULT_HEAVY_BASIS", "CLIENT_BAT_NAME",
    "is_method_keyword", "is_basis_token", "is_heavy_element_basis",
    "prepare_bridge_route", "inject_external", "external_route",
    "gau_xtb_script_path", "python_launcher", "write_client_bat",
    "short_path", "build_bridge_env", "xtb_bridge_argv",
]

#: 高斯默认基组 STO-3G 覆盖到的最大原子序数（Xe）
STO3G_MAX_Z = 54
#: 覆盖 H–Rn 且自带 ECP 的重元素基组（联用时基组只用于通过建基组这一步）
DEFAULT_HEAVY_BASIS = "sdd"
#: 高斯 External 调用的包装脚本名
CLIENT_BAT_NAME = "gau_xtb_client.bat"

# 方法关键字（含 DFT/后 HF/半经验/复合方法），命中即需要丢掉
_METHOD_EXACT = {
    "hf", "rhf", "uhf", "hfs", "mp2", "mp3", "mp4", "mp5", "ccsd", "ccsd(t)",
    "qcidd", "qcisd", "cisd", "cis", "bd", "gvb", "cas", "caspt2", "sci",
    "mcscf", "am1", "pm3", "pm6", "pm7", "rm1", "mndo", "indo", "cndo",
    "zindo", "xtb", "pbe", "pbe0", "pbe1pbe", "pbesol", "b3lyp", "b3pw91",
    "blyp", "bp86", "bpw91", "opbe", "olyp", "tpss", "tpssh", "m06", "m06l",
    "m06-2x", "m06-hf", "mn15", "mn15l", "wb97x", "wb97xd", "b97d", "b97d3",
    "svwn", "svwn5", "cam-b3lyp", "lc-wpbe", "hse06", "hseh1pbe", "b2plyp",
    "b2gp-plyp", "mpw1k", "x3lyp", "hf-3c", "b97-3c", "r2scan-3c", "cbs-qb3",
    "cbs-4m", "g4",
}

# 片段匹配（覆盖带后缀/修饰的写法，如 wb97x-d3bj、pbe0-d3）
_METHOD_FRAGMENTS = (
    "b3lyp", "b3pw91", "blyp", "bp86", "bpw91", "opbe", "olyp", "pbe", "b97",
    "m06", "mn15", "wb97", "tpss", "r2scan", "ccsd", "mp2", "mp4", "qp2",
    "cam-", "lc-", "hse", "svwn", "2plyp", "mpw", "x3lyp", "cbs-",
    "hf-3c", "3c", "pm6", "pm7", "am1", "rm1",
)

# 基组（用于判断路由里是否已经写了基组）
_BASIS_EXACT = {"gen", "genecp"}
_BASIS_FRAGMENTS = (
    "sto-", "3-21", "4-31", "6-31", "6-311", "cc-pv", "aug-cc", "def2",
    "lanl2", "sdd", "shf", "cep-", "sbk", "dgdzvp", "midix", "wtbs", "roos",
    "sdb-", "crenbl", "dhf",
)

# 覆盖重元素（含 ECP）的基组；只有这些才能建出 Z>54 的基组
_HEAVY_BASIS_EXACT = {"gen", "genecp"}
_HEAVY_BASIS_FRAGMENTS = (
    "sdd", "lanl2", "def2", "cep-", "sbk", "shf", "sdb-", "crenbl", "dhf",
)

_ROUTE_LINE_RE = re.compile(r"^\s*#")
_EXTERNAL_RE = re.compile(r"\bexternal\s*=\s*", re.IGNORECASE)


# ── 路由整理 ──────────────────────────────────────────────────────────
def _norm(token):
    return str(token or "").strip().lower()


def is_method_keyword(token):
    """判断路由里的一个 token 是不是"方法"关键字。"""
    text = _norm(token)
    if not text:
        return False
    head = text.split("/", 1)[0]          # b3lyp/sdd → b3lyp
    if head in _METHOD_EXACT:
        return True
    return any(frag in head for frag in _METHOD_FRAGMENTS)


def is_basis_token(token):
    """判断路由里的一个 token 是不是基组。"""
    text = _norm(token)
    if not text:
        return False
    tail = text.split("/")[-1]            # b3lyp/sdd → sdd
    return tail in _BASIS_EXACT or any(frag in tail
                                       for frag in _BASIS_FRAGMENTS)


def is_heavy_element_basis(token):
    """判断基组是否覆盖重元素（自带 ECP）。"""
    text = _norm(token)
    tail = text.split("/")[-1]
    return tail in _HEAVY_BASIS_EXACT or any(
        frag in tail for frag in _HEAVY_BASIS_FRAGMENTS)


def prepare_bridge_route(route, max_z=0, default="opt"):
    """把路由整理成"必定走 External 联用"的形式。

    返回 ``(整理后的路由, 提示列表)``：

    * 丢掉方法关键字（``b3lyp/sdd`` 这种写法保留基组部分）——路由里有方法时
      高斯会**静默忽略 external**，自己跑真实 SCF；
    * ``max_z > 54`` 时保证路由里有覆盖重元素的基组（默认 ``sdd``），否则高斯
      在 Link 301 建 STO-3G 基组时就退出，根本轮不到 external；
    * 其他功能关键字（opt/freq/ts/calcfc/modredundant…）原样保留。
    """
    notes = []
    text = str(route or "").strip() or default
    kept, removed, bases = [], [], []
    for token in text.split():
        if "/" in token:
            head, tail = token.split("/", 1)
            if is_method_keyword(head):
                removed.append(head)
                if tail.strip():
                    kept.append(tail.strip())
                    if is_basis_token(tail):
                        bases.append(tail.strip())
                continue
        elif is_method_keyword(token):
            removed.append(token)
            continue
        kept.append(token)
        if is_basis_token(token):
            bases.append(token)

    if removed:
        notes.append("已去掉方法关键字 %s：路由里写了方法时高斯会忽略 "
                     "external，改为自己跑 SCF。" % "、".join(removed))

    max_z = int(max_z or 0)
    if max_z > STO3G_MAX_Z:
        heavy = [b for b in bases if is_heavy_element_basis(b)]
        if not bases:
            kept.append(DEFAULT_HEAVY_BASIS)
            notes.append("已补基组 %s：体系含 Z=%d 的元素，高斯默认 STO-3G 只"
                         "覆盖到 Xe，未给基组会在建基组时直接退出。"
                         % (DEFAULT_HEAVY_BASIS, max_z))
        elif not heavy:
            for index, token in enumerate(kept):
                if is_basis_token(token):
                    notes.append("已把基组 %s 换成 %s：它覆盖不到 Z=%d 的元素，"
                                 "而联用时基组只用于通过建基组这一步。"
                                 % (token, DEFAULT_HEAVY_BASIS, max_z))
                    kept[index] = DEFAULT_HEAVY_BASIS
                    break
    return " ".join(kept), notes


def external_route(route, external_cmd):
    """拼出 ``#P <route> external='<cmd>'``（面板为准的完整路由行）。"""
    body = str(route or "").strip()
    if body.startswith("#"):
        body = body.lstrip("#").strip()
        if body[:1].lower() == "p":
            body = body[1:].strip()
    if body:
        return "#P %s external='%s'" % (body, str(external_cmd).strip())
    return "#P external='%s'" % str(external_cmd).strip()


def inject_external(content, external_cmd, route_override=None):
    """把 ``external='...'`` 注入 .gjf 文本；找不到路由行时返回 ``None``。

    ``route_override`` 不为 None 时整段路由替换为
    ``#P <route_override> external='<cmd>'``；为 None 时保留原路由、只替换/
    追加 external。
    """
    lines = str(content or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if _ROUTE_LINE_RE.match(line):
            start = index
            break
    if start is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if not lines[index].strip():
            end = index
            break

    new_lines = list(lines)
    if route_override is not None:
        new_lines[start] = external_route(route_override, external_cmd)
        for index in range(end - 1, start, -1):
            del new_lines[index]
        return "\n".join(new_lines)

    route_lines = lines[start:end]
    joined = " ".join(line.strip() for line in route_lines)
    if _EXTERNAL_RE.search(joined):
        # 用函数形式替换，避免 Windows 路径里的反斜杠被 re.sub 当转义
        joined = re.sub(
            r"\s*external\s*=\s*(['\"`]).*?\1",
            lambda _m: " external='%s'" % external_cmd,
            joined, count=1, flags=re.IGNORECASE)
        joined = re.sub(
            r"\s*external\s*=\s*\S+",
            lambda _m: " external='%s'" % external_cmd,
            joined, count=1, flags=re.IGNORECASE)
        new_lines[start] = joined
        for index in range(end - 1, start, -1):
            del new_lines[index]
    else:
        new_lines[end - 1] = (new_lines[end - 1].rstrip()
                              + " external='%s'" % external_cmd)
    return "\n".join(new_lines)


# ── 客户端脚本（高斯调用的 bat）────────────────────────────────────
def gau_xtb_script_path():
    """随程序分发的 ``gau_xtb.py`` 的绝对路径。"""
    import molstudio                                      # noqa: PLC0415
    root = Path(molstudio.__file__).resolve().parent
    script = root / "tools" / "gau_xtb.py"
    if not script.is_file():
        raise FileNotFoundError("找不到 %s" % script)
    return str(script)


def python_launcher():
    """运行 gau_xtb.py 的解释器命令（不带引号；打包后优先 ``py -3``）。

    可用环境变量 ``MOLSTUDIO_PYTHON`` 覆盖（填 python.exe 的完整路径）。
    """
    override = os.environ.get("MOLSTUDIO_PYTHON", "").strip()
    if override:
        return override
    if getattr(sys, "frozen", False):
        return "py -3"
    return sys.executable or "python"


def short_path(path):
    """把路径换成 Windows 8.3 短名（去空格）；拿不到就原样返回。"""
    path = str(path)
    if os.name != "nt" or " " not in path:
        return path
    try:
        buf = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
        if length and buf.value and " " not in buf.value:
            return buf.value
    except Exception:                                     # noqa: BLE001
        pass
    return path


def _bat_bytes(content):
    """把 bat 内容编码成 cmd.exe 能读的字节。

    Windows 的 ``cmd.exe`` 按系统 ANSI 代码页（中文系统是 GBK）解析 .bat，
    所以优先 ``mbcs``；装到中文路径时写 UTF-8 会让 cmd 读成乱码、路径失效。
    """
    encodings = ("mbcs", "utf-8") if os.name == "nt" else ("utf-8",)
    for encoding in encodings:
        try:
            return content.encode(encoding)
        except (UnicodeEncodeError, LookupError):
            continue
    return content.encode("utf-8", "replace")


def write_client_bat(dest_dir=None, python_exe=None):
    """写高斯要调用的包装 bat，返回它的路径。

    内容形如 ``"<python>" "<...>/gau_xtb.py" %*``：Gaussian 把
    ``layer Input Output Msg FChk MatEl`` 原样传给 gau_xtb.py。写不进去时
    退到系统临时目录。
    """
    script = gau_xtb_script_path()
    launcher = str(python_exe or python_launcher()).strip()
    if launcher.lower().endswith(".exe"):
        command = '"%s" "%s"' % (launcher, script)
    else:
        command = '%s "%s"' % (launcher, script)
    content = "@echo off\r\n%s %%*\r\n" % command
    payload = _bat_bytes(content)

    candidates = []
    if dest_dir:
        candidates.append(Path(dest_dir) / CLIENT_BAT_NAME)
    candidates.append(Path(os.environ.get("TEMP") or os.getcwd())
                      / "molstudio_xtb_bridge" / CLIENT_BAT_NAME)
    last_error = None
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return str(path)
        except (OSError, ValueError) as exc:              # noqa: PERF203
            last_error = exc
    raise OSError("无法写入 %s：%s" % (CLIENT_BAT_NAME, last_error))


# ── 环境变量与命令预览 ───────────────────────────────────────────────
def build_bridge_env(base_env, xtb_path, method_args="", gfn="", threads=0,
                     extra_args=""):
    """组装 ``GAU_XTB_*`` 环境变量（在 ``base_env`` 的副本上改）。

    ``method_args``（如 ``"--gfn 2 --alpb water"``）优先；只给 ``gfn`` 时退回
    旧行为（``--gfn <gfn>``）。参数与 :mod:`molstudio.tools.gau_xtb` 一致。
    """
    env = dict(os.environ if base_env is None else base_env)
    text = str(method_args or "").strip()
    if text:
        env["GAU_XTB_METHOD"] = text
        env.pop("GAU_XTB_GFN", None)
    elif str(gfn or "").strip():
        env["GAU_XTB_GFN"] = str(gfn).strip()
        env.pop("GAU_XTB_METHOD", None)
    else:
        env.pop("GAU_XTB_METHOD", None)
        env.pop("GAU_XTB_GFN", None)
    if xtb_path:
        env["GAU_XTB_COMMAND"] = str(xtb_path)
    if threads:
        env["GAU_XTB_THREADS"] = str(int(threads))
    extra = str(extra_args or "").strip()
    if extra:
        env["GAU_XTB_ARGS"] = extra
    else:
        env.pop("GAU_XTB_ARGS", None)
    return env


def xtb_bridge_argv(xtb_path, charge, uhf, method_args="", threads=0,
                    extra_args="", derivs=1):
    """复现每一步真正执行的 xTB 命令行（界面预览 / 测试对照用）。"""
    argv = [str(xtb_path or "xtb"), "mol.xyz",
            "--chrg", str(int(charge)), "--uhf", str(int(uhf))]
    text = str(method_args or "").strip()
    if text.lstrip("-").isdigit():            # 兼容只给 "2" / "0" 的写法
        text = "--gfn %s" % text
    if text:
        argv += shlex.split(text, posix=os.name != "nt")
    if threads:
        argv += ["--parallel", str(int(threads))]
    extra = str(extra_args or "").strip()
    if extra:
        argv += shlex.split(extra, posix=os.name != "nt")
    derivs = int(derivs)
    if derivs <= 0:
        argv.append("--sp")
    elif derivs == 1:
        argv.append("--grad")
    else:
        argv += ["--hess", "--grad"]
    return argv
