#!/usr/bin/env sh
# Gera Aplicacao/Linux/Nexo-x86_64.AppImage — um ficheiro que corre na maioria das distribuições
# (Ubuntu, Fedora, Mint, openSUSE, Arch…) sem instalar nada: chmod +x e abrir.
#
# Usa o PyInstaller em modo pasta (onedir) — dentro da AppImage não faz sentido o executável único, que
# se descomprimiria outra vez para /tmp a cada arranque — e o appimagetool + runtime oficiais com
# versão e SHA-256 fixos (descarregados uma vez para build/appimage-tools).
#
#   ./packaging/appimage/build_appimage.sh
#
# Para correr em distribuições antigas, gere-a numa distribuição com glibc antiga (o release.yml usa
# ubuntu-22.04): o executável só corre em sistemas com glibc igual ou mais recente.
set -eu
cd "$(dirname "$0")/../.."
ROOT=$(pwd)

TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
TOOL_SHA="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

PY=${PYTHON:-}
if [ -z "$PY" ]; then
    [ -x .venv/bin/python ] || python3 -m venv .venv
    PY=.venv/bin/python
fi
"$PY" -m pip install -q -r requirements.txt pyinstaller

TOOLS=build/appimage-tools
mkdir -p "$TOOLS"
fetch() {   # url sha256 destino
    if [ -f "$3" ] && echo "$2  $3" | sha256sum -c --status; then return 0; fi
    curl -fL --retry 3 -o "$3.part" "$1"
    if ! echo "$2  $3.part" | sha256sum -c --status; then
        rm -f "$3.part"
        echo "SHA-256 errado em $1 — não foi usado." >&2
        exit 1
    fi
    mv "$3.part" "$3"
    chmod +x "$3"
}
fetch "$TOOL_URL" "$TOOL_SHA" "$TOOLS/appimagetool"
fetch "$RUNTIME_URL" "$RUNTIME_SHA" "$TOOLS/runtime-x86_64"

VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' nexo/core/util.py)
"$PY" -m PyInstaller --noconfirm --clean --onedir --windowed --name Nexo \
    --distpath build/appimage-dist --workpath build/appimage-work --specpath build/appimage-work run_nexo.py

APPDIR=build/Nexo.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a build/appimage-dist/Nexo "$APPDIR/usr/lib/nexo"
cp assets/nexo.png "$APPDIR/nexo.png"
cp assets/nexo.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/nexo.png"
ln -s nexo.png "$APPDIR/.DirIcon"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
exec "$HERE/usr/lib/nexo/Nexo" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/nexo.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Nexo
GenericName=Utilitário do PC
Comment=Sensores, fiabilidade, otimização, modo jogo, benchmark e mais
Exec=Nexo
Icon=nexo
Categories=System;Monitor;Utility;
Keywords=sensores;temperatura;otimizar;limpeza;benchmark;fiabilidade;
Terminal=false
StartupWMClass=Nexo
X-AppImage-Version=$VERSION
DESKTOP
cp "$APPDIR/nexo.desktop" "$APPDIR/usr/share/applications/nexo.desktop"

mkdir -p Aplicacao/Linux
OUT="$ROOT/Aplicacao/Linux/Nexo-x86_64.AppImage"
rm -f "$OUT"
# APPIMAGE_EXTRACT_AND_RUN: o appimagetool corre sem precisar de FUSE (CI, contentores)
ARCH=x86_64 VERSION="$VERSION" APPIMAGE_EXTRACT_AND_RUN=1 "$TOOLS/appimagetool" --no-appstream \
    --runtime-file "$TOOLS/runtime-x86_64" "$APPDIR" "$OUT"
echo "Pronto: Aplicacao/Linux/Nexo-x86_64.AppImage ($VERSION)"
