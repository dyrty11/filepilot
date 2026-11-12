"""Консольный интерфейс: filepilot <команда>. Удобен для автоматизации и скриптов."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, db, diskmap, duplicates, indexer, rules as rules_mod, search as search_mod
from .config import format_time, human_size
from .settings import load_settings, save_settings


def _out(obj, as_json: bool, lines) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        for line in lines:
            print(line)


def _cmd_folders(a) -> int:
    s = load_settings()
    if a.action == "add":
        for f in a.paths:
            s.add_folder(f)
        save_settings(s)
    elif a.action == "remove":
        for f in a.paths:
            s.remove_folder(f)
        save_settings(s)
    _out(s.folders, a.json, s.folders or ["(папки не добавлены)"])
    return 0


def _cmd_index(a) -> int:
    folders = a.folders or load_settings().folders
    if not folders:
        print("Нет папок. Добавьте: filepilot folders add <путь>", file=sys.stderr)
        return 2
    stats = indexer.index_folders(folders, on_progress=None if a.json else _progress)
    if not a.json:
        print()
    _out(stats, a.json, [f"Файлов: {stats['total']}, новых: {stats['added']}, обновлено: {stats['updated']}, "
                         f"без изменений: {stats['skipped']}, удалено из индекса: {stats['removed']}, ошибок: {stats['errors']}"])
    return 0


def _progress(i: int, total: int, path: str) -> None:
    if i % 50 == 0 or i == total:
        print(f"\r{i}/{total}", end="", file=sys.stderr, flush=True)


def _cmd_search(a) -> int:
    f = search_mod.Filters(exts=search_mod.parse_exts(a.ext or ""), min_kb=a.min_kb, max_kb=a.max_kb, older_days=a.older)
    res = search_mod.search(a.query, f, limit=a.limit)
    for r in res:  # убираем служебные маркеры подсветки в консоли
        r["snippet"] = (r["snippet"] or "").replace(search_mod.HL_START, "[").replace(search_mod.HL_END, "]")
    _out(res, a.json, [f"{r['path']}  ({human_size(r['size'])}, {format_time(r['mtime'])})\n    {r['snippet']}" for r in res] or ["Ничего не найдено."])
    return 0


def _cmd_dupes(a) -> int:
    groups = duplicates.find_duplicates(min_size=a.min_kb * 1024)
    lines = []
    for g in groups:
        lines.append(f"{human_size(g['size'])} x {len(g['files'])}")
        lines.extend(f"    {p}" for p in g["files"])
    _out(groups, a.json, lines or ["Дубликатов нет."])
    return 0


def _cmd_top(a) -> int:
    res = diskmap.top_files(limit=a.limit)
    _out(res, a.json, [f"{human_size(r['size']):>10}  {r['path']}" for r in res])
    return 0


def _cmd_rules(a) -> int:
    rl = rules_mod.load_rules()
    if a.action == "list":
        _out([r.to_dict() for r in rl], a.json, [f"{r.name}: {rules_mod.ACTION_LABELS.get(r.action, r.action)}, {r.folder} -> {r.dest or '-'}" for r in rl] or ["Правил нет."])
        return 0
    selected = [r for r in rl if r.enabled and (not a.name or r.name == a.name)]
    report = []
    for r in selected:
        for act in rules_mod.apply(r, dry_run=not a.apply):
            report.append({"rule": r.name, **act})
    mode = "ПРИМЕНЕНО" if a.apply else "ПРОБНЫЙ ЗАПУСК (ничего не изменено)"
    _out(report, a.json, [mode] + [f"{x['rule']}: {x['file']} -> {x.get('dest') or x['action']}" + (f"  ОШИБКА: {x['error']}" if x.get("error") else "") for x in report])
    return 0


def _cmd_clear(a) -> int:
    n = db.clear_index()
    print(f"Индекс очищен ({n} записей).")
    return 0


def _cmd_stats(a) -> int:
    st = db.stats()
    _out(st, a.json, [f"Файлов в индексе: {st['files']}, объём: {human_size(st['bytes'])}"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="filepilot", description="FilePilot: поиск по содержимому, дубликаты, правила.")
    p.add_argument("--version", action="version", version=f"FilePilot {__version__}")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("folders", help="папки для индексации"); s.add_argument("action", choices=["list", "add", "remove"])
    s.add_argument("paths", nargs="*"); s.set_defaults(func=_cmd_folders)
    s = sub.add_parser("index", help="проиндексировать папки"); s.add_argument("folders", nargs="*"); s.set_defaults(func=_cmd_index)
    s = sub.add_parser("search", help="поиск по содержимому"); s.add_argument("query")
    s.add_argument("--ext"); s.add_argument("--min-kb", type=int); s.add_argument("--max-kb", type=int)
    s.add_argument("--older", type=int, help="старше N дней"); s.add_argument("--limit", type=int, default=50); s.set_defaults(func=_cmd_search)
    s = sub.add_parser("dupes", help="найти дубликаты"); s.add_argument("--min-kb", type=int, default=0); s.set_defaults(func=_cmd_dupes)
    s = sub.add_parser("top", help="самые крупные файлы"); s.add_argument("--limit", type=int, default=30); s.set_defaults(func=_cmd_top)
    s = sub.add_parser("rules", help="правила сортировки"); s.add_argument("action", choices=["list", "run"])
    s.add_argument("--name"); s.add_argument("--apply", action="store_true", help="выполнить (по умолчанию пробный запуск)"); s.set_defaults(func=_cmd_rules)
    s = sub.add_parser("clear", help="очистить индекс"); s.set_defaults(func=_cmd_clear)
    s = sub.add_parser("stats", help="статистика индекса"); s.set_defaults(func=_cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
