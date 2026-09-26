# family-recipes-600 —— 《巧做家庭菜600例》知识库仓

> **这是什么**：一本书（朴丰田 口述 · 穆里／金岩 整理 · 北京科学技术出版社）的**本地 RAG 知识库工程仓**。
> 它是技能 [`series-book-to-rag`](../../../../../.dsh/skills/series-book-to-rag/) 的**第一个单册实例**，
> 也是该技能「**只改配置、不改脚本**」这条 P3 验收判据的**被测对象**。
>
> **仓根＝知识库仓根**。引擎、配置、方法文档、台账、转写与索引**同在一棵树内** ⇒ 可离线检索。

---

## 1 状态（截至 2026-09-26）

| 项 | 读数 | 怎么得到的 |
|---|---|---|
| 书名（印本） | **巧做家庭菜600例** | p0000 封面实读（会话内视觉 · 200 dpi） |
| 册数 | **1**（`B01`） | `kb/_BOOKS.tsv`（人工登记真源） |
| 源件 | 49,459,704 B · **289 页** | `s0_book_shape.py` 逐页实测 |
| 形态 | 纯图 PDF · 无文本层 · 单页单位图 | 同上（首 20 页 0 字符） |
| 原生分辨率 | **约 96 dpi**（702×1043 px / 526.5×782.25 pt） | 同上（⇒ `render_dpi: 300` 是上采样，待 S1 标定） |
| S0 配置校验 | ✅ **9 / 9 PASS**（G-01 随引擎同步修好；此前 8/9 是**旧引擎的尺子缺陷**） | `s0c_series_check.py` |
| 转写（S1） | ✅ **289 / 289 · FAIL 0** · 1,413,906 token · 233 min | `kb/B01/_pages/` 289 件 ＋ `_vision-log.tsv` |
| 索引／向量／检索 | ⛔ 未开跑 | |
| 门禁（G 系列 · 逐册） | ⛔ 未开跑（⚠ 且 G4 现在会记 **SKIP：需重算** —— 见下「引擎」行） | `verify_gates.py` |
| 门禁（R 系列 · 仓级） | ★ **已建** · 现读数 **`FAIL R1`（如实报红）** | `repo_check.py` |
| 引擎 | ★ `scripts/` 已同步至技能 **v0.1.3**（内容指纹 `36d4d938e661ce35`） | `ENGINE.lock` ＋ `scripts/_ENGINE` |
| 发布 | ⛔ 未做（无远端，按裁定 R4 口径） | |

### ★★ 引擎身份：本仓现在**无法再静默分叉**（缺口 G-17）

`scripts/` 是技能 `series-book-to-rag` 的一份**只读快照**。此前技能侧继续修 bug 而本仓不同步，
于是**同一条命令在两处给出两个答案**（`privacy_audit` 行号 `@L1` vs `@L5`；`s0c` **8/9** vs **9/9**）。

现在有两个量**分工不同、缺一不可**：

| 量 | 位置 | 性质 |
|---|---|---|
| **内容指纹** `engine_id` | 由 `scripts/_engine.py` 对所有 `*.py` 现算 | ★ **承重**：改一个字节就变，⛔ 不靠谁记得升版本号 |
| **版本标签** | 技能根 `VERSION` ↔ `scripts/_ENGINE` | 人读；★ 两者不等即错（反控 `L` 钉住） |

`ENGINE.lock` 记的是**产物出处**的引擎，⛔ **不是**当前 `scripts/` 的引擎。
两者不等 ⇒ ★ **产物需按现行引擎重建**，这正是 `repo_check.py` R1 现在报红的那件事：

```
产物出处 a4de1b96b41782ce  ｜  现行 36d4d938e661ce35  ⇒ ★ 不一致
```

★ `repo_check.py --accept-engine --reason "<理由>"` 是**唯一**的改锁入口，⛔ **无理由不接受**，
且每次改锁都追加到 `ENGINE.log` —— 它⛔ **不是「一键消红」**：本脚本无法知道你究竟有没有重建。

★ **诚实声明**：本仓目前是**骨架 ＋ 已实测的 S0/S1**，⛔ 还不是可检索的知识库；
★ 且 **R1 现在是红的**（产物出自旧引擎）—— 那是**如实读数**，⛔ 不是待修的故障。
已知缺口逐条登记在 [`OPEN-ITEMS.md`](OPEN-ITEMS.md) —— 读它比读本节重要。

---

## 2 目录

```
family-recipes-600/                ← 仓根（git rev-parse --show-toplevel 指向这里）
├── series.yml                     ★ **唯一接口**：脚本只读它，⛔ 不内嵌册码/册名/路径
├── SKILL.md                       册级操作手册（怎么用这个仓）
├── OPEN-ITEMS.md                  ★ 缺口登记表（未跑通的地方，逐条有复现命令）
├── REPO-SCOPE.md                  仓界：根在哪、字节保真、隐私与源路径怎么处理
├── NOTICE.md                      版权与许可边界（MIT 覆盖什么、不覆盖什么）
├── LICENSE                        MIT
├── .gitattributes / .gitignore    ★ 字节契约与机器物隔离
├── ENGINE.lock                    ★ **产物出处**引擎的指纹与版本（≠ 当前 scripts/ 的引擎）
├── repo_check.py                  ★ **仓级 R 系列**门（R1 引擎锁 · R2 版本 · R3 禁止表 · R4 引擎自检）
├── config/                        密钥模板 ＋ 禁止串表（真钥⛔ 不入仓）
├── scripts/                       参数化引擎（复制自 skill，⛔ 不是引用）＋ `_engine.py`／`_ENGINE`
├── references/                    方法文档（通用纪律）
├── kb/
│   ├── _BOOKS.tsv                 ★ 册码登记表（人工真源，登记即固化）
│   └── B01/
│       ├── _book.json             S0 实测形态（289 页逐页读数）
│       └── _pages/                S1 逐页转写 ✅ 289 件 ＋ `_vision-log.tsv`
└── (仓内**没有**源件入口)          ★ 源件入口是任务槽根的 junction `src-in`（见 REPO-SCOPE §3）
```

---

## 3 怎么跑（按阶段）

```powershell
$R = "<本仓根>"   # 例：<工作区根>\tasks\20260926-02_family-recipes-600\out\family-recipes-600
cd $R

# S0 配置校验（★ 现在 9/9 PASS —— 旧引擎下是 8/9，那是尺子缺陷 G-01）
python scripts/s0c_series_check.py --series series.yml

# ★ 仓级 R 系列门（⛔ 不属于技能本体）—— 先跑它，它最先告诉你「引擎有没有分叉」
python repo_check.py
# 若产物**确实**已按现行引擎重建，才可改锁（⛔ 必须给理由，且会记入 ENGINE.log）：
#   python repo_check.py --accept-engine --reason "<为什么可以认为产物已重建>"

# S0 形态探测（幂等；--check 重新探测并与在盘 _book.json 逐字段比对）
python scripts/s0_book_shape.py --series series.yml
python scripts/s0_book_shape.py --series series.yml --check

# S1 逐页转写：先计划（⛔ 零请求），确认无误再 --run（要 DASHSCOPE_API_KEY）
#   ★ 本仓 B01 已转完 289/289，`--plan` 现在报「待转写 0 页」；重跑**幂等**。
python scripts/s1_transcribe.py --series series.yml --plan
python scripts/s1_transcribe.py --series series.yml --run --max-pages 3

# S2 装配 —— G-02 已修：S1 写、S2 读共用 `scripts/_paths.py` 一个函数
python scripts/s2_build_corpus.py --series series.yml --dry-run
```

---

## 4 语言与约定

| 场合 | 语言 |
|---|---|
| 文件名 / 目录名 / 代码 / 册码 | ASCII |
| `README.md` · `OPEN-ITEMS.md` · `NOTICE.md` · `REPO-SCOPE.md` | 简体中文 |
| `series.yml` 注释、`SKILL.md` | 中文（面向人），键名 ASCII（面向工具） |

★ 引用原文（封面、版权页、转写件）**保留其本来面目，⛔ 不翻译、⛔ 不润色**。
