# GXNU MolStudio

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0-blue.svg" alt="Version 1.0">
  <img src="https://img.shields.io/badge/python-3.8+-green.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/license-GPLv3-blue.svg" alt="GPLv3 License">
</p>

<p align="center">
  <strong>English</strong> · <a href="./README_zh.md">简体中文</a>
</p>

<p align="center">
  <b>Molecular visualization and quantum-chemical analysis — from fchk to publication-ready orbital images in one go.</b>
  <br>
  <sub>Hou Cheng Research Group · Guangxi Normal University</sub>
</p>

---

## Screenshots

<p align="center">
  <img src="screenshots/mol_view1.png" width="32%" alt="View 1">
  <img src="screenshots/mol_view2.png" width="32%" alt="View 2">
  <img src="screenshots/mol_view3.png" width="32%" alt="View 3">
</p>
<p align="center">
  <img src="screenshots/mol_view4.png" width="32%" alt="View 4">
  <img src="screenshots/mol_view5.png" width="32%" alt="View 5">
  <img src="screenshots/mol_view6.png" width="32%" alt="View 6">
</p>

---

## About

GXNU MolStudio is a molecular visualization and quantum-chemistry analysis suite built for computational chemistry research. It integrates an **embedded OpenGL real-time rendering engine** (ported from the IboView pipeline), **Multiwfn wavefunction analysis**, **IGMH/IRI weak-interaction analysis**, **ESP electrostatic potential**, **NBO and charge analysis**, and more — wrapping workflows that used to require manual switching between several programs into a single intuitive GUI.

| Task | Traditional workflow | GXNU MolStudio |
|---|---|---|
| cube generation | type commands by hand | double-click an orbital, auto-generated |
| 3D preview | manually load & tweak isovalues | embedded OpenGL canvas with live sliders |
| rendering | tune lights & materials by hand | one-click styles, instant images |
| weak interactions | run IGMH/IRI separately, then compose | one-click analysis and visualization in-panel |
| batch processing | repeat file-by-file | drag in a folder, fully automated |

---

## Features

### 🧬 Embedded OpenGL rendering engine (ovcanvas)
- **Depth-peeled transparency compositing** — IboView-ported pipeline, correct in-plane transparency sorting across layers; automatic fallback to sorted blending when unavailable
- **One-click styles** — sob-art / IBOview / HoukMol / IQmol default looks, switchable in one click
- **Atom colors × lights, two orthogonal axes** — atom palettes (CPK / SobArt / HoukMol / Vcube …) × lighting rigs (3-light / 1-light / 2-light / 4-light) in any combination
- **Per-light glow** — light dialog for direction / count / glow with fine tuning, save & load
- **Ring rings** — HoukMol-style equatorial great circles; azimuth / elevation adjustable, lockable

### 🔬 Molecule display helpers
- **Hide hydrogens** — hide all H atoms with one click to highlight the heavy-atom skeleton
- **Keep selected H** — enter indices (e.g. `1,3,5-8`) to show only chosen hydrogens
- **Atom indices / element symbols** — label each atom with its in-molecule number or element symbol

### 🧪 IGMH / IRI weak-interaction analysis
- **One-click analysis** — pick fragments, run IGMH or IRI indices through Multiwfn
- **BGR coloring** — sign(λ₂)ρ blue-green-red coloring; isosurface size / opacity sliders plus precise input boxes
- **IGM scatter plots** — embedded scatter-plot viewer

### ⚡ Quantum-chemistry data analysis
- **Orbital browser** — orbital energies, occupations, HOMO/LUMO labels; double-click to generate a cube
- **ESP electrostatic potential** — isosurface + extrema labels + color scale bar
- **NBO analysis** — bond orders, occupations, second-order perturbation E(2) orbital pairs
- **Charge analysis** — Mulliken / fitted charges with bond-order visualization
- **IRC analysis** — track Mayer bond orders and atomic charges along an IRC path, showing each structure live in the shared canvas
- **Distortion–Interaction (DI) analysis** — fragment energy-decomposition with a report and diagram
- **Energetic Span Model (ESM)** — catalytic-cycle analysis: identify TDI/TDTS, compute the energy span δE and TOF, step-shaped energy profiles
- **AIM topology** — QTAIM bond critical points and bond paths from `.wfn` / `.wfx` / fchk input
- **Charge & Mayer bond order** — combined charge-population and bond-order analysis

### 🎬 Legacy VMD / Tachyon rendering (compatibility mode)
- 30+ preset render styles (vcube2.0, IboView, original picks)
- High-resolution output (BMP/PNG, 3000+), optional transparent background, shadow/AO control
- Instant Chinese/English toggle, run logs, command-line batch mode

---

## Quick Start

### Requirements

| Component | Purpose | Install |
|------|------|------|
| Python 3.8+ | runtime | [python.org](https://www.python.org/) |
| PyQt5 | GUI | `pip install PyQt5 PyOpenGL PyOpenGL-accelerate` |
| NumPy | numerics | `pip install numpy` |
| PyMCubes | isosurface extraction | `pip install PyMCubes` |
| matplotlib | scatter plots / color bars | `pip install matplotlib` |
| [Multiwfn](http://sobereva.com/multiwfn/) | fchk → cube, IGMH/IRI | download and configure the path |

> VMD / Tachyon are only required for the legacy render mode; the embedded OpenGL canvas does not depend on them.

### Installation

```bash
git clone https://github.com/houcheng-gxnu/GXNU-MolStudio.git
cd GXNU-MolStudio
pip install PyQt5 PyOpenGL numpy PyMCubes matplotlib
```

### Configure tool paths

On first launch, browse and select the Multiwfn path (and others) in the GUI ⚙️ settings; they are saved automatically to `fchk_orbital.ini`.

### Launch

```bash
# GUI mode (English UI available; 中文内置)
python main.py
```

### Command-line mode (batch)

```bash
# Single file, HOMO orbital, sob-art style
python main.py input.fchk --mo h --iso 0.05 --style sob-art

# Batch a folder, HOMO + LUMO
python main.py ./fchk_folder/ --mo h,l --iso 0.05

# Specific orbitals, style, high resolution
python main.py input.fchk --mo h-1,h,l,l+1 --iso 0.04 --style lakers --res 3000,2250

# cube only, no rendering (for debugging)
python main.py ./folder/ --mo h --grid 3 --no-render
```

| Argument | Type | Default | Description |
|------|------|--------|------|
| `input` | str | — | fchk file path or folder path |
| `--mo` | str | `h` | orbitals: `h` (HOMO), `l` (LUMO), `h-1`, numeric indices, comma-separated |
| `--iso` | float | `0.05` | isosurface threshold |
| `--grid` | int | `2` | grid quality: 1=low, 2=medium, 3=high |
| `--style` | str | `sob-art` | render style |
| `--res` | str | `2000,1500` | output resolution `width,height` (`widthxheight` also accepted) |
| `--no-render` | flag | — | generate cubes only, skip rendering |
| `--out` | str | same as input | output directory |

---

## Project Structure

```
GXNU-MolStudio/
├── main.py                  # Entry point (GUI launch + CLI batch)
├── main_window.py           # Main window (UI layout, panel docking, logs)
├── ovcanvas/                # Embedded OpenGL rendering engine (IboView port)
│   ├── _glwidget.py         # GL core: depth peeling / lighting / ball-stick / isosurfaces
│   ├── _panel.py            # Canvas controls (one-click styles / params / lights / ring)
│   ├── _colorwheel.py       # IboView-style color wheel
│   └── _molviewer_style.py  # MolViewer preset
├── etsnocv/                 # ETS-NOCV analysis package
├── igmh_panel.py            # IGMH/IRI weak-interaction panel
├── irc_panel.py             # IRC panel: Mayer bond order / charge along the path
├── esp_panel.py             # ESP electrostatic-potential panel
├── aim_panel.py             # AIM topology analysis (QTAIM BCPs & bond paths)
├── charge_bond_panel.py     # Charge + Mayer bond-order combined panel
├── charge_viewer.py         # Charge analysis viewer
├── nbo_viewer.py            # NBO analysis viewer
├── di_analysis_panel.py     # Distortion–Interaction energy decomposition
├── energy_span_panel.py     # Energetic Span Model (energy span δE / TOF)
├── fchk_orbital.py          # Backend engine (cube gen, VMD control, Tachyon render, styles)
├── fchk_parser.py           # fchk parsing
├── marching_cubes.py        # Isosurface extraction (PyMCubes wrapper)
├── file_dialogs.py          # File dialogs (remember last directory)
├── i18n.py                  # Internationalization (简体中文 / English)
├── theme.py                 # QSS themes
├── workers.py               # Background worker threads
├── OrbitalViewer.spec       # PyInstaller config (onedir)
├── screenshots/             # Preview screenshots
├── README.md                # English (default)
└── README_zh.md             # 简体中文
```

---

## Build a Standalone EXE

No Python installation required on the target machine — handy for non-technical users:

```bash
pip install pyinstaller
pyinstaller OrbitalViewer.spec --clean
```

Output: `dist/GXNU MolStudio/` (a folder; double-click `GXNU MolStudio.exe` to start).

> Packaging already handles 360 Security guard's write interception on a few system DLLs (see comments in the spec).

---

## Acknowledgments

GXNU MolStudio stands on the shoulders of giants:

- **[Multiwfn](http://sobereva.com/multiwfn/)** — the wavefunction analysis program by Prof. Tian Lu (sobereva), cited by over 40,000 papers. Used here to generate cubes and run IGMH/IRI analyses.
- **[vcube2.0](https://github.com/Zhong-Cheng-2020/vcube2.0)** — the collection of polished VMD orbital render configurations by Prof. Cheng Zhong.
- **[VMD](https://www.ks.uiuc.edu/Research/vmd/)** — Humphrey, W., Dalke, A. and Schulten, K., "VMD: Visual Molecular Dynamics", J. Molec. Graphics, 1996, 14, 33–38.
- **[Tachyon](http://jedi.ks.uiuc.edu/~johns/raytracer/)** — Stone, J. E., "An Efficient Library for Parallel Ray Tracing and Animation", M.Sc. Thesis, 1998.
- **[IboView](https://www.iboview.org)** — the quantum-chemistry visualization program by Gerald Knizia. Our OpenGL engine (depth-peeled transparent compositing, Phong lighting, ball-and-stick geometry, atomic radii/color tables) is modeled on and partly ported from IboView (Copyright (c) 2015 Gerald Knizia, GPLv3). Many thanks.

---

## Citation

If GXNU MolStudio helps your research, please cite:

```bibtex
@software{GXNUMolStudio2026,
  title        = {GXNU MolStudio: Molecular Visualization and Quantum Chemical Analysis},
  author       = {Hou Cheng},
  year         = {2026},
  version      = {1.0},
  url          = {https://github.com/houcheng-gxnu/GXNU-MolStudio},
}
```

Also cite the corresponding tools from the acknowledgments above. See also [CITATION.cff](./CITATION.cff) and [CITATION.bib](./CITATION.bib).

---

## License

This project is a derivative work of IboView and is distributed under the **GNU General Public License v3 (GPLv3)**. See the [LICENSE](./LICENSE) file.

---

<p align="center">
  <sub>Made with ❤️ by Hou Cheng Research Group @ Guangxi Normal University</sub>
</p>
