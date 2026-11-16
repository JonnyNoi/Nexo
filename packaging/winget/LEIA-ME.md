# Publicar o Nexo no winget

Depois de a release `vX.Y` estar publicada (o `release.yml` gera o instalador e o `SHA256SUMS`):

```sh
python packaging/winget/gerar.py                # ou --id Dono.Nexo para escolher o identificador
```

No Windows, validar e enviar para o repositório da Microsoft (precisa de uma conta GitHub):

```bat
winget validate packaging\winget\saida\manifests\...\X.Y
winget install --manifest packaging\winget\saida\manifests\...\X.Y   &rem teste local (modo de programador)
wingetcreate submit packaging\winget\saida\manifests\...\X.Y
```

Notas:
- O winget pede que o instalador esteja assinado ou que ganhe reputação no SmartScreen; sem assinatura o
  pedido pode demorar mais a ser aprovado (ver "Assinatura do .exe" no README).
- Indique a licença verdadeira no campo `License` do manifesto de idioma quando o repositório tiver uma.
- Versões seguintes: `wingetcreate update <Id> --version X.Y --urls <url do instalador> --submit`.
