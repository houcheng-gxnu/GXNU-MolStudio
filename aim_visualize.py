#!/usr/bin/env python3
"""
AIM VMD 可视化模块（供 aim_panel 调用，不提供独立 GUI）。

加载 CPs.pdb + paths.pdb + mol.pdb → VMD 预览 + Tachyon 渲染：
  - 临界点按类型（C/N/O/F）着色
  - 梯度路径点云 + 分子球棍模型
  - 一键 Tachyon 高质量渲染
  - 多种渲染样式（移植自 igmh.py）

VMD / Tachyon 可执行文件路径由调用方（aim_panel → ⚙️ 路径设置）显式传入。
"""

import os
import sys
import subprocess
import shutil
import time
import tempfile
import socket
import atexit
import uuid


# ── 默认路径 ──────────────────────────────────────────────
_DEFAULT_VMD_DIR = r"C:\Program Files (x86)\University of Illinois\VMD"

def _resolve_vmd_path(env_var, default_name):
    """解析外部程序路径，优先级：环境变量 > 默认安装路径。"""
    if env_var in os.environ and os.path.isfile(os.environ[env_var]):
        return os.environ[env_var]
    return os.path.join(_DEFAULT_VMD_DIR, default_name)

DEFAULT_VMD = _resolve_vmd_path("VMD_PATH", "vmd.exe")
DEFAULT_TACHYON = _resolve_vmd_path("TACHYON_PATH", "tachyon_WIN32.exe")


# ── 样式定义（移植自 igmh.py）───────────────────────────────
STYLES = {
    "sob-art": {
        "desc": "绿蓝, 高光, 经典 (sobereva推荐)",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.1, 0.6, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.65, 0.5, 0.53, 0.15, 1.0, 2.0, 0.3],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "ao-shiny": {
        "desc": "橙青, 珠宝感, AO(慢)",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "on", "ao": "on",
        "cp_mat": [0.20, 0.8, 0.7, 0.3, 0.0, 0.7, 0.0, 0.0],
        "atom_cpk": "0.700000 0.3500000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.0, 0.53, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "ao-chalky": {
        "desc": "蓝绿, 粉笔感, AO(慢)",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "on",
        "cp_mat": [0.1, 0.85, 0.2, 0.55, 0.0, 0.8, 0.5, 0.7],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.0, 0.53, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "white-green": {
        "desc": "白绿, 塑料, 半透明",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.2, 0.5, 0.6, 0.85, 0.0, 0.7, 0.6, 0.6],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "white-red": {
        "desc": "白红, 柔和粉笔, 半透明",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.2, 0.45, 0.05, 0.2, 0.0, 0.7, 0.0, 0.0],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "morandi-blue": {
        "desc": "莫兰迪蓝白, 磨砂玻璃",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.3],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "morandi-green": {
        "desc": "莫兰迪绿白, 磨砂玻璃, 不透明",
        "tachyon_options": "-trans_raster3d -shadow_filter_off",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.6, 0.3, 0.1, 0.2, 0.0, 1.0, 0.4, 0.6],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "morandi-orange": {
        "desc": "莫兰迪橙蓝, 磨砂玻璃",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.5],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "morandi-red": {
        "desc": "莫兰迪红白, 磨砂玻璃",
        "tachyon_options": "-trans_raster3d",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.5],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "vmwfn0": {
        "desc": "白冰蓝, 光滑, 半透明",
        "tachyon_options": "-fullshade",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.6, 0.3, 1.0, 0.95, 0.0, 0.7, 0.3, 0.3],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "vmwfn1": {
        "desc": "红白, 光滑漆面, 不透明",
        "tachyon_options": "-trans_raster3d -shadow_filter_off",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "cp_mat": [0.4, 0.6, 1.0, 0.9, 0.0, 1.0, 0.4, 0.6],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
}


# ── AIM VMD TCL 脚本生成 ────────────────────────────────────
def _aim_tcl(cps_pdb, paths_pdb, mol_pdb, cp_size=0.07, path_size=0.02,
             show_3n3=True, show_3n1=True, show_3p1=True, show_3p3=True,
             show_molecule=True, style_name="sob-art"):
    """生成 AIM 可视化的 VMD TCL 脚本"""
    
    s = STYLES.get(style_name, STYLES["sob-art"])
    
    # 灯光设置
    light_lines = ""
    for k, v in s["lights"].items():
        light_lines += f"light {k} {v}\n"
    
    # 阴影和 AO 设置
    shadow_lines = f"display shadows {'on' if s['shadows'] == 'on' else 'off'}\n"
    shadow_lines += f"display ambientocclusion {'on' if s['ao'] == 'on' else 'off'}\n"
    shadow_lines += "display aoambient 0.8\ndisplay aodirect 0.3\n"
    
    # 材质属性名称
    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror", "opacity", "outline", "outlinewidth"]
    
    # 临界点材质
    cp_mat_lines = "if {[lsearch [material list] _aim_cp] < 0} {material add _aim_cp}\n"
    for name, val in zip(mat_names, s["cp_mat"]):
        cp_mat_lines += f"material change {name} _aim_cp {val}\n"
    
    # 原子材质
    atom_mat_lines = "if {[lsearch [material list] _aim_atom] < 0} {material add _aim_atom}\n"
    for name, val in zip(mat_names, s["atom_mat"]):
        atom_mat_lines += f"material change {name} _aim_atom {val}\n"
    
    # 临界点显示控制（molecule id 用变量 $cps_mol，避免硬编码错位）
    cp_toggle_lines = []
    if not show_3n3:
        cp_toggle_lines.append("mol offrep 0 $cps_mol")
    if not show_3n1:
        cp_toggle_lines.append("mol offrep 1 $cps_mol")
    if not show_3p1:
        cp_toggle_lines.append("mol offrep 2 $cps_mol")
    if not show_3p3:
        cp_toggle_lines.append("mol offrep 3 $cps_mol")

    mol_display = "mol on $mol_mol" if show_molecule else "mol off $mol_mol"
    
    tcl = f"""color Display Background white
axes location Off
display depthcue off
display projection Orthographic
display rendermode GLSL

{light_lines}
{shadow_lines}

set CPsize {cp_size}
set pathsize {path_size}

# ── 加载临界点 CPs.pdb（molecule id 存变量，防止后续编号错位）──
set cps_mol [mol new "{cps_pdb}"]
# (3,-3) 核临界点 - 紫色 (name C)
mol modselect 0 $cps_mol name C
mol modstyle 0 $cps_mol VDW $CPsize 22.0
mol modcolor 0 $cps_mol ColorID 11
# (3,-1) 键临界点 - 绿色 (name N)
mol addrep $cps_mol
mol modselect 1 $cps_mol name N
mol modstyle 1 $cps_mol VDW $CPsize 22.0
mol modcolor 1 $cps_mol ColorID 3
# (3,+1) 环临界点 - 黄色 (name O)
mol addrep $cps_mol
mol modselect 2 $cps_mol name O
mol modstyle 2 $cps_mol VDW $CPsize 22.0
mol modcolor 2 $cps_mol ColorID 4
# (3,+3) 笼临界点 - 青色 (name F)
mol addrep $cps_mol
mol modselect 3 $cps_mol name F
mol modstyle 3 $cps_mol VDW $CPsize 22.0
mol modcolor 3 $cps_mol ColorID 7

# ── 加载键径 paths.pdb（可能为空/不存在，失败则跳过，不影响分子编号）──
if {{[catch {{set paths_mol [mol new "{paths_pdb}"]}}]}} {{
    set paths_mol -1
}}
if {{$paths_mol >= 0}} {{
    mol modstyle 0 $paths_mol VDW $pathsize 22.0
    mol modcolor 0 $paths_mol ColorID 32
}}

# ── 加载分子结构 mol.pdb ──
set mol_mol [mol new "{mol_pdb}"]
mol modstyle 0 $mol_mol CPK 0.7 0.3 22.0 22.0
mol modcolor 0 $mol_mol Element
color Element C {s['c_color']}
color change rgb {s['c_color']} {s['c_rgb']}
color Element H white
color Element N iceblue
color Element O red
color Element S yellow
color change rgb 4 1.000000 0.800000 0.000000
color Element F yellow2
color change rgb 17 0.800000 1.000000 0.000000
color Element Cl yellow3
color change rgb 18 0.500000 1.000000 0.000000
color Element Br magenta2
color change rgb 28 0.600000 0.100000 0.000000
color Element I magenta
color change rgb 27 0.700000 0.000000 0.700000
color Element B pink
color change rgb 9 1.000000 0.400000 0.800000
color Element P red2
color change rgb 6 1.000000 0.400000 0.000000
{mol_display}

# ── 临界点显示控制 ──
{"\n".join(cp_toggle_lines)}

{cp_mat_lines}
{atom_mat_lines}

# ── 挂载材质 ──
mol modmaterial 0 $cps_mol _aim_cp
mol modmaterial 1 $cps_mol _aim_cp
mol modmaterial 2 $cps_mol _aim_cp
mol modmaterial 3 $cps_mol _aim_cp
if {{$paths_mol >= 0}} {{ mol modmaterial 0 $paths_mol _aim_cp }}
mol modmaterial 0 $mol_mol _aim_atom

display distance -8.0
display height 10

# ── 快捷键 ──
proc _cp_size_up {{}} {{
    global CPsize cps_mol
    set CPsize [expr {{$CPsize + 0.01}}]
    mol modstyle 0 $cps_mol VDW $CPsize 22.0
    mol modstyle 1 $cps_mol VDW $CPsize 22.0
    mol modstyle 2 $cps_mol VDW $CPsize 22.0
    mol modstyle 3 $cps_mol VDW $CPsize 22.0
    puts "临界点大小: $CPsize"
}}

proc _cp_size_down {{}} {{
    global CPsize cps_mol
    set CPsize [expr {{max(0.01, $CPsize - 0.01)}}]
    mol modstyle 0 $cps_mol VDW $CPsize 22.0
    mol modstyle 1 $cps_mol VDW $CPsize 22.0
    mol modstyle 2 $cps_mol VDW $CPsize 22.0
    mol modstyle 3 $cps_mol VDW $CPsize 22.0
    puts "临界点大小: $CPsize"
}}

bind . <KeyPress-Prior> _cp_size_up
bind . <KeyPress-Next> _cp_size_down

puts "==========================================="
puts " AIM 可视化已就绪 (样式: {style_name})"
puts " PageUp: 增大临界点"
puts " PageDown: 减小临界点"
puts "==========================================="
"""
    return tcl


def _aim_tcl_socket(port):
    """生成 Socket 控制脚本"""
    return f"""
# === Socket 服务器 ===
set serverSocket [socket -server _aim_accept -myaddr 127.0.0.1 {port}]
proc _aim_accept {{chan addr port}} {{
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _aim_handle $chan]
}}

proc _aim_handle {{chan}} {{
    if {{[eof $chan]}} {{
        close $chan
        return
    }}
    gets $chan cmd
    if {{[string trim $cmd] eq ""}} {{ return }}

    if {{[catch {{uplevel #0 $cmd}} err]}} {{
        puts $chan "ERROR: $err"
    }} else {{
        puts $chan "OK"
    }}
    flush $chan
}}

puts " Socket 端口: {port}"
"""


# ── VMD 预览 ──────────────────────────────────────────────

# 跟踪已创建的临时目录，进程退出时清理
_temp_dirs = set()

def _cleanup_temp_dirs():
    """进程退出时清理临时目录。"""
    import shutil as _shutil
    for d in list(_temp_dirs):
        try:
            _shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    _temp_dirs.clear()

atexit.register(_cleanup_temp_dirs)


def _is_ascii(s):
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _safe_filename(original):
    """如果文件名含非 ASCII 字符，生成 ASCII-safe 替代名（保留扩展名）。"""
    if _is_ascii(original):
        return original
    name, ext = os.path.splitext(original)
    safe = "aim_" + uuid.uuid4().hex[:8] + ext
    return safe


def preview_aim(cps_pdb, paths_pdb, mol_pdb, cp_size=0.07, path_size=0.02,
                show_3n3=True, show_3n1=True, show_3p1=True, show_3p3=True,
                show_molecule=True, style_name="sob-art", vmd_exe=None):
    """打开 VMD GUI 预览 AIM 结果，返回 (port, render_dir, style_name)。"""
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD

    cps_name = os.path.basename(cps_pdb)
    paths_name = os.path.basename(paths_pdb)
    mol_name = os.path.basename(mol_pdb)
    work_dir = os.path.dirname(os.path.abspath(cps_pdb))

    # 检查路径或文件名是否包含非 ASCII 字符
    path_ok = _is_ascii(cps_pdb) and _is_ascii(paths_pdb) and _is_ascii(mol_pdb)
    name_ok = _is_ascii(cps_name) and _is_ascii(paths_name) and _is_ascii(mol_name)

    # 「仅显示已查询的 CP」时，过滤后的 CPs/paths 在各自临时目录，
    # 分子在工作目录——三个文件不在同一目录，VMD 用 basename 加载会失败
    #（分子结构丢失）。此时统一复制到同一个 render_dir。
    same_dir = (os.path.dirname(os.path.abspath(paths_pdb)) == work_dir
                and os.path.dirname(os.path.abspath(mol_pdb)) == work_dir)

    if not path_ok or not name_ok or not same_dir:
        render_dir = tempfile.mkdtemp(prefix="vmd_aim_")
        _temp_dirs.add(render_dir)
        # 生成 ASCII-safe 文件名
        safe_cps = _safe_filename(cps_name)
        safe_paths = _safe_filename(paths_name)
        safe_mol = _safe_filename(mol_name)
        shutil.copy2(cps_pdb, os.path.join(render_dir, safe_cps))
        shutil.copy2(paths_pdb, os.path.join(render_dir, safe_paths))
        shutil.copy2(mol_pdb, os.path.join(render_dir, safe_mol))
        cps_name, paths_name, mol_name = safe_cps, safe_paths, safe_mol
    else:
        render_dir = work_dir

    # 获取空闲端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # 生成 TCL 脚本
    style_tcl = _aim_tcl(cps_name, paths_name, mol_name, cp_size, path_size,
                         show_3n3, show_3n1, show_3p1, show_3p3, show_molecule, style_name)
    socket_tcl = _aim_tcl_socket(port)
    tcl = style_tcl + socket_tcl

    tcl_path = os.path.join(render_dir, "_aim_preview.tcl")
    with open(tcl_path, "w") as f:
        f.write(tcl)

    # 启动 VMD
    subprocess.Popen(
        [vmd_exe, "-e", "_aim_preview.tcl"],
        cwd=render_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    return port, render_dir, style_name


# ── 通过 socket 渲染当前视角 ─────────────────────────────
def render_current_view(port, render_dir, output_png=None,
                        tachyon_exe=None, resolution=(2000, 1500), style_name="sob-art"):
    """连接 VMD socket，发送 render Tachyon 命令，Tachyon 渲染成 PNG。"""
    if tachyon_exe is None:
        tachyon_exe = DEFAULT_TACHYON
    
    s = STYLES.get(style_name, STYLES["sob-art"])
    
    # 检查 Tachyon 路径
    if not os.path.exists(tachyon_exe):
        msg = f"Tachyon 不存在: {tachyon_exe}"
        print(f"  {msg}")
        vmd_dir = os.path.dirname(tachyon_exe) if os.path.dirname(tachyon_exe) else "."
        for name in ["tachyon_WIN64.exe", "tachyon.exe", "tachyon_OGL.exe"]:
            alt_path = os.path.join(vmd_dir, name)
            if os.path.exists(alt_path):
                tachyon_exe = alt_path
                msg = f"使用替代 Tachyon: {tachyon_exe}"
                print(f"  {msg}")
                break
        else:
            msg = "未找到 Tachyon，请检查 VMD 安装路径"
            print(f"  {msg}")
            return None, msg

    # 连接 VMD socket
    vmd_sock = None
    for attempt in range(10):
        try:
            vmd_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            vmd_sock.settimeout(3)
            vmd_sock.connect(("127.0.0.1", port))
            break
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.5)
            if vmd_sock:
                vmd_sock.close()
            vmd_sock = None

    if vmd_sock is None:
        msg = "无法连接 VMD（端口未就绪或 VMD 已关闭）"
        print(f"  {msg}")
        return None, msg

    def send_cmd(cmd):
        vmd_sock.sendall((cmd + "\n").encode("utf-8"))
        time.sleep(0.3)
        resp = b""
        vmd_sock.settimeout(2)
        try:
            while True:
                chunk = vmd_sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
                if b"\n" in resp:
                    break
        except socket.timeout:
            pass
        return resp.decode("utf-8", errors="replace").strip()

    # 删除旧文件
    for fn in ["vmdscene.dat", "_render.bmp"]:
        fp = os.path.join(render_dir, fn)
        if os.path.exists(fp):
            os.remove(fp)

    # 发送渲染命令
    resp = send_cmd("render Tachyon vmdscene.dat")
    vmd_sock.close()
    
    if resp and "ERROR" in resp:
        msg = f"VMD 渲染命令失败: {resp}"
        print(f"  {msg}")
        return None, msg

    dat = os.path.join(render_dir, "vmdscene.dat")
    if not os.path.exists(dat):
        msg = "VMD 未能生成 vmdscene.dat 文件"
        print(f"  {msg}")
        return None, msg

    # 运行 Tachyon
    bmp_name = "_render.bmp"
    args = [
        tachyon_exe, "vmdscene.dat",
        "-format", "BMP", "-o", bmp_name,
        "-res", str(resolution[0]), str(resolution[1]),
        "-numthreads", "4", "-aasamples", "24",
        "-fullshade",
    ]
    if s["tachyon_options"]:
        extra = s["tachyon_options"].split()
        args.extend(extra)

    try:
        result = subprocess.run(
            args, capture_output=True, cwd=render_dir, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            err_msg = result.stderr[:200] if result.stderr else "未知错误"
            msg = f"Tachyon 渲染失败 (代码: {result.returncode}): {err_msg}"
            print(f"  {msg}")
            return None, msg
    except subprocess.TimeoutExpired:
        msg = "Tachyon 渲染超时（可能是大图或复杂场景）"
        print(f"  {msg}")
        return None, msg
    except FileNotFoundError:
        msg = f"Tachyon 未找到: {tachyon_exe}"
        print(f"  {msg}")
        return None, msg

    bmp = os.path.join(render_dir, bmp_name)
    if not os.path.exists(bmp):
        msg = "Tachyon 未能生成输出 BMP 文件"
        print(f"  {msg}")
        return None, msg

    if output_png is None:
        output_png = os.path.join(render_dir, "aim_render.png")

    # 转换为 PNG
    try:
        from PIL import Image
        img = Image.open(bmp)
        img.save(output_png)
    except ImportError:
        output_png = bmp
    except Exception as e:
        msg = f"PNG 转换失败: {e}"
        print(f"  {msg}")
        return None, msg

    return output_png, None
