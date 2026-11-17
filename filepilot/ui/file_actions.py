"""Действия с выбранными файлами в таблицах: в корзину, переместить, копировать, переименовать."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMenu, QMessageBox, QWidget

from .. import fileops
from ..config import human_size
from ..i18n import tr
from .theme import open_path, reveal_in_folder


def _report(done_text: str, errors) -> str:
    if not errors:
        return done_text
    return done_text + " " + tr('Ошибок: {0}. Первая: {1}').format(len(errors), errors[0][1])


def trash_dialog(parent: QWidget, paths: list[str], on_done: Callable[[str], None]) -> None:
    if not paths:
        return
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    names = "\n".join(os.path.basename(p) for p in paths[:5]) + ("\n…" if len(paths) > 5 else "")
    box = QMessageBox(QMessageBox.Icon.Question, "FilePilot",
                      tr('Отправить в корзину файлов: {0} ({1})?').format(len(paths), human_size(total)) +
                      "\n\n" + names + "\n\n" + tr("Файлы можно будет вернуть из корзины."),
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    if box.exec() != QMessageBox.StandardButton.Yes:
        return
    done, errors = fileops.trash(paths)
    on_done(_report(tr('В корзину отправлено: {0}.').format(len(done)), errors))


def transfer_dialog(parent: QWidget, paths: list[str], on_done: Callable[[str], None], copy: bool) -> None:
    if not paths:
        return
    start = str(Path(paths[0]).parent)
    dest = QFileDialog.getExistingDirectory(parent, tr("Копировать в папку") if copy else tr("Переместить в папку"), start)
    if not dest:
        return
    done, errors = (fileops.copy if copy else fileops.move)(paths, dest)
    text = tr('Скопировано: {0} → {1}.') if copy else tr('Перемещено: {0} → {1}.')
    on_done(_report(text.format(len(done), dest), errors))


def rename_dialog(parent: QWidget, path: str, on_done: Callable[[str], None]) -> None:
    name, ok = QInputDialog.getText(parent, tr("Переименовать"), tr("Новое имя файла:"), QLineEdit.EchoMode.Normal, os.path.basename(path))
    if not ok or name == os.path.basename(path):
        return
    try:
        new = fileops.rename(path, name)
    except (ValueError, OSError) as e:
        QMessageBox.warning(parent, "FilePilot", tr('Не удалось переименовать: {0}').format(e))
        return
    on_done(tr('Переименовано: {0}').format(os.path.basename(new)))


def fill_menu(menu: QMenu, parent: QWidget, paths: list[str], on_done: Callable[[str], None]) -> None:
    """Добавляет в меню действия для выбранных файлов (один или несколько)."""
    one = paths[0] if len(paths) == 1 else None
    if one:
        menu.addAction(tr("Открыть"), lambda: open_path(one) if Path(one).exists() else on_done(tr("Файл не найден: возможно, он удалён. Нажмите «Индексировать».")))
        menu.addAction(tr("Показать в папке"), lambda: reveal_in_folder(one))
        menu.addSeparator()
    menu.addAction(tr("Переместить в папку…"), lambda: transfer_dialog(parent, paths, on_done, copy=False))
    menu.addAction(tr("Копировать в папку…"), lambda: transfer_dialog(parent, paths, on_done, copy=True))
    if one:
        menu.addAction(tr("Переименовать…"), lambda: rename_dialog(parent, one, on_done))
    menu.addSeparator()
    menu.addAction(tr("В корзину…") if len(paths) == 1 else tr('В корзину ({0})…').format(len(paths)), lambda: trash_dialog(parent, paths, on_done))
