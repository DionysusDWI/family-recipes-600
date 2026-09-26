#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S6 —— **门禁骨架**（逐册 G 系列 · 只读产物 ＋ 调用其它阶段脚本）。

| 门 | 判据 | 失败意味着 |
|---|---|---|
| G0 | 幂等：`s2_build_corpus --check` exit 0 | 装配不可复现（输入没变而产物变了） |
| G1 | 形态：`_book.json` 的字节/页数与**盘上源件**实测相符 | 源件被换过或读数陈旧 |
| G2 | 编号连续 ＋ 每条记录都有制法 | 装配漏条 / 变体没处理干净 |
| G5 | 便携：产物中**绝对路径 0** · **在册禁令 0** · **水印 0** | 产物不可移植、可能泄漏本机信息或来源水印 |
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
# ★ 禁止串清单**来自配置**，⛔ 不在代码里硬编码（缺口 G-04）。
#   实测旧版：`BANNED = ["<tmp>", "forbidden-fragments.local"]` ——
#   ① 换一套书即失效（禁令写在代码里）；② 声明了「水印 0」却**没有**任何水印判据（缺口 G-03）。
#   ⇒ 现在：在册禁令读 `config/forbidden-strings.txt`，水印读 `series.yml` 的 `watermark_strip`。
BANNED_FILE = "config/forbidden-strings.txt"


def load_banned(base):
    """读在册禁令表 ⇒ `(清单, 读数)`。

    ⛔ 文件不存在 ⇒ 返回 `None`：**不可判**，⛔ 不是「通过」——
       「一个『没找到』必须以『不可判』的姿态出现」（与「无键 ⇒ SKIP」同一族纪律）。
    """
    f = base / BANNED_FILE
    if not f.exists():
        return None, "%s 不存在 ⇒ ⛔ 不可判（不是通过）" % BANNED_FILE
    items = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()        # 注释
        if not ln or ln.startswith("["):        # `[watermark]` 之类的分节标题
            continue
        items.append(ln)
    return items, "%s ⇒ %d 条" % (BANNED_FILE, len(items))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def classify(rc):
    """★★ 退出码 ⇒ **三态**（缺口 **G-09**）。

    `3` 在本技能里是一个**约定的语义**：**不可判（环境）** ——
    `s4_build_vectors.py`（无键）与 `s5_search.py`（请求了向量却没走到）都用它。
    ⛔ 旧版只给 G9 实现了三态，其余各门一律 `rc != 0 ⇒ FAIL`
    ⇒ 「没跑到」被说成了「跑坏了」，本机无键时基线**永久假红**（实测 `fails=['G4']`）。
    ★ 三态必须**逐门一致**，否则读者无法区分「门坏了」与「门没跑」。
    """
    return "ok" if rc == 0 else ("skip" if rc == 3 else "fail")


def gate(rc, name, fails, skips, extra_bad=False):
    """把一次子进程退出码按三态落进 `fails` / `skips`；返回状态串。"""
    st = classify(rc)
    if st == "fail" or (st == "ok" and extra_bad):
        fails.append(name)
    elif st == "skip":
        skips.append(name)
    return st


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
    # ★ G5 的两张判据表都来自配置：在册禁令 ＋ 本系列水印（缺口 G-03 / G-04）
    banned, banned_note = load_banned(base)
    wms = [str(x).strip() for x in (cfg.get("watermark_strip") or []) if str(x).strip()]
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
        gate(rc, "G0", fails, skips)

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
        ok3 = (not m3.get("forward_missing_pairs") and not m3.get("backward_uncovered_gaps"))
        reads["G3_index"] = {"check_exit": rc3, "families": m3.get("families"),
                             "forward_missing": m3.get("forward_missing_pairs"),
                             "backward_uncovered": m3.get("backward_uncovered_gaps")}
        gate(rc3, "G3", fails, skips, extra_bad=not ok3)

        # G4 向量（签名/产物一致 ＋ 五条判语：行数 · id 唯一 · 单位范数 · 签名对模型/精度敏感）
        rc4, _o4 = run([sys.executable, str(HERE / "s4_build_vectors.py"), "--series", str(p),
                        "--book", code, "--check"])
        rp = kdir / "corpus" / "vectors_report.json"
        rep = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        g4gates = rep.get("gates", {}) or {}
        reads["G4_vectors"] = {"check_exit": rc4, "model": rep.get("model"),
                               "api_calls_last": rep.get("api_calls"), "gates": g4gates}
        # ★★ 缺口 **G-24**：`--check` 的 exit 3 ＝「**签名不符 ⇒ 需重算**」。
        #    此时盘上的 `vectors_report.json` 描述的是**另一份语料**，⛔ 它的 `gates`
        #    不是对**当前**语料的证据 ⇒ 必须**先短路**。
        #    ⛔ 否则会拿旧报告的判语去判新语料，把「语料变了、向量没重算」又说成「向量坏了」。
        if rc4 == 3:
            skips.append("G4")
            reads["G4_vectors"]["why"] = "签名不符 ⇒ 需重算（★ 旧报告判语对当前语料无效）"
        # ★★ G-09 的正身：无键时 `--check` 返回 **3（不可判）**，⛔ 不是 FAIL。
        #    ⛔ 但**报告里已经记着的判语**若为假，那是与键无关的真失败。
        elif g4gates and not all(g4gates.values()):
            fails.append("G4")
        else:
            gate(rc4, "G4", fails, skips)

        # G6 灾备零网络（★ 「零网络」必须被**制造出来**：禁掉 socket 出网口后灾备侧仍要出读数）
        rc6, o6 = run([sys.executable, str(HERE / "s5c_fallback.py"), "--series", str(p),
                       "--book", code, "--zero-network-selftest"])
        tail6 = [l.strip() for l in o6.splitlines() if "判定" in l or "RAG 侧优雅降级" in l]
        reads["G6_fallback_zero_network"] = {"exit": rc6, "tail": tail6[-2:]}
        gate(rc6, "G6", fails, skips)

        # G5 便携（★ 判据来自配置：绝对路径 ＋ 在册禁令 ＋ 本系列水印）
        hits = []
        for f in sorted(kdir.rglob("*")):
            if f.is_file() and f.suffix in (".json", ".jsonl", ".txt", ".md", ".tsv"):
                t = f.read_text(encoding="utf-8", errors="replace")
                if ABS_RE.search(t):
                    hits.append("%s:绝对路径" % f.name)
                for bn in (banned or []):
                    if bn in t:
                        hits.append("%s:在册禁令" % f.name)
                for w in wms:
                    if w in t:
                        hits.append("%s:水印" % f.name)
        reads["G5_portable"] = hits
        reads["G5_banned_source"] = banned_note
        if hits:
            fails.append("G5")
        elif banned is None:
            skips.append("G5")          # ★ 不可判 ⇒ ⛔ 不算通过、也⛔ 不算失败（三态语义）

        # G9 自测
        rc, o = run([sys.executable, str(HERE / "s5_search.py"), "--series", str(p),
                     "--book", code, "--self-test"])
        reads["G9_self_test"] = {"exit": rc,
                                 "tail": [l for l in o.splitlines() if l.startswith("判据:")]}
        gate(rc, "G9", fails, skips)    # ★ 三态：exit 3 ⇒ SKIP（⛔ 不算通过、也⛔ 不算失败）
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
