@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo Instale o Python 3.11 ou superior pelo python.org e tente novamente.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
    echo A instalacao falhou. Confira o erro acima.
    pause
    exit /b 1
)
echo Instalacao concluida. Use iniciar.bat para abrir o Carriola.
call iniciar.bat
