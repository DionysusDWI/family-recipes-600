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
| S0 配置校验 | **8 / 9**（唯一 FAIL 是**尺子缺陷** G-01） | `s0c_series_check.py` |
| 转写（S1） | ⛔ **未开跑** | 下一个会话 |
| 索引／向量／检索 | ⛔ 未开跑 | |
| 门禁（G/R 系列） | ⛔ 未开跑 | |
| 发布 | ⛔ 未做（无远端，按裁定 R4 口径） | |

★ **诚实声明**：本仓目前是**骨架 ＋ 已实测的 S0**，⛔ 不是可检索的知识库。
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
├── config/                        密钥模板 ＋ 禁止串表（真钥⛔ 不入仓）
├── scripts/                       参数化引擎（复制自 skill，⛔ 不是引用）
├── references/                    方法文档（通用纪律）
├── kb/
│   ├── _BOOKS.tsv                 ★ 册码登记表（人工真源，登记即固化）
│   └── B01/
│       ├── _book.json             S0 实测形态（289 页逐页读数）
│       └── _pages/                S1 逐页转写（⛔ 尚未生成）
└── (仓内**没有**源件入口)          ★ 源件入口是任务槽根的 junction `src-in`（见 REPO-SCOPE §3）
```

---

## 3 怎么跑（按阶段）

```powershell
$R = "<本仓根>"   # 例：<工作区根>\tasks\20260926-02_family-recipes-600\out\family-recipes-600
cd $R

# S0 配置校验（★ 现在会 8/9 —— 唯一 FAIL 是尺子缺陷 G-01，见 OPEN-ITEMS.md）
python scripts/s0c_series_check.py --series series.yml

# S0 形态探测（幂等；--check 重新探测并与在盘 _book.json 逐字段比对）
python scripts/s0_book_shape.py --series series.yml
python scripts/s0_book_shape.py --series series.yml --check

# S1 逐页转写：先计划（⛔ 零请求），确认无误再 --run（要 DASHSCOPE_API_KEY）
python scripts/s1_transcribe.py --series series.yml --plan
python scripts/s1_transcribe.py --series series.yml --run --max-pages 3

# S2 装配 —— ⚠ 先读 OPEN-ITEMS.md G-02（S1 写入路径与 S2 读取路径不一致）
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
