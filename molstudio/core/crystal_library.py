# -*- coding: utf-8 -*-
"""Read the bundled high-school crystal library (offline CIF + manifest).

The data lives in ``molstudio/assets/crystal_library``.  It is curated from
Avogadro2's public-domain COD CIF set; see that folder's README for the full
citation.  Nothing here needs Qt or OpenGL at import time: the heavyweight
``crystal_lib`` parser is imported lazily, only when a structure is turned
into coordinates for the canvas / a GLB export.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from molstudio import paths

CATEGORY_ORDER = ("molecular", "covalent", "ionic", "metallic",
                  "mixed", "advanced")
CATEGORY_LABELS = {
    "molecular": ("分子晶体", "Molecular crystals"),
    "covalent": ("共价晶体", "Covalent crystals"),
    "ionic": ("离子晶体", "Ionic crystals"),
    "metallic": ("金属晶体", "Metallic crystals"),
    "mixed": ("混合型与过渡晶体", "Mixed / transition crystals"),
    "advanced": ("高考常考与新材料", "Exam cells & advanced materials"),
}
LEVEL_LABELS = {
    1: ("课本必建", "Textbook"),
    2: ("高考常考", "Exam"),
    3: ("拓展", "Extension"),
}


@dataclass(frozen=True)
class CrystalEntry:
    id: str
    name_zh: str
    name_en: str
    formula: str
    category: str
    level: int
    file: str
    preview: str = ""
    aliases: tuple[str, ...] = ()
    structure_type: str = ""
    coordination: str = ""
    cell_contents: str = ""
    teaching_point: str = ""
    description_zh: str = ""
    description_en: str = ""
    space_group: str = ""
    cell: str = ""
    source: str = ""
    generated: bool = False

    def display_name(self, lang: str = "zh") -> str:
        return self.name_zh if str(lang).lower().startswith("zh") else self.name_en

    def description(self, lang: str = "zh") -> str:
        if not str(lang).lower().startswith("zh") and self.description_en:
            return self.description_en
        return self.description_zh or self.description_en

    def category_label(self, lang: str = "zh") -> str:
        labels = CATEGORY_LABELS.get(
            self.category, (self.category, self.category))
        return labels[0 if str(lang).lower().startswith("zh") else 1]

    def level_label(self, lang: str = "zh") -> str:
        labels = LEVEL_LABELS.get(self.level, ("", ""))
        return labels[0 if str(lang).lower().startswith("zh") else 1]

    def search_text(self) -> str:
        return " ".join((
            self.name_zh, self.name_en, self.formula, self.category,
            self.structure_type, self.teaching_point, self.description_zh,
            self.description_en, self.space_group, self.source,
            *self.aliases,
        )).casefold()


def crystal_library_dir() -> Path | None:
    """First assets directory that actually carries the crystal manifest."""
    for root in paths.assets_dirs():
        candidate = Path(root) / "crystal_library"
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


def load_crystal_library() -> list[CrystalEntry]:
    root = crystal_library_dir()
    if root is None:
        return []
    try:
        data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for raw in data.get("crystals", []):
        try:
            out.append(CrystalEntry(
                id=str(raw["id"]),
                name_zh=str(raw["name_zh"]),
                name_en=str(raw.get("name_en") or raw["name_zh"]),
                formula=str(raw.get("formula") or ""),
                category=str(raw.get("category") or "advanced"),
                level=int(raw.get("level") or 3),
                file=str(raw["file"]),
                preview=str(raw.get("preview") or ""),
                aliases=tuple(str(v) for v in raw.get("aliases", [])),
                structure_type=str(raw.get("structure_type") or ""),
                coordination=str(raw.get("coordination") or ""),
                cell_contents=str(raw.get("cell_contents") or ""),
                teaching_point=str(raw.get("teaching_point") or ""),
                description_zh=str(raw.get("description_zh") or ""),
                description_en=str(raw.get("description_en") or ""),
                space_group=str(raw.get("space_group") or ""),
                cell=str(raw.get("cell") or ""),
                source=str(raw.get("source") or ""),
                generated=bool(raw.get("generated")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def crystal_path(entry: CrystalEntry) -> Path:
    root = crystal_library_dir()
    if root is None:
        raise FileNotFoundError("晶体结构库不存在")
    return root / entry.file


def crystal_preview(entry: CrystalEntry) -> Path | None:
    if not entry.preview:
        return None
    root = crystal_library_dir()
    if root is None:
        return None
    path = root / entry.preview
    return path if path.is_file() else None


def filter_crystals(entries, category: str = "all", text: str = "",
                    level: int = 0):
    """Category + free-text + teaching-level filter, in manifest order."""
    needle = str(text or "").strip().casefold()
    out = []
    for entry in entries:
        if category and category != "all" and entry.category != category:
            continue
        if level and entry.level != int(level):
            continue
        if needle and needle not in entry.search_text():
            continue
        out.append(entry)
    return out


def crystal_geometry(entry: CrystalEntry, supercell=(1, 1, 1),
                     fill_boundary: bool = True, with_cell_box: bool = True):
    """→ (symbols, coords[Å], corners[Å] | None, crystal).

    ``corners`` is the 8 vertices of the *original* unit cell (the same box
    the crystal tab draws), never of the enlarged supercell.  Callers can pass
    it straight to ``export_glb(cell_box=...)``.
    """
    # Lazy: crystal_lib pulls in the OpenGL canvas module, which must not be
    # imported by the pure data layer (or by headless unit tests).
    from molstudio.core.crystal_lib import Crystal

    crystal = Crystal.from_file(str(crystal_path(entry)))
    na, nb, nc = (int(max(1, min(6, v))) for v in
                  (supercell + (1, 1, 1))[:3])
    atoms = crystal.supercell(na, nb, nc, fill_boundary=fill_boundary)
    symbols = [str(atom[1]) for atom in atoms]
    coords = [[float(v) for v in atom[3]] for atom in atoms]
    corners = None
    if with_cell_box and not crystal.is_molecule:
        corners = [[float(v) for v in corner]
                   for corner in crystal.cell_corners()]
    return symbols, coords, corners, crystal
