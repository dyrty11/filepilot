"""Индексация папок: быстрый обход, пакетная запись, отмена, удаление исчезнувших файлов."""
from __future__ import annotations

import fnmatch
import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import (
    ATTR_OFFLINE_MASK, DRIVE_ROOT_SKIP, IGNORED_DIRS, MAX_CONTENT_FILE_BYTES, NOISY_DIRS,
)
from .db import get_db
from . import native
from .extractors import extract_many

ProgressCb = Callable[[int, int, str], None]
CancelCb = Callable[[], bool]


def _is_path_pattern(pattern: str) -> bool:
    return "/" in pattern or "\\" in pattern or ":" in pattern


def is_excluded(path: str, name: str, patterns: Iterable[str]) -> bool:
    """Исключение: либо путь папки/файла (всё внутри пропускается), либо маска имени без путей (node_modules, *.tmp, ~$*)."""
    full = os.path.normcase(os.path.normpath(path))
    low = name.lower()
    for pat in patterns:
        if _is_path_pattern(pat):
            base = os.path.normcase(os.path.normpath(pat))
            if full == base or full.startswith(base.rstrip("\\/") + os.sep):
                return True
        elif fnmatch.fnmatchcase(low, pat.lower()):
            return True
    return False


def _is_drive_root(path: str) -> bool:
    p = Path(path)
    return p.parent == p


def _skip_dir(entry: os.DirEntry, at_drive_root: bool) -> bool:
    low = entry.name.lower()
    if low in NOISY_DIRS or (at_drive_root and low in DRIVE_ROOT_SKIP):
        return True
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)
        return bool(is_junction and is_junction())  # junction легко зациклить: не заходим
    except OSError:
        return True


def scan(root: str, exclude: Iterable[str] = ()):
    """Обходит папку без лишних обращений к диску: размер и даты берутся из самого обхода (на Windows бесплатно).
    Отдаёт кортежи (путь, имя, размер, mtime, ctime, облачная_заглушка)."""
    exclude = [e for e in exclude if e]
    stack = [root]
    drive_root = _is_drive_root(root)
    while stack:
        cur = stack.pop()
        at_root = drive_root and cur == root
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for entry in it:
                name = entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name in IGNORED_DIRS or name.startswith(".") or _skip_dir(entry, at_root):
                            continue
                        if exclude and is_excluded(entry.path, name, exclude):
                            continue
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        if exclude and is_excluded(entry.path, name, exclude):
                            continue
                        st = entry.stat(follow_symlinks=False)
                        cloud = bool(getattr(st, "st_file_attributes", 0) & ATTR_OFFLINE_MASK)
                        yield entry.path, name, st.st_size, st.st_mtime, st.st_ctime, cloud
                except OSError:
                    continue


def walk_files(root: Path, exclude: Iterable[str] = ()) -> Iterable[Path]:
    for p, *_ in scan(str(root), exclude):
        yield Path(p)


def lower_priority() -> None:
    """Фоновая индексация не должна тормозить компьютер: на Windows понижаем приоритет текущего потока."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentThread.restype = ctypes.c_void_p
        k.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k.SetThreadPriority(k.GetCurrentThread(), -1)  # THREAD_PRIORITY_BELOW_NORMAL
    except Exception:
        pass


def _under(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("\\/") + os.sep) for r in roots)


def _python_batches(root: str, exclude: Iterable[str], size: int = 500):
    batch: list = []
    for item in scan(root, exclude):
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class _NativeBatches:
    """Параллельный обход в Rust: пачки приходят по мере чтения диска."""

    def __init__(self, root: str, exclude: Iterable[str]) -> None:
        patterns = [e for e in exclude if e]
        paths = [os.path.normcase(os.path.normpath(e)) for e in patterns if _is_path_pattern(e)]
        names = [e for e in patterns if not _is_path_pattern(e)]
        self.scanner = native.module().Scanner(
            root, paths, names, sorted(IGNORED_DIRS), sorted(NOISY_DIRS), sorted(DRIVE_ROOT_SKIP), sys.platform == "win32")

    def __iter__(self):
        while True:
            batch = self.scanner.next_batch(2000, 100)
            if batch is None:
                return
            yield batch  # пустая пачка = пауза в обходе: даём вызывающему проверить отмену

    def cancel(self) -> None:
        self.scanner.cancel()


def index_folders(
    folders: list[str],
    on_progress: ProgressCb | None = None,
    should_cancel: CancelCb | None = None,
    batch: int = 200,
    exclude: Iterable[str] = (),
) -> dict:
    """Индексирует папки. Возвращает статистику; при отмене ставит cancelled=True и ничего не удаляет."""
    conn = get_db()
    roots = [str(Path(f).expanduser()) for f in folders if Path(f).expanduser().is_dir()]
    known = {row["path"]: (row["size"] or 0, row["mtime"] or 0.0) for row in conn.execute("SELECT path, size, mtime FROM files")}
    # Сколько файлов ждём: по прошлому индексу. При первом проходе число неизвестно (0): строка прогресса бегущая.
    estimate = sum(1 for p in known if _under(p, roots))
    added = updated = skipped = errors = 0
    seen: set[str] = set()
    cancelled = False
    now = time.time()
    count = 0
    last_emit = 0.0
    use_native = native.available()
    upsert = """
        INSERT INTO files(path, name, ext, size, mtime, ctime, content, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET name=excluded.name, ext=excluded.ext, size=excluded.size,
            mtime=excluded.mtime, ctime=excluded.ctime, content=excluded.content, indexed_at=excluded.indexed_at
        """

    for root in roots:
        batches = _NativeBatches(root, exclude) if use_native else _python_batches(root, exclude)
        for items in batches:
            if should_cancel and should_cancel():
                cancelled = True
                if use_native:
                    batches.cancel()
                break
            todo = []
            for it in items:
                sp, size, mtime = it[0], it[2], it[3]
                count += 1
                seen.add(sp)
                old = known.get(sp)
                if old is not None and old[0] == size and abs(old[1] - mtime) <= 1.0:
                    skipped += 1
                else:
                    todo.append((it, old is None))
            if on_progress and items:
                t_now = time.monotonic()
                if t_now - last_emit >= 0.1:  # не заваливаем интерфейс миллионами сигналов
                    last_emit = t_now
                    on_progress(count, max(estimate, count) if estimate else 0, items[-1][0])
            if not todo:
                continue
            # заглушки облака не читаем: это запустило бы скачивание
            readable = [i for i, ((_, _, size, _, _, cloud), _) in enumerate(todo) if not cloud and size <= MAX_CONTENT_FILE_BYTES]
            texts = extract_many([todo[i][0][0] for i in readable])
            content = dict(zip(readable, texts))
            rows = []
            for i, ((sp, name, size, mtime, ctime, _cloud), is_new) in enumerate(todo):
                rows.append((sp, name, os.path.splitext(name)[1].lower(), size, mtime, ctime, content.get(i), now))
                if is_new:
                    added += 1
                else:
                    updated += 1
            conn.executemany(upsert, rows)
            conn.commit()
        if cancelled:
            break
    total = count
    if on_progress:
        on_progress(count, count, "")
    conn.commit()

    removed = 0
    if not cancelled:
        gone = [p for p in known if p not in seen and _under(p, roots)]
        for k in range(0, len(gone), 500):
            conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in gone[k:k + 500]])
        conn.commit()
        removed = len(gone)

    return {"total": total, "added": added, "updated": updated, "skipped": skipped,
            "removed": removed, "errors": errors, "cancelled": cancelled}
