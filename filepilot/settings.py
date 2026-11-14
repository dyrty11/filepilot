"""Настройки пользователя: список папок, автоиндексация, последние фильтры."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .config import ensure_dirs, settings_path


@dataclass
class Settings:
    folders: list[str] = field(default_factory=list)
    auto_index: bool = False
    filters_enabled: bool = False
    language: str = "auto"  # auto | ru | en
    reindex_minutes: int = 0  # фоновое обновление индекса: 0 (выкл.), 15, 60, 360
    check_updates: bool = True
    last_update_check: float = 0.0
    skipped_version: str = ""
    last_seen_version: str = ""  # версия, при последнем запуске которой показали «Что нового»
    saved_searches: list[dict] = field(default_factory=list)  # {name, query, exts, min_kb, max_kb, older, folder}
    exclude: list[str] = field(default_factory=list)  # исключения индексации: путь папки или маска имени (node_modules, *.tmp)

    def save_search(self, entry: dict) -> None:
        self.saved_searches = [e for e in self.saved_searches if e.get("name") != entry["name"]] + [entry]

    def delete_search(self, name: str) -> None:
        self.saved_searches = [e for e in self.saved_searches if e.get("name") != name]

    def add_exclude(self, pattern: str) -> bool:
        pattern = pattern.strip()
        if not pattern or pattern in self.exclude:
            return False
        self.exclude.append(pattern)
        return True

    def remove_exclude(self, pattern: str) -> bool:
        if pattern in self.exclude:
            self.exclude.remove(pattern)
            return True
        return False

    def add_folder(self, folder: str) -> bool:
        folder = os.path.normpath(folder)
        if folder in self.folders:
            return False
        self.folders.append(folder)
        return True

    def remove_folder(self, folder: str) -> bool:
        folder = os.path.normpath(folder)
        if folder in self.folders:
            self.folders.remove(folder)
            return True
        return False


def load_settings() -> Settings:
    p = settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    folders = data.get("folders")
    exclude = data.get("exclude")
    return Settings(
        folders=[str(f) for f in folders] if isinstance(folders, list) else [],
        auto_index=bool(data.get("auto_index", False)),
        filters_enabled=bool(data.get("filters_enabled", False)),
        language=data.get("language") if data.get("language") in ("ru", "en") else "auto",
        reindex_minutes=data.get("reindex_minutes") if data.get("reindex_minutes") in (15, 60, 360) else 0,
        check_updates=bool(data.get("check_updates", True)),
        last_update_check=float(data.get("last_update_check") or 0) if isinstance(data.get("last_update_check"), (int, float)) else 0.0,
        skipped_version=str(data.get("skipped_version") or ""),
        last_seen_version=str(data.get("last_seen_version") or ""),
        exclude=[str(x).strip() for x in exclude if str(x).strip()] if isinstance(exclude, list) else [],
        saved_searches=[e for e in (data.get("saved_searches") or []) if isinstance(e, dict) and e.get("name")],
    )


def save_settings(s: Settings) -> None:
    ensure_dirs()
    p = settings_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # атомарная запись: файл не повредится при сбое
