#!/usr/bin/env python3
"""
fchk Orbital Isosurface Visualization Tool v5.0 (Multi-Orbital Support)
Multiwfn (fchk -> cube) + VMD (Preview + Tachyon Rendering) + Tachyon (scene -> BMP/PNG)

Author: Workbuddy + Trae AI
Development: Human-AI Collaborative Development
Development Time: May 2026, ~1 hour

Acknowledgements:
  - Multiwfn (sobereva): Powerful quantum chemistry wavefunction analysis software
  - vcube2.0 (Zhong Cheng): Provides 11 beautiful rendering style configurations
  - VMD & Tachyon: Molecular visualization and ray tracing rendering engine

Features:
  - Integrates 11 rendering styles from vcube2.0 (Zhong Cheng)
  - VMD GUI Preview -> Manual View Adjustment -> One-click Tachyon Rendering
  - Supports both batch auto-rendering and manual preview modes
  - Render output filename matches fchk
  - Multi-orbital support: Display multiple orbitals simultaneously (HOMO+LUMO, etc.), each with independent colors
  - Hydrogen hiding: Optionally hide hydrogen atoms to highlight core structure
  - Dashed line drawing tool: Supports manual annotation of hydrogen bonds and other interactions

Usage:
  Run directly -> GUI pops up
  Command line -> python fchk_orbital.py folder/ --mo h,l --iso 0.05
  Multi-orbital example -> python fchk_orbital.py folder/ --mo h-1,h,l,l+1
"""

import os
import sys
import glob
import subprocess
import threading
import shutil
import time
import tempfile
import socket
import re
import math


# ── Default Paths ────────────────────────────────────────
DEFAULT_MULTIWFN = r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe"
DEFAULT_VMD = r"C:\Program Files (x86)\University of Illinois\VMD\vmd.exe"


def find_tachyon(vmd_dir):
    """在 VMD 目录自动查找 tachyon，优先 64 位版本。"""
    import glob as _glob
    vmd_dir = vmd_dir or ""
    # 优先 64 位
    t64 = os.path.join(vmd_dir, "tachyon_WIN64.exe")
    if os.path.isfile(t64):
        return t64
    t32 = os.path.join(vmd_dir, "tachyon_WIN32.exe")
    if os.path.isfile(t32):
        return t32
    # 兜底：匹配任意 tachyon*.exe
    candidates = sorted(_glob.glob(os.path.join(vmd_dir, "tachyon*.exe")))
    if candidates:
        return candidates[0]
    # 实在找不到，返回默认名（由调用方判断）
    return t64


DEFAULT_TACHYON = find_tachyon(os.path.dirname(DEFAULT_VMD))

# ── Atomic Data ──────────────────────────────────────────
ELEMENT_SYMBOLS = {
    1: 'H', 2: 'He', 3: 'Li', 4: 'Be', 5: 'B', 6: 'C', 7: 'N', 8: 'O', 9: 'F', 10: 'Ne',
    11: 'Na', 12: 'Mg', 13: 'Al', 14: 'Si', 15: 'P', 16: 'S', 17: 'Cl', 18: 'Ar',
    19: 'K', 20: 'Ca', 21: 'Sc', 22: 'Ti', 23: 'V', 24: 'Cr', 25: 'Mn', 26: 'Fe',
    27: 'Co', 28: 'Ni', 29: 'Cu', 30: 'Zn', 31: 'Ga', 32: 'Ge', 33: 'As', 34: 'Se',
    35: 'Br', 36: 'Kr', 37: 'Rb', 38: 'Sr', 39: 'Y', 40: 'Zr', 41: 'Nb', 42: 'Mo',
    43: 'Tc', 44: 'Ru', 45: 'Rh', 46: 'Pd', 47: 'Ag', 48: 'Cd', 49: 'In', 50: 'Sn',
    51: 'Sb', 52: 'Te', 53: 'I', 54: 'Xe',
}

ATOM_RADII = {
    'H': 0.31, 'C': 0.76, 'N': 0.71, 'O': 0.66, 'F': 0.57, 'S': 1.05, 'P': 1.07,
    'Cl': 1.02, 'Br': 1.2, 'I': 1.39, 'Si': 1.11, 'B': 0.84,
}

# Config file path (same directory as exe or script)
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__)),
    "fchk_orbital.ini"
)


def load_config():
    """Read path configuration from ini file, return default values if not exist."""
    import configparser
    cfg = configparser.ConfigParser()
    paths = {
        "multiwfn": DEFAULT_MULTIWFN,
        "vmd": DEFAULT_VMD,
        "tachyon": DEFAULT_TACHYON,
    }
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
        if "paths" in cfg:
            for k in paths:
                if k in cfg["paths"] and cfg["paths"][k]:
                    paths[k] = cfg["paths"][k]
    return paths


def save_config(multiwfn, vmd, tachyon):
    """Save path configuration to ini file.

    先读旧文件再更新 [paths]，保留其它 section（如 [dialogs] last_dir），
    避免每次保存路径都清空"上次目录"记忆。
    """
    import configparser
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.read(CONFIG_FILE, encoding="utf-8")
        except Exception:
            cfg = configparser.ConfigParser()
    cfg["paths"] = {
        "multiwfn": multiwfn,
        "vmd": vmd,
        "tachyon": tachyon,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


# ── vcube2.0 Style Definitions ──────────────────────────
# Each style contains: tachyon_options, lighting, shadows/AO, material, color, atom coloring
# All styles from E:\vcube2.0\styles\ (vcube 2.0, Zhong Cheng)

STYLES = {
    "ultra-glass": {
        "desc": "Ice Crystal, Ultra-Transparent Glass (冰晶透澈)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.75", "aodirect": "0.30",
        "surface_mat": [0.25, 0.12, 1.15, 0.82, 0.0, 0.30, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.12, 1.15, 0.82, 0.0, 0.30, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.48, 0.78, 0.92],
        "neg_color": [32, 0.65, 0.55, 0.88],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.50, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "sob-art": {
        "desc": "Green-Blue, Highlight, Classic (sobereva recommended)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        # Material: ambient, diffuse, specular, shininess, mirror, opacity, outline, outlinewidth, transmode
        "surface_mat": [0.1, 0.6, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.1, 0.6, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0],
        "pos_color": [12, None, None],   # ColorID 12 = green
        "neg_color": [22, None, None],   # ColorID 22 = blue
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.65, 0.5, 0.53, 0.15, 1.0, 2.0, 0.3, 0.0],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
    },
    "ao-shiny": {
        "desc": "Orange-Cyan, Jewel-like, AO(slow)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "on", "ao": "on",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.20, 0.8, 0.7, 0.3, 0.0, 0.7, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.20, 0.8, 0.7, 0.3, 0.0, 0.7, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.900, 0.500, 0.200],
        "neg_color": [32, 0.000, 0.600, 0.800],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.0, 0.53, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "ao-chalky": {
        "desc": "Blue-Green, Chalk-like, AO(slow)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "on",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.1, 0.85, 0.2, 0.55, 0.0, 0.8, 0.5, 0.7, 1.0],
        "surface_mat_b": [0.1, 0.85, 0.2, 0.55, 0.0, 0.8, 0.5, 0.7, 1.0],
        "pos_color": [31, 0.600, 0.900, 0.500],
        "neg_color": [32, 0.000, 0.700, 0.900],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.0, 0.53, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "white-green": {
        "desc": "White-Green, Plastic, Translucent",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.2, 0.5, 0.6, 0.85, 0.0, 0.7, 0.6, 0.6, 1.0],
        "surface_mat_b": [0.2, 0.5, 0.6, 0.85, 0.0, 0.7, 0.6, 0.6, 1.0],
        "pos_color": [31, 0.950, 0.950, 0.950],
        "neg_color": [32, 0.500, 0.900, 0.100],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "white-red": {
        "desc": "White-Red, Soft Chalk, Translucent",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.2, 0.45, 0.05, 0.2, 0.0, 0.7, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.2, 0.4, 0.2, 0.2, 0.0, 0.7, 0.3, 0.5, 1.0],
        "pos_color": [31, 0.950, 0.950, 0.950],
        "neg_color": [32, 1.000, 0.440, 0.260],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "morandi-blue": {
        "desc": "Morandi Blue-White, Frosted Glass",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.3, 1.0],
        "surface_mat_b": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.3, 1.0],
        "pos_color": [31, 0.760, 0.720, 0.650],
        "neg_color": [32, 0.470, 0.490, 0.520],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "morandi-green": {
        "desc": "Morandi Green-White, Frosted Glass, Opaque",
        "tachyon_options": "-trans_vmd -shadow_filter_off",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.6, 0.3, 0.1, 0.2, 0.0, 1.0, 0.4, 0.6, 1.0],
        "surface_mat_b": [0.6, 0.3, 0.1, 0.2, 0.0, 1.0, 0.4, 0.6, 1.0],
        "pos_color": [31, 0.450, 0.600, 0.400],
        "neg_color": [32, 0.850, 0.800, 0.750],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "morandi-orange": {
        "desc": "Morandi Orange-Blue, Frosted Glass",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.5, 1.0],
        "surface_mat_b": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.5, 1.0],
        "pos_color": [31, 0.760, 0.570, 0.380],
        "neg_color": [32, 0.690, 0.840, 0.890],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "morandi-red": {
        "desc": "Morandi Red-White, Frosted Glass",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.5, 1.0],
        "surface_mat_b": [0.5, 0.4, 0.0, 0.0, 0.0, 0.7, 0.3, 0.5, 1.0],
        "pos_color": [31, 0.660, 0.410, 0.350],
        "neg_color": [32, 0.820, 0.750, 0.650],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "vmwfn0": {
        "desc": "White-Ice Blue, Smooth, Translucent",
        "tachyon_options": "-fullshade",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.6, 0.3, 1.0, 0.95, 0.0, 0.7, 0.3, 0.3, 1.0],
        "surface_mat_b": [0.6, 0.2, 1.0, 1.0, 0.0, 0.7, 0.3, 0.3, 1.0],
        "pos_color": [31, 0.400, 0.450, 0.550],
        "neg_color": [32, 0.850, 0.820, 0.750],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    "vmwfn1": {
        "desc": "Red-White, Smooth Paint, Opaque",
        "tachyon_options": "-trans_vmd -shadow_filter_off",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.4, 0.6, 1.0, 0.9, 0.0, 1.0, 0.4, 0.6, 1.0],
        "surface_mat_b": [0.4, 0.6, 1.0, 0.9, 0.0, 1.0, 0.4, 0.6, 1.0],
        "pos_color": [31, 0.850, 0.850, 0.750],
        "neg_color": [32, 0.600, 0.200, 0.300],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.1, 0.3, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
    },
    # ── IboView Style Light Effects ──────────────────────────
    # Based on IboView's dual-exponential specular reflection model
    "IQmol": {
        "desc": "IboView High-Glossy, Blue-Red",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.15, 0.55, 1.0, 1.0, 0.0, 0.72, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.15, 0.55, 1.0, 1.0, 0.0, 0.72, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.050, 0.350, 0.800],
        "neg_color": [32, 0.900, 0.250, 0.250],
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.65, 0.5, 0.53, 0.20, 1.0, 1.5, 0.3, 0.0],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
        "display_distance": "-7.5",
    },
    "iboview-crystal": {
        "desc": "IboView Crystal, Cyan-Pink",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.25, 0.45, 0.95, 0.90, 0.0, 0.65, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.45, 0.95, 0.90, 0.0, 0.65, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.100, 0.800, 0.900],
        "neg_color": [32, 0.900, 0.300, 0.600],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.15, 0.55, 0.6, 0.70, 0.25, 1.0, 1.0, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-8.0",
    },
    "iboview-dark": {
        "desc": "IboView Dark, Purple-Orange",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.25",
        "surface_mat": [0.10, 0.50, 0.90, 0.85, 0.0, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.10, 0.50, 0.90, 0.85, 0.0, 0.68, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.700, 0.300, 0.800],
        "neg_color": [32, 0.900, 0.600, 0.200],
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.08, 0.60, 0.5, 0.55, 0.15, 1.0, 1.8, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.550000 0.550000 0.550000",
        "display_distance": "-7.5",
    },
    "lakers": {
        "desc": "Lakers Purple / Gold, Championship Noir",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.25",
        "surface_mat": [0.10, 0.50, 0.92, 0.88, 0.0, 0.70, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.10, 0.50, 0.92, 0.88, 0.0, 0.70, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.333, 0.145, 0.514],
        "neg_color": [32, 0.992, 0.725, 0.153],
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.06, 0.65, 0.5, 0.60, 0.15, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.450000 0.450000 0.450000",
        "display_distance": "-7.0",
    },
    # ── IboView Multi-Orbital Color Styles ─────────────────────
    "iboview-green-pink": {
        "desc": "IboView Green-Pink, Classic Dual",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.15, 0.50, 1.0, 1.0, 0.0, 0.70, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.15, 0.50, 1.0, 1.0, 0.0, 0.70, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.250, 0.850, 0.350],
        "neg_color": [32, 0.900, 0.350, 0.550],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.12, 0.60, 0.5, 0.55, 0.20, 1.0, 1.5, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.750000 0.750000 0.750000",
        "display_distance": "-7.5",
    },
    "iboview-purple-blue": {
        "desc": "IboView Purple-Blue, Mystic Texture",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.18, 0.48, 1.0, 1.0, 0.0, 0.72, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.18, 0.48, 1.0, 1.0, 0.0, 0.72, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.650, 0.350, 0.850],
        "neg_color": [32, 0.200, 0.450, 0.900],
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.10, 0.65, 0.5, 0.60, 0.22, 1.0, 1.8, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.700000 0.700000 0.700000",
        "display_distance": "-7.5",
    },
    "iboview-cyan-yellow": {
        "desc": "IboView Cyan-Yellow, Bright Contrast",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.20, 0.45, 0.95, 0.95, 0.0, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.20, 0.45, 0.95, 0.95, 0.0, 0.68, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.100, 0.850, 0.900],
        "neg_color": [32, 0.950, 0.850, 0.200],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.15, 0.55, 0.5, 0.50, 0.18, 1.0, 1.2, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.680000 0.680000 0.680000",
        "display_distance": "-8.0",
    },
    "iboview-orange-teal": {
        "desc": "IboView Orange-Teal, Warm Contrast",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.12, 0.55, 1.0, 1.0, 0.0, 0.73, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.12, 0.55, 1.0, 1.0, 0.0, 0.73, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.900, 0.500, 0.200],
        "neg_color": [32, 0.150, 0.700, 0.750],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.08, 0.68, 0.5, 0.58, 0.25, 1.0, 2.0, 0.3, 0.0],
        "c_color": "tan", "c_rgb": "0.700000 0.560000 0.360000",
        "display_distance": "-7.0",
    },
    "Gaussview": {
        "desc": "IboView Red-Green, Classic Complementary",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.10, 0.52, 1.0, 1.0, 0.0, 0.71, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.10, 0.52, 1.0, 1.0, 0.0, 0.71, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.850, 0.200, 0.250],
        "neg_color": [32, 0.200, 0.750, 0.350],
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.10, 0.62, 0.5, 0.53, 0.20, 1.0, 1.6, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "iboview-rainbow": {
        "desc": "IboView Rainbow, Colorful Effect",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.18, 0.48, 1.0, 1.0, 0.0, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.18, 0.48, 1.0, 1.0, 0.0, 0.68, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.950, 0.150, 0.600],
        "neg_color": [32, 0.150, 0.650, 0.950],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.12, 0.60, 0.5, 0.55, 0.22, 1.0, 1.4, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.750000 0.750000 0.750000",
        "display_distance": "-8.0",
    },
    # ── Curated Palette Collection ───────────────────────────
    "aurora-teal": {
        "desc": "Aurora Teal / Coral Pink, Nordic Glass",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.8", "aodirect": "0.3",
        "surface_mat": [0.18, 0.48, 0.95, 0.90, 0.0, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.18, 0.48, 0.95, 0.90, 0.0, 0.68, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.100, 0.820, 0.750],
        "neg_color": [32, 0.920, 0.450, 0.400],
        "atom_cpk": "0.650000 0.380000 30.000000 30.000000",
        "atom_mat": [0.12, 0.60, 0.5, 0.55, 0.18, 1.0, 1.6, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.620000 0.620000 0.620000",
        "display_distance": "-7.5",
    },
    "midnight-gold": {
        "desc": "Midnight Indigo / Amber Gold, Journal Quality",
        "tachyon_options": "-trans_vmd -shadow_filter_off",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.78", "aodirect": "0.32",
        "surface_mat": [0.08, 0.55, 1.0, 0.95, 0.0, 0.78, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.08, 0.55, 1.0, 0.95, 0.0, 0.78, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.180, 0.200, 0.580],
        "neg_color": [32, 0.920, 0.720, 0.300],
        "atom_cpk": "0.600000 0.420000 30.000000 30.000000",
        "atom_mat": [0.05, 0.72, 0.5, 0.62, 0.15, 1.0, 2.2, 0.3, 0.0],
        "c_color": "tan", "c_rgb": "0.680000 0.550000 0.380000",
        "display_distance": "-7.0",
        "extra_mat_lines": [
            "material change mirror Opaque 0.18",
            "material change outline Opaque 3.0",
            "material change outlinewidth Opaque 0.5",
        ],
    },
    "lavender-mint": {
        "desc": "Lavender Purple / Mint Green, Soft Elegance",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.82", "aodirect": "0.28",
        "surface_mat": [0.22, 0.42, 0.85, 0.85, 0.0, 0.65, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.22, 0.42, 0.85, 0.85, 0.0, 0.65, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.600, 0.420, 0.820],
        "neg_color": [32, 0.350, 0.820, 0.550],
        "atom_cpk": "0.680000 0.380000 30.000000 30.000000",
        "atom_mat": [0.10, 0.58, 0.5, 0.50, 0.20, 1.0, 1.4, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.720000 0.720000 0.720000",
        "display_distance": "-7.5",
    },
    "sunset-fire": {
        "desc": "Warm Orange / Deep Blue-Violet, Dramatic Sky",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.22",
        "surface_mat": [0.10, 0.52, 1.0, 1.0, 0.0, 0.73, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.10, 0.52, 1.0, 1.0, 0.0, 0.73, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.950, 0.480, 0.180],
        "neg_color": [32, 0.200, 0.180, 0.650],
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.06, 0.68, 0.5, 0.60, 0.12, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.580000 0.580000 0.580000",
        "display_distance": "-7.0",
    },
    "ocean-depth": {
        "desc": "Deep Ocean Blue / Seafoam Green, Calm Depth",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.30",
        "surface_mat": [0.12, 0.50, 0.95, 0.92, 0.0, 0.70, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.12, 0.50, 0.95, 0.92, 0.0, 0.70, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.050, 0.300, 0.700],
        "neg_color": [32, 0.200, 0.720, 0.580],
        "atom_cpk": "0.620000 0.400000 30.000000 30.000000",
        "atom_mat": [0.08, 0.65, 0.5, 0.58, 0.18, 1.0, 1.8, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "rose-quartz": {
        "desc": "Rose Quartz Pink / Slate Blue, Pantone Duo",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.82", "aodirect": "0.28",
        "surface_mat": [0.20, 0.45, 0.80, 0.78, 0.0, 0.62, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.20, 0.45, 0.80, 0.78, 0.0, 0.62, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.880, 0.520, 0.580],
        "neg_color": [32, 0.420, 0.500, 0.650],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.15, 0.52, 0.5, 0.48, 0.25, 1.0, 1.2, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.750000 0.750000 0.750000",
        "display_distance": "-8.0",
    },
    "forest-emerald": {
        "desc": "Emerald Green / Copper Brown, Forest Metal",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "off",
        "aoambient": "0.78", "aodirect": "0.32",
        "surface_mat": [0.10, 0.55, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.10, 0.55, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.150, 0.650, 0.280],
        "neg_color": [32, 0.750, 0.400, 0.220],
        "atom_cpk": "0.600000 0.420000 30.000000 30.000000",
        "atom_mat": [0.08, 0.68, 0.5, 0.60, 0.15, 1.0, 2.0, 0.3, 0.0],
        "c_color": "tan", "c_rgb": "0.680000 0.520000 0.360000",
        "display_distance": "-7.0",
    },
    "neon-cyber": {
        "desc": "Electric Violet / Neon Cyan, Cyberpunk Glow",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.25",
        "surface_mat": [0.15, 0.42, 1.0, 1.0, 0.0, 0.64, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.15, 0.42, 1.0, 1.0, 0.0, 0.64, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.720, 0.150, 0.900],
        "neg_color": [32, 0.050, 0.920, 0.880],
        "atom_cpk": "0.700000 0.350000 30.000000 30.000000",
        "atom_mat": [0.10, 0.55, 0.6, 0.65, 0.15, 0.95, 1.0, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.500000 0.500000 0.500000",
        "display_distance": "-8.0",
    },
    "cherry-blossom": {
        "desc": "Sakura Pink / Baby Blue, Japanese Airy",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.20",
        "surface_mat": [0.25, 0.40, 0.70, 0.65, 0.0, 0.55, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.40, 0.70, 0.65, 0.0, 0.55, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.900, 0.600, 0.650],
        "neg_color": [32, 0.450, 0.620, 0.820],
        "atom_cpk": "0.720000 0.330000 30.000000 30.000000",
        "atom_mat": [0.18, 0.48, 0.4, 0.42, 0.28, 1.0, 1.0, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.780000 0.780000 0.780000",
        "display_distance": "-8.0",
    },
    "graphite-ink": {
        "desc": "Graphite Black / Vermillion Red, Ink Wash Minimal",
        "tachyon_options": "-trans_vmd -shadow_filter_off",
        "lights": {"0": "on", "1": "off", "2": "on", "3": "off"},
        "shadows": "on", "ao": "off",
        "aoambient": "0.75", "aodirect": "0.35",
        "surface_mat": [0.06, 0.52, 0.95, 0.90, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.06, 0.52, 0.95, 0.90, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.220, 0.220, 0.240],
        "neg_color": [32, 0.820, 0.220, 0.180],
        "atom_cpk": "0.600000 0.450000 30.000000 30.000000",
        "atom_mat": [0.05, 0.75, 0.4, 0.65, 0.08, 1.0, 2.5, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.350000 0.350000 0.350000",
        "display_distance": "-6.5",
        "extra_mat_lines": [
            "material change mirror Opaque 0.10",
            "material change outline Opaque 2.0",
        ],
    },
    "blood-orange": {
        "desc": "Crimson Red-Orange / Deep Teal, Visceral Contrast",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.78", "aodirect": "0.32",
        "surface_mat": [0.10, 0.55, 1.0, 1.0, 0.0, 0.76, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.10, 0.55, 1.0, 1.0, 0.0, 0.76, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.880, 0.250, 0.100],
        "neg_color": [32, 0.050, 0.520, 0.480],
        "atom_cpk": "0.650000 0.380000 30.000000 30.000000",
        "atom_mat": [0.08, 0.68, 0.5, 0.62, 0.15, 1.0, 2.2, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.580000 0.580000 0.580000",
        "display_distance": "-7.0",
    },
    "starlight": {
        "desc": "Pale Champagne / Deep Cosmos Purple, Celestial",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.22",
        "surface_mat": [0.22, 0.40, 0.90, 0.82, 0.0, 0.60, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.22, 0.40, 0.90, 0.82, 0.0, 0.60, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.920, 0.850, 0.650],
        "neg_color": [32, 0.180, 0.100, 0.420],
        "atom_cpk": "0.680000 0.350000 30.000000 30.000000",
        "atom_mat": [0.15, 0.50, 0.5, 0.48, 0.28, 1.0, 1.2, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.780000 0.780000 0.780000",
        "display_distance": "-8.0",
    },
    "arctic-ice": {
        "desc": "Ice Crystal Blue / Midnight Navy, Cryogenic Cold",
        "tachyon_options": "-trans_vmd -shadow_filter_off",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.88", "aodirect": "0.18",
        "surface_mat": [0.25, 0.38, 0.85, 0.75, 0.0, 0.55, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.38, 0.85, 0.75, 0.0, 0.55, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.700, 0.920, 0.950],
        "neg_color": [32, 0.080, 0.080, 0.350],
        "atom_cpk": "0.680000 0.350000 30.000000 30.000000",
        "atom_mat": [0.18, 0.48, 0.4, 0.42, 0.30, 1.0, 1.0, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.800000 0.820000 0.820000",
        "display_distance": "-8.5",
    },
    "mango-lime": {
        "desc": "Tropical Mango / Lime Green, Summer Vibrant",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.82", "aodirect": "0.28",
        "surface_mat": [0.15, 0.50, 0.95, 0.92, 0.0, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.15, 0.50, 0.95, 0.92, 0.0, 0.68, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.920, 0.620, 0.120],
        "neg_color": [32, 0.350, 0.820, 0.280],
        "atom_cpk": "0.650000 0.380000 30.000000 30.000000",
        "atom_mat": [0.10, 0.62, 0.5, 0.55, 0.18, 1.0, 1.8, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "plum-wine": {
        "desc": "Deep Plum Purple / Golden Champagne, Luxury Wine",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "off",
        "aoambient": "0.76", "aodirect": "0.34",
        "surface_mat": [0.08, 0.58, 1.0, 1.0, 0.0, 0.78, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.08, 0.58, 1.0, 1.0, 0.0, 0.78, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.480, 0.180, 0.480],
        "neg_color": [32, 0.850, 0.720, 0.350],
        "atom_cpk": "0.600000 0.420000 30.000000 30.000000",
        "atom_mat": [0.05, 0.75, 0.5, 0.65, 0.12, 1.0, 2.4, 0.3, 0.0],
        "c_color": "tan", "c_rgb": "0.680000 0.580000 0.420000",
        "display_distance": "-7.0",
        "extra_mat_lines": [
            "material change mirror Opaque 0.20",
            "material change outline Opaque 3.5",
        ],
    },
    "plastic-bright": {
        "desc": "Plastic / Glossy Bright Surface (亮面塑料)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.25",
        # 塑料亮面: 高 diffuse + 高 specular + 中高 shininess + 偏实心
        # surface_mat: [ambient, diffuse, specular, shininess, mirror, opacity, outline, outlinewidth, transmode]
        "surface_mat": [0.12, 0.90, 0.95, 0.75, 0.0, 0.90, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.12, 0.90, 0.95, 0.75, 0.0, 0.90, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.100, 0.800, 0.900],
        "neg_color": [32, 0.950, 0.200, 0.450],
        # 球棍模型同样塑料亮面材质
        "atom_cpk": "0.650000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.95, 0.75, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    # ── Glass Family (4 additional variants) ──────────────
    # Core "ultra-glass" moved to top of STYLES as the default style.
    # Each variant has strongly contrasting ± phase colors
    "amber-glass": {
        "desc": "Amber × Cobalt Blue Glass (琥珀金×钴蓝)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.75", "aodirect": "0.30",
        "surface_mat": [0.22, 0.14, 1.10, 0.78, 0.0, 0.32, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.22, 0.14, 1.10, 0.78, 0.0, 0.32, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.95, 0.58, 0.08],
        "neg_color": [32, 0.10, 0.32, 0.82],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.50, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "frost-glass": {
        "desc": "Mint × Coral Frosted Glass (薄荷×珊瑚磨砂璃)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.28",
        "surface_mat": [0.38, 0.24, 0.25, 0.20, 0.0, 0.40, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.38, 0.24, 0.25, 0.20, 0.0, 0.40, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.22, 0.75, 0.60],
        "neg_color": [32, 0.88, 0.40, 0.42],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.15, 0.60, 0.10, 0.15, 0.0, 1.0, 0.3, 0.6, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "jade-glass": {
        "desc": "Emerald × Ruby Glass (翡翠×红宝石璃)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.75", "aodirect": "0.30",
        "surface_mat": [0.20, 0.16, 0.85, 0.68, 0.0, 0.35, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.20, 0.16, 0.85, 0.68, 0.0, 0.35, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.12, 0.70, 0.32],
        "neg_color": [32, 0.82, 0.12, 0.28],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.50, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "crystal-glass": {
        "desc": "Cream × Lavender Crystal Glass (暖奶×冷薰水晶璃)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.72", "aodirect": "0.30",
        "surface_mat": [0.12, 0.10, 1.38, 0.90, 0.0, 0.22, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.12, 0.10, 1.38, 0.90, 0.0, 0.22, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.88, 0.76, 0.45],
        "neg_color": [32, 0.52, 0.48, 0.82],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.50, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    # ── IboView-derived shiny styles (migrated from MERGED_STYLES) ──
    "Gaussview default": {
        "desc": "Gaussview 默认外观 (o* = 0.8/0.7/0.7/-0.5)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.20, 0.60, 0.65, 0.45, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.20, 0.60, 0.65, 0.45, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.20, 0.85, 0.20],
        "neg_color": [32, 0.85, 0.25, 0.25],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.95, 0.75, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Blue/Orange shiny": {
        "desc": "柔和 (蓝/橙)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.20, 0.55, 0.95],
        "neg_color": [32, 0.95, 0.55, 0.15],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Purple/Yellow shiny": {
        "desc": "柔和 (紫/黄)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.60, 0.35, 0.90],
        "neg_color": [32, 0.95, 0.85, 0.20],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Cyan/Magenta shiny": {
        "desc": "柔和 (青/品红)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.15, 0.85, 0.85],
        "neg_color": [32, 0.90, 0.25, 0.75],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Orange/Blue shiny": {
        "desc": "柔和 (橙/蓝)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.95, 0.55, 0.15],
        "neg_color": [32, 0.20, 0.55, 0.95],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Red/Green shiny": {
        "desc": "柔和 (红/绿)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.90, 0.25, 0.30],
        "neg_color": [32, 0.25, 0.80, 0.35],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Teal/Rose shiny": {
        "desc": "柔和 (青绿/玫红)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.20, 0.80, 0.70],
        "neg_color": [32, 0.95, 0.45, 0.55],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    "Mono Cyan shiny": {
        "desc": "柔和 (单色青)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.25, 0.50, 0.50, 0.20, 0.0, 0.80, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.15, 0.80, 0.80],
        "neg_color": [32, 0.25, 0.92, 0.92],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.0, 0.85, 0.80, 0.55, 0.10, 1.0, 2.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.650000 0.650000 0.650000",
        "display_distance": "-7.5",
    },
    # ── New high-end scientific series (5 styles) ──────────
    "quantum-porcelain": {
        "desc": "Quantum Porcelain, Smooth Enamel (量子瓷釉)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.25",
        # Enamel: high diffuse + mid-high specular + high shininess, opaque,
        # near-zero mirror, very faint outline → ceramic, not glass.
        "surface_mat": [0.22, 0.78, 0.70, 0.85, 0.02, 0.90, 0.08, 0.6, 1.0],
        "surface_mat_b": [0.22, 0.78, 0.70, 0.85, 0.02, 0.90, 0.08, 0.6, 1.0],
        # muted cobalt (pos) vs warm coral (neg) — distinct, paper-friendly
        "pos_color": [31, 0.18, 0.34, 0.62],
        "neg_color": [32, 0.78, 0.36, 0.32],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.12, 0.70, 0.45, 0.60, 0.0, 1.0, 1.0, 0.3, 0.0],
        "c_color": "gray", "c_rgb": "0.620000 0.620000 0.620000",
        "display_distance": "-7.5",
    },
    "liquid-quantum": {
        "desc": "Liquid Quantum, Fluid Glass (液态量子)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "on", "ao": "on",
        "aoambient": "0.90", "aodirect": "0.18",
        # Fluid drop: mid-high transparency, high specular + shininess,
        # low mirror, soft AO + light shadow → suspended liquid.
        "surface_mat": [0.18, 0.40, 1.05, 0.92, 0.08, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.18, 0.40, 1.05, 0.92, 0.08, 0.68, 0.0, 0.0, 1.0],
        # deep aqua (pos) vs warm amber (neg) — dye-in-water feel
        "pos_color": [31, 0.10, 0.55, 0.62],
        "neg_color": [32, 0.80, 0.52, 0.22],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.08, 0.55, 0.50, 0.65, 0.0, 1.0, 1.5, 0.25, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "quantum-crystal": {
        "desc": "Quantum Crystal, Prismatic Solid (量子晶体)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.82", "aodirect": "0.22",
        # Prism: mid transparency, strong specular + shininess, slight mirror,
        # faint outline → cut gem, not plain glass.
        "surface_mat": [0.16, 0.46, 0.98, 0.95, 0.15, 0.75, 0.35, 0.7, 1.0],
        "surface_mat_b": [0.16, 0.46, 0.98, 0.95, 0.15, 0.75, 0.35, 0.7, 1.0],
        # icy turquoise (pos) vs amethyst violet (neg) — clear hue split
        "pos_color": [31, 0.42, 0.78, 0.78],
        "neg_color": [32, 0.55, 0.38, 0.72],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.10, 0.60, 0.85, 0.80, 0.10, 1.0, 2.0, 0.25, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "velvet-quantum": {
        "desc": "Velvet Quantum, Soft Matte (天鹅绒量子)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "on", "ao": "on",
        "aoambient": "0.88", "aodirect": "0.22",
        # Matte velvet: very high diffuse, low specular, near-zero shininess,
        # opaque, no mirror, AO + soft shadow → soft volumetric sculpture.
        "surface_mat": [0.35, 0.82, 0.18, 0.22, 0.0, 0.95, 0.05, 0.4, 1.0],
        "surface_mat_b": [0.35, 0.82, 0.18, 0.22, 0.0, 0.95, 0.05, 0.4, 1.0],
        # deep burgundy (pos) vs dusty teal (neg) — desaturated, not neon
        "pos_color": [31, 0.45, 0.16, 0.22],
        "neg_color": [32, 0.22, 0.48, 0.46],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.20, 0.75, 0.10, 0.15, 0.0, 1.0, 0.3, 0.5, 0.0],
        "c_color": "gray", "c_rgb": "0.620000 0.620000 0.620000",
        "display_distance": "-7.5",
    },
    "precision-ink": {
        "desc": "Precision Ink, Publication Minimal (精密墨稿)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "on", "ao": "on",
        "aoambient": "0.86", "aodirect": "0.20",
        # Publication: mid-high opacity, moderate specular/shininess, no mirror,
        # very faint outline, weak AO+shadow → clean, light-bg friendly.
        "surface_mat": [0.30, 0.68, 0.45, 0.55, 0.0, 0.90, 0.12, 0.4, 1.0],
        "surface_mat_b": [0.30, 0.68, 0.45, 0.55, 0.0, 0.90, 0.12, 0.4, 1.0],
        # academic blue (pos) vs academic red (neg) — desaturated, hi-contrast
        "pos_color": [31, 0.22, 0.42, 0.82],
        "neg_color": [32, 0.82, 0.30, 0.32],
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.18, 0.72, 0.20, 0.35, 0.0, 1.0, 0.5, 0.2, 0.0],
        "c_color": "gray", "c_rgb": "0.780000 0.780000 0.780000",
        "display_distance": "-7.5",
    },
    # ── Extended material FX series (ovcanvas shader) ──────────
    # 这些风格驱动 ovcanvas 着色器的扩展材质通道：
    #   fx:          'neon'(边缘辉光) | 'pearl'(虹彩珍珠) | 'metal'(菲涅尔金属)
    #   ambient:     自发光强度（surface_mat[0] 仅作 VMD 侧提示，此处显式指定）
    #   spec_color:  高光染色（金属色）
    #   spec_mul:    1 = IboView 原样; 0 = 哑光; >1 = 更亮的高光
    #   fx_color:    边缘 / 次生光泽颜色
    "neon-cyber": {
        "desc": "Neon Cyber, Electroluminescent Tube (霓虹赛博)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.20",
        "surface_mat": [0.30, 0.45, 0.30, 0.50, 0.0, 0.85, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.30, 0.45, 0.30, 0.50, 0.0, 0.85, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.05, 0.85, 0.95],
        "neg_color": [32, 0.95, 0.20, 0.65],
        "fx": "neon",
        "ambient": 0.55,
        "fx_color": [0.55, 0.95, 1.00],
        "fx_strength": 1.0,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "plasma-core": {
        "desc": "Plasma Core, Indigo-Orange Energy (等离子核心)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.20",
        "surface_mat": [0.35, 0.40, 0.35, 0.55, 0.0, 0.82, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.35, 0.40, 0.35, 0.55, 0.0, 0.82, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.20, 0.15, 0.75],
        "neg_color": [32, 1.00, 0.45, 0.10],
        "fx": "neon",
        "ambient": 0.60,
        "fx_color": [1.00, 0.75, 0.35],
        "fx_strength": 0.9,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "aurora-pearl": {
        "desc": "Aurora Pearl, Iridescent Teal-Violet (极光珍珠)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.82", "aodirect": "0.22",
        "surface_mat": [0.20, 0.50, 0.70, 0.80, 0.0, 0.72, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.20, 0.50, 0.70, 0.80, 0.0, 0.72, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.10, 0.75, 0.65],
        "neg_color": [32, 0.55, 0.35, 0.85],
        "fx": "pearl",
        "ambient": 0.12,
        "fx_color": [0.95, 0.55, 0.85],
        "fx_strength": 0.6,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "hologram": {
        "desc": "Hologram, Silver Rainbow Sheen (全息幻彩)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.22",
        "surface_mat": [0.22, 0.48, 0.75, 0.85, 0.0, 0.68, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.22, 0.48, 0.75, 0.85, 0.0, 0.68, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.85, 0.88, 0.92],
        "neg_color": [32, 0.88, 0.82, 0.95],
        "fx": "pearl",
        "ambient": 0.20,
        "fx_color": [0.35, 0.80, 0.95],
        "fx_strength": 0.75,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "rose-gold": {
        "desc": "Rose Gold × Champagne, Brushed Metal (玫瑰金香槟)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.12, 0.40, 1.20, 0.95, 0.10, 0.90, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.12, 0.40, 1.20, 0.95, 0.10, 0.90, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.90, 0.45, 0.55],
        "neg_color": [32, 0.90, 0.82, 0.65],
        "fx": "metal",
        "ambient": 0.05,
        "spec_color": [1.00, 0.75, 0.55],
        "spec_mul": 1.9,
        "fx_color": [1.00, 0.65, 0.45],
        "fx_strength": 0.7,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "copper-patina": {
        "desc": "Copper × Patina Teal, Oxidized Metal (铜绿氧化)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.80", "aodirect": "0.25",
        "surface_mat": [0.12, 0.42, 1.10, 0.90, 0.08, 0.88, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.12, 0.42, 1.10, 0.90, 0.08, 0.88, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.85, 0.42, 0.22],
        "neg_color": [32, 0.15, 0.55, 0.52],
        "fx": "metal",
        "ambient": 0.05,
        "spec_color": [1.00, 0.62, 0.32],
        "spec_mul": 1.7,
        "fx_color": [1.00, 0.70, 0.40],
        "fx_strength": 0.6,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "matte-clay": {
        "desc": "Studio Clay, Terracotta × Slate Matte (陶土哑光)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "off", "3": "off"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.25",
        "surface_mat": [0.35, 0.82, 0.10, 0.10, 0.0, 1.0, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.35, 0.82, 0.10, 0.10, 0.0, 1.0, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.72, 0.42, 0.32],
        "neg_color": [32, 0.36, 0.44, 0.54],
        "fx": None,
        "ambient": 0.0,
        "spec_mul": 0.0,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
    "ghost-glass": {
        "desc": "Ghost Glass, Ethereal Ice Translucent (幽灵冰晶)",
        "tachyon_options": "-trans_vmd",
        "lights": {"0": "on", "1": "on", "2": "on", "3": "on"},
        "shadows": "off", "ao": "off",
        "aoambient": "0.85", "aodirect": "0.20",
        "surface_mat": [0.30, 0.30, 0.40, 0.50, 0.0, 0.35, 0.0, 0.0, 1.0],
        "surface_mat_b": [0.30, 0.30, 0.40, 0.50, 0.0, 0.35, 0.0, 0.0, 1.0],
        "pos_color": [31, 0.75, 0.90, 0.95],
        "neg_color": [32, 0.90, 0.88, 0.95],
        "fx": None,
        "ambient": 0.25,
        "spec_mul": 1.0,
        "atom_cpk": "0.600000 0.400000 30.000000 30.000000",
        "atom_mat": [0.1, 0.5, 0.15, 0.30, 0.0, 1.0, 0.5, 0.9, 0.0],
        "c_color": "gray", "c_rgb": "0.600000 0.600000 0.600000",
        "display_distance": "-7.5",
    },
}

# Atom element coloring (shared by all styles, from vcube2.0)
ATOM_COLORS = """
color change rgb 101 0.8000 0.8000 0.8000
color change rgb 102 0.8471 1.0000 1.0000
color change rgb 103 0.8000 0.4863 1.0000
color change rgb 104 0.8000 1.0000 0.0000
color change rgb 105 1.0000 0.7098 0.7098
color change rgb 106 0.5569 0.5569 0.5569
color change rgb 107 0.0980 0.0980 0.8980
color change rgb 108 0.8980 0.0000 0.0000
color change rgb 109 0.6980 1.0000 1.0000
color change rgb 110 0.6863 0.8863 0.9569
color change rgb 111 0.6667 0.3569 0.9490
color change rgb 112 0.6980 0.8000 0.0000
color change rgb 113 0.8196 0.6471 0.6471
color change rgb 114 0.4980 0.6000 0.6000
color change rgb 115 1.0000 0.4980 0.0000
color change rgb 116 1.0000 0.7765 0.1569
color change rgb 117 0.0980 0.9373 0.0980
color change rgb 118 0.4980 0.8196 0.8863
color change rgb 119 0.5569 0.2471 0.8275
color change rgb 120 0.6000 0.6000 0.0000
color change rgb 121 0.8980 0.8980 0.8863
color change rgb 122 0.7490 0.7569 0.7765
color change rgb 123 0.6471 0.6471 0.6667
color change rgb 124 0.5373 0.6000 0.7765
color change rgb 125 0.6078 0.4784 0.7765
color change rgb 126 0.4980 0.4784 0.7765
color change rgb 127 0.3569 0.4275 1.0000
color change rgb 128 0.3569 0.4784 0.7569
color change rgb 129 1.0000 0.4784 0.3765
color change rgb 130 0.4863 0.4980 0.6863
color change rgb 131 0.7569 0.5569 0.5569
color change rgb 132 0.4000 0.5569 0.5569
color change rgb 133 0.7373 0.4980 0.8863
color change rgb 134 1.0000 0.6275 0.0000
color change rgb 135 0.6471 0.1294 0.1294
color change rgb 136 0.3569 0.7294 0.8196
color change rgb 137 0.4392 0.1765 0.6863
color change rgb 138 0.4980 0.4000 0.0000
color change rgb 139 0.5765 0.9882 1.0000
color change rgb 140 0.5765 0.8784 0.8784
color change rgb 141 0.4471 0.7569 0.7882
color change rgb 142 0.3294 0.7098 0.7098
color change rgb 143 0.2275 0.6196 0.6588
color change rgb 144 0.1373 0.5569 0.5882
color change rgb 145 0.0392 0.4863 0.5490
color change rgb 146 0.0000 0.4078 0.5176
color change rgb 147 0.6000 0.7765 1.0000
color change rgb 148 1.0000 0.8471 0.5569
color change rgb 149 0.6471 0.4588 0.4471
color change rgb 150 0.4000 0.4980 0.4980
color change rgb 151 0.6196 0.3882 0.7098
color change rgb 152 0.8275 0.4784 0.0000
color change rgb 153 0.5765 0.0000 0.5765
color change rgb 154 0.2588 0.6196 0.6863
color change rgb 155 0.3373 0.0863 0.5569
color change rgb 156 0.4000 0.2000 0.0000
color change rgb 157 0.4392 0.8667 1.0000
color change rgb 158 1.0000 1.0000 0.7765
color change rgb 159 0.8471 1.0000 0.7765
color change rgb 160 0.7765 1.0000 0.7765
color change rgb 161 0.6392 1.0000 0.7765
color change rgb 162 0.5569 1.0000 0.7765
color change rgb 163 0.3765 1.0000 0.7765
color change rgb 164 0.2667 1.0000 0.7765
color change rgb 165 0.1882 1.0000 0.7765
color change rgb 166 0.1176 1.0000 0.7098
color change rgb 167 0.0000 1.0000 0.7098
color change rgb 168 0.0000 0.8980 0.4588
color change rgb 169 0.0000 0.8275 0.3176
color change rgb 170 0.0000 0.7490 0.2196
color change rgb 171 0.0000 0.6667 0.1373
color change rgb 172 0.2980 0.7569 1.0000
color change rgb 173 0.2980 0.6471 1.0000
color change rgb 174 0.1490 0.5765 0.8392
color change rgb 175 0.1490 0.4863 0.6667
color change rgb 176 0.1490 0.4000 0.5882
color change rgb 177 0.0863 0.3294 0.5294
color change rgb 178 0.0863 0.3569 0.5569
color change rgb 179 1.0000 0.8196 0.1373
color change rgb 180 0.7098 0.7098 0.7569
color change rgb 181 0.6471 0.3294 0.2980
color change rgb 182 0.3373 0.3490 0.3765
color change rgb 183 0.6196 0.3098 0.7098
color change rgb 184 0.6667 0.3569 0.0000
color change rgb 185 0.4588 0.3098 0.2667
color change rgb 186 0.2588 0.5098 0.5882
color change rgb 187 0.2588 0.0000 0.4000
color change rgb 188 0.2980 0.0980 0.0000
color change rgb 189 0.4392 0.6667 0.9765
color change rgb 190 0.0000 0.7294 1.0000
color change rgb 191 0.0000 0.6275 1.0000
color change rgb 192 0.0000 0.5569 1.0000
color change rgb 193 0.0000 0.4980 0.9490
color change rgb 194 0.0000 0.4196 0.9490
color change rgb 195 0.3294 0.3569 0.9490
color change rgb 196 0.4667 0.3569 0.8863
color change rgb 197 0.5373 0.3686 0.8863
color change rgb 198 0.6275 0.2078 0.8275
color change rgb 199 0.6588 0.1686 0.7765
color change rgb 200 0.6980 0.1176 0.7294
color change rgb 201 0.6980 0.0471 0.6471
color change rgb 202 0.7373 0.0471 0.5294
color change rgb 203 0.7765 0.0000 0.4000
color change rgb 204 1.0000 0.4980 0.4980
color change rgb 205 0.8980 0.4000 0.4000
color change rgb 206 0.8000 0.2980 0.2980
color change rgb 207 0.6980 0.2000 0.2000
color change rgb 208 0.6000 0.0980 0.0980
color change rgb 209 0.5490 0.0000 0.0000
color change rgb 210 0.4980 0.0000 0.0000
color change rgb 211 0.4471 0.0000 0.0000
color Element H  101
color Element He 102
color Element Li 103
color Element Be 104
color Element B  105
color Element C  106
color Element N  107
color Element O  108
color Element F  109
color Element Ne 110
color Element Na 111
color Element Mg 112
color Element Al 113
color Element Si 114
color Element P  115
color Element S  116
color Element Cl 117
color Element Ar 118
color Element K  119
color Element Ca 120
color Element Sc 121
color Element Ti 122
color Element V  123
color Element Cr 124
color Element Mn 125
color Element Fe 126
color Element Co 127
color Element Ni 128
color Element Cu 129
color Element Zn 130
color Element Ga 131
color Element Ge 132
color Element As 133
color Element Se 134
color Element Br 135
color Element Kr 136
color Element Rb 137
color Element Sr 138
color Element Y  139
color Element Zr 140
color Element Nb 141
color Element Mo 142
color Element Tc 143
color Element Ru 144
color Element Rh 145
color Element Pd 146
color Element Ag 147
color Element Cd 148
color Element In 149
color Element Sn 150
color Element Sb 151
color Element Te 152
color Element I  153
color Element Xe 154
color Element Cs 155
color Element Ba 156
color Element La 157
color Element Ce 158
color Element Pr 159
color Element Nd 160
color Element Pm 161
color Element Sm 162
color Element Eu 163
color Element Gd 164
color Element Tb 165
color Element Dy 166
color Element Ho 167
color Element Er 168
color Element Tm 169
color Element Yb 170
color Element Lu 171
color Element Hf 172
color Element Ta 173
color Element W  174
color Element Re 175
color Element Os 176
color Element Ir 177
color Element Pt 178
color Element Au 179
color Element Hg 180
color Element Tl 181
color Element Pb 182
color Element Bi 183
color Element Po 184
color Element At 185
color Element Rn 186
color Element Fr 187
color Element Ra 188
color Element Ac 189
color Element Th 190
color Element Pa 191
color Element U  192
color Element Np 193
color Element Pu 194
color Element Am 195
color Element Cm 196
color Element Bk 197
color Element Cf 198
color Element Es 199
color Element Fm 200
color Element Md 201
color Element No 202
color Element Lr 203
color Element Rf 204
color Element Db 205
color Element Sg 206
color Element Bh 207
color Element Hs 208
color Element Mt 209
color Element Ds 210
color Element Rg 211
"""

# ── Multi-Orbital Color Schemes ─────────────────────────
MULTI_ORBIT_COLORS = [
    {"pos": [12, None, None, None], "neg": [22, None, None, None]},
    {"pos": [31, 0.900, 0.500, 0.200], "neg": [32, 0.000, 0.600, 0.800]},
    {"pos": [33, 0.800, 0.200, 0.200], "neg": [34, 0.600, 0.200, 0.600]},
    {"pos": [35, 0.900, 0.700, 0.100], "neg": [36, 0.900, 0.300, 0.600]},
    {"pos": [37, 0.200, 0.700, 0.700], "neg": [38, 0.700, 0.500, 0.200]},
    {"pos": [39, 0.600, 0.400, 0.800], "neg": [40, 0.300, 0.700, 0.400]},
]


def _gen_multi_orbital_tcl(cube_files, isovalues, base_style_name, shade_mode="full",
                           keep_h_indices=None):
    """Generate multi-orbital VMD TCL script
    cube_files: [(cube_path, orbital_name), ...]
    isovalues: [isovalue, ...] or single value applied to all
    keep_h_indices: List of hydrogen indices to keep (0-indexed), None=keep all, []=remove all
    """
    if not cube_files:
        return ""

    s = STYLES.get(base_style_name, STYLES["sob-art"])

    light_lines = ""
    for k, v in s["lights"].items():
        light_lines += f"light {k} {v}\n"

    if shade_mode == "medium":
        shadow_on = True
        ao_on = False
    elif shade_mode == "noshadow":
        shadow_on = False
        ao_on = False
    else:
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"

    shadow_lines = f"display shadows {'on' if shadow_on else 'off'}\n"
    if ao_on:
        shadow_lines += "display ambientocclusion on\n"
    else:
        shadow_lines += "display ambientocclusion off\n"
    shadow_lines += f"display aoambient {s.get('aoambient', '0.8')}\ndisplay aodirect {s.get('aodirect', '0.3')}\n"

    # Bug fix: mat_names must include transmode (matches 9 elements of atom_mat)
    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror", "opacity", "outline", "outlinewidth", "transmode"]
    atom_mat_lines = "if {[lsearch [material list] _stl_atom] < 0} {material add _stl_atom}\n"
    for name, val in zip(mat_names, s["atom_mat"]):
        atom_mat_lines += f"material change {name} _stl_atom {val}\n"

    if isinstance(isovalues, (int, float)):
        isovalues = [isovalues] * len(cube_files)

    # Construct hydrogen filter TCL (controlled by modselect, does not affect isosurface)
    if keep_h_indices is not None:
        if keep_h_indices:
            h_idx_list = " ".join(map(str, keep_h_indices))
            h_sel_str = f"not element H or (element H and index {h_idx_list})"
        else:
            h_sel_str = "not element H"
        h_filter_template = f"""
# Hide hydrogen atoms (only affects rep 0 atom ball-stick)
mol modselect 0 top "{h_sel_str}"
"""
    else:
        h_filter_template = ""

    orbital_reps = ""
    for idx, (cube_path, orb_name) in enumerate(cube_files):
        cube_name = os.path.basename(cube_path)
        iso = isovalues[idx] if idx < len(isovalues) else isovalues[-1]
        # Bug fix: Each orbital uses corresponding color scheme instead of fixed MULTI_ORBIT_COLORS[0]
        colors = MULTI_ORBIT_COLORS[idx % len(MULTI_ORBIT_COLORS)]

        mat_name_a = f"_stl_orb_{idx}_a"
        mat_name_b = f"_stl_orb_{idx}_b"

        mat_a_lines = f"if {{[lsearch [material list] {mat_name_a}] < 0}} {{material add {mat_name_a}}}\n"
        for name, val in zip(mat_names, s["surface_mat"]):
            mat_a_lines += f"material change {name} {mat_name_a} {val}\n"

        mat_b_lines = f"if {{[lsearch [material list] {mat_name_b}] < 0}} {{material add {mat_name_b}}}\n"
        for name, val in zip(mat_names, s["surface_mat_b"]):
            mat_b_lines += f"material change {name} {mat_name_b} {val}\n"

        pc = colors["pos"]
        if len(pc) == 4 and pc[1] is not None:
            color_pos = f"mol modcolor 1 top ColorID {pc[0]}\ncolor change rgb {pc[0]} {pc[1]} {pc[2]} {pc[3]}"
        else:
            color_pos = f"mol modcolor 1 top ColorID {pc[0]}"

        nc = colors["neg"]
        if len(nc) == 4 and nc[1] is not None:
            color_neg = f"mol modcolor 2 top ColorID {nc[0]}\ncolor change rgb {nc[0]} {nc[1]} {nc[2]} {nc[3]}"
        else:
            color_neg = f"mol modcolor 2 top ColorID {nc[0]}"

        # Each orbital needs hydrogen filtering (each cube is independent molecule)
        h_filter_code = h_filter_template

        orbital_reps += f"""
# Orbital {idx + 1}: {orb_name} ({cube_name})
mol new {cube_name} type cube first 0 last 0 step 1 waitfor all
# Atoms
mol modstyle 0 top CPK {s['atom_cpk']}
mol modmaterial 0 top _stl_atom
{atom_mat_lines}
mol modcolor 0 top Element
{ATOM_COLORS}
color Element C {s['c_color']}
color change rgb {s['c_color']} {s['c_rgb']}
{h_filter_code}
# Positive isosurface
mol addrep top
mol modstyle 1 top Isosurface {iso} 0 0 0 1 1
{color_pos}
{mat_a_lines}
mol modmaterial 1 top {mat_name_a}
# Negative isosurface
mol addrep top
mol modstyle 2 top Isosurface -{iso} 0 0 0 1 1
{color_neg}
{mat_b_lines}
mol modmaterial 2 top {mat_name_b}
"""

    # Additional VMD built-in material/display settings
    extra_lines = s.get("extra_mat_lines", [])
    extra_mat_tcl = "\n".join(extra_lines) + "\n" if extra_lines else ""

    return f"""color Display Background white
axes location Off
display depthcue off
display projection Orthographic
display rendermode GLSL

{light_lines}
{shadow_lines}

# Multi-orbital isosurfaces
{orbital_reps}

display distance {s.get('display_distance', '-8.0')}
display height 10
{extra_mat_tcl}
"""


# ── Log File Parsing ─────────────────────────────────────

def parse_log(log_path):
    """Parse Gaussian log — extract last Standard/Input orientation atoms."""
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    atoms = []
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if "Standard orientation:" in line or "Input orientation:" in line:
            j = i + 1
            dashes_seen = 0
            coords = []
            while j < len(lines):
                lj = lines[j].rstrip()
                if lj.startswith(" ------"):  # leading space
                    dashes_seen += 1
                    if dashes_seen >= 3:
                        break
                    j += 1
                    continue
                if dashes_seen == 2:
                    parts = lj.split()
                    if len(parts) >= 6:
                        try:
                            center_num = int(parts[0])
                            atomic_num = int(parts[1])
                            x = float(parts[3])
                            y = float(parts[4])
                            z = float(parts[5])
                            sym = ELEMENT_SYMBOLS.get(atomic_num, "X")
                            atoms.append((center_num, sym, atomic_num, (x, y, z)))
                        except (ValueError, IndexError):
                            pass
                j += 1
            if atoms:
                break  # Use last orientation block found

    if not atoms:
        # Fallback: regex-based parse
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        pattern = r"^\s*([A-Z][a-z]?)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)"
        idx = 1
        for line in text.splitlines():
            m = re.match(pattern, line)
            if m:
                elem = m.group(1)
                x = float(m.group(2))
                y = float(m.group(3))
                z = float(m.group(4))
                an = {v: k for k, v in ELEMENT_SYMBOLS.items()}.get(elem, 0)
                atoms.append((idx, elem, an, (x, y, z)))
                idx += 1

    bonds = _auto_bonds(atoms)
    return atoms, bonds


def _auto_bonds(atoms):
    """Auto-detect bonds from atom positions using covalent radii."""
    if not atoms:
        return []
    bonds = []
    for i in range(len(atoms)):
        idx1, sym1, _, (x1, y1, z1) = atoms[i]
        r1 = ATOM_RADII.get(sym1, 1.5)
        for j in range(i + 1, len(atoms)):
            idx2, sym2, _, (x2, y2, z2) = atoms[j]
            r2 = ATOM_RADII.get(sym2, 1.5)
            d = math.sqrt((x1 - x2)**2 + (y1 - y2)**2 + (z1 - z2)**2)
            if d < r1 + r2 + 0.45:
                bonds.append((idx1, idx2))
    return bonds


def parse_log_info(log_path):
    """Extract calculation metadata from Gaussian log file."""
    info = {}
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return info

    info["File Type"] = "Gaussian"

    route_lines = [l.strip() for l in text.splitlines() if l.strip().startswith("#")]
    full_route = " ".join(route_lines).replace("#", "").strip()
    info["Route"] = full_route if full_route else "N/A"

    method = ""
    route_no_sp = full_route.replace(" ", "")
    slash_m = re.search(r"/([A-Za-z0-9\-\+\(\)]+)", route_no_sp)
    if slash_m:
        info["Basis Set"] = slash_m.group(1)
        method = route_no_sp[:slash_m.start()].strip()
    else:
        basis_m = re.search(r"\b(6-31\+?\+?G\*?\*?|6-311\+?\+?G\*?\*?|cc-pV\w+Z|aug-cc-pV\w+Z|def2\w+|STO-3G|LANL2DZ|SDD)\b",
                            full_route, re.IGNORECASE)
        info["Basis Set"] = basis_m.group(1) if basis_m else ("Gen" if "gen" in full_route.lower() else "N/A")

    if not method:
        for pat in [r"\b(UPBE1PBE|UB3LYP|B3LYP|PBE1PBE|PBEPBE|wB97XD?|CAM-B3LYP|M06-2X|M06-L|HF|RHF|UHF|MP2|CCSD)\b"]:
            m = re.search(pat, full_route, re.IGNORECASE)
            if m:
                method = m.group(1)
                break
    info["Method"] = method or "N/A"

    # Charge & multiplicity
    cm = re.search(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text)
    if cm:
        info["Charge"] = cm.group(1)
        info["Multiplicity"] = cm.group(2)

    # Energy
    em = re.search(r"SCF Done:\s+E\(\w+\)\s*=\s*(-?[\d\.D\+\-]+)", text)
    if em:
        info["Energy (Hartree)"] = em.group(1)

    return info


# ── Log → XYZ via Multiwfn ───────────────────────────────

def log_to_xyz(log_path, multiwfn_exe=None, work_dir=None):
    """Convert Gaussian log file to XYZ using Multiwfn subfunction 100/2/2."""
    if multiwfn_exe is None:
        multiwfn_exe = DEFAULT_MULTIWFN
    if work_dir is None:
        work_dir = os.path.dirname(os.path.abspath(log_path))
    os.makedirs(work_dir, exist_ok=True)

    log_name = os.path.basename(log_path)
    ascii_dir = os.path.join(work_dir, "_multiwfn_tmp")
    os.makedirs(ascii_dir, exist_ok=True)
    ascii_log = os.path.join(ascii_dir, log_name)
    if not os.path.exists(ascii_log):
        shutil.copy2(log_path, ascii_log)

    xyz_name = "temp.xyz"
    inputs = f"\n{log_name}\n100\n2\n2\n{xyz_name}\n0\nq\n"

    try:
        subprocess.run(
            multiwfn_exe, input=inputs, capture_output=True,
            cwd=ascii_dir, timeout=600, encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    xyz_src = os.path.join(ascii_dir, xyz_name)
    if not os.path.exists(xyz_src):
        try:
            shutil.rmtree(ascii_dir)
        except OSError:
            pass
        return None

    stem = os.path.splitext(log_name)[0]
    xyz_dst = os.path.join(work_dir, f"{stem}.xyz")
    shutil.move(xyz_src, xyz_dst)
    try:
        shutil.rmtree(ascii_dir)
    except OSError:
        pass
    return xyz_dst


# ── VMD Molecule-Only Preview (no isosurfaces) ────────────

def _style_tcl_mol(mol_name, style_name="sob-art", representation="CPK",
                   cpk_scale="1.0", shade_mode="full", keep_h_indices=None):
    """Generate VMD TCL for molecule-only visualization (XYZ file, no isosurface)."""
    s = STYLES.get(style_name, STYLES["sob-art"])

    light_lines = ""
    for k, v in s["lights"].items():
        light_lines += f"light {k} {v}\n"

    if shade_mode == "medium":
        shadow_on, ao_on = True, False
    elif shade_mode == "noshadow":
        shadow_on, ao_on = False, False
    else:
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"
    shadow_lines = f"display shadows {'on' if shadow_on else 'off'}\n"
    shadow_lines += f"display ambientocclusion {'on' if ao_on else 'off'}\n"
    shadow_lines += f"display aoambient {s.get('aoambient', '0.8')}\n"
    shadow_lines += f"display aodirect {s.get('aodirect', '0.3')}\n"

    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror", "opacity", "outline", "outlinewidth", "transmode"]
    atom_mat_lines = "if {[lsearch [material list] _stl_atom] < 0} {material add _stl_atom}\n"
    for name, val in zip(mat_names, s["atom_mat"]):
        atom_mat_lines += f"material change {name} _stl_atom {val}\n"

    bond_mat_vals = s.get("bond_mat", [0.05, 0.72, 0.35, 0.42, 0.08, 1.0, 0.0, 0.0, 0.0])
    bond_mat_lines = "if {[lsearch [material list] _stl_bond] < 0} {material add _stl_bond}\n"
    for name, val in zip(mat_names, bond_mat_vals):
        bond_mat_lines += f"material change {name} _stl_bond {val}\n"

    atom_cpk = s.get("atom_cpk", "0.600000 0.400000 30.000000 30.000000")
    cpk_parts = atom_cpk.split()
    if len(cpk_parts) >= 2:
        try:
            sf_val = float(cpk_scale)
            atom_cpk = f"{float(cpk_parts[0]) * sf_val:.6f} {float(cpk_parts[1]) * sf_val:.6f}"
            if len(cpk_parts) >= 4:
                atom_cpk += f" {cpk_parts[2]} {cpk_parts[3]}"
        except (ValueError, IndexError):
            pass

    if representation == "CPK":
        rep_style, rep_material = f"CPK {atom_cpk}", "_stl_atom"
    elif representation == "Licorice":
        rep_style, rep_material = "Licorice 0.2 12 12", "_stl_bond"
    elif representation == "VDW":
        rep_style, rep_material = f"VDW {atom_cpk.split()[0]} 12", "_stl_atom"
    elif representation == "Bonds":
        rep_style, rep_material = "Bonds 0.3 12", "_stl_bond"
    else:
        rep_style, rep_material = "Lines 1.0", "_stl_atom"

    h_filter_code = ""
    if keep_h_indices is not None:
        if keep_h_indices:
            h_idx_list = " ".join(map(str, keep_h_indices))
            h_sel_str = f"not element H or (element H and index {h_idx_list})"
        else:
            h_sel_str = "not element H"
        h_filter_code = f"""
set _h_sel [atomselect top "{h_sel_str}"]
if {{[$_h_sel num] > 0}} {{
    $_h_sel writepdb _temp_hfilter.pdb
    mol delete top
    mol new {{_temp_hfilter.pdb}} type pdb waitfor all
    file delete _temp_hfilter.pdb
    mol modstyle 0 top {rep_style}
    mol modmaterial 0 top {rep_material}
    mol modcolor 0 top Element
    color Element C {s['c_color']}
    color change rgb {s['c_color']} {s['c_rgb']}
}}
$_h_sel delete
"""

    extra_mat_tcl = "\n".join(s.get("extra_mat_lines", [])) + "\n" if s.get("extra_mat_lines") else ""
    display_dist = s.get("display_distance", "-8.0")
    background = s.get("background", "white")

    return f"""color Display Background {background}
axes location Off
display depthcue off
display projection Orthographic
display rendermode GLSL

{light_lines}
{shadow_lines}

mol new {{{mol_name}}} type xyz first 0 last 0 step 1 waitfor all

mol modstyle 0 top {rep_style}
mol modmaterial 0 top {rep_material}
mol modcolor 0 top Element
{atom_mat_lines}
{bond_mat_lines}
{ATOM_COLORS}
color Element C {s['c_color']}
color change rgb {s['c_color']} {s['c_rgb']}

{extra_mat_tcl}
display distance {display_dist}
display height 10

{h_filter_code}
"""


def preview_mol(xyz_path, style_name="sob-art", representation="CPK",
                cpk_scale="1.0", vmd_exe=None, shade_mode="full",
                keep_h_indices=None):
    """Start VMD with molecule-only visualization (XYZ file, no isosurface)."""
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD
    mol_name = os.path.basename(xyz_path)
    work_dir = os.path.dirname(os.path.abspath(xyz_path))

    try:
        xyz_path.encode("ascii")
        has_nonascii = False
    except UnicodeEncodeError:
        has_nonascii = True

    if has_nonascii:
        render_dir = tempfile.mkdtemp(prefix="vmd_")
        shutil.copy2(xyz_path, os.path.join(render_dir, mol_name))
    else:
        render_dir = work_dir

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    style_tcl = _style_tcl_mol(mol_name, style_name, representation, cpk_scale,
                               shade_mode=shade_mode, keep_h_indices=keep_h_indices)
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
puts "OrbitalViewer VMD ready (molecule, port: {port})"
"""
    tcl = style_tcl + _draw_bond_tcl() + socket_tcl
    tcl_path = os.path.join(render_dir, "_preview_mol.tcl")
    with open(tcl_path, "w", encoding="utf-8") as f:
        f.write(tcl)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    vmd_proc = subprocess.Popen(
        [vmd_exe, "-e", "_preview_mol.tcl"],
        cwd=render_dir,
        creationflags=creationflags,
    )
    return port, render_dir, vmd_proc


def _draw_bond_tcl():
    return r"""
# === draw_bond dashed line drawing ===
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

proc make_material {name opacity} {
    if {[lsearch [material list] $name] == -1} { material add $name }
    material change opacity $name $opacity
    material change ambient $name 0.15
    material change specular $name 0.5
    material change shininess $name 0.5
    material change diffuse $name 0.85
}
"""


def _live_style_tcl(style_name, shade_mode="full", n_mols=1,
                    rep_atom=0, rep_pos=1, rep_neg=2):
    """Generate a self-contained TCL proc `_apply_live_style` that updates the
    currently-open VMD preview in-place (no mol reload, no socket setup).

    n_mols = number of cube molecules loaded (1 = single, >1 = multi-orbital).
    rep_atom / rep_pos / rep_neg = representation indices for atoms / pos iso / neg iso.
    """
    import sys
    print(f"[DEBUG _live_style_tcl] style={style_name} rep_atom={rep_atom} rep_pos={rep_pos} rep_neg={rep_neg} n_mols={n_mols}", file=sys.stderr)
    s = STYLES.get(style_name, STYLES["sob-art"])
    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror",
                 "opacity", "outline", "outlinewidth", "transmode"]

    # ── build per-material TCL ──
    def _mat_block(name, mat_vals):
        lines = [f"if {{[lsearch [material list] {name}] >= 0}} {{material delete {name}}}",
                 f"material add {name}"]
        for pn, val in zip(mat_names, mat_vals):
            lines.append(f"material change {pn} {name} {val}")
        return "\n".join(lines)

    blocks = [_mat_block("_stl_atom", s["atom_mat"])]

    pos_rep_color = ""
    neg_rep_color = ""

    if n_mols <= 1:
        # single-orbital mode: rep_atom=atoms, rep_pos=pos iso, rep_neg=neg iso
        blocks.append(_mat_block("_stl_a", s["surface_mat"]))
        blocks.append(_mat_block("_stl_b", s["surface_mat_b"]))
        pc, nc = s["pos_color"], s["neg_color"]
        if len(pc) == 4 and pc[1] is not None:
            pos_rep_color = f"mol modcolor {rep_pos} top ColorID {pc[0]}\ncolor change rgb {pc[0]} {pc[1]} {pc[2]} {pc[3]}\n"
        else:
            pos_rep_color = f"mol modcolor {rep_pos} top ColorID {pc[0]}\n"
        if len(nc) == 4 and nc[1] is not None:
            neg_rep_color = f"mol modcolor {rep_neg} top ColorID {nc[0]}\ncolor change rgb {nc[0]} {nc[1]} {nc[2]} {nc[3]}\n"
        else:
            neg_rep_color = f"mol modcolor {rep_neg} top ColorID {nc[0]}\n"
        remap_atom = f"mol modmaterial {rep_atom} top _stl_atom\n"
        remap_pos = f"mol modmaterial {rep_pos} top _stl_a\n"
        remap_neg = f"mol modmaterial {rep_neg} top _stl_b\n"
    else:
        # multi-orbital mode: per-orbital materials _stl_orb_{i}_a/b
        remap_atom = ""
        remap_pos = ""
        remap_neg = ""
        for i in range(n_mols):
            blocks.append(_mat_block(f"_stl_orb_{i}_a", s["surface_mat"]))
            blocks.append(_mat_block(f"_stl_orb_{i}_b", s["surface_mat_b"]))
            colors = MULTI_ORBIT_COLORS[i % len(MULTI_ORBIT_COLORS)]
            pc, nc = colors["pos"], colors["neg"]
            pos_rep_color += f"mol modcolor {rep_pos} top ColorID {pc[0]}\n"
            if len(pc) == 4 and pc[1] is not None:
                pos_rep_color += f"color change rgb {pc[0]} {pc[1]} {pc[2]} {pc[3]}\n"
            neg_rep_color += f"mol modcolor {rep_neg} top ColorID {nc[0]}\n"
            if len(nc) == 4 and nc[1] is not None:
                neg_rep_color += f"color change rgb {nc[0]} {nc[1]} {nc[2]} {nc[3]}\n"
            remap_atom += f"mol modmaterial {rep_atom} top _stl_atom\n"
            remap_pos += f"mol modmaterial {rep_pos} top _stl_orb_{i}_a\n"
            remap_neg += f"mol modmaterial {rep_neg} top _stl_orb_{i}_b\n"

    # lights (first reset all 4, then set what style wants) and shadows/ao
    light_reset = "\n".join(f"light {k} off" for k in range(4)) + "\n"
    light_set = "\n".join(f"light {k} {v}" for k, v in s["lights"].items()) + "\n"

    if shade_mode == "medium":
        shadow_on, ao_on = True, False
    elif shade_mode == "noshadow":
        shadow_on, ao_on = False, False
    else:
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"

    shadow_tcl = (f"display shadows {'on' if shadow_on else 'off'}\n"
                  f"display ambientocclusion {'on' if ao_on else 'off'}\n"
                  f"display aoambient {s.get('aoambient', '0.8')}\n"
                  f"display aodirect {s.get('aodirect', '0.3')}\n")

    extra_lines = s.get("extra_mat_lines", [])
    extra_tcl = "\n".join(extra_lines) + "\n" if extra_lines else ""

    carbon_tcl = (f"color Element C {s.get('c_color', 'silver')}\n"
                  f"color change rgb {s.get('c_color', 'silver')} {s.get('c_rgb', '0.75 0.75 0.75')}\n")

    body = "\n".join(blocks) + "\n"

    tcl = f"""if {{[info proc _apply_live_style] ne ""}} {{rename _apply_live_style ""}}
proc _apply_live_style {{}} {{
# Lights + shadows
{light_reset}{light_set}{shadow_tcl}
# Materials
{body}# Surface colors
{pos_rep_color}{neg_rep_color}# Re-map materials on reps
{remap_atom}{remap_pos}{remap_neg}# CPK C color
{carbon_tcl}{extra_tcl}# Display distance
display distance {s.get('display_distance', '-8.0')}
display height 10
# Force redraw
display redraw
display update
}}
_apply_live_style
if {{[info proc _apply_live_style] ne ""}} {{rename _apply_live_style ""}}
"""
    return tcl


def _live_style_tcl_mol(style_name, shade_mode="full"):
    """Generate TCL for live style update in molecule-only mode (CPK atoms, no isosurface)."""
    s = STYLES.get(style_name, STYLES["sob-art"])

    # lights
    light_reset = "\n".join(f"light {k} off" for k in range(4)) + "\n"
    light_set = "\n".join(f"light {k} {v}" for k, v in s["lights"].items()) + "\n"

    # shadows / ao
    if shade_mode == "medium":
        shadow_on, ao_on = True, False
    elif shade_mode == "noshadow":
        shadow_on, ao_on = False, False
    else:
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"
    shadow_tcl = (f"display shadows {'on' if shadow_on else 'off'}\n"
                  f"display ambientocclusion {'on' if ao_on else 'off'}\n"
                  f"display aoambient {s.get('aoambient', '0.8')}\n"
                  f"display aodirect {s.get('aodirect', '0.3')}\n")

    # atom material only (no surface materials)
    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror",
                 "opacity", "outline", "outlinewidth", "transmode"]
    atom_tcl = "if {[lsearch [material list] _stl_atom] < 0} {material add _stl_atom}\n"
    for name, val in zip(mat_names, s["atom_mat"]):
        atom_tcl += f"material change {name} _stl_atom {val}\n"

    # carbon color
    carbon_tcl = (f"color Element C {s.get('c_color', 'silver')}\n"
                  f"color change rgb {s.get('c_color', 'silver')} "
                  f"{s.get('c_rgb', '0.75 0.75 0.75')}\n")

    tcl = f"""if {{[info proc _apply_live_style] ne ""}} {{rename _apply_live_style ""}}
proc _apply_live_style {{}} {{
# Lights + shadows
{light_reset}{light_set}{shadow_tcl}
# Atom material
{atom_tcl}# Remap atom rep
mol modmaterial 0 top _stl_atom
# CPK C color
{carbon_tcl}# Display
display redraw
display update
}}
_apply_live_style
if {{[info proc _apply_live_style] ne ""}} {{rename _apply_live_style ""}}
"""
    return tcl


def _style_tcl(cube_name, isovalue, style_name, shade_mode="full", keep_h_indices=None):
    """Generate VMD TCL setup script based on style name (excluding socket server and render commands).
    shade_mode: 'full'=full shadows, 'medium'=medium shadows, 'noshadow'=no shadows
    keep_h_indices: List of hydrogen indices to keep (0-indexed), None=keep all, []=remove all
    """
    s = STYLES.get(style_name, STYLES["sob-art"])

    # Lighting
    light_lines = ""
    for k, v in s["lights"].items():
        light_lines += f"light {k} {v}\n"

    # Shadows/AO: shade_mode overrides style defaults
    if shade_mode == "medium":
        shadow_on = True
        ao_on = False
    elif shade_mode == "noshadow":
        shadow_on = False
        ao_on = False
    else:  # full
        shadow_on = s["shadows"] == "on"
        ao_on = s["ao"] == "on"
    shadow_lines = f"display shadows {'on' if shadow_on else 'off'}\n"
    if ao_on:
        shadow_lines += "display ambientocclusion on\n"
    else:
        shadow_lines += "display ambientocclusion off\n"
    shadow_lines += "display aoambient 0.8\ndisplay aodirect 0.3\n"

    # Bug fix: mat_names includes transmode (9 items), aligned with surface_mat / atom_mat
    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror", "opacity", "outline", "outlinewidth", "transmode"]

    # Surface material
    mat_a_lines = "if {[lsearch [material list] _stl_a] < 0} {material add _stl_a}\n"
    for name, val in zip(mat_names, s["surface_mat"]):
        mat_a_lines += f"material change {name} _stl_a {val}\n"

    mat_b_lines = "if {[lsearch [material list] _stl_b] < 0} {material add _stl_b}\n"
    for name, val in zip(mat_names, s["surface_mat_b"]):
        mat_b_lines += f"material change {name} _stl_b {val}\n"

    # Atom material
    atom_mat_lines = "if {[lsearch [material list] _stl_atom] < 0} {material add _stl_atom}\n"
    for name, val in zip(mat_names, s["atom_mat"]):
        atom_mat_lines += f"material change {name} _stl_atom {val}\n"

    # Surface color
    pc = s["pos_color"]
    if len(pc) == 4:  # ColorID + RGB
        color_pos = f"mol modcolor 1 top ColorID {pc[0]}\ncolor change rgb {pc[0]} {pc[1]} {pc[2]} {pc[3]}"
    else:
        color_pos = f"mol modcolor 1 top ColorID {pc[0]}"

    nc = s["neg_color"]
    if len(nc) == 4:
        color_neg = f"mol modcolor 2 top ColorID {nc[0]}\ncolor change rgb {nc[0]} {nc[1]} {nc[2]} {nc[3]}"
    else:
        color_neg = f"mol modcolor 2 top ColorID {nc[0]}"

    # Hide hydrogen TCL (controls atom selection for rep 0 via modselect, does not affect isosurface rep 1/2)
    if keep_h_indices is not None:
        if keep_h_indices:
            h_idx_list = " ".join(map(str, keep_h_indices))
            h_sel_str = f"not element H or (element H and index {h_idx_list})"
        else:
            h_sel_str = "not element H"
        h_filter_code = f"""
# Hide hydrogen atoms (only affects atom ball-stick rep 0, not isosurface rep 1/2)
mol modselect 0 top "{h_sel_str}"
"""
    else:
        h_filter_code = ""

    # Additional VMD built-in material/display settings (sob-art uses Opaque/Glossy original materials)
    extra_lines = s.get("extra_mat_lines", [])
    extra_mat_tcl = "\n".join(extra_lines) + "\n" if extra_lines else ""

    # DEBUG: log rep layout
    import sys
    print(f"[DEBUG _style_tcl] cube={cube_name} iso={isovalue} rep_layout: 0=CPK 1=pos_iso 2=neg_iso", file=sys.stderr)

    return f"""color Display Background white
axes location Off
display depthcue off
display projection Orthographic
display rendermode GLSL

{light_lines}
{shadow_lines}

mol new {cube_name} type cube first 0 last 0 step 1 waitfor all

# Atoms
mol modstyle 0 top CPK {s['atom_cpk']}
mol modmaterial 0 top _stl_atom
{atom_mat_lines}
mol modcolor 0 top Element
{ATOM_COLORS}
color Element C {s['c_color']}
color change rgb {s['c_color']} {s['c_rgb']}

# Positive isosurface
mol addrep top
mol modstyle 1 top Isosurface {isovalue} 0 0 0 1 1
{color_pos}
{mat_a_lines}
mol modmaterial 1 top _stl_a

# Negative isosurface
mol addrep top
mol modstyle 2 top Isosurface -{isovalue} 0 0 0 1 1
{color_neg}
{mat_b_lines}
mol modmaterial 2 top _stl_b

display distance {s.get('display_distance', '-8.0')}
display height 10
{extra_mat_tcl}
{h_filter_code}
"""


# ── 画布场景 → VMD（「同步到 VMD」一键同步） ────────────────

def _socket_server_tcl(port, label):
    """VMD socket 命令服务器（供 Python 端发送实时命令）。"""
    return f"""
# === Socket Server: Waiting for Python commands ===
set serverSocket [socket -server _vmd_accept -myaddr 127.0.0.1 {port}]
proc _vmd_accept {{chan addr port}} {{
    global _vmd_waiting
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _vmd_handle $chan]
}}

proc _vmd_handle {{chan}} {{
    if [eof $chan] {{
        close $chan
        return
    }}
    gets $chan cmd
    if {{$cmd eq ""}} return

    if [catch {{uplevel #0 $cmd}} err] {{
        puts $chan "ERROR: $err"
    }} else {{
        puts $chan "OK"
    }}
    flush $chan
}}

puts "==========================================="
puts " VMD Scene Sync Ready ({label})"
puts " Port: {port}"
puts "==========================================="
"""


def _scene_tcl(scene, style_name="sob-art", shade_mode="full"):
    """把画布场景描述生成 VMD Tcl 脚本（分子 + 等值面 + 配色 + 极值点）。

    scene: {
        "xyz":      xyz 文件名（render_dir 内相对名，已写好）
        "surfaces": [ {"type":"orbital","vol":name,"iso":v,
                       "pos_color":(cid,r,g,b)|None, "neg_color":(cid,r,g,b)|None} |
                      {"type":"bgr","vol":name,"color_vol":name2,
                       "iso":v,"cmin":cmin,"cmax":cmax} ],
        "atom_groups": [ {"sel":"index 0 1", "cid":20, "rgb":(r,g,b)} ],  # 片段着色
        "keep_h":   None | [0-based 保留的 H 索引]（None=全部显示）
        "extrema":  [(x, y, z, kind)] 单位 Å，kind="max"/"min"
        "opacity":  float | None（覆盖样式默认表面不透明度）
    }
    rep 布局：0=CPK 原子；1/2=第一个 orbital 的 ±iso（保证实时滑杆可用）；
    其余表面（含 bgr）依次追加；片段着色 rep 放在最后。
    """
    s = STYLES.get(style_name, STYLES["sob-art"])

    # Lighting / shadows（与 _style_tcl 一致）
    light_lines = "".join(f"light {k} {v}\n" for k, v in s["lights"].items())
    if shade_mode == "medium":
        shadow_on, ao_on = True, False
    elif shade_mode == "noshadow":
        shadow_on, ao_on = False, False
    else:
        shadow_on, ao_on = s["shadows"] == "on", s["ao"] == "on"
    shadow_lines = f"display shadows {'on' if shadow_on else 'off'}\n"
    shadow_lines += ("display ambientocclusion on\n" if ao_on
                     else "display ambientocclusion off\n")
    shadow_lines += "display aoambient 0.8\ndisplay aodirect 0.3\n"

    mat_names = ["ambient", "diffuse", "specular", "shininess", "mirror",
                 "opacity", "outline", "outlinewidth", "transmode"]

    def mat_block(mat, vals):
        lines = [f"if {{[lsearch [material list] {mat}] < 0}} {{material add {mat}}}\n"]
        for name, val in zip(mat_names, vals):
            lines.append(f"material change {name} {mat} {val}\n")
        return "".join(lines)

    mat_a = mat_block("_stl_a", s["surface_mat"])
    mat_b = mat_block("_stl_b", s["surface_mat_b"])
    mat_atom = mat_block("_stl_atom", s["atom_mat"])
    mat_bgr = mat_block("_stl_bgr", s["surface_mat"])

    # 全局不透明度覆盖
    opacity_lines = ""
    op = scene.get("opacity")
    if op is not None:
        try:
            op = max(0.0, min(float(op), 1.0))
            for m in ("_stl_a", "_stl_b", "_stl_bgr", "EdgyGlass"):
                opacity_lines += (f"if {{[lsearch [material list] {m}] >= 0}} "
                                  f"{{material change opacity {m} {op:.3f}}}\n")
        except (TypeError, ValueError):
            pass

    extra_mat_tcl = "\n".join(s.get("extra_mat_lines", [])) + "\n" \
        if s.get("extra_mat_lines") else ""

    # H 过滤选择子句（VMD index 为 0-based）
    keep_h = scene.get("keep_h")
    if keep_h is None:
        h_clause = None
    elif keep_h:
        h_clause = f"(not element H or (element H and index {' '.join(map(str, keep_h))}))"
    else:
        h_clause = "not element H"

    lines = []
    lines.append("color Display Background white\n")
    lines.append("axes location Off\ndisplay depthcue off\n"
                 "display projection Orthographic\ndisplay rendermode GLSL\n")
    lines.append(light_lines)
    lines.append(shadow_lines)

    # 球棍配色方案：scene["atom_color"] = "Element"（默认，沿用本软件风格）
    # 或 "Name"（对齐 ESPViewer2/esp_surface_gui.py：VMD 默认 Name 配色，
    # C=青、N=蓝、O=红、H=白、S=黄）
    atom_color = scene.get("atom_color", "Element")
    if atom_color not in ("Element", "Name"):
        atom_color = "Element"

    # 分子（先建 _stl_atom 材质，再指定给 rep0，避免材质未定义时被忽略）
    lines.append(f"mol new {{{scene['xyz']}}} type xyz first 0 last 0 step 1 waitfor all\n")
    lines.append("mol bondsrecalc top\n")
    lines.append(f"mol modstyle 0 top CPK {s['atom_cpk']}\n")
    lines.append(mat_atom)
    lines.append("mol modmaterial 0 top _stl_atom\n")
    if atom_color == "Name":
        lines.append("mol modcolor 0 top Name\n")
    else:
        lines.append("mol modcolor 0 top Element\n")
        lines.append(ATOM_COLORS)
        lines.append(f"color Element C {s['c_color']}\n")
        lines.append(f"color change rgb {s['c_color']} {s['c_rgb']}\n")
    if h_clause is not None:
        lines.append(f'mol modselect 0 top "{h_clause}"\n')

    rep = 0
    vol_id = 0

    def cid_lines(cid, rgb):
        if rgb is not None and len(rgb) >= 3:
            return (f"color change rgb {cid} {rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f}\n"
                    f"mol modcolor {rep} top ColorID {cid}\n")
        return f"mol modcolor {rep} top ColorID {cid}\n"

    # 表面
    for sf in scene.get("surfaces", []):
        sf_type = sf.get("type")
        iso = sf.get("iso", 0.05)
        if sf_type == "orbital":
            vol = sf["vol"]
            lines.append(f"if {{[catch {{mol addfile {{{vol}}} type cube first 0 last 0 step 1 waitfor all volsets {{0}}}} err]}} {{puts \"SYNC-WARN: $err\"}}\n")
            this_vol = vol_id
            vol_id += 1
            # +iso（Isosurface 参数：iso volset draw wire solid normals）
            rep += 1
            lines.append(f"mol addrep top\n")
            lines.append(f"mol modstyle {rep} top Isosurface {iso} {this_vol} 0 0 1 1\n")
            pc = sf.get("pos_color")
            if pc:
                cid = pc[0]
                rgb = pc[1:4] if len(pc) > 1 else None
                lines.append(cid_lines(cid, rgb))
            else:
                pc_def = s["pos_color"]
                lines.append(cid_lines(pc_def[0], pc_def[1:4] if len(pc_def) > 1 else None))
            lines.append(mat_a)
            lines.append(f"mol modmaterial {rep} top _stl_a\n")
            # -iso
            rep += 1
            lines.append("mol addrep top\n")
            lines.append(f"mol modstyle {rep} top Isosurface -{iso} {this_vol} 0 0 1 1\n")
            nc = sf.get("neg_color")
            if nc:
                cid = nc[0]
                rgb = nc[1:4] if len(nc) > 1 else None
                lines.append(cid_lines(cid, rgb))
            else:
                nc_def = s["neg_color"]
                lines.append(cid_lines(nc_def[0], nc_def[1:4] if len(nc_def) > 1 else None))
            lines.append(mat_b)
            lines.append(f"mol modmaterial {rep} top _stl_b\n")
        elif sf_type == "bgr":
            vol = sf["vol"]
            cvol = sf.get("color_vol")
            lines.append(f"if {{[catch {{mol addfile {{{vol}}} type cube first 0 last 0 step 1 waitfor all volsets {{0}}}} err]}} {{puts \"SYNC-WARN: $err\"}}\n")
            this_vol = vol_id
            vol_id += 1
            color_vol = this_vol
            if cvol and cvol != vol:
                lines.append(f"if {{[catch {{mol addfile {{{cvol}}} type cube first 0 last 0 step 1 waitfor all volsets {{0}}}} err]}} {{puts \"SYNC-WARN: $err\"}}\n")
                color_vol = vol_id
                vol_id += 1
            rep += 1
            lines.append("mol addrep top\n")
            lines.append(f"mol modstyle {rep} top Isosurface {iso} {this_vol} 0 0 1 1\n")
            lines.append(f"mol modcolor {rep} top Volume {color_vol}\n")
            # 注意：scaleminmax 的第二个参数是该 rep 的编号（不是 vol 编号）
            lines.append(f"mol scaleminmax top {rep} {sf.get('cmin', -0.05)} {sf.get('cmax', 0.05)}\n")
            # 色标：ESP 用 BWR（对齐 ESPViewer2 的 ESPiso.vmd），IGMH 用 BGR
            cmap = str(sf.get("cmap", "BGR")).upper()
            if cmap not in ("RGB", "BGR", "RWB", "BWR"):
                cmap = "BWR"
            lines.append(f"color scale method {cmap}\n")
            # 材质：ESP 用 EdgyGlass（对齐 ESPViewer2），IGMH 用 _stl_bgr
            mat = sf.get("material", "_stl_bgr")
            if mat == "EdgyGlass":
                lines.append("material change transmode EdgyGlass 1.0\n"
                             "material change specular EdgyGlass 0.15\n"
                             "material change shininess EdgyGlass 0.95\n"
                             "material change opacity EdgyGlass 0.7\n"
                             "material change outlinewidth EdgyGlass 0.9\n"
                             "material change outline EdgyGlass 0.5\n")
                lines.append(f"mol modmaterial {rep} top EdgyGlass\n")
            else:
                lines.append(mat_bgr)
                lines.append(f"mol modmaterial {rep} top _stl_bgr\n")

    lines.append(opacity_lines)

    # 片段着色 rep（最后，避免占用 rep 1/2）
    for grp in scene.get("atom_groups", []):
        rep += 1
        lines.append("mol addrep top\n")
        lines.append(f"mol modstyle {rep} top CPK {s['atom_cpk']}\n")
        lines.append(f"mol modmaterial {rep} top _stl_atom\n")
        sel = grp["sel"]
        if h_clause is not None:
            sel = f"{sel} and {h_clause}"
        lines.append(f'mol modselect {rep} top "{sel}"\n')
        lines.append(f"mol modcolor {rep} top ColorID {grp['cid']}\n")
        rgb = grp.get("rgb")
        if rgb and len(rgb) >= 3:
            lines.append(f"color change rgb {grp['cid']} {rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f}\n")

    # ESP 极值点标记
    extrema = scene.get("extrema") or []
    if extrema:
        lines.append("draw delete all\n")
        ext_r = 0.25
        for (x, y, z, kind) in extrema:
            col = "orange" if str(kind).lower() in ("max", "pos") else "iceblue"
            lines.append(f"draw color {col}\n")
            lines.append(f"draw sphere {{{x:.4f} {y:.4f} {z:.4f}}} radius {ext_r} resolution 20\n")

    # 兜底：球棍模型始终实体不透明（rep0 配色 + _stl_atom 不透明），
    # 防止任何表面透明度/样式副作用让分子"发蓝/半透明"
    lines.append(f"mol modcolor 0 top {atom_color}\n")
    lines.append("mol modmaterial 0 top _stl_atom\n")
    lines.append("material change opacity _stl_atom 1.0\n")
    lines.append("material change transmode _stl_atom 0.0\n")

    lines.append(f"display distance {s.get('display_distance', '-8.0')}\n")
    lines.append("display height 10\n")
    lines.append(extra_mat_tcl)
    lines.append("display resetview\n")
    return "".join(lines)


def build_scene_tcl(scene, style_name="sob-art", shade_mode="full", port=None,
                    render_dir=None):
    """把场景写进渲染目录：安全化文件路径、写 xyz 与 _sync.tcl。

    scene 需含 "xyz_text"（xyz 文件内容字符串）与 "surfaces"。
    返回 (render_dir, tcl_filename)。
    """
    import tempfile as _tmp
    if render_dir is None:
        render_dir = _tmp.mkdtemp(prefix="vmd_sync_")

    def safe(p):
        """非 ASCII 路径复制进 render_dir 并返回相对名；ASCII 路径转正斜杠。"""
        if not p:
            return p
        try:
            p.encode("ascii")
            return p.replace("\\", "/")
        except UnicodeEncodeError:
            base = os.path.basename(p)
            dst = os.path.join(render_dir, base)
            if os.path.abspath(p) != os.path.abspath(dst):
                shutil.copy2(p, dst)
            return base

    xyz_text = scene.get("xyz_text", "")
    xyz_name = scene.get("xyz") or "scene.xyz"
    with open(os.path.join(render_dir, xyz_name), "w", encoding="utf-8") as f:
        f.write(xyz_text)

    for sf in scene.get("surfaces", []):
        sf["vol"] = safe(sf["vol"])
        if sf.get("color_vol"):
            sf["color_vol"] = safe(sf["color_vol"])

    tcl = _scene_tcl(scene, style_name, shade_mode)
    if port is not None:
        tcl += _socket_server_tcl(port, style_name)
    tcl = _draw_bond_tcl() + tcl
    tcl_path = os.path.join(render_dir, "_sync.tcl")
    with open(tcl_path, "w", encoding="utf-8") as f:
        f.write(tcl)
    return render_dir, "_sync.tcl"


def preview_scene(scene, style_name="sob-art", vmd_exe=None, shade_mode="full"):
    """启动 VMD 显示画布同步场景，返回 (port, render_dir) 或 (None, None)。"""
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    render_dir, tcl_name = build_scene_tcl(
        scene, style_name, shade_mode, port=port)
    subprocess.Popen(
        [vmd_exe, "-e", tcl_name],
        cwd=render_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    return port, render_dir


# ── Multiwfn: Single fchk -> cube ───────────────────────
def gen_cube(fchk_path, orbital="h", grid_quality=2,
             multiwfn_exe=None, work_dir=None):
    """Call Multiwfn to generate orbital wavefunction cube file.
    
    For open-shell systems (UHF/ROHF), use:
    - Positive indices or "ha", "la", "ha-1" for alpha orbitals
    - Negative indices or "hb", "lb", "hb-1" for beta orbitals
    
    Args:
        fchk_path: Path to fchk file
        orbital: Orbital identifier (h/l/h-1/number/ha/hb/la/lb)
        grid_quality: Grid quality (1-5)
        multiwfn_exe: Path to Multiwfn executable
        work_dir: Working directory for output
    """
    if multiwfn_exe is None:
        multiwfn_exe = DEFAULT_MULTIWFN
    if work_dir is None:
        work_dir = os.path.dirname(os.path.abspath(fchk_path))
    os.makedirs(work_dir, exist_ok=True)

    fchk_name = os.path.basename(fchk_path)
    ascii_dir = os.path.join(work_dir, "_multiwfn_tmp")
    os.makedirs(ascii_dir, exist_ok=True)
    ascii_fchk = os.path.join(ascii_dir, fchk_name)
    if not os.path.exists(ascii_fchk):
        shutil.copy2(fchk_path, ascii_fchk)

    # Command sequence: 5 -> 4 -> orbital -> grid -> 2 -> 0 -> q
    # For open-shell systems, orbital can be:
    # - ha/hb/la/lb for HOMO/LUMO alpha/beta
    # - ha-1, hb+2, etc. for shifted orbitals
    # - Positive numbers for alpha orbitals
    # - Negative numbers for beta orbitals
    inputs = (
        "\n" + fchk_name + "\n5\n4\n" + orbital + "\n"
        + str(grid_quality) + "\n2\n0\nq\n"
    )

    try:
        subprocess.run(
            multiwfn_exe, input=inputs, capture_output=True,
            cwd=ascii_dir, timeout=600, encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Error: {e}")
        return None

    cube_src = os.path.join(ascii_dir, "MOvalue.cub")
    if not os.path.exists(cube_src):
        return None

    stem = os.path.splitext(fchk_name)[0]
    cube_dst = os.path.join(work_dir, f"{stem}_MO{orbital}.cub")
    shutil.move(cube_src, cube_dst)
    try:
        shutil.rmtree(ascii_dir)
    except OSError:
        pass
    return cube_dst


# ── Multiwfn: Multi-orbital -> Multiple cubes ───────────
def gen_multi_cubes(fchk_path, orbitals, grid_quality=2,
                    multiwfn_exe=None, work_dir=None):
    """
    Call Multiwfn to generate multiple orbital wavefunction cube files.
    
    For open-shell systems (UHF/ROHF), use:
    - ha/hb/la/lb for HOMO/LUMO alpha/beta
    - ha-1, hb+2, etc. for shifted orbitals
    - Positive numbers for alpha orbitals
    - Negative numbers for beta orbitals
    
    Args:
        fchk_path: Path to fchk file
        orbitals: List of orbitals, e.g., ['h', 'l', 'h-1', 'l+1'] or ['ha', 'hb', 'la', 'lb']
        grid_quality: Grid quality (1-5)
        multiwfn_exe: Path to Multiwfn executable
        work_dir: Working directory for output
    
    Returns: [(cube_path, orbital_name), ...] or None
    """
    if multiwfn_exe is None:
        multiwfn_exe = DEFAULT_MULTIWFN
    if work_dir is None:
        work_dir = os.path.dirname(os.path.abspath(fchk_path))
    os.makedirs(work_dir, exist_ok=True)

    fchk_name = os.path.basename(fchk_path)
    stem = os.path.splitext(fchk_name)[0]
    results = []

    for orbital in orbitals:
        cube_name = f"{stem}_MO{orbital}.cub"
        cube_path = os.path.join(work_dir, cube_name)

        if os.path.exists(cube_path):
            results.append((cube_path, orbital))
            continue

        ascii_dir = os.path.join(work_dir, f"_multiwfn_tmp_{orbital}")
        os.makedirs(ascii_dir, exist_ok=True)
        ascii_fchk = os.path.join(ascii_dir, fchk_name)
        if not os.path.exists(ascii_fchk):
            shutil.copy2(fchk_path, ascii_fchk)

        # Command sequence: 5 -> 4 -> orbital -> grid -> 2 -> 0 -> q
        inputs = (
            "\n" + fchk_name + "\n5\n4\n" + str(orbital) + "\n"
            + str(grid_quality) + "\n2\n0\nq\n"
        )

        try:
            subprocess.run(
                multiwfn_exe, input=inputs, capture_output=True,
                cwd=ascii_dir, timeout=600, encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"  Error: {e}")
            continue

        cube_src = os.path.join(ascii_dir, "MOvalue.cub")
        if os.path.exists(cube_src):
            shutil.move(cube_src, cube_path)
            results.append((cube_path, orbital))

        try:
            shutil.rmtree(ascii_dir)
        except OSError:
            pass

    return results if results else None


# ── VMD Preview: Open GUI Window + Socket Server ────────
def preview_cube(cube_path, isovalue=0.05, style_name="sob-art", vmd_exe=None,
                 shade_mode="full", keep_h_indices=None):
    """
    Open VMD GUI window to preview cube file, and start socket server waiting for render commands.
    keep_h_indices: List of hydrogen indices to keep (0-indexed), None=keep all, []=remove all
    Returns: (port, render_dir) or (None, None)
    """
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD
    cube_name = os.path.basename(cube_path)
    work_dir = os.path.dirname(os.path.abspath(cube_path))

    # Detect Chinese path
    try:
        cube_path.encode("ascii")
        has_nonascii = False
    except UnicodeEncodeError:
        has_nonascii = True

    if has_nonascii:
        render_dir = tempfile.mkdtemp(prefix="vmd_")
        tmp_cube = os.path.join(render_dir, cube_name)
        shutil.copy2(cube_path, tmp_cube)
    else:
        render_dir = work_dir

    # Find an available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # Style TCL + socket server
    style_tcl = _style_tcl(cube_name, isovalue, style_name, shade_mode=shade_mode,
                            keep_h_indices=keep_h_indices)
    socket_tcl = f"""
# === Socket Server: Waiting for Python commands ===
set serverSocket [socket -server _vmd_accept -myaddr 127.0.0.1 {port}]
proc _vmd_accept {{chan addr port}} {{
    global _vmd_waiting
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _vmd_handle $chan]
}}

proc _vmd_handle {{chan}} {{
    if [eof $chan] {{
        close $chan
        return
    }}
    gets $chan cmd
    if {{$cmd eq ""}} return

    if [catch {{uplevel #0 $cmd}} err] {{
        puts $chan "ERROR: $err"
    }} else {{
        puts $chan "OK"
    }}
    flush $chan
}}

puts "==========================================="
puts " VMD Preview Ready (Style: {style_name})"
puts " Click [Render Current View] button in Python GUI"
puts " Port: {port}"
puts "==========================================="
"""
    tcl = _draw_bond_tcl() + style_tcl + socket_tcl
    tcl_path = os.path.join(render_dir, "_preview.tcl")
    with open(tcl_path, "w") as f:
        f.write(tcl)

    subprocess.Popen(
        [vmd_exe, "-e", "_preview.tcl"],
        cwd=render_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    return port, render_dir


# ── VMD Multi-Orbital Preview ──────────────────────────
def preview_multi_cubes(cube_files, isovalues, style_name="sob-art",
                        vmd_exe=None, shade_mode="full", keep_h_indices=None):
    """
    Open VMD GUI window to preview multiple cube files, and start socket server waiting for render commands.
    cube_files: [(cube_path, orbital_name), ...]
    isovalues: [isovalue, ...] or single value applied to all
    keep_h_indices: List of hydrogen indices to keep (0-indexed), None=keep all, []=remove all
    Returns: (port, render_dir, copied_cubes) or (None, None, None)
    """
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD

    if not cube_files:
        return None, None, None

    work_dir = os.path.dirname(os.path.abspath(cube_files[0][0]))
    has_nonascii = False
    for cube_path, _ in cube_files:
        try:
            cube_path.encode("ascii")
        except UnicodeEncodeError:
            has_nonascii = True
            break

    if has_nonascii:
        render_dir = tempfile.mkdtemp(prefix="vmd_multi_")
        copied_cubes = []
        for cube_path, orb_name in cube_files:
            cube_name = os.path.basename(cube_path)
            tmp_cube = os.path.join(render_dir, cube_name)
            shutil.copy2(cube_path, tmp_cube)
            copied_cubes.append((tmp_cube, orb_name))
    else:
        render_dir = work_dir
        copied_cubes = cube_files

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    style_tcl = _gen_multi_orbital_tcl(copied_cubes, isovalues, style_name, shade_mode=shade_mode,
                                       keep_h_indices=keep_h_indices)
    orb_names = ", ".join([orb for _, orb in copied_cubes])
    socket_tcl = f"""
# === Socket Server: Waiting for Python commands ===
set serverSocket [socket -server _vmd_accept -myaddr 127.0.0.1 {port}]
proc _vmd_accept {{chan addr port}} {{
    global _vmd_waiting
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _vmd_handle $chan]
}}

proc _vmd_handle {{chan}} {{
    if [eof $chan] {{
        close $chan
        return
    }}
    gets $chan cmd
    if {{$cmd eq ""}} return

    if [catch {{uplevel #0 $cmd}} err] {{
        puts $chan "ERROR: $err"
    }} else {{
        puts $chan "OK"
    }}
    flush $chan
}}

puts "==========================================="
puts " VMD Multi-Orbital Preview Ready"
puts " Orbitals: {orb_names}"
puts " Style: {style_name}"
puts " Click [Render Current View] button in Python GUI"
puts " Port: {port}"
puts "==========================================="
"""
    tcl = _draw_bond_tcl() + style_tcl + socket_tcl
    tcl_path = os.path.join(render_dir, "_preview_multi.tcl")
    with open(tcl_path, "w") as f:
        f.write(tcl)

    subprocess.Popen(
        [vmd_exe, "-e", "_preview_multi.tcl"],
        cwd=render_dir,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    return port, render_dir, copied_cubes


# ── Send Render Command to VMD via Socket ──────────────
def render_current_view(port, render_dir, output_png=None,
                        tachyon_exe=None, resolution=(2000, 1500),
                        style_name="sob-art", shade_mode="full",
                        trans_mode=None, threads=4, log_func=None):
    """
    Connect to VMD's socket server, send render Tachyon command,
    then render to PNG with Tachyon.
    
    Parameters:
        trans_mode: Tachyon transparency mode: "vmd"|"raster3d"|"orig" or None (off)
        threads: Number of Tachyon rendering threads
        log_func: Optional callback function(str) to receive log/error messages
    """
    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    if tachyon_exe is None:
        tachyon_exe = DEFAULT_TACHYON
    s = STYLES.get(style_name, STYLES["sob-art"])

    # Connect to VMD socket
    vmd_sock = None
    last_error = None
    for attempt in range(10):
        try:
            vmd_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            vmd_sock.settimeout(3)
            vmd_sock.connect(("127.0.0.1", port))
            break
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            last_error = str(e)
            time.sleep(0.5)
            if vmd_sock:
                vmd_sock.close()
            vmd_sock = None

    if vmd_sock is None:
        _log(f"  Cannot connect to VMD (port {port}): {last_error}")
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

    # Clean up old files
    for fn in ["vmdscene.dat", "_render.tga"]:
        fp = os.path.join(render_dir, fn)
        if os.path.exists(fp):
            os.remove(fp)

    resp = send_cmd("render Tachyon vmdscene.dat")
    vmd_sock.close()
    if resp and not resp.startswith("OK"):
        _log(f"  VMD 返回异常: {resp}")

    dat = os.path.join(render_dir, "vmdscene.dat")
    if not os.path.exists(dat):
        _log(f"  vmdscene.dat does not exist: {dat}")
        return None

    dat_size = os.path.getsize(dat)
    _log(f"  vmdscene.dat 已生成 ({dat_size} 字节)，开始 Tachyon 渲染...")

    # Tachyon rendering: shade_mode determines lighting level
    if shade_mode == "noshadow":
        shade_flag = None
    else:
        shade_flag = "-fullshade" if shade_mode == "full" else "-mediumshade"
    tga_name = "_render.tga"
    args = [tachyon_exe, "vmdscene.dat",
        "-format", "TARGA", "-o", tga_name,
        "-res", str(resolution[0]), str(resolution[1]),
        "-numthreads", str(threads), "-aasamples", "24"]
    if shade_flag:
        args.append(shade_flag)
    # Apply style's tachyon_options (e.g. -trans_vmd for transparent background)
    if s["tachyon_options"]:
        extra = s["tachyon_options"].split()
        args.extend(extra)
    # Add -trans_xxx based on user selection (overrides style default if set)
    if trans_mode:
        args.append(f"-trans_{trans_mode}")

    try:
        result = subprocess.run(
            args, capture_output=True, cwd=render_dir, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            _log(f"  Tachyon 执行失败 (返回码: {result.returncode})")
            _log(f"  命令: {' '.join(args)}")
            if result.stderr:
                _log(f"  错误输出: {result.stderr[:1000]}")
            if result.stdout:
                _log(f"  标准输出: {result.stdout[:500]}")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        _log(f"  Tachyon 执行异常: {e}")
        return None

    tga = os.path.join(render_dir, tga_name)
    if not os.path.exists(tga):
        _log(f"  TGA 文件不存在: {tga}")
        return None

    if output_png is None:
        output_png = os.path.join(render_dir, "render.png")

    try:
        from PIL import Image
        img = Image.open(tga)
        if img.mode == 'RGBA':
            img.save(output_png, 'PNG')
        else:
            img.save(output_png)
    except ImportError:
        output_png = tga

    return output_png


# ── Auto Render (No Preview, for Batch Mode) ─────────────
def render_cube_auto(cube_path, output_png=None, isovalue=0.05,
                     vmd_exe=None, tachyon_exe=None,
                     resolution=(2000, 1500), style_name="sob-art", shade_mode="full"):
    """Auto render (without opening VMD GUI), for batch mode."""
    if vmd_exe is None:
        vmd_exe = DEFAULT_VMD
    if tachyon_exe is None:
        tachyon_exe = DEFAULT_TACHYON
    if output_png is None:
        output_png = os.path.splitext(cube_path)[0] + ".png"

    cube_name = os.path.basename(cube_path)
    work_dir = os.path.dirname(os.path.abspath(cube_path))

    try:
        cube_path.encode("ascii")
        has_nonascii = False
    except UnicodeEncodeError:
        has_nonascii = True

    if has_nonascii:
        tmp_dir = tempfile.mkdtemp(prefix="vmd_")
        tmp_cube = os.path.join(tmp_dir, cube_name)
        shutil.copy2(cube_path, tmp_cube)
        render_dir = tmp_dir
    else:
        render_dir = work_dir

    s = STYLES.get(style_name, STYLES["sob-art"])
    style_tcl = _style_tcl(cube_name, isovalue, style_name, shade_mode=shade_mode)
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

    if shade_mode == "noshadow":
        shade_flag = None
    else:
        shade_flag = "-fullshade" if shade_mode == "full" else "-mediumshade"
    tga_name = "_render.tga"
    args = [tachyon_exe, "vmdscene.dat",
        "-format", "TARGA", "-o", tga_name,
        "-res", str(resolution[0]), str(resolution[1]),
        "-numthreads", "4", "-aasamples", "24"]
    if shade_flag:
        args.append(shade_flag)
    if s["tachyon_options"]:
        extra = s["tachyon_options"].split()
        args.extend(extra)

    try:
        subprocess.run(
            args, capture_output=True, cwd=render_dir, timeout=600,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        if has_nonascii:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    tga = os.path.join(render_dir, tga_name)
    if not os.path.exists(tga):
        if has_nonascii:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    try:
        from PIL import Image
        img = Image.open(tga)
        if img.mode == 'RGBA':
            img.save(output_png, 'PNG')
        else:
            img.save(output_png)
    except ImportError:
        output_png = tga
        if has_nonascii:
            dst = os.path.splitext(cube_path)[0] + ".tga"
            shutil.copy2(tga, dst)
            output_png = dst

    for fn in ["vmdscene.dat", "_auto_render.tcl", tga_name]:
        fp = os.path.join(render_dir, fn)
        if os.path.exists(fp):
            os.remove(fp)
    if has_nonascii:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return output_png


# ── GUI ───────────────────────────────────────────────────
def launch_gui():
    import tkinter as tk
    from tkinter import filedialog, ttk, messagebox

    paths = load_config()

    class App:
        def __init__(self, root):
            self.root = root
            self.root.title("Orbital Isosurface Visualization v5 — Multiwfn + VMD/Tachyon (Multi-Orbital Support)")
            self.root.geometry("820x850")
            self.running = False

            self.vmd_port = None
            self.vmd_render_dir = None
            self.vmd_process = None
            self.vmd_cube_path = None
            self.vmd_multi_cubes = None

            # ── Path Settings ──
            frm0 = ttk.LabelFrame(root, text="Software Paths")
            frm0.pack(fill="x", padx=10, pady=(5, 2))

            r_paths = ttk.Frame(frm0); r_paths.pack(fill="x", padx=5, pady=2)
            ttk.Label(r_paths, text="Multiwfn:").pack(side="left")
            self.var_mw = tk.StringVar(value=paths["multiwfn"])
            ttk.Entry(r_paths, textvariable=self.var_mw, width=52).pack(
                side="left", fill="x", expand=True, padx=3)
            ttk.Button(r_paths, text="Browse", width=5,
                       command=lambda: self._browse_exe("multiwfn")).pack(side="left")

            r_paths2 = ttk.Frame(frm0); r_paths2.pack(fill="x", padx=5, pady=2)
            ttk.Label(r_paths2, text="VMD:").pack(side="left")
            self.var_vmd = tk.StringVar(value=paths["vmd"])
            ttk.Entry(r_paths2, textvariable=self.var_vmd, width=52).pack(
                side="left", fill="x", expand=True, padx=3)
            ttk.Button(r_paths2, text="Browse", width=5,
                       command=lambda: self._browse_exe("vmd")).pack(side="left")

            # ── File Selection ──
            frm1 = ttk.LabelFrame(root, text="Input")
            frm1.pack(fill="x", padx=10, pady=5)

            self.var_mode = tk.StringVar(value="file")
            ttk.Radiobutton(frm1, text="Folder", variable=self.var_mode,
                            value="folder").pack(side="left", padx=5)
            ttk.Radiobutton(frm1, text="Single File", variable=self.var_mode,
                            value="file").pack(side="left", padx=5)

            self.var_path = tk.StringVar()
            ttk.Entry(frm1, textvariable=self.var_path, width=55).pack(
                side="left", fill="x", expand=True, padx=5, pady=5)
            ttk.Button(frm1, text="Browse", command=self._browse).pack(
                side="right", padx=5, pady=5)

            # ── Parameters ──
            frm2 = ttk.LabelFrame(root, text="Parameters")
            frm2.pack(fill="x", padx=10, pady=5)

            r1 = ttk.Frame(frm2); r1.pack(fill="x", padx=5, pady=2)
            ttk.Label(r1, text="Orbital(s):").pack(side="left")
            self.var_orbital = tk.StringVar(value="h")
            orb_entry = ttk.Entry(r1, textvariable=self.var_orbital, width=25)
            orb_entry.pack(side="left", padx=5)
            ttk.Label(r1, text="(comma separated, e.g.: h,l,h-1,l+1)").pack(side="left")
            ttk.Label(r1, text="  Isosurface:").pack(side="left")
            self.var_iso = tk.StringVar(value="0.05")
            ttk.Entry(r1, textvariable=self.var_iso, width=7).pack(side="left", padx=5)

            r1b = ttk.Frame(frm2); r1b.pack(fill="x", padx=5, pady=2)
            ttk.Label(r1b, text="Quick:").pack(side="left")
            for txt, val in [
                ("H", "h"), ("L", "l"),
                ("H-1", "h-1"), ("L+1", "l+1"),
                ("H-2", "h-2"), ("L+2", "l+2"),
            ]:
                ttk.Button(r1b, text=txt, width=4,
                          command=lambda v=val: self._add_orbital(v)
                          ).pack(side="left", padx=1)
            ttk.Button(r1b, text="H+L", width=5,
                      command=lambda: self.var_orbital.set("h,l")).pack(side="left", padx=(10, 1))
            ttk.Button(r1b, text="H-1+H+L+L+1", width=12,
                      command=lambda: self.var_orbital.set("h-1,h,l,l+1")).pack(side="left", padx=1)
            ttk.Button(r1b, text="H-2+H-1+H+L+L+1+L+2", width=18,
                      command=lambda: self.var_orbital.set("h-2,h-1,h,l,l+1,l+2")).pack(side="left", padx=1)
            ttk.Label(r1b, text="  Grid:").pack(side="left", padx=(10, 0))
            self.var_grid = tk.StringVar(value="2")
            ttk.Combobox(r1b, textvariable=self.var_grid, width=3,
                         values=["1", "2", "3"], state="readonly"
                         ).pack(side="left", padx=5)
            ttk.Label(r1b, text="(1=low 2=medium 3=high)").pack(side="left")

            r_style = ttk.Frame(frm2); r_style.pack(fill="x", padx=5, pady=2)
            ttk.Label(r_style, text="Style:").pack(side="left")
            # Build style list: show "name - description"
            style_names = list(STYLES.keys())
            style_display = [f"{n}  ({STYLES[n]['desc']})" for n in style_names]
            self.var_style = tk.StringVar(value=style_display[0])
            self.style_combo = ttk.Combobox(r_style, textvariable=self.var_style,
                                            width=40, values=style_display, state="readonly")
            self.style_combo.pack(side="left", padx=5)
            # Default select sob-art
            self.style_combo.current(0)

            r2 = ttk.Frame(frm2); r2.pack(fill="x", padx=5, pady=2)
            ttk.Label(r2, text="Resolution:").pack(side="left")
            self.var_res = tk.StringVar(value="2000x1500")
            ttk.Combobox(r2, textvariable=self.var_res, width=12,
                         values=["2000x1500", "1200x900", "3000x2250"],
                         state="readonly"
                         ).pack(side="left", padx=5)
            self.var_shade = tk.StringVar(value="full")
            ttk.Label(r2, text="Shading:").pack(side="left", padx=(20, 0))
            for text, val in [("Full", "full"), ("Medium", "medium")]:
                ttk.Radiobutton(r2, text=text, variable=self.var_shade,
                                value=val).pack(side="left", padx=3)

            # Mode selection
            r3 = ttk.Frame(frm2); r3.pack(fill="x", padx=5, pady=2)
            self.var_auto = tk.BooleanVar(value=False)
            ttk.Checkbutton(r3, text="Auto render (no preview, batch mode)",
                            variable=self.var_auto).pack(side="left")
            self.var_open = tk.BooleanVar(value=False)
            ttk.Checkbutton(r3, text="Open folder after completion",
                            variable=self.var_open).pack(side="left", padx=20)

            # Tachyon parameters
            r4 = ttk.Frame(frm2); r4.pack(fill="x", padx=5, pady=2)
            self.var_trans_raster = tk.BooleanVar(value=True)
            ttk.Checkbutton(r4, text="-trans_vmd",
                            variable=self.var_trans_raster).pack(side="left")
            ttk.Label(r4, text="Threads:").pack(side="left", padx=(15, 0))
            self.var_threads = tk.StringVar(value="4")
            ttk.Combobox(r4, textvariable=self.var_threads, width=4,
                         values=["1", "2", "4", "8", "16", "28"], state="readonly"
                         ).pack(side="left", padx=5)

            # ── Output Directory ──
            frm3 = ttk.LabelFrame(root, text="Output Directory (default same as input)")
            frm3.pack(fill="x", padx=10, pady=5)
            self.var_out = tk.StringVar()
            ttk.Entry(frm3, textvariable=self.var_out, width=55).pack(
                side="left", fill="x", expand=True, padx=5, pady=5)
            ttk.Button(frm3, text="Browse", command=self._browse_out).pack(
                side="right", padx=5, pady=5)

            # ── Buttons ──
            frm4 = ttk.Frame(root); frm4.pack(fill="x", padx=10, pady=5)
            self.btn_run = ttk.Button(frm4, text="  Generate Cube  ", command=self._run)
            self.btn_run.pack(side="left", padx=5)
            self.btn_preview = ttk.Button(frm4, text="  Preview (Single)  ", command=self._preview,
                                          state="disabled")
            self.btn_preview.pack(side="left", padx=5)
            self.btn_preview_multi = ttk.Button(frm4, text="  Preview (Multi)  ", command=self._preview_multi,
                                               state="disabled")
            self.btn_preview_multi.pack(side="left", padx=5)
            self.btn_render = ttk.Button(frm4, text="  Render Current View  ", command=self._render_view,
                                         state="disabled")
            self.btn_render.pack(side="left", padx=5)
            self.btn_stop = ttk.Button(frm4, text="  Stop  ", command=self._stop,
                                       state="disabled")
            self.btn_stop.pack(side="left", padx=5)

            # ── Hide Hydrogen Atoms ──
            frm_h = ttk.LabelFrame(root, text="Hide Hydrogen (Available after Preview)")
            frm_h.pack(fill="x", padx=10, pady=5)

            f_h = ttk.Frame(frm_h); f_h.pack(fill="x", padx=5, pady=4)
            self.var_hide_h = tk.BooleanVar(value=False)
            self.var_h_indices = tk.StringVar(value="")
            self.btn_h_filter = ttk.Button(
                f_h, text="Hide All Hydrogens",
                command=self._toggle_h_filter, state="disabled")
            self.btn_h_filter.pack(side="left", padx=5)
            ttk.Label(f_h, text="Hydrogen indices to keep (comma separated, empty=hide all):").pack(side="left", padx=(10, 2))
            ttk.Entry(f_h, textvariable=self.var_h_indices, width=20).pack(side="left", padx=2)

            # ── Draw Dashed Line Settings ──
            frm5 = ttk.LabelFrame(root, text="Draw Dashed Line (Available after Preview)")
            frm5.pack(fill="x", padx=10, pady=5)

            self.bond_colors = {
                "Black": "black", "Gray": "gray", "Cyan": "cyan", "Yellow": "yellow",
                "Red": "red", "Blue": "blue", "Green": "green", "White": "white"}
            self.bond_types = {
                "Dashed(pymol)": "pymol", "Dots": "dots",
                "Cylinder": "cylinder", "Sphere": "sphere",
                "Arrow(cone)": "cone", "Line": "line"}
            self.bond_mats = {
                "Opaque": "Opaque", "50% Transparent": "HalfTransparent",
                "Transparent": "Transparent"}

            f_bond = ttk.Frame(frm5); f_bond.pack(fill="x", padx=5, pady=2)
            ttk.Label(f_bond, text="Atom 1:").pack(side="left")
            self.var_bond_atom1 = tk.StringVar(value="0")
            ttk.Entry(f_bond, textvariable=self.var_bond_atom1, width=6).pack(side="left", padx=2)
            ttk.Label(f_bond, text="Atom 2:").pack(side="left", padx=(8, 0))
            self.var_bond_atom2 = tk.StringVar(value="1")
            ttk.Entry(f_bond, textvariable=self.var_bond_atom2, width=6).pack(side="left", padx=2)

            ttk.Label(f_bond, text="Color:").pack(side="left", padx=(8, 0))
            self.var_bond_color = tk.StringVar(value="Gray")
            ttk.Combobox(f_bond, textvariable=self.var_bond_color, width=6,
                         values=list(self.bond_colors.keys()),
                         state="readonly").pack(side="left", padx=2)

            ttk.Label(f_bond, text="Type:").pack(side="left", padx=(8, 0))
            self.var_bond_type = tk.StringVar(value="Dots")
            ttk.Combobox(f_bond, textvariable=self.var_bond_type, width=10,
                         values=list(self.bond_types.keys()),
                         state="readonly").pack(side="left", padx=2)

            ttk.Label(f_bond, text="Material:").pack(side="left", padx=(8, 0))
            self.var_bond_mat = tk.StringVar(value="50% Transparent")
            ttk.Combobox(f_bond, textvariable=self.var_bond_mat, width=8,
                         values=list(self.bond_mats.keys()),
                         state="readonly").pack(side="left", padx=2)

            f_bond2 = ttk.Frame(frm5); f_bond2.pack(fill="x", padx=5, pady=2)
            ttk.Label(f_bond2, text="Segments:").pack(side="left")
            self.var_bond_nbars = tk.StringVar(value="10")
            ttk.Entry(f_bond2, textvariable=self.var_bond_nbars, width=5).pack(side="left", padx=2)
            ttk.Label(f_bond2, text="Spacing:").pack(side="left", padx=(6, 0))
            self.var_bond_space = tk.StringVar(value="1.2")
            ttk.Entry(f_bond2, textvariable=self.var_bond_space, width=5).pack(side="left", padx=2)
            ttk.Label(f_bond2, text="Radius:").pack(side="left", padx=(6, 0))
            self.var_bond_radius = tk.StringVar(value="0.06")
            ttk.Entry(f_bond2, textvariable=self.var_bond_radius, width=5).pack(side="left", padx=2)

            self.btn_draw_bond = ttk.Button(f_bond2, text="  Draw Line  ",
                                            command=self._draw_bond, state="disabled")
            self.btn_draw_bond.pack(side="left", padx=(12, 2))
            self.btn_undo_bond = ttk.Button(f_bond2, text="Undo", command=self._undo_bond,
                                            state="disabled")
            self.btn_undo_bond.pack(side="left", padx=2)
            self.btn_clear_bond = ttk.Button(f_bond2, text="Clear All", command=self._clear_bond,
                                              state="disabled")
            self.btn_clear_bond.pack(side="left", padx=2)

            # ── Progress ──
            self.var_prog = tk.StringVar(value="Ready")
            ttk.Label(root, textvariable=self.var_prog).pack(fill="x", padx=10)

            # ── Log ──
            self.log = tk.Text(root, height=6, font=("Consolas", 9),
                               bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
            self.log.pack(fill="both", expand=True, padx=10, pady=5)

            # ── Keyboard Shortcuts: Adjust isosurface and opacity in real-time ──
            self.current_iso = 0.05      # Current isovalue
            self.current_opacity = None   # Current opacity (None=style default)
            self.iso_step = 0.005
            self.opacity_step = 0.05

            root.bind("<Prior>", self._key_iso_up)       # PageUp
            root.bind("<Next>", self._key_iso_down)       # PageDown
            root.bind("<Home>", self._key_opacity_up)     # Home
            root.bind("<End>", self._key_opacity_down)    # End

        def _add_orbital(self, orb):
            """Add orbital to existing list (for quick buttons)"""
            current = self.var_orbital.get().strip()
            if not current:
                self.var_orbital.set(orb)
            else:
                orbs = [x.strip() for x in current.split(',') if x.strip()]
                if orb not in orbs:
                    orbs.append(orb)
                    self.var_orbital.set(','.join(orbs))

        def _get_orbitals(self):
            """Parse orbital input, supports comma-separated multiple orbitals"""
            orb_str = self.var_orbital.get().strip()
            if not orb_str:
                return []
            return [x.strip() for x in orb_str.split(',') if x.strip()]

        def _extract_orbital_name(self, cube_path):
            """Extract orbital name from cube filename (e.g., extract h from xxx_MOh.cub)"""
            basename = os.path.basename(cube_path)
            name_without_ext = os.path.splitext(basename)[0]
            if '_MO' in name_without_ext:
                return name_without_ext.rsplit('_MO', 1)[1]
            return name_without_ext

        def _get_style_name(self):
            """Get style name from combobox (remove description part)"""
            val = self.var_style.get().strip()
            if val:
                return val.split("  ")[0].strip()
            return "sob-art"

        def _browse_exe(self, which):
            if which == "multiwfn":
                p = filedialog.askopenfilename(title="Select Multiwfn.exe",
                    filetypes=[("Executable", "*.exe")])
                if p:
                    self.var_mw.set(p)
            elif which == "vmd":
                p = filedialog.askopenfilename(title="Select VMD Executable",
                    filetypes=[("Executable", "*.exe")])
                if p:
                    self.var_vmd.set(p)

        def _save_paths(self):
            vmd = self.var_vmd.get().strip()
            tachyon = find_tachyon(os.path.dirname(vmd))
            save_config(self.var_mw.get().strip(), vmd, tachyon)

        def _get_paths(self):
            vmd = self.var_vmd.get().strip()
            tachyon = find_tachyon(os.path.dirname(vmd))
            return {
                "multiwfn": self.var_mw.get().strip(),
                "vmd": vmd,
                "tachyon": tachyon,
            }

        def _browse(self):
            if self.var_mode.get() == "folder":
                p = filedialog.askdirectory(title="Select folder containing input files")
            else:
                p = filedialog.askopenfilename(
                    title="Select Input File",
                    filetypes=[
                        ("Formatted Checkpoint", "*.fchk"),
                        ("Molden File", "*.molden"),
                        ("Molden Input", "*.molden.input"),
                        ("Gaussian Cube", "*.cube"),
                        ("All Files", "*.*")])
            if p:
                self.var_path.set(p)

        def _browse_out(self):
            p = filedialog.askdirectory(title="Select Output Directory")
            if p:
                self.var_out.set(p)

        def _append(self, msg):
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.root.update_idletasks()

        def _get_params(self):
            orbitals = self._get_orbitals()
            orbital = orbitals[0] if orbitals else ""
            try:
                iso = float(self.var_iso.get().strip())
            except ValueError:
                iso = 0.05
            grid = self.var_grid.get().strip()
            style_name = self._get_style_name()
            try:
                res_str = self.var_res.get().strip()
                w, h = res_str.split("x")
                resolution = (int(w), int(h))
            except (ValueError, AttributeError):
                resolution = (2000, 1500)
            return orbital, iso, grid, style_name, resolution, self.var_shade.get()

        def _fchk_to_png_name(self, fchk_path, out_dir):
            orbital = self.var_orbital.get().strip()
            stem = os.path.splitext(os.path.basename(fchk_path))[0]
            return os.path.join(out_dir, f"{stem}_MO{orbital}.png")

        def _run(self):
            if self.running:
                return
            path = self.var_path.get().strip()
            if not path:
                messagebox.showwarning("Warning", "Please select file or folder first")
                return

            exe_paths = self._get_paths()
            if not os.path.exists(exe_paths["multiwfn"]):
                messagebox.showwarning("Path Error", f"Multiwfn not found:\n{exe_paths['multiwfn']}")
                return
            if not os.path.exists(exe_paths["vmd"]):
                messagebox.showwarning("Path Error", f"VMD not found:\n{exe_paths['vmd']}")
                return

            self._save_paths()

            files = (sorted(glob.glob(os.path.join(path, "*.fchk")))
                     if os.path.isdir(path) else [path])
            if not files:
                messagebox.showwarning("Warning", "No .fchk files found")
                return

            out = self.var_out.get().strip() or (
                path if os.path.isdir(path) else os.path.dirname(path))
            os.makedirs(out, exist_ok=True)

            orbital_str, iso, grid, style_name, resolution, shade_mode = self._get_params()
            orbitals = self._get_orbitals()
            if not orbitals:
                messagebox.showwarning("Warning", "Please enter orbital number first")
                return
            orbital = orbitals[0]

            auto = self.var_auto.get()
            do_open = self.var_open.get()
            is_multi = len(orbitals) > 1

            self.running = True
            self.btn_run.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.btn_preview.config(state="disabled")
            self.btn_preview_multi.config(state="disabled")
            self.btn_render.config(state="disabled")

            def worker():
                total = len(files)
                self._append(f"{total} files -> {out}")
                if is_multi:
                    self._append(f"Orbitals=[{','.join(orbitals)}]  iso={iso}  grid={grid}  Style={style_name}  res={resolution[0]}x{resolution[1]}")
                else:
                    self._append(f"Orbital={orbital}  iso={iso}  grid={grid}  Style={style_name}  res={resolution[0]}x{resolution[1]}")
                if auto:
                    self._append("Mode: Auto render (no preview)")
                else:
                    self._append("Mode: Generate cube -> Manual preview -> Render")
                self._append("=" * 50)
                ok = 0
                cubes = []
                t_total = time.time()
                for i, fchk in enumerate(files):
                    if not self.running:
                        self._append("Stopped"); break
                    name = os.path.basename(fchk)
                    self.var_prog.set(f"[{i+1}/{total}] {name}")
                    self._append(f"\n[{i+1}/{total}] {name}")

                    t0 = time.time()
                    if is_multi:
                        results = gen_multi_cubes(fchk, orbitals,
                                               grid_quality=int(grid), work_dir=out,
                                               multiwfn_exe=exe_paths["multiwfn"])
                        dt = time.time() - t0
                        if results:
                            for cube_path, orb_name in results:
                                self._append(f"  cube OK ({orb_name}) -> {os.path.basename(cube_path)}")
                                cubes.append((cube_path, orb_name))
                            ok += 1
                        else:
                            self._append(f"  Cube generation failed ({dt:.1f}s)")
                    else:
                        cube = gen_cube(fchk, orbital=orbital,
                                       grid_quality=int(grid), work_dir=out,
                                       multiwfn_exe=exe_paths["multiwfn"])
                        dt = time.time() - t0
                        if not cube:
                            self._append(f"  Cube failed ({dt:.1f}s)")
                            continue
                        self._append(f"  cube OK ({dt:.1f}s) -> {os.path.basename(cube)}")
                        cubes.append(cube)
                        ok += 1

                    if auto:
                        t0 = time.time()
                        try:
                            png = self._fchk_to_png_name(fchk, out)
                            render_cube_auto(cube if not is_multi else cubes[-1][0], output_png=png, isovalue=iso,
                                             style_name=style_name, resolution=resolution,
                                             vmd_exe=exe_paths["vmd"],
                                             tachyon_exe=exe_paths["tachyon"],
                                             shade_mode=shade_mode)
                            dt = time.time() - t0
                            self._append(f"  PNG: {os.path.basename(png)} ({dt:.1f}s)")
                        except Exception as e:
                            self._append(f"  Render error: {e}")

                elapsed = time.time() - t_total
                self._append(f"\nCube generation completed: {ok}/{total}, elapsed {elapsed:.1f}s")

                if not auto and cubes:
                    self._append("\nAfter adjusting view in VMD, click [Preview (Single)] / [Preview (Multi)] or [Render Current View]")
                    self.btn_preview.config(state="normal")
                    if is_multi:
                        self.btn_preview_multi.config(state="normal")

                if auto:
                    self._append(f"\nAll completed {ok}/{total}")
                    self.var_prog.set(f"Completed: {ok}/{total}")
                    if do_open and ok > 0:
                        os.startfile(out)

                self.running = False
                self.btn_run.config(state="normal")
                self.btn_stop.config(state="disabled")

            threading.Thread(target=worker, daemon=True).start()

        def _preview(self):
            path = self.var_path.get().strip()
            out = self.var_out.get().strip() or (
                path if os.path.isdir(path) else os.path.dirname(path))

            cubes = sorted(glob.glob(os.path.join(out, "*.cub")))
            if not cubes:
                messagebox.showwarning("Warning", "No .cub files in output directory")
                return

            if os.path.isfile(path):
                stem = os.path.splitext(os.path.basename(path))[0]
                target = [c for c in cubes if stem in c]
                if target:
                    cubes = target

            if len(cubes) == 1:
                cube_path = cubes[0]
            else:
                import tkinter as tk
                from tkinter import simpledialog, messagebox

                class CubeSelector(tk.Toplevel):
                    def __init__(self, parent, cubes):
                        super().__init__(parent)
                        self.title("Select cube file to preview")
                        self.geometry("500x400")
                        self.result = None

                        frame = tk.Frame(self, padx=10, pady=10)
                        frame.pack(fill="both", expand=True)

                        tk.Label(frame, text="Select cube file to preview:").pack(anchor="w", pady=5)

                        self.listbox = tk.Listbox(frame, width=60, height=15)
                        self.listbox.pack(fill="both", expand=True)
                        for cube in cubes:
                            self.listbox.insert(tk.END, os.path.basename(cube))
                        self.listbox.bind("<Double-1>", self.on_select)
                        self.listbox.selection_set(0)

                        btn_frame = tk.Frame(frame)
                        btn_frame.pack(fill="x", pady=10)
                        tk.Button(btn_frame, text="OK", command=self.on_select).pack(side="right", padx=5)
                        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right")

                        self.transient(parent)
                        self.grab_set()

                    def on_select(self, event=None):
                        selection = self.listbox.curselection()
                        if selection:
                            self.result = cubes[selection[0]]
                            self.destroy()

                selector = CubeSelector(self.root, cubes)
                self.root.wait_window(selector)
                if selector.result:
                    cube_path = selector.result
                else:
                    return

            self.vmd_cube_path = cube_path
            orbital, iso, grid, style_name, resolution, shade_mode = self._get_params()
            exe_paths = self._get_paths()

            # Parse hydrogen hiding configuration
            h_str = self.var_h_indices.get().strip()
            if self.var_hide_h.get() or h_str:
                if h_str:
                    try:
                        keep_h_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                    except ValueError:
                        keep_h_indices = []
                else:
                    keep_h_indices = []
            else:
                keep_h_indices = None

            # Sync current values for keyboard adjustment
            self.current_iso = iso
            self.current_opacity = None  # Reset, will read style default on next Home/End

            self._append(f"\nStarting VMD preview: {os.path.basename(cube_path)}")
            self._append(f"Style: {style_name}")
            self._append("Adjust view in VMD, then click [Render Current View]")

            try:
                port, render_dir = preview_cube(cube_path, isovalue=iso,
                                                style_name=style_name,
                                                vmd_exe=exe_paths["vmd"],
                                                shade_mode=shade_mode,
                                                keep_h_indices=keep_h_indices)
                if port:
                    self.vmd_port = port
                    self.vmd_render_dir = render_dir
                    self.btn_render.config(state="normal")
                    self.btn_draw_bond.config(state="normal")
                    self.btn_undo_bond.config(state="normal")
                    self.btn_clear_bond.config(state="normal")
                    self.btn_h_filter.config(state="normal")
                    self._current_iso = iso
                    self._current_style_name = style_name
                    self._append(f"VMD started (port {port}), waiting for operations...")
                else:
                    self._append("VMD start failed")
            except Exception as e:
                self._append(f"VMD start error: {e}")

        def _preview_multi(self):
            """Preview isosurfaces of multiple orbitals"""
            path = self.var_path.get().strip()
            out = self.var_out.get().strip() or (
                path if os.path.isdir(path) else os.path.dirname(path))

            all_cubes = sorted(glob.glob(os.path.join(out, "*_MO*.cub")))
            if not all_cubes:
                messagebox.showwarning("Warning", "No orbital cube files found in output directory\nPlease click [Generate Cube] first")
                return

            if len(all_cubes) == 1:
                cube_path = all_cubes[0]
                cubes = [(cube_path, self._extract_orbital_name(cube_path))]
            else:
                import tkinter as tk
                from tkinter import messagebox

                class MultiCubeSelector(tk.Toplevel):
                    def __init__(self, parent, cubes):
                        super().__init__(parent)
                        self.title("Select orbitals to preview")
                        self.geometry("500x450")
                        self.result = None
                        self.cubes = cubes  

                        frame = tk.Frame(self, padx=10, pady=10)
                        frame.pack(fill="both", expand=True)

                        tk.Label(frame, text="Select orbitals to preview (multi-select with Ctrl or Shift):").pack(anchor="w", pady=5)

                        self.listbox = tk.Listbox(frame, width=60, height=15, selectmode="extended")
                        self.listbox.pack(fill="both", expand=True)
                        for cube in cubes:
                            self.listbox.insert(tk.END, os.path.basename(cube))
                        self.listbox.selection_set(0, len(cubes)-1)

                        btn_frame = tk.Frame(frame)
                        btn_frame.pack(fill="x", pady=10)
                        tk.Button(btn_frame, text="Select All", command=self.select_all).pack(side="left", padx=5)
                        tk.Button(btn_frame, text="Invert", command=self.select_invert).pack(side="left", padx=5)
                        tk.Button(btn_frame, text="OK", command=self.on_select).pack(side="right", padx=5)
                        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right")

                        self.transient(parent)
                        self.grab_set()

                    def select_all(self):
                        self.listbox.select_set(0, tk.END)

                    def select_invert(self):
                        for i in range(self.listbox.size()):
                            if self.listbox.selection_includes(i):
                                self.listbox.selection_clear(i)
                            else:
                                self.listbox.selection_set(i)

                    def on_select(self):
                        selection = self.listbox.curselection()
                        if selection:
                            self.result = [self.cubes[i] for i in selection]
                            self.destroy()

                selector = MultiCubeSelector(self.root, all_cubes)
                self.root.wait_window(selector)
                if not selector.result:
                    return

                cubes = [(cube, self._extract_orbital_name(cube)) for cube in selector.result]

            orbitals = [orb for _, orb in cubes]

            try:
                iso = float(self.var_iso.get().strip())
            except ValueError:
                iso = 0.05

            style_name = self._get_style_name()
            shade_mode = self.var_shade.get()
            # Bug fix: Correctly parse resolution string
            try:
                res_str = self.var_res.get().strip()
                res_w, res_h = res_str.split("x")
                resolution = (int(res_w), int(res_h))
            except (ValueError, AttributeError):
                resolution = (2000, 1500)
            exe_paths = self._get_paths()

            # Parse hydrogen hiding configuration
            h_str = self.var_h_indices.get().strip()
            if self.var_hide_h.get() or h_str:
                if h_str:
                    try:
                        keep_h_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                    except ValueError:
                        keep_h_indices = []
                else:
                    keep_h_indices = []
            else:
                keep_h_indices = None

            self.current_iso = iso
            self.current_opacity = None

            orb_names = ", ".join([orb for _, orb in cubes])
            self._append(f"\nStarting VMD multi-orbital preview: {orb_names}")
            self._append(f"Style: {style_name}, Isovalue: {iso}")
            self._append("Adjust view in VMD, then click [Render Current View]")

            try:
                port, render_dir, copied_cubes = preview_multi_cubes(
                    cubes, iso, style_name=style_name,
                    vmd_exe=exe_paths["vmd"], shade_mode=shade_mode,
                    keep_h_indices=keep_h_indices)
                if port:
                    self.vmd_port = port
                    self.vmd_render_dir = render_dir
                    self.vmd_multi_cubes = copied_cubes
                    self.btn_render.config(state="normal")
                    self.btn_draw_bond.config(state="normal")
                    self.btn_undo_bond.config(state="normal")
                    self.btn_clear_bond.config(state="normal")
                    self.btn_h_filter.config(state="normal")
                    self._current_iso = iso
                    self._current_style_name = style_name
                    self._append(f"VMD started (port {port}), waiting for operations...")
                else:
                    self._append("VMD start failed")
            except Exception as e:
                self._append(f"VMD start error: {e}")

        def _render_view(self):
            if not self.vmd_port or not self.vmd_render_dir:
                messagebox.showwarning("Warning", "Please click [Preview] to open VMD first")
                return

            out = self.var_out.get().strip()
            if out and not os.path.isdir(out):
                os.makedirs(out, exist_ok=True)

            _, _, _, style_name, resolution, shade_mode = self._get_params()
            exe_paths = self._get_paths()

            # Generate output filename: same as fchk filename
            output_png = None
            if self.vmd_cube_path:
                cube_stem = os.path.splitext(os.path.basename(self.vmd_cube_path))[0]
                fchk_name = cube_stem.rsplit("_MO", 1)[0]
                orbital = self.var_orbital.get().strip()
                output_png = os.path.join(out, f"{fchk_name}_MO{orbital}.png") if out else None
            elif self.vmd_multi_cubes and self.vmd_multi_cubes[0][0]:
                # Multi-orbital mode: use fchk name from first cube file
                cube_stem = os.path.splitext(os.path.basename(self.vmd_multi_cubes[0][0]))[0]
                fchk_name = cube_stem.rsplit("_MO", 1)[0]
                orbitals = self._get_orbitals()
                orbital_suffix = "_".join(orbitals) if orbitals else "multi"
                output_png = os.path.join(out, f"{fchk_name}_MO{orbital_suffix}.png") if out else None

            # Get Tachyon parameters
            trans_raster = self.var_trans_raster.get()
            threads = int(self.var_threads.get())

            def render_worker():
                self.btn_render.config(state="disabled")
                self._append(f"\nRendering current view (Style: {style_name})...")
                t0 = time.time()
                try:
                    png = render_current_view(
                        self.vmd_port, self.vmd_render_dir,
                        output_png=output_png,
                        tachyon_exe=exe_paths["tachyon"],
                        resolution=resolution, style_name=style_name,
                        shade_mode=shade_mode,
                        trans_raster=trans_raster,
                        threads=threads,
                    )
                    dt = time.time() - t0
                    if png:
                        self._append(f"Render completed ({dt:.1f}s) -> {os.path.basename(png)}")
                        os.startfile(png)
                    else:
                        self._append(f"Render failed ({dt:.1f}s)")
                except Exception as e:
                    self._append(f"Render error: {e}")
                self.btn_render.config(state="normal")

            threading.Thread(target=render_worker, daemon=True).start()

        def _stop(self):
            self.running = False
            self.btn_stop.config(state="disabled")

        def _toggle_h_filter(self):
            """Toggle hydrogen show/hide (Send TCL command in preview mode)
            Principle: Use mol modselect 0 molID "..." to control only atom representation (rep 0),
            without affecting isosurface (representation 1/2), avoiding cube data loss during pdb conversion.
            In multi-orbital mode, iterate through all molecule IDs.
            """
            if not hasattr(self, 'vmd_port') or not self.vmd_port:
                self._append("Please click preview button to start VMD first")
                return

            self.var_hide_h.set(not self.var_hide_h.get())
            if self.var_hide_h.get():
                self.btn_h_filter.config(text="Show All Hydrogens")
                # Build selection string: rep 0 shows only non-hydrogen (or keep specified hydrogens)
                h_str = self.var_h_indices.get().strip()
                if h_str:
                    try:
                        keep_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                        idx_str = " ".join(map(str, keep_indices))
                        sel_str = f"not element H or (element H and index {idx_str})"
                    except ValueError:
                        sel_str = "not element H"
                else:
                    sel_str = "not element H"
                # Iterate through all molecule IDs, execute modselect on rep 0 for each
                cmd = (
                    f'foreach mid [molinfo list] {{'
                    f'  mol modselect 0 $mid "{sel_str}"'
                    f'}}'
                )
                self._send_vmd_cmd(cmd)
                self._append("[Hide H] Hid hydrogens for all molecules")
            else:
                self.btn_h_filter.config(text="Hide All Hydrogens")
                # Restore: rep 0 shows all atoms for all molecules
                cmd = 'foreach mid [molinfo list] { mol modselect 0 $mid all }'
                self._send_vmd_cmd(cmd)
                self._append("[Hide H] Restored hydrogens for all molecules")

        def _send_vmd_cmd(self, cmd):
            """Send a TCL command to VMD via socket and return response."""
            if not self.vmd_port:
                return None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect(("127.0.0.1", self.vmd_port))
                sock.sendall((cmd + "\n").encode("utf-8"))
                time.sleep(0.2)
                resp = b""
                sock.settimeout(2)
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        resp += chunk
                        if b"\n" in resp:
                            break
                except socket.timeout:
                    pass
                sock.close()
                return resp.decode("utf-8", errors="replace").strip()
            except Exception:
                return None

        def _key_iso_up(self, event=None):
            """PageUp: Increase isovalue"""
            self.current_iso = round(min(self.current_iso + self.iso_step, 0.5), 4)
            self._apply_iso_change()

        def _key_iso_down(self, event=None):
            """PageDown: Decrease isovalue"""
            self.current_iso = round(max(self.current_iso - self.iso_step, 0.005), 4)
            self._apply_iso_change()

        def _key_opacity_up(self, event=None):
            """Home: Increase opacity (more opaque)"""
            if self.current_opacity is None:
                # First Home/End press, read current style's opacity as baseline
                style = STYLES.get(self._get_style_name(), STYLES["sob-art"])
                self.current_opacity = style["surface_mat"][5]
            self.current_opacity = round(min(self.current_opacity + self.opacity_step, 1.0), 2)
            self._apply_opacity_change()

        def _key_opacity_down(self, event=None):
            """End: Decrease opacity (more transparent)"""
            if self.current_opacity is None:
                style = STYLES.get(self._get_style_name(), STYLES["sob-art"])
                self.current_opacity = style["surface_mat"][5]
            self.current_opacity = round(max(self.current_opacity - self.opacity_step, 0.05), 2)
            self._apply_opacity_change()

        def _apply_iso_change(self):
            """Send TCL command to update isosurface, sync GUI."""
            iso = self.current_iso
            self.var_iso.set(f"{iso:.4g}")
            # Update positive/negative isosurfaces (mol modstyle 1/2 top Isosurface ±value ...)
            cmd = f"mol modstyle 1 top Isosurface {iso} 0 0 0 1 1"
            resp1 = self._send_vmd_cmd(cmd)
            cmd = f"mol modstyle 2 top Isosurface -{iso} 0 0 0 1 1"
            resp2 = self._send_vmd_cmd(cmd)
            status = "OK" if resp1 and "ERROR" not in (resp1 + (resp2 or "")) else "VMD not connected"
            self._append(f"[Isosurface] iso = {iso:.4g}  ({status})")

        def _apply_opacity_change(self):
            """Send TCL command to update opacity, sync GUI."""
            op = self.current_opacity
            # Update material opacity for both positive and negative isosurfaces
            for mat_name in ["_stl_a", "_stl_b"]:
                cmd = f"material change opacity {mat_name} {op}"
                self._send_vmd_cmd(cmd)
            self._append(f"[Opacity] opacity = {op:.2f}")

        def _draw_bond(self):
            """Draw dashed line: draw connection between two atoms"""
            if not self.vmd_port:
                messagebox.showwarning("Warning", "Please click [Preview] to open VMD first")
                return
            a1 = self.var_bond_atom1.get().strip()
            a2 = self.var_bond_atom2.get().strip()
            if not a1 or not a2:
                messagebox.showwarning("Warning", "Please enter two atom indices")
                return
            color = self.bond_colors.get(self.var_bond_color.get(), "gray")
            btype = self.bond_types.get(self.var_bond_type.get(), "dots")
            mat = self.bond_mats.get(self.var_bond_mat.get(), "HalfTransparent")
            nbars = self.var_bond_nbars.get().strip() or "10"
            space = self.var_bond_space.get().strip() or "1.2"
            radius = self.var_bond_radius.get().strip() or "0.06"

            if btype == "cylinder":
                cmd = (f"draw_bond -mol1 top -index1 {a1} -mol2 top -index2 {a2} "
                       f"-color {color} -h_type {btype} -h_radius {radius} -mat {mat}")
            else:
                cmd = (f"draw_bond -mol1 top -index1 {a1} -mol2 top -index2 {a2} "
                       f"-h_nbars {nbars} -h_space {space} -h_radius {radius} "
                       f"-color {color} -h_type {btype} -mat {mat}")
            resp = self._send_vmd_cmd(cmd)
            if resp and "ERROR" not in resp:
                self._append(f"[Draw Bond] Atom{a1}-{a2} {color} {btype} {mat}")
                self.btn_undo_bond.config(state="normal")
            else:
                self._append("[Draw Bond] Failed")

        def _undo_bond(self):
            """Undo last drawn bond"""
            resp = self._send_vmd_cmd("draw_bond_undo")
            if resp and "ERROR" not in resp:
                self._append("[Bond] Undo")
            else:
                self._append("[Bond] Undo failed")

        def _clear_bond(self):
            """Clear all drawn bonds"""
            resp = self._send_vmd_cmd("draw_bond_clear")
            if resp and "ERROR" not in resp:
                self._append("[Bond] Cleared all")
            else:
                self._append("[Bond] Clear failed")

    root = tk.Tk()
    App(root)
    root.mainloop()


# ── Command Line Entry ────────────────────────────────────
def main():
    if len(sys.argv) > 1:
        import argparse
        p = argparse.ArgumentParser(description="Multiwfn + VMD/Tachyon Orbital Isosurface Visualization v4")
        p.add_argument("input", help="fchk file or folder")
        p.add_argument("--mo", default="h", help="Orbital (h/l/h-1/number)")
        p.add_argument("--iso", type=float, default=0.05, help="Isosurface threshold")
        p.add_argument("--grid", default="2", help="Grid quality (1/2/3)")
        p.add_argument("--style", default="sob-art",
                       choices=list(STYLES.keys()), help="Render style")
        p.add_argument("--res", default="2000,1500", help="Resolution width,height")
        p.add_argument("--no-render", action="store_true", help="Generate cube only, skip rendering")
        p.add_argument("--out", default=None)
        a = p.parse_args()

        files = sorted(glob.glob(os.path.join(a.input, "*.fchk"))) if os.path.isdir(a.input) else [a.input]
        out = a.out or (os.path.dirname(a.input) if os.path.isfile(a.input) else a.input)
        os.makedirs(out, exist_ok=True)

        w, h = [int(x) for x in a.res.split(",")]

        for i, f in enumerate(files):
            print(f"[{i+1}/{len(files)}] {os.path.basename(f)}")
            cube = gen_cube(f, orbital=a.mo, grid_quality=int(a.grid), work_dir=out)
            if cube:
                print(f"  cube: {os.path.basename(cube)}")
                if not a.no_render:
                    png = render_cube_auto(cube, isovalue=a.iso,
                                           style_name=a.style, resolution=(w, h))
                    if png:
                        print(f"  png:  {os.path.basename(png)}")
            else:
                print(f"  Failed")
    else:
        launch_gui()


if __name__ == "__main__":
    main()


