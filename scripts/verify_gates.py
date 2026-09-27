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
sys.path.insert(0, str(HERE))
from _paths import pages_dir as resolve_pages_dir       # noqa: E402  ★ G-02 的单一来源
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


# ★★ G-33：**印本自身的号错**（⛔ 不是转写错）走**具名豁免** —— 仓根 `ERRATA.tsv`。
#   为什么不改数据：那个号是**印本印出来的**，改数据＝产物与印本不再逐字一致 ⇒ 事实被抹平。
#   三条纪律（与 `privacy-allow.txt` · `repo_check --accept-engine` 同一族）：
#     ① ⛔ **无证据不受理** —— 每行必须带 `evidence` 与 `source`（源页），否则该行**作废并报出**；
#     ② ⛔ **只豁免具名的那一个**（作用域 ＋ 号）—— 未在册的撞号/缺号**照旧红**，⛔ 无「整类豁免」；
#     ③ ★ **豁免一律打印** —— 门从红转绿时，必须读出是**哪一行**换来的。
#   ★ 缺表 ⇒ **零豁免**（更严，⛔ 不是「跳过」）：与 `load_banned` 的三态语义不同，
#     此处「没有表」只会让门**更红**，所以不需要 SKIP 态。
ERRATA_FILE = "ERRATA.tsv"
ERRATA_KINDS = ("print_duplicate_number", "print_missing_number")
ERRATA_COLS = ("book", "scope", "kind", "value", "expected", "evidence", "source")


def scope_code(x):
    """作用域比对键：只取首段代码（`C23 五、烧菜类` 与 `C23` 视为同一作用域）。

    ★ 为什么必须归一：`_meta.json` 的缺号键是 **`C23 五、烧菜类`**（含章名），
      而归因列给出的 `scope` 是 **`C23`**（`scope_id`）⇒ 不归一时**两侧永远对不上**，
      豁免会**在它本该生效的输入上悄悄失效**（与 G-31 v1 判据同一种错法）。
    """
    return str(x or "").split()[0] if str(x or "").split() else ""


def load_errata(base, override=None):
    """读在册**印本错**声明表 ⇒ `(受理行, 不受理行, 读数)`（★ G-33）。"""
    f = Path(override).resolve() if override else (base / ERRATA_FILE)
    if not f.exists():
        return [], [], "%s 不存在 ⇒ **零豁免**（门按原始读数判，⛔ 不是跳过）" % f.name
    ok, bad = [], []
    for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        parts = ln.split("\t")
        row = dict(zip(ERRATA_COLS, [x.strip() for x in parts]))
        row["line"] = i
        if len(parts) < len(ERRATA_COLS):
            bad.append({"line": i, "why": "列数 %d < %d ⇒ 不受理" % (len(parts), len(ERRATA_COLS))})
            continue
        if row["kind"] not in ERRATA_KINDS:
            bad.append({"line": i, "why": "kind 不在册：%s" % row["kind"]})
            continue
        if not row["evidence"] or not row["source"]:
            bad.append({"line": i, "why": "⛔ 无 evidence / 无 source（源页）⇒ 不受理"})
            continue
        ok.append(row)
    return ok, bad, "%s ⇒ 受理 %d 行 · 不受理 %d 行" % (f.name, len(ok), len(bad))


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


def id_collision_attribution(kdir, cfg=None, pages_dir=None):
    """**G-31 归因列** —— `recipe_id` 撞号是「**装配侧**」还是「**转写侧**」造成的。

    ★ 为什么需要它：`G4` 的 `ids_unique=false` 把两种成因记成**同一格** ⇒
      门**红得正确，却不指向任何可执行动作**（改配置救不了转写侧的撞号）。

    ★★ 判据（v2）：对每一组撞号，取其**页跨度**（由 `corpus/blocks.jsonl` 的 `page_from` 定），
      在跨度内找**「像边界却没被认出来」**的行 —— 满足**全部**四个条件：
        ① 形如 `@@SECTION <t>`；② `<t>` **不在** `contract.sections` 的在册节名里；
        ③ **不匹配** `chapter_pattern`，也**不匹配** `subchapter_pattern`（这些是**已认出来**的边界）；
        ④ 其后**首个非空行**是 `@@RECIPE_START`（★ 与 G-29 同一判据：真子类标题后必跟一条食谱）。
      **找到 ≥1 行 ⇒ 装配侧**（配置本可把这些边界分开，却没分开）；
      **找不到 ⇒ 转写侧**（边界标记**根本没进产物** ⇒ 漏标；或印本号写错 ⇒ 同作用域内撞号）。

    ★★ v1 判据（「`chapter`/`sub_chapter` 不同 ⇒ 装配侧」）**已被自己的反控证伪**：
      掐掉 `subchapter_pattern` 后，两侧 `sub_chapter` **都变成空串**（⛔ 不是「不同」），
      于是那条判据**在它本该生效的场景里永远不可能触发**。⇒ 归因**必须看页面证据**，⛔ 不看字段差异。

    ★ 这是**归因**，⛔ 不是判决：它**不改变** `G4` 的红/绿（强度不变）。
    """
    rp = kdir / "corpus" / "recipes.jsonl"
    bp = kdir / "corpus" / "blocks.jsonl"
    if not rp.exists() or not bp.exists():
        return None
    rows = [json.loads(l) for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
    blocks = [json.loads(l) for l in bp.read_text(encoding="utf-8").splitlines() if l.strip()]
    pages_of = {}
    for b in blocks:
        pages_of.setdefault(b.get("recipe_id"), set()).add(b.get("page_from"))

    import re as _re
    c = (cfg or {}).get("contract", {}) or {}
    sec_names = set()
    for group in (c.get("sections", {}) or {}).values():
        for name in (group or []):
            sec_names.add(_re.sub(r"\s+", "", str(name)))
    chap_re = _re.compile(c["chapter_pattern"]) if c.get("chapter_pattern") else None
    sub_re = _re.compile(c["subchapter_pattern"]) if c.get("subchapter_pattern") else None
    m_sec = ((c.get("markers", {}) or {}).get("section", "@@SECTION"))
    m_rs = ((c.get("markers", {}) or {}).get("recipe_start", "@@RECIPE_START"))

    def headings_in(pages):
        """跨度内「像边界却没被认出来」的行（页, 原文）。"""
        # ★★ 页目录**必须**走 `_paths.pages_dir`（G-02 的单一来源），⛔ 不得拼 `kdir/_pages`。
        #   实测踩过：夹具（`examples/printed-style`）的页文件**不在** `out/kb/<册>/_pages/`
        #   —— S2 是**从 `pages_root` 读**、⛔ 不复制 ⇒ 拼 `kdir/_pages` 时扫描集**恒为空**，
        #   函数**永远**返回「转写侧」。★ 是**反控**（向 2）把它抓出来的，⛔ 不是评审。
        root = Path(pages_dir) if pages_dir else (kdir / "_pages")
        out = []
        for p in sorted(pages):
            if p is None:
                continue
            f = root / ("p%04d.md" % p)
            if not f.exists():
                continue
            lines = f.read_text(encoding="utf-8").splitlines()
            for i, ln in enumerate(lines):
                s = ln.strip()
                if not s.startswith(m_sec):
                    continue
                t = s[len(m_sec):].strip()
                if _re.sub(r"\s+", "", t) in sec_names:
                    continue
                if chap_re and chap_re.match(t):
                    continue
                if sub_re and sub_re.match(t):
                    continue
                nxt = ""
                for n in lines[i + 1:]:
                    if n.strip():
                        nxt = n.strip()
                        break
                if nxt.startswith(m_rs):
                    out.append({"page": p, "line": i + 1, "text": s[:60]})
        return out

    by = {}
    for r in rows:
        by.setdefault(r.get("recipe_id"), []).append(r)
    dup = {k: v for k, v in by.items() if len(v) > 1}
    asm = trans = 0
    examples = []
    for rid in sorted(dup):
        grp = dup[rid]
        pages = set()
        for r in grp:
            pages |= {p for p in pages_of.get(rid, set()) if p is not None}
        hs = headings_in(pages)
        if hs:
            asm += 1
            examples.append({"id": rid, "side": "assembly", "unrecognized_boundaries": hs[:3]})
        else:
            trans += 1
            examples.append({"id": rid, "side": "transcription",
                             "scope": (grp[0].get("scope_id") or ""),
                             "chapter": grp[0].get("chapter") or "",
                             "records": len(grp),
                             "numbers": sorted(x.get("number") for x in grp)})
    # ★★ G-33：`examples` 截断到 12 条（人读用），而**豁免判据需要全集** ⇒ 另给一份纯读数。
    #    ⛔ 不得用 `examples` 判「是否全部撞号都在册」—— 截断会把第 13 个撞号**静默算成已豁免**。
    dup_list = [{"id": rid, "scope": scope_code(dup[rid][0].get("scope_id")),
                 "numbers": sorted(x.get("number") for x in dup[rid])} for rid in sorted(dup)]
    return {"duplicate_ids": len(dup), "assembly_side": asm, "transcription_side": trans,
            "criterion": ("v2 页跨度内存在「结构 + 位置」都像边界却未被 chapter/subchapter 认出的 "
                          "@@SECTION 行（其后紧跟 @@RECIPE_START）⇒ 装配侧；否则 ⇒ 转写侧"),
            "duplicate_id_list": dup_list,
            "examples": examples[:12]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    # ★ G-33：路径**只有**这一处可改，且它**只能让门更严**（指向空表/坏表 ⇒ 豁免失效 ⇒ 照旧红）
    #   ⇒ 因此它是**反控**的入口（正控＝在册表、负控＝空表），⛔ 不是「消红开关」。
    ap.add_argument("--errata-file", help="覆盖 ERRATA.tsv 路径（★ 反控用：空表应使门回到红）")
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
    # ★★ G-33：印本错声明表（★ 缺表＝零豁免；不受理的行**打印出来**，⛔ 不静默丢弃）
    errata, errata_bad, errata_note = load_errata(base, a.errata_file)
    print("★ %s" % errata_note)
    for r in errata_bad:
        print("  ⛔ ERRATA 第 %s 行不受理：%s" % (r["line"], r["why"]))
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
        # ★ G-33：本册适用的印本错行（`*`／空串＝全册适用）
        erows = [r for r in errata if r["book"] in ("", code, "*")]

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

        # G2 编号/制法/拒收
        meta = json.loads((kdir / "_meta.json").read_text(encoding="utf-8"))
        c = meta["counts"]
        # ★★ G-29：连续性判据必须**按编号作用域**取，⛔ 不是恒取「全册 1..N」。
        #   ★ 实测踩过：`numbering: per_chapter` 的册上，全局连续**必然为假**（每章从 1 重起），
        #     旧版读的是 `numbers_contiguous` ⇒ 它红的原因是**取错了那一格**，与装配无关。
        contig_raw = (bool(c.get("numbers_contiguous_per_chapter"))
                      if c.get("numbering") == "per_chapter" else bool(c["numbers_contiguous"]))
        # ★★ G-33：**印本号错**具名豁免（⛔ 只减掉在册点名的那些号）。
        #    ★ 本册实测：14 个作用域缺号里**只有 C23 的 1 处**是印本印错（重 9 缺 8），
        #      其余 13 处是**转写把食谱标题标成了 `@@SECTION`**（`p0017 （四）火腿龙须` 实证）
        #      ⇒ 它们**不在豁免之列**，G2 照旧红 —— 这是**正确的读数**，⛔ 不是漏配。
        miss_raw = c.get("numbers_missing_within_chapter") or {}
        ex_miss = {(scope_code(r["scope"]), r["value"]) for r in erows
                   if r["kind"] == "print_missing_number"}
        miss_exempted = sorted([sc, n] for sc, ns in miss_raw.items() for n in ns
                               if (scope_code(sc), str(n)) in ex_miss)
        miss_eff = {sc: [n for n in ns if (scope_code(sc), str(n)) not in ex_miss]
                    for sc, ns in miss_raw.items()}
        miss_eff = {sc: ns for sc, ns in miss_eff.items() if ns}
        # ★ 放行条件**三条缺一不可**：原始不连续 · 原始确有缺号 · 缺号**全部**在册
        contig = bool(contig_raw) or (bool(miss_raw) and not miss_eff and bool(miss_exempted))
        # ★★ G-28：这里是**两条不同的判据**，⛔ 不可合并成一条：
        #   `accounted`（恒等式）标记行数 ＋ 变体①起点数 == 记录数 ＋ 拒收数 ⇒ 抓「起点跑到账外」；
        #   `accepted` （判语）  拒收 == 0                              ⇒ 抓「真的丢了内容」。
        #   ★ 变体①（整页无标记）的起点**没有标记行**，所以 ⛔ 不能只写 `标记行数 == 记录数`。
        starts_n, rec_n = c.get("starts_body"), c.get("recipes")
        v1_n = c.get("recipes_from_variant1")
        rj = c.get("rejected_starts_by_reason") or {}
        rj_n = sum(rj.values()) if isinstance(rj, dict) else 0
        if starts_n is None or v1_n is None:
            # ★ 产物出自**不带拒收回执**的旧引擎 ⇒ 这一格**不可判**，⛔ 不是通过。
            skips.append("G2_receipt")
            starts_ok = True
        else:
            starts_ok = (starts_n + v1_n) == (rec_n + rj_n) and rj_n == 0
        ok2 = contig and not c["recipes_without_method"] and starts_ok
        reads["G2_assembly"] = {"contiguous_in_scope": contig,
                                "contiguous_raw": contig_raw,
                                "errata_exempted_missing": miss_exempted,
                                "missing_effective": miss_eff,
                                "numbering": c.get("numbering"),
                                "without_method": c["recipes_without_method"],
                                "starts_body": starts_n, "recipes_from_variant1": v1_n,
                                "recipes": rec_n,
                                "accepted_all_starts": None if starts_n is None else (rj_n == 0),
                                "rejected": rj}
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
        attr = id_collision_attribution(
            kdir, cfg, resolve_pages_dir(p.parent, (cfg.get("series", {}) or {}), code))
        reads["G4_vectors"] = {"check_exit": rc4, "model": rep.get("model"),
                               "api_calls_last": rep.get("api_calls"), "gates": g4gates,
                               # ★★ G-31 归因列：**只加读数，⛔ 不改判决**（强度不变）
                               "id_collision_attribution": attr}
        # ★★ G-33：`ids_unique=false` 若**全部**撞号都能被在册印本错点名 ⇒ 具名豁免。
        #    ★ 用的是**全集** `duplicate_id_list`（⛔ 不是人读的 `examples`，那被截断到 12 条）；
        #      只要还剩**一个**未在册的撞号，就 ⛔ 不豁免（照旧红，并由 `duplicates_uncovered` 点名）。
        g4_bad = sorted(k for k, v in g4gates.items() if not v)
        ex_dup = {(scope_code(r["scope"]), r["value"]) for r in erows
                  if r["kind"] == "print_duplicate_number"}
        dup_all = (attr or {}).get("duplicate_id_list") or []
        dup_uncovered = sorted(d["id"] for d in dup_all
                               if not any((d.get("scope"), str(n)) in ex_dup
                                          for n in (d.get("numbers") or [])))
        g4_exempted = []
        if "ids_unique" in g4_bad and dup_all and not dup_uncovered:
            g4_bad = [k for k in g4_bad if k != "ids_unique"]
            g4_exempted = ["ids_unique: %d 个撞号全部在册（%s）"
                           % (len(dup_all), ",".join(d["id"] for d in dup_all))]
        reads["G4_vectors"]["gates_bad_after_errata"] = g4_bad
        reads["G4_vectors"]["errata_exempted"] = g4_exempted
        reads["G4_vectors"]["duplicates_uncovered"] = dup_uncovered
        # ★★ 缺口 **G-24**：`--check` 的 exit 3 ＝「**签名不符 ⇒ 需重算**」。
        #    此时盘上的 `vectors_report.json` 描述的是**另一份语料**，⛔ 它的 `gates`
        #    不是对**当前**语料的证据 ⇒ 必须**先短路**。
        #    ⛔ 否则会拿旧报告的判语去判新语料，把「语料变了、向量没重算」又说成「向量坏了」。
        if rc4 == 3:
            skips.append("G4")
            reads["G4_vectors"]["why"] = "签名不符 ⇒ 需重算（★ 旧报告判语对当前语料无效）"
        # ★★ G-09 的正身：无键时 `--check` 返回 **3（不可判）**，⛔ 不是 FAIL。
        #    ⛔ 但**报告里已经记着的判语**若为假，那是与键无关的真失败。
        #    ★ G-33：这里的 `g4_bad` **已扣掉在册印本错**（旧版写 `all(g4gates.values())`）。
        elif g4_bad:
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
        # ★ G-33：豁免读数**入册** —— 门转绿时必须能读出「是哪一行换来的」（纪律 ③）
        reads["errata"] = {
            "note": errata_note, "rejected": errata_bad,
            "accepted_lines": [r["line"] for r in erows],
            "accepted": sorted("%s:%s=%s" % (scope_code(r["scope"]), r["kind"], r["value"])
                               for r in erows)}
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
