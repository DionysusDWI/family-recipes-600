#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S6 —— **门禁骨架**（逐册 G 系列 · 只读产物 ＋ 调用其它阶段脚本）。

| 门 | 判据 | 失败意味着 |
|---|---|---|
| G0 | 幂等：`s2_build_corpus --check` exit 0 | 装配不可复现（输入没变而产物变了） |
| G1 | 形态：`_book.json` 的字节/页数与**盘上源件**实测相符 | 源件被换过或读数陈旧 |
| G2 | 编号连续 ＋ 每条记录都有制法 | 装配漏条 / 变体没处理干净 |
| G5 | 便携：产物中**绝对路径 0** · 禁止串 0 | 产物不可移植、可能泄漏本机信息 |
| G9 | 自测：`s5_search --self-test` exit 0 | 检索层不达标 |
| Z  | 判决回写：`_meta.json.gates.verdict` 与本门一致 | 两处状态各自为政 |

★ 本件是**骨架**：向量门（G4）与重排门随 S4 迁入后补；★ 反控（植入坏法必须变红）见 `templates/gates.md` §四。
用法：python verify_gates.py --series <series.yml> [--book CODE]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ABS_RE = re.compile(r"(?<![A-Za-z0-9:/])(?:[A-Za-z]:[\\/]|\\\\)")
# ★ 禁止串清单：⛔ 这里**不写本机专有名**（那是本地表的事，见技能 §4.2「判据不可自指」）
BANNED = ["<tmp>", "forbidden-fragments.local"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    a = ap.parse_args()

    import yaml
    p = Path(a.series).resolve()
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    base = p.parent
    s = cfg["series"]
    out = (base / str(s["out_root"])).resolve()
    src_root = (base / str(s["source_root"])).resolve()
    books = [b for b in s["books"] if not a.book or b["code"] == a.book]

    bad_total = 0
    skip_total = 0
    for b in books:
        code = b["code"]
        kdir = out / "kb" / code
        fails = []
        skips = []          # ★ 第三态：**不可判**（如「请求了向量却没走到向量层」）
        reads = {}

        # G0 幂等
        rc, _o = run([sys.executable, str(HERE / "s2_build_corpus.py"), "--series", str(p),
                      "--book", code, "--check"])
        reads["G0_idempotent"] = rc
        if rc != 0:
            fails.append("G0")

        # G1 形态
        bj = json.loads((kdir / "_book.json").read_text(encoding="utf-8"))
        src = src_root / b["basename"]
        ok1 = src.exists() and bj["source"]["bytes"] == src.stat().st_size
        reads["G1_shape"] = {"source_bytes": src.stat().st_size if src.exists() else None,
                             "recorded": bj["source"]["bytes"], "pages": bj["source"]["pages"]}
        if not ok1:
            fails.append("G1")

        # G2 编号/制法
        meta = json.loads((kdir / "_meta.json").read_text(encoding="utf-8"))
        c = meta["counts"]
        ok2 = bool(c["numbers_contiguous"]) and not c["recipes_without_method"]
        reads["G2_assembly"] = {"contiguous": c["numbers_contiguous"],
                                "without_method": c["recipes_without_method"]}
        if not ok2:
            fails.append("G2")

        # G3 索引与别名族（幂等 ＋ 两条判语：前向「台账字对都在族里」· 后向「声明的缺口有用例覆盖」）
        rc3, _o3 = run([sys.executable, str(HERE / "s3_build_index.py"), "--series", str(p),
                        "--book", code, "--check"])
        m3 = json.loads((kdir / "_meta.json").read_text(encoding="utf-8")).get("gates", {}).get("G3_index", {})
        ok3 = (rc3 == 0 and not m3.get("forward_missing_pairs") and not m3.get("backward_uncovered_gaps"))
        reads["G3_index"] = {"check_exit": rc3, "families": m3.get("families"),
                             "forward_missing": m3.get("forward_missing_pairs"),
                             "backward_uncovered": m3.get("backward_uncovered_gaps")}
        if not ok3:
            fails.append("G3")

        # G4 向量（签名/产物一致 ＋ 五条判语：行数 · id 唯一 · 单位范数 · 签名对模型/精度敏感）
        rc4, _o4 = run([sys.executable, str(HERE / "s4_build_vectors.py"), "--series", str(p),
                        "--book", code, "--check"])
        rep = json.loads((kdir / "corpus" / "vectors_report.json").read_text(encoding="utf-8"))
        g4gates = rep.get("gates", {})
        ok4 = (rc4 == 0 and all(g4gates.values()))
        reads["G4_vectors"] = {"check_exit": rc4, "model": rep.get("model"),
                               "api_calls_last": rep.get("api_calls"), "gates": g4gates}
        if not ok4:
            fails.append("G4")

        # G6 灾备零网络（★ 「零网络」必须被**制造出来**：禁掉 socket 出网口后灾备侧仍要出读数）
        rc6, o6 = run([sys.executable, str(HERE / "s5c_fallback.py"), "--series", str(p),
                       "--book", code, "--zero-network-selftest"])
        tail6 = [l.strip() for l in o6.splitlines() if "判定" in l or "RAG 侧优雅降级" in l]
        reads["G6_fallback_zero_network"] = {"exit": rc6, "tail": tail6[-2:]}
        if rc6 != 0:
            fails.append("G6")

        # G5 便携
        hits = []
        for f in sorted(kdir.rglob("*")):
            if f.is_file() and f.suffix in (".json", ".jsonl", ".txt", ".md", ".tsv"):
                t = f.read_text(encoding="utf-8", errors="replace")
                if ABS_RE.search(t):
                    hits.append("%s:绝对路径" % f.name)
                for bn in BANNED:
                    if bn in t:
                        hits.append("%s:禁止串" % f.name)
        reads["G5_portable"] = hits
        if hits:
            fails.append("G5")

        # G9 自测
        rc, o = run([sys.executable, str(HERE / "s5_search.py"), "--series", str(p),
                     "--book", code, "--self-test"])
        reads["G9_self_test"] = {"exit": rc,
                                 "tail": [l for l in o.splitlines() if l.startswith("判据:")]}
        if rc == 3:
            skips.append("G9")          # ★ 不可判 ⇒ ⛔ 不算通过、也⛔ 不算失败（三态语义）
        elif rc != 0:
            fails.append("G9")

        # Z 判决回写
        verdict = "FAIL" if fails else ("SKIP" if skips else "PASS")
        meta.setdefault("gates", {})["verdict"] = verdict
        meta["gates"]["fails"] = fails
        meta["gates"]["skips"] = skips
        meta["gates"]["readings"] = reads
        (kdir / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8", newline="\n")
        print("  %-6s VERDICT: %s  fails=%s skips=%s"
              % (code, verdict, fails or "无", skips or "无"))
        for k, v in reads.items():
            print("        %-16s %s" % (k, json.dumps(v, ensure_ascii=False)[:110]))
        bad_total += len(fails)
        skip_total += len(skips)
    print("\n合计 FAIL = %d · SKIP = %d" % (bad_total, skip_total))
    if bad_total:
        return 2
    return 3 if skip_total else 0


if __name__ == "__main__":
    sys.exit(main())
