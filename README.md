# Nexo

Utilitário gratuito para PC, para **Linux e Windows** (Python + Qt/PySide6), que junta numa só aplicação o que
normalmente exige vários programas. Tema escuro e claro, em português e inglês.

> Antes chamava-se *PCForge* — as definições antigas são migradas automaticamente.

## O que faz

- **Estado do PC** — pontuação de saúde 0–100 com as ações mais úteis, diagnóstico «Porque está lento?»,
  sensores ao vivo (temperaturas, consumo, carga), informação do hardware e relatório semanal.
- **Discos** — saúde S.M.A.R.T., previsão do fim de vida dos SSD, teste de velocidade e análise do espaço
  (o que é seguro apagar e o que não se deve tocar).
- **Fiabilidade** — falhas dos últimos 30 dias (desligares inesperados, ecrãs azuis, erros de hardware e drivers)
  e deteção de throttling.
- **Testes** — benchmark e stress test da CPU, RAM e placa gráfica (incluindo a VRAM); «O que melhorar» diz que
  peça limita o PC e o que comprar primeiro.
- **Jogos** — deteta o jogo a correr, overlay com temperaturas e cargas, perfis por jogo e histórico de sessões
  com FPS, engasgos e frametimes.
- **Software** — atualizações (pacman, apt, AUR, Flatpak, winget), drivers e BIOS, instalar e desinstalar aplicações.
- **Otimização e limpeza** — ajustes de desempenho reversíveis, programas no arranque, debloat do Windows e
  privacidade no Linux.
- **Internet** — teste de velocidade, firewall e portas abertas, análise do Wi-Fi e programas a usar a rede.
- **E ainda** — antivírus, energia e custo em €, periféricos (bateria dos sem fios, testes de ecrã/rato/teclado),
  snapshots, fundo de ecrã (galeria do Wallhaven), painel no telemóvel, centro de alertas, pesquisa rápida (Ctrl+K)
  e atualização automática.

📖 **Tudo em detalhe:** [FUNCIONALIDADES.md](FUNCIONALIDADES.md)

## Aplicação pronta a usar

| Sistema | Ficheiro |
|---|---|
| **Linux** | `Aplicacao/Linux/Nexo` — abrir diretamente; `sh Aplicacao/Linux/instalar.sh` adiciona-o ao menu de aplicações |
| **Linux (qualquer distribuição)** | `Nexo-x86_64.AppImage` (nas releases) — `chmod +x` e abrir; atualiza-se sozinha como o executável |
| **Windows** | `Aplicacao/Windows/Nexo.exe` — ficheiro único, abre como administrador |

## Linha de comandos

Sem abrir a janela (scripts, SSH, tarefas agendadas do sistema):

```sh
nexo --saude [--json]            # pontuação da Saúde do PC e o que fazer (código de saída 0/1/2)
nexo --limpar                    # limpeza 100 % segura, sem palavra-passe
nexo --relatorio relatorio.html  # relatório do sistema (.html ou .json)
nexo --relatorio-semanal [f.html]
nexo --bateria | --arranque | --versao | --ajuda
```
No Windows o `Nexo.exe` escreve na consola de onde foi chamado.

## Executar

**Linux**
```sh
./run.sh
```
**Windows** (precisa do Python 3.10+ de python.org)
```bat
run.bat
```
Na primeira execução é criado o ambiente virtual `.venv` com PySide6 e psutil.

Algumas ações precisam de privilégios: no Linux o `pkexec` pede a palavra-passe na hora;
no Windows use o botão **Admin** no menu (ou o `.exe` gerado, que já pede administrador).

## Gerar executável

- **Linux:** `./build_linux.sh` → `Aplicacao/Linux/Nexo` (`--instalar` também o põe no menu de aplicações)
- **Windows, num Windows:** `build_windows.bat` → `Aplicacao\Windows\Nexo.exe`
- **Windows, a partir do Linux:** `./build_windows_wine.sh` → `Aplicacao/Windows/Nexo.exe`
  (usa o wine com um Python para Windows em `~/.local/share/nexo-wine`, preparado automaticamente na 1.ª vez);
  `--instalador` gera também `Nexo-Instalador-<versão>.exe` (Inno Setup: menu Iniciar, atalho, desinstalar)
- **Pacote do Arch / CachyOS:** `sh packaging/arch/build.sh` (`--instalar` instala-o com o pacman)
- **AppImage (qualquer distribuição):** `./packaging/appimage/build_appimage.sh` → `Aplicacao/Linux/Nexo-x86_64.AppImage`
  (PyInstaller em modo pasta + appimagetool 1.9.1 e runtime oficiais com SHA-256 fixo; gerada também no release.yml)

- **AUR:** `sh packaging/aur/atualizar.sh` (ver `packaging/aur/LEIA-ME.md`) · **winget:** `python packaging/winget/gerar.py` (ver `packaging/winget/LEIA-ME.md`) — ambos depois de publicar a release.

### Versões (GitHub Releases) e atualizações automáticas

Publicar uma etiqueta gera tudo no GitHub Actions (`.github/workflows/release.yml`): testes → `Nexo` (Linux,
Ubuntu 22.04 para correr em mais distribuições) + `Nexo-x86_64.AppImage` + `Nexo.exe` + instalador → release com `SHA256SUMS`.
```sh
# APP_VERSION em nexo/core/util.py tem de ser igual à etiqueta (o workflow confirma)
git tag -a v2.4.1 -m "Nexo 2.4.1" && git push origin v2.4.1
```
Para o Nexo instalado se atualizar sozinho, ponha o repositório em `UPDATE_REPO` (`nexo/core/util.py`, ex.:
`"utilizador/nexo"`): verifica uma vez por dia, confirma o SHA-256 que o GitHub publica e pede autorização.

### Assinatura do .exe (SmartScreen)

Sem assinatura, o SmartScreen avisa na primeira execução noutros PCs («Mais informações» → «Executar mesmo
assim»). Para assinar:
- **No GitHub Actions:** guarde o certificado de assinatura de código como segredos do repositório —
  `WINDOWS_CERT_PFX` (o .pfx em base64: `base64 -w0 cert.pfx`) e `WINDOWS_CERT_PASSWORD`. O `Nexo.exe` e o
  instalador passam a sair assinados e com carimbo temporal (`packaging/windows/sign.ps1`).
- **No build local (wine):** `NEXO_SIGN_PFX=/caminho/cert.pfx NEXO_SIGN_PASS=… ./build_windows_wine.sh --instalador`
  (precisa do `osslsigncode`).
- Projetos de código aberto podem pedir um certificado gratuito ao [SignPath Foundation](https://signpath.org/);
  um certificado OV comum tira o aviso depois de ganhar reputação, um EV tira-o logo.

## Onde ficam os dados

`~/.config/Nexo` (Linux) ou `%APPDATA%\Nexo` (Windows): `settings.json` (um ficheiro corrompido é guardado
como `.corrompido` antes de ser reescrito), `historico.db` (sensores e sessões de jogo), histórico do benchmark,
`ferramentas/` (PresentMon, LibreHardwareMonitor) e
`tweaks_backup.json` com os valores originais de cada ajuste (é isto que permite restaurar) e `wallpapers/`
com os fundos escolhidos. `smart.json` guarda a última leitura da saúde dos discos, `fiabilidade.json` a última análise da Fiabilidade,
`throttling.json` os episódios de limitação por temperatura e `alteracoes.json` as mudanças feitas pelo Nexo (comparação dos benchmarks).

**Registo de erros:** `nexo.log` (rotativo, máx. ~3 MB) na mesma pasta — erros não tratados ficam lá com o
traceback e o Nexo mostra a janela «Ocorreu um erro» (com *Copiar detalhes*) em vez de fechar. Falhas graves do
interpretador vão para `nexo-crash.log`; o overlay de jogo escreve em `overlay.log`.
Definições → «Abrir registo de erros».

## Testes

```sh
.venv/bin/python -m unittest discover -s tests -t .
```
Tradução: `python -m nexo.core.i18n [ficheiros]` lista os textos que ainda não têm tradução para inglês
(catálogo em `nexo/core/i18n_en.py`; textos com valores no meio vão em `TEMPLATES`).
Correm também no GitHub Actions (Linux e Windows) a cada push — `.github/workflows/testes.yml`.

## Estrutura

```
nexo/
  core/        lógica sem interface (funciona em Linux e Windows)
    sysinfo.py  sensors.py  stress.py   bench.py     gpubench.py   processes.py  memory.py
    tweaks.py   startup.py  debloat.py  apps.py      systools.py   updates.py    drivers.py
    diskscan.py disksafety.py cleanup.py autoclean.py smart.py   diskbench.py  antivirus.py
    games.py    sessions.py fps.py      power.py     lhm.py        network.py    netprocs.py
    reliability.py throttle.py slowdiag.py changes.py
    speedtest.py history.py snapshot.py watch.py     backup.py     selfupdate.py
    alertlog.py healthscore.py schedule.py gameprofile.py i18n.py i18n_en.py
    wallhaven.py desktopwp.py log.py    util.py
  ui/          interface Qt
    main_window.py (menu, navegação, bandeja)  nav.py (peças do menu)  mw_background.py (vigilância,
    tarefas, atualizações)  mw_game.py (modo jogo)  alertcenter.py  wizard.py  gameprofile_card.py
    i18n_qt.py  palette.py  theme.py  widgets.py  icons.py  logo.py  historyview.py
    overlay.py  netmonitor.py  slowdiag_card.py  crash.py  wallhaven_dialog.py  pages/*.py
tests/         testes (unittest)
packaging/     arch/PKGBUILD · windows/nexo.iss (instalador) · appimage/build_appimage.sh
assets/        logótipo (nexo.png, nexo.ico)
Aplicacao/
  Linux/       Nexo (executável) · instalar.sh · LEIA-ME.txt
  Windows/     Nexo.exe · LEIA-ME.txt
run_nexo.py   ponto de entrada
```

## Licença

[MIT](LICENSE) — pode usar, modificar e distribuir, mantendo o aviso de copyright.
