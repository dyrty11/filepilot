"""Извлечение текста из файлов. Docx/xlsx/pptx/odt читаются напрямую из zip: без сторонних библиотек."""
from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import (
    MAX_CONTENT_CHARS, MAX_CONTENT_FILE_BYTES, MAX_ZIP_MEMBER_BYTES, TEXT_EXTS, ZIP_XML_EXTS,
)

# Какие части zip содержат текст
_ZIP_MEMBERS = {
    ".docx": re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$"),
    ".xlsx": re.compile(r"^xl/sharedStrings\.xml$"),
    ".pptx": re.compile(r"^ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml$"),
    ".odt": re.compile(r"^content\.xml$"),
    ".ods": re.compile(r"^content\.xml$"),
    ".odp": re.compile(r"^content\.xml$"),
}
_PARA_TAGS = {"p", "si", "h"}  # абзацы docx/pptx/odf и строки sharedStrings


def extract_text(path: Path) -> str | None:
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTS:
            return read_text_file(path)
        if ext == ".pdf":
            return _read_pdf(path)
        if ext in ZIP_XML_EXTS:
            return _read_zip_xml(path, ext)
    except Exception:
        return None
    return None


def decode_bytes(raw: bytes) -> str:
    """Определение кодировки без внешних библиотек: BOM, UTF-8, затем cp1251 (типично для русских файлов)."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1251")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def read_text_file(path: Path) -> str:
    with open(path, "rb") as f:
        raw = f.read(MAX_CONTENT_CHARS * 2)  # не читаем гигабайты целиком
    if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ""  # бинарный файл с «текстовым» расширением
    return decode_bytes(raw)[:MAX_CONTENT_CHARS]


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # битые PDF не сыплют предупреждениями

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        return ""
    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        parts.append(t)
        total += len(t)
        if total >= MAX_CONTENT_CHARS:
            break
    return "\n".join(parts)[:MAX_CONTENT_CHARS]


def _xml_paragraphs(data: bytes) -> list[str]:
    root = ET.fromstring(data)
    out: list[str] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in _PARA_TAGS:
            text = "".join(el.itertext()).strip()
            if text:
                out.append(text)
    if not out:  # запасной вариант: весь текст подряд
        text = " ".join(t.strip() for t in root.itertext() if t.strip())
        if text:
            out.append(text)
    return out


def _read_zip_xml(path: Path, ext: str) -> str:
    pattern = _ZIP_MEMBERS[ext]
    parts: list[str] = []
    total = 0
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if pattern.match(n))
        for name in names:
            info = z.getinfo(name)
            if info.file_size > MAX_ZIP_MEMBER_BYTES:
                continue
            parts.extend(_xml_paragraphs(z.read(name)))
            total = sum(len(p) for p in parts)
            if total >= MAX_CONTENT_CHARS:
                break
    return "\n".join(parts)[:MAX_CONTENT_CHARS]


__all__ = ["extract_text", "decode_bytes", "read_text_file", "MAX_CONTENT_FILE_BYTES"]
