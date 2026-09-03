# Third-Party Notices

GXNU MolStudio contains code derived from third-party open-source projects.
This file lists those projects and explains how their license terms are
honored in this distribution.

## IboView — GPLv3

**Project:** [IboView](https://www.iboview.org), an interactive quantum
chemistry visualization program by Gerald Knizia.

- **Copyright:** (c) 2015 Gerald Knizia
- **License:** GNU General Public License v3.0 (GPLv3)
  - Official repo / fork used for reference:
    <https://github.com/KoehnLab/iboview>
  - GPLv3 license text: <https://www.gnu.org/licenses/gpl-3.0.html>

### What is derived

GXNU MolStudio is a **derivative work** of IboView. Its embedded OpenGL
rendering engine was produced by translating ("porting") parts of IboView's
C++/GLSL source code into Python. Concretely, the following are ported or
adapted from IboView:

| Component | Files | Nature of the derived content |
|-----------|-------|-------------------------------|
| OpenGL rendering core | `ovcanvas/_glwidget.py`, `glsl_shaders.py`, `orbital_gl_widget.py` | GLSL shaders; depth-peeling transparency pipeline; three-directional Phong lighting; ball-and-stick geometry; rendering parameters |
| Atomic data tables | same files | `AtomicRadii`, `ElementColors`, `g_CovalentRadii` data tables (functional scientific constants reproduced verbatim with the surrounding code) |
| Isosurface handling | `marching_cubes.py` | Algorithmic behaviour re-implemented following IboView's `FIsoSurface`/`FixVolumeDataNormals` and relative `IsoThreshold` semantics |

Files that carry the derivation carry prominent notices at the top, e.g.:

```
Based on IboView (c) 2015 Gerald Knizia, GPLv3 — modified.
```

### How the GPLv3 obligations are met

- **§4 – Copyleft:** the whole derivative work is distributed under GPLv3
  (see `LICENSE` in the repository root).
- **§5(a) – Prominent notices on modified files:** ported files are marked
  in their header comments as modified derivatives of IboView.
- **§5(b) – Preserve copyright notices:** the original copyright notice of
  IboView is preserved.
- **§5(c) – License notice on unmodified files:** none of IboView's files are
  redistributed unmodified in binary/proprietary form; the GPLv3 license text
  accompanies the distribution.
- **§6 – Source code:** complete, corresponding source code is available
  publicly (see the repository link in `README.md`).
- **No additional restrictions** are imposed beyond GPLv3.

### License

GXNU MolStudio is distributed under the **GNU General Public License v3.0**.
You may redistribute and/or modify it under the terms of that license. See the
`LICENSE` file in the repository root for the full license text.

---

*Other third-party components (Multiwfn, VMD, Tachyon, vcube2.0, MolViewer,
IQmol presets) are used as external tools or as styling references; their own
terms are acknowledged in `README.md`.*
