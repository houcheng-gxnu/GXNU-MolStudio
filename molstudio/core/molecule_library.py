# -*- coding: utf-8 -*-
"""Read the bundled teaching molecule library."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from molstudio import paths
from molstudio.core.steric.molecule import parse_xyz


CATEGORY_ORDER = ("junior", "inorganic", "organic", "biomolecule")
CATEGORY_LABELS = {
    "junior": ("初中基础", "Junior chemistry"),
    "inorganic": ("高中无机", "High-school inorganic"),
    "organic": ("高中有机", "High-school organic"),
    "biomolecule": ("生命与材料", "Life science & materials"),
}


@dataclass(frozen=True)
class LibraryMolecule:
    id: str
    name_zh: str
    name_en: str
    formula: str
    category: str
    file: str
    aliases: tuple[str, ...] = ()
    description_zh: str = ""
    description_en: str = ""
    style: str = "HoukMol"
    bond_orders: tuple[tuple[int, int, int], ...] = ()

    def display_name(self, lang: str = "zh") -> str:
        return self.name_zh if str(lang).lower().startswith("zh") else self.name_en

    def description(self, lang: str = "zh") -> str:
        return (self.description_zh if str(lang).lower().startswith("zh")
                else self.description_en)

    def search_text(self) -> str:
        return " ".join((
            self.name_zh, self.name_en, self.formula, self.category,
            self.description_zh, self.description_en, *self.aliases,
        )).casefold()


def library_dir() -> Path | None:
    for root in paths.assets_dirs():
        candidate = Path(root) / "molecule_library"
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


def load_library() -> list[LibraryMolecule]:
    root = library_dir()
    if root is None:
        return []
    try:
        data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for raw in data.get("molecules", []):
        try:
            out.append(LibraryMolecule(
                id=str(raw["id"]),
                name_zh=str(raw["name_zh"]),
                name_en=str(raw.get("name_en") or raw["name_zh"]),
                formula=str(raw.get("formula") or ""),
                category=str(raw.get("category") or "organic"),
                file=str(raw["file"]),
                aliases=tuple(str(v) for v in raw.get("aliases", [])),
                description_zh=str(raw.get("description_zh") or ""),
                description_en=str(raw.get("description_en") or ""),
                style=str(raw.get("style") or "HoukMol"),
                bond_orders=tuple(
                    (int(item[0]), int(item[1]), int(item[2]))
                    for item in raw.get("bonds", [])
                    if isinstance(item, (list, tuple)) and len(item) >= 3
                ),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    order = {key: i for i, key in enumerate(CATEGORY_ORDER)}
    out.sort(key=lambda m: (order.get(m.category, 999), m.name_zh.casefold()))
    return out


def molecule_path(entry: LibraryMolecule) -> Path:
    root = library_dir()
    if root is None:
        raise FileNotFoundError("找不到内置分子结构库")
    path = root / entry.file
    if not path.is_file():
        raise FileNotFoundError(f"缺少内置结构文件：{entry.file}")
    return path


def load_molecule(entry: LibraryMolecule):
    return parse_xyz(molecule_path(entry))


def filter_molecules(entries: Iterable[LibraryMolecule], category: str = "all",
                     query: str = "") -> list[LibraryMolecule]:
    words = [part for part in str(query).casefold().split() if part]
    result = []
    for entry in entries:
        if category != "all" and entry.category != category:
            continue
        haystack = entry.search_text()
        if words and not all(word in haystack for word in words):
            continue
        result.append(entry)
    return result


__all__ = [
    "CATEGORY_LABELS", "CATEGORY_ORDER", "LibraryMolecule",
    "filter_molecules", "library_dir", "load_library", "load_molecule",
    "molecule_path",
]
