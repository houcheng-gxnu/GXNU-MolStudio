# -*- coding: utf-8 -*-
"""
Configuration — NOCV styles, atom radii, colors, element symbols, stylesheet.
"""

import os

DEFAULT_MULTIWFN = r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe"
DEFAULT_VMD = r"C:\Program Files (x86)\University of Illinois\VMD\vmd.exe"
DEFAULT_TACHYON = r"C:\Program Files (x86)\University of Illinois\VMD\tachyon_WIN32.exe"

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ets_nocv_config.json"
)

NOCV_STYLES = {
    # ── IboView Style Light Effects ──────────────────────────
    "blue-red": {
        "desc": "IboView High-Glossy, Blue-Red",
        "tachyon_options": "-trans_raster3d",
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
    "cyan-pink": {
        "desc": "IboView Crystal, Cyan-Pink",
        "tachyon_options": "-trans_raster3d",
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
    "purple-orange": {
        "desc": "IboView Dark, Purple-Orange",
        "tachyon_options": "-trans_raster3d",
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
    # ── IboView Multi-Orbital Color Styles ─────────────────────
    "green-pink": {
        "desc": "IboView Green-Pink, Classic Dual",
        "tachyon_options": "-trans_raster3d",
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
    "purple-blue": {
        "desc": "IboView Purple-Blue, Mystic Texture",
        "tachyon_options": "-trans_raster3d",
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
    "cyan-yellow": {
        "desc": "IboView Cyan-Yellow, Bright Contrast",
        "tachyon_options": "-trans_raster3d",
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
    "orange-teal": {
        "desc": "IboView Orange-Teal, Warm Contrast",
        "tachyon_options": "-trans_raster3d",
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
    "red-green": {
        "desc": "IboView Red-Green, Classic Complementary",
        "tachyon_options": "-trans_raster3d",
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
    "magenta-blue": {
        "desc": "IboView Rainbow, Colorful Effect",
        "tachyon_options": "-trans_raster3d",
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
    "teal-coral": {
        "desc": "Aurora Teal / Coral Pink, Nordic Glass",
        "tachyon_options": "-trans_raster3d",
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
    "indigo-gold": {
        "desc": "Midnight Indigo / Amber Gold, Journal Quality",
        "tachyon_options": "-trans_raster3d -shadow_filter_off",
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
        "tachyon_options": "-trans_raster3d",
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
    "orange-violet": {
        "desc": "Warm Orange / Deep Blue-Violet, Dramatic Sky",
        "tachyon_options": "-trans_raster3d",
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
    "blue-seafoam": {
        "desc": "Deep Ocean Blue / Seafoam Green, Calm Depth",
        "tachyon_options": "-trans_raster3d",
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
    "rose-slate": {
        "desc": "Rose Quartz Pink / Slate Blue, Pantone Duo",
        "tachyon_options": "-trans_raster3d",
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
    "emerald-copper": {
        "desc": "Emerald Green / Copper Brown, Forest Metal",
        "tachyon_options": "-trans_raster3d",
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
    "violet-cyan": {
        "desc": "Electric Violet / Neon Cyan, Cyberpunk Glow",
        "tachyon_options": "-trans_raster3d",
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
    "pink-blue": {
        "desc": "Sakura Pink / Baby Blue, Japanese Airy",
        "tachyon_options": "-trans_raster3d",
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
    "graphite-red": {
        "desc": "Graphite Black / Vermillion Red, Ink Wash Minimal",
        "tachyon_options": "-trans_raster3d -shadow_filter_off",
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
    "crimson-teal": {
        "desc": "Crimson Red-Orange / Deep Teal, Visceral Contrast",
        "tachyon_options": "-trans_raster3d",
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
    "champagne-purple": {
        "desc": "Pale Champagne / Deep Cosmos Purple, Celestial",
        "tachyon_options": "-trans_raster3d",
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
    "ice-navy": {
        "desc": "Ice Crystal Blue / Midnight Navy, Cryogenic Cold",
        "tachyon_options": "-trans_raster3d -shadow_filter_off",
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
        "tachyon_options": "-trans_raster3d",
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
    "plum-gold": {
        "desc": "Deep Plum Purple / Golden Champagne, Luxury Wine",
        "tachyon_options": "-trans_raster3d",
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
}

ATOM_RADII = {
    'H': 0.31, 'He': 0.28, 'Li': 1.28, 'Be': 0.96, 'B': 0.84,
    'C': 0.76, 'N': 0.71, 'O': 0.66, 'F': 0.57, 'Ne': 0.58,
    'Na': 1.66, 'Mg': 1.41, 'Al': 1.21, 'Si': 1.11, 'P': 1.07,
    'S': 1.05, 'Cl': 1.02, 'Ar': 1.06, 'K': 2.03, 'Ca': 1.76,
    'Sc': 1.7, 'Ti': 1.6, 'V': 1.53, 'Cr': 1.39, 'Mn': 1.39,
    'Fe': 1.32, 'Co': 1.26, 'Ni': 1.24, 'Cu': 1.32, 'Zn': 1.22,
    'Ga': 1.22, 'Ge': 1.2, 'As': 1.19, 'Se': 1.2, 'Br': 1.2,
    'Kr': 1.16, 'Rb': 2.2, 'Sr': 1.95, 'Y': 1.9, 'Zr': 1.75,
    'Nb': 1.64, 'Mo': 1.54, 'Tc': 1.47, 'Ru': 1.46, 'Rh': 1.42,
    'Pd': 1.39, 'Ag': 1.45, 'Cd': 1.44, 'In': 1.42, 'Sn': 1.39,
    'Sb': 1.39, 'Te': 1.38, 'I': 1.39, 'Xe': 1.4, 'Cs': 2.44,
    'Ba': 2.15, 'La': 2.07, 'Ce': 2.04, 'Pr': 2.03, 'Nd': 2.01,
    'Pm': 1.99, 'Sm': 1.98, 'Eu': 1.98, 'Gd': 1.96, 'Tb': 1.94,
    'Dy': 1.92, 'Ho': 1.92, 'Er': 1.89, 'Tm': 1.9, 'Yb': 1.87,
    'Lu': 1.87, 'Hf': 1.75, 'Ta': 1.7, 'W': 1.62, 'Re': 1.51,
    'Os': 1.44, 'Ir': 1.41, 'Pt': 1.36, 'Au': 1.36, 'Hg': 1.32,
    'Tl': 1.45, 'Pb': 1.46, 'Bi': 1.48, 'Po': 1.4, 'At': 1.5,
    'Rn': 1.5, 'Fr': 2.6, 'Ra': 2.21, 'Ac': 2.15, 'Th': 2.06,
    'Pa': 2.0, 'U': 1.96, 'Np': 1.9, 'Pu': 1.87, 'Am': 1.8,
    'Cm': 1.69, 'Bk': 2.0, 'Cf': 2.0, 'Es': 2.0, 'Fm': 2.0,
    'Md': 2.0, 'No': 2.0, 'Lr': 2.0,
}

ATOM_COLORS = {
    'H': '#CCCCCC', 'He': '#D8FFFF', 'Li': '#CC7CFF', 'Be': '#CCFF00',
    'B': '#FFB4B4', 'C': '#8E8E8E', 'N': '#1818E4', 'O': '#E40000',
    'F': '#B1FFFF', 'Ne': '#AFE2F4', 'Na': '#AA5BF1', 'Mg': '#B1CC00',
    'Al': '#D0A5A5', 'Si': '#7E9999', 'P': '#FF7E00', 'S': '#FFC628',
    'Cl': '#18EF18', 'Ar': '#7ED0E2', 'K': '#8E3FD3', 'Ca': '#999900',
    'Sc': '#E4E4E2', 'Ti': '#BEC1C6', 'V': '#A5A5AA', 'Cr': '#8999C6',
    'Mn': '#9A79C6', 'Fe': '#7E79C6', 'Co': '#5B6DFF', 'Ni': '#5B79C1',
    'Cu': '#FF7960', 'Zn': '#7C7EAF', 'Ga': '#C18E8E', 'Ge': '#668E8E',
    'As': '#BC7EE2', 'Se': '#FFA000', 'Br': '#A52020', 'Kr': '#5BB9D0',
    'Rb': '#6F2DAF', 'Sr': '#7E6600', 'Y': '#93FBFF', 'Zr': '#93DFDF',
    'Nb': '#72C1C8', 'Mo': '#53B4B4', 'Tc': '#3A9DA7', 'Ru': '#238E95',
    'Rh': '#097C8B', 'Pd': '#006783', 'Ag': '#99C6FF', 'Cd': '#FFD88E',
    'In': '#A57472', 'Sn': '#667E7E', 'Sb': '#9D62B4', 'Te': '#D37900',
    'I': '#930093', 'Xe': '#419DAF', 'Cs': '#56168E', 'Ba': '#663300',
    'La': '#6FDDFF', 'Ce': '#FFFFC6', 'Pr': '#D8FFC6', 'Nd': '#C6FFC6',
    'Pm': '#A2FFC6', 'Sm': '#8EFFC6', 'Eu': '#60FFC6', 'Gd': '#44FFC6',
    'Tb': '#2FFFC6', 'Dy': '#1DFFB4', 'Ho': '#00FFB4', 'Er': '#00E474',
    'Tm': '#00D350', 'Yb': '#00BE37', 'Lu': '#00AA23', 'Hf': '#4BC1FF',
    'Ta': '#4BA5FF', 'W': '#2593D5', 'Re': '#257CAA', 'Os': '#256695',
    'Ir': '#165386', 'Pt': '#165B8E', 'Au': '#FFD023', 'Hg': '#B4B4C1',
    'Tl': '#A5534B', 'Pb': '#565860', 'Bi': '#9D4EB4', 'Po': '#AA5B00',
    'At': '#744E44', 'Rn': '#418195', 'Fr': '#410066', 'Ra': '#4B1800',
    'Ac': '#6FAAF9', 'Th': '#00B9FF', 'Pa': '#00A0FF', 'U': '#008EFF',
    'Np': '#007EF1', 'Pu': '#006AF1', 'Am': '#535BF1', 'Cm': '#775BE2',
    'Bk': '#895DE2', 'Cf': '#A034D3', 'Es': '#A72AC6', 'Fm': '#B11DB9',
    'Md': '#B10CA5', 'No': '#BC0C86', 'Lr': '#C60066', 'Rf': '#FF7E7E',
    'Db': '#E46666', 'Sg': '#CC4B4B', 'Bh': '#B13333', 'Hs': '#991818',
    'Mt': '#8B0000', 'Ds': '#7E0000', 'Rg': '#720000',
}

ELEMENT_SYMBOLS = {
    1: 'H', 2: 'He', 3: 'Li', 4: 'Be', 5: 'B', 6: 'C', 7: 'N', 8: 'O', 9: 'F', 10: 'Ne',
    11: 'Na', 12: 'Mg', 13: 'Al', 14: 'Si', 15: 'P', 16: 'S', 17: 'Cl', 18: 'Ar',
    19: 'K', 20: 'Ca', 21: 'Sc', 22: 'Ti', 23: 'V', 24: 'Cr', 25: 'Mn', 26: 'Fe',
    27: 'Co', 28: 'Ni', 29: 'Cu', 30: 'Zn', 31: 'Ga', 32: 'Ge', 33: 'As', 34: 'Se',
    35: 'Br', 36: 'Kr', 37: 'Rb', 38: 'Sr', 39: 'Y', 40: 'Zr', 41: 'Nb', 42: 'Mo',
    43: 'Tc', 44: 'Ru', 45: 'Rh', 46: 'Pd', 47: 'Ag', 48: 'Cd', 49: 'In', 50: 'Sn',
    51: 'Sb', 52: 'Te', 53: 'I', 54: 'Xe', 55: 'Cs', 56: 'Ba', 57: 'La', 58: 'Ce',
    59: 'Pr', 60: 'Nd', 61: 'Pm', 62: 'Sm', 63: 'Eu', 64: 'Gd', 65: 'Tb', 66: 'Dy',
    67: 'Ho', 68: 'Er', 69: 'Tm', 70: 'Yb', 71: 'Lu', 72: 'Hf', 73: 'Ta', 74: 'W',
    75: 'Re', 76: 'Os', 77: 'Ir', 78: 'Pt', 79: 'Au', 80: 'Hg', 81: 'Tl', 82: 'Pb',
    83: 'Bi', 84: 'Po', 85: 'At', 86: 'Rn', 87: 'Fr', 88: 'Ra', 89: 'Ac', 90: 'Th',
    91: 'Pa', 92: 'U', 93: 'Np', 94: 'Pu', 95: 'Am', 96: 'Cm', 97: 'Bk', 98: 'Cf',
    99: 'Es', 100: 'Fm', 101: 'Md', 102: 'No', 103: 'Lr', 104: 'Rf', 105: 'Db',
    106: 'Sg', 107: 'Bh', 108: 'Hs', 109: 'Mt', 110: 'Ds', 111: 'Rg',
}

VMD_ATOM_COLORS = r"""color Element H white
color Element S yellow
color change rgb 4  1.000000 0.800000 0.000000
color Element F yellow2
color change rgb 17  0.800000 1.000000 0.000000
color Element Cl yellow3
color change rgb 18  0.500000 1.000000 0.000000
color Element Br magenta2
color change rgb 28  0.900000 0.100000 0.000000
color Element I magenta
color change rgb 27  0.700000 0.000000 0.700000
color Element B pink
color change rgb 9   1.000000 0.400000 0.800000
color Element P red2
color change rgb 29  1.000000 0.400000 0.000000
color Element C tan
color change rgb tan 0.700000 0.560000 0.360000

# Metal elements GaussView color scheme (ColorID = atomic number + 100)
color change rgb 103 0.8000 0.4863 1.0000
color change rgb 104 0.8000 1.0000 0.0000
color change rgb 111 0.6667 0.3569 0.9490
color change rgb 112 0.6980 0.8000 0.0000
color change rgb 113 0.8196 0.6471 0.6471
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
color Element Li 103
color Element Be 104
color Element Na 111
color Element Mg 112
color Element Al 113
color Element K 119
color Element Ca 120
color Element Sc 121
color Element Ti 122
color Element V 123
color Element Cr 124
color Element Mn 125
color Element Fe 126
color Element Co 127
color Element Ni 128
color Element Cu 129
color Element Zn 130
color Element Ga 131
color Element Rb 137
color Element Sr 138
color Element Y 139
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
color Element W 174
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
color Element Fr 187
color Element Ra 188
color Element Ac 189
color Element Th 190
color Element Pa 191
color Element U 192
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

LIGHT_QSS = """
QMainWindow {
    background-color: #E4EAF2;
}

QWidget {
    font-family: "Segoe UI", "Microsoft YaHei", "Consolas", sans-serif;
    font-size: 9pt;
    color: #2C3E50;
}

QGroupBox {
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    margin-top: 16px;
    padding: 18px 12px 12px 12px;
    background-color: #FFFFFF;
    font-weight: bold;
    font-size: 10pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 2px 12px 2px 12px;
    color: #FFFFFF;
    background-color: #1565C0;
    border-radius: 4px;
    font-size: 9pt;
}

QLabel {
    color: #4A5568;
    padding: 1px 0px;
}

QLabel#TitleLabel {
    color: #0D47A1;
    font-size: 16pt;
    font-weight: bold;
    padding: 6px 8px 2px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#SubTitleLabel {
    color: #5C6BC0;
    font-size: 8.5pt;
    padding: 0px 8px 8px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#ProgressLabel {
    color: #1565C0;
    font-size: 9pt;
    font-weight: bold;
    padding: 5px 12px;
    background-color: #EEF2FF;
    border: 1px solid #C5CAE9;
    border-radius: 4px;
}

QLabel#HintLabel {
    color: #7986CB;
    font-size: 8pt;
    padding: 1px 4px;
}

QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #2C3E50;
    selection-background-color: #1E88E5;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 1px solid #1E88E5;
    background-color: #F8FAFE;
}

QLineEdit:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border: 1px solid #E2E8F0;
}

QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #2C3E50;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #1E88E5;
}

QComboBox:hover {
    border: 1px solid #5C6BC0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #E2E8F0;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    background-color: #F8FAFE;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    selection-background-color: #E3F2FD;
    selection-color: #1565C0;
    outline: none;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #E8EAF6;
    color: #1A237E;
}

QRadioButton {
    color: #4A5568;
    spacing: 6px;
    padding: 3px 6px;
}

QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border-radius: 8px;
    border: 2px solid #A0AEC0;
    background-color: #FFFFFF;
}

QRadioButton::indicator:checked {
    border: 2px solid #1E88E5;
    background-color: #1E88E5;
}

QRadioButton::indicator:hover {
    border: 2px solid #5C6BC0;
}

QRadioButton:checked {
    color: #1565C0;
    font-weight: bold;
}

QCheckBox {
    color: #4A5568;
    spacing: 6px;
    padding: 3px 6px;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 2px solid #A0AEC0;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    border: 2px solid #1E88E5;
    background-color: #1E88E5;
}

QCheckBox::indicator:hover {
    border: 2px solid #5C6BC0;
}

QCheckBox:checked {
    color: #1565C0;
}

QPushButton {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 6px 16px;
    color: #2C3E50;
    font-weight: bold;
    font-size: 9pt;
}

QPushButton:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QPushButton:pressed {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QPushButton#PrimaryBtn {
    background-color: #1565C0;
    border: 1px solid #0D47A1;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#PrimaryBtn:hover {
    background-color: #1E88E5;
    border: 1px solid #1565C0;
    color: #FFFFFF;
}

QPushButton#PrimaryBtn:pressed {
    background-color: #0D47A1;
}

QPushButton#SmallBtn {
    padding: 3px 10px;
    font-size: 8pt;
    min-width: 34px;
}

QPushButton#SmallBtn:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QTextEdit {
    background-color: #F5F6FA;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 10px;
    color: #1E293B;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.5pt;
    selection-background-color: #BBDEFB;
    selection-color: #0D47A1;
}

QTextEdit:focus {
    border: 1px solid #1E88E5;
}

QScrollBar:vertical {
    background-color: #F1F5F9;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #CBD5E1;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #1E88E5;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}

QScrollBar:horizontal {
    background-color: #F1F5F9;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #CBD5E1;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #1E88E5;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}

QTableWidget {
    font-size: 9pt;
    gridline-color: #CBD5E1;
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
}

QTableWidget::item:selected {
    background-color: #1976D2;
    color: white;
}

QTableWidget::item {
    padding: 2px 6px;
}

QHeaderView::section {
    font-weight: bold;
    background: #F1F5F9;
    padding: 3px;
    border: none;
    border-bottom: 1px solid #CBD5E1;
}

QProgressBar {
    border: none;
    border-radius: 3px;
    background-color: #E2E8F0;
    text-align: center;
    font-size: 8pt;
    color: #4A5568;
    min-height: 6px;
    max-height: 6px;
}

QProgressBar::chunk {
    background-color: #1E88E5;
    border-radius: 3px;
}

QSlider::groove:horizontal {
    border: 1px solid #CBD5E1;
    height: 8px;
    background-color: #F1F5F9;
    border-radius: 4px;
}

QSlider::sub-page:horizontal {
    background-color: #1E88E5;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background-color: #FFFFFF;
    border: 2px solid #1E88E5;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background-color: #E3F2FD;
    border: 2px solid #1565C0;
}

QSlider::handle:horizontal:pressed {
    background-color: #BBDEFB;
    border: 2px solid #0D47A1;
}

QTabWidget::pane {
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    background-color: #FFFFFF;
    padding: 8px;
}

QTabBar::tab {
    background-color: #F1F5F9;
    border: 1px solid #CBD5E1;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 28px;
    margin-right: 3px;
    min-width: 80px;
    color: #4A5568;
    font-weight: bold;
    font-size: 9pt;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1565C0;
    border-bottom: 2px solid #1E88E5;
}

QTabBar::tab:hover:!selected {
    background-color: #E3F2FD;
    color: #1565C0;
}

QTabBar::tab:disabled {
    color: #94A3B8;
    background-color: #F1F5F9;
}

QFrame#Separator {
    background-color: #CBD5E1;
    max-height: 1px;
}

QFrame#SeparatorV {
    background-color: #CBD5E1;
    max-width: 1px;
    min-width: 1px;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QToolTip {
    background-color: #FFFFFF;
    border: 1px solid #1E88E5;
    border-radius: 4px;
    padding: 5px 10px;
    color: #2C3E50;
    font-size: 8.5pt;
}

QFrame#Sidebar {
    background-color: #F1F5F9;
    border-right: 1px solid #CBD5E1;
}

QFrame#Toolbar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #CBD5E1;
}

QFrame#ViewerFrame {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}

QFrame#CanvasFrame {
    background-color: #1a1a2e;
    border: 1px solid #2D3748;
    border-radius: 8px;
}

QLabel#SectionTitle {
    font-size: 12pt;
    font-weight: 600;
    color: #1565C0;
    padding: 2px 0;
}

QLabel#Subtitle {
    font-size: 9pt;
    color: #5C6BC0;
    padding: 0;
}

QLabel#StatusLabel {
    font-size: 8pt;
    color: #7986CB;
    padding: 4px 0;
}

QFrame#Separator {
    background-color: #E2E8F0;
    max-height: 1px;
    border: none;
}
"""
