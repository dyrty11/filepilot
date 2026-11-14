"""Диалог «Папки»: какие папки индексируются и что исключается."""
from __future__ import annotations
from ..i18n import tr

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QPushButton, QVBoxLayout)


class FoldersDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Папки для индексации"))
        self.resize(600, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Эти папки будут просмотрены при индексации (вместе с подпапками):")))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        add, rem = QPushButton(tr("Добавить…")), QPushButton(tr("Убрать"))
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)

        hint = QLabel(tr("Исключения: папка целиком или маска имени (node_modules, *.tmp, ~$*). Применяются при следующей индексации."))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.ex_list = QListWidget()
        lay.addWidget(self.ex_list, 1)
        row2 = QHBoxLayout()
        ex_folder, ex_mask, ex_rem = QPushButton(tr("Папка…")), QPushButton(tr("Маска…")), QPushButton(tr("Убрать"))
        for b in (ex_folder, ex_mask, ex_rem):
            row2.addWidget(b)
        row2.addStretch(1)
        lay.addLayout(row2)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        lay.addWidget(bb)
        add.clicked.connect(self._add)
        rem.clicked.connect(self._remove)
        ex_folder.clicked.connect(self._add_ex_folder)
        ex_mask.clicked.connect(self._add_ex_mask)
        ex_rem.clicked.connect(self._remove_ex)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        self.list.addItems(self.settings.folders)
        self.ex_list.clear()
        self.ex_list.addItems(self.settings.exclude)

    def _add(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Выберите папку"))
        if d and self.settings.add_folder(d):
            self._fill()

    def _remove(self) -> None:
        for it in self.list.selectedItems():
            self.settings.remove_folder(it.text())
        self._fill()

    def _add_ex_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Выберите папку"))
        if d:
            import os
            if self.settings.add_exclude(os.path.normpath(d)):
                self._fill()

    def _add_ex_mask(self) -> None:
        text, ok = QInputDialog.getText(self, tr("Исключить по маске"), tr("Маска имени (например node_modules или *.tmp):"))
        if ok and self.settings.add_exclude(text):
            self._fill()

    def _remove_ex(self) -> None:
        for it in self.ex_list.selectedItems():
            self.settings.remove_exclude(it.text())
        self._fill()
