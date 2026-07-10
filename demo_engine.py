"""End-to-end demo of the localsearch engine (brick 5).

Proves the Definition of Done on REAL files:
  1. build an index over a directory (txt/md/pdf/docx)
  2. robustness: a CORRUPT pdf and an UNSUPPORTED file are skipped, not crash
  3. semantic (hybrid) + filename (Everything) search both work
  4. incremental: modify / add / delete files -> only changed files reindexed
  5. live watching: create/modify/delete -> index auto-updates
  6. persistence: a fresh engine loads from disk and searches without rebuilding

Run:  python demo_engine.py
"""
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import docx
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

from localsearch import SearchEngine, Config

WORK = HERE / "_demo"
CORPUS = WORK / "docs"
INDEX = WORK / "index"

FILLER = ("Background context for this document discusses the broader topic in "
          "general terms across several sentences without specific facts. ") * 4

# (filename, format, needle fact, paraphrase query)
NEEDLES = [
    ("reservoir.txt", "txt", "The Larkfield reservoir dropped to a record low water level during the long 2027 drought.",
     "when did the reservoir reach a record low"),
    ("latency.md", "md", "Our internal benchmark showed the new radix index cut tail query latency to nine milliseconds.",
     "what reduced the tail latency in the benchmark"),
    ("satellite.pdf", "pdf", "The Kestrel satellite completed its orbit insertion using a lunar gravity assist maneuver.",
     "how did the satellite enter its orbit"),
    ("solar.docx", "docx", "The Brightwater solar farm reached ninety five percent of its rated capacity in August.",
     "what capacity did the solar farm reach"),
]


def _write(path, fmt, body):
    if fmt in ("txt", "md"):
        path.write_text(body, encoding="utf-8")
    elif fmt == "pdf":
        doc = SimpleDocTemplate(str(path), pagesize=letter)
        styles = getSampleStyleSheet()
        doc.build([Paragraph(p, styles["Normal"]) for p in body.split("\n\n")])
    elif fmt == "docx":
        d = docx.Document()
        for p in body.split("\n\n"):
            d.add_paragraph(p)
        d.save(str(path))


def make_corpus():
    if WORK.exists():
        shutil.rmtree(WORK)
    CORPUS.mkdir(parents=True)
    for fname, fmt, needle, _ in NEEDLES:
        body = FILLER + "\n\n" + needle + "\n\n" + FILLER
        _write(CORPUS / fname, fmt, body)
    # robustness fixtures:
    (CORPUS / "broken.pdf").write_bytes(b"%PDF-1.4 this is not a real pdf \x00\x01 garbage")
    (CORPUS / "notes.xyz").write_text("unsupported format, should be ignored", encoding="utf-8")


def show(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def found_file(hits, name):
    return any(Path(h.path).name == name for h in hits)


def main():
    make_corpus()
    cfg = Config()
    eng = SearchEngine(INDEX, cfg)
    ok = []

    # ---------------------------------------------------------------- build
    show("1) BUILD index over the corpus directory")
    stats = eng.build([CORPUS])
    print("build stats:", stats, "| engine:", eng.stats())
    ok.append(("build produced chunks", eng.stats()["chunks"] > 0))

    # ---------------------------------------------------------- robustness
    show("2) ROBUSTNESS: corrupt pdf + unsupported file")
    print(f"broken.pdf and notes.xyz present; build reported failed={stats['failed']} "
          f"(engine did NOT crash and indexed the rest)")
    ok.append(("corrupt pdf skipped, engine alive", stats["failed"] >= 1 and eng.stats()["files"] >= 4))

    # ------------------------------------------------------- semantic search
    show("3a) SEMANTIC (hybrid) search -- paraphrase queries -> correct file+chunk")
    sem_ok = True
    for fname, fmt, needle, query in NEEDLES:
        hits = eng.search_semantic(query, top_k=5)
        top = hits[0] if hits else None
        hit_rank = next((i for i, h in enumerate(hits) if Path(h.path).name == fname), None)
        flag = "OK " if hit_rank is not None else "MISS"
        if hit_rank is None:
            sem_ok = False
        print(f"  [{flag}] q={query!r}")
        if top:
            print(f"         top: {Path(top.path).name}  score={top.score:.3f}  "
                  f"chunk@[{top.char_start}:{top.char_end}] = ...{top.chunk_text[:70].strip()}...")
    ok.append(("every needle file retrieved in top-5", sem_ok))

    # ------------------------------------------------------- filename search
    show("3b) FILENAME search via Everything (es.exe)")
    res = eng.search_filename("*.pdf", limit=5)
    if res is None:
        print("  es.exe/Everything unavailable -> filename mode gracefully disabled (fallback path)")
        ok.append(("filename search degrades gracefully", True))
    else:
        print(f"  '*.pdf' -> {len(res)} hits (e.g. {Path(res[0]).name if res else '-'})")
        ok.append(("filename search returns paths", len(res) > 0))

    # --------------------------------------------------------- incremental
    show("4) INCREMENTAL: modify + add + delete, rebuild touches only changes")
    (CORPUS / "reservoir.txt").write_text(
        FILLER + "\n\nUPDATED: the Larkfield reservoir overflowed after record spring rainfall in 2028.\n\n" + FILLER,
        encoding="utf-8")
    _write(CORPUS / "newdoc.txt", "txt",
           FILLER + "\n\nThe Aurora wind project added four hundred megawatts of capacity last quarter.\n\n" + FILLER)
    (CORPUS / "satellite.pdf").unlink()
    stats2 = eng.build([CORPUS])
    print("incremental build stats:", stats2)
    inc_ok = (stats2["skipped"] >= 2 and stats2["added"] >= 1 and stats2["updated"] >= 1
              and stats2["removed"] >= 1)
    ok.append(("incremental: skipped-unchanged + added + updated + removed", inc_ok))
    # verify content changes took effect
    new_hit = found_file(eng.search_semantic("how much capacity did the wind project add", 5), "newdoc.txt")
    del_gone = not found_file(eng.search_semantic("satellite orbit insertion gravity assist", 5), "satellite.pdf")
    print(f"  new file findable: {new_hit} | deleted file gone from results: {del_gone}")
    ok.append(("incremental content reflected in search", new_hit and del_gone))

    # ------------------------------------------------------------- watching
    show("5) LIVE WATCHING: create a file -> auto-indexed")
    eng.start_watching([CORPUS])
    try:
        _write(CORPUS / "watched.txt", "txt",
               FILLER + "\n\nThe Meridian desalination plant began supplying fresh water to the coastal city in March.\n\n" + FILLER)
        time.sleep(cfg.watch_debounce_s + 2.0)   # debounce + parse+embed
        watch_ok = found_file(eng.search_semantic("which plant started providing drinking water", 5), "watched.txt")
        print(f"  created watched.txt -> findable via semantic search: {watch_ok}")
        ok.append(("watcher auto-indexed a new file", watch_ok))
    finally:
        eng.stop_watching()

    # ----------------------------------------------------------- persistence
    show("6) PERSISTENCE: fresh engine loads from disk, searches without rebuild")
    eng.save()
    eng2 = SearchEngine(INDEX, cfg)              # constructs from disk
    reload_stats = eng2.stats()
    print("reloaded engine:", reload_stats)
    reload_hit = found_file(eng2.search_semantic("when did the reservoir overflow", 5), "reservoir.txt")
    # a re-build should now skip everything (nothing changed)
    nochange = eng2.build([CORPUS])
    print("rebuild after reload (should be all skipped):", nochange)
    ok.append(("reload from disk + search works", reload_stats["chunks"] > 0 and reload_hit))
    ok.append(("incremental skips all when nothing changed",
               nochange["added"] == 0 and nochange["updated"] == 0 and nochange["skipped"] >= 4))

    # ------------------------------------------------------------- verdict
    show("RESULT")
    for name, passed in ok:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    allpass = all(p for _, p in ok)
    print("\n" + ("ALL CHECKS PASSED -- engine runs end-to-end and stably."
                  if allpass else "SOME CHECKS FAILED -- see above."))
    eng2.close()
    shutil.rmtree(WORK, ignore_errors=True)
    return 0 if allpass else 1


if __name__ == "__main__":
    sys.exit(main())
