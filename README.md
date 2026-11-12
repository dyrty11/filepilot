# FilePilot

Локальная программа для Windows: поиск по содержимому файлов, поиск дубликатов, карта диска и правила автосортировки.
Всё работает на вашем компьютере, индекс хранится локально.

> Версия 0.2 пишется заново. Готовы ядро, консольная версия и окно программы. Сборка EXE и установщик в работе.

## Запуск из исходников

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m filepilot --help
```

Запуск окна: `python -m filepilot` (или `python run.py`).

## Возможности

- **Поиск** по содержимому (txt, код, pdf, docx, xlsx, pptx, odt и др.) с фильтрами по расширению, размеру и возрасту файлов.
- **Дубликаты**: сравнение по содержимому, удаление только в корзину, в каждой группе остаётся копия.
- **Карта диска**: крупные файлы, папки и типы файлов.
- **Правила**: перенос, архивация в zip или отправка в корзину с пробным запуском. Окончательного удаления нет.
- **Автоиндекс при запуске**, очистка индекса, отмена индексации.

## Консольные команды

```
python -m filepilot folders add "C:\Users\Вы\Documents"
python -m filepilot index
python -m filepilot search "договор 2024" --ext pdf,docx --older 30
python -m filepilot dupes
python -m filepilot top
python -m filepilot rules run            # пробный запуск
python -m filepilot rules run --apply    # выполнить
```

## Тесты

```
pip install pytest
pytest
```

## Лицензия

MIT, см. `LICENSE`. Интерфейс использует PySide6 (Qt) под лицензией LGPLv3.
