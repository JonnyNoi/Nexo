#!/usr/bin/env sh
# Prepara o pacote do AUR para a versão atual (depois de publicar a etiqueta vX.Y no GitHub):
#   sh packaging/aur/atualizar.sh            → escreve packaging/aur/saida/{PKGBUILD,.SRCINFO}
#   sh packaging/aur/atualizar.sh --testar   → também constrói o pacote com o makepkg para confirmar
# Depois copie PKGBUILD e .SRCINFO para o clone do repositório do AUR (ssh://aur@aur.archlinux.org/nexo.git),
# faça commit e push. Ver LEIA-ME.md.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$here/../.." && pwd)"
util="$repo_dir/nexo/core/util.py"
ver=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$util")
gh=$(sed -n 's/^UPDATE_REPO = "\(.*\)".*/\1/p' "$util")
if [ -z "$gh" ]; then
    echo "UPDATE_REPO está vazio em nexo/core/util.py — indique o repositório (\"dono/nome\") primeiro." >&2
    exit 1
fi
url="https://github.com/$gh/archive/refs/tags/v$ver.tar.gz"
out="$here/saida"
mkdir -p "$out"
echo "A transferir $url…"
curl -fsSL "$url" -o "$out/nexo-$ver.tar.gz"
sum=$(sha256sum "$out/nexo-$ver.tar.gz" | cut -d' ' -f1)
sed -e "s|@REPO@|$gh|" -e "s|@VERSAO@|$ver|" -e "s|@SHA256@|$sum|" "$here/PKGBUILD" > "$out/PKGBUILD"
cd "$out"
if command -v makepkg >/dev/null 2>&1; then
    makepkg --printsrcinfo > .SRCINFO
    [ "$1" = "--testar" ] && makepkg -f --noconfirm
else
    echo "makepkg não encontrado — gere o .SRCINFO num Arch com: makepkg --printsrcinfo > .SRCINFO" >&2
fi
echo "Pronto: $out/PKGBUILD (versão $ver, sha256 $sum)"
