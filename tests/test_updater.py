import hashlib
import io
import json

import pytest

from filepilot import updater
from filepilot.settings import Settings, load_settings, save_settings


class FakeResp(io.BytesIO):
    def __init__(self, data: bytes, url="https://github.com/x"):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url


def make_release(installer: bytes, sums_ok=True):
    name = "FilePilotSetup-9.9.9.exe"
    digest = hashlib.sha256(installer).hexdigest() if sums_ok else "0" * 64
    api = {"tag_name": "v9.9.9", "body": "Что нового", "html_url": "https://github.com/dyrty11/filepilot/releases/tag/v9.9.9",
           "assets": [
               {"name": name, "browser_download_url": "https://github.com/dyrty11/filepilot/releases/download/v9.9.9/" + name, "size": len(installer)},
               {"name": "FilePilot-Portable.zip", "browser_download_url": "https://github.com/x/p.zip", "size": 1},
               {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/x/SHA256SUMS.txt", "size": 10}]}
    files = {"api.github.com": json.dumps(api).encode(), "SHA256SUMS.txt": f"{digest}  {name}\n".encode(), name: installer}

    def opener(url, timeout=15):
        for key, data in files.items():
            if key in url:
                return FakeResp(data)
        raise updater.UpdateError("HTTP Error 404: Not Found")
    return opener


def test_versions():
    assert updater.parse_version("v0.10.1") == (0, 10, 1)
    assert updater.is_newer("0.10.0", "0.9.9") and updater.is_newer("v1.0", "0.9.9")
    assert not updater.is_newer("0.2.0", "0.2.0") and not updater.is_newer("0.2", "0.2.0")
    assert updater.due(0) and not updater.due(1000, now=1000 + 60) and updater.due(1000, now=1000 + 90000)


def test_fetch_latest_picks_assets():
    rel = updater.fetch_latest("dyrty11/filepilot", opener=make_release(b"data"))
    assert rel.version == "9.9.9" and rel.installer_name == "FilePilotSetup-9.9.9.exe" and rel.sums_url.endswith("SHA256SUMS.txt")


def test_fetch_latest_no_releases_is_none():
    def opener(url, timeout=15):
        raise updater.UpdateError("HTTP Error 404: Not Found")
    assert updater.fetch_latest("a/b", opener=opener) is None


def test_download_verifies_checksum(tmp_path):
    data = b"installer-bytes" * 1000
    rel = updater.fetch_latest(opener=make_release(data))
    seen = []
    p = updater.download_installer(rel, progress=lambda d, t, n: seen.append(d), opener=make_release(data), dest_dir=tmp_path)
    assert p.read_bytes() == data and seen and not list(tmp_path.glob("*.part"))


def test_download_rejects_bad_checksum_and_cleans_up(tmp_path):
    data = b"x" * 5000
    op = make_release(data, sums_ok=False)
    rel = updater.fetch_latest(opener=op)
    with pytest.raises(updater.UpdateError, match="Контрольная сумма"):
        updater.download_installer(rel, opener=op, dest_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_requires_sums_and_can_cancel(tmp_path):
    op = make_release(b"abc" * 100)
    rel = updater.fetch_latest(opener=op)
    rel.sums_url = None
    with pytest.raises(updater.UpdateError):
        updater.download_installer(rel, opener=op, dest_dir=tmp_path)
    rel = updater.fetch_latest(opener=op)
    with pytest.raises(updater.UpdateError, match="отменена"):
        updater.download_installer(rel, should_cancel=lambda: True, opener=op, dest_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_only_github_https_allowed():
    for bad in ("http://github.com/x", "https://evil.example/x", "file:///etc/passwd", "https://github.com.evil.io/x"):
        with pytest.raises(updater.UpdateError):
            updater._check_url(bad)
    updater._check_url("https://objects.githubusercontent.com/a")


def test_parse_sums():
    h = "a" * 64
    assert updater.parse_sums(f"{h}  a.exe\n{h.upper()} *b.zip\nмусор") == {"a.exe": h, "b.zip": h}


def test_update_settings_roundtrip():
    s = Settings(check_updates=False, last_update_check=12.5, skipped_version="1.2.3")
    save_settings(s)
    s2 = load_settings()
    assert (s2.check_updates, s2.last_update_check, s2.skipped_version) == (False, 12.5, "1.2.3")
