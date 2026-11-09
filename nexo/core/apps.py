"""Instalador de aplicações (ao estilo do WinUtil do Chris Titus).

Windows: winget (vem com o Windows 10/11 através do "Instalador de Aplicações").
Linux: Flatpak + Flathub (funciona em qualquer distribuição; instala só para o utilizador, sem palavra-passe).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .util import IS_LINUX, IS_WIN, run, which


@dataclass(frozen=True)
class App:
    name: str
    desc: str
    category: str
    winget: str = ""     # ID do winget
    flatpak: str = ""    # ID do Flathub

    @property
    def pkg_id(self) -> str:
        return self.winget if IS_WIN else self.flatpak if IS_LINUX else ""


N, C, J, M, P, D, U, R = ("Navegadores", "Comunicação", "Jogos", "Multimédia", "Produtividade",
                          "Programação", "Utilitários", "Componentes")
CATEGORIES = [N, C, J, M, P, D, U, R]

CATALOG: list[App] = [
    # navegadores
    App("Firefox", "Navegador livre da Mozilla.", N, "Mozilla.Firefox", "org.mozilla.firefox"),
    App("Google Chrome", "Navegador da Google.", N, "Google.Chrome", "com.google.Chrome"),
    App("Brave", "Navegador com bloqueio de anúncios incluído.", N, "Brave.Brave", "com.brave.Browser"),
    App("LibreWolf", "Firefox focado na privacidade.", N, "LibreWolf.LibreWolf", "io.gitlab.librewolf-community"),
    App("Vivaldi", "Navegador muito personalizável.", N, "Vivaldi.Vivaldi", "com.vivaldi.Vivaldi"),
    # comunicação
    App("Discord", "Voz, vídeo e texto para comunidades e jogos.", C, "Discord.Discord", "com.discordapp.Discord"),
    App("Telegram", "Mensagens rápidas e sincronizadas.", C, "Telegram.TelegramDesktop", "org.telegram.desktop"),
    App("Signal", "Mensagens com cifragem ponta a ponta.", C, "OpenWhisperSystems.Signal", "org.signal.Signal"),
    App("Zoom", "Videoconferências.", C, "Zoom.Zoom", "us.zoom.Zoom"),
    App("Thunderbird", "Cliente de email da Mozilla.", C, "Mozilla.Thunderbird", "org.mozilla.Thunderbird"),
    # jogos
    App("Steam", "Loja e biblioteca de jogos da Valve.", J, "Valve.Steam", "com.valvesoftware.Steam"),
    App("Epic Games Launcher", "Loja da Epic (jogos grátis semanais).", J, "EpicGames.EpicGamesLauncher"),
    App("Heroic Games Launcher", "Epic, GOG e Amazon Games num só sítio.", J,
        "HeroicGamesLauncher.HeroicGamesLauncher", "com.heroicgameslauncher.hgl"),
    App("GOG Galaxy", "Loja GOG (jogos sem DRM).", J, "GOG.Galaxy"),
    App("Lutris", "Gestor de jogos para Linux (Wine, emuladores…).", J, "", "net.lutris.Lutris"),
    App("ProtonUp-Qt", "Instala versões do Proton-GE / Wine-GE.", J, "", "net.davidotek.pupgui2"),
    App("Prism Launcher", "Launcher de Minecraft com várias instâncias.", J,
        "PrismLauncher.PrismLauncher", "org.prismlauncher.PrismLauncher"),
    App("MSI Afterburner", "Overclock e monitorização da GPU.", J, "Guru3D.Afterburner"),
    # multimédia
    App("VLC", "Reproduz praticamente qualquer vídeo ou música.", M, "VideoLAN.VLC", "org.videolan.VLC"),
    App("Spotify", "Música em streaming.", M, "Spotify.Spotify", "com.spotify.Client"),
    App("OBS Studio", "Gravação e transmissão em direto.", M, "OBSProject.OBSStudio", "com.obsproject.Studio"),
    App("Audacity", "Editor de áudio.", M, "Audacity.Audacity", "org.audacityteam.Audacity"),
    App("GIMP", "Editor de imagem avançado.", M, "GIMP.GIMP", "org.gimp.GIMP"),
    App("Krita", "Pintura digital e ilustração.", M, "KDE.Krita", "org.kde.krita"),
    App("Kdenlive", "Editor de vídeo.", M, "KDE.Kdenlive", "org.kde.kdenlive"),
    App("HandBrake", "Converter e comprimir vídeos.", M, "HandBrake.HandBrake", "fr.handbrake.ghb"),
    App("Blender", "Modelação 3D, animação e render.", M, "BlenderFoundation.Blender", "org.blender.Blender"),
    # produtividade
    App("LibreOffice", "Suite de escritório livre (Writer, Calc, Impress).", P,
        "TheDocumentFoundation.LibreOffice", "org.libreoffice.LibreOffice"),
    App("ONLYOFFICE", "Escritório muito compatível com ficheiros do Office.", P,
        "ONLYOFFICE.DesktopEditors", "org.onlyoffice.desktopeditors"),
    App("Obsidian", "Notas em Markdown ligadas entre si.", P, "Obsidian.Obsidian", "md.obsidian.Obsidian"),
    App("SumatraPDF", "Leitor de PDF muito leve.", P, "SumatraPDF.SumatraPDF"),
    App("Okular", "Leitor de PDF e documentos.", P, "", "org.kde.okular"),
    App("Bitwarden", "Gestor de palavras-passe.", P, "Bitwarden.Bitwarden", "com.bitwarden.desktop"),
    App("KeePassXC", "Gestor de palavras-passe offline.", P, "KeePassXCTeam.KeePassXC", "org.keepassxc.KeePassXC"),
    # programação
    App("Visual Studio Code", "Editor de código.", D, "Microsoft.VisualStudioCode", "com.visualstudio.code"),
    App("Git", "Controlo de versões.", D, "Git.Git"),
    App("Python 3", "Linguagem Python.", D, "Python.Python.3.12"),
    App("Node.js LTS", "JavaScript fora do navegador.", D, "OpenJS.NodeJS.LTS"),
    App("Notepad++", "Editor de texto leve.", D, "Notepad++.Notepad++"),
    App("Windows Terminal", "Terminal moderno com separadores.", D, "Microsoft.WindowsTerminal"),
    App("PowerShell 7", "Versão mais recente do PowerShell.", D, "Microsoft.PowerShell"),
    # utilitários
    App("7-Zip", "Comprimir e extrair (zip, 7z, rar…).", U, "7zip.7zip"),
    App("PowerToys", "Ferramentas extra da Microsoft (FancyZones, PowerRename…).", U, "Microsoft.PowerToys"),
    App("Everything", "Encontra qualquer ficheiro instantaneamente.", U, "voidtools.Everything"),
    App("ShareX", "Capturas de ecrã e gravações.", U, "ShareX.ShareX"),
    App("qBittorrent", "Cliente de torrents sem anúncios.", U, "qBittorrent.qBittorrent", "org.qbittorrent.qBittorrent"),
    App("LibreHardwareMonitor", "Sensores completos — o Nexo lê-os automaticamente.", U,
        "LibreHardwareMonitor.LibreHardwareMonitor"),
    App("HWiNFO", "Informação e sensores detalhados.", U, "REALiX.HWiNFO"),
    App("CPU-Z", "Detalhes da CPU, RAM e placa-mãe.", U, "CPUID.CPU-Z"),
    App("CrystalDiskInfo", "Saúde (SMART) dos discos.", U, "CrystalDewWorld.CrystalDiskInfo"),
    App("WinDirStat", "Mapa visual do espaço em disco.", U, "WinDirStat.WinDirStat"),
    App("Rufus", "Criar pens USB de arranque.", U, "Rufus.Rufus"),
    App("Ventoy", "Várias ISOs na mesma pen USB.", U, "Ventoy.Ventoy"),
    App("Mission Center", "Monitor do sistema ao estilo do Gestor de Tarefas.", U, "", "io.missioncenter.MissionCenter"),
    App("Flatseal", "Gerir permissões das apps Flatpak.", U, "", "com.github.tchx84.Flatseal"),
    App("Bottles", "Correr programas do Windows no Linux.", U, "", "com.usebottles.bottles"),
    App("Impression", "Criar pens USB de arranque.", U, "", "io.gitlab.adhami3310.Impression"),
    # componentes (Windows)
    App("Visual C++ Redistributable", "Necessário para muitos jogos e programas.", R, "Microsoft.VCRedist.2015+.x64"),
    App(".NET Desktop Runtime 8", "Necessário para várias aplicações.", R, "Microsoft.DotNet.DesktopRuntime.8"),
    App("DirectX (runtime)", "Bibliotecas DirectX antigas usadas por jogos.", R, "Microsoft.DirectX"),
]


def available_apps() -> list[App]:
    return [a for a in CATALOG if a.pkg_id]


def backend() -> tuple[str | None, str]:
    """(nome do gestor, mensagem se não estiver disponível)."""
    if IS_WIN:
        if which("winget"):
            return "winget", ""
        return None, ("O winget não está instalado. Instale o \"Instalador de Aplicações\" (App Installer) "
                      "pela Microsoft Store e volte a abrir esta página.")
    if IS_LINUX:
        if which("flatpak"):
            return "flatpak", ""
        return None, ("O Flatpak não está instalado. Instale-o pelo gestor de pacotes da distribuição "
                      "(ex.: sudo pacman -S flatpak · sudo apt install flatpak · sudo dnf install flatpak).")
    return None, "Sistema não suportado."


_WG = ["--accept-source-agreements", "--disable-interactivity"]


def installed_ids() -> set[str]:
    """IDs instalados (só os do catálogo, para ser rápido e fiável)."""
    b, _ = backend()
    if b == "winget":
        code, out = run(["winget", "list", *_WG], timeout=120)
        low = out.lower()
        return {a.winget for a in available_apps() if re.search(r"(?<![\w.])" + re.escape(a.winget.lower()) + r"(?![\w.])", low)}
    if b == "flatpak":
        code, out = run(["flatpak", "list", "--app", "--columns=application"], timeout=60)
        have = {ln.strip() for ln in out.splitlines() if ln.strip()}
        return {a.flatpak for a in available_apps() if a.flatpak in have}
    return set()


def _ensure_flathub() -> None:
    run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub",
         "https://dl.flathub.org/repo/flathub.flatpakrepo"], timeout=60)


def install(pkg: str) -> tuple[bool, str]:
    b, msg = backend()
    if b == "winget":
        code, out = run(["winget", "install", "--id", pkg, "-e", "--silent", "--accept-package-agreements", *_WG],
                        timeout=1800)
        ok = code == 0 or "already installed" in out.lower() or "já instalad" in out.lower()
        return ok, _tail(out)
    if b == "flatpak":
        _ensure_flathub()
        code, out = run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", pkg], timeout=1800)
        return code == 0, _tail(out)
    return False, msg


def uninstall(pkg: str) -> tuple[bool, str]:
    b, msg = backend()
    if b == "winget":
        code, out = run(["winget", "uninstall", "--id", pkg, "-e", "--silent", *_WG], timeout=900)
        return code == 0, _tail(out)
    if b == "flatpak":
        code, out = run(["flatpak", "uninstall", "-y", "--noninteractive", pkg], timeout=900)
        return code == 0, _tail(out)
    return False, msg


def upgrade_all() -> tuple[bool, str]:
    """Atualiza TODAS as aplicações instaladas pelo gestor (não só as do catálogo)."""
    b, msg = backend()
    if b == "winget":
        code, out = run(["winget", "upgrade", "--all", "--silent", "--include-unknown",
                         "--accept-package-agreements", *_WG], timeout=3600)
        return code == 0, _tail(out, 6)
    if b == "flatpak":
        code, out = run(["flatpak", "update", "-y", "--noninteractive"], timeout=3600)
        return code == 0, _tail(out, 6)
    return False, msg


def _tail(out: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in out.replace("\r", "\n").splitlines()
             if ln.strip() and not set(ln.strip()) <= set("-\\|/█▒ ")]
    return "\n".join(lines[-n:]) or "Feito"
