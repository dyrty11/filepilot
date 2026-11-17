"""Действия с найденными файлами: в корзину, переместить, скопировать, переименовать.

Ничего не удаляется навсегда: «удалить» всегда значит «в корзину». Индекс правится сразу, без повторной индексации."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from send2trash import send2trash

from .db import forget, rename_path
from .rules import unique_path

Errors = list[tuple[str, str]]
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def trash(paths: list[str]) -> tuple[list[str], Errors]:
    """Отправляет файлы в корзину. Уже исчезнувшие с диска просто убираются из индекса."""
    done: list[str] = []
    errors: Errors = []
    for p in paths:
        try:
            if os.path.lexists(p):
                if os.path.isdir(p) and not os.path.islink(p):
                    raise IsADirectoryError("это папка, а не файл")
                send2trash(p)
            done.append(p)
        except Exception as e:  # noqa: BLE001
            errors.append((p, str(e)))
    forget(done)
    return done, errors


def move(paths: list[str], dest_dir: str) -> tuple[list[tuple[str, str]], Errors]:
    """Переносит файлы в папку. Имя при совпадении получает номер: report (1).pdf. Возвращает ([(было, стало)], ошибки)."""
    done: list[tuple[str, str]] = []
    errors: Errors = []
    dest = Path(dest_dir)
    if not dest.is_dir():
        return done, [(dest_dir, "папка назначения не найдена")]
    for p in paths:
        src = Path(p)
        try:
            if not src.is_file():
                raise FileNotFoundError("файл не найден")
            target = unique_path(dest / src.name)
            if src.parent == dest:
                continue  # уже там
            shutil.move(str(src), str(target))
            rename_path(p, str(target))
            done.append((p, str(target)))
        except Exception as e:  # noqa: BLE001
            errors.append((p, str(e)))
    return done, errors


def copy(paths: list[str], dest_dir: str) -> tuple[list[tuple[str, str]], Errors]:
    """Копирует файлы в папку (оригиналы не трогаются). Копии появятся в индексе после следующей индексации."""
    done: list[tuple[str, str]] = []
    errors: Errors = []
    dest = Path(dest_dir)
    if not dest.is_dir():
        return done, [(dest_dir, "папка назначения не найдена")]
    for p in paths:
        src = Path(p)
        try:
            if not src.is_file():
                raise FileNotFoundError("файл не найден")
            target = unique_path(dest / src.name)
            shutil.copy2(str(src), str(target))
            done.append((p, str(target)))
        except Exception as e:  # noqa: BLE001
            errors.append((p, str(e)))
    return done, errors


def check_name(name: str) -> str | None:
    """Текст ошибки, если имя файла недопустимо в Windows, иначе None."""
    if not name.strip():
        return "имя не может быть пустым"
    if _BAD_CHARS.search(name):
        return 'имя не должно содержать символы \\ / : * ? " < > |'
    if name != name.rstrip(" .") or name.lstrip() != name:
        return "имя не может начинаться с пробела или заканчиваться пробелом и точкой"
    if name.split(".")[0].lower() in _RESERVED:
        return "это имя зарезервировано системой"
    return None


def rename(path: str, new_name: str) -> str:
    """Переименовывает файл в его папке. Бросает ValueError с понятным текстом. Возвращает новый путь."""
    err = check_name(new_name)
    if err:
        raise ValueError(err)
    src = Path(path)
    if not src.is_file():
        raise ValueError("файл не найден")
    target = src.with_name(new_name)
    if target == src:
        return path
    if target.exists():
        raise ValueError("файл с таким именем уже есть")
    os.rename(src, target)
    rename_path(path, str(target))
    return str(target)
