"""Lista de processos (estilo Gestor de Tarefas) e ações sobre eles."""
from __future__ import annotations

import os

import psutil

from .util import IS_WIN, open_path

_NCPU = psutil.cpu_count() or 1
_ATTRS = ["pid", "name", "username", "cpu_percent", "memory_info", "num_threads", "status", "exe"]

PRIORITIES = ["Baixa", "Abaixo do normal", "Normal", "Acima do normal", "Alta"]
if IS_WIN:
    _PRIO_VALUES = [psutil.IDLE_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS, psutil.NORMAL_PRIORITY_CLASS,
                    psutil.ABOVE_NORMAL_PRIORITY_CLASS, psutil.HIGH_PRIORITY_CLASS]
else:
    _PRIO_VALUES = [19, 10, 0, -5, -10]


def snapshot(only_user: bool = False) -> list[dict]:
    """Uma linha por processo. A %CPU é relativa ao CPU inteiro (como no Gestor de Tarefas).

    O psutil guarda os objetos Process entre chamadas de process_iter, por isso a %CPU é
    calculada desde a chamada anterior (a primeira chamada devolve 0 para todos)."""
    me = os.getpid()
    try:
        user = psutil.Process(me).username() if only_user else None
    except Exception:
        user = None
    out = []
    for p in psutil.process_iter(_ATTRS):
        i = p.info
        if i["pid"] == 0:
            continue
        if user and i.get("username") != user:
            continue
        mem = i.get("memory_info")
        uname = i.get("username") or ""
        out.append({
            "pid": i["pid"],
            "name": i.get("name") or "?",
            "cpu": (i.get("cpu_percent") or 0.0) / _NCPU,
            "rss": mem.rss if mem else 0,
            "threads": i.get("num_threads") or 0,
            "user": uname.split("\\")[-1],
            "status": i.get("status") or "",
            "exe": i.get("exe") or "",
            "self": i["pid"] == me,
        })
    return out


def end(pids: list[int], force: bool = False) -> tuple[int, list[str]]:
    """Termina processos. Devolve (quantos terminaram, erros)."""
    procs, errors = [], []
    for pid in pids:
        try:
            p = psutil.Process(pid)
            (p.kill if force else p.terminate)()
            procs.append(p)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            errors.append(f"PID {pid}: acesso negado (precisa de {'administrador' if IS_WIN else 'root'})")
    if not force and procs:
        _gone, alive = psutil.wait_procs(procs, timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
    return len(procs), errors


def set_priority(pid: int, level: int) -> tuple[bool, str]:
    try:
        psutil.Process(pid).nice(_PRIO_VALUES[level])
        return True, f"Prioridade alterada para {PRIORITIES[level]}"
    except psutil.AccessDenied:
        return False, "Acesso negado — aumentar a prioridade precisa de " + ("administrador" if IS_WIN else "root")
    except psutil.NoSuchProcess:
        return False, "O processo já terminou"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def open_location(exe: str) -> bool:
    if not exe or not os.path.exists(exe):
        return False
    open_path(os.path.dirname(exe))
    return True


# ---------------------------------------------------------------------------------------------- vista simples
# processos do sistema / ambiente gráfico: escondidos na vista simples e nunca fechados por ela
_SYSTEM = {
    # Linux
    "systemd", "kwin_wayland", "kwin_x11", "kwin_wayland_wrapper", "plasmashell", "xwayland", "xorg", "ksmserver",
    "kded6", "kded5", "kglobalacceld", "kactivitymanagerd", "dbus-daemon", "dbus-broker", "dbus-broker-launch",
    "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio", "gnome-shell", "gnome-session-binary", "mutter",
    "kwalletd6", "kwalletd5", "ksecretd", "org_kde_powerdevil", "powerdevil", "kaccess", "xembedsniproxy",
    "gmenudbusmenuproxy", "dconf-service", "ssh-agent", "gpg-agent", "agetty", "login", "sddm", "sddm-helper",
    "bash", "zsh", "fish", "sh", "dash", "sudo", "kdeconnectd", "obexd", "krunner", "ibus-daemon", "fcitx5",
    "at-spi-bus-launcher", "at-spi2-registryd", "polkit-kde-authentication-agent-1", "xdg-permission-store",
    "xdg-document-portal", "xdg-desktop-portal", "xdg-desktop-portal-kde", "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-gnome", "baloo_file", "baloo_file_extractor", "drkonqi-coredump-launcher", "kscreen_backend_launcher",
    "kdeconnect-indicator", "plasma-browser-integration-host", "evolution-source-registry", "evolution-alarm-notify",
    "tracker-miner-fs-3", "gvfsd", "gvfsd-fuse", "gvfsd-metadata", "gvfs-udisks2-volume-monitor", "systemd-inhibit",
    "bwrap", "xdg-dbus-proxy", "portal", "kio-worker", "kiod6", "kiod5", "ksystemstats", "kactivitymanagerd",
    "geoclue", "mission-control-5", "kf6.kio.core.kioworker", "wl-paste", "wl-copy", "ksplashqml",
    # Windows
    "explorer", "dwm", "csrss", "winlogon", "wininit", "services", "lsass", "svchost", "smss", "fontdrvhost",
    "sihost", "taskhostw", "ctfmon", "runtimebroker", "searchhost", "searchindexer", "searchapp",
    "startmenuexperiencehost", "shellexperiencehost", "textinputhost", "applicationframehost",
    "systemsettingsbroker", "conhost", "dllhost", "audiodg", "spoolsv", "securityhealthsystray",
    "securityhealthservice", "msmpeng", "nissrv", "widgets", "widgetservice", "phoneexperiencehost", "lockapp",
    "useroobebroker", "crossdeviceresume", "backgroundtaskhost", "smartscreen", "wmiprvse", "sgrmbroker",
    "memory compression", "registry", "system", "secure system", "msedgewebview2", "gamebar", "gamebarftserver",
    "nvcontainer", "nvdisplay.container", "igfxem", "rtkauduservice64", "cmd", "powershell", "openconsole",
    "windowsterminal", "sppsvc", "dashost", "wudfhost", "searchprotocolhost", "searchfilterhost", "rundll32",
}
_SYSTEM_PREFIX = ("xdg-", "gsd-", "at-spi", "kscreen", "plasma-", "org.kde.", "drkonqi", "kwin", "gvfs",
                  "evolution-", "ibus-", "systemd-", "pipewire", "dbus-", "flatpak-", "srt-", "pv-", "(sd-",
                  "fusermount", "startplasma", "kio", "baloo", "x86_64-linux-gnu-", "xsettingsd", "notify-send",
                  "journalctl", "nexo")
# aplicações pequenas e paradas não aparecem na lista (só contam em "segundo plano")
MIN_RSS, MIN_CPU = 40 * 1024**2, 1.0
_ALIAS = {"steamwebhelper": "steam", "code-oss": "code", "chrome_crashpad_handler": "", "crashpad_handler": "",
          "firefox-bin": "firefox", "msedge": "msedge", "discord": "discord", "vesktop": "vesktop",
          "zen-bin": "zen", "thunderbird-bin": "thunderbird", "steam.exe": "steam"}
_NAMES = {"firefox": "Firefox", "chrome": "Google Chrome", "google-chrome": "Google Chrome", "chromium": "Chromium",
          "brave": "Brave", "msedge": "Microsoft Edge", "opera": "Opera", "vivaldi-bin": "Vivaldi", "zen": "Zen",
          "code": "Visual Studio Code", "codium": "VSCodium", "zed": "Zed", "zed-editor": "Zed", "discord": "Discord",
          "vesktop": "Discord (Vesktop)", "steam": "Steam", "spotify": "Spotify", "telegram-desktop": "Telegram",
          "telegram": "Telegram", "whatsapp": "WhatsApp", "obs": "OBS Studio", "obs64": "OBS Studio",
          "vlc": "VLC", "mpv": "mpv", "gimp": "GIMP", "krita": "Krita", "blender": "Blender",
          "libreoffice": "LibreOffice", "soffice.bin": "LibreOffice", "thunderbird": "Thunderbird",
          "dolphin": "Dolphin (ficheiros)", "konsole": "Konsole (terminal)", "kate": "Kate",
          "nautilus": "Ficheiros", "gnome-terminal-server": "Terminal", "nexo": "Nexo",
          "teams-for-linux": "Microsoft Teams", "ms-teams": "Microsoft Teams", "slack": "Slack", "lutris": "Lutris",
          "heroic": "Heroic", "epicgameslauncher": "Epic Games", "battle.net": "Battle.net", "notepad": "Bloco de Notas",
          "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "outlook": "Outlook", "olk": "Outlook",
          "systemsettings": "Definições", "taskmgr": "Gestor de Tarefas", "spectacle": "Spectacle",
          "prismlauncher": "Prism Launcher (Minecraft)", "javaw": "Java", "java": "Java", "claude": "Claude",
          "node": "Node.js", "python": "Python", "python3": "Python", "coolercontrold": "CoolerControl",
          "coolercontrol": "CoolerControl", "packettracer": "Cisco Packet Tracer", "opencode": "opencode"}


def _key(r: dict) -> str:
    base = os.path.basename(r["exe"]) if r["exe"] else r["name"]
    k = base.lower()
    if k.endswith(".exe"):
        k = k[:-4]
    return _ALIAS.get(k, k)


def is_system(key: str) -> bool:
    return key in _SYSTEM or key.startswith(_SYSTEM_PREFIX)


def friendly(key: str) -> str:
    if key in _NAMES:
        return _NAMES[key]
    n = key.replace("_", " ").replace("-", " ").strip()
    return n[:1].upper() + n[1:] if n else "?"


def group_apps(rows: list[dict]) -> tuple[list[dict], dict]:
    """Junta os processos por aplicação. Devolve (aplicações, resumo do que ficou escondido)."""
    apps: dict[str, dict] = {}
    hidden = {"count": 0, "cpu": 0.0, "rss": 0}
    for r in rows:
        k = _key(r)
        if not k or r["self"] or is_system(k):
            hidden["count"] += 1
            hidden["cpu"] += r["cpu"]
            hidden["rss"] += r["rss"]
            continue
        a = apps.get(k)
        if a is None:
            a = apps[k] = {"key": k, "name": friendly(k), "pids": [], "cpu": 0.0, "rss": 0, "exe": r["exe"]}
        a["pids"].append(r["pid"])
        a["cpu"] += r["cpu"]
        a["rss"] += r["rss"]
        if not a["exe"]:
            a["exe"] = r["exe"]
    shown = []
    for a in apps.values():
        if a["rss"] >= MIN_RSS or a["cpu"] >= MIN_CPU:
            shown.append(a)
        else:
            hidden["count"] += len(a["pids"])
            hidden["cpu"] += a["cpu"]
            hidden["rss"] += a["rss"]
    return shown, hidden
