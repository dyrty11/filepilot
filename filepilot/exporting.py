"""Общая запись таблиц в CSV: UTF-8 с BOM и разделитель «;», такой файл открывается в Excel без настройки."""
from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence


def write_csv(header: Sequence[str], rows: Iterable[Sequence], dest: str) -> int:
    n = 0
    with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(list(header))
        for row in rows:
            w.writerow(list(row))
            n += 1
    return n
