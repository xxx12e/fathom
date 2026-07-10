"""掌控模式 (Control mode) proof: deep-index a chosen scope.

  1. FIRST scan = full (parse + embed everything), with system/junk dirs
     (node_modules / .git / .venv / Windows ...) automatically EXCLUDED.
  2. After editing files, the NEXT scan is DIFF-ONLY: unchanged files are skipped
     (by mtime+size), only the changed/new/deleted files are touched -- so the
     re-scan is near-instant and cheap. This is the "下次只扫 diff" guarantee.
"""
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localsearch import SearchEngine

WORK = HERE / "_control_tmp"
SCOPE = WORK / "scope"
IDX = WORK / "index"
N_REAL = 120


def setup():
    if WORK.exists():
        shutil.rmtree(WORK)
    SCOPE.mkdir(parents=True)
    body = ("This note discusses project planning, budgets, schedules and risk "
            "across several quarters in plain prose. ") * 6
    for i in range(N_REAL):
        (SCOPE / f"note_{i:03d}.txt").write_text(body + f"\n\nItem {i}.", encoding="utf-8")
    # junk dirs that 掌控模式 must auto-exclude:
    for junk in ("node_modules", ".git", ".venv", "__pycache__"):
        d = SCOPE / "project" / junk
        d.mkdir(parents=True)
        for j in range(15):
            (d / f"junk_{j}.txt").write_text("should NOT be indexed " * 20, encoding="utf-8")


def main():
    setup()
    eng = SearchEngine(IDX)
    ok = []

    print("1) 首次扫描 = 全量(系统/垃圾目录自动排除)")
    t0 = time.perf_counter()
    s1 = eng.build([SCOPE])
    full_s = time.perf_counter() - t0
    print(f"   全量扫描: {s1} | 用时 {full_s:.1f}s | 索引文件数 {eng.stats()['files']}")
    ok.append((f"全量只索引了真实文件({N_REAL})，node_modules/.git/.venv 被排除",
               eng.stats()["files"] == N_REAL and s1["added"] == N_REAL))

    print("\n2) 改 1 个、加 1 个、删 1 个文件")
    (SCOPE / "note_000.txt").write_text("UPDATED content about quarterly revenue forecasts.", encoding="utf-8")
    (SCOPE / "brand_new.txt").write_text("A brand new memo about hiring plans.", encoding="utf-8")
    (SCOPE / "note_119.txt").unlink()

    print("3) 下次扫描 = 仅增量(diff),跳过没变的文件")
    t0 = time.perf_counter()
    s2 = eng.build([SCOPE])
    diff_s = time.perf_counter() - t0
    print(f"   增量扫描: {s2} | 用时 {diff_s:.2f}s")
    ok.append(("增量只动了变化的(改1/加1/删1)，其余全部跳过",
               s2["updated"] == 1 and s2["added"] == 1 and s2["removed"] == 1
               and s2["skipped"] == N_REAL - 2))
    ok.append((f"增量比全量快很多 ({full_s:.1f}s -> {diff_s:.2f}s)", diff_s < full_s / 3))

    print("\n4) 内容确实更新了(搜得到新文件、新内容)")
    hits = eng.search_semantic("hiring plans memo", top_k=5)
    found_new = any(Path(h.path).name == "brand_new.txt" for h in hits)
    ok.append(("新加的文件能被深度语义搜到", found_new))

    print("\n" + "=" * 64 + "\n结果\n" + "=" * 64)
    for name, p in ok:
        print(f"  [{'PASS' if p else 'FAIL'}] {name}")
    allp = all(p for _, p in ok)
    print("\n" + ("全部通过 —— 掌控模式:首次全扫(排垃圾) + 之后只扫 diff,成立。"
                  if allp else "有失败,见上。"))
    eng.close()
    shutil.rmtree(WORK, ignore_errors=True)
    return 0 if allp else 1


if __name__ == "__main__":
    sys.exit(main())
