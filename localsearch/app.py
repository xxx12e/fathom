"""Minimal LOCAL web UI for the localsearch engine (brick 6)."""
import argparse
import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Flask, request, jsonify, Response

from .engine import SearchEngine
from .config import Config
from . import resources

log = logging.getLogger("localsearch.app")
HERE = Path(__file__).resolve().parent
WEB = resources.web_dir()


class AppState:
    def __init__(self, engine, index_dir):
        self.engine = engine
        self.index_dir = Path(index_dir)
        self.folders_file = self.index_dir / "folders.json"
        self.folders = self._load_folders()
        self.building = False
        self.build_lock = threading.Lock()
        self.cancel = False
        self.last_build = None
        self.last_error = ""
        self.last_error_detail = ""
        self.model_ready = False
        self.progress = {"done": 0, "total": 0, "file": ""}

    def _load_folders(self):
        try:
            return json.loads(self.folders_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_folders(self):
        """Atomically persist the folder list (tmp + fsync + replace)."""
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.folders_file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.folders, f)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.folders_file)
        except Exception as e:
            log.warning("could not persist folders: %s", e)

    def resume_watch(self):
        existing = [f for f in self.folders if os.path.isdir(f)]
        if existing:
            try:
                self.engine.start_watching(existing)
            except Exception as e:
                log.warning("resume watch failed: %s", e)


def _snippet(text, n=240):
    t = " ".join(text.split())
    return t[:n] + ("…" if len(t) > n else "")


def _human_size(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024


def _result(path, snippet, score, terms, personal=False):
    """Build a result row with current metadata; None if the file is gone."""
    import time as _t
    try:
        st = os.stat(path)
    except OSError:
        return None
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "?"
    size = _human_size(st.st_size)
    mtime = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(st.st_mtime))
    return dict(name=os.path.basename(path), path=path, snippet=snippet, score=score,
                terms=terms, ext=ext, size=size, mtime=mtime, personal=personal)


def create_app(index_dir, config=None):
    from . import winsearch
    engine = SearchEngine(index_dir, config or Config())
    state = AppState(engine, index_dir)
    state.resume_watch()

    def _warm():
        ok = engine.warmup()
        engine.prepare_index()
        if ok:
            state.model_ready = True
        else:
            state.last_error = "AI 模型加载失败，语义搜索不可用（详见控制台/engine.log）。"
    threading.Thread(target=_warm, daemon=True).start()

    ws_available = winsearch.available()
    app = Flask(__name__)

    @app.get("/")
    def home():
        return Response((WEB / "index.html").read_text(encoding="utf-8"), mimetype="text/html")

    @app.get("/api/status")
    def status():
        s = engine.stats()
        return jsonify(files=s["files"], chunks=s["chunks"], model=engine.cfg.model_name,
                       building=state.building, progress=state.progress, folders=state.folders,
                       last_build=state.last_build, ws_available=ws_available,
                       model_ready=state.model_ready, last_error=state.last_error,
                       last_error_detail=state.last_error_detail, index_error=engine.load_error,
                       personalize=engine.personalizer.stats())

    @app.post("/api/cancel_build")
    def cancel_build():
        state.cancel = True
        return jsonify(ok=True)

    @app.post("/api/personalize")
    def personalize():
        # toggle local, training-free personalization on/off
        on = bool((request.get_json(silent=True) or {}).get("enabled", True))
        engine.personalizer.set_enabled(on)
        return jsonify(ok=True, enabled=engine.personalizer.enabled)

    @app.post("/api/forget")
    def forget():
        # wipe the local behavioral profile (opens + interest vector)
        engine.personalizer.reset()
        return jsonify(ok=True)

    @app.post("/api/pick_folder")
    def pick_folder():


        try:
            import tkinter as tk
            from tkinter import filedialog
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            p = filedialog.askdirectory()
            r.destroy()
            return jsonify(path=p or "")
        except Exception as e:
            log.warning("folder dialog failed (type the path instead): %s", e)
            return jsonify(path="", error=str(e))

    def _start_build(paths, register):
        """Background full-or-diff build (the engine skips unchanged files itself)."""
        with state.build_lock:
            if state.building:
                return False
            state.building = True
        state.cancel = False
        state.last_error = ""
        state.last_error_detail = ""
        state.progress = {"done": 0, "total": 0, "file": ""}

        def worker():
            def cb(done, total, f):
                state.progress = {"done": done, "total": total, "file": os.path.basename(f)}
            try:
                state.last_build = engine.build(paths, progress_callback=cb,
                                                cancel_check=lambda: state.cancel)
                engine.load_error = ""
                if register:
                    for p in paths:
                        if p not in state.folders:
                            state.folders.append(p)
                    state._save_folders()
                engine.start_watching([f for f in state.folders if os.path.isdir(f)])
            except Exception as e:
                log.error("build failed: %s", e)
                state.last_error = "build_failed"
                state.last_error_detail = str(e)
            finally:
                state.building = False

        threading.Thread(target=worker, daemon=True).start()
        return True

    @app.post("/api/add_folder")
    def add_folder():
        path = (request.get_json(silent=True) or {}).get("path", "").strip()
        if not path or not os.path.isdir(path):
            return jsonify(ok=False, code="bad_folder", error="Not a valid folder."), 400
        if not _start_build([path], register=True):
            return jsonify(ok=False, code="busy", error="Already indexing, please wait."), 409
        return jsonify(ok=True, started=True)

    @app.post("/api/remove_folder")
    def remove_folder():
        """Un-control a folder: drop it and purge its indexed entries."""
        path = (request.get_json(silent=True) or {}).get("path", "").strip()
        with state.build_lock:
            if state.building:
                return jsonify(ok=False, code="busy", error="Busy indexing."), 409
            if path not in state.folders:
                return jsonify(ok=False, code="not_controlled", error="Not in the controlled list."), 400
            state.folders.remove(path)
            state._save_folders()
            n = engine.remove_tree(path, persist=True)
            engine.start_watching([f for f in state.folders if os.path.isdir(f)])
        return jsonify(ok=True, removed_chunks=n)

    @app.get("/api/drives")
    def drives():
        return jsonify(drives=engine.list_drives())

    @app.post("/api/rescan")
    def rescan():

        paths = [f for f in state.folders if os.path.isdir(f)]
        if not paths:
            return jsonify(ok=False, code="no_folders", error="No controlled folders yet."), 400
        if not _start_build(paths, register=False):
            return jsonify(ok=False, code="busy", error="Busy indexing."), 409
        return jsonify(ok=True, started=True)

    @app.post("/api/search")
    def search():
        d = request.get_json(silent=True) or {}
        q = d.get("query", "").strip()
        mode = d.get("mode", "semantic")
        k = int(d.get("top_k", 20))
        scope = (d.get("scope") or "").strip() or None
        if not q:
            return jsonify(results=[])
        if mode == "filename":
            paths = engine.search_filename(q, limit=k, scope=scope)
            if paths is None:
                return jsonify(results=[], code="no_everything",
                               error="Everything (es.exe) not available.")
            res = [_result(p, snippet="", score=None, terms=[]) for p in paths]
        elif mode == "instant":
            if not ws_available:
                return jsonify(results=[], code="ws_down",
                               error="Windows Search service is off.")
            hits = engine.search_instant_global(q, top_k=k, scope=scope)
            if not hits:
                return jsonify(results=[], code="no_hits", error="No content matches.")
            res = [_result(h.path, snippet=h.snippet, score=round(h.score, 3),
                           terms=h.terms, personal=h.personal) for h in hits]
        else:
            hits = engine.search_semantic(q, top_k=k)
            res = [_result(h.path, snippet=h.snippet or _snippet(h.chunk_text),
                           score=round(h.score, 3), terms=h.terms, personal=h.personal) for h in hits]
        return jsonify(results=[r for r in res if r is not None])

    @app.post("/api/open")
    def open_path():
        d = request.get_json(silent=True) or {}
        path = d.get("path", "")
        reveal = bool(d.get("reveal", False))
        if not os.path.exists(path):
            return jsonify(ok=False, code="no_file", error="File no longer exists."), 404
        engine.record_open(path)        # local behavioral profile (training-free)
        if os.environ.get("LOCALSEARCH_NO_LAUNCH"):
            return jsonify(ok=True, launched=False)
        try:
            if reveal:
                subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            else:
                os.startfile(path)
            return jsonify(ok=True)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    return app, engine, state


def _install_shutdown_hooks(engine):
    """Persist pending changes on every exit path (finally/atexit + console-close)."""
    closed = threading.Event()

    def close_once():
        if not closed.is_set():
            closed.set()
            try:
                engine.close()
            except Exception:
                pass

    atexit.register(close_once)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def _ctrl(evt):

                if evt in (2, 5, 6):
                    close_once()
                return False

            _install_shutdown_hooks._keep = HANDLER(_ctrl)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_install_shutdown_hooks._keep, True)
        except Exception as e:
            log.warning("console close hook not installed: %s", e)
    return close_once


def main():
    ap = argparse.ArgumentParser(description="LocalSearch UI (fully local)")
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--index-dir", default=str(Path.home() / ".localsearch_index"))
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    app, engine, state = create_app(args.index_dir)
    close_once = _install_shutdown_hooks(engine)
    url = f"http://127.0.0.1:{args.port}"
    print("=" * 64)
    print(f"  LocalSearch UI  ->  {url}")
    print(f"  index dir: {args.index_dir}")
    print("  Fully local. Nothing is sent over the network.")
    print("  Press Ctrl+C (or close this window) to stop.")
    print("=" * 64)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        app.run(host="127.0.0.1", port=args.port, threaded=True)
    finally:
        close_once()


if __name__ == "__main__":
    main()
