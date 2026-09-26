#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S0 配置校验器 —— 在动手之前，先把 `series.yml` 判一遍（**只读**）。

★ 为什么它是技能的第一步：本技能的七条不可动摇①「仪器先标定」。
  配置就是**仪器**：它错，后面每一步都白跑，而且**不会报错**（会用默认值一路跑下去）。

判据（每条都可失败，逐条打印读数）：

  ① 必填字段齐全（`series.id/title/out_root/source_root/books`）
  ② `id` 符合 kebab 文法 `^[a-z0-9]+(-[a-z0-9]+)*$`（会进向量签名与仓名）
  ③ 册码**唯一**且符合 `^[A-Za-z][A-Za-z0-9-]{1,7}$`（★ 登记即固化，⛔ 不排序得到）
  ④ ★ **`source_root` 不得落在 `out_root` 之内**（否则源件会被当成产物打包 —— 便携门必红）
  ⑤ ★ **模板占位符 `<…>` 必须已被替换** —— 但只在**值位置**判：正则**命名组** `(?P<name>…)`
     与**注释区**的举例都**不是**占位符（缺口 G-01：旧判据对整篇原文 findall，会**假红**）
  ⑥ 每册 `basename` 非空；若源件存在，**实测**字节数与页数并报出（⛔ 不读配置里的自称值）
  ⑦ 密钥：配置里⛔ 不得出现疑似真钥的字符串（只允许环境变量名与仓外路径）

用法：
    python s0c_series_check.py --series <series.yml>            # 校验并打印后续门清单
    python s0c_series_check.py --series <series.yml> --json     # 机器可读

退出码：0 ＝ 全部通过 · 2 ＝ 有 FAIL（逐条列出）· 3 ＝ 配置读不到/解析不了
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,7}$")
PLACEHOLDER_RE = re.compile(r"<[^<>]{1,60}>")
# ★ 正则**命名组** `(?P<name>…)` 不是占位符 —— 引擎**要求**它（见 s2_build_corpus.py 的 glossary_pattern）
RE_GROUP_RE = re.compile(r"\(\?P<[^<>]{1,60}>")
KEYLIKE_RE = re.compile(r"\b(sk-[A-Za-z0-9]{16,}|[A-Za-z0-9_-]{32,})\b")

results = []


def placeholder_hits(raw: str):
    """★ 只在**值位置**找占位符（缺口 G-01 的修法）。

    旧判据 `PLACEHOLDER_RE.findall(整篇原文)` 分不清三类尖括号：
      ① 模板占位符（**该报**）—— 例如 `title: "<标题>"`
      ② 正则命名组 `(?P<marker>…)`（⛔ **不该报**）—— 引擎要它，⛔ 不是「没替换」
      ③ 注释里的举例 `# 产物落 ./kb/<册码>/`（⛔ **不该报**）—— 文档必须能写形状

    ★ 决定性证据：修前**技能自己的回归夹具**跑不过自己的门 ——
      `s0c_series_check.py --series examples/toy-series/series.yml` ⇒ 8/9 · exit 2。
      （P1 记为 9/9，只是因为它的冒烟配置 `example-series.yml` **没有注释区** ⇒ 夹具从未被那道门跑过。）

    ⚠ 已知边界：`#` 一律按**行内注释起点**理解 ⇒ 若某个**带引号的值**里含 `#` 且其后跟 `<…>`，
      会漏报。★ 这是**故意取窄**：漏报一条，好过让每份真实配置永久假红。
    """
    hits = []
    for ln in raw.splitlines():
        code = ln.split("#", 1)[0]                 # ① 注释区不算值位置
        code = RE_GROUP_RE.sub("", code)           # ② 命名组不是占位符
        hits.extend(PLACEHOLDER_RE.findall(code))
    return sorted(set(hits))


def check(name, ok, detail):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print("  [%s] %-22s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = Path(a.series).resolve()
    if not p.exists():
        print("⛔ 配置不存在：%s" % p, file=sys.stderr)
        return 3
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:                                      # noqa: BLE001
        print("⛔ 配置解析失败：%s: %s" % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return 3
    if not isinstance(cfg, dict) or not isinstance(cfg.get("series"), dict):
        print("⛔ 顶层必须是 `series:` 映射", file=sys.stderr)
        return 3

    raw = p.read_text(encoding="utf-8")
    s = cfg["series"]
    print("== S0 配置校验（%s）==" % p.name)

    # ① 必填
    need = ["id", "title", "out_root", "source_root", "books"]
    miss = [k for k in need if not s.get(k)]
    check("required-fields", not miss, "缺：%s" % (miss or "无"))

    # ② id 文法
    sid = str(s.get("id", ""))
    check("series-id-grammar", bool(ID_RE.match(sid)), "id=%r" % sid)

    # ③ 册码
    books = s.get("books") if isinstance(s.get("books"), list) else []
    codes = [str(b.get("code", "")) for b in books if isinstance(b, dict)]
    bad_codes = [c for c in codes if not CODE_RE.match(c)]
    dup = sorted({c for c in codes if codes.count(c) > 1})
    check("book-codes-grammar", not bad_codes and bool(codes),
          "%d 册 · 不合文法：%s" % (len(codes), bad_codes or "无"))
    check("book-codes-unique", not dup, "重复：%s" % (dup or "无"))

    # ④ source_root 不得落在 out_root 内
    base = p.parent
    out_root = (base / str(s.get("out_root", ""))).resolve()
    src_root = (base / str(s.get("source_root", ""))).resolve()
    inside = False
    try:
        src_root.relative_to(out_root)
        inside = True
    except ValueError:
        inside = False
    check("source-not-inside-out", not inside,
          "out=%s · src=%s ⇒ %s" % (out_root.name, src_root.name,
                                    "src 在 out 之内（会把源件打包）" if inside else "互不包含"))

    # ⑤ 模板占位符（★ 只在值位置；注释与正则命名组都不算）
    ph = placeholder_hits(raw)
    check("placeholders-replaced", not ph, "未替换：%s" % (ph[:6] or "无"))

    # ⑥ 每册 basename ＋ 实测（存在才测）
    missing, measured = [], []
    for b in books:
        if not isinstance(b, dict):
            continue
        bn = str(b.get("basename", "")).strip()
        if not bn:
            missing.append(str(b.get("code", "?")))
            continue
        f = src_root / bn
        if f.exists():
            measured.append("%s: %d B" % (b.get("code"), f.stat().st_size))
    check("book-basenames", not missing, "缺 basename：%s" % (missing or "无"))
    check("source-files-present", bool(measured) or not src_root.exists(),
          "实测：%s%s" % (", ".join(measured[:4]) or "无（源根不可达 ⇒ 只校验配置）",
                          "" if len(measured) <= 4 else " …"))

    # ⑦ 密钥形态
    kl = KEYLIKE_RE.findall(raw)
    check("no-inline-secret", not kl, "疑似真钥 %d 处（只允许环境变量名与仓外路径）" % len(kl))

    bad = [r for r in results if not r["ok"]]
    print("\n== 结论 ==")
    print("  通过 %d / %d" % (len(results) - len(bad), len(results)))
    if bad:
        print("  ⛔ 先修这些再动手：%s" % "、".join(r["check"] for r in bad))
    else:
        print("  ✅ 配置可用。后续门清单：")
        print("     S0 形态（每册 _book.json）→ S1 转写（0 FAIL · 提示词版本落盘）→ "
              "S2 装配（编号连续 · 分歧有处置）→ S3 索引（别名族派生 · 缺口双向）→ "
              "S4 向量（签名含模型与 dtype · 幂等）→ S5 检索（双模式＋交付模式三列）→ "
              "S6 门禁（G 系列逐册 ＋ R 系列仓级，**每道门先跑反控**）→ S7 发布（回程校验三条）")
    if a.json:
        print(json.dumps({"series": str(p), "results": results,
                          "pass": len(results) - len(bad), "fail": len(bad)},
                         ensure_ascii=False, indent=1))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
