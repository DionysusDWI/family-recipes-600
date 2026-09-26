#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仓级 **R 系列**门 —— 逐册 G 系列之外的、只对**本仓**成立的判据。

★ 为什么 R 系列不属于技能本体（`series.yml: gates.repo_check`）：G 系列判「一册产物合不合规」，
  而 R 系列判「**这个仓**有没有在悄悄错下去」—— 换一个仓，判据就换。

现有四道（★ 每道都必须**可失败**，否则不算门）：

  R1  engine-lock       本仓产物的出处引擎 vs 现行 `scripts/` 引擎 —— **内容指纹**比对（承重）
  R2  engine-version    两者的人读版本标签比对（★ 产物侧 `unrecorded` ⇒ SKIP，⛔ 不猜）
  R3  privacy-table     `privacy-forbidden.local.txt` 存在、非空、且**不是**审计 TSV（G-15 事故形态）
  R4  engine-selfcheck  `scripts/_engine.py` 可导入且 `scripts/_ENGINE` 有版本行

用法：
    python repo_check.py                 # 跑全部
    python repo_check.py --json
    python repo_check.py --accept-engine --reason "<为什么可以认为产物已重建>"

★ `--accept-engine` **必须**给理由，且会把这次转变**追加**到 `ENGINE.log`。
  ⛔ 它不是「消红按钮」：R1 红的意思是**产物需要按现行引擎重建**，
  而本脚本**无法**知道你是否真的重建过 —— 它只能把这句话记下来。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _engine import engine, engine_id, engine_version      # noqa: E402

LOCK = HERE / "ENGINE.lock"
LOG = HERE / "ENGINE.log"
FORBIDDEN = HERE / "privacy-forbidden.local.txt"
# ★ G-15 的**事故签名**：审计器 `--tsv` 写出的表头（`privacy_audit.py:220`）。
#   禁止表一旦被它覆盖过，首行就是这个。
AUDIT_HEADER = "path\tverdict\tlabels_or_exemption\tnote"


def read_lock():
    """解析 `ENGINE.lock` 的 `key=value`（`#` 起头为注释）。"""
    d = {}
    if not LOCK.exists():
        return d
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        d[k.strip()] = v.strip()
    return d


def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--accept-engine", action="store_true")
    ap.add_argument("--reason")
    a = ap.parse_args()

    cur = engine()
    lock = read_lock()

    if a.accept_engine:
        if not a.reason or not a.reason.strip():
            print("  [FAIL] --accept-engine **必须**带 --reason（⛔ 不许无理由消红）")
            return 2
        old = lock.get("artifact_engine_id", "(缺失)")
        cur_v = cur["version"]
        LOCK.write_text(
            "# ENGINE.lock —— **本仓产物**是由哪一版引擎产出的。\n"
            "# ★ 判据分工见 scripts/_engine.py 头注：id 承重，version 只是标签。\n"
            "# ⛔ 本文件描述**产物出处**的引擎，不是当前 scripts/ 里的引擎。\n"
            "\n"
            "artifact_engine_id=%s\n"
            "artifact_engine_version=%s\n"
            "note=由 repo_check.py --accept-engine 于 %s 改写（旧 id=%s）。理由：%s\n"
            % (cur["id"], cur_v, now_cn(), old, a.reason.strip()),
            encoding="utf-8", newline="\n")
        with LOG.open("a", encoding="utf-8", newline="\n") as f:
            f.write("%s\taccept-engine\t%s->%s\t%s\n"
                    % (now_cn(), old, cur["id"], a.reason.strip()))
        print("  [OK] ENGINE.lock 已改写：%s -> %s（★ 已记入 ENGINE.log）" % (old, cur["id"]))
        return 0

    fails, skips, reads = [], [], {}

    # ── R1 · 产物出处引擎 vs 现行引擎（内容指纹｜承重）
    if not LOCK.exists():
        fails.append("R1")
        reads["R1"] = {"lock": "缺失"}
        print("  [FAIL] R1 engine-lock：`ENGINE.lock` **不存在** ⇒ 产物出处不可判（⛔ 缺锁不是 SKIP）")
    else:
        want = lock.get("artifact_engine_id")
        ok = (want == cur["id"])
        reads["R1"] = {"lock_id": want, "current_id": cur["id"], "match": ok}
        print("  [%s] R1 engine-lock：产物出处 %s ｜ 现行 %s ⇒ %s"
              % ("PASS" if ok else "FAIL", want, cur["id"],
                 "一致" if ok else "★ **不一致** ⇒ 产物需按现行引擎重建"))
        if not ok:
            fails.append("R1")

    # ── R2 · 版本标签（人读｜⛔ 非承重）
    lv, cv = lock.get("artifact_engine_version"), cur["version"]
    if lv in (None, "", "unrecorded") or cv in (None, "", "unrecorded"):
        skips.append("R2")
        reads["R2"] = {"lock_version": lv, "current_version": cv, "why": "有一侧无标签 ⇒ 不可判"}
        print("  [SKIP] R2 engine-version：产物侧 %r ｜ 现行侧 %r ⇒ ⛔ 不可判（**不是通过**）"
              % (lv, cv))
    else:
        ok2 = (lv == cv)
        reads["R2"] = {"lock_version": lv, "current_version": cv, "match": ok2}
        print("  [%s] R2 engine-version：%s ｜ %s ⇒ %s"
              % ("PASS" if ok2 else "FAIL", lv, cv, "一致" if ok2 else "**不一致**"))
        if not ok2:
            fails.append("R2")

    # ── R3 · 本机禁止表（G-15 的**事故形态**：被审计 TSV 整份覆盖）
    if not FORBIDDEN.exists():
        fails.append("R3")
        reads["R3"] = {"exists": False}
        print("  [FAIL] R3 privacy-table：`%s` **不存在** ⇒ 隐私门无判据" % FORBIDDEN.name)
    else:
        lines = [l for l in FORBIDDEN.read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        first = lines[0].strip() if lines else ""
        clobbered = first.startswith(AUDIT_HEADER)
        rules = len(lines)
        ok3 = (rules > 0) and not clobbered
        reads["R3"] = {"exists": True, "rules": rules, "clobbered": clobbered}
        if clobbered:
            print("  [FAIL] R3 privacy-table：★ 首行是**审计 TSV 的表头** ⇒ 本表已被 `--tsv` 覆盖（G-15）")
        elif rules == 0:
            print("  [FAIL] R3 privacy-table：本表**零条规则** ⇒ 隐私门永远不会命中")
        else:
            print("  [PASS] R3 privacy-table：%d 条规则 · 未被审计 TSV 覆盖" % rules)
        if not ok3:
            fails.append("R3")

    # ── R4 · 引擎自检能被算出（防止 `scripts/` 被替换成不含 `_engine.py` 的旧快照）
    ok4 = bool(cur["id"]) and (SCRIPTS / "_ENGINE").exists()
    reads["R4"] = {"engine_id": cur["id"], "has_ENGINE": (SCRIPTS / "_ENGINE").exists()}
    print("  [%s] R4 engine-selfcheck：id=%s ｜ `_ENGINE` %s"
          % ("PASS" if ok4 else "FAIL", cur["id"],
             "在" if reads["R4"]["has_ENGINE"] else "**缺失**"))
    if not ok4:
        fails.append("R4")

    verdict = "FAIL" if fails else ("SKIP" if skips else "PASS")
    print("\n  R 系列 VERDICT: %s  fails=%s skips=%s"
          % (verdict, fails or "无", skips or "无"))

    if a.json:
        print(json.dumps({"verdict": verdict, "fails": fails, "skips": skips,
                          "reads": reads, "engine": cur}, ensure_ascii=False, indent=1))
    if fails:
        return 2
    return 3 if skips else 0


if __name__ == "__main__":
    sys.exit(main())
