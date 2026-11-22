"""Быстрое ядро на Rust (filepilot/_native). Если его нет (запуск из исходников без сборки) или оно сломано,
программа работает на чистом Python: медленнее, но с тем же результатом."""
from __future__ import annotations

import os

_native = None
if not os.environ.get("FILEPILOT_NO_NATIVE"):
    try:
        from . import _native  # type: ignore[no-redef]
    except Exception:  # нет сборки под эту платформу: остаёмся на Python
        _native = None


def available() -> bool:
    return _native is not None


def version() -> str | None:
    return getattr(_native, "VERSION", None) if _native is not None else None


def module():
    return _native
