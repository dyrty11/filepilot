"""Вкладка «Правила»: автосортировка файлов с пробным запуском."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import tr
from .. import rules as rules_mod
from ..config import human_size
from .rule_dialog import RuleDialog
from .workers import Task


class PreviewDialog(QDialog):
    def __init__(self, title: str, actions: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 480)
        lay = QVBoxLayout(self)
        errors = sum(1 for a in actions if a.get("error"))
        lay.addWidget(QLabel(tr('Файлов: {0}').format(len(actions)) + (tr(', ошибок: {0}').format(errors) if errors else "")))
        t = QTableWidget(len(actions), 4)
        t.setHorizontalHeaderLabels([tr("Правило"), tr("Файл"), tr("Результат"), tr("Размер")])
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for r, a in enumerate(actions):
            result = a.get("error") and tr('Ошибка: {0}').format(a['error']) or a.get("dest") or tr(rules_mod.ACTION_LABELS.get(a["action"], a["action"]))
            for c, text in enumerate((a.get("rule", ""), a["file"], result, human_size(a.get("size")))):
                t.setItem(r, c, QTableWidgetItem(text))
        lay.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        lay.addWidget(bb)


class RulesTab(QWidget):
    changed = None  # зарезервировано

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules = rules_mod.load_rules()
        self._task: Task | None = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.btn_add = QPushButton(tr("Добавить"))
        self.btn_edit = QPushButton(tr("Редактировать"))
        self.btn_del = QPushButton(tr("Удалить"))
        self.btn_dry = QPushButton(tr("Пробный запуск"))
        self.btn_apply = QPushButton(tr("Применить"))
        self.btn_apply.setObjectName("primary")
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_dry)
        row.addWidget(self.btn_apply)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("Имя"), tr("Действие"), tr("Источник"), tr("Назначение"), tr("Совпадений"), tr("Вкл.")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        for c in (0, 1, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        self.info = QLabel(tr("Правила переносят, архивируют или отправляют в корзину файлы по условиям. Сначала сделайте «Пробный запуск»."))
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.btn_add.clicked.connect(self.add_rule)
        self.btn_edit.clicked.connect(self.edit_rule)
        self.table.doubleClicked.connect(lambda *_: self.edit_rule())
        self.btn_del.clicked.connect(self.delete_rule)
        self.btn_dry.clicked.connect(lambda: self.run(dry=True))
        self.btn_apply.clicked.connect(lambda: self.run(dry=False))
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(len(self.rules))
        for r, rule in enumerate(self.rules):
            try:
                n = len(rules_mod.plan(rule)) if rule.validate() is None else 0
            except Exception:  # noqa: BLE001
                n = 0
            cells = (rule.name, tr(rules_mod.ACTION_LABELS.get(rule.action, rule.action)), rule.folder or "", rule.dest or "—", str(n), tr("да") if rule.enabled else tr("нет"))
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.btn_dry.setEnabled(bool(self.rules))
        self.btn_apply.setEnabled(bool(self.rules))

    def _selected_index(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _save(self) -> None:
        rules_mod.save_rules(self.rules)
        self.refresh()

    def add_rule(self) -> None:
        dlg = RuleDialog(None, self)
        if dlg.exec() and dlg.result_rule:
            self.rules.append(dlg.result_rule)
            self._save()

    def edit_rule(self) -> None:
        i = self._selected_index()
        if i is None:
            return
        dlg = RuleDialog(self.rules[i], self)
        if dlg.exec() and dlg.result_rule:
            self.rules[i] = dlg.result_rule
            self._save()

    def delete_rule(self) -> None:
        i = self._selected_index()
        if i is None:
            return
        if QMessageBox.question(self, "FilePilot", tr('Удалить правило «{0}»?').format(self.rules[i].name)) == QMessageBox.StandardButton.Yes:
            del self.rules[i]
            self._save()

    def _targets(self):
        i = self._selected_index()
        chosen = [self.rules[i]] if i is not None else [r for r in self.rules if r.enabled]
        return [r for r in chosen if r.validate() is None]

    def run(self, dry: bool) -> None:
        if self._task:
            return
        targets = self._targets()
        if not targets:
            self.info.setText(tr("Нет подходящих правил: выберите правило или включите хотя бы одно."))
            return
        if not dry:
            n = sum(len(rules_mod.plan(r)) for r in targets)
            names = ", ".join(r.name for r in targets)
            if n == 0:
                self.info.setText(tr("Под правила не подходит ни один файл."))
                return
            if QMessageBox.question(self, "FilePilot", tr('Применить правила ({0}) к файлам: {1}?\nПеренос и архивация обратимы, а удалённые файлы попадут в корзину.').format(names, n)) != QMessageBox.StandardButton.Yes:
                return
        for b in (self.btn_dry, self.btn_apply):
            b.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)

        def job(progress, cancel):
            out = []
            for r in targets:
                for a in rules_mod.apply(r, dry_run=dry, on_progress=lambda i, n: progress(i, n, r.name), should_cancel=cancel):
                    out.append({"rule": r.name, **a})
            return out

        self._task = Task(job, self)
        self._task.progress.connect(lambda i, n, _: (self.bar.setRange(0, max(n, 1)), self.bar.setValue(i)))
        self._task.done.connect(lambda res: self._finished(res, dry))
        self._task.failed.connect(lambda m: (self._reset(), self.info.setText(tr('Ошибка: {0}').format(m))))
        self._task.start()

    def _reset(self) -> None:
        self._task = None
        self.bar.setVisible(False)
        self.refresh()

    def _finished(self, actions, dry: bool) -> None:
        self._reset()
        errors = sum(1 for a in actions if a.get("error"))
        self.info.setText((tr("Пробный запуск: ничего не изменено. ") if dry else tr("Готово. ")) + tr('Файлов: {0}').format(len(actions)) + (tr(', ошибок: {0}').format(errors) if errors else "") + ".")
        PreviewDialog(tr("Пробный запуск") if dry else tr("Результат"), actions, self).exec()
