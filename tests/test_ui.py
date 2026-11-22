"""Дымовые тесты интерфейса: запускаются без монитора (offscreen)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from filepilot.settings import load_settings, save_settings  # noqa: E402
from filepilot.ui.main_window import MainWindow  # noqa: E402
from filepilot.ui.search_tab import snippet_to_html  # noqa: E402
from filepilot.ui.theme import apply_dark  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_dark(a)
    return a


def wait_until(cond, timeout=10000):
    loop = QEventLoop()
    t = QTimer(); t.setInterval(30)
    elapsed = {"ms": 0}

    def tick():
        elapsed["ms"] += 30
        if cond() or elapsed["ms"] > timeout:
            loop.quit()
    t.timeout.connect(tick); t.start(); loop.exec(); t.stop()
    return cond()


def test_snippet_html_is_escaped():
    out = snippet_to_html('<img src=x onerror=1> \x02ключ\x03', "#fff")
    assert "<img" not in out and "&lt;img" in out and "<b " in out


def test_full_flow(app, tmp_path):
    root = tmp_path / "docs"; root.mkdir()
    (root / "a.txt").write_text("Договор поставки 2024", encoding="utf-8")
    (root / "b.txt").write_text("копия", encoding="utf-8")
    (root / "c.txt").write_text("копия", encoding="utf-8")
    s = load_settings(); s.add_folder(str(root)); save_settings(s)
    w = MainWindow()
    w.show()
    w.start_index()
    assert wait_until(lambda: w._task is None)
    assert "3 файлов" in w.status.text()
    w.search_tab.query.setText("договор")
    w.search_tab.run_search()
    assert w.search_tab.table.rowCount() == 1
    w.search_tab.table.selectRow(0)
    assert "Договор поставки" in w.search_tab.preview.toPlainText()
    w.search_tab.settings.save_search({"name": "т", "query": "договор", "exts": "txt", "min_kb": 0, "max_kb": 0, "older": 0, "filters": True})
    w.search_tab.refresh_saved("т")
    w.search_tab.query.setText("")
    w.search_tab.load_saved()
    assert w.search_tab.query.text() == "договор" and w.search_tab.ext.text() == "txt"
    w.dupes_tab.start()
    assert wait_until(lambda: w.dupes_tab._task is None)
    assert w.dupes_tab.tree.topLevelItemCount() == 1
    w.disk_tab.refresh()
    assert w.disk_tab.table.rowCount() == 3
    w.close()


def test_update_flow_in_window(app, monkeypatch):
    from filepilot import updater as upd
    from filepilot.ui import main_window as mw
    shown = []
    monkeypatch.setattr(mw.UpdateDialog, "exec", lambda self: shown.append(self.rel.version) or 0)
    w = MainWindow()
    w.check_updates(manual=True, fetch=lambda: upd.Release("9.9.9", "v9.9.9", "notes", "https://github.com/x"))
    assert wait_until(lambda: w._update_task is None)
    assert shown == ["9.9.9"]
    w.check_updates(manual=True, fetch=lambda: upd.Release("0.0.1", "v0.0.1", "", "https://github.com/x"))
    assert wait_until(lambda: w._update_task is None)
    assert "последняя" in w.status.text()
    w.close()


def test_donut_chart_geometry_and_english_labels(app, tmp_path):
    from PySide6.QtCore import QPointF
    from filepilot import i18n
    from filepilot.ui.charts import DonutChart
    from filepilot.ui.diskmap_tab import _loc
    ch = DonutChart()
    ch.resize(300, 500)
    ch.set_data([("a", 75), ("b", 25)], 0)
    c = ch._ring().center()
    r = ch._ring().width() / 2 * 0.75
    assert ch.slice_at(QPointF(c.x() + r * 0.5, c.y() - r * 0.5)) == 0   # сверху справа — первый сектор (75 %)
    assert ch.slice_at(QPointF(c.x() - r * 0.5, c.y() - r * 0.5)) == 1   # сверху слева — последний
    assert ch.slice_at(QPointF(c.x(), c.y())) is None                    # дырка в центре
    ch.grab()  # рисование не падает
    ch.set_data([], 0)
    ch.grab()
    i18n.set_language("en")
    assert _loc("(без расширения)") == "(no extension)"


def test_keep_rule_marking_and_background_timer(app):
    w = MainWindow()
    tab = w.dupes_tab
    from PySide6.QtWidgets import QTreeWidgetItem
    tab._finished([{"hash": "h", "size": 5, "files": ["/x/a.txt", "/x/longer/b.txt"]}])
    tab.mark_duplicates("shortest")
    kids = next(tab._children())
    assert [k.checkState(0).name for k in kids] == ["Unchecked", "Checked"]
    tab.mark_all_but_first()
    assert [k.checkState(0).name for k in kids] == ["Unchecked", "Checked"]
    assert not w._bg_timer.isActive()
    w.set_reindex_minutes(15)
    assert w._bg_timer.isActive() and w._bg_timer.interval() == 15 * 60_000 and w.settings.reindex_minutes == 15
    w.set_reindex_minutes(0)
    assert not w._bg_timer.isActive()
    w.close()


def test_whats_new_after_update(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from filepilot import __version__
    from filepilot.settings import Settings, load_settings, save_settings
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.informativeText()) or 0)

    # первая установка (файла настроек нет): тихо запоминаем версию
    w = MainWindow()
    assert w._had_settings_file is False
    assert w.check_whats_new() is False and not shown
    assert load_settings().last_seen_version == __version__
    assert w.check_whats_new() is False   # повторный запуск той же версии: тишина
    w.close()

    # обновление с предыдущей версии: уведомление и «Что нового»
    s = load_settings(); s.last_seen_version = "0.1.0"; save_settings(s)
    w = MainWindow()
    assert w.check_whats_new() is True
    assert shown and "Что нового" in shown[0]
    w.close()

    # настройки от версии без этого поля (старше 0.4.0): тоже считается обновлением
    s = load_settings(); s.last_seen_version = ""; save_settings(s)
    w = MainWindow()
    assert w.check_whats_new() is True
    w.close()

    # откат на старую версию: молчим
    s = load_settings(); s.last_seen_version = "99.0.0"; save_settings(s)
    shown.clear()
    w = MainWindow()
    assert w.check_whats_new() is False and not shown
    w.close()


def test_about_dialog_has_links(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from filepilot import config
    shown = []
    monkeypatch.setattr(QMessageBox, "about", staticmethod(lambda parent, title, text: shown.append(text)))
    w = MainWindow()
    w.show_about()
    assert config.SITE_URL in shown[0] and config.REPO_URL in shown[0] and config.DOWNLOAD_URL in shown[0]
    w.close()


def test_scope_combo_and_excluded_index(app, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "f.txt").write_text("общий текст", encoding="utf-8")
    skip = b / "skip"; skip.mkdir(); (skip / "s.txt").write_text("общий текст", encoding="utf-8")
    s = load_settings(); s.add_folder(str(a)); s.add_folder(str(b)); s.add_exclude(str(skip)); save_settings(s)
    w = MainWindow()
    w.show()
    w.start_index()
    assert wait_until(lambda: w._task is None)
    t = w.search_tab
    t.query.setText("текст")
    t.run_search()
    assert t.table.rowCount() == 2  # s.txt исключён
    assert t.scope.count() == 3 and t.scope.itemText(0) == "Все папки"
    t.filters_box.setChecked(True)
    t.scope.setCurrentIndex(t.scope.findData(str(a)))
    t.run_search()
    assert t.table.rowCount() == 1 and t.table.item(0, 0).text().startswith(str(a))
    assert t.current_filters().folder == str(a)


def test_operators_history_and_csv_export(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    root = tmp_path / "docs"; root.mkdir()
    (root / "a.txt").write_text("Договор поставки 2024", encoding="utf-8")
    (root / "b.log").write_text("Договор старый", encoding="utf-8")
    (root / "c.txt").write_text("копия", encoding="utf-8")
    (root / "d.txt").write_text("копия", encoding="utf-8")
    s = load_settings(); s.add_folder(str(root)); save_settings(s)
    w = MainWindow(); w.show(); w.start_index()
    assert wait_until(lambda: w._task is None)
    st = w.search_tab
    st.query.setText("договор ext:log")
    st.run_search()
    assert st.table.rowCount() == 1
    st.remember_query()
    st.remember_query()
    assert load_settings().history == ["договор ext:log"]
    # CSV дубликатов
    w.dupes_tab.start()
    assert wait_until(lambda: w.dupes_tab._task is None)
    out = tmp_path / "d.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    w.dupes_tab.export_groups()
    assert len(out.read_text("utf-8-sig").splitlines()) == 3
    # CSV карты диска
    w.disk_tab.refresh()
    out2 = tmp_path / "m.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out2), ""))
    w.disk_tab.export_table()
    assert len(out2.read_text("utf-8-sig").splitlines()) == w.disk_tab.table.rowCount() + 1
    w.close()


def test_drop_folders_into_window(app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtCore import QPointF, Qt
    folder = tmp_path / "new"; folder.mkdir()
    (folder / "x.txt").write_text("привет мир", encoding="utf-8")
    afile = tmp_path / "file.txt"; afile.write_text("не папка", encoding="utf-8")
    w = MainWindow(); w.show()
    assert w.add_folders([str(afile)]) == 0
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(str(folder)), QUrl.fromLocalFile(str(afile))])
    ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    w.dropEvent(ev)
    assert str(folder) in w.settings.folders or os.path.normpath(str(folder)) in [os.path.normpath(f) for f in w.settings.folders]
    assert wait_until(lambda: w._task is None)
    assert w.add_folders([str(folder)]) == 0  # повтор не дублируется
    w.close()


def test_adding_whole_drive_asks_first(app, monkeypatch):
    w = MainWindow()
    asked = []
    monkeypatch.setattr(w, "_confirm_whole_drive", lambda: (asked.append(1), False)[1])
    root = os.path.abspath(os.sep)
    assert w.add_folders([root]) == 0 and asked == [1]
    assert root not in w.settings.folders
    w.close()


def test_optimize_button(app, tmp_path):
    root = tmp_path / "docs"; root.mkdir()
    (root / "a.txt").write_text("Договор поставки", encoding="utf-8")
    s = load_settings(); s.add_folder(str(root)); save_settings(s)
    w = MainWindow(); w.show(); w.start_index()
    assert wait_until(lambda: w._task is None)
    assert "Размер индекса" in w._summary()
    w.act_optimize.trigger()
    assert wait_until(lambda: w._task is None)
    assert "Индекс сжат" in w.status.text() and w.act_optimize.isEnabled()
    w.close()


def test_sort_results_by_header(app, tmp_path):
    root = tmp_path / "docs"; root.mkdir()
    (root / "b.txt").write_text("слово " * 50, encoding="utf-8")
    (root / "a.txt").write_text("слово", encoding="utf-8")
    (root / "c.txt").write_text("слово " * 5, encoding="utf-8")
    s = load_settings(); s.add_folder(str(root)); save_settings(s)
    w = MainWindow(); w.show(); w.start_index()
    assert wait_until(lambda: w._task is None)
    st = w.search_tab
    st.query.setText("слово"); st.run_search()
    col = lambda: [os.path.basename(st.table.item(r, 0).text()) for r in range(st.table.rowCount())]
    st._header_clicked(0)
    assert col() == ["a.txt", "b.txt", "c.txt"]
    st._header_clicked(0)
    assert col() == ["c.txt", "b.txt", "a.txt"]
    st._header_clicked(1)
    assert col() == ["a.txt", "c.txt", "b.txt"]  # по размеру, по возрастанию
    st.run_search()  # сортировка переживает новый поиск
    assert col() == ["a.txt", "c.txt", "b.txt"]
    st._header_clicked(1); st._header_clicked(1)
    assert st._sort is None
    w.close()


def test_tray_hides_window_instead_of_closing(app, monkeypatch):
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    s = load_settings(); s.tray = True; save_settings(s)
    w = MainWindow(); w.show()
    assert w.tray is not None and w.act_tray.isChecked()
    assert QApplication.quitOnLastWindowClosed() is False
    w.close()
    assert w.isHidden() and w._quitting is False  # окно спрятано, программа живёт
    w.show_and_search()
    assert w.isVisible() and w.tabs.currentIndex() == 0
    w.act_tray.trigger()  # выключили трей: закрытие снова настоящее
    assert load_settings().tray is False and QApplication.quitOnLastWindowClosed() is True
    w.close()
    assert w.isHidden()


def test_tray_unavailable_is_safe(app, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    s = load_settings(); s.tray = True; save_settings(s)
    w = MainWindow()
    assert w.tray is None and not w.act_tray.isEnabled() and not w.act_tray.isChecked()
    w.show(); w.close()
    assert w.isHidden()  # без трея закрытие обычное


def test_hotkey_message_parsing():
    import ctypes
    from ctypes import wintypes
    from filepilot import hotkey
    msg = wintypes.MSG(); msg.message = hotkey.WM_HOTKEY; msg.wParam = hotkey.HOTKEY_ID
    assert hotkey.is_hotkey_message(ctypes.addressof(msg))
    msg.wParam = 1
    assert not hotkey.is_hotkey_message(ctypes.addressof(msg))
    msg.message = 0x0100; msg.wParam = hotkey.HOTKEY_ID
    assert not hotkey.is_hotkey_message(ctypes.addressof(msg))
    assert hotkey.GlobalHotkey(lambda: None).register() is False or hotkey.GlobalHotkey.supported()


def _window_with_files(tmp_path):
    root = tmp_path / "docs"; root.mkdir()
    (root / "big.bin").write_bytes(b"x" * 300_000)
    (root / "small.txt").write_text("договор поставки", encoding="utf-8")
    (root / "other.txt").write_text("договор аренды", encoding="utf-8")
    s = load_settings(); s.add_folder(str(root)); save_settings(s)
    w = MainWindow(); w.show(); w.start_index()
    assert wait_until(lambda: w._task is None)
    return root, w


def test_delete_big_file_from_disk_map(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from filepilot import fileops
    monkeypatch.setattr(fileops, "send2trash", lambda p: os.remove(p))
    root, w = _window_with_files(tmp_path)
    dm = w.disk_tab
    dm.refresh()
    assert dm.table.item(0, 0).text() == str(root / "big.bin")  # самый крупный сверху
    dm.table.selectRow(0)
    # отказ в подтверждении: файл на месте
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)
    dm.trash_selected()
    assert (root / "big.bin").exists()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    dm.trash_selected()
    assert not (root / "big.bin").exists()
    assert all(dm.table.item(r, 0).text() != str(root / "big.bin") for r in range(dm.table.rowCount()))
    assert "В корзину отправлено: 1" in dm.info.text()
    # в режимах «Папки» и «Типы» действий с файлами нет
    dm.modes["types"].setChecked(True)
    assert dm.selected_paths() == []
    w.close()


def test_search_tab_file_actions(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    from filepilot import fileops
    monkeypatch.setattr(fileops, "send2trash", lambda p: os.remove(p))
    root, w = _window_with_files(tmp_path)
    st = w.search_tab
    st.query.setText("договор"); st.run_search()
    assert st.table.rowCount() == 2
    # переименование через диалог
    st.table.selectRow(0)
    target = st.selected_paths()[0]
    other = ({"small.txt", "other.txt"} - {os.path.basename(target)}).pop()  # порядок строк зависит от системы
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("новое.txt", True))
    from filepilot.ui.file_actions import rename_dialog
    rename_dialog(st, target, st._files_changed)
    assert (root / "новое.txt").exists() and "Переименовано" in st.info.text()
    # перенос выбранных файлов
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    st.table.selectAll()
    from filepilot.ui.file_actions import transfer_dialog
    transfer_dialog(st, st.selected_paths(), st._files_changed, copy=False)
    assert sorted(p.name for p in out.iterdir()) == sorted([other, "новое.txt"])
    # меню: для одного файла есть переименование и «Копировать путь», для нескольких нет
    from PySide6.QtWidgets import QMenu
    st.table.selectRow(0)
    from filepilot.ui.file_actions import fill_menu
    one, many = QMenu(), QMenu()
    fill_menu(one, st, st.selected_paths(), lambda m: None)
    fill_menu(many, st, ["a", "b"], lambda m: None)
    assert any("Переименовать" in a.text() for a in one.actions()) and not any("Переименовать" in a.text() for a in many.actions())
    assert any("(2)" in a.text() for a in many.actions())
    assert st.table.rowCount() == 2 and all(str(out) in st.table.item(r, 0).text() for r in range(2))
    # удаление нескольких выбранных
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    st.table.selectAll()
    st.trash_selected()
    assert list(out.iterdir()) == [] and st.table.rowCount() == 0
    w.close()


def test_hotkey_thread_delivers_press_to_callback(app, monkeypatch):
    """Подделываем user32: поток регистрирует сочетание, получает WM_HOTKEY и будит окно через сигнал Qt."""
    import ctypes
    import threading
    import types
    from ctypes import wintypes
    from filepilot import hotkey

    stop = threading.Event()
    calls = {"registered": 0, "unregistered": 0, "msgs": 0}

    def get_message(msg_ptr, *_):
        calls["msgs"] += 1
        if calls["msgs"] == 1:
            m = ctypes.cast(msg_ptr, ctypes.POINTER(wintypes.MSG)).contents
            m.message, m.wParam = hotkey.WM_HOTKEY, hotkey.HOTKEY_ID
            return 1
        stop.wait(5)
        return 0  # WM_QUIT

    class Fn:
        def __init__(self, f): self.f, self.argtypes, self.restype = f, None, None
        def __call__(self, *a): return self.f(*a)

    user32 = types.SimpleNamespace(
        RegisterHotKey=Fn(lambda *a: calls.__setitem__("registered", calls["registered"] + 1) or 1),
        UnregisterHotKey=Fn(lambda *a: calls.__setitem__("unregistered", calls["unregistered"] + 1) or 1),
        GetMessageW=Fn(get_message), PeekMessageW=Fn(lambda *a: 0),
        PostThreadMessageW=Fn(lambda *a: stop.set() or 1))
    kernel32 = types.SimpleNamespace(GetCurrentThreadId=Fn(lambda: 1234))
    monkeypatch.setattr(hotkey.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32, kernel32=kernel32), raising=False)

    pressed = []
    hk = hotkey.GlobalHotkey(lambda: pressed.append(1))
    assert hk.register() and hk.active and calls["registered"] == 1
    wait_until(lambda: pressed)
    assert pressed == [1]
    hk.unregister()
    assert not hk.active and calls["unregistered"] == 1


def test_hotkey_busy_combination_reports_false(app, monkeypatch):
    import ctypes
    import types
    from filepilot import hotkey

    class Fn:
        def __init__(self, f): self.f, self.argtypes, self.restype = f, None, None
        def __call__(self, *a): return self.f(*a)

    user32 = types.SimpleNamespace(RegisterHotKey=Fn(lambda *a: 0), PeekMessageW=Fn(lambda *a: 0), GetMessageW=Fn(lambda *a: 0))
    monkeypatch.setattr(hotkey.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32, kernel32=types.SimpleNamespace(GetCurrentThreadId=Fn(lambda: 1))), raising=False)
    hk = hotkey.GlobalHotkey(lambda: None)
    assert hk.register() is False and not hk.active
