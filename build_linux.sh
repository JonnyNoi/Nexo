#!/usr/bin/env sh
# Gera Aplicacao/Linux/Nexo (executável único para Linux).
#   ./build_linux.sh            → só gera o executável
#   ./build_linux.sh --instalar → gera e instala no menu de aplicações (~/.local)
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt pyinstaller || exit 1
.venv/bin/pyinstaller --noconfirm --clean --onefile --windowed --name Nexo \
    --distpath Aplicacao/Linux --workpath build/linux --specpath build/linux run_nexo.py || exit 1
cp assets/nexo.png Aplicacao/Linux/nexo.png
echo "Pronto: Aplicacao/Linux/Nexo"
[ "$1" = "--instalar" ] && sh Aplicacao/Linux/instalar.sh
exit 0
