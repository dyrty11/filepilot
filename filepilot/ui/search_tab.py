"""Вкладка «Поиск»: поиск по содержимому с фильтрами."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QAbstractTextDocumentLayout, QGuiApplication, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QSpinBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..config import format_time, human_size
from ..search import HL_END, HL_START, Filters, parse_exts, search
from .theme import HIGHLIGHT, open_path, reveal_in_folder


def snippet_to_html(text: str, color: str) -> str:
    """Текст из файла экранируется целиком, подсветка добавляется только по нашим маркерам."""
    safe = html.escape(text or "", quote=False).replace("\n", " ")
    safe = safe.replace(HL_START, f'<b style="color:{HIGHLIGHT}">').replace(HL_END, "</b>")
    return f'<span style="color:{color}">{safe}</span>'


class SnippetDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        raw = index.data(Qt.ItemDataRole.UserRole) or ""
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        color = opt.palette.highlightedText().color().name() if selected else opt.palette.text().color().name()
        doc = QTextDocument()
        doc.setHtml(snippet_to_html(raw, color))
        doc.setDocumentMargin(2)
        painter.save()
        painter.translate(opt.rect.topLeft())
        painter.setClipRect(QRectF(0, 0, opt.rect.width(), opt.rect.height()))
        ctx = QAbstractTextDocumentLayout.PaintContext()
        doc.documentLayout().draw(painter, ctx)
        painter.restore()


class SearchTab(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('Поиск по содержимому, например "договор 2024" (кавычки: точная фраза)')
        self.query.setClearButtonEnabled(True)
        self.btn = QPushButton("Найти")
        self.btn.setObjectName("primary")
        row.addWidget(self.query, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)

        self.filters_box = QGroupBox("Фильтры")
        self.filters_box.setCheckable(True)
        self.filters_box.setChecked(settings.filters_enabled)
        fl = QHBoxLayout(self.filters_box)
        self.ext = QLineEdit()
        self.ext.setPlaceholderText("pdf, docx, txt")
        self.ext.setMaximumWidth(190)
        self.min_kb = self._spin("—")
        self.max_kb = self._spin("—")
        self.older = self._spin("—")
        for text, w in (("Расширения:", self.ext), ("Мин. КБ:", self.min_kb), ("Макс. КБ:", self.max_kb), ("Старше (дн.):", self.older)):
            fl.addWidget(QLabel(text))
            fl.addWidget(w)
        fl.addStretch(1)
        lay.addWidget(self.filters_box)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Путь", "Размер", "Изменён", "Фрагмент"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegateForColumn(3, SnippetDelegate(self.table))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 380)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 130)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lay.addWidget(self.table, 1)
        self.info = QLabel("Добавьте папки и нажмите «Индексировать», затем введите запрос.")
        lay.addWidget(self.info)

        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(self.run_search)
        self.query.textChanged.connect(lambda _: self._timer.start())
        self.query.returnPressed.connect(self.run_search)
        self.btn.clicked.connect(self.run_search)
        for w in (self.ext,):
            w.textChanged.connect(lambda _: self._timer.start())
        for w in (self.min_kb, self.max_kb, self.older):
            w.valueChanged.connect(lambda _: self._timer.start())
        self.filters_box.toggled.connect(self._on_filters_toggled)
        self.table.doubleClicked.connect(lambda *_: self.open_selected())
        self.table.customContextMenuRequested.connect(self._menu)

    @staticmethod
    def _spin(special: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(0, 10_000_000)
        s.setSpecialValueText(special)
        s.setMaximumWidth(110)
        return s

    def _on_filters_toggled(self, on: bool) -> None:
        self.settings.filters_enabled = on
        self._timer.start()

    def current_filters(self) -> Filters:
        if not self.filters_box.isChecked():
            return Filters()
        return Filters(exts=parse_exts(self.ext.text()), min_kb=self.min_kb.value() or None,
                       max_kb=self.max_kb.value() or None, older_days=self.older.value() or None)

    def run_search(self) -> None:
        self._timer.stop()
        res = search(self.query.text(), self.current_filters())
        self.table.setRowCount(len(res))
        for r, item in enumerate(res):
            path_item = QTableWidgetItem(item["path"])
            path_item.setToolTip(item["path"])
            size_item = QTableWidgetItem(human_size(item["size"]))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            snip = QTableWidgetItem("")
            snip.setData(Qt.ItemDataRole.UserRole, item["snippet"] or "")
            for c, it in enumerate((path_item, size_item, QTableWidgetItem(format_time(item["mtime"])), snip)):
                self.table.setItem(r, c, it)
        if not self.query.text().strip() and not self.current_filters().active():
            self.info.setText("Введите запрос или задайте фильтры.")
        else:
            self.info.setText(f"Найдено: {len(res)}" + (" (показаны первые 300)" if len(res) >= 300 else ""))

    def selected_path(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).text() if rows else None

    def open_selected(self) -> None:
        p = self.selected_path()
        if p and Path(p).exists():
            open_path(p)
        elif p:
            self.info.setText("Файл не найден: возможно, он удалён. Нажмите «Индексировать».")

    def _menu(self, pos) -> None:
        p = self.selected_path()
        if not p:
            return
        m = QMenu(self)
        m.addAction("Открыть", self.open_selected)
        m.addAction("Показать в папке", lambda: reveal_in_folder(p))
        m.addAction("Копировать путь", lambda: QGuiApplication.clipboard().setText(p))
        m.exec(self.table.viewport().mapToGlobal(pos))
