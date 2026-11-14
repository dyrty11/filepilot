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
