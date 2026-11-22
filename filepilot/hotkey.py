"""Глобальная горячая клавиша Windows (Ctrl+Alt+F): показать окно FilePilot и сразу искать.

Работает только на Windows и без внешних библиотек. Сочетание ловит отдельный поток со своим циклом сообщений
(RegisterHotKey + GetMessage), а в окно оно попадает сигналом Qt: так не зависим от того, как именно версия Qt
отдаёт системные сообщения."""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Qt, Signal

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
HOTKEY_ID = 0x4650  # «FP»
HOTKEY_TEXT = "Ctrl+Alt+F"


def is_hotkey_message(address: int, hotkey_id: int = HOTKEY_ID) -> bool:
    """Читает структуру MSG по адресу и проверяет, что это наша горячая клавиша."""
    msg = wintypes.MSG.from_address(address)
    return msg.message == WM_HOTKEY and msg.wParam == hotkey_id


def bring_to_front(hwnd: int) -> None:
    """Windows не даёт окну фоновой программы выйти вперёд. Короткое нажатие Alt снимает это ограничение."""
    if sys.platform != "win32":
        return
    try:
        u = ctypes.windll.user32
        u.keybd_event(0x12, 0, 0, 0)       # Alt вниз
        u.SetForegroundWindow(wintypes.HWND(hwnd))
        u.keybd_event(0x12, 0, 0x0002, 0)  # Alt вверх
    except Exception:
        pass


class GlobalHotkey(QObject):
    _fired = Signal()

    def __init__(self, callback) -> None:
        super().__init__()
        self._fired.connect(callback, Qt.ConnectionType.QueuedConnection)
        self.active = False
        self._thread: threading.Thread | None = None
        self._tid = 0

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32"

    def _run(self, ready: threading.Event, result: list) -> None:
        try:
            self._loop(ready, result)
        except Exception:
            if not ready.is_set():
                result.append(False)
                ready.set()

    def _loop(self, ready: threading.Event, result: list) -> None:
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = ctypes.c_int
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        k.GetCurrentThreadId.restype = wintypes.DWORD
        msg = wintypes.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0x0400, 0x0400, 0)  # создаём очередь сообщений потока
        self._tid = int(k.GetCurrentThreadId())
        ok = bool(u.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("F")))
        result.append(ok)
        ready.set()
        if not ok:
            return
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._fired.emit()
        finally:
            u.UnregisterHotKey(None, HOTKEY_ID)

    def register(self) -> bool:
        """False, если сочетание уже занято другой программой или система не Windows."""
        if self.active:
            return True
        if not self.supported():
            return False
        ready, result = threading.Event(), []
        self._thread = threading.Thread(target=self._run, args=(ready, result), name="filepilot-hotkey", daemon=True)
        self._thread.start()
        ready.wait(3)
        self.active = bool(result and result[0])
        if not self.active:
            self._thread = None
        return self.active

    def unregister(self) -> None:
        if not self.active:
            return
        ctypes.windll.user32.PostThreadMessageW(wintypes.DWORD(self._tid), WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(1)
        self._thread = None
        self.active = False
