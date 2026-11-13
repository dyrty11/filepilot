"""Главное окно FilePilot."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QTabWidget, QToolBar, QToolButton,
)

from ..i18n import tr
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
        tabs.addTab(self.search_tab, tr("Поиск"))
        tabs.addTab(self.dupes_tab, tr("Дубликаты"))
        tabs.addTab(self.disk_tab, tr("Карта диска"))
        tabs.addTab(self.rules_tab, tr("Правила"))
        tabs.currentChanged.connect(self._tab_changed)
        self.tabs = tabs
        self.setCentralWidget(tabs)

        tb = QToolBar(tr("Действия"))
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_add = self._action(tb, tr("Добавить папку"), self.add_folder, tr("Добавить папку для индексации"))
        self.act_folders = self._action(tb, tr("Папки…"), self.manage_folders, tr("Список папок"))
        tb.addSeparator()
        self.act_index = self._action(tb, tr("Индексировать"), self.start_index, tr("Просмотреть папки и обновить индекс (Ctrl+I)"), "Ctrl+I")
        self.act_cancel = self._action(tb, tr("Отменить"), self.cancel_task, tr("Остановить индексацию"))
        self.act_cancel.setEnabled(False)
        self.act_refresh = self._action(tb, tr("Обновить"), self.refresh_views, tr("Перечитать данные на вкладках (F5)"), "F5")
        tb.addSeparator()
        self.act_clear = self._action(tb, tr("Очистить индекс"), self.clear_index, tr("Удалить всё из индекса (сами файлы не затрагиваются)"))
        self.act_auto = self._action(tb, tr("Автоиндекс при запуске"), self._toggle_auto, tr("Индексировать папки при каждом запуске"))
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(self.settings.auto_index)
        tb.addSeparator()
        lang_btn = QToolButton()
        lang_btn.setText("Language / Язык")
        lang_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        lang_menu = QMenu(lang_btn)
        for code, label in (("auto", "Auto / Авто"), ("ru", "Русский"), ("en", "English")):
            act = lang_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.settings.language == code)
            act.triggered.connect(lambda _c=False, c=code: self._set_language(c))
        lang_btn.setMenu(lang_menu)
        tb.addWidget(lang_btn)
        self.act_find = QAction(self)
        self.act_find.setShortcut("Ctrl+F")
        self.act_find.triggered.connect(lambda: (self.tabs.setCurrentIndex(0), self.search_tab.query.setFocus()))
        self.addAction(self.act_find)

        sb = self.statusBar()
        self.status = QLabel(tr("Готово"))
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(260)
        self.bar.setVisible(False)
        sb.addWidget(self.status, 1)
        sb.addPermanentWidget(self.bar)
        self.status.setText(self._summary())
        self.search_tab.query.setFocus()

        if self.settings.auto_index and self.settings.folders:
            QTimer.singleShot(400, self.start_index)

    def _set_language(self, code: str) -> None:
        self.settings.language = code
        save_settings(self.settings)
        QMessageBox.information(self, "FilePilot", "Restart FilePilot to apply the language.\nПерезапустите FilePilot, чтобы применить язык.")

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
        return tr('В индексе файлов: {0}. Папок: {1}.').format(st['files'], folders) if st["files"] else tr("Индекс пуст. Добавьте папку и нажмите «Индексировать».")

    # --- действия ---
    def add_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(self, tr("Выберите папку для индексации"))
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
            self.status.setText(tr("Сначала добавьте папку."))
            return
        folders = list(self.settings.folders)
        self._busy(True)
        self.status.setText(tr("Индексация…"))

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
            self.status.setText(tr('Индексация {0}/{1}: {2}').format(i, total, path))

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
            self.status.setText(tr("Останавливаю…"))

    def _index_done(self, st: dict) -> None:
        self._task = None
        self._busy(False)
        head = tr("Остановлено") if st["cancelled"] else tr("Готово")
        self.status.setText(tr('{0}: {1} файлов, +{2} новых, ~{3} обновлено, {4} без изменений, {5} убрано, {6} ошибок').format(head, st['total'], st['added'], st['updated'], st['skipped'], st['removed'], st['errors']))
        self.refresh_views()

    def _index_failed(self, msg: str) -> None:
        self._task = None
        self._busy(False)
        self.status.setText(tr('Ошибка индексации: {0}').format(msg))

    def refresh_views(self) -> None:
        self.search_tab.run_search()
        self.disk_tab.refresh()
        self.rules_tab.refresh()

    def _tab_changed(self, i: int) -> None:
        if self.tabs.widget(i) is self.disk_tab:
            self.disk_tab.refresh()

    def clear_index(self) -> None:
        if QMessageBox.question(self, "FilePilot", tr("Очистить индекс? Ваши файлы не будут затронуты, потом можно проиндексировать заново.")) != QMessageBox.StandardButton.Yes:
            return
        n = db.clear_index()
        self.refresh_views()
        self.status.setText(tr('Индекс очищен ({0} записей).').format(n))

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
