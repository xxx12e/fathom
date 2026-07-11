"""Robust file-text extraction. Office/HTML/RTF formats use only the stdlib
(zipfile + xml.etree + html.parser) -- no new dependencies, so the bundle never
grows for the extra coverage."""
import logging
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from . import ocr as _ocr

log = logging.getLogger("localsearch.parser")

_OCR_ON = False


def set_ocr(enabled):
    """Turn image OCR on/off. Returns the effective state (on only if the Windows
    OCR engine is actually available)."""
    global _OCR_ON
    _OCR_ON = bool(enabled) and _ocr.available()
    return _OCR_ON


def _ocr_active():
    return _OCR_ON

try:
    import fitz
except Exception:
    fitz = None
try:
    import docx
except Exception:
    docx = None


def _read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _parse_md(path):
    t = _read_text(path)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"[#>*_`]+", " ", t)
    return t


def _parse_pdf(path):
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) not installed")
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _parse_docx(path):
    if docx is None:
        raise RuntimeError("python-docx not installed")
    d = docx.Document(str(path))
    return "\n".join(p.text for p in d.paragraphs)


def _zip_xml_text(path, patterns):
    """Extract every <*:t> text node from the zip members matching `patterns`
    (OOXML stores text in <w:t>/<a:t>/<t>, all localname 't'). Used for xlsx/pptx."""
    parts = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not any(re.match(p, name) for p in patterns):
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for el in root.iter():
                if el.tag.rsplit("}", 1)[-1] == "t" and el.text:
                    parts.append(el.text)
    return " ".join(parts)


def _parse_xlsx(path):
    return _zip_xml_text(path, [r"xl/sharedStrings\.xml$", r"xl/worksheets/sheet.*\.xml$"])


def _parse_pptx(path):
    return _zip_xml_text(path, [r"ppt/slides/slide\d.*\.xml$", r"ppt/notesSlides/.*\.xml$"])


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _parse_html(path):
    p = _HTMLText()
    p.feed(_read_text(path))
    return " ".join(" ".join(p.parts).split())


def _parse_rtf(path):
    t = _read_text(path)
    t = re.sub(r"\\'[0-9a-fA-F]{2}", " ", t)     # hex-escaped bytes
    t = re.sub(r"\\u-?\d+\??", " ", t)           # unicode escapes
    t = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", t)    # control words
    t = t.replace("{", " ").replace("}", " ").replace("\\*", " ")
    return " ".join(t.split())


_PARSERS = {".txt": _read_text, ".md": _parse_md, ".pdf": _parse_pdf, ".docx": _parse_docx,
            ".xlsx": _parse_xlsx, ".pptx": _parse_pptx, ".csv": _read_text,
            ".html": _parse_html, ".htm": _parse_html, ".rtf": _parse_rtf}

SUPPORTED = tuple(_PARSERS.keys())


def current_exts():
    """Extensions the engine should index right now (image types only while OCR
    is on) -- the single source of truth for both the walk and the watcher."""
    return SUPPORTED + _ocr.IMAGE_EXT if _OCR_ON else SUPPORTED


def is_supported(path):
    ext = Path(path).suffix.lower()
    return ext in _PARSERS or (_OCR_ON and ext in _ocr.IMAGE_EXT)


def parse_file(path):
    """Return extracted text, or None if unsupported / unreadable (logged)."""
    ext = Path(path).suffix.lower()
    fn = _PARSERS.get(ext)
    if fn is None and _OCR_ON and ext in _ocr.IMAGE_EXT:
        fn = _ocr.ocr_image
    if fn is None:
        log.debug("skip unsupported type: %s", path)
        return None
    try:
        text = fn(path)
        if not text or not text.strip():
            log.debug("empty after parse: %s", path)
            return None
        return text
    except Exception as e:
        log.warning("parse failed, skipping %s: %s: %s", path, type(e).__name__, e)
        return None
