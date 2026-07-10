"""Robust file-text extraction for txt / md / pdf / docx."""
import logging
import re
from pathlib import Path

log = logging.getLogger("localsearch.parser")

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


_PARSERS = {".txt": _read_text, ".md": _parse_md, ".pdf": _parse_pdf, ".docx": _parse_docx}

SUPPORTED = tuple(_PARSERS.keys())


def is_supported(path):
    return Path(path).suffix.lower() in _PARSERS


def parse_file(path):
    """Return extracted text, or None if unsupported / unreadable (logged)."""
    ext = Path(path).suffix.lower()
    fn = _PARSERS.get(ext)
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
