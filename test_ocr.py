# -*- coding: utf-8 -*-
"""End-to-end OCR test through the real engine: build a deep index over a folder
of IMAGES (no text files) and find them by meaning. Also checks OCR-off skips
images, the toggle plumbing, and CJK space-collapse."""
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from localsearch import ocr, parser
from localsearch.config import Config
from localsearch.engine import SearchEngine

PASS = FAIL = 0
def check(name, ok, detail=""):
    global PASS, FAIL
    PASS += ok; FAIL += (not ok)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (f"  ::  {detail}" if detail else ""))


def _font(name, size):
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()


def make_png(path, lines):
    img = Image.new("RGB", (960, 90 + 70 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for text, cjk in lines:
        d.text((36, y), text, fill="black", font=_font("msyh.ttc" if cjk else "arial.ttf", 34))
        y += 70
    img.save(path)


def main():
    # 0) OCR must be available on this machine (available() forces the probe;
    # status() stays lazy/None until OCR is actually used)
    check("status lazy before probe", ocr.status()["available"] is None)
    avail = ocr.available()
    st = ocr.status()
    print("OCR status:", st)
    check("Windows OCR available", avail, st.get("error") or st.get("language"))
    if not avail:
        print("\n!!! OCR not available; cannot run the end-to-end test")
        sys.exit(1)

    # 1) collapse of CJK inter-glyph spaces
    check("cjk collapse joins glyphs", ocr._collapse_cjk("公 司 差 旅") == "公司差旅")
    check("cjk collapse keeps latin space", "hello world" in ocr._collapse_cjk("hello world 你 好"))

    docs = Path(tempfile.mkdtemp(prefix="ocr_imgs_"))
    idx = Path(tempfile.mkdtemp(prefix="ocr_idx_"))
    try:
        make_png(docs / "screenshot_finance.png",
                 [("Quarterly revenue grew twenty percent", False),
                  ("annual shareholder dividend vote agenda", False)])
        make_png(docs / "scan_policy.png",
                 [("公司差旅报销制度说明文件", True),
                  ("住宿费每天上限五百元餐费实报实销", True)])
        make_png(docs / "diagram_reservoir.png",
                 [("The mountain reservoir hit a record low this summer", False)])

        cfg = Config()
        eng = SearchEngine(str(idx), cfg)
        eng.warmup()

        # 2) OCR OFF (default): images are not even walked
        check("default OCR off", eng.ocr_status()["enabled"] is False)
        check("png unsupported while off", not parser.is_supported(str(docs / "a.png")))
        eng.build([str(docs)])
        check("no files indexed while OCR off", eng.stats()["files"] == 0, eng.stats())

        # 3) turn OCR ON, rescan
        stt = eng.set_ocr(True)
        check("set_ocr(True) enables", stt["enabled"] is True, stt)
        check("png supported while on", parser.is_supported(str(docs / "a.png")))
        check(".png in current_exts", ".png" in parser.current_exts())
        eng.build([str(docs)])
        check("all 3 images indexed", eng.stats()["files"] == 3, eng.stats())

        # 4) find images BY MEANING (words not in any filename)
        r = eng.search_semantic("company travel expense reimbursement rules", top_k=5)
        top = r[0].path if r else ""
        check("EN query -> Chinese scan (cross-lang OCR)", "scan_policy" in top,
              top or "no hits")

        r = eng.search_semantic("水库水位创新低", top_k=5)
        check("中文 query -> English reservoir image", any("reservoir" in h.path for h in r),
              (r[0].path if r else "no hits"))

        r = eng.search_semantic("stock holders payout meeting", top_k=5)
        check("paraphrase -> finance screenshot", any("finance" in h.path for h in r),
              (r[0].path if r else "no hits"))

        # 5) the extracted Chinese is clean (space-collapsed), so it is searchable
        r = eng.search_semantic("报销制度", top_k=5)
        check("collapsed Chinese searchable", any("scan_policy" in h.path for h in r),
              (r[0].path if r else "no hits"))

        # 6) turn OCR back OFF + rescan -> images purged
        eng.set_ocr(False)
        eng.build([str(docs)])
        check("OCR off + rescan purges images", eng.stats()["files"] == 0, eng.stats())

        eng.close()
    finally:
        shutil.rmtree(docs, ignore_errors=True)
        shutil.rmtree(idx, ignore_errors=True)

    print(f"\n==== {PASS} PASS / {FAIL} FAIL ====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
