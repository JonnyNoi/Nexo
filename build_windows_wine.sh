#!/usr/bin/env sh
# Gera Aplicacao/Windows/Nexo.exe a partir do Linux, usando o wine com um Python para Windows.
# (O PyInstaller não faz compilação cruzada; aqui corre o PyInstaller do Windows dentro do wine.)
#   ./build_windows_wine.sh          → prepara o ambiente (só na 1.ª vez) e gera o .exe
#   ./build_windows_wine.sh --setup  → só prepara o ambiente
#   ./build_windows_wine.sh --instalador → gera o .exe e também o instalador (Inno Setup)
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
sign() {   # assinatura opcional: NEXO_SIGN_PFX=/caminho/cert.pfx NEXO_SIGN_PASS=… ./build_windows_wine.sh
    [ -n "$NEXO_SIGN_PFX" ] || return 0
    command -v osslsigncode >/dev/null || { echo "Instale o osslsigncode para assinar."; return 1; }
    osslsigncode sign -pkcs12 "$NEXO_SIGN_PFX" -pass "$NEXO_SIGN_PASS" -n Nexo -h sha256 \
        -ts http://timestamp.digicert.com -in "$1" -out "$1.assinado" && mv "$1.assinado" "$1" && echo "Assinado: $1"
}
sign Aplicacao/Windows/Nexo.exe || exit 1
echo "Pronto: Aplicacao/Windows/Nexo.exe"

[ "$1" = "--instalador" ] || exit 0
# ---------------------------------------------------------------- instalador (Inno Setup)
ISVER=7.1.1
ISSHA=8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0
ISCC="$WINEPREFIX/drive_c/InnoSetup/ISCC.exe"
if [ ! -f "$ISCC" ]; then
    echo "» A instalar o Inno Setup $ISVER no wine (só na 1.ª vez)…"
    inst="$WINEPREFIX/innosetup-$ISVER-x64.exe"
    [ -f "$inst" ] || curl -fL --retry 3 -o "$inst" \
        "https://github.com/jrsoftware/issrc/releases/download/is-$(echo $ISVER | tr . _)/innosetup-$ISVER-x64.exe" || exit 1
    echo "$ISSHA  $inst" | sha256sum -c --quiet || { rm -f "$inst"; echo "SHA-256 do Inno Setup não confere."; exit 1; }
    wine "$inst" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR='C:\InnoSetup' || exit 1
    [ -f "$ISCC" ] || { echo "Falhou a instalação do Inno Setup."; exit 1; }
fi
VER=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' nexo/core/util.py)
echo "» A gerar o instalador…"
wine "$ISCC" /Q "/DAppVersion=$VER" 'packaging\windows\nexo.iss' || exit 1
sign "Aplicacao/Windows/Nexo-Instalador-$VER.exe" || exit 1
echo "Pronto: Aplicacao/Windows/Nexo-Instalador-$VER.exe"
