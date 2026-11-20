"""Tradução para inglês das funcionalidades da 2.4: Energia, O que melhorar, Snapshots, painel no telemóvel,
BIOS, histórico S.M.A.R.T., frametimes e testes de periféricos."""
from __future__ import annotations

EN_V24: dict[str, str] = {
    # menu e páginas
    "Energia": "Energy",
    "O que melhorar": "What to upgrade",
    "Snapshots": "Snapshots",
    "Painel no telemóvel": "Phone dashboard",
    "Testes de periféricos": "Peripheral tests",
    "BIOS / UEFI": "BIOS / UEFI",
    # energia
    "Quanto o PC gasta e quanto custa: consumo medido da CPU e da placa gráfica mais uma estimativa do resto do "
    "computador. Conta enquanto o Nexo está aberto.":
        "How much power the PC uses and what it costs: measured CPU and graphics card power plus an estimate for "
        "the rest of the computer. Counted while Nexo is open.",
    "Agora": "Now",
    "Hoje": "Today",
    "Últimos 7 dias": "Last 7 days",
    "Por mês (estimativa)": "Per month (estimate)",
    "Custo por dia": "Cost per day",
    "Últimos 30 dias. Passe o rato por cima de uma barra para ver o detalhe.":
        "Last 30 days. Hover a bar to see the details.",
    "14 dias": "14 days",
    "30 dias": "30 days",
    "90 dias": "90 days",
    "Jogos": "Games",
    "Energia e custo das sessões de jogo (últimos 30 dias). As sessões gravadas antes desta versão não têm o consumo.":
        "Energy and cost of game sessions (last 30 days). Sessions recorded before this version have no power data.",
    "Jogo": "Game",
    "Tempo": "Time",
    "Custo": "Cost",
    "Preço e estimativas": "Price and estimates",
    "Preço do kWh": "Price per kWh",
    "Está na fatura da eletricidade (preço da energia com taxas e IVA). Em Portugal ronda os 0,15–0,25 €.":
        "It is on your electricity bill (energy price including taxes). In Portugal it is around €0.15–0.25.",
    "Resto do PC": "Rest of the PC",
    "Placa-mãe, memória, discos, ventoinhas e perdas da fonte não têm sensor. Um PC de secretária gasta normalmente "
    "30–70 W nisto; um portátil 5–15 W. O monitor não conta.":
        "Motherboard, memory, drives, fans and power supply losses have no sensor. A desktop PC usually uses "
        "30–70 W for these; a laptop 5–15 W. The monitor is not included.",
    "sem sensores de consumo": "no power sensors",
    "pelo uso dos últimos 30 dias": "based on the last 30 days",
    "ainda sem dados": "no data yet",
    "CPU": "CPU",
    "Placa gráfica": "Graphics card",
    "Resto do PC (estimativa)": "Rest of the PC (estimate)",
    "Ainda não há dados: o consumo começa a ser registado a partir de agora.":
        "No data yet: power use is recorded from now on.",
    "Sem sessões de jogo com consumo medido nos últimos 30 dias.":
        "No game sessions with measured power in the last 30 days.",
    "Não há leitura do consumo da CPU nem da placa gráfica": "There is no power reading for the CPU or graphics card",
    "Não há leitura do consumo da CPU": "There is no CPU power reading",
    "Não há leitura do consumo da placa gráfica": "There is no graphics card power reading",
    ": essa parte fica a zero e o custo sai mais baixo do que o real. No Linux, o consumo da CPU Intel/AMD (RAPL) só "
    "é legível pelo administrador em alguns sistemas; no Windows precisa do LibreHardwareMonitor (página Sensores).":
        ": that part counts as zero and the cost comes out lower than the real one. On Linux, Intel/AMD CPU power "
        "(RAPL) is only readable by the administrator on some systems; on Windows it needs LibreHardwareMonitor "
        "(Sensors page).",
    # o que melhorar
    "Que peça limita o seu PC e o que vale a pena trocar primeiro — a partir das sessões de jogo, dos benchmarks e do "
    "hardware. As correções grátis aparecem primeiro.":
        "Which part holds your PC back and what is worth replacing first — based on game sessions, benchmarks and "
        "hardware. Free fixes come first.",
    "Analisar de novo": "Analyse again",
    "Processador": "Processor",
    "Memória": "Memory",
    "Disco do sistema": "System drive",
    "O que limita nos jogos": "What limits games",
    "A analisar…": "Analysing…",
    "Jogos analisados": "Games analysed",
    "Últimos 90 dias. Carga média durante o jogo — uma placa gráfica perto dos 100 % está no limite; folgada com FPS "
    "baixo aponta para o processador.":
        "Last 90 days. Average load while playing — a graphics card near 100 % is maxed out; an idle one with low "
        "FPS points to the processor.",
    "FPS médio": "Average FPS",
    "1 % low": "1 % low",
    "Limitado por": "Limited by",
    "Processador / jogo": "Processor / game",
    "Nada claro": "Nothing clear",
    "Ver": "View",
    "Grátis": "Free",
    "Comprar": "Buy",
    "Tudo bem": "All good",
    "Monitor": "Monitor",
    "Refrigeração": "Cooling",
    "Equilíbrio": "Balance",
    "Disco": "Drive",
    "Nos jogos, nem a CPU nem a placa gráfica limitam de forma clara (o FPS está perto do monitor ou limitado pelo "
    "jogo).":
        "In games, neither the CPU nor the graphics card is clearly the limit (FPS is close to the monitor's refresh "
        "rate or capped by the game).",
    "Não há nada que precise claramente de ser trocado. Jogue um pouco com o Nexo aberto e faça os benchmarks (CPU e "
    "placa gráfica) para uma recomendação mais precisa.":
        "Nothing clearly needs replacing. Play a little with Nexo open and run the benchmarks (CPU and graphics "
        "card) for a more precise recommendation.",
    "Não há nada que precise claramente de ser trocado. Jogue um pouco com o Nexo aberto para saber o que limita o "
    "PC nos jogos.":
        "Nothing clearly needs replacing. Play a little with Nexo open to find out what limits the PC in games.",
    "O PC está equilibrado: nenhuma peça limita claramente as outras. Para mais FPS, a melhoria com mais efeito "
    "costuma ser a placa gráfica.":
        "The PC is balanced: no part clearly holds the others back. For more FPS, the upgrade with the biggest effect "
        "is usually the graphics card.",
    "Ligar o XMP/EXPO no BIOS": "Enable XMP/EXPO in the BIOS",
    "abaixo da velocidade": "below its speed",
    "Baixar as temperaturas": "Lower the temperatures",
    "Limpe o pó, confirme as ventoinhas e a pasta térmica — perde-se desempenho sem dar por isso.":
        "Clean the dust, check the fans and thermal paste — you lose performance without noticing.",
    "Trocar o disco do sistema por um SSD": "Replace the system drive with an SSD",
    "O sistema está num disco rígido (HDD). Um SSD (de preferência NVMe) é a melhoria que mais se nota: arranque, "
    "programas e carregamentos dos jogos várias vezes mais rápidos.":
        "The system is on a hard drive (HDD). An SSD (preferably NVMe) is the most noticeable upgrade: boot, apps "
        "and game loading several times faster.",
    "Mais memória RAM (16 GB)": "More RAM (16 GB)",
    "Mais memória RAM": "More RAM",
    "Placa gráfica mais potente": "More powerful graphics card",
    "Placa gráfica com mais VRAM": "Graphics card with more VRAM",
    "Processador mais rápido": "Faster processor",
    "Nada urgente para trocar": "Nothing urgent to replace",
    "Escolha uma placa com pelo menos 8 GB de VRAM (a memória da atual encheu nos jogos).":
        "Choose a card with at least 8 GB of VRAM (the current one's memory filled up in games).",
    "Antes de trocar, ligue o XMP: a CPU depende muito da velocidade da memória.":
        "Before replacing it, enable XMP: the CPU depends a lot on memory speed.",
    "O processador e a placa gráfica baixaram o clock por temperatura este mês.":
        "The processor and graphics card lowered their clocks due to temperature this month.",
    "O processador baixou o clock por temperatura este mês.":
        "The processor lowered its clock due to temperature this month.",
    "A placa gráfica baixou o clock por temperatura este mês.":
        "The graphics card lowered its clock due to temperature this month.",
    # snapshots
    "Fotografias do sistema para voltar atrás quando uma atualização ou um ajuste corre mal. Com btrfs são "
    "instantâneas e só ocupam o que mudou desde então.":
        "Snapshots of the system to go back when an update or a tweak goes wrong. With btrfs they are instant and "
        "only take up what changed since.",
    "Ver snapshots": "Show snapshots",
    "A lista só pode ser lida pelo administrador: pede a palavra-passe.":
        "The list can only be read by the administrator: it asks for the password.",
    "Estado": "Status",
    "Sistema de snapshots": "Snapshot system",
    "carregue em «Ver snapshots»": "click «Show snapshots»",
    "Criados pelo Nexo": "Created by Nexo",
    "Criar snapshot": "Create snapshot",
    "Antes de mexer no sistema por conta própria (instalar drivers, mudar configurações, atualizar o kernel).":
        "Before changing the system yourself (installing drivers, changing settings, updating the kernel).",
    "Descrição (ex.: antes de instalar o driver da NVIDIA)": "Description (e.g. before installing the NVIDIA driver)",
    "Criar agora": "Create now",
    "Snapshots existentes": "Existing snapshots",
    "Os mais recentes primeiro. «pre/post» são criados aos pares antes e depois de cada atualização (snap-pac).":
        "Newest first. «pre/post» are created in pairs before and after each update (snap-pac).",
    "N.º": "No.",
    "Data": "Date",
    "Descrição": "Description",
    "Tipo": "Type",
    "Espaço": "Space",
    "Apagar selecionados": "Delete selected",
    "Como restaurar": "How to restore",
    "Restaurar troca o sistema pelo snapshot e precisa de reiniciar — é feito na ferramenta própria, onde pode ver "
    "cada snapshot antes de escolher.":
        "Restoring replaces the system with the snapshot and needs a restart — it is done in the dedicated tool, "
        "where you can inspect each snapshot before choosing.",
    "Ainda não há snapshots.": "There are no snapshots yet.",
    "Apagar snapshots": "Delete snapshots",
    "Nada selecionado.": "Nothing selected.",
    "Não foi possível ler os snapshots.": "Could not read the snapshots.",
    "Não há snapper nem Timeshift configurados.": "Neither snapper nor Timeshift is configured.",
    "Instale o snapper ou o Timeshift para criar snapshots do sistema.":
        "Install snapper or Timeshift to create system snapshots.",
    "O sistema está em btrfs, por isso os snapshots são instantâneos e quase não ocupam espaço. Instale o snapper (e o "
    "snap-pac no Arch, para um snapshot antes de cada atualização) ou o Timeshift em modo btrfs, e configure-o para "
    "a raiz (/).":
        "The system is on btrfs, so snapshots are instant and take almost no space. Install snapper (and snap-pac on "
        "Arch, for a snapshot before each update) or Timeshift in btrfs mode, and configure it for the root (/).",
    # painel no telemóvel
    "Veja as temperaturas, o consumo e o FPS no telemóvel enquanto joga: abra a ligação (ou leia o código QR) num "
    "browser ligado à mesma rede Wi-Fi.":
        "See temperatures, power and FPS on your phone while you play: open the link (or scan the QR code) in a "
        "browser on the same Wi-Fi network.",
    "Ligar o painel": "Enable the dashboard",
    "Só leitura: ninguém consegue mudar nada no PC a partir daqui. Só abre com o código da ligação.":
        "Read-only: nobody can change anything on the PC from it. It only opens with the code in the link.",
    "Porta": "Port",
    "Mude só se outro programa já usar a 8765.": "Only change it if another program already uses 8765.",
    "Copiar ligação": "Copy link",
    "Gerar código novo": "Generate new code",
    "A ligação antiga deixa de funcionar (por exemplo, se a partilhou sem querer).":
        "The old link stops working (for example, if you shared it by mistake).",
    "Código novo gerado — a ligação antiga deixou de funcionar.": "New code generated — the old link no longer works.",
    "Ligação copiada.": "Link copied.",
    "Se o telemóvel não abrir: confirme que está na mesma rede e que a firewall deixa entrar ligações na porta "
    "(página Internet → Firewall).":
        "If the phone can't open it: check it is on the same network and that the firewall allows connections on "
        "the port (Internet page → Firewall).",
    "Este PC não parece estar ligado a uma rede local — o telemóvel não o vai encontrar.":
        "This PC doesn't seem to be on a local network — the phone won't find it.",
    "Código errado — abra a ligação mostrada no Nexo.": "Wrong code — open the link shown in Nexo.",
    # BIOS
    "Versão instalada, há quanto tempo saiu e onde procurar uma mais recente. Versões novas trazem correções de "
    "segurança e estabilidade e suporte para processadores e memórias novos.":
        "Installed version, how old it is and where to look for a newer one. New versions bring security and "
        "stability fixes and support for newer processors and memory.",
    "Verificar": "Check",
    "Versão": "Version",
    "Placa-mãe": "Motherboard",
    "Ainda não verificado.": "Not checked yet.",
    "Página de suporte do fabricante": "Manufacturer's support page",
    "Atualizar pelo fwupd": "Update with fwupd",
    "Abre um terminal com «fwupdmgr update» — confirme lá cada passo. Não desligue o PC durante a atualização.":
        "Opens a terminal with «fwupdmgr update» — confirm each step there. Don't turn off the PC during the update.",
    "O Nexo não instala o BIOS: use a ferramenta do fabricante (ex.: M-Flash, EZ Flash, Q-Flash) ou o fwupd. Não "
    "desligue o PC durante uma atualização do BIOS.":
        "Nexo doesn't install the BIOS: use the manufacturer's tool (e.g. M-Flash, EZ Flash, Q-Flash) or fwupd. "
        "Don't turn off the PC during a BIOS update.",
    "BIOS recente (menos de 1 ano).": "Recent BIOS (less than 1 year old).",
    "Não foi possível saber a data do BIOS.": "Could not determine the BIOS date.",
    # S.M.A.R.T.
    "erros de integridade dos dados": "data integrity errors",
    "setores pendentes": "pending sectors",
    "A partir de hoje o Nexo guarda a evolução deste disco (uma leitura por dia) para avisar se os setores "
    "estragados começarem a subir e prever o fim da vida útil":
        "From today Nexo keeps this drive's history (one reading per day) to warn if bad sectors start rising and "
        "to predict the end of its lifespan",
    # sessões / frametimes
    "Engasgos": "Stutters",
    "Carga média": "Average load",
    "Temperatura máx.": "Max. temperature",
    "sem dados": "no data",
    "jogo fluido": "smooth gameplay",
    "alguns engasgos": "some stutters",
    "Fotograma médio": "Average frame",
    "Fotograma mais lento": "Slowest frame",
    "Engasgo": "Stutter",
    "Linha de baixo: quanto demorou em média cada fotograma (menos é melhor). Linha de cima: o fotograma mais lento "
    "de cada momento. Os pontos vermelhos são engasgos — fotogramas 2,5× mais lentos do que o normal, que se sentem "
    "mesmo com FPS alto.":
        "Bottom line: how long each frame took on average (lower is better). Top line: the slowest frame at each "
        "moment. Red dots are stutters — frames 2.5× slower than normal, which you feel even at high FPS.",
    "Esta fonte de FPS só dá a média de cada segundo (RTSS), por isso não há o fotograma mais lento nem a contagem de "
    "engasgos. Com o PresentMon (Windows) ou o MangoHud (Linux) o gráfico completo aparece.":
        "This FPS source only gives the average for each second (RTSS), so there is no slowest frame or stutter "
        "count. With PresentMon (Windows) or MangoHud (Linux) the full chart appears.",
    "Esta sessão não tem frametimes: foi gravada antes desta versão do Nexo ou sem o contador de FPS ativo (Modo jogo "
    "→ Contador de FPS).":
        "This session has no frametimes: it was recorded before this version of Nexo or without the FPS counter "
        "enabled (Game mode → FPS counter).",
    "Clique numa sessão para ver o gráfico de frametimes.\n«1 % low»: o FPS abaixo do qual o jogo esteve 1 % do tempo "
    "— mostra as quebras melhor do que a média. «Engasgos»: segundos com um fotograma 2,5× mais lento do que o "
    "normal.":
        "Click a session to see the frametime chart.\n«1 % low»: the FPS the game was below 1 % of the time — shows "
        "drops better than the average. «Stutters»: seconds with a frame 2.5× slower than normal.",
    "Fechar": "Close",
    # testes de periféricos
    "Verifique se tudo funciona como deve — útil depois de comprar um monitor, rato ou teclado novo (ainda dentro do "
    "prazo de devolução).":
        "Check that everything works as it should — useful after buying a new monitor, mouse or keyboard (while you "
        "can still return it).",
    "Ecrã": "Screen",
    "Rato": "Mouse",
    "Teclado": "Keyboard",
    "Som e microfone": "Sound and microphone",
    "Píxeis mortos ou presos, fugas de luz, degradê e ghosting (ecrã inteiro).":
        "Dead or stuck pixels, backlight bleed, gradient and ghosting (full screen).",
    "Polling rate, botões, roda e cliques duplos fantasma.": "Polling rate, buttons, wheel and phantom double clicks.",
    "Todas as teclas e quantas funcionam ao mesmo tempo.": "Every key and how many work at the same time.",
    "Coluna esquerda/direita e nível do microfone.": "Left/right speaker and microphone level.",
    "Preto — píxeis acesos (presos) aparecem como pontos de cor": "Black — lit (stuck) pixels show up as coloured dots",
    "Branco — píxeis mortos aparecem como pontos pretos; manchas = uniformidade":
        "White — dead pixels show up as black dots; blotches = uniformity",
    "Vermelho": "Red",
    "Verde": "Green",
    "Azul": "Blue",
    "Cinzento — manchas escuras nos cantos são «fugas de luz» (normal até certo ponto)":
        "Grey — bright patches in the corners are «backlight bleed» (normal up to a point)",
    "Degradê — riscas em vez de uma transição suave indicam pouca profundidade de cor":
        "Gradient — bands instead of a smooth transition indicate low colour depth",
    "Movimento — um rasto atrás dos blocos é ghosting (tempo de resposta lento); tente o modo «overdrive» do monitor":
        "Motion — a trail behind the blocks is ghosting (slow response time); try the monitor's «overdrive» mode",
    "Clique ou Espaço: seguinte · ←: anterior · Esc: sair": "Click or Space: next · ←: previous · Esc: exit",
    "Teste do rato": "Mouse test",
    "Polling rate": "Polling rate",
    "mexa o rato depressa": "move the mouse quickly",
    "Máximo medido": "Highest measured",
    "Roda": "Wheel",
    "Cliques duplos fantasma": "Phantom double clicks",
    "Mexa o rato aqui dentro em círculos rápidos": "Move the mouse in fast circles in here",
    "Esquerdo": "Left",
    "Direito": "Right",
    "Meio": "Middle",
    "Retroceder": "Back",
    "Avançar": "Forward",
    "O polling rate é quantas vezes por segundo o rato diz onde está (125, 500, 1000 Hz ou mais). Se der muito abaixo "
    "do anunciado, confirme no software do rato. No Wayland e em monitores de 60 Hz o valor pode aparecer limitado "
    "pelo ambiente gráfico.":
        "The polling rate is how many times per second the mouse reports its position (125, 500, 1000 Hz or more). "
        "If it is far below the advertised value, check the mouse software. On Wayland and 60 Hz monitors the value "
        "may be capped by the desktop.",
    "abaixo do normal": "below normal",
    "rato de 8000 Hz": "8000 Hz mouse",
    "o interruptor pode estar gasto (clica duas vezes sozinho)": "the switch may be worn (it double-clicks by itself)",
    "Teste do teclado": "Keyboard test",
    "Teclas testadas": "Keys tested",
    "carregue em todas as teclas": "press every key",
    "Ao mesmo tempo": "At the same time",
    "Última tecla": "Last key",
    "Espaço ": "Space ",
    "Verde = já funcionou. Carregue em várias teclas ao mesmo tempo (ex.: W+A+Shift+Espaço) para ver quantas o "
    "teclado deixa — teclados baratos falham algumas combinações (ghosting). Esc também é testada: para sair use o "
    "botão Fechar.":
        "Green = already worked. Press several keys at once (e.g. W+A+Shift+Space) to see how many the keyboard "
        "allows — cheap keyboards miss some combinations (ghosting). Esc is tested too: use the Close button to exit.",
    "Teste do som": "Sound test",
    "Colunas / auscultadores": "Speakers / headphones",
    "◀ Esquerda": "◀ Left",
    "Ambos": "Both",
    "Direita ▶": "Right ▶",
    "Deve ouvir o som só do lado indicado. Se vier trocado, os auscultadores estão ao contrário ou o cabo/canais estão "
    "trocados nas definições de som.":
        "You should hear the sound only on the side shown. If it is swapped, the headphones are on backwards or the "
        "cable/channels are swapped in the sound settings.",
    "Microfone": "Microphone",
    "Fale para o microfone: a barra deve mexer-se.": "Speak into the microphone: the bar should move.",
    "Não foi encontrado nenhum microfone.": "No microphone was found.",
    "Não foi possível abrir o microfone (permissões ou outro programa a usá-lo).":
        "Could not open the microphone (permissions or another program using it).",
    "Esta instalação do Nexo não tem o módulo de som do Qt (QtMultimedia).":
        "This Nexo installation doesn't have Qt's sound module (QtMultimedia).",
}

TEMPLATES_V24: dict[str, str] = {
    "{}/hora": "{}/hour",
    "{} Wh · {} h ligado": "{} Wh · {} h on",
    "{} · {} h ligado": "{} · {} h on",
    "{}: {} · {} · {} h ligado": "{}: {} · {} · {} h on",
    " · a jogar {}": " · gaming {}",
    " · a jogar {} %": " · gaming {} %",
    "Em {} dias: {} = {} · média de {} W com o PC ligado · CPU {} % · placa gráfica {} % · resto {} %":
        "In {} days: {} = {} · average {} W while on · CPU {} % · graphics card {} % · rest {} %",
    "A jogar, o PC gasta em média {} W — {} por hora de jogo.":
        "While gaming, the PC uses {} W on average — {} per hour of play.",
    "{} h {} min": "{} h {} min",
    # o que melhorar
    "{} núcleos / {} threads": "{} cores / {} threads",
    "{} núcleos / {} threads · {}": "{} cores / {} threads · {}",
    "{} GB de VRAM": "{} GB of VRAM",
    "{} pontos (1080p)": "{} points (1080p)",
    "{} · {} pontos (1080p)": "{} · {} points (1080p)",
    "{} GB de VRAM · {} pontos (1080p)": "{} GB of VRAM · {} points (1080p)",
    "{} · {}.º a comprar": "{} · buy #{}",
    "{} · Grátis": "{} · Free",
    "{} · Tudo bem": "{} · All good",
    "Limitado pela placa gráfica: {} % do tempo de jogo ({} h analisadas)":
        "Limited by the graphics card: {} % of play time ({} h analysed)",
    "Limitado pelo processador (ou pelo jogo): {} %": "Limited by the processor (or the game): {} %",
    "Não foi possível analisar: {}": "Could not analyse: {}",
    "Ainda há pouco tempo de jogo registado para saber o que limita o PC nos jogos (precisa de {} min com o Nexo "
    "aberto).":
        "There isn't enough recorded play time yet to know what limits the PC in games (needs {} min with Nexo open).",
    "Nos jogos, a placa gráfica esteve no limite em {} % do tempo — é ela que decide o FPS.":
        "In games, the graphics card was maxed out {} % of the time — it is what decides the FPS.",
    "Nos jogos, a placa gráfica ficou folgada (abaixo de {} %) com FPS abaixo de {} em {} % do tempo — o processador "
    "(ou o próprio jogo) não a consegue alimentar.":
        "In games, the graphics card had headroom (below {} %) with FPS under {} for {} % of the time — the processor "
        "(or the game itself) can't keep it fed.",
    "A memória está a {} MT/s em vez de {}. Ligar o perfil XMP (Intel) ou EXPO/DOCP (AMD) dá mais desempenho sem "
    "gastar nada — sobretudo nos jogos limitados pela CPU.":
        "Memory is running at {} MT/s instead of {}. Enabling the XMP (Intel) or EXPO/DOCP (AMD) profile gives more "
        "performance for free — especially in CPU-limited games.",
    "A memória está a {}. Ligar o perfil XMP (Intel) ou EXPO/DOCP (AMD) dá mais desempenho sem gastar nada — "
    "sobretudo nos jogos limitados pela CPU.":
        "Memory is running {}. Enabling the XMP (Intel) or EXPO/DOCP (AMD) profile gives more performance for free — "
        "especially in CPU-limited games.",
    "Pôr o monitor a {} Hz": "Set the monitor to {} Hz",
    "Está a {} Hz. Mude nas definições de ecrã (e use um cabo DisplayPort ou HDMI 2.0+).":
        "It is running at {} Hz. Change it in the display settings (and use a DisplayPort or HDMI 2.0+ cable).",
    "Tem {} GB — pouco para o Windows/Linux atual com navegador e jogos abertos. 16 GB (2 módulos iguais, dual "
    "channel) é o mínimo recomendado hoje.":
        "It has {} GB — little for today's Windows/Linux with a browser and games open. 16 GB (2 identical modules, "
        "dual channel) is the recommended minimum today.",
    "A RAM chegou aos {} % em {}.": "RAM reached {} % in {}.",
    "Tem {} GB.": "It has {} GB.",
    "Quando a RAM enche, o sistema usa o disco e o jogo engasga. Passar para {} GB resolve.":
        "When RAM fills up, the system uses the drive and the game stutters. Going to {} GB fixes it.",
    "No benchmark fez {} pontos em 1080p (uma RX 6500 XT faz ~1500).":
        "It scored {} points in the 1080p benchmark (an RX 6500 XT scores ~1500).",
    "FPS médio abaixo de 60 em: {}.": "Average FPS below 60 in: {}.",
    "Os jogos já correm a ~{} FPS em média: só vale a pena se quiser mais FPS ou mais qualidade gráfica.":
        "Games already run at ~{} FPS on average: only worth it if you want more FPS or higher graphics quality.",
    "Escolha uma placa com pelo menos 8 GB de VRAM (a atual tem {} GB).":
        "Choose a card with at least 8 GB of VRAM (the current one has {} GB).",
    "A memória da placa gráfica encheu em {}: baixe a qualidade das texturas ou, numa próxima placa, escolha uma com "
    "mais VRAM.":
        "The graphics card memory filled up in {}: lower texture quality or, for your next card, choose one with "
        "more VRAM.",
    "No benchmark fez {} (um i5-12400F faz ~1290 / 196).": "In the benchmark it scored {} (an i5-12400F scores ~1290 / 196).",
    "{} multi-core": "{} multi-core",
    "{} single-core": "{} single-core",
    "Tem {} threads — muitos jogos atuais querem 8 ou mais.": "It has {} threads — many current games want 8 or more.",
    # snapshots
    "último: {}": "latest: {}",
    "Restaurar no {}…": "Restore in {}…",
    "Apagar {} snapshot(s) ({})? Deixa de ser possível voltar a esses pontos. O sistema atual não é alterado.":
        "Delete {} snapshot(s) ({})? It will no longer be possible to go back to those points. The current system "
        "is not changed.",
    "{} snapshot(s) apagado(s).": "{} snapshot(s) deleted.",
    "Abri o {}. Escolha o snapshot e siga os passos — no fim reinicie o PC.":
        "Opened {}. Choose the snapshot and follow the steps — restart the PC at the end.",
    "Não foi possível abrir o {}: {}": "Could not open {}: {}",
    "O sistema está em {}: snapshots instantâneos precisam de btrfs. O Timeshift em modo rsync funciona em qualquer "
    "sistema de ficheiros, mas cada cópia demora minutos e ocupa espaço.":
        "The system is on {}: instant snapshots need btrfs. Timeshift in rsync mode works on any file system, but "
        "each copy takes minutes and uses space.",
    "Abri uma janela de comandos com: {}": "Opened a command window with: {}",
    # painel / BIOS
    "Não foi possível usar a porta {}: {}": "Could not use port {}: {}",
    "há {} anos": "{} years ago",
    "há {} meses": "{} months ago",
    "Há uma versão nova do firmware: {}. Instale-a pelo fwupd (Atualizar o BIOS).":
        "There is a new firmware version: {}. Install it with fwupd (Update the BIOS).",
    "O BIOS tem {} anos. Os fabricantes costumam lançar versões com correções de segurança, estabilidade e suporte "
    "para processadores/memórias mais recentes — veja na página de suporte se há uma versão nova.":
        "The BIOS is {} years old. Manufacturers usually release versions with security and stability fixes and "
        "support for newer processors/memory — check the support page for a new version.",
    "O BIOS tem {} anos. Vale a pena confirmar se há uma versão nova.":
        "The BIOS is {} years old. It's worth checking whether there's a newer version.",
    "Há uma atualização do BIOS/UEFI: {}.": "There is a BIOS/UEFI update: {}.",
    "Não foi possível ler o BIOS: {}": "Could not read the BIOS: {}",
    # S.M.A.R.T.
    "Os {} subiram de {} para {} em {} dias — e continuam a subir. Faça já uma cópia dos dados importantes.":
        "The {} went up from {} to {} in {} days — and are still rising. Back up your important data now.",
    "Os {} subiram de {} para {} em {} dias. Vigie: se voltarem a subir, o disco está a degradar-se.":
        "The {} went up from {} to {} in {} days. Keep an eye on it: if they rise again, the drive is degrading.",
    "Ao ritmo atual, o SSD chega ao fim da vida útil daqui a ~{} meses. Planeie a substituição.":
        "At the current rate, the SSD reaches the end of its lifespan in ~{} months. Plan a replacement.",
    "Ao ritmo atual, o SSD dura mais ~{} anos (gasta {} % de vida por ano).":
        "At the current rate, the SSD lasts another ~{} years (uses {} % of its life per year).",
    "Desgaste lento: ao ritmo atual dura mais de {} anos ({} % por ano).":
        "Slow wear: at the current rate it lasts more than {} years ({} % per year).",
    "Histórico de {} dias": "{} days of history",
    "escreve ~{} por dia": "writes ~{} per day",
    "a previsão da vida útil precisa de {} dias de histórico": "the lifespan forecast needs {} days of history",
    # sessões
    "{} por minuto — muitos": "{} per minute — a lot",
    "GPU {}": "GPU {}",
    "CPU {}": "CPU {}",
    "1 % low {} · mín. {}": "1 % low {} · min. {}",
    # periféricos
    "cliques com menos de {} ms": "clicks less than {} ms apart",
    "rato de ~{} Hz": "~{} Hz mouse",
    "máximo {}": "max {}",
    "código {}": "code {}",
    "O microfone está a captar som ({} dBFS).": "The microphone is picking up sound ({} dBFS).",
    "O microfone está a captar som ({} dBFS). Está a saturar — baixe o ganho.":
        "The microphone is picking up sound ({} dBFS). It is clipping — lower the gain.",
}
