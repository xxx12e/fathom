"""Optional image OCR via the Windows built-in engine (Windows.Media.Ocr).

No model to ship or train: Windows provides the OCR engine and its language data,
so this adds ~zero size and stays 100% offline. If winrt or an OCR language pack
is missing, OCR degrades to off and image files are simply skipped.

All WinRT calls run on ONE dedicated worker thread (single COM apartment, one
reused engine) so it is safe under the engine's multi-threaded, lock-free parse.
Windows OCR emits a space between every CJK glyph; we collapse those so bigram
tokenization and dense embedding see natural Chinese/Japanese text.
"""
import asyncio
import logging
import re
import threading

log = logging.getLogger("localsearch.ocr")

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")

_CJK = "⺀-⿿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯"
_CJK_GAP = re.compile("(?<=[%s])[ \t]+(?=[%s])" % (_CJK, _CJK))


def _collapse_cjk(t):
    """Drop the single space Windows OCR inserts between CJK glyphs; a Latin/CJK
    boundary keeps its space (both sides must be CJK to collapse)."""
    return _CJK_GAP.sub("", t) if t else t


class _Engine:
    def __init__(self):
        self._loop = None
        self._engine = None
        self.language = None
        self.error = None
        self._lock = threading.Lock()
        self._started = False

    def _ensure(self):
        with self._lock:
            if self._started:
                return
            self._started = True
            ready = threading.Event()

            def run():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                try:
                    from winrt.windows.media.ocr import OcrEngine
                    eng = OcrEngine.try_create_from_user_profile_languages()
                    if eng is None:
                        langs = list(OcrEngine.available_recognizer_languages)
                        if langs:
                            eng = OcrEngine.try_create_from_language(langs[0])
                    self._engine = eng
                    if eng is not None:
                        self.language = eng.recognizer_language.language_tag
                    else:
                        self.error = "no OCR language pack installed"
                except Exception as e:
                    self.error = "%s: %s" % (type(e).__name__, e)
                ready.set()
                if self._loop is not None:
                    self._loop.run_forever()

            threading.Thread(target=run, name="ls-ocr", daemon=True).start()
            ready.wait(timeout=20)

    def available(self):
        self._ensure()
        return self._engine is not None

    async def _ocr(self, path):
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage import StorageFile, FileAccessMode
        f = await StorageFile.get_file_from_path_async(str(path))
        stream = await f.open_async(FileAccessMode.READ)
        try:
            decoder = await BitmapDecoder.create_async(stream)
            bmp = await decoder.get_software_bitmap_async()
        finally:
            stream.close()
        res = await self._engine.recognize_async(bmp)
        return res.text

    def image(self, path, timeout=30):
        if not self.available():
            return None
        fut = asyncio.run_coroutine_threadsafe(self._ocr(str(path)), self._loop)
        try:
            return _collapse_cjk(fut.result(timeout))
        except Exception as e:
            fut.cancel()          # don't leave a slow recognition (+bitmap) orphaned
            log.warning("OCR failed for %s: %s", path, e)
            return None


_ENGINE = _Engine()


def available():
    return _ENGINE.available()


def status():
    """OCR availability WITHOUT forcing a probe: while OCR has never been used,
    `available` is None (unknown) so off-by-default users never load winrt or
    spin the worker thread. Enabling OCR (available()) does the real probe."""
    if not _ENGINE._started:
        return {"available": None, "language": None, "error": None}
    _ENGINE._ensure()
    return {"available": _ENGINE._engine is not None,
            "language": _ENGINE.language, "error": _ENGINE.error}


def ocr_image(path, timeout=30):
    return _ENGINE.image(path, timeout)
