"""Главное окно FilePilot."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QProgressBar, QTabWidget, QToolBar,
)

from .. import __version__, db, indexer
from ..settings import load_settings, save_settings
from .diskmap_tab import DiskMapTab
from .duplicates_tab import DuplicatesTab
from .folders_dialog import FoldersDialog
from .rules_tab import RulesTab
from .search_tab import SearchTab
from .theme import app_icon, apply_dark
from .workers import Task


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FilePilot")
        self.setWindowIcon(app_icon())
        self.resize(1100, 730)
        self.settings = load_settings()
        self._task: Task | None = None

        self.search_tab = SearchTab(self.settings)
        self.dupes_tab = DuplicatesTab()
        self.disk_tab = DiskMapTab(self.settings)
        self.rules_tab = RulesTab()
        tabs = QTabWidget()
        tabs.addTab(self.search_tab, "Поиск")
        tabs.addTab(self.dupes_tab, "Дубликаты")
        tabs.addTab(self.disk_tab, "Карта диска")
        tabs.addTab(self.rules_tab, "Правила")
        tabs.currentChanged.connect(self._tab_changed)
        self.tabs = tabs
        self.setCentralWidget(tabs)

        tb = QToolBar("Действия")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_add = self._action(tb, "Добавить папку", self.add_folder, "Добавить папку для индексации")
        self.act_folders = self._action(tb, "Папки…", self.manage_folders, "Список папок")
        tb.addSeparator()
        self.act_index = self._action(tb, "Индексировать", self.start_index, "Просмотреть папки и обновить индекс (Ctrl+I)", "Ctrl+I")
        self.act_cancel = self._action(tb, "Отменить", self.cancel_task, "Остановить индексацию")
        self.act_cancel.setEnabled(False)
        self.act_refresh = self._action(tb, "Обновить", self.refresh_views, "Перечитать данные на вкладках (F5)", "F5")
        tb.addSeparator()
        self.act_clear = self._action(tb, "Очистить индекс", self.clear_index, "Удалить всё из индекса (сами файлы не затрагиваются)")
        self.act_auto = self._action(tb, "Автоиндекс при запуске", self._toggle_auto, "Индексировать папки при каждом запуске")
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(self.settings.auto_index)
        self.act_find = QAction(self)
        self.act_find.setShortcut("Ctrl+F")
        self.act_find.triggered.connect(lambda: (self.tabs.setCurrentIndex(0), self.search_tab.query.setFocus()))
        self.addAction(self.act_find)

        sb = self.statusBar()
        self.status = QLabel("Готово")
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(260)
        self.bar.setVisible(False)
        sb.addWidget(self.status, 1)
        sb.addPermanentWidget(self.bar)
        self.status.setText(self._summary())
        self.search_tab.query.setFocus()

        if self.settings.auto_index and self.settings.folders:
            QTimer.singleShot(400, self.start_index)

    def _action(self, tb, text, slot, tip="", shortcut=None) -> QAction:
        a = QAction(text, self)
        a.setToolTip(tip or text)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(lambda _checked=False: slot())
        tb.addAction(a)
        return a

    def _summary(self) -> str:
        st = db.stats()
        folders = len(self.settings.folders)
        return f"В индексе файлов: {st['files']}. Папок: {folders}." if st["files"] else "Индекс пуст. Добавьте папку и нажмите «Индексировать»."

    # --- действия ---
    def add_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(self, "Выберите папку для индексации")
        if d and self.settings.add_folder(d):
            save_settings(self.settings)
            self.start_index()

    def manage_folders(self) -> None:
        before = list(self.settings.folders)
        FoldersDialog(self.settings, self).exec()
        if before != self.settings.folders:
            save_settings(self.settings)
            self.status.setText(self._summary())

    def _toggle_auto(self) -> None:
        self.settings.auto_index = self.act_auto.isChecked()
        save_settings(self.settings)

    def start_index(self) -> None:
        if self._task:
            return
        if not self.settings.folders:
            self.status.setText("Сначала добавьте папку.")
            return
        folders = list(self.settings.folders)
        self._busy(True)
        self.status.setText("Индексация…")

        def job(progress, cancel):
            return indexer.index_folders(folders, on_progress=progress, should_cancel=cancel)

        self._task = Task(job, self)
        self._task.progress.connect(self._on_progress)
        self._task.done.connect(self._index_done)
        self._task.failed.connect(self._index_failed)
        self._task.start()

    def _on_progress(self, i: int, total: int, path: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(i)
        if i % 25 == 0:
            self.status.setText(f"Индексация {i}/{total}: {path}")

    def _busy(self, on: bool) -> None:
        self.bar.setVisible(on)
        self.bar.setRange(0, 0)
        self.act_index.setEnabled(not on)
        self.act_add.setEnabled(not on)
        self.act_clear.setEnabled(not on)
        self.act_cancel.setEnabled(on)

    def cancel_task(self) -> None:
        if self._task:
            self._task.cancel()
            self.status.setText("Останавливаю…")

    def _index_done(self, st: dict) -> None:
        self._task = None
        self._busy(False)
        head = "Остановлено" if st["cancelled"] else "Готово"
        self.status.setText(f"{head}: {st['total']} файлов, +{st['added']} новых, ~{st['updated']} обновлено, {st['skipped']} без изменений, "
                            f"{st['removed']} убрано, {st['errors']} ошибок")
        self.refresh_views()

    def _index_failed(self, msg: str) -> None:
        self._task = None
        self._busy(False)
        self.status.setText(f"Ошибка индексации: {msg}")

    def refresh_views(self) -> None:
        self.search_tab.run_search()
        self.disk_tab.refresh()
        self.rules_tab.refresh()

    def _tab_changed(self, i: int) -> None:
        if self.tabs.widget(i) is self.disk_tab:
            self.disk_tab.refresh()

    def clear_index(self) -> None:
        if QMessageBox.question(self, "FilePilot", "Очистить индекс? Ваши файлы не будут затронуты, потом можно проиндексировать заново.") != QMessageBox.StandardButton.Yes:
            return
        n = db.clear_index()
        self.refresh_views()
        self.status.setText(f"Индекс очищен ({n} записей).")

    def closeEvent(self, e) -> None:
        save_settings(self.settings)
        for t in (self._task, self.dupes_tab._task, self.rules_tab._task):
            if t is not None:
                t.cancel()
                t.wait(3000)
        super().closeEvent(e)


def run() -> int:
    if sys.platform == "win32":
        try:  # своя иконка на панели задач, а не иконка python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dyrty11.FilePilot")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FilePilot")
    app.setApplicationVersion(__version__)
    apply_dark(app)
    win = MainWindow()
    win.show()
    return app.exec()
