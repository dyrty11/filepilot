"""Карта диска: крупнейшие файлы, папки и типы файлов."""
from __future__ import annotations

import os
from collections import defaultdict

from .db import get_db

# Служебные подписи (данные хранятся по-русски, интерфейс переводит их при показе)
ROOT_LABEL = "(файлы в корне)"
NO_EXT_LABEL = "(без расширения)"


def top_files(limit: int = 200, min_size: int = 0) -> list[dict]:
    cur = get_db().execute(
        "SELECT path, name, size, mtime FROM files WHERE size >= ? ORDER BY size DESC LIMIT ?", (min_size, limit)
    )
    return [dict(r) for r in cur]


def by_folder(roots: list[str], limit: int = 100) -> list[dict]:
    """Размер по папкам первого уровня внутри каждой проиндексированной папки."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    conn = get_db()
    for root in roots:
        root = os.path.normpath(root)
        prefix = root.rstrip("\\/") + os.sep
        for row in conn.execute("SELECT path, size FROM files WHERE substr(path, 1, ?) = ?", (len(prefix), prefix)):
            rest = row["path"][len(prefix):]
            first = rest.split(os.sep, 1)[0] if os.sep in rest else ROOT_LABEL
            key = os.path.join(root, first) if first != ROOT_LABEL else root + " " + ROOT_LABEL
            totals[key] += row["size"] or 0
            counts[key] += 1
    grand = sum(totals.values()) or 1
    rows = [{"folder": k, "size": v, "files": counts[k], "share": v / grand} for k, v in totals.items()]
    rows.sort(key=lambda r: r["size"], reverse=True)
    return rows[:limit]


def by_type(limit: int = 30) -> list[dict]:
    rows = get_db().execute(
        "SELECT COALESCE(NULLIF(ext, ''), ?) AS ext, COUNT(*) AS files, COALESCE(SUM(size), 0) AS size "
        "FROM files GROUP BY 1 ORDER BY size DESC LIMIT ?", (NO_EXT_LABEL, limit)
    ).fetchall()
    total = sum(r["size"] for r in rows) or 1
    return [{"ext": r["ext"], "files": r["files"], "size": r["size"], "share": r["size"] / total} for r in rows]


def group_top(items: list[tuple[str, int]], top: int = 7) -> tuple[list[tuple[str, int]], int]:
    """Оставляет `top` самых крупных, остальное складывает в «прочее». Возвращает (крупные, размер прочего)."""
    ordered = sorted((i for i in items if i[1] > 0), key=lambda i: i[1], reverse=True)
    return ordered[:top], sum(v for _, v in ordered[top:])
