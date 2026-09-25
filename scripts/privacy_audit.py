#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""隐私复审（**逐件**）—— 产出 `PRIVACY-AUDIT.tsv`（⛔ 只记路径与标签，**不记命中字面**）。

★ 为什么单独一件（不并进打包器）：
  · 打包器的隐私门是**发布前的闸门**（命中即拒）；本件是**可复核的审计记录**（逐件判决）；
  · 两者共用同一套「机器相关串」来源：`privacy-forbidden.local.txt`（逐行字面 · git 忽略）
    ＋ 形状规则（盘符 · 临时根 · 邮箱 · 令牌）。

★ 判据（可失败）：**逐件判决 = PASS / FAIL**；`FAIL` 非零 ⇒ 退出码 2。
  ★ 命中的**行号与标签**要记（供人复核），⛔ **字面不记**（否则审计报告本身就是泄漏）。
用法：
    python privacy_audit.py --skill <技能目录> [--tsv PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = Path(__file__).resolve().parent
SKIP_DIRS = {"__pycache__", ".git", "out", "scratch"}
SCAN = [
    ("绝对路径(盘符)", re.compile(r"(?<![A-Za-z0-9:/])[A-Za-z]:[\\/]")),
    ("本机临时根", re.compile(r"[A-Za-z]:\\[^\"'\n]*system-temp", re.I)),
    ("邮箱形态", re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.I)),
    ("令牌形态", re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|gh[pous]_[A-Za-z0-9]{20,})\b")),
]
# ★ 豁免（⛔ 不静默）：① **扫描器／门自身**（规则字面就是被测形态 —— 已知坑 #81）；
#   ② **本机禁止表本身**（它就是那些串的容器；git 忽略、⛔ 不入仓、⛔ 不进发布体）。
SELF = {"scripts/privacy_audit.py", "scripts/pack_release.py", "scripts/verify_gates.py",
        "privacy-forbidden.local.txt"}


def load_local(skill: Path):
    p = skill / "privacy-forbidden.local.txt"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--tsv")
    a = ap.parse_args()
    skill = Path(a.skill).resolve()
    local = load_local(skill)
    print("== 隐私复审（%s）==" % skill.name)
    print("   本机禁止表：%d 条（%s）"
          % (len(local), "存在" if local else "**不存在** ⇒ 只跑形状规则"))
    rows, fails = [], 0
    for f in sorted(skill.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(skill).as_posix()
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        try:
            txt = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            rows.append((rel, "PASS", "二进制（免扫）", ""))
            continue
        labels, exempt = [], []
        for label, rx in SCAN:
            m = rx.search(txt)
            if not m:
                continue
            line = txt[:m.start()].split("\n")[-1] + txt[m.start():].split("\n")[0]
            if "re.compile(" in line or "re.escape(" in line or rel in SELF:
                exempt.append(label + "(规则/扫描器)")
            else:
                labels.append("%s@L%d" % (label, txt[:m.start()].count("\n") + 1))
        for lit in local:
            if lit in txt and rel in SELF:                  # ★ 本机禁止表自身豁免（它就是这个容器）
                exempt.append('本机禁止串(禁止表自身)')
                continue
            if lit in txt:
                labels.append("本机禁止串@L%d" % (txt[:lit.find(lit)].count("\n") + 1
                                              if lit in txt else 0))
        verdict = "PASS" if not labels else "FAIL"
        fails += 1 if labels else 0
        rows.append((rel, verdict, ",".join(labels) or (",".join(exempt) + "（豁免）" if exempt else ""), ""))
    for rel, v, note, _ in rows:
        if v == "FAIL" or "豁免" in note:
            print("   [%s] %-46s %s" % (v, rel, note))
    print("   逐件判决：PASS %d · FAIL %d（共 %d 件）"
          % (sum(1 for r in rows if r[1] == "PASS"), fails, len(rows)))
    if a.tsv:
        out = ["path\tverdict\tlabels_or_exemption\tnote"]
        out += ["%s\t%s\t%s\t%s" % r for r in rows]
        Path(a.tsv).write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
        print("   TSV ⇒ %s" % a.tsv)
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
