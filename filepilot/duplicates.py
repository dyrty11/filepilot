"""Поиск дубликатов: размер -> хеш первого мегабайта -> полный хеш. Удаление только в корзину."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Callable

from send2trash import send2trash

from .db import forget, get_db

CHUNK = 1 << 20
ProgressCb = Callable[[int, int], None]
CancelCb = Callable[[], bool]


def _hash(path: str, full: bool) -> str | None:
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            if full:
                while chunk := f.read(CHUNK):
                    h.update(chunk)
            else:
                h.update(f.read(CHUNK))
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(min_size: int = 1, on_progress: ProgressCb | None = None,
                    should_cancel: CancelCb | None = None) -> list[dict]:
    """Группы вида {'hash','size','files':[...]}, отсортированы по возможной экономии места."""
    conn = get_db()
    sizes = conn.execute(
        "SELECT size FROM files WHERE size >= ? GROUP BY size HAVING COUNT(*) > 1", (max(min_size, 1),)
    ).fetchall()
    result: list[dict] = []
    for n, srow in enumerate(sizes, 1):
        if should_cancel and should_cancel():
            break
        if on_progress:
            on_progress(n, len(sizes))
        size = srow["size"]
        paths = [r["path"] for r in conn.execute("SELECT path FROM files WHERE size = ?", (size,))]
        by_partial: dict[str, list[str]] = defaultdict(list)
        for p in paths:
            if Path(p).is_file():
                h = _hash(p, full=False)
                if h:
                    by_partial[h].append(p)
        for group in (g for g in by_partial.values() if len(g) > 1):
            by_full: dict[str, list[str]] = defaultdict(list)
            for p in group:
                h = _hash(p, full=True)
                if h:
                    by_full[h].append(p)
            for h, lst in by_full.items():
                if len(lst) > 1:
                    result.append({"hash": h, "size": size, "files": sorted(lst)})
    result.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    return result


def trash_selected(groups: list[list[str]], selected: set[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Отправляет выбранные файлы в корзину, но в каждой группе обязательно оставляет хотя бы один.
    Возвращает (удалённые, [(путь, ошибка)])."""
    done: list[str] = []
    errors: list[tuple[str, str]] = []
    for files in groups:
        chosen = [f for f in files if f in selected]
        if len(chosen) >= len(files):
            chosen = chosen[:-1]  # страховка: последняя копия остаётся
        for f in chosen:
            try:
                send2trash(f)
                done.append(f)
            except Exception as e:  # noqa: BLE001
                errors.append((f, str(e)))
    forget(done)
    return done, errors
