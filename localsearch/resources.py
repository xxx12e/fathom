"""Locate bundled assets (web UI, es.exe, model) in source and frozen modes."""
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
_PKG = Path(__file__).resolve().parent
_MEI = Path(getattr(sys, "_MEIPASS", _PKG))


def web_dir():
    return (_MEI / "web") if FROZEN else (_PKG / "web")


def es_exe():
    return (_MEI / "tools" / "es.exe") if FROZEN else (_PKG.parent / "tools" / "es.exe")


def model_path():
    """Bundled model dir when frozen (fully offline); else the HF hub id.
    multilingual-e5-small: 100+ languages, strong cross-lingual retrieval, light
    (~118M params, 384-dim). Needs 'query: ' / 'passage: ' prefixes (see Config)."""
    if FROZEN:
        m = _MEI / "models" / "embed"
        if (m / "config.json").exists():
            return str(m)
    return "intfloat/multilingual-e5-small"
