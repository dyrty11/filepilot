"""Делает скриншоты окон для README и сайта на демо-данных: python scripts/make_screenshots.py
Результат: docs/screenshots/{search,duplicates,diskmap,rules,rules-dry}-{ru,en}.png. Личные данные не используются:
всё создаётся во временной папке. Нужен PySide6, запускается без экрана (QT_QPA_PLATFORM=offscreen)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FILEPILOT_NO_UPDATE_CHECK"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots"

DEMO = {
    "ru": dict(docs="Документы", dl="Загрузки", media="Музыка", work="Проекты", query="договор",
               q_files={"Договор поставки 2024.txt": "Договор поставки № 15 от 12.03.2024. Поставщик обязуется передать товар, а покупатель оплатить договор в срок.",
                        "Смета проекта.txt": "Смета проекта: работы, материалы, итоговая сумма по договору поставки.",
                        "Заметки.md": "# Заметки\nПозвонить клиенту по договору 2024 и уточнить сроки."},
               saved="Договоры", rules=[("Архив установщиков", "archive", [".exe", ".msi"]), ("Видео в отдельную папку", "move", [".mkv"])]),
    "en": dict(docs="Documents", dl="Downloads", media="Music", work="Projects", query="contract",
               q_files={"Supply contract 2024.txt": "Supply contract No. 15 of 12.03.2024. The supplier undertakes to deliver the goods and the buyer to pay under the contract on time.",
                        "Project estimate.txt": "Project estimate: work, materials, total amount under the supply contract.",
                        "Notes.md": "# Notes\nCall the client about the 2024 contract and confirm the dates."},
               saved="Contracts", rules=[("Archive installers", "archive", [".exe", ".msi"]), ("Videos to a separate folder", "move", [".mkv"])]),
}


def make_tree(base: Path, d: dict) -> None:
    for sub in (d["docs"], d["dl"], d["media"], d["work"]):
        (base / sub).mkdir(parents=True)
    for name, text in d["q_files"].items():
        (base / d["docs"] / name).write_text(text, encoding="utf-8")
    spec = [(d["work"], "a%d.py", 12, 40_000), (d["work"], "d%d.docx", 5, 150_000), (d["media"], "t%d.mp3", 6, 700_000),
            (d["media"], "c%d.flac", 2, 2_500_000), (d["dl"], "p%d.png", 8, 90_000), (d["docs"], "n%d.xlsx", 4, 60_000),
            (d["docs"], "z%d.zip", 3, 500_000), (d["dl"], "setup%d.exe", 1, 900_000), (d["dl"], "film%d.mkv", 1, 3_000_000)]
    for sub, pat, n, size in spec:
        for i in range(n):
            (base / sub / (pat % i)).write_bytes(os.urandom(size))
    same = os.urandom(200_000)
    (base / d["dl"] / "photo.jpg").write_bytes(same)
    (base / d["docs"] / "photo copy.jpg").write_bytes(same)
    (base / d["media"] / "photo old.jpg").write_bytes(same)


def shoot(lang: str) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from filepilot import i18n, rules
    from filepilot.settings import Settings, save_settings
    from filepilot.ui.main_window import MainWindow
    from filepilot.ui.theme import apply_dark

    tmp = Path(tempfile.mkdtemp(prefix="fp-shots-"))
    os.environ["FILEPILOT_DATA_DIR"] = str(tmp / "data")
    d, base = DEMO[lang], Path(tempfile.gettempdir()) / "FilePilotDemo"  # короткий путь, чтобы на снимках не было случайных имён
    shutil.rmtree(base, ignore_errors=True)
    make_tree(base, d)
    i18n.set_language(lang)
    save_settings(Settings(folders=[str(base)], language=lang, saved_searches=[{"name": d["saved"], "query": d["query"]}]))
    rules.save_rules([rules.Rule(name=n, action=a, folder=str(base / d["dl"]), ext=e, dest=str(base / "Archive" / str(i)))
                      for i, (n, a, e) in enumerate(d["rules"])])
    app = QApplication.instance() or QApplication([])
    apply_dark(app)
    w = MainWindow()
    w.resize(1100, 730)
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    w.start_index()
    wait(2500)
    save = lambda name: w.grab().save(str(OUT / f"{name}-{lang}.png"))  # noqa: E731
    t = w.search_tab
    t.refresh_saved(d["saved"])
    t.query.setText(d["query"])
    t.run_search()
    t.table.selectRow(0)
    wait(300)
    save("search")
    w.tabs.setCurrentIndex(1)
    w.dupes_tab.start()
    wait(1500)
    w.dupes_tab.keep.setCurrentIndex(w.dupes_tab.keep.findData("oldest"))
    w.dupes_tab.btn_mark.click()
    save("duplicates")
    w.tabs.setCurrentIndex(2)
    w.disk_tab.modes["types"].setChecked(True)
    wait(400)
    save("diskmap")
    w.tabs.setCurrentIndex(3)
    wait(300)
    save("rules")
    from filepilot.ui import rules_tab as rt
    shown = []
    rt.PreviewDialog.exec = lambda self: (self.show(), shown.append(self), 0)[-1]  # не блокируем: нужен только снимок
    w.rules_tab.table.selectRow(0)
    w.rules_tab.run(dry=True)
    wait(1200)
    if shown:
        shown[0].resize(900, 250)
        wait(200)
        shown[0].grab().save(str(OUT / f"rules-dry-{lang}.png"))
        shown[0].close()
    w.close()
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    for lang in ("ru", "en"):
        shoot(lang)
    print("готово:", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))
