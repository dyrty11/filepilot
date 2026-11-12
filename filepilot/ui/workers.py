"""Фоновые задачи: интерфейс не зависает, а задачу можно отменить."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal


class Task(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent=None):
        """fn(progress, should_cancel) -> результат. progress(i, total, text)."""
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = self._fn(self.progress.emit, lambda: self._cancel)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        self.done.emit(result)
