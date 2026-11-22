"""Rust-ядро должно давать тот же результат, что и Python-код. Без сборки ядра тесты пропускаются
(в CI задана FILEPILOT_REQUIRE_NATIVE=1: там отсутствие ядра считается ошибкой)."""
import os
import zipfile
from pathlib import Path

import pytest

from filepilot import config, extractors, indexer, native

if os.environ.get("FILEPILOT_REQUIRE_NATIVE"):
    assert native.available(), "Rust-ядро не собрано: python scripts/build_native.py"
pytestmark = pytest.mark.skipif(not native.available(), reason="Rust-ядро не собрано")


def _docs(root: Path) -> None:
    (root / "a").mkdir(parents=True)
    (root / "a" / "u8.txt").write_text("Привет, мир", encoding="utf-8")
    (root / "a" / "cp.txt").write_bytes("договор №5".encode("cp1251"))
    (root / "a" / "u16.txt").write_bytes(b"\xff\xfe" + "отчёт".encode("utf-16-le"))
    (root / "a" / "bin.txt").write_bytes(b"abc\x00\x01def")
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(root / "a" / "d.docx", "w") as z:
        z.writestr("word/document.xml", f"<w:document {ns}><w:body><w:p><w:r><w:t>Первый &amp; абзац</w:t></w:r></w:p>"
                                         "<w:p><w:r><w:t>Второй</w:t></w:r></w:p></w:body></w:document>")
        z.writestr("word/header1.xml", f"<w:hdr {ns}><w:p><w:r><w:t>Шапка</w:t></w:r></w:p></w:hdr>")
        z.writestr("word/media.xml", "<x>не берём</x>")
    with zipfile.ZipFile(root / "a" / "t.xlsx", "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>Цена</t></si><si><r><t>Ито</t></r><r><t>го</t></r></si></sst>")
    (root / "a" / "fake.docx").write_bytes(b"not a zip")


def test_extract_matches_python(tmp_path):
    _docs(tmp_path)
    paths = sorted(str(p) for p in (tmp_path / "a").iterdir())
    got = extractors.extract_many(paths)
    for p, text in zip(paths, got):
        assert text == extractors.extract_text(Path(p)), p


def test_extract_tolerates_broken_files(tmp_path):
    bad = tmp_path / "broken.docx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:p>не закрыт")
    fake = tmp_path / "fake.docx"
    fake.write_bytes(b"not a zip")
    out = extractors.extract_many([str(bad), str(fake), str(tmp_path / "нет.txt")])
    assert out[0] in (None, "не закрыт")  # Rust отдаёт то, что успел прочитать; Python сдаётся целиком
    assert out[1:] == [None, None]


def test_extract_cuts_at_char_limit(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("я" * 100, encoding="utf-8")
    out = native.module().extract_many([str(f)], 10, 1000, [".txt"])
    assert out == ["я" * 10]


def _scan_native(root, exclude=()):
    batches = indexer._NativeBatches(str(root), exclude)
    return sorted(it[0] for b in batches for it in b)


def test_scan_matches_python(tmp_path):
    for d in ("keep", "node_modules", ".hidden", "AppData", "keep/deep", "skipme"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "f.txt").write_text("x", encoding="utf-8")
        (tmp_path / d / "~$tmp.doc").write_text("x", encoding="utf-8")
    exclude = ["*.TMP", "~$*", str(tmp_path / "skipme")]
    py = sorted(p for p, *_ in indexer.scan(str(tmp_path), exclude))
    assert _scan_native(tmp_path, exclude) == py
    assert _scan_native(tmp_path) == sorted(p for p, *_ in indexer.scan(str(tmp_path)))


def test_scan_fields(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("12345", encoding="utf-8")
    (path, name, size, mtime, ctime, cloud), = [it for b in indexer._NativeBatches(str(tmp_path), ()) for it in b]
    st = f.stat()
    assert (path, name, size, cloud) == (str(f), "a.txt", 5, False)
    assert abs(mtime - st.st_mtime) < 1 and abs(ctime - st.st_ctime) < 1


@pytest.mark.skipif(os.name == "nt", reason="символьные ссылки на Windows требуют прав")
def test_scan_does_not_follow_symlinks(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f.txt").write_text("x", encoding="utf-8")
    os.symlink(tmp_path / "real", tmp_path / "link")
    os.symlink(tmp_path / "real" / "f.txt", tmp_path / "flink.txt")
    assert _scan_native(tmp_path) == [str(tmp_path / "real" / "f.txt")]


def test_cancel_stops_scan(tmp_path):
    for i in range(50):
        (tmp_path / f"d{i}").mkdir()
        (tmp_path / f"d{i}" / "f.txt").write_text("x", encoding="utf-8")
    b = indexer._NativeBatches(str(tmp_path), ())
    b.cancel()
    list(b)  # не должно зависнуть


def test_hash_many(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b"x" * (3 << 20))
    b.write_bytes(b"x" * (3 << 20))
    c.write_bytes(b"x" * (2 << 20) + b"y" * (1 << 20))  # первый мегабайт тот же, дальше разное
    nat = native.module()
    ha, hb, hc = nat.hash_many([str(a), str(b), str(c)], True)
    assert ha == hb != hc
    pa, pb, pc = nat.hash_many([str(a), str(b), str(c)], False)
    assert pa == pb == pc  # частичный хеш смотрит только первый мегабайт
    assert nat.hash_many([str(tmp_path / "нет")], True) == [None]


def test_decode_bytes_matches_python():
    for raw in ("Привет".encode("utf-8"), "Привет".encode("cp1251"), b"\xef\xbb\xbfabc", b"\xff\xfe" + "да".encode("utf-16-le")):
        assert native.module().decode_bytes(raw) == extractors.decode_bytes(raw)
