#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S2 —— **装配**：`_pages/` → `corpus/{recipes,blocks}.jsonl` ＋ `all.txt` ＋ `glossary.jsonl` ＋ `_meta.json`。

★ 本件是**技能里最难的一块**：它必须容忍 `references/输出契约.md` §2 的**五种变体**，
  ⛔ 而判据只有一条 —— **编号连续 ＋ 每条记录都有制法**（变体没处理干净时，这两条会红）。

判据（可失败）：
  ① `numbers_contiguous`：编号 1..N 连续无缺
  ② `every_recipe_has_method`：每条记录 ≥1 个制法块
  ③ `placeholders`：`⟦?⟧` 记号计数（**如实报出，⛔ 不当错误**）
  ④ `--check`：重新装配并与在盘产物**逐字节比对**（幂等）
  ⑤ `contract_drift`：五种变体各命中多少，逐项写进 `_meta.json`（★ 这是改提示词的直接依据）

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

SPACE = re.compile(r"\s+")


def norm(s: str) -> str:
    """★ 归一化**只用于比对与识别**，⛔ 不改写原文（原文进 blocks.text）。"""
    return SPACE.sub("", s).strip()


def load_series(p):
    import yaml
    cfg = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    base = Path(p).resolve().parent
    s = cfg["series"]
    s["_base"] = base
    s["_out"] = (base / str(s["out_root"])).resolve()
    s["_pages_root"] = (base / str(s.get("pages_root", "pages"))).resolve()
    s["_contract"] = cfg.get("contract", {})
    return cfg, s


class Contract:
    def __init__(self, c):
        self.c = c
        sec = c.get("sections", {})
        self.sec_of = {}
        for canon, spellings in sec.items():
            for sp in spellings + [canon]:
                self.sec_of[norm(sp)] = canon
        grp = c.get("groups", {})
        self.grp_of = {}
        for canon, spellings in grp.items():
            for sp in spellings:
                # ★ 配置里的写法**可能自带冒号**（`主 料：`）⇒ 建表时统一剥掉，⛔ 不要在这里再拼一个
                #   （实测踩过：拼成 `主 料：：` ⇒ 变体④ 一条都识别不到，而产物**看起来正常**）
                self.grp_of[norm(sp).rstrip("：:")] = canon
        self.step_res = [re.compile(p) for p in c.get("step_number_patterns", [])]
        self.num_re = re.compile(c.get("recipe_number_pattern", r"^\d{1,4}$"))
        self.gloss_re = re.compile(c.get("glossary_pattern", r"^$"))
        m = c.get("markers", {})
        self.m_rs = m.get("recipe_start", "@@RECIPE_START")
        self.m_sec = m.get("section", "@@SECTION")
        self.m_step = m.get("step", "@@STEP")
        self.m_foot = m.get("footer", "@@FOOTER")

    def section(self, raw):
        return self.sec_of.get(norm(raw))

    def group(self, line):
        """裸组名（变体 ④）：`主 料：值` ⇒ (canon, 值) 或 None。"""
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


def assemble(book_code, pages_dir, contract, cfg_series):
    """返回 (products dict[relpath]→text, stats dict)。★ 纯函数：同样的输入必得同样的输出。"""
    C = contract
    recipes, blocks, glossary = [], [], []
    cur = None
    sec = None
    grp = None
    drift = {"variant1_pages_no_marker": [], "variant2_inline_step": 0,
             "variant3_bare_step": 0, "variant4_bare_group": 0, "section_spellings": {}}
    step_seq = 0
    bid_seq = 0
    stats_splice = [0]                # ★ 拼接次数（★ 可证伪读数：跨页夹具上应 ≥1）
    marker_cont_page = set()          # 声明「承接上一页」的页
    nomark_pages = set()              # 整页无标记的页（变体①）

    def open_recipe(num, name):
        nonlocal cur, sec, grp, step_seq
        cur = {"number": int(num), "name": norm(name), "name_toc": "", "name_body": norm(name),
               "chapter": "", "ingredients": [], "seasonings": [], "blocks": [],
               "recipe_id": "%s-R%03d" % (book_code, int(num))}
        recipes.append(cur)
        sec = grp = None
        step_seq = 0

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

    for page_file in sorted(pages_dir.glob("p*.md")):
        page = int(page_file.stem[1:])
        lines = page_file.read_text(encoding="utf-8").splitlines()
        has_marker = any(l.lstrip().startswith("@@") for l in lines)
        if not has_marker:
            drift["variant1_pages_no_marker"].append(page_file.name)
            nomark_pages.add(page)
        if any(l.strip().startswith("@@" + "RECIPE_CONT") for l in lines):
            marker_cont_page.add(page)
        for raw in lines:
            line = raw.rstrip()
            if not line.strip():
                continue
            st = line.strip()

            # ── 变体 ①：整页无标记 ⇒ 用行首形态识别（记录名 / 节名 / 组名 / 步骤号）
            if not st.startswith("@@"):
                if cur is None:
                    parts = st.split(None, 1)
                    if len(parts) == 2 and C.num_re.match(parts[0]):
                        open_recipe(parts[0], parts[1])
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
                # 普通正文：按当前节落块
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
                continue

            # ── 带标记
            if st.startswith(C.m_rs):
                rest = st[len(C.m_rs):].strip()
                parts = rest.split(None, 1)
                if len(parts) == 2 and C.num_re.match(parts[0]):
                    open_recipe(parts[0], parts[1])
                continue
            if st.startswith(C.m_sec):
                sec = C.section(st[len(C.m_sec):]) or "other"
                grp = None
                continue
            if st.startswith(C.c.get("markers", {}).get("recipe_cont", "@@RECIPE_CONT")):
                # ★ 承接上一页：⛔ 不改 `cur`、⛔ 不落内容，只把「本节」状态保留
                continue
            if st.startswith(C.m_step):
                rest = st[len(C.m_step):].strip()
                if rest:                                            # 变体 ②：标记与正文同行
                    drift["variant2_inline_step"] += 1
                    step_seq += 1
                    add_block("step", rest, page, "step%d" % step_seq)
                continue
            if st.startswith(C.m_foot):
                continue
            # 标记行之外的正文（与前一节同类处理）
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

    # ── 判据
    nums = sorted(r["number"] for r in recipes)
    contiguous = nums == list(range(1, len(nums) + 1)) if nums else False
    no_method = [r["number"] for r in recipes
                 if not any(b["type"] == "step" for b in blocks
                            if b["recipe_id"] == r["recipe_id"])]
    placeholder_marks = sum(p.read_text(encoding="utf-8").count("⟦?⟧")
                            for p in sorted(pages_dir.glob("p*.md")))
    stats = {"recipes": len(recipes), "blocks": len(blocks), "glossary": len(glossary),
             "numbers_contiguous": contiguous, "recipes_without_method": no_method,
             "placeholder_marks": placeholder_marks, "splice_joins": stats_splice[0],
             "contract_drift": drift}
    products = {
        "corpus/recipes.jsonl": "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recipes),
        "corpus/blocks.jsonl": "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks),
        "corpus/all.txt": "".join(b["text"] + "\n" for b in blocks),
        "corpus/glossary.jsonl": "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in glossary),
    }
    return products, stats


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
        pages_dir = s["_pages_root"] / b["code"]
        if not pages_dir.exists():
            print("  [FAIL] %-6s 无 `_pages/`：%s" % (b["code"], pages_dir))
            bad += 1
            continue
        products, stats = assemble(b["code"], pages_dir, C, s)
        meta = {"book": b["code"], "title": b.get("title", ""), "counts": stats, "gates": {}}
        meta["gates"]["numbers_contiguous"] = stats["numbers_contiguous"]
        meta["gates"]["every_recipe_has_method"] = not stats["recipes_without_method"]
        kdir = s["_out"] / "kb" / b["code"]
        ok = stats["numbers_contiguous"] and not stats["recipes_without_method"]
        print("  [%s] %-6s %d 页 ⇒ %d 记录 · %d 块 · 注释 %d 条 | 编号连续=%s 缺制法=%s | "
              "变体命中 ①%d页 ②%d ③%d ④%d ⑤%d种"
              % ("PASS" if ok else "FAIL", b["code"], len(list(pages_dir.glob("p*.md"))),
                 stats["recipes"], stats["blocks"], stats["glossary"],
                 stats["numbers_contiguous"], stats["recipes_without_method"] or "无",
                 len(stats["contract_drift"]["variant1_pages_no_marker"]),
                 stats["contract_drift"]["variant2_inline_step"],
                 stats["contract_drift"]["variant3_bare_step"],
                 stats["contract_drift"]["variant4_bare_group"],
                 len(stats["contract_drift"]["section_spellings"]))
              + " | 拼接 %d 处" % stats["splice_joins"])
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
