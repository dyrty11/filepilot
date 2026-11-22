# Changelog (English)

Full history in Russian: [CHANGELOG.md](CHANGELOG.md).

## 0.10.1
- Duplicates: files smaller than 1 KB are no longer checked by default. Tiny files such as Firefox's empty `{}` are almost always identical without being real copies. Change the limit in the "At least" box (0 includes everything); on the command line it is `--min-kb`.
- Hotkey Ctrl+Alt+F: turning it on now also turns on running in the tray; before, closing the window quit the program and the key stopped working. If the combination is taken, the status bar shows the error code.

## 0.10.0
- New Rust core: folder scanning, text extraction (txt, code, docx, xlsx, pptx, odt) and the file comparison behind duplicate search run in parallel on all CPU cores. If the core fails to load, FilePilot falls back to the previous code, just slower.
- Duplicates: only files with the same extension are compared by default. Before, `test.exe` and `test.bat` with identical content ended up in one group, and deleting such "copies" is unsafe. Untick "Same extension only" to widen the search; on the command line use `filepilot dupes --any-ext`.
- Hotkey Ctrl+Alt+F rewritten: a dedicated thread now listens for it and the window is forced to the foreground. Before, the key press might never reach the window.
- Faster index writing: bigger cache and larger batches.

## 0.9.0
- Tray icon: the "Window" menu → "Minimize to tray on close". The close button hides the window while indexing and the background refresh keep running. Click the icon to open the window; right-click gives "Open and search", "Index" and "Quit".
- Hotkey Ctrl+Alt+F (Windows, turned on in the "Window" menu): shows the FilePilot window and puts the cursor in the search box from any program. If another program already uses the combination, FilePilot tells you.
- Both features are off by default.
- File actions: right-click (or Delete) on a found file and in the "Largest files" list of the disk map. "Move to Recycle Bin" with confirmation (always the bin, never permanent), "Move to folder", "Copy to folder", "Rename". You can select several files at once. The index updates right away: a renamed or moved file is found at its new path without re-indexing.

## 0.8.0
- The `newer:7` operator in the search box: only files changed in the last 7 days (the counterpart of `older:`).
- The `name:invoice` operator searches the file name only, not the contents: `name:invoice ext:pdf`.
- Search results sort by clicking a column header (path, size, date): ascending, descending, then back to relevance. The choice is kept between searches.
- A "Compact index" button (and the `filepilot optimize` command): the index is compacted and free space goes back to the disk. The index size is shown in the status line and in `filepilot stats`.

## 0.7.0
- Indexing a whole drive is now safe and faster: system folders at the drive root (Windows, Program Files, ProgramData, Recycle Bin) and AppData are skipped, junctions are not followed, and cloud placeholders (OneDrive etc.) are not read so nothing gets downloaded.
- Folder scanning is faster: size and dates come straight from the scan with no extra disk calls (50,000 files are scanned in a fraction of a second). The progress counter no longer floods the UI, and a re-index shows a percentage based on the previous pass.
- Indexing runs at lower priority, so the computer stays responsive.
- Adding a whole drive now shows a warning about how long it takes and asks for confirmation.

## 0.6.0
- Operators in the search box: `ext:pdf,docx`, `in:"C:\Folder"`, `older:30`, `bigger:5mb`, `smaller:100kb`. They override the Filters panel; a quoted phrase is searched as is. They work in the command line too.
- Query history: Enter or Find saves the query (last 20), suggestions appear as you type.
- Drag folders from Explorer into the app window: they are added to the index and indexing starts by itself.
- CSV export for the duplicates list and the disk map table (opens in Excel right away, UTF-8 with BOM, `;` separator).
- README: install and quick start come first; running from source, command line and build moved to a "For developers" section.

## 0.5.0
- Index exclusions: in the Folders window you can exclude a whole folder or a name mask (`node_modules`, `*.tmp`, `~$*`). Files already indexed from excluded places are removed from the index on the next run. Command line: `filepilot exclude add|remove|list`.
- Search inside one folder: a "Folder" list in the Filters panel (default "All folders"). The choice is saved with saved searches. Command line: `filepilot search ... --folder <path>`.
