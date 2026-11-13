"""Диалог «Папки»: какие папки индексируются."""
from __future__ import annotations
from ..i18n import tr

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout


class FoldersDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Папки для индексации"))
        self.resize(560, 360)
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
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        lay.addWidget(bb)
        add.clicked.connect(self._add)
        rem.clicked.connect(self._remove)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        self.list.addItems(self.settings.folders)

    def _add(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Выберите папку"))
        if d and self.settings.add_folder(d):
            self._fill()

    def _remove(self) -> None:
        for it in self.list.selectedItems():
            self.settings.remove_folder(it.text())
        self._fill()
