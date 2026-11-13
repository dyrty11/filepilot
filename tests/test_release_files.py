import re
import sys
from pathlib import Path

from filepilot import __version__

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_installer_default_version_matches_package():
    raw = (ROOT / "installer.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "installer.iss должен быть в UTF-8 с BOM (русские строки)"
    m = re.search(r'#define MyAppVersion "([\d.]+)"', raw.decode("utf-8-sig"))
    assert m and m.group(1) == __version__


def test_installer_files_exist():
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8-sig")
    for rel in re.findall(r"assets\\([\w.-]+\.(?:bmp|ico))", iss):
        assert (ROOT / "assets" / rel).exists(), rel
    assert (ROOT / "LICENSE").exists()


def test_release_notes_section():
    import release_notes
    log = "# История\n\n## Не выпущено\n- новое\n\n## 0.2.0\nПрограмма.\n- а\n\n## 0.1.0\n- старое\n"
    assert release_notes.section("0.2.0", log) == "Программа.\n- а"
    assert release_notes.section("9.9.9", log) == ""
