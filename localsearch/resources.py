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
    """Bundled model dir when frozen (fully offline); else the HF hub id."""
    if FROZEN:
        m = _MEI / "models" / "bge-base"
        if (m / "config.json").exists():
            return str(m)
    return "BAAI/bge-base-en-v1.5"
