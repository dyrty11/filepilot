import os
import time
import zipfile
from pathlib import Path

from filepilot import db, diskmap, duplicates, indexer, rules, search
from filepilot.extractors import decode_bytes, extract_text
from filepilot.settings import Settings, load_settings, save_settings


def make_tree(root: Path) -> None:
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "dogovor.txt").write_text("Договор поставки 2024 между сторонами", encoding="utf-8")
    (root / "docs" / "old.log").write_text("старый лог файл", encoding="utf-8")
    (root / "a.txt").write_text("hello world", encoding="utf-8")
    (root / "b.txt").write_text("hello world", encoding="utf-8")  # дубликат a.txt
    (root / "big.bin").write_bytes(b"\x00" * 300_000)


def test_decode_cp1251_and_utf8():
    assert decode_bytes("Привет".encode("cp1251")) == "Привет"
    assert decode_bytes("Привет".encode("utf-8")) == "Привет"
    assert decode_bytes("Привет".encode("utf-16")) == "Привет"


def test_docx_extraction(tmp_path):
    p = tmp_path / "t.docx"
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           "<w:p><w:r><w:t>Первый абзац</w:t></w:r></w:p><w:p><w:r><w:t>Второй</w:t></w:r></w:p></w:body></w:document>")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    text = extract_text(p)
    assert "Первый абзац" in text and "Второй" in text


def test_index_and_search(tmp_path):
    make_tree(tmp_path / "root")
    st = indexer.index_folders([str(tmp_path / "root")])
    assert st["added"] == 5 and st["errors"] == 0
    res = search.search("договор 2024")
    assert [Path(r["path"]).name for r in res] == ["dogovor.txt"]
    assert search.search("догов")  # префиксный поиск
    assert search.search("") == []
    assert search.search('"hello world')  # битая кавычка не ломает поиск


def test_search_snippet_has_no_html(tmp_path):
    root = tmp_path / "r"; root.mkdir()
    (root / "x.txt").write_text("<b>опасно</b> слово ключ", encoding="utf-8")
    indexer.index_folders([str(root)])
    r = search.search("ключ")[0]
    assert search.HL_START in r["snippet"]


def test_filters(tmp_path):
    make_tree(tmp_path / "root")
    indexer.index_folders([str(tmp_path / "root")])
    only_txt = search.search("hello", search.Filters(exts=[".txt"]))
    assert len(only_txt) == 2
    assert search.search("hello", search.Filters(exts=[".pdf"])) == []
    big = search.search("", search.Filters(min_kb=100))
    assert [Path(r["path"]).name for r in big] == ["big.bin"]
    old = tmp_path / "root" / "docs" / "old.log"
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    indexer.index_folders([str(tmp_path / "root")])
    assert [Path(r["path"]).name for r in search.search("", search.Filters(older_days=30))] == ["old.log"]
    assert search.parse_exts("pdf, .DOCX; txt") == [".pdf", ".docx", ".txt"]


def test_reindex_removes_missing_and_skips_unchanged(tmp_path):
    root = tmp_path / "root"; make_tree(root)
    indexer.index_folders([str(root)])
    (root / "a.txt").unlink()
    st = indexer.index_folders([str(root)])
    assert st["removed"] == 1 and st["skipped"] == 4
    assert not search.search("hello", search.Filters(exts=[".txt"]))[1:]  # остался только b.txt


def test_cancel_keeps_index(tmp_path):
    root = tmp_path / "root"; make_tree(root)
    indexer.index_folders([str(root)])
    st = indexer.index_folders([str(root)], should_cancel=lambda: True)
    assert st["cancelled"] and st["removed"] == 0
    assert db.stats()["files"] == 5


def test_clear_index(tmp_path):
    root = tmp_path / "root"; make_tree(root)
    indexer.index_folders([str(root)])
    assert db.clear_index() == 5
    assert search.search("hello") == [] and db.stats()["files"] == 0


def test_duplicates_and_safe_trash(tmp_path, monkeypatch):
    root = tmp_path / "root"; make_tree(root)
    indexer.index_folders([str(root)])
    groups = duplicates.find_duplicates(min_size=1)
    assert len(groups) == 1 and len(groups[0]["files"]) == 2
    trashed = []
    monkeypatch.setattr(duplicates, "send2trash", lambda p: (trashed.append(p), os.remove(p)))
    files = groups[0]["files"]
    done, errs = duplicates.trash_selected([files], set(files))  # пытаемся удалить всё
    assert len(done) == 1 and not errs and len(trashed) == 1       # одна копия обязана остаться
    assert sum(Path(f).exists() for f in files) == 1


def test_diskmap(tmp_path):
    root = tmp_path / "root"; make_tree(root)
    indexer.index_folders([str(root)])
    assert Path(diskmap.top_files(1)[0]["path"]).name == "big.bin"
    folders = diskmap.by_folder([str(root)])
    assert abs(sum(r["share"] for r in folders) - 1) < 1e-9
    assert diskmap.by_type()[0]["ext"] == ".bin"


def test_rule_validate():
    assert rules.Rule(name="").validate()
    assert rules.Rule(name="x", folder="/a").validate()                       # нет условий
    assert rules.Rule(name="x", folder="/a", ext=[".txt"]).validate()         # нет папки назначения
    assert rules.Rule(name="x", folder="/a", ext=[".txt"], dest="/b").validate() is None
    assert rules.Rule(name="x", action="trash", folder="/a", ext=["txt"]).validate() is None


def test_rule_move_dry_run_and_apply_with_name_collision(tmp_path):
    root = tmp_path / "root"; make_tree(root)
    dest = tmp_path / "dest"; dest.mkdir()
    (dest / "a.txt").write_text("уже есть", encoding="utf-8")  # конфликт имён
    indexer.index_folders([str(root)])
    rule = rules.Rule(name="txt", folder=str(root), ext=["txt"], dest=str(dest))
    plan = rules.apply(rule, dry_run=True)
    assert len(plan) == 3 and (root / "a.txt").exists()          # пробный запуск ничего не двигает
    done = rules.apply(rule, dry_run=False)
    assert all("error" not in x for x in done)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "уже есть"  # чужой файл цел
    assert (dest / "a (1).txt").exists()
    assert not (root / "a.txt").exists()
    assert not search.search("hello", search.Filters(exts=[".txt"]))  # из индекса убрано


def test_rule_archive_and_trash(tmp_path, monkeypatch):
    root = tmp_path / "root"; make_tree(root)
    dest = tmp_path / "arch"
    monkeypatch.setattr(rules, "send2trash", lambda p: os.remove(p))
    indexer.index_folders([str(root)])
    rules.apply(rules.Rule(name="arch", action="archive", folder=str(root), ext=[".log"], dest=str(dest)), dry_run=False)
    z = dest / "old.log.zip"
    assert z.exists() and zipfile.ZipFile(z).namelist() == ["old.log"]
    assert not (root / "docs" / "old.log").exists()
    rules.apply(rules.Rule(name="t", action="trash", folder=str(root), pattern="*.BIN"), dry_run=False)
    assert not (root / "big.bin").exists()


def test_settings_and_rules_roundtrip(tmp_path):
    s = Settings(); s.add_folder(str(tmp_path)); s.auto_index = True
    assert not s.add_folder(str(tmp_path))
    save_settings(s)
    assert load_settings().auto_index and load_settings().folders == [os.path.normpath(str(tmp_path))]
    rules.save_rules([rules.Rule(name="r", folder="/x", ext=["pdf"], dest="/y")])
    assert rules.load_rules()[0].name == "r"
    (tmp_path / "data" / "settings.json").write_text("{битый json", encoding="utf-8")
    assert load_settings().folders == []                          # повреждённый файл не роняет программу


def test_cli_roundtrip(tmp_path, capsys):
    from filepilot import cli
    root = tmp_path / "root"; make_tree(root)
    assert cli.main(["folders", "add", str(root)]) == 0
    assert cli.main(["index"]) == 0
    assert cli.main(["--json", "search", "договор"]) == 0
    out = capsys.readouterr().out
    assert "dogovor.txt" in out


def test_preview_content_and_marks(tmp_path):
    make_tree(tmp_path / "root")
    indexer.index_folders([str(tmp_path / "root")])
    path = str(tmp_path / "root" / "docs" / "dogovor.txt")
    text = search.get_content(path)
    assert "Договор поставки" in text
    assert search.get_content(str(tmp_path / "нет.txt")) is None
    marked, n = search.mark_matches(text, "договор AND 2024")
    assert n == 2 and marked.count(search.HL_START) == 2
    assert search.mark_matches(text, "")[1] == 0


def test_export_csv(tmp_path):
    make_tree(tmp_path / "root")
    indexer.index_folders([str(tmp_path / "root")])
    res = search.search("hello")
    dest = tmp_path / "out.csv"
    assert search.export_csv(res, str(dest)) == len(res) == 2
    lines = dest.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("Путь;Имя") and len(lines) == 3


def test_saved_searches_roundtrip():
    s = Settings()
    s.save_search({"name": "а", "query": "x"})
    s.save_search({"name": "а", "query": "y"})  # перезапись по имени
    s.save_search({"name": "б", "query": "z"})
    save_settings(s)
    s2 = load_settings()
    assert [e["query"] for e in s2.saved_searches] == ["y", "z"]
    s2.delete_search("а")
    assert [e["name"] for e in s2.saved_searches] == ["б"]


def test_group_top():
    top, other = diskmap.group_top([("a", 50), ("b", 30), ("c", 10), ("d", 6), ("e", 4), ("z", 0)], top=3)
    assert top == [("a", 50), ("b", 30), ("c", 10)] and other == 10
    assert diskmap.group_top([], 3) == ([], 0)


def test_choose_keep_rules(tmp_path):
    import os
    from filepilot import duplicates
    a, b, c = tmp_path / "b" / "long_name_copy.txt", tmp_path / "a.txt", tmp_path / "c.txt"
    a.parent.mkdir()
    for i, f in enumerate((a, b, c)):
        f.write_text("x")
        os.utime(f, (1_000_000 + i * 100, 1_000_000 + i * 100))   # a — самый старый, c — самый новый
    files = [str(a), str(b), str(c)]
    assert duplicates.choose_keep(files, "first") == sorted(files)[0]
    assert duplicates.choose_keep(files, "oldest") == str(a)
    assert duplicates.choose_keep(files, "newest") == str(c)
    assert duplicates.choose_keep(files, "shortest") == str(b)
    assert duplicates.choose_keep(files, "что-то непонятное") == sorted(files)[0]
    assert duplicates.choose_keep([str(tmp_path / "нет.txt"), str(b)], "newest") == str(b)  # недоступный файл не оставляем


def test_reindex_setting_validated():
    s = Settings(reindex_minutes=60)
    save_settings(s)
    assert load_settings().reindex_minutes == 60
    import json
    from filepilot.config import settings_path
    d = json.loads(settings_path().read_text(encoding="utf-8")); d["reindex_minutes"] = 7
    settings_path().write_text(json.dumps(d), encoding="utf-8")
    assert load_settings().reindex_minutes == 0


def test_exclusions_skip_folders_and_masks(tmp_path):
    root = tmp_path / "root"
    make_tree(root)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.txt").write_text("hello lib", encoding="utf-8")
    (root / "tmp.tmp").write_text("hello tmp", encoding="utf-8")
    skip = str(root / "docs")
    st = indexer.index_folders([str(root)], exclude=["node_modules", "*.TMP", skip])
    names = sorted(r["name"] for r in db.get_db().execute("SELECT name FROM files"))
    assert names == ["a.txt", "b.txt", "big.bin"]
    assert st["total"] == 3


def test_exclusion_removes_already_indexed_files(tmp_path):
    root = tmp_path / "root"
    make_tree(root)
    indexer.index_folders([str(root)])
    assert search.search("Договор")
    indexer.index_folders([str(root)], exclude=[str(root / "docs")])
    assert not search.search("Договор")


def test_path_exclusion_does_not_match_sibling_prefix(tmp_path):
    assert indexer.is_excluded(str(tmp_path / "docs" / "a.txt"), "a.txt", [str(tmp_path / "docs")])
    assert not indexer.is_excluded(str(tmp_path / "docs2" / "a.txt"), "a.txt", [str(tmp_path / "docs")])


def test_search_in_folder_filter(tmp_path):
    root = tmp_path / "root"
    make_tree(root)
    (root / "docs_x").mkdir()
    (root / "docs_x" / "z.txt").write_text("hello other", encoding="utf-8")
    indexer.index_folders([str(root)])
    in_docs = search.search("", search.Filters(folder=str(root / "docs")))
    assert sorted(Path(r["path"]).name for r in in_docs) == ["dogovor.txt", "old.log"]
    assert search.Filters(folder="x").active()
    assert [Path(r["path"]).name for r in search.search("other", search.Filters(folder=str(root / "docs_x")))] == ["z.txt"]
    assert search.search("other", search.Filters(folder=str(root / "docs"))) == []


def test_settings_exclude_roundtrip_and_tolerant_load(tmp_path):
    s = Settings()
    assert s.add_exclude(" node_modules ") and not s.add_exclude("node_modules") and not s.add_exclude("  ")
    save_settings(s)
    assert load_settings().exclude == ["node_modules"]
    assert s.remove_exclude("node_modules") and not s.remove_exclude("node_modules")
    from filepilot.config import settings_path
    settings_path().write_text('{"exclude": "oops"}', encoding="utf-8")
    assert load_settings().exclude == []
