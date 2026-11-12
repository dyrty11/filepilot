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
