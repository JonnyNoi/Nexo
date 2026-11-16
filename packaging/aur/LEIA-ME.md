# Publicar o Nexo no AUR

Uma vez (precisa de conta no AUR com a chave SSH registada):

```sh
git clone ssh://aur@aur.archlinux.org/nexo.git ~/aur-nexo   # se o nome estiver ocupado, use p.ex. nexo-pc
```

A cada versão (depois de `git tag -a vX.Y && git push origin vX.Y`):

```sh
sh packaging/aur/atualizar.sh --testar        # gera saida/PKGBUILD e saida/.SRCINFO e constrói o pacote
cp packaging/aur/saida/PKGBUILD packaging/aur/saida/.SRCINFO ~/aur-nexo/
cd ~/aur-nexo && git add PKGBUILD .SRCINFO && git commit -m "Nexo X.Y" && git push
```

Notas:
- O AUR exige uma licença: acrescente um ficheiro `LICENSE` ao repositório e troque `license=('custom')`
  pelo identificador SPDX (ex.: `'GPL-3.0-or-later'` ou `'MIT'`).
- `packaging/arch/PKGBUILD` continua a servir para gerar o pacote local a partir do código (sem internet).
