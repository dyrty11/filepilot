"""Проверка и установка обновлений через GitHub Releases.

Что делает: один GET-запрос к api.github.com за последним релизом, при согласии пользователя скачивает
установщик с github.com, сверяет SHA-256 с SHA256SUMS.txt из того же релиза и запускает установщик.
Ничего о пользователе не отправляется (только стандартные заголовки HTTP). Всё происходит только по HTTPS
и только с доменами GitHub.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import __version__
from .config import is_portable

REPO = os.environ.get("FILEPILOT_UPDATE_REPO", "dyrty11/filepilot")
API_URL = "https://api.github.com/repos/{repo}/releases/latest"
ALLOWED_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
INSTALLER_RE = re.compile(r"^FilePilotSetup-[\d.]+\.exe$", re.IGNORECASE)
SUMS_NAME = "SHA256SUMS.txt"
CHECK_INTERVAL = 24 * 3600
MAX_INSTALLER_BYTES = 500 * 1024 * 1024


class UpdateError(Exception):
    """Понятная пользователю ошибка проверки или загрузки."""


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page_url: str
    installer_name: str | None = None
    installer_url: str | None = None
    installer_size: int = 0
    sums_url: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (text or "").split("-")[0])
    return tuple(int(n) for n in nums) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def due(last_check: float, now: float | None = None) -> bool:
    return (now if now is not None else time.time()) - (last_check or 0) >= CHECK_INTERVAL


def _check_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" or (u.hostname or "") not in ALLOWED_HOSTS:
        raise UpdateError(f"Адрес не разрешён: {url}")


def _open(url: str, timeout: float = 15.0):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": f"FilePilot/{__version__}", "Accept": "application/vnd.github+json, */*"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (схема и хост проверены выше)
    except Exception as e:  # noqa: BLE001
        raise UpdateError(str(e)) from e
    _check_url(resp.geturl())  # после редиректов тоже только GitHub
    return resp


def fetch_latest(repo: str | None = None, opener: Callable = _open) -> Release | None:
    """Последний релиз или None, если релизов ещё нет."""
    url = API_URL.format(repo=repo or REPO)
    try:
        with opener(url) as resp:
            data = json.loads(resp.read(2_000_000).decode("utf-8"))
    except UpdateError as e:
        if "404" in str(e):
            return None
        raise
    except ValueError as e:
        raise UpdateError("Неожиданный ответ сервера") from e
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    rel = Release(version=".".join(map(str, parse_version(tag))), tag=tag, notes=str(data.get("body") or ""),
                  page_url=str(data.get("html_url") or f"https://github.com/{repo or REPO}/releases"))
    for a in data.get("assets") or []:
        name, link = str(a.get("name", "")), str(a.get("browser_download_url", ""))
        if INSTALLER_RE.match(name):
            rel.installer_name, rel.installer_url, rel.installer_size = name, link, int(a.get("size") or 0)
        elif name == SUMS_NAME:
            rel.sums_url = link
    return rel


def parse_sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_installer(rel: Release, progress: Callable | None = None, should_cancel: Callable | None = None,
                       opener: Callable = _open, dest_dir: Path | None = None) -> Path:
    """Скачивает установщик и проверяет контрольную сумму. При любой неудаче файл удаляется."""
    if not rel.installer_url or not rel.installer_name:
        raise UpdateError("В релизе нет установщика.")
    if not rel.sums_url:
        raise UpdateError("В релизе нет SHA256SUMS.txt: без контрольной суммы установщик не запускается.")
    with opener(rel.sums_url) as r:
        expected = parse_sums(r.read(100_000).decode("utf-8", "replace")).get(rel.installer_name)
    if not expected:
        raise UpdateError("Для установщика нет контрольной суммы.")
    folder = dest_dir or Path(tempfile.gettempdir()) / "FilePilotUpdate"
    folder.mkdir(parents=True, exist_ok=True)
    dest, part = folder / rel.installer_name, folder / (rel.installer_name + ".part")
    try:
        with opener(rel.installer_url, 30.0) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or rel.installer_size or 0)
            if total > MAX_INSTALLER_BYTES:
                raise UpdateError("Файл слишком большой.")
            done = 0
            while True:
                if should_cancel and should_cancel():
                    raise UpdateError("Загрузка отменена.")
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_INSTALLER_BYTES:
                    raise UpdateError("Файл слишком большой.")
                out.write(chunk)
                if progress:
                    progress(done, total, rel.installer_name)
        if sha256_file(part) != expected:
            raise UpdateError("Контрольная сумма не совпала: файл повреждён, установка отменена.")
        os.replace(part, dest)
        return dest
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def can_self_install() -> bool:
    """Установщик запускаем только в установленной Windows-версии; портативную и запуск из исходников обновляют вручную."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False)) and not is_portable()


def launch_installer(path: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART", "/RELAUNCH=1"], close_fds=True, creationflags=flags)  # noqa: S603
