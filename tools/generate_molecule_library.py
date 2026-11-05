# -*- coding: utf-8 -*-
"""Build the bundled teaching molecule coordinates with RDKit.

RDKit is a development-time dependency only. MolStudio ships the generated
XYZ files and reads them without requiring RDKit at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "molstudio" / "assets" / "molecule_library"


MOLECULES = [
    # id, zh, en, formula, category, SMILES, aliases, zh description, en description
    ("hydrogen", "氢气", "Hydrogen", "H2", "junior", "[H][H]", ["H2", "氢分子"],
     "最简单的双原子分子，含一个 H–H 单键。", "The simplest diatomic molecule with one H-H bond."),
    ("oxygen", "氧气", "Oxygen", "O2", "junior", "O=O", ["O2", "氧分子"],
     "双原子分子，常用球棍模型展示氧氧双键。", "A diatomic molecule commonly shown with an O=O bond."),
    ("nitrogen", "氮气", "Nitrogen", "N2", "junior", "N#N", ["N2", "氮分子"],
     "稳定的双原子分子，具有氮氮三键。", "A stable diatomic molecule with a nitrogen-nitrogen triple bond."),
    ("chlorine", "氯气", "Chlorine", "Cl2", "junior", "ClCl", ["Cl2", "氯分子"],
     "黄绿色双原子分子。", "A green-yellow diatomic molecule."),
    ("hydrogen-chloride", "氯化氢", "Hydrogen chloride", "HCl", "junior", "[H]Cl",
     ["HCl", "盐酸分子"],
     "由氢和氯组成的直线形双原子分子。", "A linear diatomic molecule of hydrogen and chlorine."),
    ("water", "水", "Water", "H2O", "junior", "O", ["H2O", "水分子"],
     "弯曲形分子，是讲解键角与极性键的常用例子。", "A bent molecule often used to teach bond angles and polar bonds."),
    ("carbon-dioxide", "二氧化碳", "Carbon dioxide", "CO2", "junior", "O=C=O",
     ["CO2", "碳酸气"],
     "直线形分子，含两个 C=O 双键。", "A linear molecule with two C=O bonds."),
    ("methane", "甲烷", "Methane", "CH4", "junior", "C", ["CH4", "沼气"],
     "正四面体形分子，是最简单的烷烃。", "A tetrahedral molecule and the simplest alkane."),
    ("ammonia", "氨", "Ammonia", "NH3", "junior", "N", ["NH3", "氨气"],
     "三角锥形分子。", "A trigonal-pyramidal molecule."),
    ("carbon-monoxide", "一氧化碳", "Carbon monoxide", "CO", "junior", "[C-]#[O+]",
     ["CO"], "直线形双原子分子。", "A linear diatomic molecule."),
    ("sulfur-dioxide", "二氧化硫", "Sulfur dioxide", "SO2", "junior", "O=S=O",
     ["SO2"], "弯曲形分子，是介绍 VSEPR 的常见实例。", "A bent molecule commonly used in VSEPR teaching."),
    ("hydrogen-sulfide", "硫化氢", "Hydrogen sulfide", "H2S", "junior", "S",
     ["H2S"], "与水分子的几何构型相似的弯曲形分子。", "A bent molecule with geometry similar to water."),
    ("ozone", "臭氧", "Ozone", "O3", "inorganic", "[O-][O+]=O", ["O3"],
     "弯曲形三原子分子。", "A bent triatomic molecule."),
    ("nitric-oxide", "一氧化氮", "Nitric oxide", "NO", "inorganic", "[N]=O",
     ["NO"], "直线形双原子分子。", "A linear diatomic molecule."),
    ("nitrogen-dioxide", "二氧化氮", "Nitrogen dioxide", "NO2", "inorganic", "[O-][N+]=O",
     ["NO2"], "弯曲形分子，可作为开壳层结构的展示例子。", "A bent molecule useful for illustrating open-shell species."),
    ("sulfur-trioxide", "三氧化硫", "Sulfur trioxide", "SO3", "inorganic", "O=S(=O)=O",
     ["SO3"], "平面三角形分子。", "A trigonal-planar molecule."),
    ("hydrogen-peroxide", "过氧化氢", "Hydrogen peroxide", "H2O2", "inorganic", "OO",
     ["H2O2", "双氧水"], "具有非平面构型和 O–O 单键。", "A non-planar molecule with an O-O bond."),
    ("phosphine", "磷化氢", "Phosphine", "PH3", "inorganic", "P",
     ["PH3"], "三角锥形分子，可与氨作结构对比。", "A trigonal-pyramidal molecule comparable with ammonia."),
    ("boron-trifluoride", "三氟化硼", "Boron trifluoride", "BF3", "inorganic", "FB(F)F",
     ["BF3"], "典型的平面三角形分子。", "A classic trigonal-planar molecule."),
    ("silicon-tetrafluoride", "四氟化硅", "Silicon tetrafluoride", "SiF4", "inorganic", "F[Si](F)(F)F",
     ["SiF4"], "正四面体形分子。", "A tetrahedral molecule."),
    ("sulfur-hexafluoride", "六氟化硫", "Sulfur hexafluoride", "SF6", "inorganic", "FS(F)(F)(F)(F)F",
     ["SF6"], "正八面体形分子。", "An octahedral molecule."),
    ("ethane", "乙烷", "Ethane", "C2H6", "organic", "CC", ["C2H6"],
     "最简单的碳碳单键分子。", "The simplest molecule containing a C-C single bond."),
    ("ethene", "乙烯", "Ethene", "C2H4", "organic", "C=C", ["C2H4", "ethylene"],
     "平面分子，具有碳碳双键。", "A planar molecule with a C=C double bond."),
    ("ethyne", "乙炔", "Ethyne", "C2H2", "organic", "C#C", ["C2H2", "acetylene"],
     "直线形分子，具有碳碳三键。", "A linear molecule with a C#C triple bond."),
    ("propane", "丙烷", "Propane", "C3H8", "organic", "CCC", ["C3H8"],
     "直链烷烃。", "A straight-chain alkane."),
    ("butane", "正丁烷", "Butane", "C4H10", "organic", "CCCC", ["C4H10", "n-butane"],
     "四碳直链烷烃。", "A four-carbon straight-chain alkane."),
    ("isobutane", "异丁烷", "Isobutane", "C4H10", "organic", "CC(C)C", ["C4H10", "2-methylpropane"],
     "与正丁烷互为同分异构体。", "A branched isomer of n-butane."),
    ("cyclopropane", "环丙烷", "Cyclopropane", "C3H6", "organic", "C1CC1", ["C3H6"],
     "三元碳环。", "A three-membered carbon ring."),
    ("cyclohexane", "环己烷", "Cyclohexane", "C6H12", "organic", "C1CCCCC1", ["C6H12"],
     "六元饱和碳环，常用于展示椅式构象。", "A six-membered saturated ring, useful for chair conformations."),
    ("benzene", "苯", "Benzene", "C6H6", "organic", "c1ccccc1", ["C6H6"],
     "平面芳香环，是理解共轭与芳香性的基础结构。", "A planar aromatic ring central to conjugation and aromaticity."),
    ("toluene", "甲苯", "Toluene", "C7H8", "organic", "Cc1ccccc1", ["C7H8", "methylbenzene"],
     "苯环上连接一个甲基。", "Benzene bearing one methyl substituent."),
    ("phenol", "苯酚", "Phenol", "C6H6O", "organic", "Oc1ccccc1", ["C6H5OH"],
     "苯环直接连接羟基。", "Benzene bearing a directly attached hydroxyl group."),
    ("methanol", "甲醇", "Methanol", "CH4O", "organic", "CO", ["CH3OH", "methyl alcohol"],
     "最简单的醇。", "The simplest alcohol."),
    ("ethanol", "乙醇", "Ethanol", "C2H6O", "organic", "CCO", ["C2H5OH", "酒精"],
     "中学常见的醇，含羟基官能团。", "A common school alcohol containing a hydroxyl group."),
    ("propan-1-ol", "正丙醇", "Propan-1-ol", "C3H8O", "organic", "CCCO", ["C3H7OH", "1-propanol"],
     "三碳酸直链醇。", "A three-carbon straight-chain alcohol."),
    ("ethylene-glycol", "乙二醇", "Ethylene glycol", "C2H6O2", "organic", "OCCO", ["C2H6O2"],
     "含两个羟基的二元醇。", "A diol containing two hydroxyl groups."),
    ("glycerol", "甘油", "Glycerol", "C3H8O3", "organic", "OCC(O)CO", ["C3H8O3", "glycerin"],
     "含三个羟基的多元醇。", "A triol containing three hydroxyl groups."),
    ("formaldehyde", "甲醛", "Formaldehyde", "CH2O", "organic", "C=O", ["CH2O", "methanal"],
     "最简单的醛。", "The simplest aldehyde."),
    ("acetaldehyde", "乙醛", "Acetaldehyde", "C2H4O", "organic", "CC=O", ["CH3CHO", "ethanal"],
     "含醛基的二碳有机物。", "A two-carbon molecule containing an aldehyde group."),
    ("acetone", "丙酮", "Acetone", "C3H6O", "organic", "CC(=O)C", ["C3H6O", "propan-2-one"],
     "最简单的酮。", "The simplest ketone."),
    ("formic-acid", "甲酸", "Formic acid", "CH2O2", "organic", "O=CO", ["HCOOH", "methanoic acid"],
     "最简单的羧酸。", "The simplest carboxylic acid."),
    ("acetic-acid", "乙酸", "Acetic acid", "C2H4O2", "organic", "CC(=O)O", ["CH3COOH", "醋酸"],
     "中学常见的羧酸。", "A common school carboxylic acid."),
    ("propanoic-acid", "丙酸", "Propanoic acid", "C3H6O2", "organic", "CCC(=O)O", ["C2H5COOH"],
     "三碳酸羧酸。", "A three-carbon carboxylic acid."),
    ("methyl-formate", "甲酸甲酯", "Methyl formate", "C2H4O2", "organic", "COC=O", ["HCOOCH3"],
     "甲酸与甲醇形成的酯。", "An ester formed from formic acid and methanol."),
    ("ethyl-acetate", "乙酸乙酯", "Ethyl acetate", "C4H8O2", "organic", "CCOC(C)=O", ["CH3COOC2H5"],
     "中学酯化反应常见产物。", "A common product of high-school esterification."),
    ("dimethyl-ether", "二甲醚", "Dimethyl ether", "C2H6O", "organic", "COC", ["CH3OCH3"],
     "与乙醇互为同分异构体。", "An isomer of ethanol."),
    ("diethyl-ether", "乙醚", "Diethyl ether", "C4H10O", "organic", "CCOCC", ["C2H5OC2H5"],
     "常见的醚类化合物。", "A common ether."),
    ("methylamine", "甲胺", "Methylamine", "CH5N", "organic", "CN", ["CH3NH2"],
     "最简单的有机胺。", "The simplest organic amine."),
    ("ethylamine", "乙胺", "Ethylamine", "C2H7N", "organic", "CCN", ["C2H5NH2"],
     "含氨基的二碳有机物。", "A two-carbon organic amine."),
    ("aniline", "苯胺", "Aniline", "C6H7N", "organic", "Nc1ccccc1", ["C6H5NH2"],
     "苯环直接连接氨基。", "Benzene bearing a directly attached amino group."),
    ("urea", "尿素", "Urea", "CH4N2O", "organic", "NC(=O)N", ["CO(NH2)2"],
     "含酰胺结构的常见含氮化合物。", "A common nitrogen compound containing an amide-like unit."),
    ("acetonitrile", "乙腈", "Acetonitrile", "C2H3N", "organic", "CC#N", ["CH3CN"],
     "含氰基的极性有机溶剂。", "A polar nitrile solvent."),
    ("acrylonitrile", "丙烯腈", "Acrylonitrile", "C3H3N", "organic", "C=CC#N", ["C3H3N"],
     "含碳碳双键与氰基。", "Contains both a C=C bond and a nitrile group."),
    ("chloroform", "三氯甲烷", "Chloroform", "CHCl3", "organic", "ClC(Cl)Cl", ["CHCl3"],
     "四面体形卤代烃。", "A tetrahedral halogenated hydrocarbon."),
    ("carbon-tetrachloride", "四氯化碳", "Carbon tetrachloride", "CCl4", "organic", "ClC(Cl)(Cl)Cl",
     ["CCl4"], "正四面体形卤代烃。", "A tetrahedral halogenated hydrocarbon."),
    ("bromoethane", "溴乙烷", "Bromoethane", "C2H5Br", "organic", "CCBr", ["C2H5Br"],
     "常见的卤代烃。", "A common alkyl bromide."),
    ("pyridine", "吡啶", "Pyridine", "C5H5N", "organic", "n1ccccc1", ["C5H5N"],
     "含一个氮原子的六元芳香环。", "A six-membered aromatic ring containing nitrogen."),
    ("furan", "呋喃", "Furan", "C4H4O", "organic", "o1cccc1", ["C4H4O"],
     "含氧的五元芳香杂环。", "A five-membered oxygen-containing aromatic heterocycle."),
    ("thiophene", "噻吩", "Thiophene", "C4H4S", "organic", "s1cccc1", ["C4H4S"],
     "含硫的五元芳香杂环。", "A five-membered sulfur-containing aromatic heterocycle."),
    ("pyrrole", "吡咯", "Pyrrole", "C4H5N", "organic", "[nH]1cccc1", ["C4H5N"],
     "含氮的五元芳香杂环。", "A five-membered nitrogen-containing aromatic heterocycle."),
    ("naphthalene", "萘", "Naphthalene", "C10H8", "organic", "c1ccc2ccccc2c1", ["C10H8"],
     "两个稠合苯环组成的芳香烃。", "An aromatic hydrocarbon made of two fused rings."),
    ("styrene", "苯乙烯", "Styrene", "C8H8", "organic", "C=Cc1ccccc1", ["C8H8"],
     "苯环连接乙烯基。", "Benzene bearing a vinyl group."),
    ("glycine", "甘氨酸", "Glycine", "C2H5NO2", "biomolecule", "NCC(=O)O", ["gly", "aminoacetic acid"],
     "最简单的氨基酸，同时含氨基和羧基。", "The simplest amino acid with amino and carboxyl groups."),
    ("alanine", "丙氨酸", "Alanine", "C3H7NO2", "biomolecule", "CC(N)C(=O)O", ["ala"],
     "常见的手性氨基酸。", "A common chiral amino acid."),
    ("lactic-acid", "乳酸", "Lactic acid", "C3H6O3", "biomolecule", "CC(O)C(=O)O", ["C3H6O3"],
     "含羟基和羧基的生物相关小分子。", "A small biomolecule containing hydroxyl and carboxyl groups."),
    ("glucose", "葡萄糖", "Glucose", "C6H12O6", "biomolecule", "OCC(O)C(O)C(O)C(O)C=O",
     ["C6H12O6", "dextrose"],
     "重要的单糖，常以其开链结构展示多个羟基和一个醛基。", "An important monosaccharide shown here in open-chain form."),
    ("serotonin", "血清素", "Serotonin", "C10H12N2O", "biomolecule",
     "NCCc1c[nH]c2ccc(O)cc12", ["5-hydroxytryptamine", "5-HT", "C10H12N2O"],
     "重要的神经递质；含羟基吲哚环、氨基和柔性乙胺侧链。",
     "An important neurotransmitter with a hydroxyindole ring and aminoethyl side chain."),
    ("fructose", "果糖", "Fructose", "C6H12O6", "biomolecule", "OCC(O)C(O)C(O)C(=O)CO",
     ["C6H12O6", "levulose"],
     "与葡萄糖互为同分异构体的单糖。", "A monosaccharide isomeric with glucose."),
    ("sucrose", "蔗糖", "Sucrose", "C12H22O11", "biomolecule",
     "OC[C@H]1O[C@@](CO)(O[C@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O)[C@@H](O)[C@@H]1O",
     ["C12H22O11", "table sugar"],
     "由葡萄糖和果糖单元组成的二糖。", "A disaccharide composed of glucose and fructose units."),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    for (slug, zh, en, formula, category, smiles, aliases, desc_zh, desc_en) in MOLECULES:
        try:
            if slug == "sulfur-hexafluoride":
                # RDKit UFF has no reliable S(VI) type for this hypervalent
                # structure. Use an explicit octahedral geometry instead.
                symbols = ["S"] + ["F"] * 6
                d = 1.56
                coords = [
                    (0.0, 0.0, 0.0),
                    (d, 0.0, 0.0), (-d, 0.0, 0.0),
                    (0.0, d, 0.0), (0.0, -d, 0.0),
                    (0.0, 0.0, d), (0.0, 0.0, -d),
                ]
                bond_orders = [[1, i, 1] for i in range(2, 8)]
            else:
                mol = Chem.MolFromSmiles(smiles)
                if mol is None:
                    raise ValueError("SMILES parse failed")
                mol = Chem.AddHs(mol)
                params = AllChem.ETKDGv3()
                params.randomSeed = 20261104
                params.useSmallRingTorsions = True
                if AllChem.EmbedMolecule(mol, params) != 0:
                    params.useRandomCoords = True
                    if AllChem.EmbedMolecule(mol, params) != 0:
                        raise ValueError("3D embedding failed")
                if AllChem.MMFFHasAllMoleculeParams(mol):
                    AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
                else:
                    AllChem.UFFOptimizeMolecule(mol, maxIters=500)
                conf = mol.GetConformer()
                symbols = [atom.GetSymbol() for atom in mol.GetAtoms()]
                coords = [
                    tuple(conf.GetAtomPosition(i))
                    for i in range(mol.GetNumAtoms())
                ]
                bond_orders = []
                for bond in mol.GetBonds():
                    order = max(1, int(round(bond.GetBondTypeAsDouble())))
                    bond_orders.append([
                        bond.GetBeginAtomIdx() + 1,
                        bond.GetEndAtomIdx() + 1,
                        order,
                    ])
            mean = tuple(sum(c[k] for c in coords) / len(coords) for k in range(3))
            filename = f"{slug}.xyz"
            lines = [str(len(coords)), f"{en} ({zh})"]
            for symbol, xyz in zip(symbols, coords):
                x, y, z = (xyz[k] - mean[k] for k in range(3))
                lines.append(f"{symbol:<3} {x:15.8f} {y:15.8f} {z:15.8f}")
            (OUT / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
            records.append({
                "id": slug, "name_zh": zh, "name_en": en, "formula": formula,
                "category": category, "file": filename, "aliases": aliases,
                "description_zh": desc_zh, "description_en": desc_en,
                "style": "HoukMol", "bonds": bond_orders,
            })
        except Exception as exc:  # noqa: BLE001
            failures.append((slug, str(exc)))
    manifest = {
        "version": 1,
        "title_zh": "中学分子结构库",
        "title_en": "School molecule library",
        "source_note": "3D coordinates generated from molecular graphs with RDKit ETKDGv3 and MMFF/UFF; bundled as static XYZ assets for offline use.",
        "molecules": records,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} molecules to {OUT}")
    if failures:
        print("FAILURES:")
        for item in failures:
            print(" ", item)


if __name__ == "__main__":
    main()
