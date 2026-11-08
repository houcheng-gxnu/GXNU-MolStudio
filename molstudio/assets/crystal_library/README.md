# 中学晶体结构库

本目录是 MolStudio「结构库 → 晶体」页的离线数据，共 43 个晶胞。
运行时只读静态 CIF 与 PNG 预览，不需要联网，也不依赖 Avogadro2。

## 数据来源与致谢

绝大多数 CIF 来自 Avogadro2 自带的 `crystals` 数据插件：
Geoffrey Hutchison 等，Open Chemistry crystals data set，https://github.com/openchemistry/crystals（public domain）。
原始结构来自 Crystallography Open Database（COD，http://www.crystallography.net/）、American Mineralogist Crystal Structure Database（AMCSD）与 International Zeolite Association。每个 CIF 都保留了原始文件头里的文献与数据库编号，在此向 COD、AMCSD 及原结构测定者致谢。

其中 `po-simple-cubic.cif`（简单立方钋）、`dry-ice.cif`（干冰）与 `white-phosphorus.cif`（白磷 P₄）是 MolStudio 为教学补写的**简化模型**，不是实验结构：干冰把 4 个 CO₂ 分子按面心立方排布并统一取向（真实 Pa3 结构分子取向交错），白磷只放了一个 P₄ 四面体分子。请在课堂上说明这一点。

冰 Ih、α-石英、CaTiO₃ 等 CIF 是实测结构，与教材里的理想化模型（例如理想立方钙钛矿、P6₃/mmc 冰）可能略有差别；库里另收 `SrTiO3-Tausonite.cif` 作为理想立方钙钛矿模型。

## 重新生成

```powershell
python tools/build_crystal_library.py
```
