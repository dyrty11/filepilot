"""Диалог создания и редактирования правила."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QWidget, QCheckBox,
)

from ..i18n import tr
from ..rules import ACTION_LABELS, ACTIONS, Rule


def _folder_row(line: QLineEdit, parent) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    btn = QPushButton("…")
    btn.setMaximumWidth(36)

    def pick():
        d = QFileDialog.getExistingDirectory(parent, tr("Выберите папку"), line.text())
        if d:
            line.setText(d)
    btn.clicked.connect(pick)
    h.addWidget(line, 1)
    h.addWidget(btn)
    return w


class RuleDialog(QDialog):
    def __init__(self, rule: Rule | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Правило"))
        self.setMinimumWidth(520)
        r = rule or Rule(name="")
        form = QFormLayout(self)
        self.name = QLineEdit(r.name)
        self.action = QComboBox()
        for a in ACTIONS:
            self.action.addItem(tr(ACTION_LABELS[a]), a)
        self.action.setCurrentIndex(ACTIONS.index(r.action) if r.action in ACTIONS else 0)
        self.folder = QLineEdit(r.folder or "")
        self.folder.setPlaceholderText(tr(r"C:\Users\Вы\Downloads"))
        self.ext = QLineEdit(", ".join(r.ext))
        self.ext.setPlaceholderText(tr(".exe, .msi (пусто = любые)"))
        self.pattern = QLineEdit(r.pattern or "")
        self.pattern.setPlaceholderText(tr("Screenshot*.png (пусто = любые)"))
        self.older = QSpinBox()
        self.older.setRange(0, 100_000)
        self.older.setSpecialValueText(tr("— не важно —"))
        self.older.setValue(r.older_than_days or 0)
        self.dest = QLineEdit(r.dest or "")
        self.dest.setPlaceholderText(tr(r"C:\Users\Вы\Archive (для переноса и архивации)"))
        self.enabled = QCheckBox(tr("Правило включено"))
        self.enabled.setChecked(r.enabled)
        form.addRow(tr("Имя:"), self.name)
        form.addRow(tr("Действие:"), self.action)
        form.addRow(tr("Папка-источник:"), _folder_row(self.folder, self))
        form.addRow(tr("Расширения:"), self.ext)
        form.addRow(tr("Шаблон имени:"), self.pattern)
        form.addRow(tr("Старше (дней):"), self.older)
        form.addRow(tr("Назначение:"), _folder_row(self.dest, self))
        form.addRow("", self.enabled)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.result_rule: Rule | None = None

    def _accept(self) -> None:
        from ..search import parse_exts

        rule = Rule(
            name=self.name.text().strip(), action=self.action.currentData(),
            folder=self.folder.text().strip() or None, ext=parse_exts(self.ext.text()),
            older_than_days=self.older.value() or None, pattern=self.pattern.text().strip() or None,
            dest=self.dest.text().strip() or None, enabled=self.enabled.isChecked(),
        )
        err = rule.validate()
        if err:
            QMessageBox.warning(self, "FilePilot", tr(err))
            return
        self.result_rule = rule
        self.accept()
