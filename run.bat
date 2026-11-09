@echo off
REM Executa o Nexo no Windows (cria o ambiente virtual na primeira vez)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\pip install -q -r requirements.txt
)
.venv\Scripts\python.exe run_nexo.py %*
