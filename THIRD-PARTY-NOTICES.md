# Third-Party Notices

GXNU MolStudio contains code and data derived from third-party sources.
This file documents **what comes from where**, so the GPLv3 / third-party /
in-house boundary is explicit.

> **Overall license:** GXNU MolStudio is distributed under the
> **GNU General Public License version 3 (GPLv3-only)**. See `LICENSE`.
> IboView is GPLv3-only, so this project must not be re-declared as
> "GPLv3 or later" while it still contains IboView code.

---

## 1. IboView — GPLv3（衍生作品的来源，决定了本项目的许可证）

| | |
|---|---|
| **Project** | [IboView](https://www.iboview.org) — quantum-chemistry visualization program |
| **Copyright** | (c) 2015 Gerald Knizia |
| **License** | GNU General Public License v3.0 — **GPLv3-only** |
| **Text** | <https://www.gnu.org/licenses/gpl-3.0.html> |

### What is derived

The OpenGL rendering core was produced by translating ("porting") parts of
IboView's C++/GLSL source into Python. Concretely:

| Component | Files | Nature of the derived content |
|---|---|---|
| OpenGL rendering core | `ovcanvas/_glwidget.py` | GLSL shaders; depth-peeling transparency; multi-light Phong lighting; ball-and-stick geometry; rendering parameters |
| Atomic data tables | `ovcanvas/_glwidget.py` | `AtomicRadii` (identical, 104/104) and `g_CovalentRadii` (108/110 identical) data tables |
| Panel defaults & semantics | `ovcanvas/_panel.py`, `ovcanvas/__init__.py` | Relative `IsoThreshold`, phase-colour schemes, `FlipPhase`, gloss presets, depth-fog `Fade` |
| Legacy preview shaders | `legacy/glsl_shaders.py`, `legacy/orbital_gl_widget.py` | Earlier port of the same shaders (currently unused, retained for reference) |

Files that carry the derivation carry prominent notices at the top, e.g.:

```
Based on IboView (Copyright (c) 2015 Gerald Knizia), GPLv3 — modified.
```

The pre-rewrite snapshot is preserved verbatim in `ovcanvas/_glwidget_iboview.py`
(with its original copyright header intact).
A per-item audit is in [`docs/iboview_transplant_audit.md`](./docs/iboview_transplant_audit.md).

### How the GPLv3 obligations are met

| GPLv3 | Requirement | Status |
|---|---|---|
| §4 | Copyleft — whole work under GPLv3 | ✅ `LICENSE`, `README.md`, `README_zh.md` |
| §5(a) | Prominent modification notices | ✅ headers of `ovcanvas/_glwidget.py`, `_panel.py`, `__init__.py`, `legacy/*` |
| §5(b) | License notice on the whole work | ✅ `LICENSE` + READMEs |
| §5(c) | Preserve copyright notices | ✅ `Copyright (c) 2015 Gerald Knizia` retained in all derived files |
| §5(d) | GUI must display Appropriate Legal Notices | ⚠️ About dialog — see §7 below |
| §6 | Corresponding source available | ✅ public repository (see `README.md`) |
| §10 | No further restrictions | ✅ no "academic use only" or similar terms are imposed |

**Note on redistribution:** IboView's `README.txt` contains a request not to
distribute modified versions. That is a **request, not a license term**: GPLv3
§10 forbids further restrictions, and §7 explicitly permits a recipient to
remove such a term. Distributing a modified version is a right granted by
GPLv3 §5 and requires no additional permission. The request is nevertheless
acknowledged here out of respect for the author.

---

## 2. Multiwfn / VMD / Tachyon — external tools, **not** derivative works

These are **separate programs invoked as external processes** (`subprocess`).
They are **not bundled** with MolStudio — the user downloads them separately and
configures the paths in ⚙️ Paths. Calling an external executable does **not**
create a derivative work, so their licenses do not affect MolStudio's GPLv3.

| Tool | Used for | License |
|---|---|---|
| [Multiwfn](http://sobereva.com/multiwfn/) (Tian Lu) | fchk → cube, IGMH/IRI, ESP, AIM, MPP, charges, bond orders | Free for academic use, **closed source** — redistribution governed by its own terms; MolStudio does not redistribute it |
| [VMD](https://www.ks.uiuc.edu/Research/vmd/) | preview, Tcl-driven rendering | University of Illinois/NCSA open-source style license — see the LICENSE in the VMD distribution |
| [Tachyon](http://jedi.ks.uiuc.edu/~johns/raytracer/) (John E. Stone) | ray-traced offline rendering | BSD-style license — see the LICENSE in the Tachyon distribution |
| Tachyon in `ovcanvas/_tachyon_render.py` | bundled `tachyon_WIN32.exe` for offline path tracing | ⚠️ **Verify** whether this binary is redistributed in `dist/`; if so, ship its license text alongside |

> Cite: Lu, T. *J. Comput. Chem.* **2012**, *33*, 580–592 (Multiwfn);
> Humphrey, W.; Dalke, A.; Schulten, K. *J. Molec. Graphics* **1996**, *14*, 33–38 (VMD);
> Stone, J. E. *An Efficient Library for Parallel Ray Tracing and Animation*,
> M.Sc. Thesis, Univ. of Missouri–Rolla, 1998 (Tachyon).

---

## 3. Third-party data tables and palettes

These are **scientific data / colour values**, reproduced as numbers. Data per se
is generally not copyrightable, but the sources are credited here.

| Item | Location | Source |
|---|---|---|
| van der Waals radii | `_VDW_RADII_A` in `ovcanvas/_glwidget.py` | Bondi, *J. Phys. Chem.* **1964**, *68*, 441–451 (public data) |
| Element colours — CPK | `_CPK_COLORS` | Rasmol CPK-new / Jmol standard palette (public) |
| Element colours — GaussView | `_GVIEW_COLORS` | transcribed from `gview_color.tcl` by Tian Lu (sobereva) |
| Element colours — Jmol | `_JMOL_COLORS` | Jmol project palette |
| Isosurface normal handling | `marching_cubes.py` | behaviour follows IboView `FIsoSurface::FixVolumeDataNormals` (algorithm, not code) |
| VMD orbital render styles | `fchk_orbital.py` presets | vcube 2.0 — Tcl scripts for batch rendering of Gaussian cube files with VMD, by Prof. Cheng Zhong (Wuhan University); 计算化学公社 (Computational Chemistry Commune), thread 18150, http://bbs.keinsci.com/thread-18150-1-1.html |
| VMD dashed-bond drawing | `_igmh_preview.tcl`, `etsnocv/` | `draw_bond` Tcl script by **Eming** (KeinSci forum) |
| Render style presets | `IQMOL.json`, `HoukMol.json`, `sob-art.json`, `gxnu_style.json`, `ring_style.json` | light directions / style parameters; the *IQmol* and *HoukMol* sets are named after the look they reproduce |

---

## 4. In-house components of this research group (no third-party constraint)

These are the group's own work; they were integrated into MolStudio and, where
previously published under different terms, are now **relicensed under GPLv3**
together with the rest of the project.

| Component | Origin | Note |
|---|---|---|
| IGMH/IRI panel `igmh_panel.py` | ported from **IGMH_Toolbox V4** (Hou Cheng, Zenodo `10.5281/zenodo.20791253`) | previously labelled "academic use"; **relicensed to GPLv3** as the author owns it |
| Charge panel `charge_viewer.py` | ported from **ChargeViewer** (`cnb.cool/chem311/ChargeViewer`) | group's own |
| MPP panel `mpp_panel.py` | ported from `mpp_auto_qt.py` (Hou Cheng group, GXNU) | group's own |
| ETS-NOCV sub-package `etsnocv/` | **ETS-NOCV Viewer** (group's own) | calls Multiwfn externally |
| `molcanvas.py`, MolViewer gradients | group's own (`Chem311`) | |

---

## 5. Python dependencies

Not vendored; installed separately. All are GPLv3-compatible.

| Package | License |
|---|---|
| PyQt5 5.15 | GPLv3 **or** commercial (dual) — GPLv3 chosen here |
| NumPy | BSD-3-Clause |
| Matplotlib | Matplotlib license (PSF-style) |
| Pillow | HPND |
| PyOpenGL | BSD |
| `mcubes` | ⚠️ verify — PyMCubes is MIT |

---

## 6. Fonts and icons

| Asset | Source |
|---|---|
| `校徽.png` | Guangxi Normal University emblem — used with permission for the splash screen |
| `molstudio.ico`, `gxnu_molstudio.ico` | produced for this project |

---

## 7. Status and remaining housekeeping

### ✅ §5(d) — Appropriate Legal Notices: implemented

GPLv3 requires an interactive program to display Appropriate Legal Notices.
This is done by the **About dialog** (`AboutDialog` in `main_window.py`),
reachable from the **关于 / About** button in the top input bar. It displays:

- `GXNU MolStudio` + version
- the GPLv3 grant and no-warranty disclaimer
- `IboView — Copyright (c) 2015 Gerald Knizia, GPLv3 — modified`
- pointers to `THIRD-PARTY-NOTICES.md` and the full source repository
- the third-party acknowledgments (Multiwfn, vcube2.0, IGMH/IRI, VMD, Tachyon,
  Eming `draw_bond`)

Both zh/en locales are covered (`i18n.py` keys `btn_about`, `dlg_about_title`,
`about_version`, `grp_about_license`, `grp_about_acknowledgments`, `btn_close`).

### Remaining housekeeping (low priority)

- ⚠️ `OrbitalViewer.spec` `hiddenimports` still lists `glsl_shaders`,
  `orbital_gl_viewer`, `orbital_gl_widget`, which now live in `legacy/` and are
  imported by nothing. Harmless but stale — clean up.
- ⚠️ Confirm whether `tachyon_WIN32.exe` is shipped in `dist/`; if so bundle
  its license text.

---

## License

GXNU MolStudio is distributed under the **GNU General Public License version 3**
(GPLv3-only). You may redistribute and/or modify it under the terms of that
license. See the `LICENSE` file in the repository root for the full text.

*Citations requested for academic use are listed in `README.md` / `README_zh.md`
and are requests, not additional license conditions.*
