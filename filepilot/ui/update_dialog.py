"""Окно «Доступна новая версия»: описание, загрузка, проверка суммы, запуск установщика."""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout

from .. import __version__, updater
from ..i18n import tr
from .workers import Task


class UpdateDialog(QDialog):
    """Результат: exec() == Accepted, если установщик запущен и программу нужно закрыть."""

    def __init__(self, release: updater.Release, settings, parent=None):
        super().__init__(parent)
        self.rel, self.settings = release, settings
        self.installer_started = False
        self._task: Task | None = None
        self.setWindowTitle(tr("Доступно обновление"))
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        head = QLabel(tr("Доступна версия {0} (у вас {1}).").format(release.version, __version__))
        head.setStyleSheet("font-size: 15px; font-weight: 600;")
        lay.addWidget(head)
        lay.addWidget(QLabel(tr("Что нового:")))
        self.notes = QTextBrowser()
        self.notes.setPlainText(release.notes.strip() or tr("Описание не указано."))
        lay.addWidget(self.notes, 1)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        self.btn_install = QPushButton(tr("Скачать и установить"))
        self.btn_install.setObjectName("primary")
        self.btn_page = QPushButton(tr("Открыть страницу релиза"))
        self.btn_skip = QPushButton(tr("Пропустить эту версию"))
        self.btn_later = QPushButton(tr("Позже"))
        for b in (self.btn_install, self.btn_page, self.btn_skip):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_later)
        lay.addLayout(row)

        can = updater.can_self_install() and bool(release.installer_url)
        self.btn_install.setVisible(can)
        if not can:
            self.info.setText(tr("Автоустановка доступна только в установленной версии. Скачайте новую версию на странице релиза."))
        self.btn_install.clicked.connect(self.start_download)
        self.btn_page.clicked.connect(lambda: webbrowser.open(release.page_url))
        self.btn_skip.clicked.connect(self._skip)
        self.btn_later.clicked.connect(self.reject)

    def _skip(self) -> None:
        self.settings.skipped_version = self.rel.version
        self.reject()

    def start_download(self) -> None:
        if self._task:
            return
        self.btn_install.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.btn_later.setText(tr("Отмена"))
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.info.setText(tr("Загрузка…"))
        rel = self.rel
        self._task = Task(lambda progress, cancel: updater.download_installer(rel, progress, cancel), self)
        self._task.progress.connect(self._progress)
        self._task.done.connect(self._downloaded)
        self._task.failed.connect(self._failed)
        self._task.start()

    def _progress(self, done: int, total: int, _name: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)

    def _downloaded(self, path) -> None:
        self._task = None
        self.info.setText(tr("Файл проверен (SHA-256). Запускаю установку: программа закроется и откроется снова."))
        try:
            updater.launch_installer(path)
        except OSError as e:
            self._failed(str(e))
            return
        self.installer_started = True
        self.accept()

    def _failed(self, msg: str) -> None:
        self._task = None
        self.bar.setVisible(False)
        self.btn_install.setEnabled(True)
        self.btn_skip.setEnabled(True)
        self.btn_later.setText(tr("Позже"))
        self.info.setText(tr("Не удалось обновить: {0}").format(msg))

    def reject(self) -> None:
        if self._task:  # кнопка «Отмена» во время загрузки
            self._task.cancel()
            self._task.wait(3000)
            self._task = None
        super().reject()
