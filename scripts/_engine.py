#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""引擎身份 —— **版本标签** ＋ **内容指纹**。★ 单一来源，⛔ 任何脚本不得自己拼。

★ 为什么有这个文件（缺口 **G-17**，实测于 `family-recipes-600`）：
  该仓把 `scripts/` 当作技能引擎的一份**只读快照**卖进仓库，之后技能侧继续修 bug
  （`_paths.py` · G-05~G-24 …），而仓内快照**不动**。于是**同一条命令在两处给出两个答案**：

      技能仓  privacy_audit 命中行号 @L5      ｜  工程仓  @L1（G-07 未修版）
      技能仓  s0c 9/9 PASS                    ｜  工程仓 8/9 exit 2（G-01 未修版）

  ⇒ 分叉**已经发生**，而**没有任何门在读它** —— 这是最坏的一种：静默。
  修法不是「每次记得同步」，而是**让引擎能被指认**，再由仓级 R 门去比对。

★★ 两个量**分工不同，缺一不可**：
  · `engine_id()`   —— `scripts/` 下全部 `*.py` 的**内容指纹**（顺序无关）。
                      改一个字节就变 ⇒ 它是**承重**的那个，⛔ 不依赖任何人记得改版本号。
  · `engine_version()` —— `scripts/_ENGINE` 里的**人读标签**。它可以让两份内容不同的引擎
                      顶着同一个号，也可能忘了升 ⇒ ★ **单靠版本号判「引擎变了」是不可靠的**。

⇒ 仓级门（`repo_check.py` R1/R2）**两个都比对**，任一不符即红。

用法：
    from _engine import engine          # {'version': '0.1.3', 'id': 'ab12…'}
    from _engine import engine_id, engine_version
"""
from __future__ import annotations

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = HERE / "_ENGINE"


def engine_version():
    """人读版本标签（`scripts/_ENGINE` 的 `version=` 行）；⛔ 缺失时**不猜**。"""
    if META.exists():
        for line in META.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version="):
                return line.split("=", 1)[1].strip()
    return "unrecorded"


def engine_id(full=False):
    """`scripts/**/*.py` 的内容指纹。★ 与文件名**和**内容都相关，⛔ 与 mtime 无关。

    ★ 只取 `.py`：`README.md`／`_ENGINE` 改字不该算「引擎变了」。
    ★ 截断到 16 位只是**显示**需要；比对一律用本函数返回值，⛔ 不要自己截。
    """
    h = hashlib.sha256()
    for p in sorted(HERE.rglob("*.py")):
        h.update(p.relative_to(HERE).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    d = h.hexdigest()
    return d if full else d[:16]


def engine():
    return {"version": engine_version(), "id": engine_id()}


if __name__ == "__main__":
    import json
    print(json.dumps(engine(), ensure_ascii=False))
