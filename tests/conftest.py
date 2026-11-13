import pytest

from filepilot import db


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("FILEPILOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FILEPILOT_NO_UPDATE_CHECK", "1")  # тесты не ходят в сеть
    db.close_db()
    yield
    db.close_db()


@pytest.fixture(autouse=True)
def russian_ui():
    from filepilot import i18n
    i18n.set_language("ru")
    yield
    i18n.set_language("ru")
