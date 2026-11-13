"""Пути, константы и мелкие помощники. Все пути вычисляются при вызове, чтобы их можно было подменить в тестах."""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

APP_NAME = "FilePilot"

# Папки, в которые индексатор не заходит
IGNORED_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".venv", "venv", "env",
    "$RECYCLE.BIN", "System Volume Information",
    ".cache", ".gradle", ".idea", ".vscode",
}

# Расширения, из которых достаём текст
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".htm", ".css", ".scss", ".xml", ".sql",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php",
    ".sh", ".bat", ".ps1", ".env",
}
ZIP_XML_EXTS = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
DOC_EXTS = {".pdf"} | ZIP_XML_EXTS

MAX_CONTENT_CHARS = 2_000_000          # потолок текста на один файл
MAX_CONTENT_FILE_BYTES = 50 * 1024 * 1024  # крупнее: только метаданные
MAX_ZIP_MEMBER_BYTES = 100 * 1024 * 1024    # защита от «архивных бомб»


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    """Портативный режим: рядом с exe лежит файл portable.flag."""
    return is_frozen() and (exe_dir() / "portable.flag").exists()


def data_dir() -> Path:
    override = os.environ.get("FILEPILOT_DATA_DIR")
    if override:
        return Path(override)
    if is_portable():
        return exe_dir() / "FilePilotData"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_NAME


def db_path() -> Path:
    return data_dir() / "index.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def rules_path() -> Path:
    return data_dir() / "rules.json"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)


_UNITS = ["Б", "КБ", "МБ", "ГБ", "ТБ"]


def human_size(n: int | None) -> str:
    if n is None:
        return ""
    from .i18n import tr
    x = float(n)
    for u in _UNITS:
        if x < 1024 or u == _UNITS[-1]:
            return f"{int(x)} {tr(u)}" if u == "Б" else f"{x:.1f} {tr(u)}"
        x /= 1024
    return f"{x:.1f} {tr('ТБ')}"


def format_time(ts: float | None) -> str:
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
