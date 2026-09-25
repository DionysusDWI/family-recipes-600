---
name: family-recipes-600
description: 《巧做家庭菜600例》单册本地 RAG 知识库。按 series.yml 参数化驱动 S0 形态探测 → S1 逐页转写 → S2 装配 → S3 索引 → S4 向量 → S5 检索 → S6 门禁 → S7 发布；当前进度与已知缺口以 OPEN-ITEMS.md 为准。
---

# family-recipes-600 —— 册级操作手册

> 本件是技能 `series-book-to-rag` 的**册级实例**：流程与纪律来自技能，**具体值全部来自本仓的
> [`series.yml`](series.yml)**。⛔ 本文件不重复技能的通用纪律，只写**本册怎么跑、现在到哪、哪里会红**。
>
> ★ **先读 [`OPEN-ITEMS.md`](OPEN-ITEMS.md)** —— 本仓有**已知会红的门**，不看它会误判成「自己弄坏了」。

## 0 一句话

一本书（**巧做家庭菜600例**，朴丰田 口述 · 穆里／金岩 整理 · 北京科学技术出版社 · 289 页纯图扫描件）
→ 一个可离线检索的本地 RAG 知识库。**先把仪器标定对，再动数据。**

## 1 本册的实测前提（★ 这些是判据的前提，不是背景介绍）

| 前提 | 实测读数 | 后果 |
|---|---|---|
| **无文本层** | 全部 289 页 · 文本层 **0 字符** | 只能走**视觉转写**；任何「抽文本」的捷径都会**静默产出空库** |
| **原生约 96 dpi** | 702×1043 px / 526.5×782.25 pt ⇒ **96.0 dpi**（宽高一致） | `render_dpi: 300` 是 **3.1× 上采样**，**不产生新信息**。★ S1 必须先按「同册已知实例 10/10」**标定**，再定标称 dpi |
| **单页单位图** | 每页 1 张位图，无拼版 | 页↔图一一对应；图版页与正文页**靠版面区分**，⛔ 不能靠位图数量 |
| **离群页 0** | 289 页页尺寸**全部相同** | 无需处理尺寸离群；★ 但**「离群 0」只对页尺寸成立**，不表示体例整齐 |
| **源件带水印** | 文件名含 `Z-Library` | 记名须剥水印；⚠ 引擎**尚未实现**（G-03） |

## 2 当前进度

```
S0 配置校验   8/9   ⚠ 唯一 FAIL 是尺子缺陷 G-01（⛔ 不是配置错）
S0 形态探测   PASS  kb/B01/_book.json · 289 页逐页 · --check 逐字段相同
S1 逐页转写   未开跑 ← 下一个会话从这里开始
S2..S7        未开跑
```

## 3 阶段与判据（本册命令）

```powershell
$R = "…\tasks\20260926-02_family-recipes-600\out\family-recipes-600"; cd $R
```

| 阶段 | 命令 | 出口判据（**可失败**） |
|---|---|---|
| S0 配置 | `python scripts/s0c_series_check.py --series series.yml` | 9/9；⚠ 当前受 G-01 所限为 8/9 |
| S0 形态 | `python scripts/s0_book_shape.py --series series.yml [--check]` | 每册 `_book.json`；`--check` 逐字段相同（**已 PASS**） |
| S1 转写 | `python scripts/s1_transcribe.py --series series.yml --plan` → `--run` | 每页一文件 · `_vision-log.tsv` **0 FAIL** · `_prompt-version.txt` 落盘 · ⛔ 无键 ⇒ `SKIP`（**不是通过**） |
| S2 装配 | `python scripts/s2_build_corpus.py --series series.yml [--dry-run]` | 编号连续 · 每条有制法 · `--check` 逐字节幂等。⚠ **先读 G-02** |
| S3 索引 | `python scripts/s3_build_index.py --series series.yml` | 别名族**由台账派生** · 缺口**双向**检查 |
| S4 向量 | `python scripts/s4_build_vectors.py --series series.yml` | 签名含**模型＋dtype** · 单位范数 · 复跑 `api_calls = 0` |
| S5 检索 | `python scripts/s5_search.py --series series.yml --self-test` | 三态：`0` 全过 / `2` 有 FAIL / **`3` 有不可判（SKIP）** |
| S6 门禁 | `python scripts/verify_gates.py --series series.yml` | 逐册 VERDICT；★ **每道新门先跑反控**（能红才算门） |

## 4 本册特有的注意事项

1. **96 dpi 是硬约束，不是可调参数。** 上采样能把字放大，**不能把没扫到的笔画变出来**。
   ⇒ 若 S1 在「已知实例标定」上做不到 10/10，正确动作是**如实降级并登记**，
   ⛔ 不是把 dpi 调高再假装通过。
2. **`contract` 段目前是出厂默认**（见 `series.yml` 注释）。**必须在 S1 样本上逐项标定**后，
   S2 的 `contract_drift` 读数才有意义。⛔ 标定前不得把「变体命中 0」读成「本册没有变体」。
3. **册码 `B01` 已在 `kb/_BOOKS.tsv` 登记固化**，⛔ 不得由脚本当场排序得到。
4. **源件路径只经 `series.yml` 传入**（本机为 `src` junction）；⛔ 绝对路径不得进任何在册文件。
5. **⛔ 不改 `scripts/`** —— 本仓是技能 P3 验收的被测对象，判据是「**只改配置、不改脚本**」。
   凡需要改脚本才能跑通的地方，一律**登记为缺口**（`OPEN-ITEMS.md`），回填走任务 `20260926-01` 的 P2。

## 5 参考件

| 件 | 用途 |
|---|---|
| [`series.yml`](series.yml) | **唯一接口**；改配置不改脚本 |
| [`OPEN-ITEMS.md`](OPEN-ITEMS.md) | ★ 缺口登记表（逐条带复现命令） |
| [`REPO-SCOPE.md`](REPO-SCOPE.md) | 仓界：隔离、字节保真、源路径与隐私 |
| [`NOTICE.md`](NOTICE.md) | 版权与许可边界 |
| `references/设计说明.md` | 方法总纲：仪器、判据、读数的前提 |
| `references/输出契约.md` | 转写输出契约与**必须容忍的变体** |
| `references/已知坑.md` | 跨系列成立的坑 |
| `kb/_BOOKS.tsv` · `kb/B01/_book.json` | 两份**人工/实测真源** |

★ 技能本体在 `…\.Default_Mixed-task-workspace\.dsh\skills\series-book-to-rag\`
（本仓 `scripts/` 与 `references/` 是它的**复制件**，来源版本见 `REPO-SCOPE.md`／`OPEN-ITEMS.md`）。
