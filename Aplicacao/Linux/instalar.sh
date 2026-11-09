#!/usr/bin/env sh
# Instala o Nexo para o utilizador atual: ~/.local/bin/Nexo + atalho no menu de aplicações.
# Para desinstalar: sh instalar.sh --remover
cd "$(dirname "$0")" || exit 1
BIN="$HOME/.local/bin/Nexo"
DESK="$HOME/.local/share/applications/nexo.desktop"
if [ "$1" = "--remover" ]; then
    rm -f "$BIN" "$DESK" "$HOME/.config/autostart/nexo.desktop" "$HOME/.local/share/icons/hicolor/256x256/apps/nexo.png"
    echo "Nexo removido (as definições ficam em ~/.config/Nexo)."
    exit 0
fi
[ -f Nexo ] || { echo "Não encontrei o ficheiro Nexo nesta pasta."; exit 1; }
ICON="$HOME/.local/share/icons/hicolor/256x256/apps/nexo.png"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$(dirname "$ICON")"
cp Nexo "$BIN" && chmod +x "$BIN"
[ -f nexo.png ] && cp nexo.png "$ICON"
cat > "$DESK" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Nexo
GenericName=Utilitário do PC
Comment=Sensores, otimização, temas, instalar aplicações, stress test e benchmark
Exec=$BIN
Icon=nexo
Categories=System;Monitor;Utility;
Keywords=sensores;temperatura;otimizar;limpeza;benchmark;
Terminal=false
StartupWMClass=Nexo
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
echo "Nexo instalado: procure \"Nexo\" no menu de aplicações (ou execute $BIN)."
