"""Глобальная горячая клавиша Windows (Ctrl+Alt+F): показать окно FilePilot и сразу искать.

Работает только на Windows и без внешних библиотек: RegisterHotKey из user32 + фильтр системных сообщений Qt."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
HOTKEY_ID = 0x4650  # «FP»
HOTKEY_TEXT = "Ctrl+Alt+F"


def is_hotkey_message(address: int, hotkey_id: int = HOTKEY_ID) -> bool:
    """Читает структуру MSG по адресу и проверяет, что это наша горячая клавиша."""
    msg = wintypes.MSG.from_address(address)
    return msg.message == WM_HOTKEY and msg.wParam == hotkey_id


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG") and is_hotkey_message(int(message)):
            self._callback()
            return True, 0
        return False, 0


class GlobalHotkey:
    def __init__(self, callback) -> None:
        self._filter = _Filter(callback)
        self.active = False

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32"

    def register(self) -> bool:
        """False, если сочетание уже занято другой программой или система не Windows."""
        if self.active:
            return True
        if not self.supported():
            return False
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("F")))
        if ok:
            QApplication.instance().installNativeEventFilter(self._filter)
            self.active = True
        return ok

    def unregister(self) -> None:
        if not self.active:
            return
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        QApplication.instance().removeNativeEventFilter(self._filter)
        self.active = False
