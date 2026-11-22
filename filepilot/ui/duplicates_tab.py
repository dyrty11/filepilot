"""Вкладка «Дубликаты»: поиск одинаковых файлов и удаление лишних копий в корзину."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QSpinBox, QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import tr
from .. import duplicates
from ..config import human_size
from ..i18n import plural
from .workers import Task


DEFAULT_MIN_KB = 100  # мелочь (пустые JSON «{}», заглушки, конфиги) почти всегда «одинакова», но копиями не является и места не занимает


def _mtime_text(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


class DuplicatesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups: list[dict] = []
        self._task: Task | None = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.btn_find = QPushButton(tr("Найти дубликаты"))
        self.btn_find.setObjectName("primary")
        self.btn_cancel = QPushButton(tr("Отменить"))
        self.btn_cancel.setEnabled(False)
        self.keep = QComboBox()
        for key, label in (("first", tr("Первую в списке")), ("oldest", tr("Самую старую")), ("newest", tr("Самую новую")), ("shortest", tr("С самым коротким путём"))):
            self.keep.addItem(label, key)
        self.same_ext = QCheckBox(tr("Только с одинаковым расширением"))
        self.same_ext.setChecked(True)
        self.same_ext.setToolTip(tr("Файлы с одинаковым содержимым, но разным расширением (например test.exe и test.bat) не считаются дубликатами."))
        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 10_000_000)
        self.min_kb.setValue(DEFAULT_MIN_KB)
        self.min_kb.setSuffix(tr(" КБ"))
        self.min_kb.setToolTip(tr("Файлы меньше этого размера не проверяются: крошечные файлы вроде «{}» почти всегда одинаковы и копиями не являются."))
        self.btn_mark = QPushButton(tr("Отметить остальные"))
        self.btn_unmark = QPushButton(tr("Снять отметки"))
        self.btn_trash = QPushButton(tr("Удалить отмеченные в корзину"))
        self.btn_csv = QPushButton(tr("Экспорт в CSV"))
        for b in (self.btn_find, self.btn_cancel):
            row.addWidget(b)
        row.addWidget(QLabel(tr("Не меньше:")))
        row.addWidget(self.min_kb)
        row.addWidget(self.same_ext)
        row.addWidget(QLabel(tr("Оставить:")))
        row.addWidget(self.keep)
        row.addWidget(self.btn_mark)
        row.addWidget(self.btn_unmark)
        row.addStretch(1)
        row.addWidget(self.btn_csv)
        row.addWidget(self.btn_trash)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Файл"), tr("Размер"), tr("Изменён")])
        self.tree.setColumnWidth(0, 640)
        lay.addWidget(self.tree, 1)
        self.info = QLabel(tr("Нажмите «Найти дубликаты»: сравниваются файлы из индекса по содержимому."))
        lay.addWidget(self.info)
        self.btn_find.clicked.connect(self.start)
        self.btn_cancel.clicked.connect(lambda: self._task and self._task.cancel())
        self.btn_mark.clicked.connect(lambda: self.mark_duplicates(self.keep.currentData()))
        self.btn_unmark.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        self.btn_trash.clicked.connect(self.trash_checked)
        self.btn_csv.clicked.connect(self.export_groups)

    def export_groups(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        if not self.groups:
            self.info.setText(tr("Нет результатов для экспорта."))
            return
        dest, _ = QFileDialog.getSaveFileName(self, tr("Экспорт результатов"), "filepilot-duplicates.csv", "CSV (*.csv)")
        if dest:
            n = duplicates.export_csv(self.groups, dest)
            self.info.setText(tr('Сохранено строк: {0} → {1}').format(n, dest))

    def start(self) -> None:
        if self._task:
            return
        self.btn_find.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.info.setText(tr("Ищу дубликаты…"))

        same_ext = self.same_ext.isChecked()
        min_size = self.min_kb.value() * 1024
        self._min_kb_used = self.min_kb.value()

        def job(progress, cancel):
            return duplicates.find_duplicates(on_progress=lambda i, n: progress(i, n, ""), should_cancel=cancel, same_ext=same_ext, min_size=min_size)

        self._task = Task(job, self)
        self._task.progress.connect(lambda i, n, _: (self.bar.setRange(0, max(n, 1)), self.bar.setValue(i)))
        self._task.done.connect(self._finished)
        self._task.failed.connect(lambda m: (self._reset(), self.info.setText(tr('Ошибка: {0}').format(m))))
        self._task.start()

    def _reset(self) -> None:
        self._task = None
        self.btn_find.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.bar.setVisible(False)

    def _finished(self, groups) -> None:
        self._reset()
        self.groups = groups
        self.tree.clear()
        saved = 0
        for g in groups:
            saved += g["size"] * (len(g["files"]) - 1)
            n = len(g["files"])
            top = QTreeWidgetItem([tr('{0} {1} по {2} (можно освободить {3})').format(n, plural(n, ('copy', 'copies'), ('копия', 'копии', 'копий')), human_size(g['size']), human_size(g['size'] * (n - 1))), ""])
            top.setFirstColumnSpanned(False)
            self.tree.addTopLevelItem(top)
            for p in g["files"]:
                ch = QTreeWidgetItem([p, human_size(g["size"]), _mtime_text(p)])
                ch.setFlags(ch.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                ch.setCheckState(0, Qt.CheckState.Unchecked)
                top.addChild(ch)
            top.setExpanded(True)
        text = tr('Групп дубликатов: {0}. Можно освободить: {1}.').format(len(groups), human_size(saved)) if groups else tr("Дубликатов нет.")
        if getattr(self, "_min_kb_used", 0):
            text += " " + tr("Файлы меньше {0} КБ не проверялись.").format(self._min_kb_used)
        self.info.setText(text)

    def _children(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield [top.child(j) for j in range(top.childCount())]

    def _set_all(self, state) -> None:
        for kids in self._children():
            for k in kids:
                k.setCheckState(0, state)

    def mark_duplicates(self, rule: str = "first") -> None:
        """Отмечает в каждой группе все копии, кроме одной (по правилу «оставить»)."""
        for kids in self._children():
            keep = duplicates.choose_keep([k.text(0) for k in kids], rule)
            for k in kids:
                k.setCheckState(0, Qt.CheckState.Unchecked if k.text(0) == keep else Qt.CheckState.Checked)

    def mark_all_but_first(self) -> None:
        self.mark_duplicates("first")

    def trash_checked(self) -> None:
        groups, selected = [], set()
        for kids in self._children():
            groups.append([k.text(0) for k in kids])
            selected.update(k.text(0) for k in kids if k.checkState(0) == Qt.CheckState.Checked)
        if not selected:
            self.info.setText(tr("Ничего не отмечено."))
            return
        ok = QMessageBox.question(self, "FilePilot", tr('Отправить в корзину файлов: {0}?\nВ каждой группе останется хотя бы одна копия.').format(len(selected)))
        if ok != QMessageBox.StandardButton.Yes:
            return
        done, errors = duplicates.trash_selected(groups, selected)
        msg = tr('Отправлено в корзину: {0}.').format(len(done))
        if errors:
            msg += tr(' Ошибок: {0} (например: {1})').format(len(errors), errors[0][1])
        self.info.setText(msg)
        self.start()
