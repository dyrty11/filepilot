"""Поиск дубликатов: размер -> хеш первого мегабайта -> полный хеш. Удаление только в корзину."""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable

from send2trash import send2trash

from . import native
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


def _find_native(min_size: int, on_progress: ProgressCb | None, should_cancel: CancelCb | None, same_ext: bool = True) -> list[dict]:
    """То же, что `find_duplicates`, но хеши считает Rust-ядро: параллельно по всем ядрам процессора."""
    nat = native.module()
    conn = get_db()
    # группа кандидатов: размер (и расширение, если не просили искать среди разных форматов)
    by_size: dict[tuple[int, str], list[str]] = defaultdict(list)
    for r in conn.execute(
        "SELECT size, ext, path FROM files WHERE size IN (SELECT size FROM files WHERE size >= ? GROUP BY size HAVING COUNT(*) > 1)",
        (max(min_size, 1),),
    ):
        by_size[(r["size"], (r["ext"] or "") if same_ext else "")].append(r["path"])
    by_size = {k: v for k, v in by_size.items() if len(v) > 1}
    sizes = list(by_size)
    ext_of = {p: k[1] for k, ps in by_size.items() for p in ps}
    result: list[dict] = []
    done = 0
    i = 0
    while i < len(sizes):
        if should_cancel and should_cancel():
            break
        # пачка размеров примерно на 2000 файлов: хватает для загрузки всех ядер, а отмена и прогресс остаются живыми
        chunk: list[int] = []
        n = 0
        while i < len(sizes) and (not chunk or n < 2000):
            chunk.append(sizes[i])
            n += len(by_size[sizes[i]])
            i += 1
        flat = [(sz[0], p) for sz in chunk for p in by_size[sz]]
        partial = nat.hash_many([p for _, p in flat], False)
        groups: dict[tuple[int, str, str], list[str]] = defaultdict(list)
        for (sz, p), h in zip(flat, partial):
            if h:
                groups[(sz, ext_of[p], h)].append(p)
        cand = [(k[0], p) for k, v in groups.items() if len(v) > 1 for p in v]
        full = nat.hash_many([p for _, p in cand], True)
        final: dict[tuple[int, str, str], list[str]] = defaultdict(list)
        for (sz, p), h in zip(cand, full):
            if h:
                final[(sz, ext_of[p], h)].append(p)
        for (sz, _ext, h), lst in final.items():
            if len(lst) > 1:
                result.append({"hash": h, "size": sz, "files": sorted(lst)})
        done += len(chunk)
        if on_progress:
            on_progress(done, len(sizes))
    result.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    return result


def find_duplicates(min_size: int = 1, on_progress: ProgressCb | None = None,
                    should_cancel: CancelCb | None = None, same_ext: bool = True) -> list[dict]:
    """Группы вида {'hash','size','files':[...]}, отсортированы по возможной экономии места.
    По умолчанию сравниваются только файлы с одинаковым расширением: test.exe и test.bat с одинаковыми
    байтами дубликатами не считаются. same_ext=False ищет копии независимо от формата."""
    if native.available():
        return _find_native(min_size, on_progress, should_cancel, same_ext)
    conn = get_db()
    ecol = "ext" if same_ext else "''"
    sizes = conn.execute(
        f"SELECT size, {ecol} AS e FROM files WHERE size >= ? GROUP BY size, {ecol} HAVING COUNT(*) > 1", (max(min_size, 1),)
    ).fetchall()
    result: list[dict] = []
    for n, srow in enumerate(sizes, 1):
        if should_cancel and should_cancel():
            break
        if on_progress:
            on_progress(n, len(sizes))
        size = srow["size"]
        if same_ext:
            paths = [r["path"] for r in conn.execute("SELECT path FROM files WHERE size = ? AND ext IS ?", (size, srow["e"]))]
        else:
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


def export_csv(groups: list[dict], dest: str) -> int:
    """Одна строка на файл: номер группы, число копий, размер в байтах, путь. Возвращает число строк."""
    from .exporting import write_csv
    from .i18n import tr
    rows = [(i, len(g["files"]), g["size"], p) for i, g in enumerate(groups, 1) for p in g["files"]]
    return write_csv([tr("Группа"), tr("Копий"), tr("Размер, байт"), tr("Путь")], rows, dest)


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


KEEP_RULES = ("first", "oldest", "newest", "shortest")


def choose_keep(files: list[str], rule: str = "first") -> str:
    """Какую копию оставить. first — первая по алфавиту, oldest/newest — по дате изменения,
    shortest — с самым коротким путём. При равенстве (или недоступном файле) выбирается первая по алфавиту."""
    ordered = sorted(files)

    def mtime(p: str) -> float:
        try:
            return os.stat(p).st_mtime
        except OSError:
            return float("inf")  # недоступный файл не выбираем как «оставить»

    if rule == "oldest":
        return min(ordered, key=mtime)
    if rule == "newest":
        return max(ordered, key=lambda p: (mtime(p) if mtime(p) != float("inf") else -1.0))
    if rule == "shortest":
        return min(ordered, key=len)
    return ordered[0]
