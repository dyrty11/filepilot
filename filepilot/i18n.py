"""Простая локализация: исходные строки в коде русские, английский перевод лежит в i18n_en.py.

tr("текст") возвращает перевод для выбранного языка. Для строк с подстановкой пишется
tr("Найдено: {0}").format(n): так порядок слов в переводе может отличаться.
"""
from __future__ import annotations

LANGUAGES = {"ru": "Русский", "en": "English"}
_lang: str | None = None


def detect_language() -> str:
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name()
    except Exception:  # noqa: BLE001
        import locale
        name = (locale.getdefaultlocale()[0] or "") if hasattr(locale, "getdefaultlocale") else ""
    return "ru" if name.lower().startswith(("ru", "uk", "be")) else "en"


def resolve(setting: str | None) -> str:
    return setting if setting in LANGUAGES else detect_language()


def set_language(code: str | None) -> str:
    global _lang
    _lang = resolve(code)
    return _lang


def current_language() -> str:
    global _lang
    if _lang is None:
        try:
            from .settings import load_settings
            _lang = resolve(load_settings().language)
        except Exception:  # noqa: BLE001
            _lang = detect_language()
    return _lang


def tr(text: str) -> str:
    if current_language() != "en":
        return text
    from .i18n_en import EN
    return EN.get(text, text)


def plural(n: int, forms_en: tuple[str, str], forms_ru: tuple[str, str, str]) -> str:
    """Форма слова по числу: английский (1 / остальные), русский (1 / 2-4 / 5+)."""
    if current_language() == "en":
        return forms_en[0] if n == 1 else forms_en[1]
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms_ru[0]
    return forms_ru[1] if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else forms_ru[2]
