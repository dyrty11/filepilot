"""SQLite + FTS5. Соединение на каждый поток: индексатор работает в фоне, интерфейс читает параллельно."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from .config import db_path, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY,
    path       TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    ext        TEXT,
    size       INTEGER,
    mtime      REAL,
    ctime      REAL,
    content    TEXT,
    indexed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_files_ext   ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_size  ON files(size);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    name, content, content='files', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name, content) VALUES (new.id, new.name, new.content);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, content) VALUES ('delete', old.id, old.name, old.content);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, content) VALUES ('delete', old.id, old.name, old.content);
    INSERT INTO files_fts(rowid, name, content) VALUES (new.id, new.name, new.content);
END;
"""

_local = threading.local()


def get_db() -> sqlite3.Connection:
    path = str(db_path())
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != path:
        if conn is not None:
            conn.close()
        ensure_dirs()
        conn = sqlite3.connect(path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _local.conn, _local.path = conn, path
    return conn


def close_db() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.path = None


@contextmanager
def transaction():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def forget(paths: list[str]) -> None:
    """Убрать файлы из индекса (после удаления или переноса)."""
    if not paths:
        return
    with transaction() as c:
        c.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in paths])


def clear_index() -> int:
    """Очистить индекс целиком. Возвращает число удалённых записей."""
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    with transaction() as c:
        c.execute("DELETE FROM files")
    conn.execute("INSERT INTO files_fts(files_fts) VALUES('optimize')")
    conn.commit()
    return n


def stats() -> dict:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS total FROM files").fetchone()
    return {"files": row["n"], "bytes": row["total"]}
