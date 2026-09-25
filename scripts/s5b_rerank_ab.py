#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S5b —— **重排 A/B 对照器**（⛔ 不是「看着更好」，而是可失败的三条判据）。

判据：
  ① **不许出现新的 FAIL**：逐条按用例自己的期望（`topn`）判 PASS/FAIL；
     重排**把原本 PASS 的打出 FAIL** ⇒ 逐条列出（★ 平均更好不算数）。
  ② **前后逐位对照**：每条给「关重排 rank → 开重排 rank」，并统计被动过的位数。
  ③ **失败必回退**：用一个**不存在的模型名**跑一次 ⇒ 必须 `reranked=False`、结果非空
     （「失败时回退」这句话，只有被**制造过一次失败**才算数）。

用法：
    python s5b_rerank_ab.py --series <series.yml> [--book CODE] [--rerank-model NAME]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import s5_search as S5                                          # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--rerank-model", default=None)
    ap.add_argument("--json-out")
    a = ap.parse_args()

    cfg, s = S5.load_series(a.series)
    model = a.rerank_model or (cfg.get("retrieval") or {}).get("rerank_model")
    books = [b["code"] for b in s["books"] if not a.book or b["code"] == a.book]

    tot = {"cases": 0, "pass_off": 0, "pass_on": 0, "regress": [], "improve": [],
           "reranked_rows": 0}
    print("== 重排 A/B（%s ｜ 模型 %s）==" % (s["id"], model))
    per = {}
    for b in books:
        kb = S5.KB(s["_out"] / "kb" / b, cfg, with_vectors=True)
        cases = [(q, w, t, en, False, note) for q, w, t, en, note in S5.cases_for(kb)]
        cases += S5.load_registered(str(s["_base"] / "series.yml"), b)
        rows = []
        for q, want, topn, expect_none, _nv, note in cases:
            def rank(rr):
                rk, _u, _re = kb.search(q, max(a.topk, topn or 4), use_vectors=True,
                                        rerank_model=rr)
                nums = [n for n, _ in rk]
                if expect_none:
                    return (0 if want not in nums else 1), nums
                return (nums.index(want) + 1 if want in nums else None), nums
            r_off, _ = rank(None)
            r_on, _ = rank(model)
            def ok(r):
                if expect_none:
                    return r == 0
                return r is not None and r <= (topn or 4)
            tot["cases"] += 1
            tot["pass_off"] += int(ok(r_off)); tot["pass_on"] += int(ok(r_on))
            item = {"book": b, "q": q, "want": want, "topn": topn,
                    "rank_off": r_off, "rank_on": r_on, "ok_off": ok(r_off), "ok_on": ok(r_on)}
            rows.append(item)
            if ok(r_off) and not ok(r_on):
                tot["regress"].append(item)
            if ok(r_on) and not ok(r_off):
                tot["improve"].append(item)
            print("  %-6s %-14s 期望 #%-4s top%-2s | 关 %-6s 开 %-6s %s"
                  % (b, q[:14], "不存在" if expect_none else want, topn or 4,
                     r_off if r_off is not None else "未中", r_on if r_on is not None else "未中",
                     "★ 变坏" if (ok(r_off) and not ok(r_on)) else
                     ("☆ 变好" if (ok(r_on) and not ok(r_off)) else "")))
        per[b] = rows
    print("\n== 合计 ==")
    print("   用例 %d · 关重排 PASS %d · 开重排 PASS %d" % (tot["cases"], tot["pass_off"], tot["pass_on"]))
    print("   变坏 %d 条 %s" % (len(tot["regress"]), [x["q"] for x in tot["regress"]][:6]))
    print("   变好 %d 条 %s" % (len(tot["improve"]), [x["q"] for x in tot["improve"]][:6]))

    # ③ 失败回退（制造一次失败）
    kb = S5.KB(s["_out"] / "kb" / books[0], cfg, with_vectors=True)
    q0 = S5.cases_for(kb)[0][0]
    rk, used, reranked = kb.search(q0, 5, use_vectors=True,
                                   rerank_model="Qwen/ThisModelDoesNotExist-0B")
    ok_fb = (reranked is None) and bool(rk)
    print("\n== 失败回退（故意用不存在的模型名）==")
    print("   查询 %s ⇒ reranked=%s · 结果 %d 条 ⇒ %s"
          % (q0, reranked, len(rk), "回退 RRF ✅" if ok_fb else "⛔ 未回退"))
    bad = len(tot["regress"]) + (0 if ok_fb else 1)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"totals": tot, "fallback_ok": ok_fb, "books": per},
                                               ensure_ascii=False, indent=1),
                                    encoding="utf-8", newline="\n")
    print("\n判据：变坏 %d（应 0）· 回退 %s ⇒ %s"
          % (len(tot["regress"]), "OK" if ok_fb else "FAIL", "PASS" if not bad else "FAIL"))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
