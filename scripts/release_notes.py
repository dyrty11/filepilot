"""Печатает раздел CHANGELOG.md для версии: python scripts/release_notes.py 0.2.0 > notes.md

Текст попадает в описание релиза на GitHub и в окно «Доступно обновление» внутри программы.
"""
import re
import sys
from pathlib import Path


def section(version: str, text: str) -> str:
    m = re.search(r"^## %s\s*$(.*?)(?=^## |\Z)" % re.escape(version), text, re.M | re.S)
    return m.group(1).strip() if m else ""


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # на Windows при перенаправлении вывода кодировка была бы cp1252 и русский текст ломал бы скрипт
    ver = sys.argv[1].lstrip("v")
    log = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    body = section(ver, log.read_text(encoding="utf-8")) if log.exists() else ""
    print(body or f"FilePilot {ver}. Подробности: CHANGELOG.md в репозитории.")
