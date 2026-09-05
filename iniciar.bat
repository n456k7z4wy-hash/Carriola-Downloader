@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Execute instalar.bat primeiro.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m carriola_downloader
