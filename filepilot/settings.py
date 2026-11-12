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
    saved_searches: list[dict] = field(default_factory=list)  # {name, query, exts, min_kb, max_kb, older}

    def save_search(self, entry: dict) -> None:
        self.saved_searches = [e for e in self.saved_searches if e.get("name") != entry["name"]] + [entry]

    def delete_search(self, name: str) -> None:
        self.saved_searches = [e for e in self.saved_searches if e.get("name") != name]

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
    return Settings(
        folders=[str(f) for f in folders] if isinstance(folders, list) else [],
        auto_index=bool(data.get("auto_index", False)),
        filters_enabled=bool(data.get("filters_enabled", False)),
        saved_searches=[e for e in (data.get("saved_searches") or []) if isinstance(e, dict) and e.get("name")],
    )


def save_settings(s: Settings) -> None:
    ensure_dirs()
    p = settings_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # атомарная запись: файл не повредится при сбое
