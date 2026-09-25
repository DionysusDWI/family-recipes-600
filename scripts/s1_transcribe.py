#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S1 —— **逐页转写**（视觉模型 → `_pages/pNNNN.md`）＋ 计划模式（⛔ 计划模式不发请求）。

★ 三条纪律（试点教训）：
  ① **一页一个文件**、已有即跳过（幂等）；页索引 0 起算，与源件页只差**固定偏移**（写进 `_book.json`）。
  ② **提示词版本落盘且追加**（`_pages/_prompt-version.txt`）—— 一册里出现两个版本必须能被查出来。
  ③ **逐页日志**（`_vision-log.tsv`）：页号 · 秒 · token · 状态；⛔ 0 FAIL 才谈得上「转写完成」。

用法：
    python s1_transcribe.py --series <series.yml> --plan                # 只列计划，⛔ 不发请求
    python s1_transcribe.py --series <series.yml> --run --book B01 --max-pages 1
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _keys import load_key                                       # noqa: E402

URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen3.8-omni-flash"
PROMPT_VERSION = "v1"
PROMPT = """你是一个严格的中文印刷品版面转写器。请逐字转写这一页的全部内容，⛔ 不改写、不润色、不省略。

输出约定（**标记必须独占一行**）：
- 一条记录（菜/条目）开始时写：`@@RECIPE_START <编号> <名称>`（编号与名称按印本原样）
- 承接上一页的记录（本页是它的续页）时，第一行写：`@@RECIPE_CONT`
- 分节标题写：`@@SECTION <节名>`（如 原 料／主 料／调 料／制 法／注 释，按印本原样）
- 步骤写：`@@STEP <步号>`，正文另起一行（若印本步号与正文同行，也照此行式输出）
- 页脚（页码）写：`@@FOOTER <页码>`
- 图版与图注写：`@@FIGURE` 与 `@@CAPTION <图注原文>`

⛔ 读不出的字写 `⟦?⟧`（**不要猜**）；⛔ 不要输出任何解释、前后缀或 Markdown 代码块。"""


def render(pdf: Path, page: int, dpi: int, out_png: Path):
    import fitz
    doc = fitz.open(str(pdf))
    pix = doc[page].get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
    out_png.write_bytes(pix.tobytes("png"))
    doc.close()
    return out_png


def transcribe(png: Path, model, key, retries=3):
    import urllib.request
    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    body = {"model": model, "messages": [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": [{"type": "image_url",
                                      "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    data = json.dumps(body).encode("utf-8")
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(URL, data=data, headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.loads(r.read().decode("utf-8"))
            txt = j["choices"][0]["message"]["content"]
            usage = j.get("usage", {}) or {}
            return txt, usage
        except Exception as e:                                   # noqa: BLE001
            last = "%s %s" % (type(e).__name__, str(e)[:120])
            time.sleep(2)
    raise RuntimeError(last or "unknown")


def plan(book, pdf, pages_dir, dpi, model):
    import fitz
    doc = fitz.open(str(pdf))
    n = doc.page_count
    doc.close()
    todo = [i for i in range(n) if not (pages_dir / ("p%04d.md" % i)).exists()]
    est_img = 1262                                               # ★ 实测量级：单页图像 token
    print("  %-6s 源件 %d 页 · 待转写 %d 页 · dpi %d · 模型 %s · 提示词 %s"
          % (book, n, len(todo), dpi, model, PROMPT_VERSION))
    if todo:
        print("         待转写页：%s%s"
              % (", ".join("p%04d" % i for i in todo[:8]), " …" if len(todo) > 8 else ""))
        print("         预估 token ≈ %d（图像 %d/页 ＋ 提示词与输出）"
              % (len(todo) * (est_img + 250), est_img))
    return todo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--book")
    ap.add_argument("--max-pages", type=int, default=0, help="本次最多转写几页（0 ＝ 不限）")
    a = ap.parse_args()
    if not (a.plan or a.run):
        ap.error("要么 --plan（只列计划），要么 --run")

    import yaml
    p = Path(a.series).resolve()
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    base = p.parent
    s = cfg["series"]
    out = (base / str(s["out_root"])).resolve()
    src = (base / str(s["source_root"])).resolve()
    dpi = int(s.get("render_dpi", 300))
    s1 = cfg.get("s1", {}) or {}
    model = s1.get("model", DEFAULT_MODEL)
    kcfg = dict(cfg.get("keys", {}) or {})
    kcfg["env_var"] = s1.get("env_var", "DASHSCOPE_API_KEY")
    key, src_note = load_key(kcfg, base)

    books = [b for b in s["books"] if not a.book or b["code"] == a.book]
    print("== S1 逐页转写（%s）==\n   输出根 %s\n   密钥来源 %s" % (s["id"], out / "kb", src_note))

    if a.plan:
        total = 0
        for b in books:
            pdf = src / b["basename"]
            if not pdf.exists():
                print("  [SKIP] %-6s 源件不存在：%s" % (b["code"], b["basename"]))
                continue
            total += len(plan(b["code"], pdf, out / "kb" / b["code"] / "_pages", dpi, model))
        print("\n  计划完成：待转写 %d 页 · ⛔ 本次未发任何请求" % total)
        return 0

    if not key:
        print("  [SKIP] 无键 ⇒ ⛔ 不可判（**不是通过**）：%s" % src_note)
        return 3
    import shutil
    import tempfile
    done = 0
    for b in books:
        pdf = src / b["basename"]
        if not pdf.exists():
            continue
        pages_dir = out / "kb" / b["code"] / "_pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        log = pages_dir / "_vision-log.tsv"
        if not log.exists():
            log.write_text("page\tseconds\ttokens\tstatus\n", encoding="utf-8", newline="\n")
        (pages_dir / "_prompt-version.txt").open("a", encoding="utf-8", newline="\n").write(
            "%s\t%s\ttodo=%d\n" % (PROMPT_VERSION, time.strftime("%Y-%m-%d %H:%M:%S"),
                                   len(plan(b["code"], pdf, pages_dir, dpi, model))))
        todo = [i for i in range(_page_count(pdf)) if not (pages_dir / ("p%04d.md" % i)).exists()]
        tmp = Path(tempfile.mkdtemp(prefix="s1-"))
        try:
            for i in todo:
                if a.max_pages and done >= a.max_pages:
                    break
                t0 = time.time()
                png = render(pdf, i, dpi, tmp / ("p%04d.png" % i))
                try:
                    txt, usage = transcribe(png, model, key)
                    (pages_dir / ("p%04d.md" % i)).write_text(txt.strip() + "\n",
                                                              encoding="utf-8", newline="\n")
                    st = "ok"
                except Exception as e:                           # noqa: BLE001
                    txt, usage, st = "", {}, "FAIL:%s" % str(e)[:60]
                dt = time.time() - t0
                done += 1
                with log.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write("%d\t%.1f\t%s\t%s\n" % (i, dt, usage.get("total_tokens", ""), st))
                print("  [%s] %-6s p%04d %.1fs" % (st, b["code"], i, dt))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\n  本次转写 %d 页" % done)
    return 0


def _page_count(pdf: Path):
    import fitz
    doc = fitz.open(str(pdf))
    n = doc.page_count
    doc.close()
    return n


if __name__ == "__main__":
    sys.exit(main())
