#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S2 —— **装配**：`_pages/` → `corpus/{recipes,blocks}.jsonl` ＋ `all.txt` ＋ `glossary.jsonl` ＋ `_meta.json`。

★ 本件是**技能里最难的一块**：它必须容忍 `references/输出契约.md` §2 的**五种变体**，
  ⛔ 而判据只有一条 —— **编号连续 ＋ 每条记录都有制法**（变体没处理干净时，这两条会红）。

判据（可失败）：
  ① `numbers_contiguous`：编号连续（**口径由 `contract.numbering` 决定** —— 见下）
  ② `every_recipe_has_method`：每条记录 ≥1 个制法块
  ③ `no_numeric_only_step_block`：⛔ 不存在「正文只是一个步号」的步骤块
  ④ `placeholders`：`⟦?⟧` 记号计数（**如实报出，⛔ 不当错误**）
  ⑤ `--check`：重新装配并与在盘产物**逐字节比对**（幂等）
  ⑥ `contract_drift`：五种变体各命中多少，逐项写进 `_meta.json`（★ 这是改提示词的直接依据）

★★ 编号口径（`contract.numbering`）—— 缺口 **G-19**：
  · `book_global`（默认，向后兼容）：印刷体编号在**全册**唯一，门判 `1..N`。
  · `per_chapter`：印刷体编号**每章从 1 重起**（实测《巧做家庭菜600例》：章 28 · 重起 23）。
    此时门判「**每个章内 1..len(章)**」，且 `recipe_id` **带上章序号**以免撞号。

★★ 中文数字编号（缺口 **G-18**）—— `contract.number_style`：
  `arabic`（默认）· `chinese` · `mixed`。⛔ 绝不能让使用者「拼一个能 int 的正则」：
  正则只能**筛**，`int()` 才能**读**。本件把「筛」与「读」分开，并**同时保留 `number_raw`**（印本原样）。

用法：
    python s2_build_corpus.py --series <series.yml> [--book CODE] [--check] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import pages_dir as resolve_pages_dir                # noqa: E402

SPACE = re.compile(r"\s+")

# ── 印本标点：**只用于比对**（缺口 G-22）★ ⛔ 不改写原文
BRACKETS = "〔〕【】[]（）()〈〉《》"
EDGE = re.compile(r"^[%s]+|[%s：:]+$" % (re.escape(BRACKETS), re.escape(BRACKETS)))
# 行内节名：`〔主料〕 值`（缺口 G-22b —— 引擎原先只认「整行就是节名」）
INLINE_SEC = re.compile(r"^\s*[〔\[【]\s*([^〕\]】]{1,10}?)\s*[〕\]】]\s*(.*)$")
# 目录行：`…{2,}` ＋ 2–3 位页码（缺口 G-21）
# ★★ 页码**可能带括号**（`清汤示例…………（1）`）—— 玩具夹具正是这一形态。
#   ⛔ 这一格曾**默默承重**：旧引擎把 `1. 清汤示例…………（1）` 拒收（`1.` 读不出号），
#   于是「拒收」意外挡住了目录幻影；G-25 修好尾随点号之后，它**立刻变成一条幻影食谱**。
#   ⇒ 目录判据必须**自己**认得这种行，⛔ 不靠拒收兜底。
TOC_LINE_DEFAULT = r"[…·]{2,}\s*[（(]?\s*\d{1,3}\s*[）)]?\s*$"

# ── 中文数字 → int（够本册用：一～九十九）
CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "两": 2}


def cn2int(s):
    """中文数字 ⇒ int；判不出来返回 None。★ 只读，⛔ 不改写。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, _, b = s.partition("十")
        tens = CN_DIGIT.get(a, 1) if a else 1
        ones = CN_DIGIT.get(b, 0) if b else 0
        if (a and a not in CN_DIGIT) or (b and b not in CN_DIGIT):
            return None
        return tens * 10 + ones
    return CN_DIGIT.get(s)


def norm(s: str) -> str:
    """★ 归一化**只用于比对与识别**，⛔ 不改写原文（原文进 blocks.text）。

    ⛔ 本函数**去掉空白而已** —— 它喂给 `name` 等**进产物**的字段。
    ★ 剥印本标点的是**另一个**函数 `norm_key()`：两者的作用域不同，
      ⛔ 不要合并（合并会把 `四拔汤（又名：…）` 的括号从**产物**里抹掉）。
    """
    return SPACE.sub("", s).strip()


def norm_key(s: str) -> str:
    """**仅供查表**：`norm()` ＋ 剥掉首尾印本标点与冒号。

    ★ 为什么需要它（缺口 G-22）：提示词要求节名「**按印本原样**」，印本写的是 `〔主料〕`；
      而契约声明的是裸名 `主料`。原文实测 `@@SECTION` 2540 行里 **1747 行带 〔〕**，
      ⇒ 不剥标点则**节名比对整类失效**（内容掉块，且产物**看起来正常**）。
    """
    return EDGE.sub("", norm(s))


def load_series(p):
    import yaml
    cfg = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    base = Path(p).resolve().parent
    s = cfg["series"]
    s["_base"] = base
    s["_out"] = (base / str(s["out_root"])).resolve()
    # ★ `_pages/` 的落点由 scripts/_paths.py **单点决定**（缺口 G-02：⛔ 不在这里手拼）
    s["_contract"] = cfg.get("contract", {})
    return cfg, s


class Contract:
    def __init__(self, c):
        self.c = c
        sec = c.get("sections", {})
        self.sec_of = {}
        for canon, spellings in sec.items():
            for sp in spellings + [canon]:
                self.sec_of[norm_key(sp)] = canon
        grp = c.get("groups", {})
        self.grp_of = {}
        for canon, spellings in grp.items():
            for sp in spellings:
                # ★ 配置里的写法**可能自带冒号**（`主 料：`）⇒ 建表时统一剥掉，⛔ 不要在这里再拼一个
                #   （实测踩过：拼成 `主 料：：` ⇒ 变体④ 一条都识别不到，而产物**看起来正常**）
                self.grp_of[norm_key(sp).rstrip("：:")] = canon
        self.step_res = [re.compile(p) for p in c.get("step_number_patterns", [])]
        self.num_re = re.compile(c.get("recipe_number_pattern", r"^\d{1,4}$"))
        self.gloss_re = re.compile(c.get("glossary_pattern", r"^$"))
        # ── 本轮新增（G-18/G-19/G-20/G-21）
        self.numbering = c.get("numbering", "book_global")
        self.number_style = c.get("number_style", "arabic")
        self.chapter_re = re.compile(c["chapter_pattern"]) if c.get("chapter_pattern") else None
        # ★ G-29：**子类**（章 → 子类 → 子类内编号重起）的形态。
        #   ⛔ 单独看它**不足以**判定子类 —— `（N）名字` 既是真子类标题、又是被漏标的食谱标题，
        #   行形态**不可区分**（实测：放宽正则 ⇒ 断号章 14 → 20，更差）。
        #   ⇒ 判据是**两个条件**：匹配本 pattern **且**下一非空行是 `@@RECIPE_START`。
        self.sub_re = re.compile(c["subchapter_pattern"]) if c.get("subchapter_pattern") else None
        self.bare_step_re = re.compile(c.get("step_number_bare", r"^\d{1,3}$"))
        self.toc_re = re.compile(c.get("toc_line_pattern", TOC_LINE_DEFAULT))
        m = c.get("markers", {})
        self.m_rs = m.get("recipe_start", "@@RECIPE_START")
        self.m_sec = m.get("section", "@@SECTION")
        self.m_step = m.get("step", "@@STEP")
        self.m_foot = m.get("footer", "@@FOOTER")
        self.m_toc = m.get("toc", "@@TOC")
        self.m_cont = m.get("recipe_cont", "@@RECIPE_CONT")

    def section(self, raw):
        return self.sec_of.get(norm_key(raw))

    def group(self, line):
        """裸组名（变体 ④）：`主 料：值` ⇒ (canon, 值) 或 None。★ 查表用 `norm_key`。"""
        t = norm(line)
        for prefix, canon in self.grp_of.items():
            for sep in ("：", ":"):
                if t.startswith(prefix + sep):
                    return canon, t.split(sep, 1)[1]
        return None

    def step(self, line):
        """裸步骤号（变体 ③）：`（1）正文` / `1. 正文` ⇒ (号, 正文) 或 None。"""
        for rx in self.step_res:
            m = rx.match(line.strip())
            if m:
                return m.group(0).strip(), line.strip()[m.end():].strip()
        return None

    def number(self, token):
        """**筛过的 token ⇒ int**（缺口 G-18）。判不出来返回 None。

        ★ 分工：`accept_number()` 负责**筛**（形态），本函数负责**读**（折成整数）。
          ⛔ 两件事混在一起就会出现「正则匹配了、`int()` 崩了」的实测故障。
        """
        t = token
        if not t:
            return None
        if t.isdigit():
            return int(t)
        if self.number_style in ("chinese", "mixed"):
            return cn2int(t)
        return None

    def accept_number(self, tok):
        """★ 缺口 G-18 的**要害**：出厂把编号文法写死成 `^\\d{1,4}$`，于是**筛**这一步
        就把 `（一）` 挡在门外 —— 连 `int()` 都到不了。

        ⇒ 修法**不能**是「让使用者拼一个既能筛中文数字、又能 int 的正则」（不可能），
          而是让 `number_style` **接管这一格**：

            arabic （默认）  形态由 `recipe_number_pattern` 定，且必须全数字（向后兼容）
            chinese          形态由**中文数字读法**定；`recipe_number_pattern` 不再参与
            mixed            二者**任一**成立即可（本册：正文 65.9% 中文数字 ＋ 21% 阿拉伯数字）
        """
        if self.number_style == "arabic":
            return bool(self.num_re.match(tok)) and tok.isdigit()
        if self.number_style == "chinese":
            return cn2int(tok) is not None
        return bool(self.num_re.match(tok)) or cn2int(tok) is not None


_OPEN_BR = "（(〔[【"
_CLOSE_OF = {"（": "）", "(": ")", "〔": "〕", "[": "]", "【": "】"}
_NUM_TAIL = ".．、,，:：;；*＊"
_NUM_HEAD = "*＊"


def norm_num_token(t):
    """编号 token 的**归一**（缺口 G-25／G-26）。⛔ 只用于识别，⛔ 不改写产物原文。

    ★ 两件事必须在这里做完，否则**整类起点会被拒或读错**：
      G-25 尾随点号：`2. 七星子蟹` ⇒ token `2.` ⇒ `isdigit()` False ⇒ **整条被静默拒收**（实测 22 条）
      G-26 内部空白：`（二 十 八）` ⇒ 旧字符类 `[^）)〕\\]\\s]` **排除空白** ⇒ token `二` ⇒ 读成 **2**（印本 28）
    ⇒ 归一 ＝ **去空白 ＋ 剥首尾括号与分隔标点**。⛔ 不在此处折成整数（那是 `number()` 的事）。
    """
    s = SPACE.sub("", (t or "").strip())
    # ★★ 必须**一次性**用整个字符集剥（`strip`/`rstrip` 接过一个集合，与顺序无关）。
    #   ⛔ 曾写成 `for ch in _NUM_TAIL: s = s.rstrip(ch)` —— 那是**逐字符**剥，
    #   `.` 的那一遍先跑、`*` 的那一遍后跑 ⇒ `1.*` 只掉到 `1.` 就停了（实测：真书
    #   p0113 的 `1.* 龙鱼肠鲍鸽蛋` **仍然被整条拒收**，而它在删掉星号后是合法的 1 号）。
    s = s.lstrip(_NUM_HEAD).rstrip(_NUM_TAIL)
    return s


def split_start_diag(C: Contract, rest: str):
    """同 `split_start`，但**多返回一个拒收原因**（缺口 G-28）。

    ★ 为什么必须带原因：没有它，「被拒」在门上**与「重号」长得一样** ——
      实测：被拒 9 条落在 `十八、粗菜类`，而该章门诊断是「缺 [] ＋ 重号 [1,3,4,5,6,7,10]」，
      **缺号列表是空的**，因为重复号把空档填满了。⇒ 丢内容**不可见**。
    """
    s = (rest or "").strip()
    if not s:
        return None, None, None, "empty"
    s = re.sub(r"^[*＊]\s*", "", s)                       # `*`/`＊` 前缀（实测 10 条）
    raw, name = None, ""
    if s[0] in _OPEN_BR:
        close = _CLOSE_OF[s[0]]
        i = s.find(close, 1)
        if i > 0:
            raw, name = s[1:i], s[i + 1:].strip()
        else:                                            # 未闭合 ⇒ 退回到「首个空白为止」
            m = re.match(r"^[（(〔\[]\s*(\S{1,12})\s*(.*)$", s)
            raw, name = (m.group(1), m.group(2).strip()) if m else (None, "")
    else:
        # 无括号 ⇒ **空格分界**（`2. 七星子蟹` / `1.* 龙鱼肠鲍鸽蛋` / `1 芙蓉干贝`）；
        # ★ 整行无空格（如 `四拔汤（又名：…）`）⇒ 不是有号起点，⛔ 不猜。
        m = re.match(r"^(\S{1,12})\s+(.*)$", s)
        raw, name = (m.group(1), m.group(2).strip()) if m else (s, "")
    if raw is None:
        return None, None, None, "no-token"
    tok = norm_num_token(raw)
    if not C.accept_number(tok):
        return None, None, None, "unnumbered"            # ★ 印本无编号（G-27）
    n = C.number(tok)
    if n is None:
        return None, None, None, "number-unreadable"
    if not name:
        return None, None, None, "no-name"
    return raw, n, name, "ok"


def split_start(C: Contract, rest: str):
    """起点行的 `rest` ⇒ (number_raw, number_int, name) 或 (None, None, None)。

    ★ 兼容 `@@RECIPE_START （一） 红烧示例` · `(五)鱼`（**无空格**）· `*（六） X` · `〔二〕 X`
      · `2. 名`（尾随点号，G-25）· `（二 十 八） 名`（编号内含空格，G-26）。
    ★ `number_raw` 保留**印本原样**（只剥掉外层括号），⇒ 归一后若号有变，仍可逐条复核。
    """
    raw, n, name, _why = split_start_diag(C, rest)
    return raw, n, name


def assemble(book_code, pages_dir, contract, cfg_series):
    """返回 (products dict[relpath]→text, stats dict)。★ 纯函数：同样的输入必得同样的输出。"""
    C = contract
    recipes, blocks, glossary = [], [], []
    cur = None
    sec = None
    grp = None
    chapter = ""
    chap_seq = 0
    sub_chapter = ""                       # ★ G-29：子类标题
    sub_seq = 0                            # ★ G-29：本**章内**的子类序号
    scope = ("C", 0, 0)                    # ★ G-29：**编号作用域**（章或子类）
    pending_step = None                    # ★ G-20：`@@STEP <n>` 后正文另起一行
    rejected = []                          # ★ G-28：被拒起点（具名）
    starts_body = [0]                      # ★ G-28：非目录页上的 `@@RECIPE_START` **行数**
    opens_variant1 = [0]                   # ★ G-28：变体①（整页无标记）开出的起点数（**无标记行**）
    drift = {"variant1_pages_no_marker": [], "variant2_inline_step": 0,
             "variant3_bare_step": 0, "variant4_bare_group": 0, "section_spellings": {},
             "variant5_inline_section": 0, "toc_pages": [], "toc_lines_skipped": 0,
             "subchapters": [], "rejected_reasons": {}}
    step_seq = 0
    bid_seq = 0
    stats_splice = [0]                # ★ 拼接次数（★ 可证伪读数：跨页夹具上应 ≥1）
    marker_cont_page = set()          # 声明「承接上一页」的页
    nomark_pages = set()              # 整页无标记的页（变体①）

    def open_recipe(raw, num, name):
        nonlocal cur, sec, grp, step_seq, pending_step
        ordinal = len(recipes) + 1
        # ★ G-29：`recipe_id` 必须带上**编号作用域**，否则「子类内重起」会让不同菜撞同一个 id
        #   （实测：546 条记录里 470 个唯一 id ⇒ **48 个撞号 id / 124 条记录**，
        #    撞号 id 已写进向量库的同一行空间 ⇒ 检索回引会命中错误的菜）。
        if C.numbering == "per_chapter":
            if scope[0] == "S":
                rid = "%s-C%02d-S%02d-R%03d" % (book_code, scope[1], scope[2], num)
            else:
                rid = "%s-C%02d-R%03d" % (book_code, scope[1], num)
        else:
            rid = "%s-R%03d" % (book_code, num)
        cur = {"number": num, "number_raw": (raw or "").strip(), "ordinal": ordinal,
               "name": norm(name), "name_toc": "", "name_body": norm(name),
               "chapter": chapter, "chapter_seq": chap_seq, "sub_chapter": sub_chapter,
               "scope_id": ("C%02d-S%02d" % (scope[1], scope[2])) if scope[0] == "S"
                           else ("C%02d" % scope[1]),
               "ingredients": [], "seasonings": [], "blocks": [],
               "recipe_id": rid}
        recipes.append(cur)
        sec = grp = None
        step_seq = 0
        pending_step = None
        return rid

    def add_block(btype, text, page, group=None):
        """★ **跨页拼接**：若上一块**句中断**（结尾不是终止标点）且同类，则**接上**，⛔ 不另起一块。

        ★ 为什么要它：印本的句子**常态性跨页**（试点实测单册 176/228 道跨页）——
          ⛔ 不是异常处理，是**必需能力**。判据：拼接缝两侧若是同一句，产物里就该是**一块**。
        """
        nonlocal bid_seq
        if cur is None or not text.strip():
            return
        TERM = "。！？；：…”』"
        if (blocks and blocks[-1]["type"] == btype and blocks[-1]["recipe_id"] == cur["recipe_id"]
                and blocks[-1]["page_from"] != page):
            prev = blocks[-1]["text"]
            mid_sentence = bool(prev) and prev[-1] not in TERM
            # ★★ 承重判据：**带标记的页**只有在首行声明 `@@RECIPE_CONT` 时才拼接；
            #   整页无标记（变体①）时才回落到「句中断」启发式（那时没有标记可依）。
            if mid_sentence and (page in marker_cont_page or page in nomark_pages):
                blocks[-1]["text"] = prev + text.strip()
                stats_splice[0] += 1
                return
        bid_seq += 1
        bid = "%s-¶%04d" % (cur["recipe_id"], bid_seq)
        blocks.append({"bid": bid, "book": book_code, "recipe_id": cur["recipe_id"],
                       "number": cur["number"], "type": btype, "page_from": page,
                       "group": group, "text": text.strip()})
        cur["blocks"].append(bid)

    def emit_content(st, page):
        """**普通正文行**按当前节落块（带标记与不带标记两条路共用）。"""
        nonlocal step_seq
        if sec in ("ingredients", "main", "side", "seasoning"):
            if cur is not None:
                (cur["seasonings"] if sec == "seasoning" else cur["ingredients"]).append(st)
            add_block("seasoning" if sec == "seasoning" else "ingredient", st, page, sec)
        elif sec == "method":
            step_seq += 1
            add_block("step", st, page, "step%d" % step_seq)
        elif sec == "notes":
            m = C.gloss_re.match(st)
            if m:
                glossary.append({"marker": m.group("marker"), "title": m.group("title"),
                                 "text": m.group("text")})
            add_block("note", st, page, "note")

    # ★ G-29：子类判据要看「**下一非空行**」，而它可能**跨页**（章末页的最后一行）⇒ 先铺一张全局表。
    _pages = [(int(pf.stem[1:]), pf, pf.read_text(encoding="utf-8").splitlines())
              for pf in sorted(pages_dir.glob("p*.md"))]
    _seq = [(pg, i, l.strip()) for pg, _pf, ls in _pages for i, l in enumerate(ls) if l.strip()]
    nxt_nonempty = {(s[0], s[1]): _seq[k + 1][2] for k, s in enumerate(_seq[:-1])}

    for page, page_file, lines in _pages:

        # ── G-21 ② 形态兜底：本页若以「…{2,}＋页码」行占多数 ⇒ 判为**目录页**
        nonempty = [l for l in lines if l.strip()]
        toc_hits = sum(1 for l in nonempty if C.toc_re.search(l))
        is_toc_page = bool(toc_hits) and toc_hits >= 3 and toc_hits * 4 >= len(nonempty)
        if is_toc_page:
            drift["toc_pages"].append(page_file.name)
            drift["toc_lines_skipped"] += toc_hits

        has_marker = any(l.lstrip().startswith("@@") for l in lines)
        if not has_marker:
            drift["variant1_pages_no_marker"].append(page_file.name)
            nomark_pages.add(page)
        if any(l.strip().startswith(C.m_cont) for l in lines):
            marker_cont_page.add(page)

        for i, raw in enumerate(lines):
            line = raw.rstrip()
            if not line.strip():
                continue
            st = line.strip()

            # ── 目录行：⛔ 一律不计入正文（幻影食谱的来源）
            if C.toc_re.search(st):
                drift["toc_lines_skipped"] += 1
                continue

            # ── 变体 ①：整页无标记 ⇒ 用行首形态识别（记录名 / 节名 / 组名 / 步骤号）
            if not st.startswith("@@"):
                # ★ G-22b：节名与正文**同行**（`〔主料〕 值`）
                ms = INLINE_SEC.match(st)
                if ms and C.section(ms.group(1)):
                    sec = C.section(ms.group(1))
                    grp = None
                    drift["variant5_inline_section"] += 1
                    rest = ms.group(2).strip()
                    if rest:
                        emit_content(rest, page)
                    continue
                if pending_step is not None and cur is not None:
                    # ★ G-20：上一行是 `@@STEP <n>` ⇒ **本行才是正文**
                    step_seq += 1
                    add_block("step", st, page, "step%d" % step_seq)
                    pending_step = None
                    continue
                if cur is None and not is_toc_page:
                    # ★ 变体①：**整页无标记**的页上的起点 —— 它**没有 `@@RECIPE_START` 行**。
                    #   ⇒ G-28 的对账必须把它**单列**，⛔ 不能拿「标记行数 == 记录数」硬套
                    #   （实测踩过：玩具 B01 是 **5 记录 / 4 标记行**，硬套会把好产物判红）。
                    r0, n0, nm0 = split_start(C, st)
                    if n0 is not None:
                        opens_variant1[0] += 1
                        open_recipe(r0, n0, nm0)
                        continue
                g = C.group(st)
                if g:
                    canon, value = g
                    grp = canon
                    drift["variant4_bare_group"] += 1
                    if cur is not None:
                        (cur["seasonings"] if canon == "seasoning"
                         else cur["ingredients"]).append(value)
                    add_block("seasoning" if canon == "seasoning" else "ingredient",
                              value, page, canon)
                    continue
                s2 = C.section(st)
                if s2 and len(st) <= 6:
                    sec = s2
                    drift["section_spellings"][st] = drift["section_spellings"].get(st, 0) + 1
                    continue
                sp = C.step(st)
                if sp and sec == "method":
                    num, body = sp
                    drift["variant3_bare_step"] += 1
                    step_seq += 1
                    add_block("step", body, page, "step%d" % step_seq)
                    continue
                emit_content(st, page)
                continue

            # ── 带标记
            if st.startswith(C.m_toc):
                continue
            if st.startswith(C.m_rs):
                if is_toc_page:
                    continue
                starts_body[0] += 1                    # ★ G-28：正文起点**行数**（被拒的也计入）
                rest = st[len(C.m_rs):].strip()
                r0, n0, nm0, why = split_start_diag(C, rest)
                if n0 is not None:
                    open_recipe(r0, n0, nm0)
                else:
                    # ★ G-28：⛔ 不再是静默 `continue` —— 丢内容必须**具名可见**。
                    #   ★ 为什么必须（实测）：被拒 9 条落在 `十八、粗菜类`，而该章门诊断是
                    #     「缺 [] ＋ 重号 [1,3,4,5,6,7,10]」——**缺号列表是空的**，
                    #     因为重复号把空档填满了 ⇒ **丢内容与重号在门上长得一样**。
                    drift["rejected_reasons"][why] = drift["rejected_reasons"].get(why, 0) + 1
                    rejected.append({"page": page, "line": i + 1, "marker": C.m_rs,
                                     "rest": rest, "reason": why})
                continue
            if st.startswith(C.m_sec):
                tail = st[len(C.m_sec):].strip()
                if C.chapter_re and C.chapter_re.match(norm(tail)):
                    chapter = norm(tail)
                    chap_seq += 1
                    scope = ("C", chap_seq, 0)         # ★ G-29：章 = 一个新的编号作用域
                    sub_chapter = ""
                    sub_seq = 0
                    sec = grp = None
                    continue
                # ★★ G-29：**子类** —— 两个条件**都必要**，缺一即误判。
                #   ① 匹配 `subchapter_pattern`；② **下一非空行**是 `@@RECIPE_START`。
                #   ★ 为什么缺一不可（实测）：`（N）名字` 既是真子类标题
                #     （`@@SECTION （一）干 贝`，其后跟 `@@RECIPE_START 1 …`），
                #     又是被漏标的**食谱**标题（`@@SECTION （四）火腿龙须`，其后跟 `@@SECTION 〔主料〕`）。
                #     行形态**完全不可区分** —— 只看 ① 会把断号章从 14 推高到 **20**（实测更差）。
                nxt = nxt_nonempty.get((page, i), "")
                if C.sub_re and C.sub_re.match(norm(tail)) and nxt.startswith(C.m_rs):
                    sub_chapter = norm(tail)
                    sub_seq += 1
                    scope = ("S", chap_seq, sub_seq)   # ★ 子类 = **独立的编号作用域**
                    sec = grp = None
                    drift["subchapters"].append({"page": page, "chapter_seq": chap_seq,
                                                 "sub_seq": sub_seq, "title": sub_chapter})
                    continue
                sec = C.section(tail) or "other"
                grp = None
                continue
            if st.startswith(C.m_cont):
                # ★ 承接上一页：⛔ 不改 `cur`、⛔ 不落内容，只把「本节」状态保留
                continue
            if st.startswith(C.m_step):
                rest = st[len(C.m_step):].strip()
                if not rest:
                    pending_step = ""
                    continue
                if C.bare_step_re.match(rest):
                    # ★★ G-20：标记后**只是步号** ⇒ 正文在**下一行**（实测 851/1428 = 59.6%）
                    pending_step = rest
                    continue
                drift["variant2_inline_step"] += 1
                step_seq += 1
                add_block("step", rest, page, "step%d" % step_seq)
                continue
            if st.startswith(C.m_foot):
                pending_step = None
                continue
            if pending_step is not None and cur is not None:
                step_seq += 1
                add_block("step", st, page, "step%d" % step_seq)
                pending_step = None
                continue
            # 标记行之外的正文（与前一节同类处理）
            emit_content(st, page)

    # ── 判据
    nums = sorted(r["number"] for r in recipes)
    contiguous = nums == list(range(1, len(nums) + 1)) if nums else False
    # ★★ G-29：分组身份是**编号作用域**（章，或子类），⛔ 不是章名。
    #   ★ 按章名会踩两个坑（均实测）：① `一、凉菜类` 这类**同名章跨「部分」各出现一次**
    #     ⇒ 两套编号并到一起，报出「1,1,2,2,…」假断号；
    #     ② 子类内重起 ⇒ 章级口径报出「1,1,1,1」假重号（`十七、杂类` 实测正是这样）。
    per_scope, scope_label = {}, {}
    for r in recipes:
        key = r.get("scope_id") or ("C%02d" % r["chapter_seq"])
        per_scope.setdefault(key, []).append(r["number"])
        lbl = "C%02d %s" % (r["chapter_seq"], r["chapter"] or "(无章)")
        if r.get("sub_chapter"):
            lbl += " / %s" % r["sub_chapter"]
        scope_label.setdefault(key, lbl)
    contig_scope = bool(recipes) and all(
        sorted(v) == list(range(1, len(v) + 1)) for v in per_scope.values())
    # ★ 断号**具名报出**：这是改提示词的直接依据。
    #   `@@RECIPE_START` 漏标属**转写侧**，⛔ 装配侧修不了 —— 门必须红得**可行动**。
    missing_in_scope = {}
    for k, v in per_scope.items():
        if sorted(v) != list(range(1, len(v) + 1)):
            missing_in_scope[scope_label[k]] = sorted(set(range(1, max(v) + 1)) - set(v)) if v else []
    if C.numbering == "per_chapter":
        contiguous_ok = contig_scope
    else:
        contiguous_ok = contiguous
    # ★★ G-28：**被拒起点**必须自成一格。没有它，「丢内容」与「重号」在门上长得一样。
    #   ★ 这里其实是**两条不同的判据**，⛔ 不可合并成一条：
    #     `starts_accounted`   恒等式：标记行数 ＋ 变体①起点数 == 记录数 ＋ 拒收数
    #                          ★ 它抓「**有起点跑到账外**」—— 旧版正是静默 `continue` 掉了这一格。
    #     `all_starts_accepted` 判语：拒收 == 0，即**一条内容都没丢**。
    #   ⛔ 不能只写 `标记行数 == 记录数`：变体①的起点**没有标记行**
    #     （实测玩具 B01 ＝ **5 记录 / 4 标记行**；真书也有变体①页）⇒ 那样会把好产物判红。
    starts_n = starts_body[0]
    v1_n = opens_variant1[0]
    starts_accounted = (starts_n + v1_n) == (len(recipes) + len(rejected))
    all_starts_accepted = not rejected
    no_method = [r["number"] for r in recipes
                 if not any(b["type"] == "step" for b in blocks
                            if b["recipe_id"] == r["recipe_id"])]
    numeric_only = [b["bid"] for b in blocks
                    if b["type"] == "step" and contract.bare_step_re.match((b["text"] or "").strip())]
    placeholder_marks = sum(p.read_text(encoding="utf-8").count("⟦?⟧")
                            for p in sorted(pages_dir.glob("p*.md")))
    stats = {"recipes": len(recipes), "blocks": len(blocks), "glossary": len(glossary),
             "starts_body": starts_n,
             "recipes_from_variant1": v1_n,
             "starts_accounted": starts_accounted,
             "rejected_starts": rejected,
             "rejected_starts_by_reason": dict(drift["rejected_reasons"]),
             "numbers_contiguous": contiguous,
             "numbers_contiguous_per_chapter": contig_scope,
             "numbering": C.numbering,
             "numbering_scopes": len(per_scope),
             "subchapters": drift["subchapters"],
             "chapters": [scope_label[k] for k in sorted(per_scope) if scope_label.get(k)],
             "numbers_within_chapter": {scope_label[k]: sorted(v)
                                        for k, v in sorted(per_scope.items())},
             "numbers_missing_within_chapter": missing_in_scope,
             "recipes_without_method": no_method,
             "numeric_only_step_blocks": numeric_only,
             "step_blocks": sum(1 for b in blocks if b["type"] == "step"),
             "ingredient_blocks": sum(1 for b in blocks if b["type"] == "ingredient"),
             "placeholder_marks": placeholder_marks, "splice_joins": stats_splice[0],
             "contract_drift": drift}
    products = {
        "corpus/recipes.jsonl": "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recipes),
        "corpus/blocks.jsonl": "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks),
        "corpus/all.txt": "".join(b["text"] + "\n" for b in blocks),
        "corpus/glossary.jsonl": "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in glossary),
    }
    return products, stats, contiguous_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg, s = load_series(a.series)
    C = Contract(s["_contract"])
    books = [b for b in s["books"] if not a.book or b["code"] == a.book]
    bad = 0
    print("== S2 装配（%s）==" % s["id"])
    for b in books:
        pages_dir = resolve_pages_dir(s["_base"], s, b["code"])
        if not pages_dir.exists():
            print("  [FAIL] %-6s 无 `_pages/`：%s" % (b["code"], pages_dir))
            bad += 1
            continue
        products, stats, contiguous_ok = assemble(b["code"], pages_dir, C, s)
        meta = {"book": b["code"], "title": b.get("title", ""), "counts": stats, "gates": {}}
        meta["gates"]["numbers_contiguous"] = stats["numbers_contiguous"]
        meta["gates"]["numbers_contiguous_per_chapter"] = stats["numbers_contiguous_per_chapter"]
        meta["gates"]["every_recipe_has_method"] = not stats["recipes_without_method"]
        meta["gates"]["no_numeric_only_step_block"] = not stats["numeric_only_step_blocks"]
        # ★★ G-28：**被拒起点**这一格。⛔ 它不是「锦上添花」—— 没有它，
        #   「丢内容」与「重号」在门上**长得一样**（实测：`十八、粗菜类` 丢了 9 条，
        #   而门的判语是「缺 [] ＋ 重号 […]」——缺号列表**为空**）。⇒ 丢内容**不可见**。
        meta["gates"]["all_starts_accepted"] = not stats["rejected_starts"]
        meta["gates"]["starts_accounted"] = stats["starts_accounted"]
        kdir = s["_out"] / "kb" / b["code"]
        ok = (contiguous_ok and not stats["recipes_without_method"]
              and not stats["numeric_only_step_blocks"]
              and meta["gates"]["all_starts_accepted"] and meta["gates"]["starts_accounted"])
        print("  [%s] %-6s %d 页 ⇒ %d 记录 · %d 块 · 注释 %d 条 | 编号(%s/%d 作用域)连续=%s "
              "缺制法=%s 伪步骤=%d 起点 %d/%d 拒收=%d | "
              "变体命中 ①%d页 ②%d ③%d ④%d ⑤%d | 目录 %d行/%d页 | 拼接 %d 处"
              % ("PASS" if ok else "FAIL", b["code"], len(list(pages_dir.glob("p*.md"))),
                 stats["recipes"], stats["blocks"], stats["glossary"],
                 stats["numbering"], stats["numbering_scopes"], contiguous_ok,
                 stats["recipes_without_method"] or "无", len(stats["numeric_only_step_blocks"]),
                 stats["recipes"], stats["starts_body"], len(stats["rejected_starts"]),
                 len(stats["contract_drift"]["variant1_pages_no_marker"]),
                 stats["contract_drift"]["variant2_inline_step"],
                 stats["contract_drift"]["variant3_bare_step"],
                 stats["contract_drift"]["variant4_bare_group"],
                 stats["contract_drift"]["variant5_inline_section"],
                 stats["contract_drift"]["toc_lines_skipped"],
                 len(stats["contract_drift"]["toc_pages"]),
                 stats["splice_joins"]))
        # ★ G-28：拒收必须**具名**（页/行/原文/原因），否则「丢了几条」仍要人肉翻页。
        if stats["rejected_starts"]:
            print("       ⛔ 被拒起点 %d 条：%s" % (
                len(stats["rejected_starts"]),
                " · ".join("%s×%d" % (k, v) for k, v in
                           sorted(stats["rejected_starts_by_reason"].items(), key=lambda x: -x[1]))))
            for rj in stats["rejected_starts"][:40]:
                print("          p%04d L%-3d [%s] %s" % (rj["page"], rj["line"], rj["reason"],
                                                         rj["rest"][:48]))
            if len(stats["rejected_starts"]) > 40:
                print("          … 另 %d 条" % (len(stats["rejected_starts"]) - 40))
        if stats["subchapters"]:
            print("       子类（编号作用域重起）%d 个：%s" % (
                len(stats["subchapters"]),
                " · ".join("C%02d/S%02d %s" % (x["chapter_seq"], x["sub_seq"], x["title"])
                           for x in stats["subchapters"][:12])))
        if a.dry_run:
            bad += 0 if ok else 1
            continue
        if a.check:
            diff = [rel for rel, text in products.items()
                    if not (kdir / rel).exists() or (kdir / rel).read_text(encoding="utf-8") != text]
            same = not diff
            print("       --check：%s" % ("与在盘产物逐字节相同" if same else "**不同**：%s" % diff))
            # ★★ `--check` 只判**幂等**（重新派生 ≡ 在盘件），⛔ **不判**装配判据。
            #   ★ 为什么必须分开（实测踩过）：首版把「判语」也算进 `--check` 的退出码 ⇒
            #     G0（幂等门）会在**字节完全相同**时也变红，于是「G2 坏了」被读成「G0 坏了」，
            #     **两道门互相冒名**。判语由 `_meta.json` 承载，交给 G2 看。
            bad += 0 if same else 1
            continue
        for rel, text in products.items():
            f = kdir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8", newline="\n")
        (kdir / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8", newline="\n")
        bad += 0 if ok else 1
    print("\n  结论：%s" % ("全部通过" if not bad else "%d 册有问题" % bad))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
