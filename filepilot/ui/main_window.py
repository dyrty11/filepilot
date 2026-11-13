"""Главное окно FilePilot."""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QTabWidget, QToolBar, QToolButton,
)

from .. import __version__, db, indexer, updater
from ..i18n import tr
from ..settings import load_settings, save_settings
from .diskmap_tab import DiskMapTab
from .duplicates_tab import DuplicatesTab
from .folders_dialog import FoldersDialog
from .rules_tab import RulesTab
from .search_tab import SearchTab
from .theme import app_icon, apply_dark
from .update_dialog import UpdateDialog
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
        bg_btn = QToolButton()
        bg_btn.setText(tr("Фоновое обновление"))
        bg_btn.setToolTip(tr("Периодически обновлять индекс, пока программа открыта"))
        bg_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bg_menu = QMenu(bg_btn)
        self._bg_actions = {}
        for minutes, label in ((0, tr("Выключено")), (15, tr("Каждые 15 минут")), (60, tr("Каждый час")), (360, tr("Каждые 6 часов"))):
            act = bg_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.settings.reindex_minutes == minutes)
            act.triggered.connect(lambda _c=False, m=minutes: self.set_reindex_minutes(m))
            self._bg_actions[minutes] = act
        bg_btn.setMenu(bg_menu)
        tb.addWidget(bg_btn)
        self._bg_timer = QTimer(self)
        self._bg_timer.timeout.connect(self._background_index)
        self._apply_reindex_timer()
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
        upd_btn = QToolButton()
        upd_btn.setText(tr("Обновления"))
        upd_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        upd_menu = QMenu(upd_btn)
        upd_menu.addAction(tr("Проверить обновления"), lambda: self.check_updates(manual=True))
        self.act_auto_update = upd_menu.addAction(tr("Проверять при запуске"))
        self.act_auto_update.setCheckable(True)
        self.act_auto_update.setChecked(self.settings.check_updates)
        self.act_auto_update.triggered.connect(self._toggle_auto_update)
        upd_btn.setMenu(upd_menu)
        tb.addWidget(upd_btn)
        self._update_task: Task | None = None
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
        if self.settings.check_updates and updater.due(self.settings.last_update_check) and not os.environ.get("FILEPILOT_NO_UPDATE_CHECK"):
            QTimer.singleShot(2500, lambda: self.check_updates(manual=False))

    def set_reindex_minutes(self, minutes: int) -> None:
        self.settings.reindex_minutes = minutes
        save_settings(self.settings)
        for m, act in self._bg_actions.items():
            act.setChecked(m == minutes)
        self._apply_reindex_timer()

    def _apply_reindex_timer(self) -> None:
        if self.settings.reindex_minutes:
            self._bg_timer.start(self.settings.reindex_minutes * 60_000)
        else:
            self._bg_timer.stop()

    def _background_index(self) -> None:
        # пропускаем, если уже что-то идёт; интерфейс не блокируется
        if not self._task and self.settings.folders:
            self.start_index()

    def _toggle_auto_update(self) -> None:
        self.settings.check_updates = self.act_auto_update.isChecked()
        save_settings(self.settings)

    def check_updates(self, manual: bool = False, fetch=None) -> None:
        """Проверка в фоне. Тихая при запуске: сообщает, только если есть новая версия."""
        if self._update_task:
            return
        if manual:
            self.status.setText(tr("Проверяю обновления…"))
        self._update_task = Task(lambda progress, cancel: (fetch or updater.fetch_latest)(), self)
        self._update_task.done.connect(lambda rel: self._update_checked(rel, manual))
        self._update_task.failed.connect(lambda msg: self._update_failed(msg, manual))
        self._update_task.start()

    def _update_checked(self, rel, manual: bool) -> None:
        self._update_task = None
        self.settings.last_update_check = time.time()
        save_settings(self.settings)
        newer = rel is not None and updater.is_newer(rel.version)
        if not newer:
            if manual:
                self.status.setText(tr("У вас последняя версия ({0}).").format(__version__))
            return
        if not manual and rel.version == self.settings.skipped_version:
            return
        self.status.setText(tr("Доступна версия {0}.").format(rel.version))
        dlg = UpdateDialog(rel, self.settings, self)
        dlg.exec()
        save_settings(self.settings)
        if dlg.installer_started:
            self.close()

    def _update_failed(self, msg: str, manual: bool) -> None:
        self._update_task = None
        if manual:
            self.status.setText(tr("Не удалось проверить обновления: {0}").format(msg))

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
        for t in (self._task, self.dupes_tab._task, self.rules_tab._task, self._update_task):
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
