import pytest

from filepilot import db


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("FILEPILOT_DATA_DIR", str(tmp_path / "data"))
    db.close_db()
    yield
    db.close_db()
