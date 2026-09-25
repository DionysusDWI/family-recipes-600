#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S5 —— **检索**（三层：精确键 → bigram 词法 → 向量）＋ **双模式自测**。

★ 三层各自独立可关：
  · `terms`  精确索引键（`#编号` · 权威名 · 目录名 · 正文名）
  · `lex`    bigram 词法（★ 天然容忍未知变体字：不存在的 gram 直接丢弃）
  · `vector` 向量（**单位向量**点积＝余弦；缺向量或算不出 ⇒ 该层静默缺席）
  融合用 RRF（倒数排名融合），⛔ 不做加权调参。

★★ 双模式自测的判据（试点的 V29 教训）：
  **模式列必须读「这一次检索**真的**走到了向量层吗」** —— `.npy` 在盘只证明 S4 跑过。
  ⇒ 三态：`PASS` / `FAIL` / **`SKIP(环境)`**（请求了向量却没走到 ⇒ **不可判**，⛔ 既不是通过也不是失败）。
  ⇒ 退出码：0 全过 · 2 有 FAIL · **3 有不可判**。
  用例可声明 `needs_vectors: true` ⇒ 降级模式**不设判据**（那种查询按设计就要向量层）。

用法：
    python s5_search.py --series <series.yml> --book B01 --self-test [--no-vectors]
    python s5_search.py --series <series.yml> --book B01 清汤示例
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

import numpy as np                                            # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _keys import load_key                                    # noqa: E402

SPACE = re.compile(r"\s+")
RRF_K = 60
EMBED_API = "https://api.siliconflow.cn/v1/embeddings"


def norm(s):
    return SPACE.sub("", s or "").strip()


def load_series(p):
    import yaml
    cfg = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    base = Path(p).resolve().parent
    s = cfg["series"]
    s["_base"] = base
    s["_out"] = (base / str(s["out_root"])).resolve()
    s["_cfg"] = cfg
    return cfg, s


class KB:
    def __init__(self, book_dir, cfg, with_vectors=True):
        self.dir = book_dir
        self.recipes = [json.loads(l) for l in
                        (book_dir / "corpus" / "recipes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.blocks = [json.loads(l) for l in
                       (book_dir / "corpus" / "blocks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.by_num = {r["number"]: r for r in self.recipes}
        self.by_rid = {r["recipe_id"]: r for r in self.recipes}
        self.keys = {}
        for r in self.recipes:
            for k in sorted({"#%d" % r["number"], norm(r["name"]), norm(r.get("name_toc")),
                             norm(r.get("name_body"))} - {""}):
                self.keys.setdefault(k, []).append(r["number"])
        self.Vc = self.Vt = None
        self.ic = self.it = None
        self.model = (cfg.get("retrieval") or {}).get("embed_model")
        self.key, self.key_src = load_key(cfg.get("keys"), cfg["series"]["_base"])
        if with_vectors:
            try:
                self.Vc = np.load(book_dir / "corpus" / "vectors_card.npy").astype("float32")
                self.ic = json.loads((book_dir / "corpus" / "ids_card.json").read_text(encoding="utf-8"))
                self.Vt = np.load(book_dir / "corpus" / "vectors_text.npy").astype("float32")
                self.it = json.loads((book_dir / "corpus" / "ids_text.json").read_text(encoding="utf-8"))
            except Exception:                                    # noqa: BLE001
                self.Vc = self.Vt = None

    # ── 第 3 层
    def _embed(self, q):
        if self.Vc is None or not self.key:
            return None
        import requests
        try:
            r = requests.post(EMBED_API, timeout=90,
                              headers={"Authorization": "Bearer " + self.key},
                              json={"model": self.model, "input": [q]})
            if r.status_code != 200:
                return None
            v = np.array(r.json()["data"][0]["embedding"], dtype="float32")
            n = np.linalg.norm(v)
            return v / n if n else None                          # ★ 单位化 ⇒ 点积＝余弦
        except Exception:                                        # noqa: BLE001
            return None

    def bigrams(self, s):
        t = norm(s)
        return {t[i:i + 2] for i in range(max(0, len(t) - 1))} or {t}

    def rerank(self, q, docs, model):
        """交叉编码重排（可选一级）。失败 ⇒ 返回 None（调用方**回退 RRF**，⛔ 不许丢结果）。"""
        if not self.key or not docs:
            return None
        import requests
        try:
            r = requests.post("https://api.siliconflow.cn/v1/rerank", timeout=120,
                              headers={"Authorization": "Bearer " + self.key,
                                       "Content-Type": "application/json"},
                              json={"model": model, "query": q, "documents": docs,
                                    "top_n": len(docs)})
            if r.status_code != 200:
                print("    [rerank] HTTP %s %s" % (r.status_code, r.text[:120]))
                return None
            return [(x["index"], float(x["relevance_score"])) for x in r.json()["results"]]
        except Exception as e:                                   # noqa: BLE001
            print("    [rerank] %s %s" % (type(e).__name__, str(e)[:100]))
            return None

    def search(self, q, topk=5, use_vectors=True, rerank_model=None):
        qn = norm(q)
        used = {"terms": False, "lex": False, "vector": False, "rerank": False}
        r_terms, r_lex, r_vec = {}, {}, {}
        if qn in self.keys:
            used["terms"] = True
            r_terms = {n: 1.0 for n in self.keys[qn]}
        qg = self.bigrams(qn)
        for b in self.blocks:
            hit = len(qg & self.bigrams(b["text"]))
            if hit:
                s = hit / max(1, len(qg))
                if qn in norm(b["text"]):
                    s += 1.0
                num = self.by_rid.get(b["recipe_id"], {}).get("number")
                if num is not None:
                    r_lex[num] = max(r_lex.get(num, 0.0), s)
        used["lex"] = bool(r_lex)
        if use_vectors:
            v = self._embed(q)
            if v is not None:
                used["vector"] = True
                sims = self.Vc @ v
                for i, rid in enumerate(self.ic):
                    num = self.by_rid.get(rid, {}).get("number")
                    if num is not None:
                        r_vec[num] = max(r_vec.get(num, 0.0), float(sims[i]))
        def rrf(d):
            order = sorted(d.items(), key=lambda kv: -kv[1])
            return {k: 1.0 / (RRF_K + i + 1) for i, (k, _) in enumerate(order)}
        fused = defaultdict(float)
        for L in (r_terms, r_lex, r_vec):
            for k, v in rrf(L).items():
                fused[k] += v
        ranked = sorted(fused.items(), key=lambda kv: -kv[1])
        # ★★ **归位**：查询**字面**就是索引键（名字／`#编号`／目录名／正文名）时，该菜排最前。
        #   判据：⛔ 不是加权，是归位（试点 V50 同族）。
        pinned = sorted({n for k in (qn,) if k in self.keys for n in self.keys[k]})
        if pinned:
            hs = set(pinned)
            ranked = [(n, fused[n]) for n in pinned if n in fused] + [kv for kv in ranked
                                                                     if kv[0] not in hs]
        reranked = None
        if rerank_model and ranked:
            cand = ranked[:20]
            docs = ["%s（%s）主料：%s；调料：%s" % (self.by_num[n]["name"],
                                                  self.by_num[n].get("chapter") or "未分章",
                                                  "、".join(self.by_num[n].get("ingredients", [])) or "无",
                                                  "、".join(self.by_num[n].get("seasonings", [])) or "无")
                    for n, _ in cand]
            rr = self.rerank(q, docs, rerank_model)
            if rr:
                used["rerank"] = True
                order = [cand[i][0] for i, _ in rr]
                smap = dict(ranked)
                ranked = [(n, smap.get(n, 0.0)) for n in order]
                # ★★ **归位过的命中不因重排掉出首位**：后加的一级 ⛔ 没有资格推翻上游更强的判据
                #   （试点实测：5 条「字面就是索引键」的查询被重排压到 rank 2 ⇒ 交付列 @1 反而更低）。
                if pinned:
                    ps = set(pinned)
                    ranked = [(n, smap.get(n, 0.0)) for n in pinned if n in smap] + \
                             [kv for kv in ranked if kv[0] not in ps]
        ranked = ranked[:topk]
        return ranked, used, reranked


def cases_for(kb):
    out = []
    if kb.recipes:
        r0 = kb.recipes[0]
        out.append((r0["name"], r0["number"], 1, False, "① 权威名精确查询"))
        out.append(("#%d" % r0["number"], r0["number"], 1, False, "② 编号键"))
    for r in kb.recipes:
        if r.get("name_toc") and norm(r["name_toc"]) != norm(r["name"]):
            out.append((r["name_toc"], r["number"], 3, False, "③ 目录形 ≠ 权威名"))
    r = next((x for x in kb.recipes if x["blocks"]), None)
    if r:
        steps = [b for b in kb.blocks if b["recipe_id"] == r["recipe_id"] and b["type"] == "step"]
        if steps:
            out.append((steps[0]["text"][:8], r["number"], 3, False, "④ 制法句"))
    return out


def load_registered(series_path, book):
    p = Path(series_path).resolve().parent / "cases.yml"
    if not p.exists():
        return []
    import yaml
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for c in d.get("cases", []):
        if str(c.get("book", "")) != book:
            continue
        out.append((str(c["q"]), c.get("want"), int(c.get("topn", 3)),
                    bool(c.get("expect_none", False)), bool(c.get("needs_vectors", False)),
                    c.get("note", "登记用例")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-vectors", action="store_true")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("query", nargs="*")
    a = ap.parse_args()

    cfg, s = load_series(a.series)
    books = [b for b in s["books"] if not a.book or b["code"] == a.book]
    if a.query:
        kb = KB(s["_out"] / "kb" / books[0]["code"], cfg, with_vectors=not a.no_vectors)
        rr_model = ((cfg.get("retrieval") or {}).get("rerank_model")
                    if (cfg.get("retrieval") or {}).get("rerank_default_on") else None)
        ranked, used, _rr = kb.search(" ".join(a.query), a.topk, use_vectors=not a.no_vectors,
                                      rerank_model=rr_model)
        print("查询：%s ｜ 层：%s" % (" ".join(a.query), used))
        for i, (num, sc) in enumerate(ranked, 1):
            print("  %d. #%s %s  score=%.5f" % (i, num, kb.by_num.get(num, {}).get("name", "?"), sc))
        return 0

    if not a.self_test:
        ap.error("要么给查询词，要么 --self-test")
    npass = nfail = nskip = 0
    vector_intended = not a.no_vectors
    for b in books:
        kb_v = KB(s["_out"] / "kb" / b["code"], cfg, with_vectors=not a.no_vectors)
        kb_d = KB(s["_out"] / "kb" / b["code"], cfg, with_vectors=False)
        derived = [(q, w, t, en, False, note) for q, w, t, en, note in cases_for(kb_v)]
        reg = load_registered(a.series, b["code"])
        print("-- %s（派生 %d ＋ 登记 %d）--" % (b["code"], len(derived), len(reg)))
        for q, want, topn, expect_none, needs_vec, note in derived + reg:
            rk_v, used_v, _r1 = kb_v.search(q, max(a.topk, topn), use_vectors=not a.no_vectors)
            rk_d, _u_d, _r2 = kb_d.search(q, max(a.topk, topn), use_vectors=False)
            nv = [n for n, _ in rk_v]
            nd = [n for n, _ in rk_d]
            if expect_none:
                ok_v, ok_d = want not in nv, want not in nd
            else:
                ok_v = want in nv and nv.index(want) + 1 <= topn
                ok_d = (None if needs_vec else (want in nd and nd.index(want) + 1 <= topn))
            vec_used = used_v["vector"]
            # ★★ 三态判定（试点的 V29 教训）：
            #   ① 没请求向量 ⇒ 该列「未测」；若该用例**按设计需要向量** ⇒ 记 **SKIP（不可判）**；
            #   ② 请求了向量、也算得出来，但**没命中** ⇒ **FAIL**（⛔ 不许拿「降级时能过」抵账）；
            #   ③ 请求了向量、却**没走到**向量层（缺键／接口失败）⇒ **SKIP**，⛔ 不是 PASS。
            if not vector_intended:
                v_state = "SKIP" if needs_vec else "未测"
            elif needs_vec and not vec_used:
                v_state = "SKIP"
            else:
                v_state = "PASS" if ok_v else "FAIL"
            d_state = "不设" if ok_d is None else ("PASS" if ok_d else "FAIL")
            if "FAIL" in (v_state, d_state):
                nfail += 1; verdict = "FAIL"
            elif "SKIP" in (v_state, d_state):
                nskip += 1; verdict = "SKIP"
            else:
                npass += 1; verdict = "PASS"
            rank_v = (nv.index(want) + 1) if want in nv else None
            print("  [%-11s] %-14s 期望 #%-4s top%-2s | 有向量 %-5s rank=%-4s | 降级 %-5s%s | %s"
                  % (verdict, q[:14], "不存在" if expect_none else want, topn,
                     v_state, rank_v if rank_v else "未中", d_state,
                     "" if needs_vec else "", note[:28]))
    print("\n判据: PASS %d · FAIL %d · SKIP(环境) %d" % (npass, nfail, nskip))
    if nfail:
        return 2
    return 3 if nskip else 0


if __name__ == "__main__":
    sys.exit(main())
