"""Libertar memória e fechar programas em segundo plano."""
from __future__ import annotations

import os
import time

import psutil

from .util import IS_LINUX, IS_WIN, human_bytes, is_admin, run_root

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


def clean_memory() -> tuple[bool, str]:
    before = psutil.virtual_memory().available
    if IS_WIN:
        msgs = []
        n = _win_empty_working_sets()
        msgs.append(f"Memória de {n} processos compactada")
        if is_admin():
            ok = _win_purge_standby()
            msgs.append("lista em espera limpa" if ok else "não foi possível limpar a lista em espera")
        else:
            msgs.append("lista em espera: precisa de administrador")
        time.sleep(0.5)
        freed = psutil.virtual_memory().available - before
        return True, f"{'; '.join(msgs)}. Libertado: {human_bytes(max(0, freed))}"
    if IS_LINUX:
        code, out = run_root("sync && echo 3 > /proc/sys/vm/drop_caches && "
                              "{ [ -w /proc/sys/vm/compact_memory ] && echo 1 > /proc/sys/vm/compact_memory; true; }")
        if code != 0:
            return False, out or "Cancelado"
        time.sleep(0.5)
        freed = psutil.virtual_memory().available - before
        return True, f"Cache de páginas e inodes libertada. Disponível agora: " \
                     f"{human_bytes(psutil.virtual_memory().available)} (+{human_bytes(max(0, freed))})"
    return False, "Sistema não suportado"


def _win_empty_working_sets() -> int:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    PROCESS_SET_QUOTA, PROCESS_QUERY_INFORMATION = 0x0100, 0x0400
    n = 0
    for p in psutil.process_iter(["pid"]):
        h = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, p.info["pid"])
        if h:
            if psapi.EmptyWorkingSet(h):
                n += 1
            k32.CloseHandle(h)
    return n


def _win_purge_standby() -> bool:
    """Limpa a lista de memória em espera (como o ISLC). Requer administrador."""
    import ctypes
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)):
        return False
    luid = LUID()
    if not adv.LookupPrivilegeValueW(None, "SeProfileSingleProcessPrivilege", ctypes.byref(luid)):
        return False
    tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, 0x2)))
    adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
    k32.CloseHandle(token)
    SystemMemoryListInformation, MemoryPurgeStandbyList = 80, 4
    cmd = ctypes.c_int(MemoryPurgeStandbyList)
    status = ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(cmd), ctypes.sizeof(cmd))
    return status == 0


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
