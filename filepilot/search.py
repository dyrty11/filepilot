"""Поиск по содержимому (FTS5) с фильтрами. Подсветка помечается служебными символами, а не HTML."""
from __future__ import annotations

import os
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
    newer_days: int | None = None  # только изменённые за последние N дней
    folder: str | None = None  # искать только внутри этой папки (с подпапками)
    name: str | None = None  # искать только в имени файла, не в содержимом

    def active(self) -> bool:
        return bool(self.exts or self.min_kb or self.max_kb or self.older_days or self.newer_days or self.folder or self.name)


def parse_exts(text: str) -> list[str]:
    """'pdf, docx; .txt' -> ['.pdf', '.docx', '.txt']"""
    out = []
    for e in re.split(r"[\s,;]+", text or ""):
        e = e.strip().lower().lstrip("*")
        if e:
            out.append(e if e.startswith(".") else "." + e)
    return out


_OP_RX = re.compile(r'"[^"]*"|(?<!\S)(ext|in|name|older|newer|bigger|smaller):(?:"([^"]*)"|(\S+))', re.IGNORECASE)
_SIZE_RX = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(kb|кб|mb|мб|gb|гб)?$", re.IGNORECASE)
_UNIT_KB = {"kb": 1, "кб": 1, "mb": 1024, "мб": 1024, "gb": 1024 * 1024}


def _size_kb(text: str) -> int | None:
    """'5mb' -> 5120, '100kb' -> 100, '2' -> 2048 (без единицы считаем мегабайты)."""
    m = _SIZE_RX.match(text.strip())
    if not m:
        return None
    unit = (m.group(2) or "mb").lower()
    return max(1, int(float(m.group(1).replace(",", ".")) * _UNIT_KB[unit]))


def parse_operators(query: str) -> tuple[str, Filters]:
    """Достаёт из строки поиска операторы: ext:pdf,docx  name:отчёт  in:"C:\\Мои документы"  older:30  newer:7  bigger:5mb  smaller:100kb.
    Возвращает (текст без операторов, фильтры из операторов). Фразы в кавычках не трогаются."""
    ops = Filters()

    def take(m: re.Match) -> str:
        key = m.group(1)
        if not key:
            return m.group(0)  # фраза в кавычках
        val = (m.group(2) if m.group(2) is not None else m.group(3)).strip()
        key = key.lower()
        if key == "ext":
            ops.exts = parse_exts(val)
        elif key == "name":
            ops.name = val or None
        elif key == "in":
            ops.folder = val or None
        elif key == "older":
            ops.older_days = int(val) if val.isdigit() and int(val) > 0 else None
        elif key == "newer":
            ops.newer_days = int(val) if val.isdigit() and int(val) > 0 else None
        elif key == "bigger":
            ops.min_kb = _size_kb(val)
        elif key == "smaller":
            ops.max_kb = _size_kb(val)
        return " "

    text = _OP_RX.sub(take, query or "")
    return re.sub(r"\s+", " ", text).strip(), ops


def merge_filters(base: Filters, ops: Filters) -> Filters:
    """Оператор в строке поиска сильнее поля в панели фильтров."""
    return Filters(exts=ops.exts or base.exts, min_kb=ops.min_kb or base.min_kb, max_kb=ops.max_kb or base.max_kb,
                   older_days=ops.older_days or base.older_days, newer_days=ops.newer_days or base.newer_days, folder=ops.folder or base.folder,
                   name=ops.name or base.name)


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
    if f.newer_days:
        cond.append("f.mtime >= ?")
        params.append(time.time() - f.newer_days * 86400)
    if f.folder:
        base = os.path.normpath(f.folder).rstrip("\\/")
        esc = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cond.append("f.path LIKE ? ESCAPE '\\'")
        params.append(esc + os.sep.replace("\\", "\\\\") + "%")
    return (" AND " + " AND ".join(cond)) if cond else ""


def search(query: str, filters: Filters | None = None, limit: int = 300) -> list[dict]:
    q, ops = parse_operators(query or "")
    f = merge_filters(filters or Filters(), ops)
    conn = get_db()
    params: list = []
    if not q and not f.name:
        if not f.active():
            return []
        sql = "SELECT f.path, f.name, f.size, f.mtime, '' AS snippet FROM files f WHERE 1=1" + _where(f, params) + " ORDER BY f.mtime DESC LIMIT ?"
        return [dict(r) for r in conn.execute(sql, params + [limit])]

    fts = build_fts_query(q)
    name_fts = build_fts_query(f.name) if f.name else ""
    if name_fts:  # name:слово: ищем только в имени файла
        fts = f"({fts}) AND name : ({name_fts})" if fts else f"name : ({name_fts})"
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
    if f.name:  # запасной путь тоже уважает name:
        nl_ = "%" + f.name.replace("%", r"\%").replace("_", r"\_") + "%"
        extra = " AND f.name LIKE ? ESCAPE '\\'"
        like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
        sql = ("SELECT f.path, f.name, f.size, f.mtime, '' AS snippet FROM files f WHERE (f.name LIKE ? ESCAPE '\\' OR f.content LIKE ? ESCAPE '\\')"
               + extra + _where(f, params) + " ORDER BY f.mtime DESC LIMIT ?")
        return [dict(r) for r in conn.execute(sql, [like, like, nl_] + params + [limit])]
    like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
    sql = (
        "SELECT f.path, f.name, f.size, f.mtime, substr(f.content, 1, 200) AS snippet FROM files f "
        "WHERE (f.name LIKE ? ESCAPE '\\' OR f.content LIKE ? ESCAPE '\\')" + _where(f, params) + " ORDER BY f.mtime DESC LIMIT ?"
    )
    return [dict(r) for r in conn.execute(sql, [like, like] + params + [limit])]


PREVIEW_LIMIT = 300_000


def get_content(path: str) -> str | None:
    """Текст файла из индекса (None, если файла нет в индексе)."""
    row = get_db().execute("SELECT substr(content, 1, ?) AS c FROM files WHERE path = ?", (PREVIEW_LIMIT, path)).fetchone()
    return None if row is None else (row["c"] or "")


def query_words(query: str) -> list[str]:
    words: list[str] = []
    for tok in re.findall(r'"[^"]+"|\S+', parse_operators(query or "")[0]):
        if tok in _OPS:
            continue
        words += [w for w in re.findall(r"\w+", tok) if w.upper() not in _OPS]
    return sorted(set(words), key=len, reverse=True)


def mark_matches(text: str, query: str) -> tuple[str, int]:
    """Оборачивает найденные слова (с продолжением, как префиксный поиск) в маркеры подсветки. Возвращает (текст, число совпадений)."""
    words = query_words(query)
    if not words or not text:
        return text, 0
    rx = re.compile("(?:%s)\\w*" % "|".join(re.escape(w) for w in words), re.IGNORECASE)
    return rx.subn(lambda m: HL_START + m.group(0) + HL_END, text)


def export_csv(rows: list[dict], dest: str) -> int:
    """Сохраняет результаты в CSV (UTF-8 с BOM, разделитель «;» — открывается в Excel)."""
    import csv
    from .config import format_time
    from .i18n import tr
    with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow([tr("Путь"), tr("Имя"), tr("Размер, байт"), tr("Изменён")])
        for r in rows:
            w.writerow([r["path"], r["name"], r["size"], format_time(r["mtime"])])
    return len(rows)
