"""Programas em segundo plano: os que mais gastam RAM e quais é seguro fechar.

(A antiga "Libertar memória" foi retirada: largar a cache de páginas no Linux ou esvaziar os
working sets no Windows só faz parecer que há RAM livre; o sistema volta a ler tudo do disco
e fica mais lento logo a seguir.)"""
from __future__ import annotations

import os

import psutil

from .util import IS_WIN

# Programas que é seguro fechar para libertar recursos (pré-marcados)
SAFE_TO_CLOSE_WIN = {
    "onedrive.exe", "teams.exe", "ms-teams.exe", "widgets.exe", "widgetservice.exe", "adobearm.exe",
    "creative cloud.exe", "adobe desktop service.exe", "acrotray.exe", "skype.exe", "yourphone.exe",
    "phoneexperiencehost.exe", "cortana.exe", "searchapp.exe", "gamebar.exe", "spotify.exe",
    "epicgameslauncher.exe", "eadesktop.exe", "origin.exe", "ubisoftconnect.exe", "upc.exe",
    "msedge.exe",
}
SAFE_TO_CLOSE_LINUX = {
    "tracker-miner-fs-3", "tracker-extract-3", "baloo_file", "baloo_file_extractor", "evolution-alarm-notify",
    "evolution-source-registry", "evolution-calendar-factory", "evolution-addressbook-factory",
    "geoclue", "gnome-software", "discover", "packagekitd", "spotify", "akonadi_control",
}
# Nunca mostrar (sistema / sessão gráfica)
_PROTECTED = {
    "systemd", "init", "kthreadd", "Xorg", "Xwayland", "gnome-shell", "kwin_wayland", "kwin_x11", "plasmashell",
    "pipewire", "wireplumber", "pulseaudio", "dbus-daemon", "dbus-broker", "sddm", "gdm", "lightdm", "sway", "Hyprland",
    "explorer.exe", "csrss.exe", "winlogon.exe", "wininit.exe", "services.exe", "lsass.exe", "svchost.exe",
    "dwm.exe", "smss.exe", "system", "registry", "memcompression", "fontdrvhost.exe", "sihost.exe",
    "ctfmon.exe", "audiodg.exe", "msmpeng.exe", "securityhealthservice.exe", "taskhostw.exe",
}


def background_processes(limit: int = 40) -> list[dict]:
    """Processos do utilizador que mais gastam RAM (sem os do sistema)."""
    me = os.getpid()
    try:
        user = psutil.Process(me).username()
    except Exception:
        user = None
    safe = SAFE_TO_CLOSE_WIN if IS_WIN else SAFE_TO_CLOSE_LINUX
    procs: dict[str, dict] = {}
    for p in psutil.process_iter(["pid", "name", "username", "memory_info", "ppid"]):
        info = p.info
        name = info.get("name") or ""
        if (info["pid"] in (me, 0, 4) or not info.get("memory_info") or name.lower() in _PROTECTED
                or name in _PROTECTED or (user and info.get("username") != user)):
            continue
        if info.get("ppid") == me:
            continue
        # agrupa por nome (ex.: os 30 processos do Chrome)
        g = procs.setdefault(name.lower(), {"name": name, "pids": [], "rss": 0,
                                            "suggest": name.lower() in safe})
        g["pids"].append(info["pid"])
        g["rss"] += info["memory_info"].rss
    return sorted(procs.values(), key=lambda g: -g["rss"])[:limit]


def terminate(pids: list[int]) -> int:
    """Pede aos processos para fecharem (sem forçar); força só os que não responderem em 3 s."""
    procs = []
    for pid in pids:
        try:
            p = psutil.Process(pid)
            p.terminate()
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    return len(procs)
