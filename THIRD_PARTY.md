# Сторонние компоненты

| Компонент | Лицензия | Для чего |
|---|---|---|
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython/) (Essentials) | LGPL-3.0 | интерфейс |
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause | текст из PDF |
| [Send2Trash](https://github.com/arsenetar/send2trash) | BSD-3-Clause | отправка файлов в корзину |
| [PyInstaller](https://pyinstaller.org) (только при сборке) | GPL-2.0 с исключением для собираемых программ | упаковка в EXE |

**О Qt и LGPL.** Собранная программа использует библиотеки Qt как отдельные файлы (`.dll` в папке программы), а не вшивает их в `FilePilot.exe`.
Это позволяет заменить их своей сборкой Qt. Исходный код Qt доступен на https://code.qt.io/. Сам FilePilot распространяется под лицензией MIT (см. `LICENSE`).
