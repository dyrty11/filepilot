"""Вкладка «Поиск»: поиск по содержимому с фильтрами."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QAbstractTextDocumentLayout, QGuiApplication, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox, QInputDialog, QMessageBox, QSplitter, QTextBrowser, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QSpinBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..i18n import tr
from ..config import format_time, human_size
from ..search import HL_END, HL_START, Filters, export_csv, get_content, mark_matches, parse_exts, search
from ..settings import save_settings
from .theme import HIGHLIGHT, open_path, reveal_in_folder


def snippet_to_html(text: str, color: str) -> str:
    """Текст из файла экранируется целиком, подсветка добавляется только по нашим маркерам."""
    safe = html.escape(text or "", quote=False).replace("\n", " ")
    safe = safe.replace(HL_START, f'<b style="color:{HIGHLIGHT}">').replace(HL_END, "</b>")
    return f'<span style="color:{color}">{safe}</span>'


def preview_to_html(text: str, query: str) -> tuple[str, int]:
    """Полный текст файла с подсветкой. Всё экранируется, подсветка — только по нашим маркерам."""
    marked, n = mark_matches(text, query)
    safe = html.escape(marked, quote=False)
    safe = safe.replace(HL_START, f'<a name="m"></a><b style="color:{HIGHLIGHT}">', 1) if n else safe
    safe = safe.replace(HL_START, f'<b style="color:{HIGHLIGHT}">').replace(HL_END, "</b>")
    return f'<div style="white-space:pre-wrap">{safe}</div>', n


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
        self.query.setPlaceholderText(tr('Поиск по содержимому, например "договор 2024" (кавычки: точная фраза)'))
        self.query.setClearButtonEnabled(True)
        self.btn = QPushButton(tr("Найти"))
        self.btn.setObjectName("primary")
        row.addWidget(self.query, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)

        saved = QHBoxLayout()
        self.saved = QComboBox()
        self.saved.setMinimumWidth(220)
        self.btn_save = QPushButton(tr("Сохранить поиск"))
        self.btn_del = QPushButton(tr("Удалить"))
        self.btn_csv = QPushButton(tr("Экспорт в CSV"))
        saved.addWidget(QLabel(tr("Сохранённые:")))
        saved.addWidget(self.saved)
        saved.addWidget(self.btn_save)
        saved.addWidget(self.btn_del)
        saved.addStretch(1)
        saved.addWidget(self.btn_csv)
        lay.addLayout(saved)

        self.filters_box = QGroupBox(tr("Фильтры"))
        self.filters_box.setCheckable(True)
        self.filters_box.setChecked(settings.filters_enabled)
        fl = QHBoxLayout(self.filters_box)
        self.ext = QLineEdit()
        self.ext.setPlaceholderText("pdf, docx, txt")
        self.ext.setMaximumWidth(190)
        self.min_kb = self._spin("—")
        self.max_kb = self._spin("—")
        self.older = self._spin("—")
        for text, w in ((tr("Расширения:"), self.ext), (tr("Мин. КБ:"), self.min_kb), (tr("Макс. КБ:"), self.max_kb), (tr("Старше (дн.):"), self.older)):
            fl.addWidget(QLabel(text))
            fl.addWidget(w)
        fl.addStretch(1)
        lay.addWidget(self.filters_box)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Путь"), tr("Размер"), tr("Изменён"), tr("Фрагмент")])
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
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.setPlaceholderText(tr("Выберите файл в списке, чтобы увидеть его текст из индекса."))
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        self._results: list[dict] = []
        self.info = QLabel(tr("Добавьте папки и нажмите «Индексировать», затем введите запрос."))
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
        self.table.itemSelectionChanged.connect(self.update_preview)
        self.btn_save.clicked.connect(self.save_current)
        self.btn_del.clicked.connect(self.delete_saved)
        self.btn_csv.clicked.connect(self.export_results)
        self.saved.activated.connect(self.load_saved)
        self.refresh_saved()

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
        self._results = res
        self.preview.clear()
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
            self.info.setText(tr("Введите запрос или задайте фильтры."))
        else:
            self.info.setText(tr('Найдено: {0}').format(len(res)) + (tr(" (показаны первые 300)") if len(res) >= 300 else ""))

    def selected_path(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).text() if rows else None

    def open_selected(self) -> None:
        p = self.selected_path()
        if p and Path(p).exists():
            open_path(p)
        elif p:
            self.info.setText(tr("Файл не найден: возможно, он удалён. Нажмите «Индексировать»."))

    def _menu(self, pos) -> None:
        p = self.selected_path()
        if not p:
            return
        m = QMenu(self)
        m.addAction(tr("Открыть"), self.open_selected)
        m.addAction(tr("Показать в папке"), lambda: reveal_in_folder(p))
        m.addAction(tr("Копировать путь"), lambda: QGuiApplication.clipboard().setText(p))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # --- предпросмотр -------------------------------------------------------
    def update_preview(self) -> None:
        p = self.selected_path()
        if not p:
            self.preview.clear()
            return
        text = get_content(p)
        if text is None:
            self.preview.setPlainText(tr("Файла нет в индексе."))
        elif not text.strip():
            self.preview.setPlainText(tr("Для этого файла нет текста (картинка, архив, пустой файл и т. п.)."))
        else:
            body, n = preview_to_html(text, self.query.text())
            self.preview.setHtml(body)
            if n:
                self.preview.scrollToAnchor("m")

    # --- сохранённые поиски -------------------------------------------------
    def refresh_saved(self, select: str | None = None) -> None:
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem(tr("— выбрать —"), None)
        for e in self.settings.saved_searches:
            self.saved.addItem(e["name"], e["name"])
        if select:
            self.saved.setCurrentIndex(max(0, self.saved.findData(select)))
        self.saved.blockSignals(False)

    def save_current(self) -> None:
        q = self.query.text().strip()
        if not q and not self.current_filters().active():
            self.info.setText(tr("Нечего сохранять: введите запрос или задайте фильтры."))
            return
        name, ok = QInputDialog.getText(self, tr("Сохранить поиск"), tr("Название:"), text=q[:40])
        name = name.strip()
        if not ok or not name:
            return
        self.settings.save_search({"name": name, "query": q, "exts": self.ext.text(), "min_kb": self.min_kb.value(),
                                   "max_kb": self.max_kb.value(), "older": self.older.value(),
                                   "filters": self.filters_box.isChecked()})
        save_settings(self.settings)
        self.refresh_saved(name)

    def load_saved(self, _idx: int = 0) -> None:
        name = self.saved.currentData()
        entry = next((e for e in self.settings.saved_searches if e.get("name") == name), None)
        if not entry:
            return
        self.ext.setText(str(entry.get("exts", "")))
        self.min_kb.setValue(int(entry.get("min_kb", 0) or 0))
        self.max_kb.setValue(int(entry.get("max_kb", 0) or 0))
        self.older.setValue(int(entry.get("older", 0) or 0))
        self.filters_box.setChecked(bool(entry.get("filters", False)))
        self.query.setText(str(entry.get("query", "")))
        self.run_search()

    def delete_saved(self) -> None:
        name = self.saved.currentData()
        if not name:
            return
        if QMessageBox.question(self, tr("Удалить поиск"), tr('Удалить сохранённый поиск «{0}»?').format(name)) == QMessageBox.StandardButton.Yes:
            self.settings.delete_search(name)
            save_settings(self.settings)
            self.refresh_saved()

    # --- экспорт ------------------------------------------------------------
    def export_results(self) -> None:
        if not self._results:
            self.info.setText(tr("Нет результатов для экспорта."))
            return
        dest, _ = QFileDialog.getSaveFileName(self, tr("Экспорт результатов"), "filepilot-results.csv", "CSV (*.csv)")
        if dest:
            n = export_csv(self._results, dest)
            self.info.setText(tr('Сохранено строк: {0} → {1}').format(n, dest))
