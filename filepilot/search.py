"""Поиск по содержимому (FTS5) с фильтрами. Подсветка помечается служебными символами, а не HTML."""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field

from .db import get_db

HL_START, HL_END = "\x02", "\x03"  # границы подсветки: в тексте файлов их практически не бывает
_OPS = {"AND", "OR", "NOT"}


@dataclass
class Filters:
    exts: list[str] = field(default_factory=list)   # [".pdf", ".docx"]
    min_kb: int | None = None
    max_kb: int | None = None
    older_days: int | None = None

    def active(self) -> bool:
        return bool(self.exts or self.min_kb or self.max_kb or self.older_days)


def parse_exts(text: str) -> list[str]:
    """'pdf, docx; .txt' -> ['.pdf', '.docx', '.txt']"""
    out = []
    for e in re.split(r"[\s,;]+", text or ""):
        e = e.strip().lower().lstrip("*")
        if e:
            out.append(e if e.startswith(".") else "." + e)
    return out


def build_fts_query(q: str) -> str:
    """Слова дополняются до префиксов: «догов» найдёт «договор». Кавычки означают точную фразу."""
    parts: list[str] = []
    for tok in re.findall(r'"[^"]+"|\S+', q):
        if tok.startswith('"') and tok.endswith('"') and len(tok) > 2:
            parts.append('"' + tok[1:-1].replace('"', "") + '"')
        elif tok in _OPS:
            parts.append(tok)
        else:
            for w in re.findall(r"\w+", tok):
                parts.append(f'"{w}"*' if len(w) > 1 else f'"{w}"')
    # операторы допустимы только между словами
    while parts and parts[0] in _OPS:
        parts.pop(0)
    while parts and parts[-1] in _OPS:
        parts.pop()
    return " ".join(parts)


def _where(f: Filters, params: list) -> str:
    cond = []
    if f.exts:
        cond.append("f.ext IN (%s)" % ",".join("?" * len(f.exts)))
        params.extend(f.exts)
    if f.min_kb:
        cond.append("f.size >= ?")
        params.append(f.min_kb * 1024)
    if f.max_kb:
        cond.append("f.size <= ?")
        params.append(f.max_kb * 1024)
    if f.older_days:
        cond.append("f.mtime <= ?")
        params.append(time.time() - f.older_days * 86400)
    return (" AND " + " AND ".join(cond)) if cond else ""


def search(query: str, filters: Filters | None = None, limit: int = 300) -> list[dict]:
    f = filters or Filters()
    q = (query or "").strip()
    conn = get_db()
    params: list = []
    if not q:
        if not f.active():
            return []
        sql = "SELECT f.path, f.name, f.size, f.mtime, '' AS snippet FROM files f WHERE 1=1" + _where(f, params) + " ORDER BY f.mtime DESC LIMIT ?"
        return [dict(r) for r in conn.execute(sql, params + [limit])]

    fts = build_fts_query(q)
    if fts:
        params = [fts]
        sql = (
            f"SELECT f.path, f.name, f.size, f.mtime, "
            f"snippet(files_fts, 1, '{HL_START}', '{HL_END}', '…', 24) AS snippet "
            "FROM files_fts JOIN files f ON f.id = files_fts.rowid WHERE files_fts MATCH ?"
            + _where(f, params) + " ORDER BY rank LIMIT ?"
        )
        try:
            return [dict(r) for r in conn.execute(sql, params + [limit])]
        except sqlite3.OperationalError:
            pass  # некорректный запрос: ищем простым LIKE
    params = []
    like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
    sql = (
        "SELECT f.path, f.name, f.size, f.mtime, substr(f.content, 1, 200) AS snippet FROM files f "
        "WHERE (f.name LIKE ? ESCAPE '\\' OR f.content LIKE ? ESCAPE '\\')" + _where(f, params) + " ORDER BY f.mtime DESC LIMIT ?"
    )
    return [dict(r) for r in conn.execute(sql, [like, like] + params + [limit])]
