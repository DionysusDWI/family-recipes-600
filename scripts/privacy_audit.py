#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""隐私复审（**逐件**）—— 产出 `PRIVACY-AUDIT.tsv`（⛔ 只记路径与标签，**不记命中字面**）。

★ 为什么单独一件（不并进打包器）：
  · 打包器的隐私门是**发布前的闸门**（命中即拒）；本件是**可复核的审计记录**（逐件判决）；
  · 两者共用同一套「机器相关串」来源：**本机禁止表**（逐行字面 · git 忽略）
    ＋ 形状规则（盘符 · 临时根 · 邮箱 · 令牌）。

★ 判据（可失败）：**逐件判决 = PASS / FAIL**；`FAIL` 非零 ⇒ 退出码 2。
  ★ 命中的**行号与标签**要记（供人复核），⛔ **字面不记**（否则审计报告本身就是泄漏）。

★★ 三态（⛔ **缺表不是通过**）：本机禁止表**一张都没找到** ⇒ **SKIP（不可判）**，退出码 **3**。
   一个「没找到」必须以「不可判」的姿态出现 —— ⛔ 不是一个绿色的 PASS。
   （真需要无表运行（夹具）时显式加 `--allow-no-table`，把这件事**说出口**。）

★★ 遍历的两条硬边界（缺口 **G-05**）：
   · `Path.rglob()` 在 Windows 上**会进入 junction**（junction 不是 symlink、`is_dir()` 为真），
     于是仓内一个指向仓外的链接会把**仓外**文件当成本仓文件 ⇒ 对它下判决、甚至把它打进发布体。
     本件改为**自走遍历**，在**重解析点**（junction / symlink）处**剪枝**，并**把剪掉的挂载点打印出来**
     （⛔ 不静默：剪枝是正确行为，但「你少扫了一棵树」必须让人看得见）。
   · `SKIP_DIRS` 里的目录名**任何层级**都跳过。

★★ 禁止表的**名字**与**豁免**（缺口 **G-06 / G-08**）：
   · G-06：本机禁止表的名字在生态里有**两套约定**（本技能 `privacy-forbidden.local.txt`
     ／同门仓 `config/forbidden-fragments.local.txt`）⇒ 本件按**候选表**逐个找，找到哪个**报哪个**。
   · G-08：**声明表**（`config/forbidden-strings.txt`，即 S6 的 G5 读的那张）**本身**必须装着一批禁令字面；
     若其中任何一条同时是「机器相关串」，审计就会**永久假红** ⇒ 声明表与禁止表一律**豁免**，且豁免**打印**。

用法：
    python privacy_audit.py --skill <技能目录> [--tsv PATH] [--allow-no-table]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = Path(__file__).resolve().parent
SKIP_DIRS = {"__pycache__", ".git", "out", "scratch"}

# ★ G-06：本机禁止表的**候选名字**（按序取第一个存在者）。
TABLE_CANDIDATES = [
    "privacy-forbidden.local.txt",
    "config/forbidden-fragments.local.txt",
    "config/privacy-forbidden.local.txt",
    "config/forbidden-strings.local.txt",
]
# ★ G-08：**声明表**（装了禁令字面，因而必须豁免）。S6 的 G5 读 `config/forbidden-strings.txt`。
DECLARATION_TABLES = [
    "config/forbidden-strings.txt",
    "config/forbidden-fragments.txt",
]

SCAN = [
    ("绝对路径(盘符)", re.compile(r"(?<![A-Za-z0-9:/])[A-Za-z]:[\\/]")),
    ("本机临时根", re.compile(r"[A-Za-z]:\\[^\"'\n]*system-temp", re.I)),
    ("邮箱形态", re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.I)),
    ("令牌形态", re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|gh[pous]_[A-Za-z0-9]{20,})\b")),
]
# ★ 豁免（⛔ 不静默）：① **扫描器／门自身**（规则字面就是被测形态 —— 已知坑 #81）；
#   ② **本机禁止表**（它就是那些串的容器；git 忽略、⛔ 不入仓、⛔ 不进发布体）；
#   ③ **声明表**（G-08：禁了什么就必须写出什么，否则永久假红）。
SELF = {"scripts/privacy_audit.py", "scripts/pack_release.py", "scripts/verify_gates.py"}

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def find_table(skill: Path):
    """按候选名找本机禁止表 ⇒ `(path or None, rel or None, tried)`。"""
    for rel in TABLE_CANDIDATES:
        p = skill / rel
        if p.is_file():
            return p, rel, TABLE_CANDIDATES
    return None, None, TABLE_CANDIDATES


def load_local(path: Path | None):
    if path is None:
        return []
    out = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


def is_reparse(p: Path) -> bool:
    """重解析点（junction / symlink）—— junction ⛔ 不是 symlink，须查属性位。"""
    try:
        st = os.stat(p, follow_symlinks=False)
    except OSError:
        return False
    if os.path.islink(p):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def walk(skill: Path):
    """仓内遍历 ⇒ `(files, mounts)`；在重解析点处**剪枝**并**记录**被剪的挂载点。"""
    files, mounts = [], []
    stack = [skill]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            p = Path(e.path)
            try:
                rel = p.relative_to(skill).as_posix()
            except ValueError:                      # 理论上到不了（剪枝在先）
                continue
            if any(part in SKIP_DIRS for part in Path(rel).parts):
                continue
            if is_reparse(p):
                mounts.append(rel)                  # ★ G-05：⛔ 不跟随、⛔ 不静默
                continue
            try:
                if e.is_dir():
                    stack.append(p)
                elif e.is_file():
                    files.append((p, rel))
            except OSError:
                continue
    files.sort(key=lambda x: x[1])
    mounts.sort()
    return files, mounts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--tsv")
    ap.add_argument("--allow-no-table", action="store_true",
                    help="⛔ 默认：一张禁止表都找不到 ⇒ SKIP（exit 3）。加此项才把「无表」当成可接受。")
    a = ap.parse_args()
    skill = Path(a.skill).resolve()

    tpath, trel, tried = find_table(skill)
    local = load_local(tpath)

    print("== 隐私复审（%s）==" % skill.name)
    if tpath is None:
        print("   [SKIP] 本机禁止表：**一张都没找到** ⇒ ⛔ 不可判（**不是通过**）")
        print("          候选名（逐个试过）：%s" % " · ".join(tried))
        print("          ⛔ 只跑形状规则**不足以**替代本机禁止串检查。")
    else:
        print("   本机禁止表：%s ⇒ %d 条" % (trel, len(local)))
    decl = [r for r in DECLARATION_TABLES if (skill / r).is_file()]
    if decl:
        print("   声明表（豁免）：%s" % " · ".join(decl))
    print("   无表运行被显式允许：%s" % ("是（--allow-no-table）" if a.allow_no_table else "否"))

    exempt = set(SELF)
    if trel:
        exempt.add(trel)
    exempt.update(decl)

    files, mounts = walk(skill)
    if mounts:
        print("   [PRUNE] 剪掉重解析点 %d 个（⛔ 未跟随 ⇒ **仓外内容没有被扫**）:" % len(mounts))
        for m in mounts:
            print("           %s" % m)

    rows, fails = [], 0
    for f, rel in files:
        try:
            txt = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            rows.append((rel, "PASS", "二进制（免扫）", ""))
            continue
        labels, ex = [], []
        for label, rx in SCAN:
            m = rx.search(txt)
            if not m:
                continue
            line = txt[:m.start()].split("\n")[-1] + txt[m.start():].split("\n")[0]
            if "re.compile(" in line or "re.escape(" in line or rel in exempt:
                ex.append(label + "(规则/扫描器)" if rel not in exempt else label + "(豁免文件)")
            else:
                labels.append("%s@L%d" % (label, txt[:m.start()].count("\n") + 1))
        for lit in local:
            if lit not in txt:
                continue
            if rel in exempt:
                ex.append("本机禁止串(禁止表/声明表自身)")
                continue
            # ★ G-07：行号必须用 `txt.find` —— 旧版写的 `lit.find(lit)` 恒为 0 ⇒ 行号**永远是 L1**。
            off = txt.find(lit)
            labels.append("本机禁止串@L%d" % (txt[:off].count("\n") + 1))
        verdict = "PASS" if not labels else "FAIL"
        fails += 1 if labels else 0
        rows.append((rel, verdict, ",".join(labels) or (",".join(ex) + "（豁免）" if ex else ""), ""))

    for rel, v, note, _ in rows:
        if v == "FAIL" or "豁免" in note:
            print("   [%s] %-46s %s" % (v, rel, note))
    print("   逐件判决：PASS %d · FAIL %d（共 %d 件）· 剪枝挂载点 %d"
          % (sum(1 for r in rows if r[1] == "PASS"), fails, len(rows), len(mounts)))
    if a.tsv:
        # ★★ 缺口 **G-15**：`--tsv` 若指向**禁止表/声明表自身**，本件会把它**整份覆盖**。
        #    实测代价（本仓，2026-09-26）：`--tsv privacy-forbidden.local.txt` 一次就把本机禁止表
        #    换成了 324 行的审计 TSV —— 本机禁止串**静默丢失**，而该表 **git 忽略**
        #    ⇒ **无版本可回退**，且本件按设计**从不记录字面**，因此**连痕迹都没有**。
        #    ⇒ 拒绝写入；⛔ 不提供 `--force`（要覆盖请自己改文件名）。
        guarded = {(skill / r).resolve() for r in TABLE_CANDIDATES + DECLARATION_TABLES}
        if Path(a.tsv).resolve() in guarded:
            print("   [FAIL] --tsv 指向**禁止表／声明表自身**（%s）⇒ ⛔ 拒绝写入。" % a.tsv)
            print("          ★ 覆盖它＝静默丢掉本机禁止串，且该表 git 忽略 ⇒ ⛔ 无法回退。")
            print("          ⇒ 换一个输出名（如 PRIVACY-AUDIT.tsv）。")
            return 2
        out = ["path\tverdict\tlabels_or_exemption\tnote"]
        out += ["%s\t%s\t%s\t%s" % r for r in rows]
        Path(a.tsv).write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
        print("   TSV ⇒ %s" % a.tsv)

    if fails:
        return 2
    if tpath is None and not a.allow_no_table:
        return 3                                    # ★ 三态：不可判，⛔ 不是通过
    return 0


if __name__ == "__main__":
    sys.exit(main())
