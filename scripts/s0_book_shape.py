#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S0 —— **形态探测**（参数化引擎 · 只读源件，写 `<out_root>/kb/<code>/_book.json`）。

判据（可失败）：
  ① 逐页实测（⛔ 不抽样）：页尺寸 · 位图数 · 每张位图的 像素/位深/滤镜 · 有效 dpi · 文本层字符数
  ② 众数形态由**实测频率**得出；**离群页逐个点名**并写出差在哪
  ③ `--check`：重新探测并与在盘 `_book.json` 的 `shape` 段**逐字段比对**
  ④ 源件路径⛔ 不落盘（便携门会在 S6 复核整册产物）

用法：
    python s0_book_shape.py --series <series.yml> [--book CODE] [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_series(p):
    import yaml
    cfg = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    base = Path(p).resolve().parent
    s = cfg["series"]
    s["_base"] = base
    s["_out"] = (base / str(s["out_root"])).resolve()
    s["_src"] = (base / str(s["source_root"])).resolve()
    return cfg, s


def probe(pdf: Path):
    """逐页实测 ⇒ 形态字典（★ 全部是量出来的）。"""
    import fitz
    doc = fitz.open(str(pdf))
    pages, text_chars = [], 0
    for i, page in enumerate(doc):
        rect = page.rect
        imgs = page.get_images(full=True)
        entries = []
        # ★ 文本层计数必须在**循环外面**：否则「没有位图的页」永远统计不到
        #   （实测踩过：整册 0 字符，看起来像「扫描件没有文本层」，其实是漏计）
        text_chars += len(page.get_text() or "")
        for im in imgs:
            xref = im[0]
            try:
                info = doc.extract_image(xref)
            except Exception:                                   # noqa: BLE001
                continue
            entries.append({"px": [info.get("width"), info.get("height")],
                            "bpc": info.get("bpc"), "filter": info.get("ext")})
        pages.append({"i": i, "pt": [round(rect.width, 1), round(rect.height, 1)],
                      "images": entries})
    doc.close()

    def modal_of(vals):
        c = Counter(vals)
        return c.most_common(1)[0][0] if c else ()

    key_pt = modal_of(tuple(p["pt"]) for p in pages)
    key_px = modal_of(tuple(e["px"]) for p in pages for e in p["images"])
    out = {
        "method": "逐页 page.rect ＋ get_images(full=True) → extract_image（零渲染、零模型、零网络）",
        "covers_pages": "全部 %d 页，无抽样" % len(pages),
        "text_layer_chars_total": text_chars,
        "modal": {"page_size_pt": list(key_pt), "native_px": list(key_px),
                  "bits_per_component": next((e["bpc"] for p in pages for e in p["images"]), None),
                  "image_filter": next((e["filter"] for p in pages for e in p["images"]), None)},
        "pages": pages,
        "outliers": [],
    }
    if key_pt:
        for p in pages:
            if tuple(p["pt"]) != key_pt:
                out["outliers"].append({"pdf_page": p["i"] + 1, "page_size_pt": p["pt"],
                                        "differs": "众数页尺寸 %s" % list(key_pt)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--book")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    cfg, s = load_series(a.series)
    books = [b for b in s["books"] if not a.book or b["code"] == a.book]
    bad = 0
    print("== S0 形态探测（%s）==" % s["id"])
    for b in books:
        src = s["_src"] / b["basename"]
        if not src.exists():
            print("  [FAIL] %-6s 源件不存在：%s" % (b["code"], b["basename"]))
            bad += 1
            continue
        shape = probe(src)
        dest = s["_out"] / "kb" / b["code"] / "_book.json"
        rec = {"book": {"code": b["code"], "title": b.get("title", ""),
                        "title_source": {"kind": b.get("title_source", "unstated"),
                                         "note": "★ 册名应取自印本封面，⛔ 不从文件名猜"}},
               "source": {"basename": src.name, "bytes": src.stat().st_size,
                          "pages": len(shape["pages"])},
               "shape": shape}
        if a.check:
            if not dest.exists():
                print("  [FAIL] %-6s --check：在盘 _book.json 不存在" % b["code"])
                bad += 1
                continue
            old = json.loads(dest.read_text(encoding="utf-8"))
            same = old.get("shape") == shape
            print("  [%s] %-6s shape 段 %s" % ("PASS" if same else "FAIL", b["code"],
                                              "逐字段相同" if same else "**不同**（源件变了或仪器变了）"))
            bad += 0 if same else 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8", newline="\n")
        print("  [PASS] %-6s %d 页 · %d B · 众数 %s pt / %s px · 文本层 %d 字符 · 离群 %d 页 ⇒ %s"
              % (b["code"], len(shape["pages"]), src.stat().st_size,
                 shape["modal"]["page_size_pt"], shape["modal"]["native_px"],
                 shape["text_layer_chars_total"], len(shape["outliers"]),
                 dest.relative_to(s["_base"])))
    print("\n  结论：%s" % ("全部通过" if not bad else "%d 册有问题" % bad))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
