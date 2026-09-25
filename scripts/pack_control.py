#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布打包器的**反控** —— 三条回程判据必须各自能红（技能 §4.3「门必须能红」）。

★ 判据：**植入 → 变红 → 还原 → 回绿**，四步都要有读数。
  A. 删掉一个文档成员（`README.md`）        ⇒ 判据① 红（只解文档不可导航）
  B. 改一个层字节（`layers/*.tar.xz` 一位） ⇒ 判据② 红（逐层 sha256 不符）
  C. 从层里删一个件再重压该层               ⇒ 判据③ 红（逐件 sha256 少一件）

用法：python scripts/pack_control.py --skill <技能目录>
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
HERE = Path(__file__).resolve().parent


def build(skill: Path, zip_path: Path):
    r = subprocess.run([sys.executable, str(HERE / "pack_release.py"), "--skill", str(skill),
                        "--out", str(zip_path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode


def verify(zip_path: Path):
    r = subprocess.run([sys.executable, str(HERE / "pack_release.py"), "--skill", "x",
                        "--out", str(zip_path), "--verify"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    tails = [l.strip() for l in out.splitlines() if l.strip().startswith("结论")]
    return r.returncode, (tails[-1] if tails else out.strip()[-70:])


ap = argparse.ArgumentParser()
ap.add_argument("--skill", required=True)
a = ap.parse_args()
skill = Path(a.skill).resolve()
tmp = Path(tempfile.mkdtemp(prefix="packctl-"))
z = tmp / "pkg.zip"
ok_all = True

try:
    print("基线：")
    build(skill, z)
    rc, tail = verify(z)
    print("  [%s] 基线（应绿）⇒ exit=%d %s" % ("PASS" if rc == 0 else "FAIL", rc, tail))
    ok_all &= (rc == 0)

    # A 删文档成员
    shutil.copy2(z, tmp / "a.zip")
    with zipfile.ZipFile(z, "r") as zf:
        items = [(n, zf.read(n)) for n in zf.namelist() if n != "README.md"]
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for n, b in items:
            zf.writestr(n, b)
    rc, tail = verify(z)
    print("  [%s] A 删 README ⇒ exit=%d %s" % ("PASS" if rc == 2 else "FAIL", rc, tail))
    ok_all &= (rc == 2)

    # B 改层字节
    shutil.copy2(tmp / "a.zip", z)
    with zipfile.ZipFile(z, "r") as zf:
        items = [(n, zf.read(n)) for n in zf.namelist()]
    items = [(n, (b[:-1] + bytes([b[-1] ^ 0xFF])) if n.startswith("layers/") else b)
             for n, b in items]
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for n, b in items:
            zf.writestr(n, b)
    rc, tail = verify(z)
    print("  [%s] B 改层字节 ⇒ exit=%d %s" % ("PASS" if rc == 2 else "FAIL", rc, tail))
    ok_all &= (rc == 2)

    # C 从层里删一个件再重压
    shutil.copy2(tmp / "a.zip", z)
    with zipfile.ZipFile(z, "r") as zf:
        items = [(n, zf.read(n)) for n in zf.namelist()]
    out_items = []
    for n, b in items:
        if n.startswith("layers/") and "00-engine" in n:
            with tarfile.open(fileobj=io.BytesIO(b), mode="r:xz") as tf:
                members = [(m, tf.extractfile(m).read()) for m in tf.getmembers()][:-1]  # 去掉最后一个
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tw:
                for m, data in members:
                    tw.addfile(m, io.BytesIO(data))
            import lzma
            b = lzma.compress(buf.getvalue(), preset=6)
        out_items.append((n, b))
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for n, b in out_items:
            zf.writestr(n, b)
    rc, tail = verify(z)
    print("  [%s] C 层内少一件 ⇒ exit=%d %s" % ("PASS" if rc == 2 else "FAIL", rc, tail))
    ok_all &= (rc == 2)

    print("\n反控结论：%s" % ("PASS（三条判据各自能红）" if ok_all else "FAIL"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if ok_all else 2)
