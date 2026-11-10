#!/usr/bin/env sh
# Gera o pacote do Arch a partir do estado atual do repositório (commit atual, sem alterações por gravar).
#   sh packaging/arch/build.sh            → cria o .pkg.tar.zst nesta pasta
#   sh packaging/arch/build.sh --instalar → cria e instala (pede a palavra-passe)
set -e
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
ver=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$repo/nexo/core/util.py")
sed -i "s/^pkgver=.*/pkgver=$ver/" "$here/PKGBUILD"
git -C "$repo" archive --format=tar.gz --prefix="nexo-$ver/" -o "$here/nexo-$ver.tar.gz" HEAD
cd "$here"
if [ "$1" = "--instalar" ]; then makepkg -fsi --noconfirm; else makepkg -f; fi
