@echo off
setlocal
cd /d "%~dp0"

echo === 1/5  Зависимости ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller pytest
if errorlevel 1 goto :err

echo === 2/5  Тесты ===
set QT_QPA_PLATFORM=offscreen
python -m pytest -q
if errorlevel 1 goto :err

echo === 3/5  Сборка EXE ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean filepilot.spec
if errorlevel 1 goto :err

echo === 4/5  Портативная версия ===
xcopy /E /I /Y "dist\FilePilot" "dist\FilePilot-Portable" >nul
type nul > "dist\FilePilot-Portable\portable.flag"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\FilePilot-Portable' -DestinationPath 'dist\FilePilot-Portable.zip' -Force"
if errorlevel 1 goto :err

echo === 5/5  Установщик (нужен Inno Setup 6) ===
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
) else (
    echo Inno Setup не найден, установщик пропущен.
)

echo.
echo === Контрольные суммы SHA-256 ===
powershell -NoProfile -Command "Get-ChildItem dist\*.zip, dist\installer\*.exe | Get-FileHash -Algorithm SHA256 | ForEach-Object { '{0}  {1}' -f $_.Hash.ToLower(), (Split-Path $_.Path -Leaf) }"
echo.
echo Готово: dist\FilePilot\FilePilot.exe
exit /b 0

:err
echo Сборка прервана из-за ошибки.
exit /b 1
