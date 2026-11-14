"""Индексация папок: быстрый обход, пакетная запись, отмена, удаление исчезнувших файлов."""
from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import IGNORED_DIRS, MAX_CONTENT_FILE_BYTES
from .db import get_db
from .extractors import extract_text

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


def walk_files(root: Path, exclude: Iterable[str] = ()) -> Iterable[Path]:
    exclude = [e for e in exclude if e]
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")
                       and not (exclude and is_excluded(os.path.join(dirpath, d), d, exclude))]
        for name in filenames:
            p = Path(dirpath) / name
            if exclude and is_excluded(str(p), name, exclude):
                continue
            if not p.is_symlink():
                yield p


def _under(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("\\/") + os.sep) for r in roots)


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
    files: list[Path] = []
    for r in roots:
        files.extend(walk_files(Path(r), exclude))

    known = {row["path"]: (row["size"] or 0, row["mtime"] or 0.0) for row in conn.execute("SELECT path, size, mtime FROM files")}
    total = len(files)
    added = updated = skipped = errors = 0
    seen: set[str] = set()
    cancelled = False
    now = time.time()
    pending = 0

    for i, path in enumerate(files, 1):
        if should_cancel and should_cancel():
            cancelled = True
            break
        if on_progress:
            on_progress(i, total, str(path))
        sp = str(path)
        seen.add(sp)
        try:
            st = path.stat()
        except OSError:
            errors += 1
            continue
        old = known.get(sp)
        if old is not None and old[0] == st.st_size and abs(old[1] - st.st_mtime) <= 1.0:
            skipped += 1
            continue
        content = extract_text(path) if st.st_size <= MAX_CONTENT_FILE_BYTES else None
        conn.execute(
            """
            INSERT INTO files(path, name, ext, size, mtime, ctime, content, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET name=excluded.name, ext=excluded.ext, size=excluded.size,
                mtime=excluded.mtime, ctime=excluded.ctime, content=excluded.content, indexed_at=excluded.indexed_at
            """,
            (sp, path.name, path.suffix.lower(), st.st_size, st.st_mtime, st.st_ctime, content, now),
        )
        if old is None:
            added += 1
        else:
            updated += 1
        pending += 1
        if pending >= batch:
            conn.commit()
            pending = 0
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
