#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S3 —— **索引与别名族**（`corpus/recipes.jsonl` → `terms.json` · `aliases.json` · 书索引.md）。

★★ 两条判据是这一阶段存在的理由（都**可失败**，且都来自试点构建的教训）：

  ① **别名族必须由台账派生，⛔ 不手写**：族只能来自 `<out>/kb/<code>/_CONFLICTS.tsv` 里
     **已裁定**（状态非 OPEN）的名称类行 —— 把等长且只差一位的两个见证写法配成**字对**，再传递闭包成族。
     **前向检查**：台账里每一条字对都必须出现在 `aliases.json` 里（派生漏一条 ⇒ 红）。
     ★ 为什么：手写族会与台账脱钩（台账回填后没人记得改族），而**脱钩是静默的**。

  ② **prose-only 缺口双向检查**：`<out>/kb/<code>/_ALIAS-GAPS.tsv` 里声明的字，
     必须至少被 `cases.yml` 里**一条登记用例**覆盖（后向）；声明了却无用例 ⇒ 红。
     ★ 为什么：缺口是**已知会漏**的地方，声明它只是第一步；没有用例，等于没人守。

  ③ `--check`：重新派生并与在盘产物**逐字节比对**（幂等）。

用法：
    python s3_build_index.py --series <series.yml> [--book CODE] [--check] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

SPACE = re.compile(r"\s+")
PAREN = re.compile(r"[（(][^）)]*[）)]")
NAME_KINDS = {"name_mismatch", "transcription_error_resolved", "name_shared_error",
              "name_ok_after_conflict"}


def norm(s):
    return SPACE.sub("", s or "").strip()


def load_series(p):
    import yaml
    cfg = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    base = Path(p).resolve().parent
    s = cfg["series"]
    s["_base"] = base
    s["_out"] = (base / str(s["out_root"])).resolve()
    return cfg, s


def tsv_rows(p: Path):
    if not p.exists():
        return []
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return []
    hdr = lines[0].split("\t")
    out = []
    for ln in lines[1:]:
        f = ln.split("\t")
        f += [""] * (len(hdr) - len(f))
        out.append(dict(zip(hdr, f)))
    return out


def ledger_pairs(ledger: Path):
    """台账 → 字对集合（**只认已裁定的名称类行**，且只看**等长差一位**）。"""
    pairs, rows_used = set(), 0
    for r in tsv_rows(ledger):
        if r.get("kind") not in NAME_KINDS or "OPEN" in (r.get("status") or ""):
            continue
        names = []
        for col in ("witness_a", "witness_b", "witness_c"):
            cell = PAREN.sub("", r.get(col, "") or "")
            if "=" in cell:
                v = norm(cell.split("=", 1)[1])
                if len(v) >= 3 and all("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U0003FFFF"
                                       for c in v):
                    names.append(v)
        if len(names) < 2:
            continue
        rows_used += 1
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if len(a) != len(b):
                    continue
                diff = [(x, y) for x, y in zip(a, b) if x != y]
                if len(diff) == 1:
                    pairs.add(diff[0])
    return pairs, rows_used


def families_from_pairs(pairs):
    """字对 → 族（并查集，含传递闭包）。"""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for x, y in pairs:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry
    groups = defaultdict(set)
    for x in list(parent):
        groups[find(x)].add(x)
    return sorted((sorted(g) for g in groups.values() if len(g) > 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg, s = load_series(a.series)
    books = [b for b in s["books"] if not a.book or b["code"] == a.book]
    cases_file = s["_base"] / "cases.yml"
    case_queries = []
    if cases_file.exists():
        import yaml
        d = yaml.safe_load(cases_file.read_text(encoding="utf-8")) or {}
        case_queries = [str(c.get("q", "")) for c in d.get("cases", [])]

    bad = 0
    print("== S3 索引与别名族（%s）==" % s["id"])
    for b in books:
        kdir = s["_out"] / "kb" / b["code"]
        recs = [json.loads(l) for l in
                (kdir / "corpus" / "recipes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        ledger = kdir / "_CONFLICTS.tsv"
        pairs, rows_used = ledger_pairs(ledger)
        fams = families_from_pairs(pairs)

        terms = {}
        for r in recs:
            # ★ **必须排序再遍历**：集合的迭代顺序受字符串哈希随机化影响 ⇒
            #   同一输入在不同进程里会产出不同字节序 ⇒ `--check` 假红（与 V35 同族）。
            for k in sorted({"#%d" % r["number"], norm(r["name"]), norm(r.get("name_toc")),
                             norm(r.get("name_body"))} - {""}):
                terms.setdefault(k, {"recipes": [], "kind": "name"})["recipes"].append(r["recipe_id"])
        aliases = {"char_families": fams, "source": {"file": ledger.name if ledger.exists() else None,
                                                    "rows_used": rows_used, "pairs": len(pairs)},
                   "prose_only_known_members": []}

        # ① 前向：台账每条字对都必须出现在**在盘** `aliases.json` 的族里
        #   ★ 为什么对照**在盘件**而不是内存里的派生结果：否则**手改族文件**永远发现不了
        #     （内存里刚派生的当然自洽 —— 这是一条「不会失败的判据」）。
        on_disk = kdir / "corpus" / "aliases.json"
        fams_disk = []
        if on_disk.exists():
            try:
                fams_disk = json.loads(on_disk.read_text(encoding="utf-8")).get("char_families", [])
            except Exception:                                   # noqa: BLE001
                fams_disk = []
        infam = {c for f in (fams_disk or fams) for c in f}
        missing_pairs = sorted({p for p in pairs if not ({p[0], p[1]} <= infam)})
        fams_drift = (sorted(map(tuple, fams_disk)) != sorted(map(tuple, fams))) if fams_disk else False

        # ② 后向：声明的缺口必须被至少一条登记用例覆盖
        gap_file = kdir / "_ALIAS-GAPS.tsv"
        gaps = [r["char"].strip() for r in tsv_rows(gap_file) if r.get("char", "").strip()]
        uncovered = [g for g in gaps if not any(g in q for q in case_queries)]

        idx = "\n".join(["<!-- 由 scripts/s3_build_index.py 确定性派生，⛔ 不是手写 -->",
                         "# %s · 书索引" % (b.get("title") or b["code"]), "",
                         "| # | 名 | 目录名 | 块 |", "|---|---|---|---|"]
                        + ["| %d | %s | %s | %d |" % (r["number"], r["name"], r.get("name_toc") or "—",
                                                      len(r["blocks"])) for r in recs]) + "\n"
        products = {
            "corpus/terms.json": json.dumps({"terms": terms, "count": len(terms)},
                                            ensure_ascii=False, indent=1) + "\n",
            "corpus/aliases.json": json.dumps(aliases, ensure_ascii=False, indent=1) + "\n",
            "书索引.md": idx,
        }
        ok = not missing_pairs and not uncovered and not fams_drift
        print("  [%s] %-6s 词项 %-4d 族 %-2d（台账 %d 行 / %d 字对）| 前向缺 %s｜后向缺 %s｜在盘族与派生%s"
              % ("PASS" if ok else "FAIL", b["code"], len(terms), len(fams), rows_used, len(pairs),
                 missing_pairs or "无", uncovered or "无", "**不一致**" if fams_drift else "一致"))
        if a.dry_run:
            bad += 0 if ok else 1
            continue
        if a.check:
            diff = [rel for rel, text in products.items()
                    if not (kdir / rel).exists() or (kdir / rel).read_text(encoding="utf-8") != text]
            print("       --check：%s" % ("与在盘产物逐字节相同" if not diff else "**不同**：%s" % diff))
            # ★ `--check` 只判**幂等**（派生 ≡ 在盘件）；判语由 `_meta.json` 承载、交给门 G3 看
            #   （与 S2 同一条纪律：两道门⛔ 不得互相冒名）。
            bad += 0 if not diff else 1
            continue
        for rel, text in products.items():
            f = kdir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8", newline="\n")
        meta_p = kdir / "_meta.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {"book": b["code"]}
        meta.setdefault("gates", {})["G3_index"] = {
            "terms": len(terms), "families": len(fams),
            "ledger_rows_used": rows_used, "pairs": len(pairs),
            "forward_missing_pairs": missing_pairs, "backward_uncovered_gaps": uncovered}
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8", newline="\n")
        bad += 0 if ok else 1
    print("\n  结论：%s" % ("全部通过" if not bad else "%d 册有问题" % bad))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
