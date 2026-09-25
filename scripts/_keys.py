#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""密钥读取阶梯（**通用件**）：环境变量 → 仓**外**用户级 key 文件 → 仓内模板。

★ 三条纪律（试点构建的裁定）：
  ① **读取顺序固定**：环境变量 → 仓外 key 文件（`keys.key_file_candidates`，或 `<ENV>_FILE` 指定）→ 仓内模板；
  ② **真钥永不入仓**：仓内只放模板与占位符；⛔ 占位符不得长得像真钥；
  ③ **⛔ 不打印密钥**：只报**来源**与长度。

用法（库）：from _keys import load_key; key, source = load_key(cfg_keys)
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _read_file(p: Path):
    """仓外 key 文件：允许**裸行**或 JSON（{"key": "..."}）。"""
    try:
        t = p.read_text(encoding="utf-8").strip()
    except Exception:                                            # noqa: BLE001
        return None
    if not t:
        return None
    if t.startswith("{"):
        try:
            d = json.loads(t)
            for k in ("key", "api_key", "siliconflow", "SILICONFLOW_API_KEY"):
                if isinstance(d.get(k), str) and d[k].strip():
                    return d[k].strip()
        except Exception:                                        # noqa: BLE001
            return None
        return None
    return t.splitlines()[0].strip() or None


def load_key(cfg_keys, base: Path | None = None):
    """返回 (key or None, 来源说明)。⛔ 绝不返回或打印密钥本身之外的东西。"""
    cfg_keys = cfg_keys or {}
    env_var = cfg_keys.get("env_var", "")
    if env_var:
        v = os.environ.get(env_var)
        if v:
            return v, "env:%s（长度 %d）" % (env_var, len(v))
    cands = []
    explicit = os.environ.get((env_var or "KEY") + "_FILE")
    if explicit:
        cands.append(Path(explicit))
    for c in cfg_keys.get("key_file_candidates", []) or []:
        cands.append(Path(os.path.expanduser(c)))
    for p in cands:
        if p.exists():
            v = _read_file(p)
            if v:
                return v, "file:%s（长度 %d）" % (p.name, len(v))
    tmpl = cfg_keys.get("template")
    if tmpl:
        p = (base or Path.cwd()) / tmpl
        return None, "无键 ⇒ 读取阶梯三档全落空（环境变量 %s · 仓外候选 %d 个 · 模板 %s%s）" % (
            env_var or "（未配）", len(cands),
            tmpl, "" if p.exists() else "（模板也不存在）")
    return None, "无键 ⇒ 未配置任何来源"
