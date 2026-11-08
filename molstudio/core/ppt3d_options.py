# -*- coding: utf-8 -*-
"""Pure-data options for PowerPoint 3D (.glb) exports.

Kept free of Qt so the geometry/scale rules can be unit-tested headlessly and
so the same object can be shared by the library tab and the toolbar dialog.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Ppt3dOptions:
    """Everything the user may tune before writing a .glb."""

    # Mesh / material quality
    high_detail: bool = True
    atom_outline: bool = True
    bake_ao: bool = True
    ao_rays: int = 8
    native_pbr: bool = True
    unlit: bool = False

    # Geometry
    atom_scale: float = 1.0
    bond_scale: float = 1.0
    hide_hydrogens: bool = False
    keep_view: bool = True
    include_surfaces: bool = True

    # Crystal-only options
    show_cell_box: bool = True
    cell_line_width: float = 0.055      # Angstrom, radius of the edge cylinders
    cell_color: str = "#46505F"
    supercell: tuple[int, int, int] = field(default=(1, 1, 1))
    fill_boundary: bool = True

    def as_dict(self) -> dict:
        data = asdict(self)
        data["supercell"] = list(self.supercell)
        return data

    @classmethod
    def from_dict(cls, data) -> "Ppt3dOptions":
        if not isinstance(data, dict):
            return cls()
        known = {name for name in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        if "supercell" in clean:
            reps = tuple(int(v) for v in clean["supercell"][:3])
            clean["supercell"] = (reps + (1, 1, 1))[:3]
        return cls(**clean)

    def apply_to(self, options: dict, symbols=None) -> dict:
        """Merge these user choices over the canvas-derived export kwargs."""
        out = dict(options or {})
        out.update({
            "high_detail": bool(self.high_detail),
            "atom_outline": bool(self.atom_outline),
            "bake_ao": bool(self.bake_ao),
            "ao_rays": int(self.ao_rays),
            "native_pbr": bool(self.native_pbr) and not self.unlit,
            "unlit": bool(self.unlit),
        })
        try:
            scale = float(self.atom_scale)
        except (TypeError, ValueError):
            scale = 1.0
        if scale > 0 and abs(scale - 1.0) > 1e-9 and out.get("atom_radii"):
            out["atom_radii"] = [max(0.02, float(r) * scale)
                                 for r in out["atom_radii"]]
        try:
            bond_scale = float(self.bond_scale)
        except (TypeError, ValueError):
            bond_scale = 1.0
        if (bond_scale > 0 and abs(bond_scale - 1.0) > 1e-9
                and out.get("bond_radius") is not None):
            out["bond_radius"] = max(0.02, float(out["bond_radius"])
                                     * bond_scale)
        if not self.keep_view:
            out.pop("view_rotation", None)
        if not self.include_surfaces:
            out["surfaces"] = []
        if self.hide_hydrogens and symbols:
            visible = out.get("visible_atoms")
            visible = (list(visible) if visible is not None
                       else [True] * len(symbols))
            if len(visible) != len(symbols):
                visible = [True] * len(symbols)
            out["visible_atoms"] = [
                bool(old) and str(sym).strip().capitalize() not in ("H", "D")
                for old, sym in zip(visible, symbols)
            ]
        return out

    def cell_box_spec(self, corners):
        """Build the ``cell_box`` argument for :func:`export_glb`."""
        if not self.show_cell_box or not corners:
            return None
        try:
            radius = max(0.01, min(0.5, float(self.cell_line_width)))
        except (TypeError, ValueError):
            radius = 0.055
        return {
            "corners": [[float(v) for v in corner] for corner in corners],
            "radius": radius,
            "color": str(self.cell_color or "#46505F"),
        }

    def reps(self):
        """Normalised supercell triple, each axis clamped to 1..3."""
        vals = tuple(int(max(1, min(3, v))) for v in
                     (tuple(self.supercell) + (1, 1, 1))[:3])
        return vals
