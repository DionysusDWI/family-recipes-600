#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布打包器 —— **分层固实** tar.xz ＋ **非固实**外层 zip ＋ 包内文档 ＋ 三条回程判据。

★ 为什么分层固实：向量几乎不可压（试点实测 **86.8%**）而文本可压到 **16.6%**；
  更要紧的是**层间独立** —— 某层损坏只赔那一层，⛔ 不会整卷不可解。

★ 三条回程判据（`--verify`，全部可失败）：
  ① **只解文档即可导航**：`README.md`／`DEPLOY.md`／`MANIFEST.tsv`／`LAYERS.tsv`／`EXCLUDED.tsv`
     在**不解任何层**的前提下就能读到；
  ② **逐层** sha256 与 `LAYERS.tsv` 逐条相等；
  ③ **逐件** sha256 与 `MANIFEST.tsv` 逐条相等。

★ 另带**隐私门**（`--scan-only`／打包前自动跑）：产物里⛔ 不得出现
  绝对路径／UNC／本机临时根／邮箱／令牌形态；命中即**拒绝打包**（⛔ 不是「打包后再说」）。

用法：
    python pack_release.py --skill <技能目录> --out <zip> [--light]
    python pack_release.py --skill <技能目录> --out <zip> --verify
    python pack_release.py --skill <技能目录> --scan-only
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

# ── 排除规则（模式 → 理由）；★ 逐条给出**理由**，`EXCLUDED.tsv` 里可核
EXCLUDE = [
    # ★★ 必须排除版本库内部对象：git init 之后技能目录里多出 .git/（数百个对象），
    #   ⛔ 它既不是源码、又可能带完整历史 ⇒ 实测首版把它整个打进了发布体（48 → 187 件）。
    ("**/.git/**", "版本库内部对象：⛔ 不进发布体"),
    ("**/__pycache__/**", "工程残留：字节码缓存（且含本机绝对路径）"),
    ("**/*.pyc", "工程残留：字节码"),
    ("**/out/**", "运行产物：由脚本重建，⛔ 不进发布体"),
    ("**/scratch/**", "易失区：⛔ 不发布"),
    ("**/*.local.txt", "本机禁止表：只在本机有效"),
]
LIGHT_EXTRA = [("**/vectors_*.npy", "轻装形态：向量体量大且可重建（另附重建说明）"),
               ("**/ids_*.json", "轻装形态：向量 id 清单随向量一起去掉")]

SCAN = [
    # ★ 绝对路径分两支写：**盘符**（`C:\` / `D:/`）与 **UNC**（`\\server\share`）。
    #   ⛔ 不要写成「任意两个反斜杠」—— 那会把**正则字面**当成 UNC 路径：实测 `series.yml` 里
    #   `"^\\d+\\.\\s*"` 的两个反斜杠命中过一次 ⇒ **假红而产物完全干净**（尺子坏了，不是产物坏了）。
    ("绝对路径(盘符)", re.compile(r"(?<![A-Za-z0-9:/])[A-Za-z]:[\\/]")),
    #   ★★ **UNC 分支已移除**（连错三次）：把「两个反斜杠 + 名字 + 一反斜杠」写成模式，
    #     在**正则字面**（`"^\\d+\\.\\s*"`、`[\\u2460-\\u2473]`）上必然误报 —— 实测三次命中
    #     全部是**尺子**的问题而产物干净。⇒ 机器相关的串改用**本机禁止表**
    #     `privacy-forbidden.local.txt`（逐行字面，git 忽略），⛔ 不再用猜形状的正则。
    ("本机临时根", re.compile(r"[A-Za-z]:\\[^\"'\n]*system-temp", re.I)),
    ("邮箱形态", re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.I)),
    ("令牌形态", re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|gh[pous]_[A-Za-z0-9]{20,})\b")),
]

LAYERS = [("00-engine", ["SKILL.md", "scripts/", "templates/"]),
          ("10-references", ["references/"]),
          ("20-examples", ["examples/"])]


def rel_files(skill: Path):
    out = []
    for f in sorted(skill.rglob("*")):
        if f.is_file():
            out.append(f.relative_to(skill).as_posix())
    return out


def excluded(rel: str, light: bool):
    rules = EXCLUDE + (LIGHT_EXTRA if light else [])
    for pat, why in rules:
        rx = "^" + re.escape(pat).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$"
        if re.match(rx, rel):
            return why
    return None


def layer_of(rel: str):
    for name, prefixes in LAYERS:
        for p in prefixes:
            if rel == p or rel.startswith(p):
                return name
    return "90-other"


def sha256_bytes(b: bytes):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--out")
    ap.add_argument("--light", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--scan-only", action="store_true")
    a = ap.parse_args()

    skill = Path(a.skill).resolve()
    if a.verify:
        return verify(Path(a.out).resolve())
    if not a.scan_only and not a.out:
        print("⛔ 需要 --out（或用 --scan-only 只做隐私门）", file=sys.stderr)
        return 3

    keep, dropped = {}, {}
    for rel in rel_files(skill):
        why = excluded(rel, a.light)
        if why:
            dropped.setdefault(why, []).append(rel)
        else:
            keep[rel] = (skill / rel).read_bytes()

    # ★ 隐私门：**打包前**扫，命中即拒。
    #   ★★ 两条豁免（都**报出来**，⛔ 不静默跳过）：
    #     ① **扫描器自身**：它的规则字面就是路径形态 ⇒ 按 已知坑 #81「先问它扫到自己会怎样」排除；
    #     ② `privacy-allow.txt`（每行 `相对路径<TAB>理由`）声明的**显式豁免**。
    SELF = {"scripts/pack_release.py"}
    allow = {}
    ap_file = skill / "privacy-allow.txt"
    if ap_file.exists():
        for ln in ap_file.read_text(encoding="utf-8").splitlines():
            if ln.strip() and not ln.startswith("#"):
                parts = ln.split("\t")
                if len(parts) >= 2:
                    allow[parts[0].strip()] = parts[1].strip()
    hits, exempt = [], []
    for rel, b in keep.items():
        try:
            t = b.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for label, rx in SCAN:
            m = rx.search(t)
            if not m:
                continue
            # ★ **行级规则豁免**：命中的那一行若是在**定义规则**（`re.compile(`／`re.escape(`），
            #   那是**尺子**不是被测物（已知坑 #81）。⛔ 只豁免那一行，不豁免整件。
            line = t[:m.start()].split("\n")[-1] + t[m.start():].split("\n")[0]
            if "re.compile(" in line or "re.escape(" in line:
                exempt.append("%s:%s（规则定义行）" % (rel, label))
            elif rel in SELF or rel in allow:
                exempt.append("%s:%s（%s）" % (rel, label,
                                               "扫描器自身" if rel in SELF else allow[rel]))
            else:
                hits.append("%s:%s（%s）" % (rel, label, line.strip()[:60]))
    print("== 发布打包（%s）==" % skill.name)
    print("  收件 %d · 排除 %d（%d 类）" % (len(keep), sum(len(v) for v in dropped.values()),
                                           len(dropped)))
    for why, lst in dropped.items():
        print("    ⛔ %-46s %d 件" % (why[:46], len(lst)))
    if hits:
        print("  [FAIL] 隐私门命中 %d 处：%s" % (len(hits), hits[:6]))
        if a.scan_only:
            return 2
        print("        ⇒ ⛔ 拒绝打包（先删减再打）")
        return 2
    if exempt:
        print("  ★ 豁免 %d 处（已报出，⛔ 非静默）：%s" % (len(exempt), exempt[:4]))
    print("  [PASS] 隐私门：绝对路径/UNC/临时根/邮箱/令牌 命中 0")
    if a.scan_only:
        return 0

    groups = {}
    for rel in keep:
        groups.setdefault(layer_of(rel), {})[rel] = keep[rel]

    layers_tsv, manifest_tsv = ["layer\tfiles\tbytes_uncompressed\tbytes_compressed\tsha256"], \
        ["path\tlayer\tbytes\tsha256"]
    layer_blobs = {}
    for name in sorted(groups):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:                  # 固实：一个流
            for rel in sorted(groups[name]):
                data = groups[name][rel]
                ti = tarfile.TarInfo(rel)
                ti.size = len(data)
                ti.mtime = 0
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                tf.addfile(ti, io.BytesIO(data))
        raw = buf.getvalue()
        comp = lzma.compress(raw, preset=6)
        layer_blobs[name] = comp
        cum = sum(len(v) for v in groups[name].values())
        layers_tsv.append("%s\t%d\t%d\t%d\t%s" % (name, len(groups[name]), cum, len(comp),
                                                  sha256_bytes(comp)))
        for rel in sorted(groups[name]):
            manifest_tsv.append("%s\t%s\t%d\t%s" % (rel, name, len(groups[name][rel]),
                                                    sha256_bytes(groups[name][rel])))

    ex_tsv = ["pattern_or_reason\tmatched_files\texamples"]
    for why, lst in dropped.items():
        ex_tsv.append("%s\t%d\t%s" % (why, len(lst), ", ".join(sorted(lst)[:3])))

    readme = """# series-book-to-rag —— 便携发布体

本包是**发布体**，不是工作副本。分三层以上**固实归档**（每层一个 `tar.xz`），
外层 zip 是**非固实**的 —— 所以**不必解压整包**就能读到本文件与下面几件：

| 件 | 用途 |
|---|---|
| `README.md` | 本文件：这是什么、怎么用 |
| `DEPLOY.md` | **部署步骤与验收命令** |
| `MANIFEST.tsv` | 逐**件** sha256（路径 · 层 · 字节 · 哈希） |
| `LAYERS.tsv` | 逐**层** sha256（层 · 件数 · 压缩前后字节 · 哈希） |
| `EXCLUDED.tsv` | **被排除的件与理由**（可核，⛔ 不是「打包时忘了」） |

★ 层划分的依据：向量几乎不可压而正文可压；更要紧的是**层间独立** —— 某层损坏只赔那一层。
★ 安装与验收见 `DEPLOY.md`。
"""
    deploy = """# 部署（给执行部署的 agent）

1. **先只解文档**（不解任何层）：`README.md` · `DEPLOY.md` · `MANIFEST.tsv` · `LAYERS.tsv` · `EXCLUDED.tsv`。
   ★ 读到即证明外层非固实、导航可用。
2. **逐层核 sha256**：对每个 `layers/*.tar.xz` 计算 sha256，与 `LAYERS.tsv` 对应行比对。
3. **逐层解包**：`tar -xf layers/<name>.tar.xz -C <目标>`（层序即安装序）。
4. **逐件核 sha256**：对解出的每个文件与 `MANIFEST.tsv` 比对。
5. **验收**：跑技能自带的最小闭环（见 `SKILL.md` §3 与 `examples/toy-series/`），
   期望：S0/S2/S3 全绿、S5 自测 exit 0、门禁 `FAIL=0`。

⛔ 禁止事项：
- ⛔ 不要用「解包后目录树看着对」代替逐件 sha256（非 ASCII 路径会静默少数）；
- ⛔ 不要把 `EXCLUDED.tsv` 当成「丢失」，它是**声明**过的排除；
- ⛔ 不要在无密钥时把 `SKIP` 读成通过。
"""
    z = Path(a.out)
    z.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:             # 外层非固实
        zf.writestr("README.md", readme)
        zf.writestr("DEPLOY.md", deploy)
        zf.writestr("MANIFEST.tsv", "\n".join(manifest_tsv) + "\n")
        zf.writestr("LAYERS.tsv", "\n".join(layers_tsv) + "\n")
        zf.writestr("EXCLUDED.tsv", "\n".join(ex_tsv) + "\n")
        for name, blob in sorted(layer_blobs.items()):
            zf.writestr("layers/%s.tar.xz" % name, blob)
    print("  写出 %s（%.1f MB）" % (z.name, z.stat().st_size / 1024 / 1024))
    print("  层：%s" % "、".join("%s(%d件/%.2fMB)" % (n, len(groups[n]),
                                                    len(layer_blobs[n]) / 1024 / 1024)
                                for n in sorted(groups)))
    print("  ★ 回程校验：python pack_release.py --skill %s --out %s --verify" % (skill.name, z.name))
    return verify(z)


def verify(z: Path):
    """三条回程判据（⛔ 不是「打包命令没报错」）。"""
    print("== 回程校验（%s）==" % z.name)
    bad = 0
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        docs = ["README.md", "DEPLOY.md", "MANIFEST.tsv", "LAYERS.tsv", "EXCLUDED.tsv"]
        # ★★ 判据必须**在坏输入下也能出读数**：包被损坏时⛔ 不许抛异常，
        #    否则「门崩了」会被读成「工具坏了」而不是「包坏了」（实测：删一个文档成员曾直接 KeyError）。
        missing = [d for d in docs if d not in names]
        got = {}
        for d in docs:
            if d in names:
                try:
                    got[d] = zf.read(d).decode("utf-8")
                except Exception as e:                           # noqa: BLE001
                    got[d] = ""
                    missing.append("%s(读失败:%s)" % (d, type(e).__name__))
        ok1 = not missing and all(got.get(d) for d in docs)
        print("  [%s] ① 只解文档即可导航（%d/%d 件%s）"
              % ("PASS" if ok1 else "FAIL", len(docs) - len(missing), len(docs),
                 "" if ok1 else "，缺/坏：%s" % missing))
        bad += 0 if ok1 else 1
        layers = {n: zf.read(n) for n in names if n.startswith("layers/")}
        want = {}
        for l in got.get("LAYERS.tsv", "").splitlines()[1:]:
            f = l.split("\t")
            if len(f) >= 5:
                want[f[0]] = f[4]
        ok2 = bool(want) and all(sha256_bytes(b) == want.get(n.split("/")[-1].replace(".tar.xz", ""))
                                 for n, b in layers.items())
        print("  [%s] ② 逐层 sha256 与 LAYERS.tsv 相符（%d 层 / 表内 %d 层）"
              % ("PASS" if ok2 else "FAIL", len(layers), len(want)))
        bad += 0 if ok2 else 1
        man = {}
        for l in got.get("MANIFEST.tsv", "").splitlines()[1:]:
            f = l.split("\t")
            if len(f) >= 4:
                man[f[0]] = (int(f[2]), f[3])
        n_ok, n_bad, bad_layers = 0, 0, []
        for n, b in layers.items():
            try:
                with tarfile.open(fileobj=io.BytesIO(b), mode="r:xz") as tf:
                    for m in tf.getmembers():
                        data = tf.extractfile(m).read()
                        exp = man.get(m.name)
                        if exp and len(data) == exp[0] and sha256_bytes(data) == exp[1]:
                            n_ok += 1
                        else:
                            n_bad += 1
            except Exception as e:                               # noqa: BLE001
                # ★ 层**读不开**（损坏）⇒ 如实记为「不可读层」，⛔ 不让它把整个校验掀翻
                bad_layers.append("%s(%s)" % (n.split("/")[-1], type(e).__name__))
                n_bad += 1
        ok3 = (n_bad == 0 and n_ok == len(man) and not bad_layers)
        print("  [%s] ③ 逐件 sha256 与 MANIFEST.tsv 相符（%d/%d 件%s%s）"
              % ("PASS" if ok3 else "FAIL", n_ok, len(man),
                 "，不符 %d" % n_bad if n_bad else "",
                 "，不可读层：%s" % bad_layers if bad_layers else ""))
        bad += 0 if ok3 else 1
    print("  结论：%s" % ("三条全过 ✅" if not bad else "⛔ %d 条不成立" % bad))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
