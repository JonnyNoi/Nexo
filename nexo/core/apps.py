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

# --------------------------------------------------------------------------------------- deteção
# Linux: nomes de pacote (Arch / Debian / Fedora…) e executáveis, quando não são o nome da app em minúsculas.
# As variantes do AUR (-bin, -git) são reconhecidas automaticamente.
LINUX_HINTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "Google Chrome": (("google-chrome", "google-chrome-stable"), ("google-chrome-stable", "google-chrome")),
    "Brave": (("brave", "brave-browser"), ("brave", "brave-browser")),
    "Vivaldi": (("vivaldi", "vivaldi-stable"), ("vivaldi", "vivaldi-stable")),
    "Telegram": (("telegram-desktop",), ("telegram-desktop", "Telegram")),
    "Signal": (("signal-desktop",), ("signal-desktop",)),
    "Steam": (("steam", "steam-native-runtime", "steam-installer", "steam-launcher"), ("steam",)),
    "Heroic Games Launcher": (("heroic-games-launcher",), ("heroic",)),
    "ProtonUp-Qt": (("protonup-qt",), ("protonup-qt",)),
    "Prism Launcher": (("prismlauncher", "prismlauncher-qt5"), ("prismlauncher",)),
    "Spotify": (("spotify", "spotify-launcher", "spotify-client"), ("spotify", "spotify-launcher")),
    "OBS Studio": (("obs-studio", "obs-studio-tytan652", "obs-studio-browser"), ("obs",)),
    "HandBrake": (("handbrake", "handbrake-gtk"), ("ghb",)),
    "LibreOffice": (("libreoffice-fresh", "libreoffice-still", "libreoffice", "libreoffice-core"),
                    ("libreoffice", "soffice")),
    "ONLYOFFICE": (("onlyoffice", "onlyoffice-desktopeditors"), ("onlyoffice-desktopeditors",)),
    "Visual Studio Code": (("code", "visual-studio-code"), ("code",)),
    "Mission Center": (("mission-center",), ("missioncenter",)),
}

# Windows: expressão para o nome no "Adicionar/remover programas" (por omissão: o nome da app como palavra).
# None = só o winget sabe (apps da Microsoft Store / componentes).
WIN_NAMES: dict[str, str | None] = {
    "Heroic Games Launcher": r"^Heroic\b",
    "Node.js LTS": r"^Node\.js\b",
    "Visual C++ Redistributable": r"Visual C\+\+ 2015-20\d\d Redistributable \(x64\)",
    ".NET Desktop Runtime 8": r"Windows Desktop Runtime - 8\.",
    "DirectX (runtime)": None,
    "Windows Terminal": None,
    "Steam": r"^Steam$",
}

LINUX_NATIVE = {"pacman": "pacman", "apt": "apt", "rpm": "dnf/rpm", "snap": "Snap"}


@dataclass(frozen=True)
class Found:
    source: str          # "Flatpak", "winget", "pacman", "apt", "dnf/rpm", "Snap", "Windows", "AppImage/manual"
    managed: bool        # True = o Nexo consegue desinstalar/atualizar pelo gestor da página

    @property
    def label(self) -> str:
        return {"Windows": "programa do Windows", "AppImage/manual": "AppImage / manual"}.get(self.source, self.source)


def _native_packages() -> tuple[str, set[str]]:
    """(gestor, nomes dos pacotes instalados) — pacman, dpkg ou rpm."""
    for tool, cmd in (("pacman", ["pacman", "-Qq"]),
                      ("apt", ["dpkg-query", "-W", "-f=${Package}\n"]),
                      ("rpm", ["rpm", "-qa", "--qf", "%{NAME}\n"])):
        if which(cmd[0]):
            code, out = run(cmd, timeout=60)
            if code == 0:
                return LINUX_NATIVE[tool], {ln.strip().lower() for ln in out.splitlines() if ln.strip()}
    return "", set()


def _snaps() -> set[str]:
    if not which("snap"):
        return set()
    code, out = run(["snap", "list"], timeout=30)
    return {ln.split()[0].lower() for ln in out.splitlines()[1:] if ln.strip()} if code == 0 else set()


def _desktop_names() -> set[str]:
    """Nomes das entradas do menu (.desktop) — apanha AppImages integradas e instalações manuais."""
    from pathlib import Path
    dirs = [Path.home() / ".local/share/applications", Path("/usr/share/applications"),
            Path("/usr/local/share/applications"), Path("/var/lib/snapd/desktop/applications")]
    names = set()
    for d in dirs:
        try:
            files = list(d.glob("*.desktop"))
        except OSError:
            continue
        for f in files:
            try:
                for ln in f.read_text(errors="replace").splitlines():
                    if ln.startswith("Name="):
                        names.add(ln[5:].strip().lower())
                        break
            except OSError:
                pass
    return names


def _linux_candidates(a: App) -> tuple[tuple[str, ...], tuple[str, ...]]:
    base = a.name.lower().replace(" ", "-")
    pkgs, bins = LINUX_HINTS.get(a.name, ((base,), (base,)))
    return tuple(p.lower() for p in pkgs), bins


def _linux_detect(apps: list[App]) -> dict[str, Found]:
    import shutil
    flat = set()
    if which("flatpak"):
        _c, out = run(["flatpak", "list", "--app", "--columns=application"], timeout=60)
        flat = {ln.strip() for ln in out.splitlines() if ln.strip()}
    mgr, native = _native_packages()
    snaps = _snaps()
    menu: set[str] | None = None
    found: dict[str, Found] = {}
    for a in apps:
        if a.flatpak and a.flatpak in flat:
            found[a.name] = Found("Flatpak", True)
            continue
        pkgs, bins = _linux_candidates(a)
        if native and any(p in native or f"{p}-bin" in native or f"{p}-git" in native for p in pkgs):
            found[a.name] = Found(mgr, False)
        elif any(p in snaps for p in pkgs):
            found[a.name] = Found("Snap", False)
        elif any(shutil.which(b) for b in bins):
            found[a.name] = Found("AppImage/manual", False)
        else:
            if menu is None:
                menu = _desktop_names()
            n = a.name.lower()
            if any(m == n or m.startswith(n + " ") for m in menu):
                found[a.name] = Found("AppImage/manual", False)
    return found


def _win_programs() -> list[str]:
    """Nomes em "Adicionar/remover programas" (registo: máquina 64/32 bits e utilizador)."""
    import winreg
    names = []
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in keys:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DisplayName")[0]).strip()
                        try:
                            if int(winreg.QueryValueEx(k, "SystemComponent")[0]) == 1 and "Redistributable" not in name:
                                continue
                        except (OSError, ValueError):
                            pass
                        if name:
                            names.append(name)
                except OSError:
                    continue
    return names


def _win_detect(apps: list[App]) -> dict[str, Found]:
    found: dict[str, Found] = {}
    if which("winget"):   # IDs do winget (inclui apps da Microsoft Store)
        _c, out = run(["winget", "list", *_WG], timeout=120)
        low = out.lower()
        for a in apps:
            if a.winget and re.search(r"(?<![\w.])" + re.escape(a.winget.lower()) + r"(?![\w.])", low):
                found[a.name] = Found("winget", True)
    try:
        progs = _win_programs()
    except Exception:  # noqa: BLE001
        progs = []
    for a in apps:
        if a.name in found:
            continue
        pat = WIN_NAMES.get(a.name, r"(?<![\w])" + re.escape(a.name) + r"(?![\w])")
        if pat and any(re.search(pat, p, re.I) for p in progs):
            found[a.name] = Found("Windows", bool(a.winget and which("winget")))
    if "LibreHardwareMonitor" not in found:
        try:
            from . import lhm
            if lhm.installed():
                found["LibreHardwareMonitor"] = Found("Nexo", False)
        except Exception:  # noqa: BLE001
            pass
    return found


def detect_installed() -> dict[str, Found]:
    """{nome da app: de onde vem}. Vê todas as formas de instalação, não só o gestor desta página."""
    apps = available_apps()
    if IS_WIN:
        return _win_detect(apps)
    if IS_LINUX:
        return _linux_detect(apps)
    return {}


def installed_ids() -> set[str]:
    """IDs (winget/Flatpak) das apps do catálogo instaladas, seja de que forma for."""
    found = detect_installed()
    return {a.pkg_id for a in available_apps() if a.name in found}


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
