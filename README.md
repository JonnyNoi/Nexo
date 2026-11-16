# Nexo

Utilitário de PC para **Linux e Windows** (Python + Qt/PySide6): informação do sistema, sensores ao vivo,
stress test, benchmark de CPU, otimização, **instalador de aplicações**, reparações do sistema, gestão do arranque,
**Windows debloat**, análise de **espaço em disco** com classificação do que é seguro apagar e troca do **fundo do ambiente de trabalho** (com galeria do **Wallhaven**). Inclui o essencial do *WinUtil* do Chris Titus. Tema escuro e claro.

> Antes chamava-se *PCForge* — as definições antigas são migradas automaticamente.

## Aplicação pronta a usar

| Sistema | Ficheiro |
|---|---|
| **Linux** | `Aplicacao/Linux/Nexo` — abrir diretamente; `sh Aplicacao/Linux/instalar.sh` adiciona-o ao menu de aplicações |
| **Linux (qualquer distribuição)** | `Nexo-x86_64.AppImage` (nas releases) — `chmod +x` e abrir; atualiza-se sozinha como o executável |
| **Windows** | `Aplicacao/Windows/Nexo.exe` — ficheiro único, abre como administrador |

## Funcionalidades

Algumas entradas do menu juntam várias páginas, com separadores no topo: **Discos** (Saúde dos discos + Espaço em disco), **Otimização** (Otimização + Arranque + Windows debloat), **Testes** (Benchmark + Stress test), **Software** (Atualizações + Instalar aplicações + Programas instalados) e **Utilitários** (Utilitários + Tarefas agendadas).

Na primeira execução abre um **assistente de boas-vindas** (tema, avisos, pontos de restauro, bandeja, tarefas automáticas, modo jogo) — pode voltar a vê-lo em Definições.

| Página | O que faz |
|---|---|
| **Visão geral** | **Relatório da semana**: como esteve o PC nos últimos 7 dias comparado com a semana anterior (pontuação média, estabilidade, throttling, tempo de arranque, horas de jogo, alertas e o que foi alterado), com aviso semanal no centro de alertas e exportação em HTML. **Porque está lento?** — diagnóstico de um clique (mede 2 s): processador, memória e paginação, discos ocupados ou cheios, throttling, atualizações/antivírus/indexação a correr, perfil de energia e tempo ligado, cada conclusão com botão para a página que resolve. **Saúde do PC**: pontuação de 0 a 100 com as 3 ações mais úteis do momento (cada uma com botão para a página certa) — junta as verificações ao vivo com atualizações pendentes, drivers antigos, última análise antivírus e pontos de restauro. Resumo do hardware, gráfico CPU × GPU (temperatura / carga / consumo, 1–15 min), anéis de RAM / VRAM / disco, rede e disco ao vivo e **Saúde do sistema** (temperaturas, RAM, espaço, swap, tempo ligado, serviços com falha) com botão "Resolver". |
| **Informação** | SO, CPU (caches, instruções), RAM (módulos e **velocidade atual vs. anunciada** — avisa quando o XMP/EXPO está desligado, p.ex. um kit DDR5-6000 a correr a 4800), GPU (VRAM, PCIe, VBIOS, OpenGL/Vulkan), placa-mãe/BIOS, Secure Boot, discos e rede. **Exportar relatório** em HTML ou JSON. |
| **Sensores** | Todas as leituras com atual/mín./máx. (registados mesmo com a página fechada), filtros por tipo e pesquisa. **Gravar CSV** de todas as leituras 1×/s. Linux: hwmon (coretemp/k10temp, amdgpu, nvme, SPD…), RAPL, amdgpu sysfs. Windows: WMI + **LibreHardwareMonitor** (o Nexo transfere a versão oficial com SHA-256 verificado, abre-a escondida na bandeja e fecha-a à saída; todos os sensores dele aparecem). NVIDIA via `nvidia-smi` em ambos. |
| **Bateria** *(só em portáteis)* | **Saúde da bateria**: capacidade atual vs. original (desgaste em %), ciclos de carga, carga e consumo agora e autonomia estimada. Linux: `/sys/class/power_supply`; Windows: WMI. Bateria gasta entra na Saúde do PC. |
| **Saúde dos discos** | **Velocidade do disco** (leitura/escrita sequencial e aleatória 4K sem a cache da memória — O_DIRECT / FILE_FLAG_NO_BUFFERING). Dados **S.M.A.R.T.** de cada disco (NVMe, SSD SATA, HDD): veredicto **Bom / Atenção / Mau**, **vida restante** dos SSD, temperatura, horas ligado, dados escritos/lidos, desligamentos inesperados, setores realocados/pendentes, erros CRC (cabo) e todos os atributos. **Autoteste rápido** do disco. O resultado aparece também na Saúde do sistema. Linux: `smartctl` (o Nexo oferece-se para instalar o smartmontools; pede a palavra-passe uma vez por leitura). Windows: `smartctl` se existir, senão o que o Windows reporta (Get-PhysicalDisk). |
| **Fiabilidade** | O que correu mal nos últimos 30 dias, com explicação e o que fazer: **desligares sem aviso** (Linux: arranques sem o registo normal de encerramento; Windows: Kernel-Power 41/6008), **falhas do sistema** (ecrã azul, kernel panic/oops/soft lockup), **erros de hardware** (WHEA/MCE), **controlador gráfico** (resets do amdgpu/i915, Xid da NVIDIA, Display 4101), **falta de memória** (OOM killer), **erros de disco** e **programas que fecharam com erro** (coredumpctl / Application Error). **Índice de estabilidade** 0–10 e faixa de 30 dias. Lê o journal / Visualizador de Eventos sem palavra-passe; avisa de eventos novos no arranque e a cada 6 h. **Throttling:** vigia a CPU e a GPU enquanto o Nexo está aberto (contadores do kernel nos Intel; nos outros, temperatura no limite + carga alta + clock abaixo do máximo atingido durante vários segundos) — avisa, regista e mostra no resumo da sessão de jogo. |
| **Processos** | Gestor de tarefas leve: CPU/memória/threads por processo, ordenar, procurar, **Terminar** / **Forçar fim** (tecla Delete), prioridade, abrir a pasta do programa. Atualiza a cada 2 s só com a página aberta. |
| **Antivírus** | Windows: Microsoft Defender. Linux: ClamAV (o Nexo instala-o) + heurísticas próprias. Análise rápida/completa, quarentena (ficheiros codificados e verificados por SHA-256; nunca apaga sozinho). |
| **Otimização** | Ajustes de desempenho e — ao estilo do WinUtil — **ajustes do sistema e da interface** (plano Desempenho Máximo, hibernação, "Terminar tarefa" na barra, menu de contexto clássico, modo escuro, Teclas Presas, ecrã azul detalhado, preferir IPv4…). Linux: BBR, NMI watchdog, split-lock, inotify. Tudo reversível. Fechar programas em segundo plano. |
| **Stress test** | CPU em todos os threads (FPU + inteiros) e/ou RAM (escreve e verifica 7 padrões). Pára no limite de temperatura, no fim do tempo ou ao detetar erro de memória. Gráfico e registo. |
| **Benchmark** | **Antes/depois:** cada resultado é comparado com o teste anterior igual (modo, qualidade e hardware) e lista o que mudou entretanto (ajustes, atualizações, arranque, limpezas, debloat — registados em `alteracoes.json`); abaixo de 3 % é variação normal. **Placa gráfica:** cena 3D em OpenGL (ray marching com sombras, oclusão ambiente e reflexos) em 1080p/1440p/4K num processo à parte; nota = FPS × 10 (RX 6500 XT ≈ 1500 em 1080p). **CPU:** path tracer próprio (iluminação global, metal, vidro com refração) multi-core e single-core. Imagem determinística, nota = amostras/s ÷ 1000, histórico. Referência: i5-12400F ≈ 1290 multi / 196 single. |
| **Modo jogo** | **Deteta o jogo que está a correr** (Steam/Proton com o nome verdadeiro, Wine, Lutris, Heroic, Epic, GOG, Xbox, pastas de jogos ou programas que marcar) e mostra um **overlay** por cima do jogo: temperatura e carga da CPU/GPU, consumo, RAM, VRAM, tempo de jogo e relógio — posição, formato (detalhado/compacto), opacidade e itens configuráveis; não apanha cliques. **Perfis por jogo:** perfil de energia, overlay, programas a fechar quando o jogo arranca (pedido normal de fecho) e, no Linux, o **Feral GameMode** — tudo volta ao normal quando o jogo fecha. Ao fechar o jogo mostra o resumo da sessão e guarda-a no **histórico de sessões** (tempo jogado por jogo, FPS médio, 1 % low, mínimo e temperaturas máximas; 7/30 dias ou desde sempre). **Jogos instalados** de todas as lojas com tamanho, **Jogar** e **Pasta**. Funciona com jogos em janela/ecrã inteiro sem bordas. |
| **Atualizações** | Mostra **o que há para atualizar** — pacotes do sistema (pacman via `checkupdates`, com plano B na base de dados local se os mirrors não responderem; apt, dnf, zypper), **AUR** (paru/yay), **Flatpak** e, no Windows, **winget** — com versão instalada e nova, filtro por origem e **Atualizar tudo** (ou **Abrir no terminal**, que inclui o AUR). Verifica sozinho a cada 6 h (só com internet) e mostra o número no menu lateral. **Drivers da placa gráfica:** versão do Mesa/NVIDIA (Linux, comparada com a última versão publicada e com as atualizações pendentes) ou do driver do fabricante (Windows, avisa se tiver mais de 6 meses). **Drivers e componentes em falta:** placa NVIDIA no nouveau, driver Vulkan da AMD/Intel em falta, driver Vulkan de 32 bits para a Steam, microcode da CPU (Linux — botão *Instalar o que falta*, com snapshot antes) e, no Windows, placa no «Adaptador de Vídeo Básico» ou dispositivos com erro no Gestor de Dispositivos. Verificado 1×/dia e incluído na Saúde do PC. |
| **Instalar aplicações** | ~60 aplicações populares por categoria (navegadores, jogos, multimédia, programação, utilitários, componentes). Marque e instale todas de uma vez, desinstale ou **atualize todas**. Windows: **winget**. Linux: **Flatpak/Flathub** (sem palavra-passe). |
| **Programas instalados** | **Tudo** o que está instalado (não só o catálogo), com tamanho, versão, data e origem; procurar, filtrar por origem, só aplicações (com entrada no menu) e **Desinstalar**. Windows: "Adicionar/remover programas" (abre o desinstalador do programa). Linux: pacotes instalados de propósito (pacman/apt/dnf), Flatpak e Snap; componentes essenciais (kernel, systemd, ambiente gráfico…) ficam protegidos. |
| **Utilitários** | Windows: **ponto de restauro**, SFC, DISM, chkdsk, repor rede, repor Windows Update, **funcionalidades** (WSL, Hyper-V, Sandbox, .NET 3.5), **Windows Update** "só segurança" e drivers, **painéis clássicos**. Linux: atualizar o sistema (pacman/apt/dnf/zypper), órfãos, TRIM, firmware (fwupd), serviços com falha, erros do arranque. Ambos: **DNS** (Cloudflare, Google, Quad9, AdGuard…) com **teste de velocidade**. |
| **Arranque** | **Tempo de arranque**: quanto demorou o último arranque (BIOS/UEFI, kernel, serviços — Linux: `systemd-analyze`; Windows: Diagnostics-Performance, como administrador), evolução dos últimos arranques, o que o atrasou e conselhos (ex.: «Fast Boot» quando o BIOS demora); cada arranque fica guardado e mostra o que mudou desde o anterior. Ativar/desativar programas que abrem com o sistema. Windows: chaves Run + pasta Arranque (mesmo método do Gestor de Tarefas). Linux: `~/.config/autostart`, `/etc/xdg/autostart` e `systemd --user`. Componentes essenciais do ambiente gráfico ficam protegidos. |
| **Windows debloat** *(só Windows)* | Remove apps pré-instaladas (Notícias, Clipchamp, Cortana, Copilot, Candy Crush, TikTok, McAfee de teste…) e desliga telemetria, ID de publicidade, Recall, sugestões/anúncios, pesquisa Bing, Widgets. Tudo com **Restaurar originais**. Não mexe em Defender, SmartScreen, UAC nem Windows Update. |
| **Espaço em disco** | **Analisa o disco do sistema logo ao abrir** e classifica cada pasta: 🟢 **Seguro apagar** (caches, temporários, lixo, logs, node_modules/.venv, Windows.old, transferências do Windows Update…), 🔵 **Seguro — desinstalar** (jogos da Steam com o nome do jogo, Epic, GOG, Xbox, Heroic, Lutris, programas), 🟡 **Rever antes** (documentos, fotos, transferências, VMs, definições das apps) e 🔴 **Sistema — não apagar** (`C:\Windows`, System32, WinSxS, pagefile/hiberfil, Program Files, `/usr`, `/etc`, `/boot`, swap, snapshots…). Resumo com quanto pode libertar, lista **Pode ser apagado** (botão *Marcar os seguros*), **Explorar por pasta** (árvore), maiores ficheiros/pastas, duplicados (em segundo plano) e espaço por tipo. Itens do sistema ficam **protegidos** (não se deixam apagar); jogos da Steam abrem o desinstalador da Steam. **Limpeza rápida**: lixo, caches de navegadores/apps/shaders/programação, temporários, Windows Update, pacotes antigos (pacman/apt/dnf), journal, Flatpak, Docker… |
| **Fundo de ecrã** | Muda o **wallpaper do ambiente de trabalho** do sistema: Windows, KDE Plasma, GNOME, Cinnamon, MATE, XFCE, LXQt, Sway, Hyprland (swww/hyprpaper) ou feh/nitrogen. Imagem própria ou **galeria do Wallhaven**, ajuste (preencher, ajustar, esticar, centrar, mosaico, vários ecrãs), opcionalmente também no **ecrã de bloqueio**, **Os meus fundos** e **troca automática** (dos seus fundos ou aleatório do Wallhaven). |
| **Tarefas agendadas** | O que o Nexo faz sozinho e quando: **limpeza automática**, **análise antivírus rápida** (só avisa; o resultado aparece na página Antivírus) e **saúde dos discos** (no Windows corre; no Linux só lembra, porque precisa da palavra-passe). Diária, semanal, quinzenal ou mensal, com próxima e última execução. Nunca corre durante um jogo. |
| **Internet** | **Wi-Fi**: sinal, banda e canal, velocidade da ligação ao router, redes vizinhas no mesmo canal e qual o canal de 2,4 GHz mais livre, com conselhos (sinal fraco, 5 GHz disponível, canal cheio) — nmcli no Linux, netsh no Windows. Teste de velocidade (Cloudflare), latência com a ligação cheia, o que a ligação permite, diagnóstico passo a passo e **programas a usar a internet** (Linux: velocidade e total por programa via `ss`; Windows: ligações por programa). |
| **Definições** | Tema **escuro** ou **claro**, **idioma** (português ou inglês), alertas (temperatura, RAM, disco, S.M.A.R.T.), pontos de restauro, histórico dos sensores, bandeja, **limpeza automática** (semanal/quinzenal/mensal, só o que é 100 % seguro e sem palavra-passe), **cópia das definições** (exportar/importar .zip com definições, benchmarks e sessões de jogo) e **atualizações do próprio Nexo** (releases do GitHub com SHA-256 verificado; `UPDATE_REPO` em `nexo/core/util.py`). |


Tema escuro/claro (guardado), ícones próprios, notificações flutuantes, leitura de CPU/GPU/RAM sempre visível no menu.
**Menu lateral:** secções que recolhem com um clique (lembradas entre sessões), **modo compacto só com ícones** (botão no fundo do menu ou Ctrl+B), barra de destaque na página ativa e contadores (ex.: atualizações pendentes).
**Bandeja do sistema:** ícone com a temperatura da CPU, dica com CPU/GPU/RAM e avisos de sobreaquecimento.
**Centro de alertas (sino no fundo do menu, Ctrl+Shift+A):** todos os avisos (temperatura, RAM, discos, S.M.A.R.T., jogos, tarefas, atualizações) ficam guardados com a hora, repetições agrupadas, contador de não lidos e botão para a página que resolve.
**Acessibilidade:** navegação completa pelo teclado (Tab mostra um contorno no elemento com foco; o rato não), nomes acessíveis nos botões só com ícone e nos interruptores, e cores com contraste WCAG AA nos dois temas (verificado em `tests/test_contrast.py`).
**Pesquisa rápida (Ctrl+K ou "Procurar…" no menu):** encontra páginas, funções, opções e temas — mesmo sem acentos — e leva diretamente até lá, abre o separador certo e destaca o elemento.
**Atalhos (F1 mostra a lista):** Ctrl+K pesquisa rápida · Ctrl+1…9 mudar de página · Ctrl+Tab / Ctrl+Shift+Tab · Ctrl+Shift+A alertas · Ctrl+B menu compacto · F5 atualizar · Ctrl+, definições · Ctrl+Q sair.
Só abre uma instância (abrir de novo traz a janela para a frente); `--minimized` arranca na bandeja.

### Desempenho
- Sensores: a estrutura do hwmon é lida uma vez; sensores lentos (NVMe/SPD, ~3 ms cada) são lidos numa thread
  à parte a cada 5 s. Um ciclo de leitura passou de ~17 ms para ~2 ms.
- NVIDIA e Windows: um único `nvidia-smi -lms` / PowerShell persistente em vez de lançar um processo novo
  a cada 1–2 s (o PowerShell custava ~0,5 s de CPU por arranque).
- Páginas criadas só quando abertas pela 1.ª vez (janela principal ~4× mais rápida a abrir).
- Árvore de sensores só redesenha as células que mudaram.
- Sem fundos animados: a interface só usa as cores do tema (0 % de CPU em repouso por causa do fundo).

### Linha de comandos

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
git tag -a v2.3 -m "Nexo 2.3" && git push origin v2.3
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
