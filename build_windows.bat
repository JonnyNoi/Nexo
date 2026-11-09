@echo off
REM Gera Aplicacao\Windows\Nexo.exe (ficheiro unico, nao precisa de Python no outro PC)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (py -3 -m venv .venv || python -m venv .venv)
.venv\Scripts\pip install -q -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed --uac-admin --name Nexo --icon "%~dp0assets\nexo.ico" ^
    --distpath Aplicacao\Windows --workpath build\windows --specpath build\windows run_nexo.py
echo.
echo Pronto: Aplicacao\Windows\Nexo.exe
pause
