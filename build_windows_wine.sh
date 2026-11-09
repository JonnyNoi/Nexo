#!/usr/bin/env sh
# Gera Aplicacao/Windows/Nexo.exe a partir do Linux, usando o wine com um Python para Windows.
# (O PyInstaller não faz compilação cruzada; aqui corre o PyInstaller do Windows dentro do wine.)
#   ./build_windows_wine.sh          → prepara o ambiente (só na 1.ª vez) e gera o .exe
#   ./build_windows_wine.sh --setup  → só prepara o ambiente
cd "$(dirname "$0")" || exit 1
command -v wine >/dev/null || { echo "Instale o wine primeiro (ex.: sudo pacman -S wine)."; exit 1; }

PYVER=3.12.10
# fora do ~/.cache: os limpadores de cache apagariam o Python instalado aqui
export WINEPREFIX="${NEXO_WINEPREFIX:-$HOME/.local/share/nexo-wine}"
export WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
PY='C:\Python312\python.exe'
PYDIR="$WINEPREFIX/drive_c/Python312"

if [ ! -f "$PYDIR/python.exe" ]; then
    echo "» A preparar o wine em $WINEPREFIX (só na 1.ª vez)…"
    mkdir -p "$WINEPREFIX"
    wineboot -i >/dev/null 2>&1
    inst="$WINEPREFIX/python-$PYVER-amd64.exe"
    [ -f "$inst" ] || cp "$HOME/.cache/nexo-wine/python-$PYVER-amd64.exe" "$inst" 2>/dev/null || curl -fL --retry 3 -o "$inst" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe" || exit 1
    echo "» A instalar o Python $PYVER para Windows…"
    wine "$inst" /quiet InstallAllUsers=0 TargetDir='C:\Python312' Include_test=0 Include_doc=0 \
         Include_launcher=0 Include_tcltk=0 Shortcuts=0 PrependPath=0 || exit 1
    [ -f "$PYDIR/python.exe" ] || { echo "Falhou a instalação do Python no wine."; exit 1; }
fi
if [ ! -d "$PYDIR/Lib/site-packages/PyInstaller" ]; then
    echo "» A instalar PySide6, psutil e PyInstaller no Python do Windows…"
    wine "$PY" -m pip install -q --disable-pip-version-check -r requirements.txt pyinstaller || exit 1
fi
[ "$1" = "--setup" ] && { echo "Ambiente pronto."; exit 0; }

echo "» A gerar o Nexo.exe…"
mkdir -p Aplicacao/Windows
wine "$PY" -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name Nexo --icon "Z:$PWD/assets/nexo.ico" \
     --distpath 'Aplicacao\Windows' --workpath 'build\windows' --specpath 'build\windows' \
     run_nexo.py || exit 1
echo "Pronto: Aplicacao/Windows/Nexo.exe"
