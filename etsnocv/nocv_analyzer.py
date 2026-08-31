# -*- coding: utf-8 -*-
"""
NOCV Analyzer — ETS-NOCV analysis logic: run Multiwfn, parse output, generate preview scripts.
"""

import os
import re
import shutil
import subprocess
import tempfile
import socket
import time
import sys

from etsnocv.config import NOCV_STYLES, DEFAULT_MULTIWFN, DEFAULT_VMD, DEFAULT_TACHYON, VMD_ATOM_COLORS


def parse_nocv_table(output_text):
    lines = output_text.split("\n")

    table_pattern = re.compile(
        r'Pair\s+Energy\s+\|\s+Orbital\s+Eigenvalue\s+Energy\s+\|\s+Orbital\s+Eigenvalue\s+Energy'
    )
    all_blocks = []
    current_spin = "Total"
    has_kcal_note = False  # persist across Alpha/Beta subtables

    for i, line in enumerate(lines):
        # Track kcal/mol note — spans both Alpha and Beta subtables
        if not has_kcal_note and "kcal/mol" in line.lower():
            has_kcal_note = True
        # Reset note on a new section separator (e.g. "---------------")
        if has_kcal_note and line.strip().startswith("---") and "Pair" not in line and "NOCV" not in line:
            has_kcal_note = False

        # Track Alpha/Beta section headers (open-shell only)
        if "Alpha NOCV orbitals" in line:
            current_spin = "Alpha"
            continue
        if "Beta NOCV orbitals" in line:
            current_spin = "Beta"
            continue

        if table_pattern.search(line):
            note_line = "Note: All energies are given in kcal/mol" if has_kcal_note else ""
            data_lines = []
            for j in range(i + 1, min(i + 200, len(lines))):
                l = lines[j].strip()
                if not l:
                    if data_lines:
                        break
                    continue
                if re.match(r'^[-=+]+$', l):
                    continue
                m = re.match(
                    r'\s*(\d+)\s+([-]?\d+\.\d+)\s+(\d+)\s+([-]?\d+\.\d+)\s+([-]?\d+\.\d+)\s+(\d+)\s+([-]?\d+\.\d+)\s+([-]?\d+\.\d+)',
                    l
                )
                if m:
                    data_lines.append(l)
                else:
                    break
            all_blocks.append({
                'note': note_line,
                'data': data_lines,
                'spin': current_spin,
            })

    if not all_blocks:
        return None, [], "NOCV Pair table not found"

    # Merge blocks with kcal/mol note only (skip raw a.u. table)
    # Deduplicate: Multiwfn reprints the full NOCV table for each cube export
    all_rows = []
    seen = set()
    for block in all_blocks:
        # Only trust blocks with kcal/mol energy conversion
        if not (block['note'] and 'kcal/mol' in block['note'].lower()):
            continue
        rows = _parse_rows(block['data'], block.get('spin', 'Total'))
        for r in rows:
            key = (r.get('spin', 'Total'), r['pair'])
            if key not in seen:
                seen.add(key)
                all_rows.append(r)

    if not all_rows:
        return None, [], "NOCV Pair table is empty"

    sep = "-" * 75
    header = " Pair  dE_pair | Orb(+)  Eigen(+)   E(+)   | Orb(-)  Eigen(-)   E(-)"
    table_lines = [sep, header, sep]
    for r in all_rows:
        spin_tag = ""
        if r.get('spin', 'Total') == 'Alpha':
            spin_tag = "[A]"
        elif r.get('spin', 'Total') == 'Beta':
            spin_tag = "[B]"
        table_lines.append(
            f"{spin_tag} {r['pair']:<4d} {r['pair_energy']:>8.2f}  |"
            f"   {r['de_orbital']:<4d} {r['de_eigen']:>8.5f}  {r['de_energy']:>8.2f}  |"
            f"   {r['dk_orbital']:<4d} {r['dk_eigen']:>8.5f}  {r['dk_energy']:>8.2f}"
        )
    table_lines.append(sep)
    total_de = sum(r['de_energy'] for r in all_rows)
    total_dk = sum(r['dk_energy'] for r in all_rows)
    table_lines.append(
        f"  {'Sum':<4s} {'':>8s}  |   {'':<4s} {'':>8s}  {total_de:>8.2f}  |   {'':<4s} {'':>8s}  {total_dk:>8.2f}"
    )
    table_lines.append(sep)

    return header, all_rows, "\n".join(table_lines)


def _parse_rows(data_lines, spin="Total"):
    rows = []
    for line in data_lines:
        m = re.match(
            r'\s*(\d+)\s+([-]?\d+\.\d+)\s+(\d+)\s+([-]?\d+\.\d+)\s+([-]?\d+\.\d+)\s+(\d+)\s+([-]?\d+\.\d+)\s+([-]?\d+\.\d+)',
            line
        )
        if m:
            rows.append({
                'spin': spin,
                'pair': int(m.group(1)),
                'pair_energy': float(m.group(2)),
                'de_orbital': int(m.group(3)),
                'de_eigen': float(m.group(4)),
                'de_energy': float(m.group(5)),
                'dk_orbital': int(m.group(6)),
                'dk_eigen': float(m.group(7)),
                'dk_energy': float(m.group(8)),
            })
    return rows


def read_fch_alpha_beta(path):
    """Read alpha/beta electron counts from a fchk file.
    Returns (alpha, beta) tuple, or None on failure.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except Exception:
        return None
    alpha = re.search(r"Number of alpha electrons\s+I\s+(-?\d+)", text)
    beta = re.search(r"Number of beta electrons\s+I\s+(-?\d+)", text)
    if alpha and beta:
        return int(alpha.group(1)), int(beta.group(1))
    return None


def build_ets_nocv_input(fchk_complex, fchk_frag1, fchk_frag2, orbital_nums, grid_quality=3, spin_answers=None):
    comp_name = os.path.basename(fchk_complex)
    f1_name = os.path.basename(fchk_frag1)
    f2_name = os.path.basename(fchk_frag2)

    inputs = f"\n{comp_name}\n23\n2\n{f1_name}\n{f2_name}\n"

    # Open-shell: inject spin-flip answers after fragment paths
    if spin_answers is not None and len(spin_answers) >= 2:
        inputs += ("y\n" if spin_answers[0] else "n\n")
        inputs += ("y\n" if spin_answers[1] else "n\n")

    inputs += "-2\n"

    for orb_num in orbital_nums:
        cub_name = f"NOCVpair_{orb_num}.cub"
        inputs += f"7\n{grid_quality}\n{orb_num}\n{cub_name}\n"

    inputs += "q\n-10\nq\n"
    return inputs


def build_nocv_setup(fchk_complex, fchk_frag1, fchk_frag2, spin_answers=None):
    """Build NOCV setup commands: load complex, fragments, then -2 (Fock matrix).
    Does NOT include cube export or exit. Multiwfn stays at post-processing menu.
    
    Matches the original ets_nocv_gui.py build_script() command sequence:
    {complex_path}  → 23 → 2 → {frag1} → {frag2} → spin_answers → -2
    """
    comp_name = os.path.basename(fchk_complex)
    f1_name = os.path.basename(fchk_frag1)
    f2_name = os.path.basename(fchk_frag2)

    inputs = f"{comp_name}\n23\n2\n{f1_name}\n{f2_name}\n"

    # Only send flip spin answers for fragments that are open-shell.
    # Multiwfn only asks "Do you want to flip spin?" for open-shell fragments.
    # Sending extra answers for closed-shell fragments poisons the menu stream.
    if spin_answers is not None:
        for ans in spin_answers:
            inputs += "y\n" if ans else "n\n"

    inputs += "-2\n"
    return inputs


def build_cube_cmd(pair_num, grid_quality=3):
    """Build a single cube export command for one NOCV pair."""
    return f"7\n{grid_quality}\n{pair_num}\nNOCVpair_{pair_num}.cub\n"


def find_cub_files(work_dir):
    cub_files = {}
    if not os.path.isdir(work_dir):
        return cub_files
    for fn in os.listdir(work_dir):
        if fn.lower().endswith(".cub") or fn.lower().endswith(".cube"):
            cub_files[fn] = os.path.join(work_dir, fn)
    return cub_files


def _draw_bond_tcl():
    return r"""
set _vmd_bond_history {}

if {[lsearch [material list] "HalfTransparent"] == -1} {
    material add HalfTransparent
    material change opacity HalfTransparent 0.5
    material change ambient HalfTransparent 0.15
    material change specular HalfTransparent 0.5
    material change shininess HalfTransparent 0.5
    material change diffuse HalfTransparent 0.85
}

proc draw_bond {args} {
    global _vmd_bond_history
    set mol1 "top"
    set index1 ""
    set mol2 "top"
    set index2 ""
    set color "cyan"
    set h_type "pymol"
    set h_nbars 12
    set h_space 1.2
    set h_radius 0.08
    set h_arrow 0
    set h_resol 6
    set mat "Opaque"
    for {set i 0} {$i < [llength $args]} {incr i} {
        set key [lindex $args $i]
        switch -- $key {
            -mol1     { set mol1 [lindex $args [incr i]] }
            -index1   { set index1 [lindex $args [incr i]] }
            -mol2     { set mol2 [lindex $args [incr i]] }
            -index2   { set index2 [lindex $args [incr i]] }
            -color    { set color [lindex $args [incr i]] }
            -h_type   { set h_type [lindex $args [incr i]] }
            -h_nbars  { set h_nbars [lindex $args [incr i]] }
            -h_space  { set h_space [lindex $args [incr i]] }
            -h_radius { set h_radius [lindex $args [incr i]] }
            -h_arrow  { set h_arrow [lindex $args [incr i]] }
            -h_resol  { set h_resol [lindex $args [incr i]] }
            -mat      { set mat [lindex $args [incr i]] }
        }
    }
    if {$index1 eq "" || $index2 eq ""} { return }
    if {$mol1 eq "top"} { set mol1_id [molinfo top] } else { set mol1_id $mol1 }
    if {$mol2 eq "top"} { set mol2_id [molinfo top] } else { set mol2_id $mol2 }
    set sel1 [atomselect $mol1_id "index $index1"]
    set sel2 [atomselect $mol2_id "index $index2"]
    if {[$sel1 num] == 0 || [$sel2 num] == 0} {
        $sel1 delete; $sel2 delete; return
    }
    set pos1 [lindex [$sel1 get {x y z}] 0]
    set pos2 [lindex [$sel2 get {x y z}] 0]
    $sel1 delete; $sel2 delete
    set molid $mol1_id
    set before [graphics $molid list]
    graphics $molid color $color
    graphics $molid material $mat
    switch -- $h_type {
        pymol {
            set vec [vecsub $pos2 $pos1]
            set len [veclength $vec]
            if {$len < 0.001} { return }
            set dir [vecnorm $vec]
            set seg_len [expr {$len / double($h_nbars)}]
            set cyl_len [expr {$seg_len / double($h_space)}]
            for {set i 0} {$i < $h_nbars} {incr i} {
                set start [vecadd $pos1 [vecscale $dir [expr {$i * $seg_len}]]]
                set end [vecadd $start [vecscale $dir $cyl_len]]
                graphics $molid cylinder $start $end radius $h_radius resolution $h_resol
            }
            if {$h_arrow} {
                set arrow_pos [vecadd $pos2 [vecscale [vecnorm [vecsub $pos2 $pos1]] [expr {$h_radius * 3}]]]
                graphics $molid cone $pos2 $arrow_pos radius [expr {$h_radius * 2.5}] resolution $h_resol
            }
        }
        cylinder {
            graphics $molid cylinder $pos1 $pos2 radius $h_radius resolution $h_resol
            if {$h_arrow} {
                set arrow_pos [vecadd $pos2 [vecscale [vecnorm [vecsub $pos2 $pos1]] [expr {$h_radius * 3}]]]
                graphics $molid cone $pos2 $arrow_pos radius [expr {$h_radius * 2.5}] resolution $h_resol
            }
        }
        dots {
            set vec [vecsub $pos2 $pos1]
            set len [veclength $vec]
            if {$len < 0.001} { return }
            set dir [vecnorm $vec]
            set seg_len [expr {$len / double($h_nbars)}]
            for {set i 0} {$i < $h_nbars} {incr i} {
                set center [vecadd $pos1 [vecscale $dir [expr {($i + 0.5) * $seg_len}]]]
                graphics $molid sphere $center radius $h_radius resolution 12
            }
        }
        sphere {
            graphics $molid sphere $pos1 radius $h_radius resolution 12
            graphics $molid sphere $pos2 radius $h_radius resolution 12
        }
        cone {
            graphics $molid cone $pos1 $pos2 radius $h_radius resolution $h_resol
        }
        line {
            graphics $molid line $pos1 $pos2
        }
    }
    set after_ids [graphics $molid list]
    set new_ids {}
    foreach id $after_ids {
        if {[lsearch $before $id] == -1} { lappend new_ids $id }
    }
    lappend _vmd_bond_history [list $molid $new_ids]
}

proc draw_bond_undo {} {
    global _vmd_bond_history
    if {[llength $_vmd_bond_history] == 0} { return }
    set last [lindex $_vmd_bond_history end]
    set _vmd_bond_history [lrange $_vmd_bond_history 0 end-1]
    set molid [lindex $last 0]
    set ids [lindex $last 1]
    foreach id $ids { catch {graphics $molid delete $id} }
}

proc draw_bond_clear {} {
    global _vmd_bond_history
    set _vmd_bond_history {}
    foreach molid [molinfo list] { graphics $molid delete all }
}
"""


def _style_tcl(cube_name, isovalue, style_name, shade_mode="full",
               show_atoms=True, show_pos=True, show_neg=True,
               keep_h_indices=None):
    s = NOCV_STYLES.get(style_name, NOCV_STYLES["blue-red"])

    light_lines = ""
    for k, v in s["lights"].items():
        light_lines += f"light {k} {v}\n"

    if shade_mode == "medium":
        shadow_on, ao_on = True, False
    else:
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"
    shadow_lines = f"display shadows {'on' if shadow_on else 'off'}\n"
    shadow_lines += f"display ambientocclusion {'on' if ao_on else 'off'}\n"
    shadow_lines += f"display aoambient {s.get('aoambient', '0.8')}\ndisplay aodirect {s.get('aodirect', '0.3')}\n"

    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror", "opacity", "outline", "outlinewidth", "transmode"]

    mat_a_lines = "if {[lsearch [material list] _nocv_pos] < 0} {material add _nocv_pos}\n"
    for name, val in zip(mat_names, s["surface_mat"]):
        mat_a_lines += f"material change {name} _nocv_pos {val}\n"

    mat_b_lines = "if {[lsearch [material list] _nocv_neg] < 0} {material add _nocv_neg}\n"
    for name, val in zip(mat_names, s["surface_mat_b"]):
        mat_b_lines += f"material change {name} _nocv_neg {val}\n"

    atom_mat_lines = "if {[lsearch [material list] _nocv_atom] < 0} {material add _nocv_atom}\n"
    for name, val in zip(mat_names, s["atom_mat"]):
        atom_mat_lines += f"material change {name} _nocv_atom {val}\n"

    pc = s["pos_color"]
    if len(pc) == 4 and pc[1] is not None:
        color_pos = f"mol modcolor 1 top ColorID {pc[0]}\ncolor change rgb {pc[0]} {pc[1]} {pc[2]} {pc[3]}"
    else:
        color_pos = f"mol modcolor 1 top ColorID {pc[0]}"

    nc = s["neg_color"]
    if len(nc) == 4 and nc[1] is not None:
        color_neg = f"mol modcolor 2 top ColorID {nc[0]}\ncolor change rgb {nc[0]} {nc[1]} {nc[2]} {nc[3]}"
    else:
        color_neg = f"mol modcolor 2 top ColorID {nc[0]}"

    rep_idx = 0
    atom_rep = ""
    pos_rep = ""
    neg_rep = ""

    if show_atoms:
        atom_rep = f"""
mol modstyle {rep_idx} top CPK {s['atom_cpk']}
mol modmaterial {rep_idx} top _nocv_atom
{atom_mat_lines}
mol modcolor {rep_idx} top Element
color Element C {s['c_color']}
color change rgb {s['c_color']} {s['c_rgb']}
{VMD_ATOM_COLORS}
"""
        rep_idx += 1
    else:
        atom_rep = "mol delrep 0 top\n"

    if show_pos:
        pos_rep = f"""
mol addrep top
mol modstyle {rep_idx} top Isosurface {isovalue} 0 0 0 1 1
{color_pos}
{mat_a_lines}
mol modmaterial {rep_idx} top _nocv_pos
"""
        rep_idx += 1

    if show_neg:
        neg_rep = f"""
mol addrep top
mol modstyle {rep_idx} top Isosurface -{isovalue} 0 0 0 1 1
{color_neg}
{mat_b_lines}
mol modmaterial {rep_idx} top _nocv_neg
"""

    # ── Extra material lines (e.g. outline/transmode for Opaque) ──
    extra_lines = ""
    for line in s.get("extra_mat_lines", []):
        extra_lines += line + "\n"

    # ── Display distance ──
    dist = s.get("display_distance", "-8.0")

    tcl = f"""color Display Background white
axes location Off
display depthcue off
display projection Orthographic
display rendermode GLSL

{light_lines}
{shadow_lines}

mol new {cube_name} type cube first 0 last 0 step 1 waitfor all
{atom_rep}{pos_rep}{neg_rep}
{extra_lines}
display distance {dist}
display height 10
"""

    if keep_h_indices is not None:
        if keep_h_indices:
            h_idx_list = " ".join(map(str, keep_h_indices))
            h_sel_str = f"not element H or (element H and index {h_idx_list})"
        else:
            h_sel_str = "not element H"
        tcl += f'mol modselect 0 top "{h_sel_str}"\n'

    return tcl


def _live_style_tcl(style_name, shade_mode="full", isovalue=0.003, n_mols=1,
                    custom_pos_rgb=None, custom_neg_rgb=None):
    """Generate TCL to switch style on a running VMD session (no restart).
    
    Assumes:
    - Molecule(s) loaded, rep 0 = atoms, rep 1 = positive isosurface, rep 2 = negative
    - Materials _nocv_pos, _nocv_neg, _nocv_atom already exist
    """
    s = NOCV_STYLES.get(style_name, NOCV_STYLES["blue-red"])

    if shade_mode == "medium":
        shadow_on, ao_on = True, False
    else:
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"

    light_lines = ""
    for k, v in s["lights"].items():
        light_lines += f"light {k} {v}\n"

    shadow_lines = f"display shadows {'on' if shadow_on else 'off'}\n"
    shadow_lines += f"display ambientocclusion {'on' if ao_on else 'off'}\n"
    shadow_lines += f"display aoambient {s.get('aoambient', '0.8')}\ndisplay aodirect {s.get('aodirect', '0.3')}\n"

    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror", "opacity", "outline", "outlinewidth", "transmode"]

    # Materials
    tcl = light_lines + shadow_lines
    
    mat_a_lines = ""
    for name, val in zip(mat_names, s["surface_mat"]):
        mat_a_lines += f"material change {name} _nocv_pos {val}\n"

    mat_b_lines = ""
    for name, val in zip(mat_names, s["surface_mat_b"]):
        mat_b_lines += f"material change {name} _nocv_neg {val}\n"

    atom_mat = s.get("atom_mat", [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0])
    atom_mat_lines = ""
    for name, val in zip(mat_names, atom_mat):
        atom_mat_lines += f"material change {name} _nocv_atom {val}\n"
    
    extra_lines = ""
    for line in s.get("extra_mat_lines", []):
        extra_lines += line + "\n"

    tcl += mat_a_lines + mat_b_lines + atom_mat_lines + extra_lines

    # Colors (support custom RGB)
    for i in range(n_mols):
        pc = s["pos_color"]
        nc = s["neg_color"]
        
        if custom_pos_rgb:
            tcl += f"color change rgb {pc[0]} {custom_pos_rgb[0]/255.0:.3f} {custom_pos_rgb[1]/255.0:.3f} {custom_pos_rgb[2]/255.0:.3f}\n"
        elif len(pc) == 4 and pc[1] is not None:
            tcl += f"color change rgb {pc[0]} {pc[1]} {pc[2]} {pc[3]}\n"
        tcl += f"mol modcolor 1 {i} ColorID {pc[0]}\n"
        
        if custom_neg_rgb:
            tcl += f"color change rgb {nc[0]} {custom_neg_rgb[0]/255.0:.3f} {custom_neg_rgb[1]/255.0:.3f} {custom_neg_rgb[2]/255.0:.3f}\n"
        elif len(nc) == 4 and nc[1] is not None:
            tcl += f"color change rgb {nc[0]} {nc[1]} {nc[2]} {nc[3]}\n"
        tcl += f"mol modcolor 2 {i} ColorID {nc[0]}\n"
        
        tcl += f"mol modmaterial 1 {i} _nocv_pos\n"
        tcl += f"mol modmaterial 2 {i} _nocv_neg\n"
        
        # Update atom display
        tcl += f"mol modmaterial 0 {i} _nocv_atom\n"
        tcl += f"color Element C {s['c_color']}\n"
        tcl += f"color change rgb {s['c_color']} {s['c_rgb']}\n"
        tcl += f"mol modstyle 0 {i} CPK {s['atom_cpk']}\n"

    return tcl


def preview_cub(cub_path, isovalue=0.003, style_name="blue-red",
                vmd_exe=None, shade_mode="full",
                show_atoms=True, show_pos=True, show_neg=True,
                keep_h_indices=None):
    """Open VMD GUI preview of cube file. Returns (port, render_dir)."""
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD
    cub_name = os.path.basename(cub_path)
    work_dir = os.path.dirname(os.path.abspath(cub_path))

    try:
        cub_path.encode("ascii")
        has_nonascii = False
    except UnicodeEncodeError:
        has_nonascii = True

    if has_nonascii:
        render_dir = tempfile.mkdtemp(prefix="vmd_")
        shutil.copy2(cub_path, os.path.join(render_dir, cub_name))
    else:
        render_dir = work_dir

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    style_tcl = _style_tcl(cub_name, isovalue, style_name, shade_mode,
                           show_atoms=show_atoms, show_pos=show_pos, show_neg=show_neg,
                           keep_h_indices=keep_h_indices)
    socket_tcl = f"""
set serverSocket [socket -server _vmd_accept -myaddr 127.0.0.1 {port}]
proc _vmd_accept {{chan addr port}} {{
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _vmd_handle $chan]
}}
proc _vmd_handle {{chan}} {{
    if [eof $chan] {{ close $chan; return }}
    gets $chan cmd
    if {{$cmd eq ""}} return
    if [catch {{uplevel #0 $cmd}} err] {{
        puts $chan "ERROR: $err"
    }} else {{
        puts $chan "OK"
    }}
    flush $chan
}}
puts "VMD NOCV Preview Ready Port: {port}"
"""
    tcl = _draw_bond_tcl() + style_tcl + socket_tcl
    tcl_path = os.path.join(render_dir, "_preview.tcl")
    with open(tcl_path, "w") as f:
        f.write(tcl)

    proc = subprocess.Popen(
        [vmd_exe, "-e", "_preview.tcl"],
        cwd=render_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    return port, render_dir, proc


def render_current_view(port, render_dir, output_png=None,
                        tachyon_exe=None, resolution=(2000, 1500),
                        style_name="blue-red", shade_mode="full",
                        keep_h_indices=None, trans_raster=True,
                        threads=8):
    if tachyon_exe is None:
        tachyon_exe = DEFAULT_TACHYON
    s = NOCV_STYLES.get(style_name, NOCV_STYLES["blue-red"])

    vmd_sock = None
    for _ in range(10):
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
        return None

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

    for fn in ["vmdscene.dat", "_render.bmp"]:
        fp = os.path.join(render_dir, fn)
        if os.path.exists(fp):
            os.remove(fp)

    send_cmd("render Tachyon vmdscene.dat")
    vmd_sock.close()

    dat = os.path.join(render_dir, "vmdscene.dat")
    if not os.path.exists(dat):
        return None

    shade_flag = "-fullshade" if shade_mode == "full" else "-mediumshade"
    bmp_name = "_render.bmp"
    args = [
        tachyon_exe, "vmdscene.dat",
        "-format", "BMP", "-o", bmp_name,
        "-res", str(resolution[0]), str(resolution[1]),
        "-numthreads", str(threads), "-aasamples", "24",
        shade_flag,
    ]
    if trans_raster and s["tachyon_options"]:
        args.extend(s["tachyon_options"].split())

    try:
        subprocess.run(args, capture_output=True, cwd=render_dir, timeout=600,
                       encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    bmp = os.path.join(render_dir, bmp_name)
    if not os.path.exists(bmp):
        return None

    if output_png is None:
        output_png = os.path.join(render_dir, "render.png")

    try:
        from PIL import Image
        img = Image.open(bmp)
        img.save(output_png)
    except ImportError:
        output_png = bmp

    return output_png


def render_cub_auto(cub_path, output_png=None,
                    isovalue=0.003, style_name="blue-red",
                    resolution=(2000, 1500),
                    vmd_exe=None, tachyon_exe=None,
                    shade_mode="full", keep_h_indices=None,
                    trans_raster=True, threads=4):
    """Auto-render (no VMD GUI)."""
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD
    if tachyon_exe is None:
        tachyon_exe = DEFAULT_TACHYON
    if output_png is None:
        output_png = os.path.splitext(cub_path)[0] + ".png"

    cub_name = os.path.basename(cub_path)
    work_dir = os.path.dirname(os.path.abspath(cub_path))

    try:
        cub_path.encode("ascii")
        has_nonascii = False
    except UnicodeEncodeError:
        has_nonascii = True

    if has_nonascii:
        tmp_dir = tempfile.mkdtemp(prefix="vmd_")
        shutil.copy2(cub_path, os.path.join(tmp_dir, cub_name))
        render_dir = tmp_dir
    else:
        render_dir = work_dir

    s = NOCV_STYLES.get(style_name, NOCV_STYLES["blue-red"])
    style_tcl = _style_tcl(cub_name, isovalue, style_name, shade_mode,
                           keep_h_indices=keep_h_indices)
    tcl = style_tcl + "render Tachyon vmdscene.dat\nquit\n"

    tcl_path = os.path.join(render_dir, "_auto_render.tcl")
    with open(tcl_path, "w") as f:
        f.write(tcl)

    for fn in ["vmdscene.dat"]:
        fp = os.path.join(render_dir, fn)
        if os.path.exists(fp):
            os.remove(fp)

    try:
        subprocess.run(
            [vmd_exe, "-dispdev", "text", "-e", "_auto_render.tcl"],
            capture_output=True, cwd=render_dir, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        if has_nonascii:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    dat = os.path.join(render_dir, "vmdscene.dat")
    if not os.path.exists(dat):
        if has_nonascii:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    shade_flag = "-fullshade" if shade_mode == "full" else "-mediumshade"
    bmp_name = "_render.bmp"
    args = [
        tachyon_exe, "vmdscene.dat",
        "-format", "BMP", "-o", bmp_name,
        "-res", str(resolution[0]), str(resolution[1]),
        "-numthreads", str(threads), "-aasamples", "24",
        shade_flag,
    ]
    if trans_raster and s["tachyon_options"]:
        args.extend(s["tachyon_options"].split())

    try:
        subprocess.run(args, capture_output=True, cwd=render_dir, timeout=600,
                       encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        if has_nonascii:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    bmp = os.path.join(render_dir, bmp_name)
    if not os.path.exists(bmp):
        if has_nonascii:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    try:
        from PIL import Image
        img = Image.open(bmp)
        img.save(output_png)
    except ImportError:
        output_png = bmp
        if has_nonascii:
            dst = os.path.splitext(cub_path)[0] + ".bmp"
            shutil.copy2(bmp, dst)
            output_png = dst

    for fn in ["vmdscene.dat", "_auto_render.tcl", bmp_name]:
        fp = os.path.join(render_dir, fn)
        if os.path.exists(fp):
            os.remove(fp)
    if has_nonascii:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return output_png
