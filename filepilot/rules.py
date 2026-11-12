"""Правила сортировки: перенос, архивация (zip) и отправка в корзину. Постоянного удаления нет намеренно."""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from send2trash import send2trash

from .config import ensure_dirs, rules_path
from .db import forget, get_db

ACTIONS = ("move", "archive", "trash")
ACTION_LABELS = {"move": "Переместить", "archive": "Архивировать (zip)", "trash": "В корзину"}


@dataclass
class Rule:
    name: str
    action: str = "move"
    folder: str | None = None
    ext: list[str] = field(default_factory=list)
    older_than_days: int | None = None
    pattern: str | None = None
    dest: str | None = None
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"name": self.name, "action": self.action, "folder": self.folder, "ext": list(self.ext),
                "older_than_days": self.older_than_days, "pattern": self.pattern, "dest": self.dest,
                "enabled": self.enabled}

    def validate(self) -> str | None:
        """Текст ошибки или None, если правило корректно."""
        if not self.name.strip():
            return "Укажите имя правила."
        if self.action not in ACTIONS:
            return "Неизвестное действие."
        if not self.folder:
            return "Укажите папку-источник."
        if self.action in ("move", "archive") and not self.dest:
            return "Укажите папку назначения."
        if not (self.ext or self.pattern or self.older_than_days):
            return "Задайте хотя бы одно условие: расширения, шаблон имени или возраст файла."
        return None


def load_rules() -> list[Rule]:
    try:
        data = json.loads(rules_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rules = []
    for item in data.get("rules", []) if isinstance(data, dict) else []:
        try:
            rules.append(Rule(**{k: v for k, v in item.items() if k in Rule.__dataclass_fields__}))
        except TypeError:
            continue
    return rules


def save_rules(rules: list[Rule]) -> None:
    ensure_dirs()
    p = rules_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"rules": [r.to_dict() for r in rules]}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _norm_exts(exts: list[str]) -> set[str]:
    return {(e if e.startswith(".") else "." + e).lower() for e in exts if e}


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def matches(rule: Rule, row) -> bool:
    path = Path(row["path"])
    if rule.folder and not _inside(path, Path(rule.folder).expanduser()):
        return False
    if rule.dest and rule.action != "trash" and _inside(path, Path(rule.dest).expanduser()):
        return False  # файл уже лежит в папке назначения
    if rule.ext and path.suffix.lower() not in _norm_exts(rule.ext):
        return False
    if rule.pattern and not fnmatch.fnmatchcase(path.name.lower(), rule.pattern.lower()):
        return False
    if rule.older_than_days is not None and (time.time() - (row["mtime"] or 0)) / 86400 < rule.older_than_days:
        return False
    return True


def plan(rule: Rule) -> list[dict]:
    rows = get_db().execute("SELECT path, name, size, mtime FROM files").fetchall()
    return [dict(r) for r in rows if matches(rule, r)]


def unique_path(path: Path) -> Path:
    """Свободное имя рядом: report.pdf -> report (1).pdf. Существующие файлы не затираются."""
    if not path.exists():
        return path
    i = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _destination(rule: Rule, src: Path) -> Path | None:
    if rule.action == "move" and rule.dest:
        return Path(rule.dest).expanduser() / src.name
    if rule.action == "archive" and rule.dest:
        return Path(rule.dest).expanduser() / f"{src.name}.zip"
    return None


def apply(rule: Rule, dry_run: bool = True, on_progress: Callable[[int, int], None] | None = None,
          should_cancel: Callable[[], bool] | None = None) -> list[dict]:
    """Выполняет правило. В пробном режиме ничего не меняет, а только возвращает план действий."""
    err = rule.validate()
    if err:
        raise ValueError(err)
    items = plan(rule)
    actions: list[dict] = []
    changed: list[str] = []
    for i, item in enumerate(items, 1):
        if should_cancel and should_cancel():
            break
        if on_progress:
            on_progress(i, len(items))
        src = Path(item["path"])
        if not src.exists():
            continue
        dst = _destination(rule, src)
        entry = {"file": str(src), "action": rule.action, "dest": str(dst) if dst else None, "size": item["size"]}
        try:
            if not dry_run:
                if rule.action == "trash":
                    send2trash(str(src))
                elif rule.action == "move":
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst = unique_path(dst)
                    shutil.move(str(src), str(dst))
                    entry["dest"] = str(dst)
                elif rule.action == "archive":
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst = unique_path(dst)
                    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
                        z.write(src, arcname=src.name)
                    send2trash(str(src))
                    entry["dest"] = str(dst)
                changed.append(str(src))
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)
        actions.append(entry)
    if changed:
        forget(changed)
    return actions
