import ast
import re
from pathlib import Path

from filepilot import i18n
from filepilot.i18n_en import EN

CY = re.compile("[А-Яа-яЁё]")
SRC = Path(__file__).resolve().parent.parent / "filepilot"


def _keys():
    keys = set()
    for f in list((SRC / "ui").glob("*.py")) + [SRC / "search.py", SRC / "config.py"]:
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args and isinstance(n.args[0], ast.Constant):
                keys.add(n.args[0].value)
    return {k for k in keys if CY.search(k)}


def test_every_tr_string_has_english():
    missing = sorted(k for k in _keys() if k not in EN)
    assert not missing, missing


def test_translations_are_english_and_keep_placeholders():
    for ru, en in EN.items():
        if "C:\\" not in ru:
            assert not CY.search(en), (ru, en)
        assert re.findall(r"\{\d\}", ru) == re.findall(r"\{\d\}", en) or sorted(re.findall(r"\{\d\}", ru)) == sorted(re.findall(r"\{\d\}", en)), ru


def test_no_untranslated_literals_in_ui():
    """Любая русская строка в ui/*.py должна быть аргументом tr() (кроме docstring и аргументов plural)."""
    for f in (SRC / "ui").glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        ok = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("tr", "plural"):
                for c in ast.walk(n):
                    ok.add(id(c))
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr):
                ok.add(id(n.body[0].value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and CY.search(n.value) and id(n) not in ok and not n.value.startswith(("Language", "Restart", "Auto /", "Русский")):
                raise AssertionError(f"{f.name}:{n.lineno}: {n.value!r}")


def test_switching_language():
    i18n.set_language("en")
    assert i18n.tr("Поиск") == "Search"
    assert i18n.tr("Нет такой строки") == "Нет такой строки"
    assert i18n.plural(1, ("copy", "copies"), ("а", "б", "в")) == "copy"
    assert i18n.plural(3, ("copy", "copies"), ("а", "б", "в")) == "copies"
    i18n.set_language("ru")
    assert i18n.tr("Поиск") == "Поиск"
    assert i18n.plural(3, ("copy", "copies"), ("копия", "копии", "копий")) == "копии"
    assert i18n.resolve("en") == "en" and i18n.resolve("xx") in ("ru", "en")


def test_ui_builds_in_english(tmp_path):
    from PySide6.QtWidgets import QApplication
    from filepilot.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    i18n.set_language("en")
    w = MainWindow()
    assert w.tabs.tabText(0) == "Search" and w.tabs.tabText(3) == "Rules"
    assert "index is empty" in w.status.text()
    w.close()
