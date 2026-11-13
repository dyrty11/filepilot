"""Вкладка «Дубликаты»: поиск одинаковых файлов и удаление лишних копий в корзину."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import tr
from .. import duplicates
from ..config import human_size
from ..i18n import plural
from .workers import Task


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
        self.btn_mark = QPushButton(tr("Отметить все копии, кроме первой"))
        self.btn_unmark = QPushButton(tr("Снять отметки"))
        self.btn_trash = QPushButton(tr("Удалить отмеченные в корзину"))
        for b in (self.btn_find, self.btn_cancel, self.btn_mark, self.btn_unmark):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_trash)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Файл"), tr("Размер")])
        self.tree.setColumnWidth(0, 640)
        lay.addWidget(self.tree, 1)
        self.info = QLabel(tr("Нажмите «Найти дубликаты»: сравниваются файлы из индекса по содержимому."))
        lay.addWidget(self.info)
        self.btn_find.clicked.connect(self.start)
        self.btn_cancel.clicked.connect(lambda: self._task and self._task.cancel())
        self.btn_mark.clicked.connect(self.mark_all_but_first)
        self.btn_unmark.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        self.btn_trash.clicked.connect(self.trash_checked)

    def start(self) -> None:
        if self._task:
            return
        self.btn_find.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.info.setText(tr("Ищу дубликаты…"))

        def job(progress, cancel):
            return duplicates.find_duplicates(on_progress=lambda i, n: progress(i, n, ""), should_cancel=cancel)

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
                ch = QTreeWidgetItem([p, human_size(g["size"])])
                ch.setFlags(ch.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                ch.setCheckState(0, Qt.CheckState.Unchecked)
                top.addChild(ch)
            top.setExpanded(True)
        self.info.setText(tr('Групп дубликатов: {0}. Можно освободить: {1}.').format(len(groups), human_size(saved)) if groups else tr("Дубликатов нет."))

    def _children(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield [top.child(j) for j in range(top.childCount())]

    def _set_all(self, state) -> None:
        for kids in self._children():
            for k in kids:
                k.setCheckState(0, state)

    def mark_all_but_first(self) -> None:
        for kids in self._children():
            for j, k in enumerate(kids):
                k.setCheckState(0, Qt.CheckState.Unchecked if j == 0 else Qt.CheckState.Checked)

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
