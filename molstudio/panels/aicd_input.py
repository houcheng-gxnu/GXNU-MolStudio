# -*- coding: utf-8 -*-
"""
AICD 的 Gaussian 输入生成器
============================

AICD 分析的数据来源是 Gaussian 的 ``nmr=csgt iop(10/93=1|2)`` 任务：算完之后
除了 ``.log``，还会在**同一个目录**里写出一个张量转储（默认 ``test.txt``）。
所以整条工作流是：

    建结构 → 本对话框生成 .gjf → 跑 Gaussian → 得到 .log + test.txt → 回面板分析

本模块只做中间那一步：把当前结构（画布上的分子，或从 xyz / gjf / log 文件读）
写成一份可直接交给 Gaussian 的输入，路由段、几何、张量文件名、以及
``IOp(10/93=2)`` 时的轨道编号列表都按能跑通的格式给好。

``build_aicd_input()`` 是纯函数（不依赖 Qt），方便单独测试/复用。
"""

from __future__ import annotations

import os
import re

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                             QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                             QWidget)

from molstudio.core import aicd as A
from molstudio.core import multiwfn_pi as MPI

#: 坐标行的第一个字段必须是元素符号（C / Cl / H1 / C2 …）。
#: 这条约束是踩过坑加上的：GaussView 出的 gjf 在坐标后面有 ``geom=connectivity``
#: 的连通性表，每行像 ``1 2 1.5 6 1.5 8 1.0``——字段数和浮点数都对得上，
#: 光看"≥4 个字段且后三个是浮点"会把连通性表当成原子读进去，生成出一份
#: 元素符号是 "1" 的假几何（Gaussian 直接报 Wanted a floating point number）。
_ATOM_TOKEN = re.compile(r"^[A-Za-z]{1,2}\d*$")
_INT_TOKEN = re.compile(r"^\d+$")


def _is_float(token):
    try:
        float(token)
        return True
    except (TypeError, ValueError):
        return False


def _atom_line(parts):
    """是否是坐标行：元素符号开头 + 紧跟三个浮点数。"""
    return (len(parts) >= 4 and bool(_ATOM_TOKEN.match(parts[0]))
            and all(_is_float(p) for p in parts[1:4]))


def element_label(value):
    """元素符号或原子序数 → 元素符号（Gaussian 输入用）。"""
    if isinstance(value, str) and value.strip():
        return value.strip().capitalize()
    try:
        return A.element_symbol(int(value))
    except (TypeError, ValueError):
        return str(value)


def build_aicd_input(atoms, method="b3lyp/6-31g(d)", extra="", charge=0, mult=1,
                     chk="", mem="", nproc=0, tensor_name="test.txt",
                     orbitals="", mode="all", title="AICD job",
                     connectivity=None):
    """拼一份 Gaussian 输入（返回字符串）。

    Parameters
    ----------
    atoms : sequence
        ``[(元素符号或原子序数, x, y, z), ...]``，坐标单位 Å。
    method : str
        方法与基组，写成 ``b3lyp/6-31g(d)`` 这种。
    extra : str
        附加关键词（例如 ``int(grid=ultrafine)``）。
    mode : {"all", "orbs"}
        ``all`` → ``IOp(10/93=1)``（全部轨道对电流密度的贡献）；
        ``orbs`` → ``IOp(10/93=2)``，并需要在张量文件名后列出轨道编号。
    orbitals : str
        ``mode="orbs"`` 时的轨道编号，例如 ``17,20,21`` 或 ``1-16,18-19``。
    connectivity : sequence of str, optional
        ``geom=connectivity`` 的连通性表（原样来自 GaussView 输出的 gjf）。
        有它就必须跟着 ``geom=connectivity`` 一起写，否则 Gaussian 会把
        后面的段当成连通性表读；反之路由里有 ``geom=connectivity`` 却没给表，
        这里会自动把该关键词去掉（宁可少一个无害关键词，也不要交一份跑不了的输入）。

    Returns
    -------
    str
        完整的 .gjf 文本（**两处关键约定**：路由里 ``nmr=csgt`` 与
        ``iop(10/93=…)`` 必须都有；几何后面那一行写张量文件名，Gaussian 会把
        电流密度张量写进它——它必须与 .log 落在同一个目录，AICD 面板才找得到）。
    """
    lines = []
    if chk:
        lines.append("%chk=" + str(chk).strip())
    if mem:
        lines.append("%mem=" + str(mem).strip())
    if nproc:
        lines.append(f"%nprocshared={int(nproc)}")

    route = "# " + method.strip()
    extra = extra.strip()
    if extra:
        route += " " + extra
    route += " nmr=csgt iop(10/93=%s)" % ("2" if mode == "orbs" else "1")
    conn = [ln for ln in (connectivity or []) if str(ln).strip()]
    if not conn and "geom=connectivity" in route.lower():
        # 没有连通性表却留着 geom=connectivity：去掉它（否则任务必然报错）
        route = re.sub(r"\s*geom=connectivity\b", "", route,
                       flags=re.IGNORECASE)
    lines.append(route)
    lines.append("")
    lines.append(title.strip() or "AICD job")
    lines.append("")
    lines.append("%d %d" % (int(charge), int(mult)))
    for atom in atoms:
        sym = element_label(atom[0])
        x, y, z = (float(v) for v in atom[1:4])
        lines.append("%-2s %14.8f %14.8f %14.8f" % (sym, x, y, z))
    lines.append("")
    if conn:
        lines.extend(conn)
        lines.append("")
    lines.append(str(tensor_name).strip() or "test.txt")
    if mode == "orbs":
        lines.append("")
        lines.append(orbitals.strip())
        # 列表后必须再留一个空行：Gaussian 的 AICD patch 在列表后没有
        # 空行时会漏读最后一个轨道（17,20,21 只算 17、20），π 等值面裂成六瓣。
        lines.append("")
        lines.append("")
    else:
        lines.append("")
    return "\n".join(lines)


def parse_structure_file(path):
    """从 xyz / gjf / com / log / out 里读结构，返回 ``[(符号, x, y, z)]``（Å）。

    只做够用的解析：xyz 走标准格式，gjf/com 取电荷多重度行之后的坐标块，
    Gaussian 输出复用 :func:`molstudio.core.aicd.read_standard_orientation`。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".log", ".out"):
        atoms = A.read_standard_orientation(path)
        if not atoms:
            raise ValueError("这个输出里找不到 Standard orientation 几何")
        # 注意别把原子序数和 z 坐标用同一个变量名（曾因此把元素全写成 X）
        return [(A.element_symbol(anum), x, y, zz)
                for anum, x, y, zz in atoms]

    with open(path, "r", errors="replace") as fh:
        lines = fh.read().splitlines()

    if ext == ".xyz":
        try:
            n = int(lines[0].split()[0])
        except (IndexError, ValueError):
            raise ValueError("xyz 第一行不是原子数")
        atoms = []
        for line in lines[2:2 + n]:
            parts = line.split()
            if len(parts) >= 4:
                atoms.append((parts[0], float(parts[1]), float(parts[2]),
                              float(parts[3])))
        if not atoms:
            raise ValueError("xyz 里没读到坐标")
        return atoms

    # gjf / com：跳过 % 开头与路由段，找到 "电荷 多重度" 行，其后的连续坐标行
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith(("%", "#", "!")):
            continue
        parts = s.split()
        if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
            start = i + 1
            break
    if start is None:
        raise ValueError("没找到电荷/多重度行")
    atoms = []
    for line in lines[start:]:
        parts = line.split()
        # 坐标段只认"元素符号 + 三个浮点"的行；碰到连通性表/空行/别的段就收工
        if _atom_line(parts):
            atoms.append((parts[0], float(parts[1]), float(parts[2]),
                          float(parts[3])))
            continue
        if atoms:
            break
    if not atoms:
        raise ValueError("没读到坐标")
    return atoms


#: 路由里属于"AICD 必需"的关键词：读旧 gjf 时要摘掉，避免重复写进新路由
_AICD_ROUTE_KEYS = ("nmr=csgt", "iop(10/93")

#: 路由预设（下拉；方法/基组那一栏始终可手改）
ROUTE_PRESETS = (
    ("b3lyp/6-31g(d)", ""),
    ("b3lyp/def2-tzvp", ""),
    ("wb97xd/6-31g(d)", ""),
    ("hf/6-31g*", ""),
)


def parse_gjf_settings(path):
    """读一份已有 .gjf，尽量把"计算设置"也还原出来，供生成器预填。

    就是用户最省事的那条路：载入 gjf → 生成器里已经填好方法和轨道模式 →
    点保存即可（不必自己回忆该写哪些关键字）。

    Returns
    -------
    dict
        ``{"atoms", "charge", "mult", "method", "extra", "mode",
        "orbitals", "title", "chk", "mem", "nproc", "tensor"}``；
        读不出来的字段留空/None，由调用方保留原值。
    """
    with open(path, "r", errors="replace") as fh:
        return parse_gjf_settings_text(fh.read())


def parse_gjf_settings_text(text):
    """同 :func:`parse_gjf_settings`，但输入是文本（编辑器里那段内容用）。"""
    out = {"atoms": [], "charge": None, "mult": None, "method": "",
           "extra": "", "mode": "", "orbitals": "", "title": "",
           "chk": "", "mem": "", "nproc": 0, "tensor": "",
           "connectivity": []}
    lines = str(text or "").splitlines()

    route_lines, body_start = [], 0
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("%"):
            key, _, val = s[1:].partition("=")
            key, val = key.strip().lower(), val.strip()
            if key == "chk":
                out["chk"] = val
            elif key == "mem":
                out["mem"] = val
            elif key in ("nprocshared", "nproc"):
                try:
                    out["nproc"] = int(val)
                except ValueError:
                    pass
            continue
        if s.startswith(("#", "!")):
            route_lines.append(s.lstrip("#!").strip())
            continue
        body_start = i
        break

    route = " ".join(route_lines)
    tokens = [t for t in route.split() if t]
    for tok in tokens:
        low = tok.lower()
        if any(k in low for k in _AICD_ROUTE_KEYS):
            if "10/93=2" in low:
                out["mode"] = "orbs"
            elif "10/93=1" in low:
                out["mode"] = "all"
            continue
        if "/" in tok and not out["method"]:
            out["method"] = tok
            continue
        if low in ("opt", "freq", "scf=tight", "guess=read"):
            out["extra"] = (out["extra"] + " " + tok).strip()
    # 剩下的都算附加关键词（含 opt/freq 之外的自定义项）
    rest = [t for t in tokens[1:] if not any(k in t.lower()
                                             for k in _AICD_ROUTE_KEYS)]
    if rest:
        out["extra"] = " ".join(rest[1:]) if rest and rest[0] == out["method"] \
            else " ".join(t for t in rest if t != out["method"])

    # 标题：路由段之后的第一段非空文本
    for raw in lines[body_start:]:
        if raw.strip():
            out["title"] = raw.strip()
            break

    # 电荷/多重度 + 坐标 + 张量名 + 轨道编号
    idx = None
    for i in range(body_start, len(lines)):
        parts = lines[i].split()
        if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
            idx = i
            break
    if idx is not None:
        out["charge"] = int(lines[idx].split()[0])
        out["mult"] = int(lines[idx].split()[1])
        atoms, conn, tail = [], [], []
        stage = 0            # 0 未开始 / 1 坐标段 / 2 连通性段 / 3 后续段
        for raw in lines[idx + 1:]:
            parts = raw.split()
            if not parts:
                if stage == 1:
                    stage = 2      # 空行：坐标段结束，可能跟着连通性段
                continue
            if stage <= 1 and _atom_line(parts):
                atoms.append((parts[0], float(parts[1]), float(parts[2]),
                              float(parts[3])))
                stage = 1
                continue
            if stage in (1, 2) and _INT_TOKEN.match(parts[0]):
                # geom=connectivity 的连通性表：原样留着，生成新输入时照抄
                conn.append(" ".join(parts))
                stage = 2
                continue
            stage = 3
            tail.append(" ".join(parts))
        out["atoms"] = atoms
        out["connectivity"] = conn
        # 张量文件名：后续段里第一条不是纯数字的行（纯数字是别的段的残留）
        for item in tail:
            if not _INT_TOKEN.match(item.split()[0]):
                out["tensor"] = item
                break
        # 轨道编号：形如 17,20,21 / 1-16,18-19，也兼容 sob 文章里的
        # 空格写法 "26 31-34"（统一整理成逗号分隔，别把空格删成 2631-34）
        for item in tail:
            if re.fullmatch(r"[\d,\-\s]+", item) and any(c.isdigit()
                                                         for c in item):
                tokens = [t for t in re.split(r"[,\s]+", item.strip()) if t]
                out["orbitals"] = ",".join(tokens)
                break
    return out


def rewrite_with_orbitals(text, orbitals, mode="orbs", name_tag=""):
    """把一段 gjf 改写成"只算指定轨道"的输入（``iop(10/93=2)`` + 轨道编号）。

    用于 π-only / σ-only 的第二遍计算：电解出来的 π（或 σ）轨道编号已知后，
    按原输入的方法/几何/连通性表重建一份干净输入，路由里把 ``iop(10/93=1)``
    换成 ``2``，末尾写上轨道列表和一个**空行**。找编号的事交给
    :func:`molstudio.core.multiwfn_pi.detect_pi_orbitals`。

    末尾空行很关键：Gaussian 的 AICD patch 在轨道列表后没有空行时会漏读
    最后一个轨道（实测 ``17,20,21`` 只算 17、20），π 密度缺一块、等值面裂开。

    ``name_tag``（如 ``"pi"`` / ``"sigma"``）会给 **%chk 与张量文件名**加后缀。
    这一步很关键：两次任务如果都写 ``test.txt``、``x.chk``，第二次会覆盖第一次
    的张量/检查点；回头分析第一份 log 时程序会静默读到第二份的数据。
    """
    info = parse_gjf_settings_text(text)
    if not info.get("atoms"):
        raise ValueError("输入里没有可识别的坐标")
    chk = info.get("chk", "")
    tensor = info.get("tensor") or "test.txt"
    if name_tag:
        tensor = _tag_name(tensor, name_tag)
        chk = _tag_name(chk, name_tag) if chk else ""
    return build_aicd_input(
        info["atoms"], method=info.get("method") or "b3lyp/6-31g(d)",
        extra=info.get("extra", ""), charge=info.get("charge") or 0,
        mult=info.get("mult") or 1, chk=chk,
        mem=info.get("mem", ""), nproc=info.get("nproc") or 0,
        tensor_name=tensor,
        orbitals=str(orbitals).strip(), mode=mode,
        title=info.get("title") or "AICD",
        connectivity=info.get("connectivity") or [])


def _tag_name(name, tag):
    """给文件名加后缀（幂等：已经以 ``_tag`` 结尾就不再加）。"""
    if not tag or not name:
        return name
    folder, base = os.path.split(str(name))
    stem, ext = os.path.splitext(base)
    if stem.endswith("_" + tag):
        return name
    out = f"{stem}_{tag}{ext}" if ext else f"{stem}_{tag}"
    return os.path.join(folder, out) if folder else out


def prepare_aicd_input(text, name_tag="aicd"):
    """把任意 gjf 变成 **AICD 可直接跑** 的输入。

    只加必需的东西（不动方法/基组/几何/连通性表）：
      * 路由里补 ``nmr=csgt iop(10/93=1)``；
      * 张量文件名放到几何（与连通性表）之后；
      * ``%chk`` 与张量名加 ``_aicd`` 后缀，避免和原任务/其它任务互相覆盖。

    如果原输入本来就是 ``iop(10/93=2)`` + 轨道列表（π-only / σ-only），
    这里会原样保留轨道模式，不会静默改成全电子。
    """
    info = parse_gjf_settings_text(text)
    if not info.get("atoms"):
        raise ValueError("输入里没有可识别的坐标")
    tensor = _tag_name(info.get("tensor") or "test.txt", name_tag)
    chk = _tag_name(info.get("chk") or "", name_tag) if info.get("chk") else ""
    mode = info.get("mode") or "all"
    orbitals = str(info.get("orbitals") or "").strip()
    if mode == "orbs" and not orbitals:
        mode = "all"                      # 没有轨道号就退回全电子，别生成跑不了的输入
    return build_aicd_input(
        info["atoms"], method=info.get("method") or "b3lyp/6-31g(d)",
        extra=info.get("extra", ""), charge=info.get("charge") or 0,
        mult=info.get("mult") or 1, chk=chk,
        mem=info.get("mem", ""), nproc=info.get("nproc") or 0,
        tensor_name=tensor, mode=mode, orbitals=orbitals,
        title=info.get("title") or "AICD",
        connectivity=info.get("connectivity") or [])


_TR = {
    "zh": {
        "title": "生成 AICD 的 Gaussian 输入",
        "hint": "跑完这个任务，会得到 .log 和同名目录下的张量 txt——之后回到"
                "「感应电流」面板选那个 .log 就能出图。\n"
                "坐标怎么摆都行：Gaussian 会自己转到标准取向，与画布里的朝向无关；"
                "分析时的「磁场方向」由面板按分子平面自动预选。",
        "grp_struct": "结构",
        "src_canvas": "当前画布上的分子",
        "src_file": "从文件读取",
        "pick": "选择文件…",
        "load_gjf": "从已有 .gjf 载入…",
        "load_gjf_tip": "把已有 gjf 的结构与设置（电荷/多重度、方法、轨道模式、"
                        "%chk/%mem/%nproc）一起读进来预填，你只要确认后保存即可。",
        "loaded_gjf": "已从 {name} 读入结构与设置",
        "preset": "预设",
        "preset_label": "（方法预设）",
        "no_canvas": "画布上还没有分子——先打开一个 fchk / xyz / gjf 文件，"
                      "或改用「从文件读取」。",
        "grp_route": "计算设置",
        "method": "方法/基组",
        "extra": "附加关键词",
        "charge": "电荷",
        "mult": "多重度",
        "grp_orb": "轨道范围（决定分析什么）",
        "mode_all": "全部轨道（iop(10/93=1)）",
        "mode_orbs": "指定轨道（iop(10/93=2)）",
        "orbs": "轨道编号",
        "find_orbs": "用 Multiwfn 自动查找…",
        "find_orbs_tip": "不知道编号？Multiwfn 的「主功能 100 → 22」能检测出所有 π "
                         "轨道，并直接给出占据 π 轨道的编号串。\n"
                         "这一步需要当前体系已在主界面打开（用到它的 fchk）与已配置的 "
                         "Multiwfn 路径。\n"
                         "σ 轨道 = 占据轨道里除 π 之外的，自动帮你补上。",
        "find_running": "正在用 Multiwfn 检测 π 轨道…",
        "find_ok": "检测完成：占据 π 轨道 {pi}；σ 轨道 {sig}",
        "find_fail": "检测失败：{err}",
        "fill_pi": "填入 π（占据）：{pi}",
        "fill_sigma": "填入 σ（占据）：{sig}",
        "need_fchk": "请先在主界面打开这个体系的 fchk（Multiwfn 检测要用它）",
        "need_mw": "Multiwfn 路径未配置（主界面 ⚙️ 路径设置里填）",
        "nonplanar_note": "注意：体系不是严格共平面时，π/σ 划分是近似的"
                          "（可按 π 成份阈值取舍）。",
        "detect_mode": "检测方式",
        "mode_auto": "自动（共平面用平面法，扭曲体系用 LMO 投影）",
        "mode_planar": "平面法（体系必须共平面）",
        "mode_projection": "LMO 投影 + 阈值（配合物 / 扭曲体系）",
        "detect_mode_tip": "平面法：Multiwfn 主功能 100→22 直接按平面判定 π 轨道，"
                           "快，但要求体系严格共平面。\n"
                           "LMO 投影：先把占据轨道定域化，判定 π 型 LMO，再把 MO 向"
                           "它们投影，得到每个轨道的 π 成份——配合物、扭曲体系、"
                           "σ/π 混合明显时用这个（sob 推荐的客观判据）。",
        "pi_threshold": "π 成份阈值 (%)",
        "pi_threshold_tip": "π 成份高于该值的分子轨道才被当作 π 轨道"
                            "（sob 建议 80%）。仅在 LMO 投影方式下生效。",
        "mode_used_planar": "（平面法，体系平面 {plane}）",
        "mode_used_projection": "（LMO 投影，π 成份阈值 {thr}%）",
        "run_after": "保存后直接用本机 Gaussian 计算（.log 与张量 txt 写在同一目录）",
        "orbs_tip": "用逗号/连字符写，如 17,20,21 或 1-16,18-19。\n"
                    "苯的 π 轨道是 17 与 20,21（E1G 简并对），σ 是 1-16,18-19。\n"
                    "轨道编号按 GaussView 的编号；开壳层 α/β 的写法见 sob 博文。",
        "grp_io": "文件与资源",
        "chk": "chk 文件名",
        "tensor": "张量文件名",
        "tensor_tip": "Gaussian 会把电流密度张量写进这个名字的文件（在 .log "
                      "同一个目录）。保持默认 test.txt 即可。",
        "mem": "内存",
        "nproc": "核数",
        "title_line": "任务标题",
        "save": "保存为 .gjf…",
        "copy": "复制到剪贴板",
        "close": "关闭",
        "copied": "已复制到剪贴板",
        "saved": "已保存：{path}",
        "no_atoms": "还没有结构，无法生成",
        "preview": "输入预览",
    },
    "en": {
        "title": "Generate Gaussian input for AICD",
        "hint": "Run this job to get the .log plus the tensor dump next to it — "
                "then pick that .log back in the AICD panel.\n"
                "The orientation of the coordinates does not matter: Gaussian "
                "re-orients to its standard orientation, and the AICD panel picks "
                "the field direction from the molecular plane.",
        "grp_struct": "Structure",
        "src_canvas": "Molecule on the canvas",
        "src_file": "Read from file",
        "pick": "Choose file…",
        "load_gjf": "Load from an existing .gjf…",
        "load_gjf_tip": "Read the structure and the job settings (charge/multiplicity, "
                        "method, orbital mode, %chk/%mem/%nproc) from an existing gjf "
                        "and prefill them — you only confirm and save.",
        "loaded_gjf": "Loaded structure and settings from {name}",
        "preset": "Preset",
        "preset_label": "(method preset)",
        "no_canvas": "No molecule on the canvas — open an fchk / xyz / gjf first, "
                     "or use \"Read from file\".",
        "grp_route": "Job settings",
        "method": "Method/basis",
        "extra": "Extra keywords",
        "charge": "Charge",
        "mult": "Multiplicity",
        "grp_orb": "Orbitals (what gets analysed)",
        "mode_all": "All orbitals (iop(10/93=1))",
        "mode_orbs": "Selected orbitals (iop(10/93=2))",
        "orbs": "Orbital numbers",
        "find_orbs": "Find automatically with Multiwfn…",
        "find_orbs_tip": "Don't know the numbers? Multiwfn's \"main function 100 → "
                         "22\" detects every π orbital and prints the indices of the "
                         "occupied π ones.\nNeeds the system opened in the main window "
                         "(its fchk) and a configured Multiwfn path.\n"
                         "σ = occupied orbitals minus π, filled in for you.",
        "find_running": "Running Multiwfn π-orbital detection…",
        "find_ok": "Done: occupied π = {pi}; σ = {sig}",
        "find_fail": "Detection failed: {err}",
        "fill_pi": "Fill π (occupied): {pi}",
        "fill_sigma": "Fill σ (occupied): {sig}",
        "need_fchk": "Open this system's fchk in the main window first (Multiwfn "
                     "needs it)",
        "need_mw": "Multiwfn path is not configured (⚙️ Path settings)",
        "nonplanar_note": "Note: unless the system is exactly planar the π/σ split "
                          "is approximate (use a π-character threshold).",
        "detect_mode": "Detection mode",
        "mode_auto": "Auto (plane method for planar, LMO projection for distorted)",
        "mode_planar": "Plane method (system must be planar)",
        "mode_projection": "LMO projection + threshold (complexes / distorted)",
        "detect_mode_tip": "Plane method: Multiwfn 100→22 classifies π orbitals by "
                           "the molecular plane — fast, but the system must be "
                           "exactly planar.\n"
                           "LMO projection: localize the occupied orbitals, tag the "
                           "π-type LMOs, then project the MOs onto them to get each "
                           "orbital's π character — the objective route for "
                           "complexes, distorted systems and strong σ/π mixing.",
        "pi_threshold": "π character threshold (%)",
        "pi_threshold_tip": "Only orbitals with π character above this are treated "
                            "as π orbitals (Sobereva suggests 80%). Used by the LMO "
                            "projection mode only.",
        "mode_used_planar": " (plane method, system plane {plane})",
        "mode_used_projection": " (LMO projection, π threshold {thr}%)",
        "run_after": "Run locally with Gaussian after saving (.log and tensor dump "
                     "land in the same folder)",
        "orbs_tip": "Comma/range list, e.g. 17,20,21 or 1-16,18-19.\n"
                    "For benzene the π orbitals are 17 and the pair 20,21; "
                    "σ are 1-16,18-19.\n"
                    "Numbering follows GaussView; see the AICD notes for open "
                    "shells (α/β).",
        "grp_io": "Files and resources",
        "chk": "chk name",
        "tensor": "Tensor file name",
        "tensor_tip": "Gaussian writes the current-density tensor into this file "
                      "(same folder as the .log). Keep test.txt.",
        "mem": "Memory",
        "nproc": "Cores",
        "title_line": "Job title",
        "save": "Save as .gjf…",
        "copy": "Copy to clipboard",
        "close": "Close",
        "copied": "Copied to clipboard",
        "saved": "Saved: {path}",
        "no_atoms": "No structure yet — nothing to generate",
        "preview": "Input preview",
    },
}


class _PiDetectWorker(QThread):
    """后台跑 Multiwfn 的 π 轨道检测（主线程不阻塞）。"""

    log = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, fchk, multiwfn, mode="auto", threshold=80, planar=True,
                 parent=None):
        super().__init__(parent)
        self._fchk = fchk
        self._mw = multiwfn
        self._mode = mode
        self._threshold = int(threshold)
        self._planar = bool(planar)

    def run(self):
        try:
            mode = self._mode
            if mode == "auto":
                # 共平面体系用平面法（快、且能顺带报出平面）；扭曲体系必须用
                # 定域化 + LMO 投影，否则 σ/π 混在一起、编号没有意义。
                mode = "planar" if self._planar else "projection"
            if mode == "projection":
                info = MPI.detect_pi_by_projection(
                    self._fchk, self._mw, threshold=self._threshold,
                    on_log=self.log.emit)
            else:
                info = MPI.detect_pi_orbitals(self._fchk, self._mw,
                                              on_log=self.log.emit)
            info["mode_used"] = mode
            self.done.emit({"ok": True, "info": info})
        except Exception as exc:                              # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc)})


class AicdInputDialog(QDialog):
    """AICD 的 Gaussian 输入生成器（模态对话框，带实时预览）。"""

    def __init__(self, glw=None, lang="zh", out_dir="", base_name="",
                 get_fchk=None, get_multiwfn=None, on_log=None,
                 gjf_path=None, parent=None):
        super().__init__(parent)
        self.lang = "zh" if lang == "zh" else "en"
        self.glw = glw
        self._get_fchk = get_fchk or (lambda: "")
        self._get_mw = get_multiwfn or (lambda: "")
        self._on_log = on_log or (lambda m: None)
        self._pi_worker = None
        self._pi_str = ""
        self._sigma_str = ""
        self._connectivity = []      # geom=connectivity 的连通性表（原样保留）
        self._atoms = []
        self._out_dir = out_dir or ""
        self._base = base_name or "aicd"
        self.setWindowTitle(self._t("title"))
        self.setMinimumWidth(680)
        # 别长过屏幕：宽 780、高取屏幕可用高度的 ~4/5
        try:
            from PyQt5.QtWidgets import QApplication as _QA
            scr = _QA.primaryScreen()
            if scr is not None:
                avail = scr.availableGeometry()
                self.resize(min(820, max(560, avail.width() - 120)),
                            min(720, max(420, int(avail.height() * 0.8))))
        except Exception:                                      # noqa: BLE001
            self.resize(780, 620)
        self._build_ui()
        self._apply_lang()
        # 给了 gjf 就以它为准（载入 → 预填 → 保存是主流程），否则用画布上的分子
        if not (gjf_path and self._load_gjf(gjf_path)):
            self._load_from_canvas()
        self._refresh_preview()

    # ── i18n ──────────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        s = _TR.get(self.lang, _TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def _apply_lang(self):
        self.lbl_hint.setText(self._t("hint"))
        self.grp_struct.setTitle(self._t("grp_struct"))
        self.rdo_canvas.setText(self._t("src_canvas"))
        self.rdo_file.setText(self._t("src_file"))
        self.btn_pick.setText(self._t("pick"))
        self.grp_route.setTitle(self._t("grp_route"))
        self.lbl_method.setText(self._t("method"))
        self.btn_load_gjf.setText(self._t("load_gjf"))
        self.btn_load_gjf.setToolTip(self._t("load_gjf_tip"))
        self.cmb_preset.setItemText(0, self._t("preset_label"))
        self.cmb_preset.setToolTip(self._t("preset"))
        self.lbl_extra.setText(self._t("extra"))
        self.lbl_charge.setText(self._t("charge"))
        self.lbl_mult.setText(self._t("mult"))
        self.grp_orb.setTitle(self._t("grp_orb"))
        self.rdo_all.setText(self._t("mode_all"))
        self.rdo_orbs.setText(self._t("mode_orbs"))
        self.lbl_orbs.setText(self._t("orbs"))
        self.lbl_orbs.setToolTip(self._t("orbs_tip"))
        self.edit_orbs.setToolTip(self._t("orbs_tip"))
        self.btn_find_orbs.setText(self._t("find_orbs"))
        self.btn_find_orbs.setToolTip(self._t("find_orbs_tip"))
        self.lbl_detect.setText(self._t("detect_mode"))
        for i, key in enumerate(("mode_auto", "mode_planar", "mode_projection")):
            self.cmb_detect.setItemText(i, self._t(key))
        self.cmb_detect.setToolTip(self._t("detect_mode_tip"))
        self.lbl_threshold.setText(self._t("pi_threshold"))
        self.lbl_threshold.setToolTip(self._t("pi_threshold_tip"))
        self.spin_threshold.setToolTip(self._t("pi_threshold_tip"))
        if self.btn_fill_pi.isVisible():
            self.btn_fill_pi.setText(self._t("fill_pi", pi=self._pi_str))
            self.btn_fill_sigma.setText(
                self._t("fill_sigma", sig=self._sigma_str or "-"))
        self.grp_io.setTitle(self._t("grp_io"))
        self.lbl_chk.setText(self._t("chk"))
        self.lbl_tensor.setText(self._t("tensor"))
        self.lbl_tensor.setToolTip(self._t("tensor_tip"))
        self.edit_tensor.setToolTip(self._t("tensor_tip"))
        self.lbl_mem.setText(self._t("mem"))
        self.lbl_nproc.setText(self._t("nproc"))
        self.lbl_title.setText(self._t("title_line"))
        self.btn_save.setText(self._t("save"))
        self.btn_copy.setText(self._t("copy"))
        self.chk_run_after.setText(self._t("run_after"))
        self.btn_close.setText(self._t("close"))
        self.grp_preview.setTitle(self._t("preview"))
        self.lbl_struct_info.setText(self._t("no_canvas")
                                     if not self._atoms else "")

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 布局：内容放进可滚动区（小屏幕上对话框不会长过屏幕），
        # 底部按钮固定在滚动区外面，永远够得着。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        root = QVBoxLayout(inner)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#475569;")
        root.addWidget(self.lbl_hint)

        # 结构
        self.grp_struct = QGroupBox()
        gs = QGridLayout(self.grp_struct)
        self.rdo_canvas = QPushButton()
        self.rdo_canvas.setCheckable(True)
        self.rdo_canvas.setChecked(True)
        self.rdo_canvas.clicked.connect(self._load_from_canvas)
        self.rdo_file = QPushButton()
        self.rdo_file.setCheckable(True)
        self.rdo_file.clicked.connect(self._pick_structure)
        self.btn_pick = QPushButton()
        self.btn_pick.clicked.connect(self._pick_structure)
        self.btn_load_gjf = QPushButton()
        self.btn_load_gjf.clicked.connect(self._pick_gjf_to_load)
        self.edit_struct = QLineEdit()
        self.edit_struct.setReadOnly(True)
        self.lbl_struct_info = QLabel()
        self.lbl_struct_info.setWordWrap(True)
        self.lbl_struct_info.setStyleSheet("color:#B91C1C;")
        gs.addWidget(self.rdo_canvas, 0, 0, 1, 2)
        gs.addWidget(self.rdo_file, 1, 0)
        gs.addWidget(self.edit_struct, 1, 1)
        gs.addWidget(self.btn_pick, 1, 2)
        gs.addWidget(self.btn_load_gjf, 2, 0, 1, 3)
        gs.addWidget(self.lbl_struct_info, 3, 0, 1, 3)
        gs.setColumnStretch(1, 1)
        root.addWidget(self.grp_struct)

        # 计算设置
        self.grp_route = QGroupBox()
        gr = QGridLayout(self.grp_route)
        self.lbl_method = QLabel()
        self.edit_method = QLineEdit("b3lyp/6-31g(d)")
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems([""] + [p[0] for p in ROUTE_PRESETS])
        self.cmb_preset.currentIndexChanged.connect(self._apply_preset)
        self.lbl_extra = QLabel()
        self.edit_extra = QLineEdit()
        self.edit_extra.setPlaceholderText("int(grid=ultrafine)")
        self.lbl_charge = QLabel()
        self.spin_charge = QSpinBox()
        self.spin_charge.setRange(-10, 10)
        self.lbl_mult = QLabel()
        self.spin_mult = QSpinBox()
        self.spin_mult.setRange(1, 10)
        gr.addWidget(self.lbl_method, 0, 0)
        gr.addWidget(self.edit_method, 0, 1, 1, 2)
        gr.addWidget(self.cmb_preset, 0, 3)
        gr.addWidget(self.lbl_extra, 1, 0)
        gr.addWidget(self.edit_extra, 1, 1, 1, 3)
        gr.addWidget(self.lbl_charge, 2, 0)
        gr.addWidget(self.spin_charge, 2, 1)
        gr.addWidget(self.lbl_mult, 2, 2)
        gr.addWidget(self.spin_mult, 2, 3)
        gr.setColumnStretch(1, 1)
        gr.setColumnStretch(3, 1)
        root.addWidget(self.grp_route)

        # 轨道范围
        self.grp_orb = QGroupBox()
        go = QGridLayout(self.grp_orb)
        self.rdo_all = QPushButton()
        self.rdo_all.setCheckable(True)
        self.rdo_all.setChecked(True)
        self.rdo_orbs = QPushButton()
        self.rdo_orbs.setCheckable(True)
        self.rdo_all.clicked.connect(lambda: self._set_mode("all"))
        self.rdo_orbs.clicked.connect(lambda: self._set_mode("orbs"))
        self.lbl_orbs = QLabel()
        self.edit_orbs = QLineEdit()
        self.edit_orbs.setPlaceholderText("17,20,21")
        self.edit_orbs.setEnabled(False)
        self.btn_find_orbs = QPushButton()
        self.btn_find_orbs.clicked.connect(self._find_orbitals)
        self.btn_fill_pi = QPushButton()
        self.btn_fill_pi.setVisible(False)
        self.btn_fill_pi.clicked.connect(
            lambda: self._fill_orbs(getattr(self, "_pi_str", "")))
        self.btn_fill_sigma = QPushButton()
        self.btn_fill_sigma.setVisible(False)
        self.btn_fill_sigma.clicked.connect(
            lambda: self._fill_orbs(getattr(self, "_sigma_str", "")))
        self.lbl_orb_result = QLabel()
        self.lbl_orb_result.setWordWrap(True)
        self.lbl_orb_result.setStyleSheet("color:#475569;")
        self.lbl_detect = QLabel()
        self.cmb_detect = QComboBox()
        self.cmb_detect.addItems(["", "", ""])
        self.cmb_detect.setCurrentIndex(0)
        self.lbl_threshold = QLabel()
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(50, 99)
        self.spin_threshold.setValue(80)
        self.spin_threshold.setSuffix(" %")
        go.addWidget(self.rdo_all, 0, 0, 1, 2)
        go.addWidget(self.rdo_orbs, 1, 0, 1, 2)
        go.addWidget(self.lbl_orbs, 2, 0)
        go.addWidget(self.edit_orbs, 2, 1)
        go.addWidget(self.btn_find_orbs, 2, 2)
        go.addWidget(self.lbl_detect, 3, 0)
        go.addWidget(self.cmb_detect, 3, 1, 1, 3)
        go.addWidget(self.lbl_threshold, 4, 0)
        go.addWidget(self.spin_threshold, 4, 1)
        go.addWidget(self.btn_fill_pi, 5, 0, 1, 2)
        go.addWidget(self.btn_fill_sigma, 5, 2, 1, 2)
        go.addWidget(self.lbl_orb_result, 6, 0, 1, 4)
        go.setColumnStretch(1, 1)
        root.addWidget(self.grp_orb)

        # 文件与资源
        self.grp_io = QGroupBox()
        gi = QGridLayout(self.grp_io)
        self.lbl_chk = QLabel()
        self.edit_chk = QLineEdit()
        self.lbl_tensor = QLabel()
        self.edit_tensor = QLineEdit("test.txt")
        self.lbl_mem = QLabel()
        self.edit_mem = QLineEdit("4GB")
        self.lbl_nproc = QLabel()
        self.spin_nproc = QSpinBox()
        self.spin_nproc.setRange(0, 128)
        self.spin_nproc.setValue(4)
        self.lbl_title = QLabel()
        self.edit_title = QLineEdit()
        gi.addWidget(self.lbl_chk, 0, 0)
        gi.addWidget(self.edit_chk, 0, 1)
        gi.addWidget(self.lbl_tensor, 0, 2)
        gi.addWidget(self.edit_tensor, 0, 3)
        gi.addWidget(self.lbl_mem, 1, 0)
        gi.addWidget(self.edit_mem, 1, 1)
        gi.addWidget(self.lbl_nproc, 1, 2)
        gi.addWidget(self.spin_nproc, 1, 3)
        gi.addWidget(self.lbl_title, 2, 0)
        gi.addWidget(self.edit_title, 2, 1, 1, 3)
        gi.setColumnStretch(1, 1)
        gi.setColumnStretch(3, 1)
        root.addWidget(self.grp_io)

        # 预览 + 按钮
        self.grp_preview = QGroupBox()
        gv = QVBoxLayout(self.grp_preview)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        # 输入文件可以很长，但编辑框不该跟着长——限高 + 自带滚动条
        self.preview.setMinimumHeight(130)
        self.preview.setMaximumHeight(210)
        f = self.preview.font()
        f.setFamily("Consolas")
        self.preview.setFont(f)
        gv.addWidget(self.preview)
        root.addWidget(self.grp_preview)

        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 8)
        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self._save)
        self.btn_copy = QPushButton()
        self.btn_copy.clicked.connect(self._copy)
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.reject)
        self.chk_run_after = QCheckBox()
        self.chk_run_after.setChecked(False)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_copy)
        row.addWidget(self.chk_run_after)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        outer.addLayout(row)

        for w in (self.edit_method, self.edit_extra, self.edit_orbs,
                  self.edit_chk, self.edit_tensor, self.edit_mem,
                  self.edit_title):
            w.textChanged.connect(self._refresh_preview)
        for w in (self.spin_charge, self.spin_mult, self.spin_nproc):
            w.valueChanged.connect(self._refresh_preview)

    # ── 结构来源 ──────────────────────────────────────────────────────────
    def _load_from_canvas(self):
        self._mode_src = "canvas"
        self.rdo_canvas.setChecked(True)
        self.rdo_file.setChecked(False)
        self._connectivity = []          # 画布上的原子没有连通性表
        atoms = []
        glw = self.glw
        if glw is not None:
            try:
                for anum, (x, y, z) in glw._atom_list():      # 坐标 Bohr
                    atoms.append((anum, x * A.BOHR, y * A.BOHR, z * A.BOHR))
            except Exception:                                  # noqa: BLE001
                atoms = []
        self._atoms = atoms
        self.edit_struct.setText("")
        self.lbl_struct_info.setText("" if atoms else self._t("no_canvas"))
        self.lbl_struct_info.setStyleSheet("color:#475569;" if atoms
                                           else "color:#B91C1C;")
        self._refresh_preview()

    def _pick_structure(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("pick"), self._out_dir or "",
            "Structure (*.xyz *.gjf *.com *.log *.out);;All files (*)")
        if not path:
            return
        # gjf/com 走"载入设置"那条路（连电荷/方法/连通性表一起预填）；
        # 其它格式只有结构，连通性表相应清掉
        if os.path.splitext(path)[1].lower() in (".gjf", ".com"):
            self._load_gjf(path)
            return
        try:
            self._atoms = parse_structure_file(path)
        except Exception as exc:                               # noqa: BLE001
            QMessageBox.warning(self, self._t("title"), str(exc))
            return
        self._connectivity = []
        self._mode_src = "file"
        self.rdo_file.setChecked(True)
        self.rdo_canvas.setChecked(False)
        self.edit_struct.setText(path)
        self.lbl_struct_info.setText("%d atoms" % len(self._atoms))
        self.lbl_struct_info.setStyleSheet("color:#166534;")
        self._refresh_preview()

    def _pick_gjf_to_load(self):
        start = self._out_dir or os.path.dirname(self.edit_struct.text() or "") or ""
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("load_gjf"), start,
            "Gaussian input (*.gjf *.com);;All files (*)")
        if path:
            self._load_gjf(path)

    def _load_gjf(self, path):
        """读已有 gjf 的结构与设置并预填（载入 → 确认 → 保存 这条主流程）。"""
        try:
            info = parse_gjf_settings(path)
        except Exception as exc:                               # noqa: BLE001
            QMessageBox.warning(self, self._t("title"), str(exc))
            return False
        atoms = info.get("atoms") or []
        if not atoms:
            try:
                atoms = parse_structure_file(path)
            except Exception:                                  # noqa: BLE001
                atoms = []
        if not atoms:
            QMessageBox.warning(self, self._t("title"), self._t("no_atoms"))
            return False

        self._atoms = atoms
        self._connectivity = list(info.get("connectivity") or [])
        self._mode_src = "file"
        self.rdo_file.setChecked(True)
        self.rdo_canvas.setChecked(False)
        self.edit_struct.setText(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem:
            self._base = stem
        if info.get("charge") is not None:
            self.spin_charge.setValue(int(info["charge"]))
        if info.get("mult") is not None:
            self.spin_mult.setValue(max(1, int(info["mult"])))
        if info.get("method"):
            self.edit_method.setText(info["method"])
        if info.get("extra"):
            self.edit_extra.setText(info["extra"])
        if info.get("chk"):
            self.edit_chk.setText(info["chk"])
        if info.get("mem"):
            self.edit_mem.setText(info["mem"])
        if info.get("nproc"):
            self.spin_nproc.setValue(int(info["nproc"]))
        if info.get("tensor"):
            self.edit_tensor.setText(info["tensor"])
        elif self.edit_tensor.text().strip() in ("", "test.txt"):
            # 同目录可能先后跑 all-electron / π-only 两次任务；默认给张量名带
            # 任务名后缀，避免第二次把第一次的 test.txt 覆盖掉（会静默串数据）
            self.edit_tensor.setText(stem + "_aicd.txt")
        if info.get("title"):
            self.edit_title.setText(info["title"])
        if info.get("mode") == "orbs":
            self._set_mode("orbs")
            if info.get("orbitals"):
                self.edit_orbs.setText(info["orbitals"])
        elif info.get("mode") == "all":
            self._set_mode("all")
        self.lbl_struct_info.setStyleSheet("color:#166534;")
        self.lbl_struct_info.setText(self._t(
            "loaded_gjf", name=os.path.basename(path))
            + "  ·  %d atoms" % len(atoms))
        self._refresh_preview()
        return True

    def _apply_preset(self, index):
        if index > 0:
            self.edit_method.setText(self.cmb_preset.currentText())

    def _set_mode(self, mode):
        self.rdo_all.setChecked(mode == "all")
        self.rdo_orbs.setChecked(mode == "orbs")
        self.edit_orbs.setEnabled(mode == "orbs")
        self._refresh_preview()

    # ── 用 Multiwfn 找 π / σ 轨道编号 ─────────────────────────────────────
    def _find_orbitals(self):
        """跑 Multiwfn（主功能 100 → 22）检测 π 轨道，并把结果做成两个"填入"按钮。

        sob 的《使用AICD 2.0绘制磁感应电流图》就是这么找编号的：让人肉眼数轨道
        不现实，而 Multiwfn 会直接打印"occupancy × π 轨道编号"，连 gjf 末尾
        要抄的那串都给了。
        """
        fchk = str(self._get_fchk() or "")
        mw = str(self._get_mw() or "")
        if not fchk or not os.path.isfile(fchk):
            QMessageBox.information(self, self._t("title"), self._t("need_fchk"))
            return
        if not mw or not os.path.isfile(mw):
            QMessageBox.information(self, self._t("title"), self._t("need_mw"))
            return
        if self._pi_worker is not None:
            return
        self.btn_find_orbs.setEnabled(False)
        self.lbl_orb_result.setText(self._t("find_running"))
        mode = ("auto", "planar", "projection")[self.cmb_detect.currentIndex()]
        # 自动模式要判断体系是否共平面：结构来自画布时直接用（平面性判据与朝向无关）
        planar = True
        if len(self._atoms) >= 3:
            try:
                planar = bool(A.guess_plane_normal(self._atoms)["planar"])
            except Exception:                                  # noqa: BLE001
                planar = True
        self._pi_worker = _PiDetectWorker(
            fchk, mw, mode=mode, threshold=self.spin_threshold.value(),
            planar=planar, parent=self)
        self._pi_worker.log.connect(self._on_log)
        self._pi_worker.done.connect(self._on_pi_done)
        self._pi_worker.finished.connect(
            lambda: self.btn_find_orbs.setEnabled(True))
        self._pi_worker.start()

    def _on_pi_done(self, info):
        self._pi_worker = None
        if not info.get("ok"):
            self.lbl_orb_result.setStyleSheet("color:#B91C1C;")
            self.lbl_orb_result.setText(
                self._t("find_fail", err=info.get("error", "")))
            return
        res = info["info"]
        self._pi_str = res.get("pi_occupied_str", "")
        self._sigma_str = res.get("sigma_occupied_str", "")
        self.lbl_orb_result.setStyleSheet("color:#166534;")
        if res.get("mode") == "projection":
            # 投影模式没有"体系平面"这回事——正因为体系不共平面才走这条路
            tail = self._t("mode_used_projection",
                           thr=int(res.get("threshold", 0)))
            note = "\n" + self._t("nonplanar_note")
        else:
            tail = self._t("mode_used_planar",
                           plane=res.get("plane_hint", "") or "?")
            note = ""
        self.lbl_orb_result.setText(
            self._t("find_ok", pi=self._pi_str or "-",
                    sig=self._sigma_str or "-") + tail + note)
        for btn, key, val in ((self.btn_fill_pi, "fill_pi", self._pi_str),
                              (self.btn_fill_sigma, "fill_sigma",
                               self._sigma_str)):
            btn.setVisible(bool(val))
            btn.setText(self._t(key, pi=val, sig=val))
            btn.setEnabled(bool(val))
        # 查到编号通常就是想做轨道分解，顺手切到"指定轨道"模式
        if self._pi_str:
            self._set_mode("orbs")

    def _fill_orbs(self, text):
        if not text:
            return
        self._set_mode("orbs")
        self.edit_orbs.setText(text)
        self._refresh_preview()

    # ── 预览 / 保存 ───────────────────────────────────────────────────────
    def _text(self):
        if not self._atoms:
            return ""
        base = self._base or "aicd"
        chk = self.edit_chk.text().strip() or (base + ".chk")
        return build_aicd_input(
            self._atoms,
            method=self.edit_method.text().strip() or "b3lyp/6-31g(d)",
            extra=self.edit_extra.text().strip(),
            charge=self.spin_charge.value(),
            mult=self.spin_mult.value(),
            chk=chk,
            mem=self.edit_mem.text().strip(),
            nproc=self.spin_nproc.value(),
            tensor_name=self.edit_tensor.text().strip() or "test.txt",
            orbitals=self.edit_orbs.text().strip(),
            mode="orbs" if self.rdo_orbs.isChecked() else "all",
            title=self.edit_title.text().strip() or ("AICD " + base),
            connectivity=self._connectivity)

    def _refresh_preview(self):
        self.preview.setPlainText(self._text())

    def _copy(self):
        text = self._text()
        if not text:
            QMessageBox.information(self, self._t("title"), self._t("no_atoms"))
            return
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.lbl_struct_info.setText(self._t("copied"))
        self.lbl_struct_info.setStyleSheet("color:#166534;")

    def _save(self):
        text = self._text()
        if not text:
            QMessageBox.information(self, self._t("title"), self._t("no_atoms"))
            return
        default = os.path.join(self._out_dir or "",
                               (self._base or "aicd") + ".gjf")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save"), default, "Gaussian input (*.gjf)")
        if not path:
            return
        if not path.lower().endswith((".gjf", ".com")):
            path += ".gjf"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError as exc:
            QMessageBox.warning(self, self._t("title"), str(exc))
            return
        self._saved_path = path
        self.run_after = bool(self.chk_run_after.isChecked())
        self.accept()
