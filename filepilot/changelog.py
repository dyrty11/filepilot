"""Раздел CHANGELOG.md для версии: показывается в окне «FilePilot обновлён». Файл лежит рядом с программой."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def section(version: str, text: str) -> str:
    m = re.search(r"^## %s\s*$(.*?)(?=^## |\Z)" % re.escape(version), text, re.M | re.S)
    return m.group(1).strip() if m else ""


def notes_for(version: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    try:
        return section(version, (base / "CHANGELOG.md").read_text(encoding="utf-8"))
    except OSError:
        return ""
