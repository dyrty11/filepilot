"""Тёмная тема и общие помощники интерфейса."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#4c8dff"
HIGHLIGHT = "#ffcc66"


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / rel


def app_icon() -> QIcon:
    p = resource_path("assets/icon.png")
    return QIcon(str(p)) if p.exists() else QIcon()


def apply_dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: "#1f1f1f", QPalette.ColorRole.WindowText: "#e6e6e6",
        QPalette.ColorRole.Base: "#262626", QPalette.ColorRole.AlternateBase: "#2b2b2b",
        QPalette.ColorRole.Text: "#e6e6e6", QPalette.ColorRole.Button: "#2f2f2f",
        QPalette.ColorRole.ButtonText: "#e6e6e6", QPalette.ColorRole.ToolTipBase: "#2f2f2f",
        QPalette.ColorRole.ToolTipText: "#e6e6e6", QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: "#8a8a8a",
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#777777"))
    app.setPalette(pal)
    app.setStyleSheet("""
        QToolBar { spacing: 2px; padding: 3px; border: 0; border-bottom: 1px solid #3a3a3a; }
        QToolButton { padding: 5px 10px; border-radius: 4px; }
        QToolButton:hover { background: #343434; }
        QToolButton:checked { background: #2f5a3f; }
        QToolButton:disabled { color: #6f6f6f; }
        QTabBar::tab { padding: 7px 16px; border: 0; border-bottom: 2px solid transparent; }
        QTabBar::tab:selected { border-bottom: 2px solid %s; }
        QTabWidget::pane { border: 0; border-top: 1px solid #3a3a3a; }
        QHeaderView::section { background: #2b2b2b; padding: 5px 8px; border: 0; border-right: 1px solid #3a3a3a; }
        QTableView, QTreeView, QListView { gridline-color: #333; border: 1px solid #3a3a3a; }
        QLineEdit, QSpinBox, QComboBox { padding: 5px 8px; border: 1px solid #444; border-radius: 4px; background: #262626; }
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: %s; }
        QPushButton { padding: 6px 14px; border: 1px solid #444; border-radius: 4px; background: #303030; }
        QPushButton:hover { background: #3a3a3a; }
        QPushButton:default, QPushButton#primary { background: %s; border-color: %s; color: white; }
        QPushButton:disabled { color: #777; background: #2a2a2a; }
        QGroupBox { border: 1px solid #3a3a3a; border-radius: 4px; margin-top: 10px; padding-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QProgressBar { border: 1px solid #444; border-radius: 3px; text-align: center; height: 14px; }
        QProgressBar::chunk { background: %s; }
        QStatusBar { border-top: 1px solid #3a3a3a; }
    """ % (ACCENT, ACCENT, ACCENT, ACCENT, ACCENT))


def open_path(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def reveal_in_folder(path: str) -> None:
    """Показать файл в Проводнике (на других системах откроется папка)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        open_path(str(Path(path).parent))
