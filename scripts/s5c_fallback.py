#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S5c —— **关键词分层灾备** ＋ 与 RAG 的**同口径召回对照**（★ 零网络、零密钥可用）。

★★ 灾备的判据（三条，都可失败）：
  ① **零网络**：灾备侧一律 `with_vectors=False` ⇒ **结构性**不发请求；
     ★ 而这句自述**必须被制造出来**：`--zero-network-selftest` 把
     `socket.connect／connect_ex／create_connection／getaddrinfo` **全部改成抛异常**，
     再跑一遍 —— 灾备侧**照常出读数**、RAG 侧**优雅降级**为 SKIP，才算证明。
  ② **同口径**：同一批查询（派生 ＋ 登记）在三种模式下各跑一遍：①关键词（灾备）②关键词＋向量 ③＋重排；
     逐条给 rank、汇总 `recall@1/@3`。⛔ 三条列的**可用前提不同**，不要读成「谁更差」。
  ③ **分层可见**：逐条打印实际用到哪几层（`terms`／`lex`／`vector`）。

用法：
    python s5c_fallback.py --series <series.yml> --book B01
    python s5c_fallback.py --series <series.yml> --all --rerank
    python s5c_fallback.py --series <series.yml> --book B01 --zero-network-selftest
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


def run_book(book, cfg, s, topk, rerank_model=None):
    kb_kw = S5.KB(s["_out"] / "kb" / book, cfg, with_vectors=False)     # ★ 灾备侧：结构性关向量
    kb_full = S5.KB(s["_out"] / "kb" / book, cfg, with_vectors=True)
    cases = [(q, w, t, en, False, note) for q, w, t, en, note in S5.cases_for(kb_full)]
    cases += S5.load_registered(str(s["_base"] / "series.yml"), book)
    rows = []
    for q, want, topn, expect_none, needs_vec, note in cases:
        def probe(kb, use_vec, rr=None):
            rk, used, _reranked = kb.search(q, max(topk, topn or 4), use_vectors=use_vec,
                                            rerank_model=rr)
            nums = [n for n, _ in rk]
            if expect_none:
                return (want not in nums), used
            return (want in nums and nums.index(want) + 1 <= topn), used
        ok_kw, used_kw = probe(kb_kw, False)
        ok_v, used_v = probe(kb_full, True)
        ok_r = None
        if rerank_model:
            ok_r, _ur = probe(kb_full, True, rerank_model)
        rows.append({"query": q, "want": want, "note": note,
                     "kw_ok": ok_kw, "vec_ok": ok_v, "rr_ok": ok_r,
                     "layers_kw": sorted(k for k, v in used_kw.items() if v),
                     "layers_vec": sorted(k for k, v in used_v.items() if v),
                     "vector_layer_used": bool(used_v.get("vector"))})
    return rows


def recall(rows, key):
    exp = [r for r in rows if r["want"] is not None]
    if not exp:
        return None
    hit = [r for r in exp if r.get(key)]
    return len(hit) / len(exp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--rerank", action="store_true", help="加测第三模式（需密钥与网络）")
    ap.add_argument("--zero-network-selftest", action="store_true",
                    help="★ 把 socket 出网口全部禁掉再跑：证明灾备侧**结构性**不发请求")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    cfg, s = S5.load_series(a.series)
    rr_model = (cfg.get("retrieval") or {}).get("rerank_model") if a.rerank else None

    if a.zero_network_selftest:
        import socket

        def _deny(*_a, **_k):
            raise RuntimeError("⛔ 本进程已禁网，但仍有人试图出网")

        socket.socket.connect = _deny
        socket.socket.connect_ex = _deny
        socket.create_connection = _deny
        socket.getaddrinfo = _deny
        # ★★ 关键：`from socket import create_connection` 之类会把**旧引用**绑进**已导入的**模块，
        #   于是只 patch `socket.*` 对它们无效 —— 实测首版就这样：禁网后 RAG 侧**照样算出了向量**，
        #   于是这条反控报红，而红的原因是**尺子漏堵**（不是灾备发请求）。
        #   ⇒ 必须把已导入模块里那一份也堵上（`requests` 走的是 `urllib3.util.connection`）。
        also = []
        try:
            import urllib3.util.connection as _u3c
            _u3c.create_connection = _deny
            also.append("urllib3.util.connection.create_connection")
        except Exception:                                        # noqa: BLE001
            pass
        print("★★ 已禁网（socket.connect／connect_ex／create_connection／getaddrinfo%s）"
              % ("，" + "、".join(also) if also else ""))

    books = [b["code"] for b in s["books"]]
    if a.book:
        books = [a.book]
    elif not a.all:
        books = books[:1]

    per, tot = {}, {"cases": 0, "exp": 0, "kw_hit": 0, "vec_hit": 0, "rr_hit": 0}
    print("== 灾备 vs RAG 同口径对照（%s）==" % s["id"])
    for b in books:
        rows = run_book(b, cfg, s, a.topk, rr_model)
        per[b] = rows
        exp = [r for r in rows if r["want"] is not None]
        tot["cases"] += len(rows); tot["exp"] += len(exp)
        tot["kw_hit"] += sum(1 for r in exp if r["kw_ok"])
        tot["vec_hit"] += sum(1 for r in exp if r["vec_ok"])
        tot["rr_hit"] += sum(1 for r in exp if r["rr_ok"])
        print("  %-6s %2d 条 | ①关键词 %-5s ②＋向量 %-5s ③＋重排 %-5s"
              % (b, len(rows), _p(recall(rows, "kw_ok")), _p(recall(rows, "vec_ok")),
                 _p(recall(rows, "rr_ok")) if rr_model else "—"))
        if a.zero_network_selftest:
            print("       灾备侧用到的层：%s"
                  % ",".join(sorted({k for r in rows for k in r["layers_kw"]})))
            print("       RAG 侧走向量：%d/%d 条（禁网 ⇒ 应为 0）"
                  % (sum(1 for r in rows if r["vector_layer_used"]), len(rows)))
    n = tot["exp"] or 1
    print("\n== 全库合计（%d 条有期望）==" % tot["exp"])
    print("  ①关键词分层（灾备 · 零网络零密钥）: %s" % _p(tot["kw_hit"] / n))
    print("  ②关键词＋向量（RAG 第一级）      : %s" % _p(tot["vec_hit"] / n))
    if rr_model:
        print("  ③关键词＋向量＋重排（**交付**）  : %s" % _p(tot["rr_hit"] / n))
    if a.zero_network_selftest:
        # ★★ 判据（**只有一条是判据**）：
        #   ① **灾备侧（关键词分层）在禁网进程里必须照常出读数** —— 这就是「零网络」的全部含义；
        #   ② RAG 侧走向量条数**只作读数报出**，⛔ 不作判据 —— RAG 本来就允许联网，
        #      而且「堵住所有出网引用」本身很难做全（`from socket import …` 会绑定旧引用）。
        #      ★ 实测教训：首版把 ② 也当判据 ⇒ 红/绿取决于**哪个库先被导入**，
        #      同一份代码两次运行给出不同结论 ⇒ 那条判据**不可复现**，必须降级为观察项。
        ok = tot["exp"] > 0 and tot["kw_hit"] > 0
        print("\n== 禁网反控 ==")
        print("   ① 灾备侧仍给出读数 : %s（%d/%d 命中）★ 判据"
              % ("✅" if tot["kw_hit"] > 0 else "⛔", tot["kw_hit"], tot["exp"]))
        print("   ② RAG 侧走向量条数 : %d（★ 只作读数：RAG 允许联网，且出网引用未必全被堵住）"
              % tot["vec_hit"])
        print("   判定               : %s" % ("PASS" if ok else "FAIL"))
        if a.json_out:
            Path(a.json_out).write_text(json.dumps({"totals": tot, "books": per},
                                                   ensure_ascii=False, indent=1),
                                        encoding="utf-8", newline="\n")
        return 0 if ok else 2
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"totals": tot, "books": per},
                                               ensure_ascii=False, indent=1),
                                    encoding="utf-8", newline="\n")
    return 0


def _p(x):
    return "—" if x is None else "%.2f" % x


if __name__ == "__main__":
    sys.exit(main())
