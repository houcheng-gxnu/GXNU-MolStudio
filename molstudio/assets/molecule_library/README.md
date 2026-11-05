# 内置中学分子结构库

本目录包含 68 个常用分子的离线三维坐标（标准 XYZ）和
`manifest.json` 元数据。MolStudio 在运行时只读取这些静态文件，
不要求安装 RDKit。

坐标由分子图经 RDKit ETKDGv3 生成三维构象，并用 MMFF94/UFF
做几何优化。它们用于教学展示，不代表特定量子化学计算级别的
能量最低结构。

`manifest.json` 记录中文名、英文名、化学式、分类、别名和说明。
重新生成资源可运行仓库根目录的：

```powershell
python tools/generate_molecule_library.py
```
