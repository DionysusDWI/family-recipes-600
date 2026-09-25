#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S4 —— **向量**（参数化 · 带签名 · 幂等）。

★★ 三条不可动摇在这里落地（都**可失败**）：
  ① **签名必须含「模型名 ＋ 输入 id ＋ 文本 ＋ dtype」** —— 少任何一项，换模型/换精度时
     快速路径会**静默复用旧向量**（试点实测：换模型而签名不含模型名 ⇒ 命中快速路径，一个 API 都不发）。
  ② **幂等**：复跑必须 `api_calls = 0`（全部 part 命中）—— 否则说明签名不稳定。
  ③ 产物自洽：行数 == 记录数/块数 · id 唯一 · **向量 L2 归一化**（点积才等于余弦）。

用法：
    python s4_build_vectors.py --series <series.yml> [--book CODE] [--check] [--dry-run]
    --check：只重新计算签名与自洽判据，**不发请求**（与在盘 `vectors_report.json` 比对）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

import numpy as np                                            # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _keys import load_key                                    # noqa: E402

DTYPE = "float16"
EMBED_API = "https://api.siliconflow.cn/v1/embeddings"
MODEL_SLUG = "vl-embed-8b"


def sig_of(model, ids, texts, dtype):
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    for i, t in zip(ids, texts):
        h.update(b"\x00")
        h.update(str(i).encode("utf-8"))
        h.update(b"\x01")
        h.update(t.encode("utf-8"))
    return "%s_%d_%s_%s" % (h.hexdigest()[:16], len(ids), dtype, MODEL_SLUG)


def card_text(r):
    return "%s（%s）主料：%s；调料：%s" % (r["name"], r.get("chapter") or "未分章",
                                          "、".join(r.get("ingredients", [])) or "无",
                                          "、".join(r.get("seasonings", [])) or "无")


def embed(texts, model, key, batch=32):
    import requests
    out, calls = [], 0
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        r = requests.post(EMBED_API, timeout=120,
                          headers={"Authorization": "Bearer " + key},
                          json={"model": model, "input": chunk})
        calls += 1
        if r.status_code != 200:
            raise RuntimeError("embed HTTP %s %s" % (r.status_code, r.text[:200]))
        out += [d["embedding"] for d in r.json()["data"]]
    return np.array(out, dtype="float32"), calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import yaml
    p = Path(a.series).resolve()
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    base = p.parent
    s = cfg["series"]
    out = (base / str(s["out_root"])).resolve()
    model = (cfg.get("retrieval") or {}).get("embed_model", "Qwen/Qwen3-VL-Embedding-8B")
    key, src = load_key(cfg.get("keys"), base)
    print("== S4 向量（%s）==\n   模型 %s ｜ dtype %s\n   密钥来源 %s" % (s["id"], model, DTYPE, src))
    if not key:
        print("  [SKIP] 无键 ⇒ ⛔ 本阶段不可判（**不是通过**）")
        return 3

    books = [b for b in s["books"] if not a.book or b["code"] == a.book]
    bad = 0
    for b in books:
        kdir = out / "kb" / b["code"]
        recs = [json.loads(l) for l in
                (kdir / "corpus" / "recipes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        blocks = [json.loads(l) for l in
                  (kdir / "corpus" / "blocks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        card_ids = [r["recipe_id"] for r in recs]
        card_tx = [card_text(r) for r in recs]
        text_ids = [x["bid"] for x in blocks]
        text_tx = [x["text"] for x in blocks]
        sig_c, sig_t = (sig_of(model, card_ids, card_tx, DTYPE),
                        sig_of(model, text_ids, text_tx, DTYPE))
        rep_p = kdir / "corpus" / "vectors_report.json"
        old = json.loads(rep_p.read_text(encoding="utf-8")) if rep_p.exists() else {}
        hits = int(old.get("sig_card") == sig_c and old.get("sig_text") == sig_t)
        calls = 0
        if a.check:
            ok = (old.get("model") == model and old.get("dtype") == DTYPE
                  and old.get("sig_card") == sig_c and old.get("sig_text") == sig_t
                  and (kdir / "corpus" / "vectors_card.npy").exists()
                  and (kdir / "corpus" / "vectors_text.npy").exists())
            print("  [%s] %-6s --check：模型/签名/产物 %s"
                  % ("PASS" if ok else "FAIL", b["code"], "一致" if ok else "**不一致**（需重跑 S4）"))
            bad += 0 if ok else 1
            continue
        if a.dry_run:
            print("  [PASS] %-6s 计划：卡 %d 条 · 块 %d 条 · 签名 %s / %s（当前 %s）"
                  % (b["code"], len(card_ids), len(text_ids), sig_c[:10], sig_t[:10],
                     "命中 ⇒ 0 请求" if hits else "未命中 ⇒ 需重算"))
            continue
        if hits:
            Vc = np.load(kdir / "corpus" / "vectors_card.npy")
            Vt = np.load(kdir / "corpus" / "vectors_text.npy")
        else:
            Vc, c1 = embed(card_tx, model, key)
            Vt, c2 = embed(text_tx, model, key)
            calls = c1 + c2
            # ★ L2 归一化：点积 == 余弦的前提（★ 归一化是**我们**做的，⛔ 不是模型的承诺）
            Vc = Vc / np.linalg.norm(Vc, axis=1, keepdims=True)
            Vt = Vt / np.linalg.norm(Vt, axis=1, keepdims=True)
            np.save(kdir / "corpus" / "vectors_card.npy", Vc.astype(DTYPE))
            np.save(kdir / "corpus" / "vectors_text.npy", Vt.astype(DTYPE))
            (kdir / "corpus" / "ids_card.json").write_text(json.dumps(card_ids), encoding="utf-8", newline="\n")
            (kdir / "corpus" / "ids_text.json").write_text(json.dumps(text_ids), encoding="utf-8", newline="\n")
        n_c = np.linalg.norm(Vc.astype("float32"), axis=1)
        n_t = np.linalg.norm(Vt.astype("float32"), axis=1)
        # ★★ 判据不是「模型名出现在签名字符串里」（那是哈希，永远不会出现），
        #   而是**签名对模型/精度敏感**：改一个字符、改一次 dtype，签名必须变。
        #   ⇒ 这条判据是**可失败的**：若有人把签名写死/漏掉某一项，它会红。
        sig_sens_model = sig_of(model + "#x", card_ids, card_tx, DTYPE) != sig_c
        sig_sens_dtype = sig_of(model, card_ids, card_tx, "float32") != sig_c
        report = {"book": b["code"], "model": model, "dtype": DTYPE,
                  "sig_card": sig_c, "sig_text": sig_t,
                  "cards": len(card_ids), "texts": len(text_ids),
                  "api_calls": calls, "sig_hit": bool(hits),
                  "l2_card": [round(float(n_c.min()), 4), round(float(n_c.max()), 4)],
                  "l2_text": [round(float(n_t.min()), 4), round(float(n_t.max()), 4)],
                  "ids_unique_card": len(set(card_ids)) == len(card_ids),
                  "ids_unique_text": len(set(text_ids)) == len(text_ids),
                  "gates": {"rows_match": len(Vc) == len(card_ids) and len(Vt) == len(text_ids),
                            "ids_unique": len(set(card_ids)) == len(card_ids) and len(set(text_ids)) == len(text_ids),
                            "unit_norm": bool(abs(n_c.max() - 1) < 2e-3 and abs(n_t.max() - 1) < 2e-3),
                            "sig_sensitive_to_model": bool(sig_sens_model),
                            "sig_sensitive_to_dtype": bool(sig_sens_dtype)}}
        ok = all(report["gates"].values())
        print("  [%s] %-6s 卡 %d · 块 %d · API %d 批 · 签名命中=%s · L2 [%.4f,%.4f] · id 唯一=%s"
              % ("PASS" if ok else "FAIL", b["code"], len(card_ids), len(text_ids), calls, bool(hits),
                 n_c.min(), n_c.max(), report["ids_unique_card"]))
        rep_p.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8", newline="\n")
        bad += 0 if ok else 1
    print("\n  结论：%s" % ("全部通过" if not bad else "%d 册有问题" % bad))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
