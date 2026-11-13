"""Вкладка «Карта диска»: крупные файлы, папки и типы файлов."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QRadioButton, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import tr
from .. import diskmap
from ..config import format_time, human_size
from .theme import ACCENT, reveal_in_folder


class BarDelegate(QStyledItemDelegate):
    """Рисует на фоне ячейки полосу, длина которой равна доле (хранится в UserRole)."""

    def paint(self, painter, option, index):
        share = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(share, float):
            r = option.rect.adjusted(1, 2, -1, -2)
            c = QColor(ACCENT)
            c.setAlpha(90)
            painter.fillRect(QRect(r.left(), r.top(), int(r.width() * min(share, 1.0)), r.height()), c)
        super().paint(painter, option, index)


def _loc(name: str) -> str:
    """Служебные подписи из diskmap.py показываем на выбранном языке."""
    return name.replace(tr("(файлы в корне)"), tr(tr("(файлы в корне)"))).replace(tr("(без расширения)"), tr(tr("(без расширения)")))


class DiskMapTab(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.modes = {}
        for key, label in (("files", tr("Крупные файлы")), ("folders", tr("Папки")), ("types", tr("Типы файлов"))):
            rb = QRadioButton(label)
            self.group.addButton(rb)
            self.modes[key] = rb
            row.addWidget(rb)
        row.addStretch(1)
        lay.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(1, BarDelegate(self.table))
        self.table.doubleClicked.connect(self._reveal)
        lay.addWidget(self.table, 1)
        self.info = QLabel("")
        lay.addWidget(self.info)
        self.modes["files"].setChecked(True)
        for rb in self.modes.values():  # подключаем после создания таблицы
            rb.toggled.connect(lambda on: on and self.refresh())
        self.refresh()

    def _fill(self, headers, rows, stretch_col=0, size_col=1):
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        hh = self.table.horizontalHeader()
        for c in range(len(headers)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
        for r, cells in enumerate(rows):
            for c, (text, share) in enumerate(cells):
                it = QTableWidgetItem(text)
                if share is not None:
                    it.setData(Qt.ItemDataRole.UserRole, share)
                if c == size_col:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, it)

    def refresh(self) -> None:
        if self.modes["files"].isChecked():
            data = diskmap.top_files(200)
            top = data[0]["size"] if data else 1
            self._fill([tr("Файл"), tr("Размер"), tr("Изменён")], [[(d["path"], None), (human_size(d["size"]), d["size"] / (top or 1)), (format_time(d["mtime"]), None)] for d in data])
            self.info.setText(tr('Показано файлов: {0} (самые крупные). Двойной щелчок покажет файл в папке.').format(len(data)))
        elif self.modes["folders"].isChecked():
            data = diskmap.by_folder(self.settings.folders)
            self._fill([tr("Папка"), tr("Размер"), tr("Файлов"), tr("Доля")], [[(_loc(d["folder"]), None), (human_size(d["size"]), d["share"]), (str(d["files"]), None), (f"{d['share'] * 100:.1f}%", None)] for d in data])
            self.info.setText(tr("Размер по папкам первого уровня внутри добавленных папок.") if data else tr("Добавьте папки и проиндексируйте их."))
        else:
            data = diskmap.by_type()
            self._fill([tr("Тип"), tr("Размер"), tr("Файлов"), tr("Доля")], [[(_loc(d["ext"]), None), (human_size(d["size"]), d["share"]), (str(d["files"]), None), (f"{d['share'] * 100:.1f}%", None)] for d in data])
            self.info.setText(tr("Какие типы файлов занимают больше всего места."))

    def _reveal(self, *_):
        if not self.modes["files"].isChecked():
            return
        rows = self.table.selectionModel().selectedRows()
        if rows:
            reveal_in_folder(self.table.item(rows[0].row(), 0).text())
