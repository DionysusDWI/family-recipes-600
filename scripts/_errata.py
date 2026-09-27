#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`ERRATA.tsv` —— **印本自身的错**声明表 · 读取器（★ 单一来源）。

★ 为什么必须是**一个**模块：本表现在被**两侧**读 ——
  · 生成侧 `s2_build_corpus.py`（缺口 **G-36**：给印本重号那条加**确定性后缀**，消除 id 撞号）；
  · 门侧   `verify_gates.py`（缺口 **G-33**：具名豁免）。
  ⛔ 若两侧各写一份解析，它们迟早对**同一行**给出两个答案 —— 本项目已经栽过同族错误
  （`_paths.py` 立起来之前，S1 写 `_pages/` 而 S2 读 `pages_root/`，见 **G-02**）。

★★ 三条纪律（**承重**，⛔ 不得为让门变绿而放宽）：
  ① ⛔ **无证据不受理** —— 每行必须带 `evidence` 与 `source`（源页），否则该行**作废并报出**；
  ② ⛔ **只对具名的那一个生效**（作用域 ＋ 号）—— 未在册的撞号/缺号**照旧红**，⛔ 无「整类豁免」；
  ③ ★ **一律打印** —— 门从红转绿时，必须读出是**哪一行**换来的。
★ 缺表 ⇒ **零生效**（更严，⛔ 不是「跳过」）：与 `load_banned` 的三态语义不同，
  此处「没有表」只会让读数**更红**，所以不需要 SKIP 态。
"""
from __future__ import annotations

from pathlib import Path

ERRATA_FILE = "ERRATA.tsv"
ERRATA_KINDS = ("print_duplicate_number", "print_missing_number")
ERRATA_COLS = ("book", "scope", "kind", "value", "expected", "evidence", "source")


def scope_code(x):
    """作用域比对键：只取首段代码（`C23 五、烧菜类` 与 `C23` 视为同一作用域）。

    ★ 为什么必须归一：`_meta.json` 的缺号键是 **`C23 五、烧菜类`**（含章名），
      而归因列给出的 `scope` 是 **`C23`**（`scope_id`）⇒ 不归一时**两侧永远对不上**，
      豁免会**在它本该生效的输入上悄悄失效**（与 G-31 v1 判据同一种错法）。
    """
    parts = str(x or "").split()
    return parts[0] if parts else ""


def load_errata(base, override=None):
    """读在册**印本错**声明表 ⇒ `(受理行, 不受理行, 读数)`（★ G-33 ／ G-36 共用）。"""
    f = Path(override).resolve() if override else (Path(base) / ERRATA_FILE)
    if not f.exists():
        return [], [], "%s 不存在 ⇒ **零生效**（门按原始读数判，⛔ 不是跳过）" % f.name
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


def match_rows(errata, book_code, scope_id, number, kind=None):
    """挑出**点名了这一个**（册 ＋ 作用域 ＋ 号）的受理行。

    ★ 作用域匹配用 `scope_code()` 归一 —— 见该函数头注（两侧键长得不一样）。
    ★ `book` 为空或 `*` ⇒ 全册适用。
    """
    out = []
    for r in errata:
        if r.get("book") not in ("", "*", book_code):
            continue
        if scope_code(r.get("scope")) != scope_code(scope_id):
            continue
        if kind and r.get("kind") != kind:
            continue
        try:
            if int(str(r.get("value", "")).strip()) != int(number):
                continue
        except (TypeError, ValueError):
            continue
        out.append(r)
    return out
