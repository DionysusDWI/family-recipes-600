#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""共享路径解析 —— ★ **单一来源**。

★ 为什么有这个文件：缺口 **G-02**（实测于 `family-recipes-600`）的根因不是「某个值写错了」，
  而是 **S1 与 S2 各自把 `_pages/` 的路径拼了一遍**，于是**没有任何配置取值**能让二者相等：

      S1 写：<out_root>/kb/<册码>/_pages/pNNNN.md     （硬编码 "kb" 与 "_pages"）
      S2 读：<pages_root>/<册码>/p*.md

  ⇒ 修法不是「改一个常量」，而是**把这条规则收成一个函数**：谁写谁读都走它。
  ⛔ 任何脚本都**不得**再自己拼 `kb/<册码>/_pages`。

规则（相对 **`series.yml` 所在目录**，与 `source_root` 同一锚点）：

    <pages_root>/<册码>/_pages/pNNNN.md          `pages_root` 默认 `"kb"`

★ 为什么锚点是**配置目录**而不是 `out_root`：读配置的人只需记住**一个**基准。
  `out_root` 只决定产物根（`kb/<册码>/_book.json` · `kb/<册码>/corpus/` 等）。
  ★ 两者在 `out_root: "."` 的仓里**恰好重合**，但⛔ 不要依赖这个巧合。

反控（改了本文件必须两处同时变红，否则说明有一处没走它）：

    python s1_transcribe.py --series <series.yml> --plan     # 打印的页目录
    python s2_build_corpus.py --series <series.yml>          # 报错的页目录
    # ⇒ 两条路径必须逐字相同；不同 ⇒ G-02 又回来了
"""
from __future__ import annotations

from pathlib import Path

PAGES_ROOT_DEFAULT = "kb"
PAGES_SUBDIR = "_pages"


def pages_root(base, s):
    """转写页的**根**（其下是每册一个目录）。"""
    return (Path(base) / str(s.get("pages_root", PAGES_ROOT_DEFAULT))).resolve()


def pages_dir(base, s, code):
    """某一册的转写页目录 —— ★ S1 写、S2 读**必须**都调用本函数。"""
    return pages_root(base, s) / str(code) / PAGES_SUBDIR
