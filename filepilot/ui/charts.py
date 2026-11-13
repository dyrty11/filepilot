"""Кольцевая диаграмма без сторонних библиотек (только QPainter)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..config import human_size
from ..i18n import tr

# Палитра различима на тёмном фоне; серый — «прочее»
COLORS = ["#4c8dff", "#20b2e8", "#7bd88f", "#ffcc66", "#ff8f5a", "#e879a6", "#a78bfa", "#5eead4"]
OTHER_COLOR = "#6b7280"
ROW_H = 22


class DonutChart(QWidget):
    """Данные: список (подпись, размер). Подпись «прочее» передаётся отдельно, её рисуем серым."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[str, int, bool]] = []  # (подпись, размер, это «прочее»)
        self.setMouseTracking(True)
        self.setMinimumWidth(260)

    def set_data(self, top: list[tuple[str, int]], other: int = 0) -> None:
        self.items = [(n, v, False) for n, v in top] + ([(tr("Прочее"), other, True)] if other > 0 else [])
        self.setMinimumHeight(220 + ROW_H * len(self.items))
        self.update()

    def total(self) -> int:
        return sum(v for _, v, _ in self.items)

    def _color(self, i: int) -> QColor:
        return QColor(OTHER_COLOR if self.items[i][2] else COLORS[i % len(COLORS)])

    def _ring(self) -> QRectF:
        side = max(min(self.width() - 24, 200), 60)
        return QRectF((self.width() - side) / 2, 8, side, side)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = self.total()
        ring = self._ring()
        bg = self.palette().window().color()
        if not total:
            p.setPen(self.palette().placeholderText().color())
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr("Нет данных для диаграммы"))
            return
        angle = 90 * 16
        p.setPen(QPen(bg, 2))
        for i, (_, v, _o) in enumerate(self.items):
            span = -round(v / total * 360 * 16)
            p.setBrush(self._color(i))
            p.drawPie(ring, angle, span)
            angle += span
        hole = ring.adjusted(ring.width() * 0.28, ring.height() * 0.28, -ring.width() * 0.28, -ring.height() * 0.28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawEllipse(hole)
        p.setPen(self.palette().text().color())
        p.drawText(hole, Qt.AlignmentFlag.AlignCenter, human_size(total))
        fm = QFontMetrics(self.font())
        y = ring.bottom() + 16
        for i, (name, v, _o) in enumerate(self.items):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color(i))
            p.drawRoundedRect(QRectF(10, y + 4, 12, 12), 3, 3)
            pct = f"{v / total * 100:.1f}%"
            pw = fm.horizontalAdvance(pct)
            p.setPen(self.palette().text().color())
            p.drawText(QPointF(self.width() - 10 - pw, y + 15), pct)
            label = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, max(self.width() - 40 - pw - 10, 30))
            p.drawText(QPointF(30, y + 15), label)
            y += ROW_H

    def slice_at(self, pos) -> int | None:
        total, ring = self.total(), self._ring()
        if not total:
            return None
        c = ring.center()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        dist = math.hypot(dx, dy)
        if dist > ring.width() / 2 or dist < ring.width() * 0.22:
            return None
        ang = math.degrees(math.atan2(dx, -dy)) % 360  # от верха по часовой
        acc = 0.0
        for i, (_, v, _o) in enumerate(self.items):
            acc += v / total * 360
            if ang < acc:
                return i
        return len(self.items) - 1

    def mouseMoveEvent(self, e) -> None:
        i = self.slice_at(e.position())
        if i is None:
            QToolTip.hideText()
            return
        name, v, _o = self.items[i]
        QToolTip.showText(e.globalPosition().toPoint(), f"{name}\n{human_size(v)} ({v / self.total() * 100:.1f}%)", self)
