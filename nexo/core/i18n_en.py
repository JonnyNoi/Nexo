"""Catálogo português → inglês (ver i18n.py). Chaves = texto exato da interface."""

EN: dict[str, str] = {
    # ------------------------------------------------------------------ menu e janela
    "SISTEMA": "SYSTEM", "DESEMPENHO": "PERFORMANCE", "FERRAMENTAS": "TOOLS",
    "Visão geral": "Overview", "Informação": "Information", "Sensores": "Sensors", "Discos": "Disks",
    "Saúde dos discos": "Disk health", "Espaço em disco": "Disk space", "Processos": "Processes",
    "Antivírus": "Antivirus", "Otimização": "Optimisation", "Arranque": "Startup", "Windows debloat": "Windows debloat",
    "Modo jogo": "Game mode", "Fiabilidade": "Reliability", "Testes": "Tests", "Benchmark": "Benchmark",
    "Stress test": "Stress test", "Software": "Software", "Atualizações": "Updates",
    "Instalar aplicações": "Install apps", "Internet": "Internet", "Utilitários": "Utilities",
    "Tarefas agendadas": "Scheduled tasks", "Fundo de ecrã": "Wallpaper", "Definições": "Settings",
    "Procurar…": "Search…", "Pesquisa rápida": "Quick search",
    "Porque está lento?": "Why is it slow?", "Diagnosticar agora": "Diagnose now",
    "Pesquisa rápida: páginas, funções, opções e temas (Ctrl+K)": "Quick search: pages, features, options and themes (Ctrl+K)",
    "Tema escuro ou claro": "Dark or light theme", "Tema": "Theme", "Menu compacto": "Compact menu",
    "Mudar o fundo do ambiente de trabalho…": "Change the desktop wallpaper…", "a verificar…": "checking…",
    "Reabrir com privilégios de administrador": "Reopen with administrator privileges",
    "Expandir o menu (Ctrl+B)": "Expand the menu (Ctrl+B)",
    "Menu compacto, só com ícones (Ctrl+B)": "Compact menu, icons only (Ctrl+B)",
    "Abrir Nexo": "Open Nexo", "Alertas": "Alerts", "Sair": "Quit", "Página atualizada.": "Page refreshed.",
    "O Nexo continua a correr na bandeja. Para sair: botão direito no ícone → Sair.":
        "Nexo keeps running in the tray. To quit: right-click the icon → Quit.",
    "Ligação à internet — clique para abrir a página Internet": "Internet connection — click to open the Internet page",
    "<i>Clique para abrir o teste de velocidade</i>": "<i>Click to open the speed test</i>",
    "Alertas (Ctrl+Shift+A)": "Alerts (Ctrl+Shift+A)", "Escuro": "Dark", "Claro": "Light",
    # ------------------------------------------------------------------ títulos e subtítulos das páginas
    "Estado do PC em tempo real": "Your PC's status in real time",
    "Informação do sistema": "System information",
    "Sistema operativo, processador, memória, placa gráfica, ecrã, placa-mãe, discos e rede":
        "Operating system, processor, memory, graphics card, display, motherboard, disks and network",
    "Como estão as peças do PC agora — atualizado a cada segundo": "How your PC's parts are doing — updated every second",
    "As aplicações abertas e quanto estão a gastar — feche as que estão a pesar":
        "Open apps and how much they use — close the heavy ones",
    "Ajustes de desempenho reversíveis e programas em segundo plano que gastam RAM":
        "Reversible performance tweaks and background programs using RAM",
    "Programas que abrem sozinhos com o sistema. Desativar não desinstala nada e pode voltar a ativar a qualquer momento.":
        "Programs that open with the system. Disabling uninstalls nothing and you can turn them back on any time.",
    "Remove apps pré-instaladas e desliga telemetria, anúncios e sugestões. Nada que reduza a segurança (Defender, SmartScreen, UAC, Windows Update).":
        "Removes preinstalled apps and turns off telemetry, ads and suggestions. Nothing that lowers security (Defender, SmartScreen, UAC, Windows Update).",
    "Deteta quando está a jogar e mostra temperaturas e uso por cima do jogo":
        "Detects when you're gaming and shows temperatures and usage over the game",
    "Carga máxima na CPU (todos os threads) e/ou teste de RAM com verificação de erros. Pára sozinho ao atingir o limite de temperatura.":
        "Full CPU load (all threads) and/or RAM test with error checking. Stops by itself at the temperature limit.",
    "CPU: path tracer próprio (iluminação global, reflexos, vidro com refração). Placa gráfica: cena 3D em OpenGL. Imagens sempre iguais — as notas comparam-se entre PCs.":
        "CPU: built-in path tracer (global illumination, reflections, refractive glass). Graphics card: OpenGL 3D scene. Always the same images — scores compare across PCs.",
    "Veja o que há para atualizar no sistema e nas aplicações — o Nexo só procura; instalar fica sempre a seu pedido.":
        "See what can be updated in the system and apps — Nexo only checks; installing is always up to you.",
    "Teste de velocidade, qualidade e diagnóstico da ligação": "Speed test, quality and connection diagnostics",
    "Fundo do ambiente de trabalho": "Desktop wallpaper",
    "Lê os dados S.M.A.R.T. que cada disco regista sobre si próprio e diz se está de boa saúde, quanto já gastou e se há sinais de avaria.":
        "Reads the S.M.A.R.T. data each disk records about itself and tells you whether it is healthy, how worn it is and whether there are signs of failure.",
    "Analisa o disco e diz o que é seguro apagar (caches, jogos…) e o que é do sistema e não se deve tocar":
        "Analyses the disk and tells you what is safe to delete (caches, games…) and what belongs to the system and must not be touched",
    "Aparência, alertas, proteção, bandeja do sistema, arranque e dados do Nexo":
        "Appearance, alerts, protection, system tray, startup and Nexo data",
    "O que o Nexo faz sozinho em segundo plano — só enquanto está aberto (ou na bandeja) e nunca durante um jogo.":
        "What Nexo does on its own in the background — only while it is open (or in the tray) and never during a game.",
    # ------------------------------------------------------------------ visão geral
    "Saúde do PC": "PC health", "Pontuação da saúde do PC": "PC health score", "A avaliar…": "Evaluating…",
    "Pontuação de 0 a 100 a partir das verificações abaixo.": "Score from 0 to 100 based on the checks below.",
    "Processador": "Processor", "Placa gráfica": "Graphics card", "Memória": "Memory", "Sistema": "System",
    "Utilização": "Usage", "Disco do sistema": "System disk", "Ainda sem resultados de benchmark.": "No benchmark results yet.",
    "Temp. CPU": "CPU temp.", "Temp. GPU": "GPU temp.", "Rede": "Network", "Disco": "Disk",
    "Saúde do sistema": "System health",
    "Verificações automáticas — os botões levam à página que resolve.": "Automatic checks — the buttons take you to the page that fixes it.",
    "Temperatura": "Temperature", "Carga": "Load", "Consumo": "Power", "de 100": "of 100",
    "Está tudo em ordem — nada para fazer agora.": "Everything is fine — nothing to do right now.",
    "sem dados": "no data", "Pacote da CPU": "CPU package", "Sensor indisponível": "Sensor unavailable",
    "Resolver": "Fix", "Excelente": "Excellent", "Boa": "Good", "Precisa de atenção": "Needs attention", "Má": "Poor",
    "Sistema atualizado.": "System up to date.", "Análise antivírus recente.": "Recent antivirus scan.",
    "Atualizar": "Update", "Ver": "View", "Analisar": "Scan", "Ativar": "Enable",
    "Ainda não fez nenhuma análise antivírus.": "You haven't run an antivirus scan yet.",
    "Pontos de restauro desligados — ative-os para poder voltar atrás.": "Restore points are off — turn them on so you can roll back.",
    # ------------------------------------------------------------------ centro de alertas
    "Marcar como lidos": "Mark as read", "Limpar": "Clear", "Fechar (Esc)": "Close (Esc)",
    "Fechar os alertas": "Close alerts", "Abrir": "Open",
    "Os alertas ficam guardados aqui (os últimos 200). Configure-os em Definições → Alertas.":
        "Alerts are kept here (the last 200). Configure them in Settings → Alerts.",
    "Sem alertas. Quando alguma coisa precisar de atenção (temperatura, memória, discos, atualizações…) aparece aqui.":
        "No alerts. When something needs attention (temperature, memory, disks, updates…) it shows up here.",
    "agora": "now", "nenhum por ler": "none unread",
    # ------------------------------------------------------------------ tarefas agendadas
    "Desligada": "Off", "Diária": "Daily", "Semanal": "Weekly", "A cada 2 semanas": "Every 2 weeks", "Mensal": "Monthly",
    "Limpeza automática": "Automatic cleanup", "Análise antivírus rápida": "Quick antivirus scan",
    "Saúde dos discos (S.M.A.R.T.)": "Disk health (S.M.A.R.T.)",
    "Miniaturas, caches de pacotes e temporários que se refazem sozinhos. Sem palavra-passe; o Lixo e as caches dos navegadores ficam de fora.":
        "Thumbnails, package caches and temporary files that rebuild themselves. No password; the Trash and browser caches are left out.",
    "Lê o estado dos discos e avisa se algum piorou.": "Reads the disks' state and warns if any got worse.",
    "Lembra-o de ler o estado dos discos (no Linux é preciso a palavra-passe, por isso não corre sozinha).":
        "Reminds you to read the disks' state (on Linux this needs your password, so it doesn't run by itself).",
    "Frequência": "Frequency", "Desligada = nunca corre sozinha.": "Off = never runs by itself.",
    "Lembrar agora": "Remind now", "Executar agora": "Run now", "Concluído.": "Done.", "em breve": "soon",
    "Está na altura de verificar a saúde dos discos (S.M.A.R.T.).": "It's time to check your disks' health (S.M.A.R.T.).",
    "Lembrete mostrado.": "Reminder shown.", "Discos lidos: sem alterações.": "Disks read: no changes.",
    "As atualizações do sistema são procuradas a cada 6 horas e as do Nexo uma vez por dia (Definições). Os avisos de temperatura, memória e espaço em disco são contínuos (Definições → Alertas).":
        "System updates are checked every 6 hours and Nexo's once a day (Settings). Temperature, memory and disk-space alerts are continuous (Settings → Alerts).",
    # ------------------------------------------------------------------ perfis por jogo
    "Perfis por jogo": "Per-game profiles",
    "O que muda quando um jogo arranca — e volta ao normal quando fecha. Cada jogo pode ter o seu.":
        "What changes when a game starts — and goes back to normal when it closes. Each game can have its own.",
    "<b>Jogo</b>": "<b>Game</b>", "Jogo a configurar": "Game to configure", "Escreva ou escolha um jogo…": "Type or pick a game…",
    "Jogo atual": "Current game", "Escolher o jogo que está a correr agora": "Pick the game that is running now",
    "Usar o geral (página Ventoinhas)": "Use the general one (Fans page)",
    "Perfil enquanto este jogo está aberto.": "Profile while this game is open.", "Energia": "Power",
    "Perfil de energia durante o jogo; o anterior volta no fim.": "Power profile during the game; the previous one comes back afterwards.",
    "Overlay": "Overlay", "Sobrepõe-se à opção geral só para este jogo.": "Overrides the general option for this game only.",
    "Feral GameMode": "Feral GameMode",
    "Pede ao gamemoded prioridade de CPU e o governador de desempenho para o jogo.":
        "Asks gamemoded for CPU priority and the performance governor for the game.",
    "<b>Fechar ao começar o jogo</b> — marque os programas (pedido normal de fecho; nada é fechado à força e o lançador do jogo nunca é tocado):":
        "<b>Close when the game starts</b> — tick the programs (normal close request; nothing is force-killed and the game launcher is never touched):",
    "Programas a fechar quando o jogo arranca": "Programs to close when the game starts",
    "Atualizar lista": "Refresh list", "Apagar perfil deste jogo": "Delete this game's profile",
    "A carregar os programas abertos…": "Loading open programs…", "Nenhum programa.": "No programs.",
    "Guardado. Aplica-se na próxima vez que o jogo arrancar.": "Saved. Applies the next time the game starts.",
    "Não mudar": "Don't change", "Desempenho": "Performance", "Equilibrado": "Balanced",
    "Poupança de energia": "Power saver", "Como nas definições gerais": "As in the general settings",
    "Mostrar sempre": "Always show", "Nunca mostrar": "Never show",
    "O GameMode (gamemoded) não está instalado.": "GameMode (gamemoded) is not installed.",
    # ------------------------------------------------------------------ assistente e atalhos
    "Atalhos de teclado": "Keyboard shortcuts", "Fechar": "Close", "Saltar": "Skip", "Anterior": "Back",
    "Seguinte": "Next", "Começar": "Get started", "Pronto!": "All set!",
    "Fechar o assistente e ficar com as opções recomendadas": "Close the assistant and keep the recommended options",
    "Monitoriza, protege e otimiza o seu PC — em Linux e Windows. Em menos de um minuto deixamo-lo à sua medida; tudo pode ser mudado depois em Definições.":
        "Monitors, protects and optimises your PC — on Linux and Windows. In under a minute we'll tailor it to you; everything can be changed later in Settings.",
    "Proteger": "Protect", "Otimizar": "Optimise", "Aparência": "Appearance",
    "Temperaturas, carga, discos e saúde do PC em tempo real.": "Temperatures, load, disks and PC health in real time.",
    "Avisos, antivírus, pontos de restauro antes de mexer no sistema.": "Alerts, antivirus, restore points before changing the system.",
    "Limpeza, arranque, testes e um modo jogo com overlay e perfis.": "Cleanup, startup, tests and a game mode with overlay and profiles.",
    "Escolha o tema. Muda já, para ver como fica.": "Pick a theme. It changes right away so you can see it.",
    "Só ícones no menu lateral, para dar mais espaço às páginas (Ctrl+B alterna a qualquer momento).":
        "Icons only in the side menu, leaving more room for pages (Ctrl+B toggles any time).",
    "Avisos e proteção": "Alerts and protection",
    "O que o Nexo vigia por si, mesmo minimizado na bandeja.": "What Nexo watches for you, even minimised to the tray.",
    "Avisos importantes": "Important alerts",
    "Temperatura alta, memória quase cheia, pouco espaço em disco e saúde dos discos a piorar. Ficam no centro de alertas (sino).":
        "High temperature, memory almost full, low disk space and worsening disk health. They're kept in the alert centre (bell).",
    "Pontos de restauro": "Restore points", "Ícone na bandeja": "Tray icon",
    "Temperatura sempre à vista; clique para abrir.": "Temperature always in view; click to open.",
    "Abrir com o sistema": "Start with the system",
    "Arranca minimizado quando entra na sessão — os avisos e as tarefas agendadas só funcionam com o Nexo aberto.":
        "Starts minimised when you log in — alerts and scheduled tasks only work while Nexo is open.",
    "Tarefas automáticas": "Automatic tasks",
    "O que o Nexo faz sozinho de tempos a tempos (nunca durante um jogo). Pode ver e mudar tudo em Utilitários → Tarefas agendadas.":
        "What Nexo does on its own from time to time (never during a game). You can see and change it all in Utilities → Scheduled tasks.",
    "Jogos": "Games",
    "O modo jogo deteta Steam, Proton, Wine, Lutris, Heroic, Epic, GOG e Xbox.": "Game mode detects Steam, Proton, Wine, Lutris, Heroic, Epic, GOG and Xbox.",
    "Detetar jogos": "Detect games", "Verifica a cada 4 segundos (quase não gasta nada).": "Checks every 4 seconds (uses almost nothing).",
    "Overlay ao jogar": "Overlay while gaming", "Temperaturas, FPS e uso por cima do jogo.": "Temperatures, FPS and usage over the game.",
    "Perfis silencioso/equilibrado/desempenho e curvas próprias. O Nexo só mexe nelas se escolher um perfil.":
        "Silent/balanced/performance profiles and custom curves. Nexo only touches them if you pick a profile.",
    "O menu está agrupado: SISTEMA para ver o estado do PC, DESEMPENHO para o otimizar e FERRAMENTAS para o resto. Comece pela Visão geral — a «Saúde do PC» diz o que vale a pena fazer.":
        "The menu is grouped: SYSTEM to see your PC's state, PERFORMANCE to optimise it and TOOLS for the rest. Start with the Overview — “PC health” tells you what's worth doing.",
    "<b>Atalhos úteis</b>": "<b>Useful shortcuts</b>",
    "Pesquisa rápida: páginas, funções e opções": "Quick search: pages, features and options",
    "Ir para a entrada do menu com esse número": "Go to the menu entry with that number",
    "Página seguinte / anterior": "Next / previous page", "Menu compacto (só ícones)": "Compact menu (icons only)",
    "Centro de alertas": "Alert centre", "Atualizar a página aberta": "Refresh the open page",
    "Esta lista de atalhos": "This list of shortcuts",
    "Saltar entre botões e opções (o elemento com foco fica contornado)": "Move between buttons and options (the focused element is outlined)",
    "Espaço / Enter": "Space / Enter", "Carregar no botão ou interruptor com foco": "Press the focused button or switch",
    "Fechar a pesquisa, os alertas ou uma janela": "Close the search, the alerts or a dialog", "Sair do Nexo": "Quit Nexo",
    # ------------------------------------------------------------------ definições
    "Aviso (notificação do sistema + mensagem na janela) quando algo precisa de atenção. Funciona também com a janela minimizada na bandeja.":
        "Warning (system notification + in-window message) when something needs attention. Also works with the window minimised to the tray.",
    "Temperatura alta": "High temperature",
    "CPU ou GPU acima do limite. No máximo um aviso a cada 5 minutos por componente.":
        "CPU or GPU above the limit. At most one alert every 5 minutes per component.",
    "Limite da CPU": "CPU limit", "Limite da GPU": "GPU limit",
    "A maioria das CPUs desktop começa a reduzir o clock perto dos 95–100 °C.": "Most desktop CPUs start throttling around 95–100 °C.",
    "GPUs dedicadas trabalham normalmente abaixo dos 85 °C.": "Dedicated GPUs normally run below 85 °C.",
    "Memória quase cheia": "Memory almost full", "RAM acima deste valor durante 2 minutos seguidos.": "RAM above this value for 2 minutes in a row.",
    "Pouco espaço em disco": "Low disk space", "Verificado a cada 5 minutos em todos os discos internos.": "Checked every 5 minutes on all internal disks.",
    "Saúde dos discos a piorar": "Disk health getting worse",
    "Avisa quando o S.M.A.R.T. de um disco passa de 'bom' para 'atenção' ou 'mau' (usa a última leitura da página Saúde dos discos).":
        "Warns when a disk's S.M.A.R.T. goes from 'good' to 'attention' or 'bad' (uses the last reading from the Disk health page).",
    "Histórico dos sensores": "Sensor history", "Guardar histórico": "Keep history", "Ocupa menos de 2 MB.": "Takes less than 2 MB.",
    "Apagar histórico": "Delete history", "Janela e bandeja": "Window and tray", "Ícone na bandeja do sistema": "System tray icon",
    "Mostra temperatura e carga ao passar o rato; clique para abrir o Nexo.": "Shows temperature and load on hover; click to open Nexo.",
    "Fechar para a bandeja": "Close to tray",
    "Ao fechar a janela, o Nexo continua a monitorizar em segundo plano (para sair: menu da bandeja → Sair, ou Ctrl+Q).":
        "When you close the window, Nexo keeps monitoring in the background (to quit: tray menu → Quit, or Ctrl+Q).",
    "Abrir minimizado": "Start minimised", "Arranca diretamente na bandeja (útil com o arranque automático).": "Starts straight in the tray (useful with autostart).",
    "Transições suaves": "Smooth transitions", "Desvanecer ao mudar de página.": "Fade when switching pages.",
    "Lembrar a última página": "Remember the last page", "Volta a abrir na página onde estava.": "Reopens on the page you were on.",
    "Inicia o Nexo minimizado quando entra na sessão.": "Starts Nexo minimised when you log in.",
    "Limpa sozinho, de tempos a tempos, só o que se refaz sem custo e não precisa de palavra-passe. O Lixo, as caches dos navegadores e dos jogos ficam sempre para si decidir.":
        "Cleans by itself, from time to time, only what rebuilds at no cost and needs no password. The Trash, browser and game caches are always your call.",
    "Ver todas as tarefas agendadas": "See all scheduled tasks", "Cópia das definições": "Settings backup",
    "Guarde as suas definições (perfis das ventoinhas, overlay, alertas, jogos marcados…), o histórico dos benchmarks e das sessões de jogo num ficheiro — para levar para outro PC ou repor depois de reinstalar.":
        "Save your settings (fan profiles, overlay, alerts, marked games…), benchmark history and game sessions to a file — to take to another PC or restore after reinstalling.",
    "Exportar…": "Export…", "Importar…": "Import…", "Ficheiro .zip": ".zip file",
    "A posição da janela e outras coisas desta máquina não são copiadas.": "The window position and other machine-specific things are not copied.",
    "Atualizações do Nexo": "Nexo updates", "Procurar agora": "Check now", "Instalar e reiniciar": "Install and restart",
    "Procurar versões novas sozinho": "Check for new versions automatically",
    "Uma vez por dia, só com internet. Nada é instalado sem a sua autorização.": "Once a day, only when online. Nothing is installed without your permission.",
    "Esta cópia do Nexo não tem um endereço de atualizações configurado.": "This copy of Nexo has no update address configured.",
    "Tem a versão mais recente.": "You have the latest version.", "A procurar…": "Checking…", "A transferir…": "Downloading…",
    "Escolha o tema da aplicação. Para mudar o fundo do computador use a página 'Fundo de ecrã'.":
        "Pick the app theme. To change the computer's wallpaper use the 'Wallpaper' page.",
    "Proteção (pontos de restauro)": "Protection (restore points)",
    "Antes de ligar ajustes, remover apps ou pacotes, o Nexo cria um ponto de restauro para poder voltar atrás se algo correr mal. No máximo um a cada 30 minutos.":
        "Before enabling tweaks or removing apps or packages, Nexo creates a restore point so you can roll back if something goes wrong. At most one every 30 minutes.",
    "Criar ponto de restauro antes de alterar o sistema": "Create a restore point before changing the system",
    "Criar ponto agora": "Create point now", "A criar…": "Creating…", "Histórico apagado.": "History deleted.",
    "Ainda não há registo de erros.": "There is no error log yet.", "Dados e informação": "Data and information",
    "Abrir pasta de dados": "Open data folder", "Abrir registo de erros": "Open error log",
    "Assistente de boas-vindas": "Welcome assistant", "Voltar a ver o assistente da primeira execução": "Show the first-run assistant again",
    "Atalhos de teclado (F1)": "Keyboard shortcuts (F1)", "Idioma": "Language",
    "Idioma da interface. Muda depois de reiniciar o Nexo.": "Interface language. Changes after restarting Nexo.",
    "<b>Atalhos:</b> Ctrl+K pesquisa · Ctrl+1…Ctrl+9 mudar de página · Ctrl+Shift+A alertas · F5 atualizar · F1 todos os atalhos":
        "<b>Shortcuts:</b> Ctrl+K search · Ctrl+1…Ctrl+9 switch page · Ctrl+Shift+A alerts · F5 refresh · F1 all shortcuts",
    # ------------------------------------------------------------------ comuns
    "Cancelar": "Cancel", "Guardar": "Save", "Apagar": "Delete", "Remover": "Remove", "Instalar": "Install",
    "Desinstalar": "Uninstall", "Atualizar tudo": "Update all", "Aplicar": "Apply", "Restaurar": "Restore",
    "Sim": "Yes", "Não": "No", "Agora": "Now", "Estado": "Status", "Resultado": "Result", "Resultados": "Results",
    "Histórico": "History", "Configuração": "Configuration", "Registo": "Log", "Perfil": "Profile", "Curva": "Curve",
    "Proteção": "Protection", "Quarentena": "Quarantine", "Jogos instalados": "Installed games",
    "Sessões de jogo": "Game sessions", "Deteção de jogos": "Game detection", "Contador de FPS": "FPS counter",
    "Durante os jogos": "During games", "Programas em segundo plano": "Background programs",
    "Ligação à internet": "Internet connection", "O que a sua ligação permite": "What your connection allows",
    "Velocidade do disco": "Disk speed", "Reparar e manutenção": "Repair and maintenance",
    "Funcionalidades do Windows": "Windows features", "Painéis clássicos": "Classic panels",
    "Os meus fundos": "My wallpapers", "Fundo atual": "Current wallpaper", "Troca automática": "Automatic change",
    "Atualizações disponíveis": "Available updates", "Drivers da placa gráfica": "Graphics drivers",
    "Programas a usar a internet": "Programs using the internet", "Ficheiros dispensáveis": "Disposable files",
    "O que pode apagar": "What you can delete", "Como ler isto": "How to read this", "Apps pré-instaladas": "Preinstalled apps",
    "Temperatura e carga (últimos 5 min)": "Temperature and load (last 5 min)", "Simples": "Simple",
    "Todos os sensores": "All sensors", "Todos os processos": "All processes", "Terminar": "End",
    "Análise rápida": "Quick scan", "Análise completa": "Full scan", "Iniciar teste": "Start test",
    "Analisar pasta / disco": "Analyse folder / disk", "Ler discos": "Read disks", "Exportar relatório": "Export report",
    "Mostrar overlay agora": "Show overlay now", "Marcar como jogo": "Mark as game",
    "Detetar jogos automaticamente": "Detect games automatically", "Avisar ao começar e acabar": "Notify on start and end",
    "Mostrar automaticamente ao jogar": "Show automatically while gaming", "Posição e formato": "Position and format",
    "Procurar jogo…": "Search game…", "Últimos 7 dias": "Last 7 days", "Últimos 30 dias": "Last 30 days",
    "Desde sempre": "All time", "Últimas sessões": "Recent sessions",
}

# textos com valores no meio: "{}" apanha qualquer coisa (também traduzida pelo catálogo, se lá estiver)
TEMPLATES: dict[str, str] = {
    "Saúde do PC: {}": "PC health: {}",
    "{} problema(s) e {} aviso(s). O mais útil a fazer agora:": "{} problem(s) and {} warning(s). The most useful thing to do now:",
    "{} problema(s). O mais útil a fazer agora:": "{} problem(s). The most useful thing to do now:",
    "{} aviso(s). O mais útil a fazer agora:": "{} warning(s). The most useful thing to do now:",
    "{} problema(s) e {} aviso(s).": "{} problem(s) and {} warning(s).",
    "{} problema(s).": "{} problem(s).", "{} aviso(s).": "{} warning(s).",
    "há {} min": "{} min ago", "há {} h": "{} h ago", "ontem {}": "yesterday {}", "hoje {}": "today {}",
    "{}  ·  repetiu {}×": "{}  ·  repeated {}×", "Abrir a página {}": "Open the {} page", "Abrir {}": "Open {}",
    "Alertas — {} por ler (Ctrl+Shift+A)": "Alerts — {} unread (Ctrl+Shift+A)", "Alertas ({} por ler)": "Alerts ({} unread)",
    "Passo {} de {}": "Step {} of {}", "Bem-vindo ao {}": "Welcome to {}", "{} — atalhos de teclado": "{} — keyboard shortcuts",
    "Próxima: <b>{}</b>": "Next: <b>{}</b>", "Última: {} — {}": "Last: {} — {}", "Frequência: {}": "Frequency: {}",
    "hoje às {}": "today at {}", "amanhã às {}": "tomorrow at {}", "ontem às {}": "yesterday at {}",
    "Temperatura da {} alta: {} °C (limite {} °C)": "{} temperature high: {} °C (limit {} °C)",
    "Temperatura da {} normal ({} °C).": "{} temperature normal ({} °C).",
    "{} muito quente: {} °C — verifique ventoinhas e pasta térmica.": "{} very hot: {} °C — check the fans and thermal paste.",
    "{} quente: {} °C.": "{} hot: {} °C.",
    "RAM quase cheia ({}%).": "RAM almost full ({}%).", "RAM muito usada ({}%).": "RAM heavily used ({}%).",
    "RAM com folga ({}% em uso).": "RAM has headroom ({}% in use).",
    "Espaço em disco suficiente ({} livres).": "Enough disk space ({} free).",
    "Pouco espaço no disco do sistema ({} livres).": "Low space on the system disk ({} free).",
    "Disco do sistema quase cheio ({} livres).": "System disk almost full ({} free).",
    "Discos de boa saúde ({} verificados).": "Disks in good health ({} checked).",
    "Ligado há {} — reiniciar aplica atualizações e liberta memória.": "On for {} — restarting applies updates and frees memory.",
    "{} serviço(s) do sistema com falha.": "{} system service(s) failed.",
    "{} atualizações disponíveis.": "{} updates available.", "{} atualizações por instalar.": "{} updates to install.",
    "Última análise antivírus há {} dias.": "Last antivirus scan {} days ago.",
    "A última análise encontrou {} ameaça(s).": "The last scan found {} threat(s).",
    "Driver desatualizado: {}.": "Outdated driver: {}.",
    "Memória RAM quase cheia ({} %) há 2 minutos. Feche programas que não estejam a ser usados (página Processos ou Otimização).":
        "RAM almost full ({} %) for 2 minutes. Close programs you're not using (Processes or Optimisation page).",
    "🎮 Jogo detetado: {}": "🎮 Game detected: {}", "Sessão de {}": "{} session",
    "Fechados para o jogo: {}": "Closed for the game: {}", "Tema: {}": "Theme: {}",
    "Perfil de «{}» apagado — usa as definições gerais.": "Profile for “{}” deleted — uses the general settings.",
    "Análise antivírus agendada: {} ameaça(s) encontrada(s) — reveja na página Antivírus.":
        "Scheduled antivirus scan: {} threat(s) found — review them on the Antivirus page.",
    "Análise antivírus agendada: {} item(ns) suspeito(s) para rever.": "Scheduled antivirus scan: {} suspicious item(s) to review.",
    "Análise antivírus agendada: nada encontrado ({} ficheiros).": "Scheduled antivirus scan: nothing found ({} files).",
    "Limpeza automática: {} libertados ({}).": "Automatic cleanup: {} freed ({}).",
    "Limpeza automática: não havia nada para limpar.": "Automatic cleanup: there was nothing to clean.",
    "🧹 {}": "🧹 {}", "Falhou: {}": "Failed: {}", "Inclui: {}.": "Includes: {}.",
    "Última limpeza: {}": "Last cleanup: {}", "total libertado: {}": "total freed: {}", "Total libertado: {}": "Total freed: {}",
    "ligado há {}": "on for {}", "carga {}%": "load {}%", "{} · carga {}%": "{} · load {}%",
    "{} em uso ({}%)": "{} in use ({}%)", "{} livres": "{} free",
    "Pouco espaço no disco {}: só {} livres ({} %).": "Low space on disk {}: only {} free ({} %).",
    "Versão instalada: {}.": "Installed version: {}.",
    "Último benchmark ({}): <b>{} pts</b> · melhor: {} pts": "Last benchmark ({}): <b>{} pts</b> · best: {} pts",
    "consumo {} W": "power {} W", "leitura · escrita {} MB/s": "read · write {} MB/s",
    "Ligado há {}": "On for {}", "{} · {}": "{} · {}",
    "Processos, arranque, pastas pessoais e temporárias (com o {}). Só avisa: nada vai para a quarentena sem a sua confirmação.":
        "Processes, startup, personal and temporary folders (with {}). Only warns: nothing goes to quarantine without your confirmation.",
    "ClamAV, se estiver instalado": "ClamAV, if installed",
    "Desligada.": "Off.", "A correr…": "Running…",
    "Antes de alterar o sistema, cria um ponto para voltar atrás ({}).":
        "Before changing the system, creates a point to roll back to ({}).",
}
