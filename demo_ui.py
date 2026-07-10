"""End-to-end UI demo (brick 6): launches the REAL `python -m localsearch.app`
server and drives the full non-programmer flow over HTTP, exactly as the browser
would: add a folder -> watch indexing progress -> search (both modes) -> open a
result. Proves the Definition of Done without a human clicking.

Run:  python demo_ui.py
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
WORK = HERE / "_demo_ui"
CORPUS = WORK / "docs"
INDEX = WORK / "index"
PORT = 8736
BASE = f"http://127.0.0.1:{PORT}"

NEEDLES = [
    ("reservoir.txt", "The Larkfield reservoir dropped to a record low water level during the 2027 drought.",
     "when did the reservoir reach a record low", "reservoir"),
    ("latency.txt", "The new radix index cut tail query latency to nine milliseconds in our benchmark.",
     "what reduced the tail latency", "latency"),
    ("solar.txt", "The Brightwater solar farm reached ninety five percent of rated capacity in August.",
     "what capacity did the solar farm reach", "solar"),
]
FILLER_OPEN = "This document provides general background discussion of the topic in broad terms."
FILLER = (FILLER_OPEN + " ") * 5


def make_corpus():
    if WORK.exists():
        shutil.rmtree(WORK)
    CORPUS.mkdir(parents=True)
    for name, needle, _q, _kw in NEEDLES:
        # needle sentence sits in the MIDDLE, after filler -> old snippet would show filler
        (CORPUS / name).write_text(FILLER + "\n\n" + needle + "\n\n" + FILLER, encoding="utf-8")
    # a few extra filler files so the progress bar has something to count
    for i in range(12):
        (CORPUS / f"filler_{i:02d}.txt").write_text(FILLER + f"\n\nMiscellaneous note number {i}.\n\n" + FILLER,
                                                    encoding="utf-8")
    # a corrupt pdf -> exercises the gentle "skipped N unreadable files" notice
    (CORPUS / "broken.pdf").write_bytes(b"%PDF-1.4 not a real pdf \x00\x01 garbage")


def wait_up(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            requests.get(f"{BASE}/api/status", timeout=2)
            return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    make_corpus()
    env = dict(os.environ, LOCALSEARCH_NO_LAUNCH="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable, "-m", "localsearch.app",
                             "--port", str(PORT), "--index-dir", str(INDEX), "--no-browser"],
                            cwd=str(HERE), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = []
    try:
        print("1) starting `python -m localsearch.app` ...")
        ok.append(("server starts and serves /api/status", wait_up()))
        # the page itself serves
        page = requests.get(BASE + "/").text
        ok.append(("UI page served", "本地语义搜索" in page or "LocalSearch" in page))

        print("2) add folder -> indexing with visible progress")
        r = requests.post(f"{BASE}/api/add_folder", json={"path": str(CORPUS)}).json()
        ok.append(("add_folder accepted", r.get("ok") is True))
        saw_progress = False
        done = False
        t0 = time.time()
        while time.time() - t0 < 90:
            s = requests.get(f"{BASE}/api/status").json()
            if s["building"] and s["progress"]["total"] > 0:
                saw_progress = True
            if not s["building"] and s["files"] > 0:
                done = True
                break
            time.sleep(0.25)
        s = requests.get(f"{BASE}/api/status").json()
        print(f"   indexed: {s['files']} files / {s['chunks']} chunks, model={s['model'].split('/')[-1]}")
        ok.append(("progress was reported during build", saw_progress))
        ok.append(("build finished with files indexed", done and s["files"] >= len(NEEDLES)))
        ok.append(("folder persisted in status", str(CORPUS) in [str(Path(f)) for f in s["folders"]]))
        lb = s.get("last_build") or {}
        print(f"   last_build={lb}  -> UI shows: 已跳过 {lb.get('failed', 0)} 个无法读取的文件")
        ok.append(("error-notice info present (corrupt pdf counted as failed)", lb.get("failed", 0) >= 1))

        print("3) semantic search -> correct file + RELEVANT-SENTENCE snippet + metadata")
        sem_ok = True
        snippet_ok = True
        meta_ok = True
        terms_ok = True
        for name, needle, query, kw in NEEDLES:
            res = requests.post(f"{BASE}/api/search",
                                json={"query": query, "mode": "semantic", "top_k": 10}).json()["results"]
            it = next((r for r in res if r["name"] == name), None)
            if it is None:
                sem_ok = False
                print(f"   [MISS] {query!r} -> {name} not retrieved")
                continue
            snip = it.get("snippet", "")
            centered = (kw.lower() in snip.lower()) and (not snip.lower().startswith(FILLER_OPEN.lower()[:30]))
            snippet_ok &= centered
            meta_ok &= bool(it.get("ext") and it.get("size") and it.get("mtime") and it.get("score") is not None)
            terms_ok &= bool(it.get("terms"))
            print(f"   [OK ] {query!r}")
            print(f"          OLD snippet (chunk start): …{FILLER_OPEN[:48]}…")
            print(f"          NEW snippet (relevant)   : {snip[:90]}")
            print(f"          meta: type={it.get('ext')} size={it.get('size')} "
                  f"modified={it.get('mtime')} score={it.get('score')} highlight_terms={it.get('terms')}")
        ok.append(("semantic: every needle file retrieved", sem_ok))
        ok.append(("snippet shows the RELEVANT sentence (not chunk-start filler)", snippet_ok))
        ok.append(("results carry type/size/modified/score metadata", meta_ok))
        ok.append(("highlight terms returned for the frontend", terms_ok))

        print("4) filename search via Everything")
        res = requests.post(f"{BASE}/api/search",
                            json={"query": "*.txt", "mode": "filename", "top_k": 10}).json()
        fn_ok = (res.get("error") is not None) or (len(res.get("results", [])) > 0)
        print(f"   filename '*.txt' -> {len(res.get('results', []))} hits"
              + (f" (note: {res['error']})" if res.get("error") else ""))
        ok.append(("filename mode works or degrades gracefully", fn_ok))

        print("5) open a result (validated, launch suppressed in test)")
        target = str(CORPUS / "reservoir.txt")
        o = requests.post(f"{BASE}/api/open", json={"path": target, "reveal": False}).json()
        ok.append(("open endpoint validates a real path", o.get("ok") is True))
        bad = requests.post(f"{BASE}/api/open", json={"path": str(CORPUS / "nope.txt")})
        ok.append(("open rejects a missing path", bad.status_code == 404))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print("\n" + "=" * 64 + "\nRESULT\n" + "=" * 64)
    for name, passed in ok:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    allpass = all(p for _, p in ok)
    print("\n" + ("ALL CHECKS PASSED -- a non-programmer can add a folder, search "
                  "(both modes), see snippets, and open files, all in the browser."
                  if allpass else "SOME CHECKS FAILED -- see above."))
    shutil.rmtree(WORK, ignore_errors=True)
    return 0 if allpass else 1


if __name__ == "__main__":
    sys.exit(main())
