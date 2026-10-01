# 参考文献核验报告 —— GXNU MolStudio 英文稿

核验日期：2026-09-18　　核验对象：`chemrxiv_draft_en.docx` 全部 23 条参考文献 + 数据可用性中的 Zenodo DOI

---

## 一、总体结论

**没有一条参考文献是幻觉。** 23 条全部在公开权威记录中找到对应实体，作者、刊名、年、卷、页码逐项对得上。

但查出 **4 处事实性错误 / 引用规范问题**，其中 2 处建议在投稿前必须改：

| 级别 | 问题 | 影响 |
|---|---|---|
| 🔴 | §2.1 称 Multiwfn 为「4.x 版」——该版本线不存在 | 正文事实错误 |
| 🔴 | 缺 Multiwfn 2024 年 JCP 介绍文章——官网标注为「必须引用」 | 软件引用合规 |
| 🟠 | Ref 8 的 URL 与 Ref 6 完全相同，且是首页而非教程页 | 引用不成立 |
| 🟠 | Ref 3 把 ibo-view.20211019-RevA 称作 "official release"——官网标为 pre-release | GPLv3 衍生声明措辞 |
| 🟡 | Zenodo IGMH_Toolbox 记录描述里页码写成 539–553（正确 539–555） | 属作者其他材料的笔误 |

---

## 二、核验方法

- **Crossref REST API** 直查 DOI 权威元数据（4 条）
- **Crossref 题名反查**（11 条无 DOI 的期刊文献）
- **Zenodo Records API / doi.org 解析**（2 条软件存档 DOI）
- **GitHub API**（1 条源码仓库）
- **一手官方站点**：Multiwfn 官网下载页与更新历史、IboView 官网、计算化学公社原帖 18150、Missouri S&T Scholars' Mine 学位论文库、剑桥大学出版社

---

## 三、逐条核验结果

| # | 文献 | 权威记录 | 结论 |
|---|---|---|---|
| 1 | VMD, *J. Mol. Graphics* 1996, 14, 33–38 | Crossref 10.1016/0263-7855(96)00018-5：Humphrey, Dalke, Schulten；刊名/年/卷/页全对 | 🟢 |
| 2 | Avogadro, *J. Cheminform.* 2012, 4, 17 | Crossref 10.1186/1758-2946-4-17：6 位作者全对，卷 4，文号 17 | 🟢 |
| 3 | Knizia, IboView 程序 | iboview.org 在线，官网标题确为 "IboView -- A program for chemical analysis" | 🟢 实体真，措辞需改（问题 4） |
| 4 | Knizia, *JCTC* 2013, 9, 4834–4843 | Crossref 10.1021/ct400687b | 🟢 |
| 5 | Multiwfn, *J. Comput. Chem.* 2012, 33, 580–592 | Crossref 10.1002/jcc.22885 | 🟢 |
| 6 | Multiwfn, version 2026.4.10 | 官网下载页："Version: 2026.4.10 (Latest version)" | 🟢 |
| 7 | IGMH, *J. Comput. Chem.* 2022, 43, 539–555 | Crossref 10.1002/jcc.26812：43(8), 539–555 | 🟢 |
| 8 | Lu, T. "IGMH/IRI analysis in Multiwfn" | URL 与 Ref 6 逐字相同（sobereva.com/multiwfn 首页） | 🟠 见问题 3 |
| 9 | Mitoraj/Michalak/Ziegler, *JCTC* 2009, 5, 962–975 | Crossref 10.1021/ct800503d | 🟢 |
| 10 | Stone 学位论文, Univ. of Missouri—Rolla, 1998 | Scholars' Mine masters_theses/1747：John Edward Stone, M.S. in Computer Science, Spring 1998 | 🟢 |
| 11 | Zhong, C. vcube 2.0, 公社帖 18150 | 原帖存在（2020-07-15 发布，作者 ggdh）；vcube 启动横幅 "vcube version 2.0 developed by ZhongCheng@whu.edu.cn" | 🟢 |
| 12 | Kozuch & Shaik, *Acc. Chem. Res.* 2011, 44, 101–110 | Crossref 10.1021/ar1000956 | 🟢 |
| 13 | Bickelhaupt & Houk, *Angew.* 2017, 56, 10070–10086 | Crossref 10.1002/anie.201701486 | 🟢 |
| 14 | ADCH, *J. Theor. Comput. Chem.* 2012, 11, 163–183 | Crossref 10.1142/S0219633612500113 | 🟢 |
| 15 | IGMH_Toolbox, Zenodo 10.5281/zenodo.20791253 | Zenodo 记录存在："houcheng-gxnu/IGMH_Toolbox: IGMH_Toolbox v1.0.0 - Initial Release"，2026-06-22 | 🟢 |
| 16 | IRI, *Chemistry–Methods* 2021, 1, 231–239 | Crossref 10.1002/cmtd.202100007 | 🟢 |
| 17 | Knizia & Klein, *Angew.* 2015, 54, 5518–5522 | Crossref 10.1002/anie.201410637 | 🟢 |
| 18 | KoehnLab/iboview (GitHub) | GitHub API 命中，描述 "Patched source code of the IboView program" | 🟢 |
| 19 | Mayer 1983 + 1986 | Crossref 10.1016/0009-2614(83)80005-0（97, 270–274）；10.1002/qua.560290108（29, 73–84） | 🟢 |
| 20 | Weinhold & Landis 专著 | CUP 出版页：2005-06-17，ISBN 9780521831284，DOI 10.1017/CBO9780511614569 | 🟢 |
| 21 | Murray & Politzer, *WIREs* 2011, 1, 153–163 | Crossref 10.1002/wcms.19 | 🟢 |
| 22 | Bader 专著, OUP 1990 | 标准书目一致 | 🟢 |
| 23 | Fukui, *Acc. Chem. Res.* 1981, 14, 363–368 | Crossref 10.1021/ar00072a001 | 🟢 |
| — | 数据可用性 Zenodo 10.5281/zenodo.22821586 | Zenodo 记录存在："GXNU MolStudio: Molecular Visualization and Quantum Chemical Analysis"，Hou, Cheng，2026-09-18 发布，V1.0.0 | 🟢 |

---

## 四、问题详情

### 🔴 问题 1：正文说 Multiwfn 是「4.x 版」，不存在这条版本线

正文 §2.1（原中文稿 §2.1 同样写作「4.x 版」）：

> The analysis back end is the external program Multiwfn (**version 4.x**; the 2026.4.10 binary was used for testing…)

官方证据（Multiwfn 作者 2026-01-13 公告《Multiwfn 3.8 正式版发布！以及未来版本号命名规则的说明》，sobereva.com/762）：

- Multiwfn 3.7 → 2020-08-14
- Multiwfn 3.8 → 2026-01-07 正式发布
- 此后**不再用「累计到一定程度发正式版」的方式，改为直接用更新日期命名**：2026.1.12、……、2026.4.10

下载页当前并列两个版本：「Version: 2026.4.10 (Latest version)」与「Version: 3.8」。**历史中从未有 4.x。**

建议改法：

> …the external program Multiwfn (version 3.8 and later date-versioned releases; the 2026.4.10 build was used for testing during this development cycle)

### 🔴 问题 2：缺 Multiwfn 2024 年 JCP 介绍文章

Multiwfn 官网 "Citing Multiwfn" 一节原文：

> The following original papers of Multiwfn **must be cited** if Multiwfn is used in your work:
> - Tian Lu, Feiwu Chen, *J. Comput. Chem.*, **33**, 580-592 (2012) DOI: 10.1002/jcc.22885
> - Tian Lu, A comprehensive electron wavefunction analysis toolbox for chemists, Multiwfn, *J. Chem. Phys.*, **161**, 082503 (2024) DOI: 10.1063/5.0216272

作者公告亦明确「两篇程序介绍原文（2012 年 JCC 文章和 2024 年 JCP 文章，**应同时引用**）」，Multiwfn 启动界面同时提示这两篇。本文只引了 2012 年那篇。

建议补入（这将新增一条并影响 [5,6] → [5–7] 的引用编号）：

> Lu, T. A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn. *J. Chem. Phys.* **2024**, *161*, 082503. doi:10.1063/5.0216272

### 🟠 问题 3：Ref 8 与 Ref 6 的 URL 完全相同，且指向首页

现稿：

```
6. Lu, T. Multiwfn, version 2026.4.10 [computer software]; http://sobereva.com/multiwfn/ (accessed 2026).
8. Lu, T. IGMH/IRI analysis in Multiwfn; http://sobereva.com/multiwfn/ (accessed 2026).
```

两条指向同一个首页 URL，Ref 8 作为「IGMH/IRI 分析」的出处不成立。实际权威教程页是：

- 《使用 Multiwfn 做 IGMH 分析非常清晰直观地展现化学体系中的相互作用》→ sobereva.com/621（论坛帖 bbs.keinsci.com/thread-28147-1-1.html）
- 《使用 IRI 方法图形化考察化学体系中的化学键和弱相互作用》→ sobereva.com/598（论坛帖 bbs.keinsci.com/thread-23457-1-1.html）

建议改为这两条（或合并为一条含两个 URL）。

### 🟠 问题 4：Ref 3 的「official release」措辞与官网不符

IboView 官网下载页把 **v20211019-RevA 标注为 pre-release**，并把 v20150427 列为 "Last official release"：

> Download IboView v20211019-RevA here (**pre-release**; AVX binaries…)
> Older versions: … **Last official release**: Download IboView v20150427 here

现稿在 GPLv3 衍生作品声明里写 "the port is based on the **official release** ibo-view.20211019-RevA"。此处涉及法律声明，措辞应当精确。

建议改法：

> the port is based on the IboView v20211019-RevA distribution (labelled a pre-release by its author; the last official release is v20150427)

### 🟡 问题 5：Zenodo IGMH_Toolbox 记录的页码笔误

Zenodo 记录 10.5281/zenodo.20791253 的致谢描述中写：

> IGMH method: Lu, T.; Chen, Q. *J. Comput. Chem.* 2022, 43, **539-553**

正确页码是 **539–555**（Crossref、Lu 本人教程帖、多篇引用文献均为此）。本文写作 539–555 是正确的，属于作者另一份材料的下游笔误，建议顺手在 Zenodo 记录里订正。

---

## 五、看着像错、其实没错的两处

- **Ref 5 Multiwfn 2012**：Crossref 的 issued 年份显示 **2011**。那是 Wiley 在线首发时间；卷 33 属于 2012 年，学界通行引用写法就是 2012，**不需要改**。
- **Ref 12 Kozuch & Shaik 2011**：同理，Crossref 显示 2010-12 在线，正刊 44 卷属 2011，**不需要改**。

---

## 六、证据文件

- 原始 API 返回：`ref_audit.txt`（Crossref / GitHub 结构化输出）
- 核验脚本：`verify_refs.py`

---

## 七、修订执行记录（2026-09-18 09:35）

上述 4 处错误已全部修正，英文稿与中文稿同步，**参考文献编号未发生任何变动**。

补 Multiwfn 2024 JCP 原文时，采用了「See also」合并写法（与稿中 Ref 19 合并 Mayer 1983/1986 的既有惯例一致），
因此 `[5,6]` 及其后全部正文引用标记无需重编号。

| 位置 | 修改前 | 修改后 |
|---|---|---|
| §2.1 正文 | Multiwfn (version **4.x**) | Multiwfn (version **3.8, released on 2026-01-07, and the subsequent date-versioned releases**) |
| Ref 5 | 仅 2012 年 JCC 原文 | 追加 **See also: Lu, T. *J. Chem. Phys.* 2024, *161*, 082503. doi:10.1063/5.0216272** |
| Ref 8 | `http://sobereva.com/multiwfn/`（与 Ref 6 重复） | `http://sobereva.com/621` (IGMH) 与 `http://sobereva.com/598` (IRI) |
| Ref 3 | the port is based on the **official release** ibo-view.20211019-RevA | the port is based on the IboView **v20211019-RevA distribution, which its author labels a pre-release — the last official release is v20150427** |
| §7 正文 | the port is based on the official release… | 同上措辞 |
| Ref 18 | the port is based on the **official release** (ref 3) | the port is based on the **v20211019-RevA distribution** (ref 3) |

### 已修改的文件

| 文件 | 说明 |
|---|---|
| `chemrxiv_draft_en.docx` / `.pdf` | 英文投稿稿，9 页 A4，已重新导出 |
| `chemrxiv_draft_zh.docx` | 中文稿，同步同一批修订（122 段未增减，自动编号未受影响） |
| `chemrxiv_draft.md` | 英文 md 源 |
| `chemrxiv_draft_zh.md` | 中文 md 源 |
| `software_note_short.md` | 短版软件说明（同样存在 version 4.x 与 official distribution 表述），一并同步 |

修订前的原始文件备份于工作区：`chemrxiv_draft_zh.backup.docx`、`chemrxiv_draft*.md.backup`。

### 尚未处理

- 🔴 `chemrxiv_draft.docx` 与 `software_note_short.docx` 是早前从 md 生成的 docx 副本，**现已过期**，
  仍含 version 4.x 与 official distribution 表述。若要用这两个文件，需从更新后的 md 重新生成。
- 🟡 Zenodo 记录 `10.5281/zenodo.20791253`（IGMH_Toolbox）描述中的页码 539-553 需在 Zenodo 网站上手动订正。
- 🟡 Multiwfn 官网另**建议**一并引用 IGMH 勘误文（ChemRxiv 2022, doi:10.26434/chemrxiv-2022-g1m34）。
  属「建议」而非「必须」，本次未加入，可由作者决定是否补。

