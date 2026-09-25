# OPEN-ITEMS.md —— 本仓的缺口登记表

> **本仓是技能 `series-book-to-rag` 的 P3 验收对象**。P3 的判据是：
> **「只改配置、不改脚本」才算通过；任何需要改脚本才能跑通的地方，登记为缺口、回填 P2。**
> ⇒ 本表就是那条判据的**产出**。⛔ 本仓不就地改引擎（改了就等于把缺口藏起来）。
>
> 每条缺口都带**复现命令**与**实测读数**。★ 读本表比读 `README.md` 重要。

登记于 **2026-09-26** · 全部为**本机实测**（Python 3.13.5 · Windows · PowerShell）。

---

## 0 一览

| # | 类 | 一句话 | 影响 | 归属 |
|---|---|---|---|---|
| **G-01** | 尺子 | 配置校验器的「占位符」判据把**正则命名组**当成未替换占位符 | ⛔ **阻断** S0 收尾（8/9，exit 2） | P2 |
| **G-02** | 集成 | S1 写 `kb/<code>/_pages/`，S2 读 `pages_root/<code>/` ⇒ 无配置值可接通 | ⛔ **阻断** S2 | P2 |
| **G-03** | 判据未实现 | G5 声明「水印 0」，但引擎**无** `clean_basename`，产物里真的带着水印 | ⚠ 发布前必炸 | P2 |
| **G-04** | 硬编码 | G5 的禁令字面写死在代码里，⛔ 不可配置 | ⚠ 换册即失效 | P2 |
| **G-05** | 工具边界 | `privacy_audit.py` 的 `rglob` **穿过**仓内 junction，把源卷 19 个 PDF 当本仓文件 | ⚠ 假读数 / 可能误打包 | P2 |
| **G-06** | 命名漂移 | 技能找仓根 `privacy-forbidden.local.txt`，同门仓用 `config/forbidden-fragments.local.txt` | ⚠ 禁止表静默失效 | P2 |
| **G-07** | 报错定位 | 本机禁止串命中**一律**报 `@L1`（bug：`lit.find(lit)` 应为 `txt.find(lit)`） | ⚠ 读数不可用 | P2 |
| **G-08** | 缺豁免 | 审计不豁免「**声明表**」⇒ 任何禁了某串的仓都会**永久假红** | ⚠ 门被迫说谎 | P2 |

★ **本仓为「只改配置」付出的代价**：G-01 / G-02 两条是**硬阻断**，即
**当前无法只靠配置跑通 S1→S2**。这正是 P3 想验出来的东西。

---

## G-01 配置校验器的「占位符」判据是坏尺子（⛔ 阻断）

**症状**：`s0c_series_check.py` 报 `[FAIL] placeholders-replaced 未替换：['<marker>','<text>','<title>']`。

**根因**（两处，已用最小探针分离）：

| 触发源 | 例 | 是否配置错 |
|---|---|---|
| **正则命名组** `(?P<name>…)` | `glossary_pattern` 里的 `(?P<marker>…)` | ⛔ **不是**：引擎**要求**命名组 |
| **注释里的尖括号** | 我自己写的 `产物落 ./kb/<册码>/` | ✅ 是我的错，已修 |

判据是 `PLACEHOLDER_RE = re.compile(r"<[^<>]{1,60}>")` 对**整个文件原文**做 `findall`
⇒ 它分不清「模板占位符」与「正则语法」与「文档举例」。

**★ 决定性证据：技能用它自己的回归夹具打自己的脸**

```powershell
$K = "…\.dsh\skills\series-book-to-rag"
python "$K\scripts\s0c_series_check.py" --series "$K\examples\toy-series\series.yml"
#  [FAIL] placeholders-replaced  未替换：['<code>', '<marker>', '<text>', '<title>', '<名>', '<标题>']
#  通过 8 / 9    exit=2
```

**引擎确实需要命名组**（`scripts/s2_build_corpus.py`）：

```
L201:  glossary.append({"marker": m.group("marker"), "title": m.group("title"), …
```

⇒ **任何**会解析注释区的真实配置都过不了这道门 ⇒ **不是配置错，是尺子坏**。

**为什么 P1 没发现**：P1 的冒烟配置是 `examples/example-series.yml`，它**没有 `contract:` 段**、
也没有带尖括号的注释 ⇒ 9/9。**唯一能抓到这个缺陷的夹具从未被那道门跑过。**
（与技能自己写的纪律同族：**「每道门都要有反控；不会红的断言不是门」**——这里是反过来：
**一道会假红的门，也不需要被跑过才会暴露，但需要有人拿对的输入去跑它**。）

**建议修法（⛔ 未应用）**：把判据限定在**值位置**，或排除 `(?P<` 形态与 `#` 注释行。

## G-02 S1 的写路径与 S2 的读路径对不上（⛔ 阻断 S2）

| 端 | 位置 | 路径 |
|---|---|---|
| S1 **写** | `s1_transcribe.py` L132 / L146 | `<out_root>/kb/<code>/_pages/pNNNN.md`（**硬编码**） |
| S2 **读** | `s2_build_corpus.py` L279 | `<pages_root>/<code>/p*.md` |

要让二者相等需要 `pages_root/<code> == out_root/kb/<code>/_pages`，
而 `pages_root` 只与册码做**一次**拼接 ⇒ **不存在**这样的取值（任何取值都不行）。

**玩具系列为什么没抓到**：它用**独立夹具** `pages-fixture/` 绕过 S1 —— 夹具是**手摆**的，
所以 S1 与 S2 **从未真正首尾相接**跑过一次。

**本仓的当前表现（诚实且响亮）**：`series.yml` 取 `pages_root: "kb"`，
S2 会报 `[FAIL] B01 无 _pages/：…\kb\B01` ⇒ **红，但不静默**。

**建议修法（⛔ 未应用）**：`s2` 改为 `pages_root/<code>/_pages`，或 S1/S2 都从配置取**同一段**相对路径。

## G-03 G5 的「水印 0」判据**声明了但没实现**

- `SKILL.md` §6 与 `templates/gates.md` G5 都写着：「产物里无绝对路径／**无水印**／无令牌」。
- 实现侧：`verify_gates.py` 的 G5 = `ABS_RE` 查绝对路径 ＋ `BANNED` 两条字面。**没有水印判据。**
- 引擎侧：S0 把源件名**原样**写进产物（无 `clean_basename`）。

**实测**（本册正好是**第一个真实带水印的实例**）：

```
kb/B01/_book.json  L11:  "basename": "巧做家庭菜600例 (朴丰田口述； 穆里, 金岩整理) (Z-Library).pdf",
```

⇒ 水印**已经在产物里**，而 G5 不会红。★ 与已知坑 **#81**（「先问『它扫到自己会怎样』」）同族，
但方向相反：这次是**该扫的没扫**。

## G-04 G5 的禁令是硬编码的

```python
scripts/verify_gates.py L32:  BANNED = ["<tmp>", "forbidden-fragments.local"]
```

册与系列的禁令应当来自 `config/forbidden-strings.txt`（本仓已建该表）。
⛔ 现在它**没有任何读者**。

## G-05 走文件系统的工具会**穿过**仓内链接（★ 已实测，本仓已规避）

**实测**：首版把源件入口做成**仓内** junction `src/` ⇒ 隐私复审逐件清单变成 **50 件**，
其中 **19 件**是 `src/**`，即源卷上**另外 18 部书**的 PDF。三处读数：

```
首版（junction 在仓内）: 逐件 PASS 50 · FAIL 0（共 50 件）   src/ 前缀 19 · 含 .pdf 19
修后（junction 在仓外）: 逐件 PASS 31 · FAIL 0（共 31 件）   src/ 前缀  0 · 含 .pdf  0
```

★ **`.gitignore` 挡得住 `git add`，⛔ 挡不住走 `rglob` 的工具。**
本仓的规避：把 junction 放在**任务槽根**（`<slot>/src-in`），由 `source_root: "../../src-in"`
以相对路径指过去 ⇒ 以**仓根**为起点的工具够不到源卷。

⚠ **技能本体仍有此隐患**：`privacy_audit.py` 的 `SKIP_DIRS = {__pycache__, .git, out, scratch}`
不含任何「外部挂载点」。谁把链接放进技能树，它就跟谁走。
★ 附带风险：`pack_release.py` 若同样走文件系统而非 `git ls-files`，会把源卷**打进发布体**（未实测）。

## G-06 本机禁止表的**文件名有两套**，且互不认识

| 侧 | 期望的路径 |
|---|---|
| 技能 `scripts/privacy_audit.py::load_local()` | 仓根 **`privacy-forbidden.local.txt`**（且写进了 `SELF` 豁免表） |
| 同门仓 `skill-chinese-famous-recipes` | **`config/forbidden-fragments.local.txt`** |

**实测后果**（用错名字时）：

```
本机禁止表：0 条（**不存在** ⇒ 只跑形状规则）
```

⇒ 禁止表**静默失效**，而审计**照样报 PASS**。★ 与「无键 ⇒ SKIP，⛔ 不是通过」是同一族问题：
**一个"没找到"必须以"不可判"的姿态出现，不能以"通过"的姿态出现。**

**本仓处置**：采用**技能的**名字（仓根 `privacy-forbidden.local.txt`），旧的 `config/…` 版本已移除。

## G-07 禁止串命中的行号**永远是 L1**

```python
scripts/privacy_audit.py L88:
  labels.append("本机禁止串@L%d" % (txt[:lit.find(lit)].count("\n") + 1 …))
                                  ^^^^^^^^^^^^^^ 应为 txt.find(lit)
```

`lit.find(lit)` 恒为 `0` ⇒ `txt[:0]` ⇒ 行号**恒为 1**。
**实测**：一次运行里 **6 条**命中**全部**报 `@L1`，包括实际落在文件末尾的那种。
⇒ 这条读数**不可用于定位**。

## G-08 审计缺「声明豁免」⇒ 禁了什么，就必须**写出**什么，于是永久假红

**实测**：把 `[watermark] Z-Library` 也放进**本机禁止表**（而不是在册的
`config/forbidden-strings.txt`）后，审计**从 1 条 FAIL 涨到 7 条**，其中 **6 条**是
「为了禁止它而不得不写出它」的文件：

```
config/forbidden-strings.txt · kb/_BOOKS.tsv · kb/B01/_book.json · NOTICE.md · series.yml · SKILL.md
```

其中 `kb/B01/_book.json` 是**真命中**（G-03），其余 5 条是**声明**。
技能已经知道这个坑（`config/forbidden-strings.txt` 的注释里写着「本表自身必须被门豁免」），
但 `privacy_audit.py` 的 `SELF` 只豁免**本机禁止表 ＋ 3 个脚本**，⛔ 不豁免**在册声明表**。

**本仓处置**（按职责拆表，⛔ 不是删禁令）：

| 表 | 放什么 | 谁负责 |
|---|---|---|
| `privacy-forbidden.local.txt`（仓外/忽略） | **本机物**：本机路径名 | `privacy_audit.py` |
| `config/forbidden-strings.txt`（在册） | **在册声明**：来源水印、通用约定 | 门 G5 —— ⚠ **尚未实现，见 G-03** |

---

## 非缺口：本仓已实测通过的读数（备查）

```
S0c 配置校验      8/9       唯一 FAIL = G-01（尺子）
S0  形态探测      PASS      B01 289 页 · 49,459,704 B · 众数 526.5×782.2 pt / 702×1043 px
                            文本层 0 字符 · 离群 0 页 · 原生 96.0 dpi（宽高一致）
S0  --check       PASS      shape 段逐字段相同（幂等）
隐私复审          PASS 31/31 本机禁止表 1 条（存在）· src/ 前缀 0 · 含 .pdf 0
```

★ **一处过程自纠（记录在案）**：我第一版的 `series.yml` 注释里写了
「在册配置里出现**盘符绝对路径**会让隐私复审 FAIL」—— **那条注释自己就把隐私复审弄 FAIL 了**
（它把被禁的字面**逐字写出**）。这是已知坑 #81 的又一次现场重演：
**写规则的时候，先问「它扫到自己会怎样」**。同类共有**四处**，全部由**门**抓出、全部已修：

| # | 位置 | 怎么被发现的 |
|---|---|---|
| 1 | `series.yml` 的注释（解释规则的**那条注释**） | `privacy_audit.py` → `绝对路径(盘符)` |
| 2 | `README.md` 的示例命令 `$R = "…"` | 同上 |
| 3 | `REPO-SCOPE.md` 的机制示意图 | 同上 |
| 4 | ★ **本文件自己**（在讲这条教训时又写了一次那个字面） | 同上 |

★★ ⇒ 立一条可操作的纪律：**引用机器相关的字面时，⛔ 一律写成类名（「盘符绝对路径」），
绝不写出实例** —— 因为**门只看字节，不看你的意图**。

---

## 回填去向

**全部 8 条都属任务 `20260926-01_series-book-to-rag` 的 P2**（技能本体），
⛔ **不在本仓就地改引擎** —— 本仓是 P3 的**被测对象**，改了就等于把缺口藏起来。
