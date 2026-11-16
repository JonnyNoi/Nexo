"""Todos os programas instalados (não só os do catálogo da página Instalar aplicações) — com tamanho,
origem e desinstalação.

Windows: o mesmo que "Adicionar/remover programas" (registo Uninstall, máquina 64/32 bits e utilizador);
desinstalar abre o desinstalador do próprio programa (ou msiexec /x para pacotes MSI).
Linux: aplicações Flatpak e Snap e pacotes instalados de propósito (pacman -Qe, apt-mark showmanual, dnf
userinstalled); os que têm entrada no menu de aplicações aparecem como "aplicação". Pacotes essenciais do
sistema ficam protegidos (não se deixam remover pelo Nexo)."""
from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass

from .util import IS_LINUX, IS_WIN, run, run_root, which

# pacotes que nunca se removem pelo Nexo (prefixos/nomes exatos) — sem eles o sistema não arranca ou fica sem
# interface, rede ou gestor de pacotes
_PROTECTED_EXACT = {
    "base", "base-devel", "filesystem", "glibc", "bash", "coreutils", "systemd", "systemd-sysvcompat", "sudo",
    "pacman", "apt", "dpkg", "dnf", "rpm", "zypper", "grub", "efibootmgr", "systemd-boot", "limine", "refind",
    "mkinitcpio", "dracut", "initramfs-tools", "networkmanager", "network-manager", "polkit", "dbus", "util-linux",
    "shadow", "pam", "linux-firmware", "mesa", "xorg-server", "xwayland", "wayland", "pipewire", "wireplumber",
    "plasma-desktop", "plasma-workspace", "kwin", "gnome-shell", "mutter", "gdm", "sddm", "lightdm", "cinnamon",
    "xfce4-session", "xfwm4", "mate-session-manager", "lxqt-session", "hyprland", "sway", "flatpak", "snapd",
    "ubuntu-desktop", "ubuntu-minimal", "ubuntu-standard", "fedora-release", "cachyos-settings", "python",
    "perl", "openssl", "ca-certificates", "nvidia", "nvidia-dkms", "nvidia-open", "nvidia-open-dkms",
}
_PROTECTED_PREFIX = ("linux", "nvidia-utils", "lib32-nvidia", "amd-ucode", "intel-ucode", "grub-", "systemd-",
                     "xf86-video", "vulkan-", "mesa-", "lib32-mesa", "plasma-", "kde-", "gnome-session", "cachyos-keyring",
                     "cachyos-hooks", "cachyos-v3-", "cachyos-v4-", "cachyos-mirrorlist", "archlinux-keyring")


@dataclass
class Program:
    name: str
    version: str = ""
    publisher: str = ""
    size: int = 0                 # bytes (0 = desconhecido)
    installed: float = 0.0        # epoch (0 = desconhecida)
    source: str = ""              # Windows | Flatpak | Snap | pacman | apt | dnf
    ident: str = ""               # chave para desinstalar (pacote, id do flatpak, comando no Windows)
    is_app: bool = True           # tem entrada no menu (Linux) / não é componente (Windows)
    protected: bool = False
    description: str = ""


def is_protected(pkg: str) -> bool:
    p = pkg.lower()
    return p in _PROTECTED_EXACT or p.startswith(_PROTECTED_PREFIX)


# ------------------------------------------------------------------------------------------------ Windows
def _win_programs() -> list[Program]:
    import winreg
    out: dict[str, Program] = {}
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]

    def val(k, name, default=None):
        try:
            return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return default

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
                        name = str(val(k, "DisplayName", "") or "").strip()
                        if not name or val(k, "ParentKeyName") or str(val(k, "ReleaseType", "")) in ("Update",
                                                                                                  "Hotfix",
                                                                                                  "Security Update"):
                            continue
                        component = str(val(k, "SystemComponent", 0)) == "1"
                        cmd = str(val(k, "QuietUninstallString", "") or val(k, "UninstallString", "") or "")
                        if str(val(k, "WindowsInstaller", 0)) == "1" and re.fullmatch(r"\{[0-9A-Fa-f-]{36}\}", sub):
                            cmd = f"msiexec.exe /x {sub}"
                        if not cmd:
                            continue
                        when = 0.0
                        d = str(val(k, "InstallDate", "") or "")
                        if re.fullmatch(r"\d{8}", d):
                            try:
                                when = time.mktime(time.strptime(d, "%Y%m%d"))
                            except (ValueError, OverflowError):
                                pass
                        try:
                            size = int(val(k, "EstimatedSize", 0) or 0) * 1024
                        except (TypeError, ValueError):
                            size = 0
                        p = Program(name, str(val(k, "DisplayVersion", "") or ""), str(val(k, "Publisher", "") or ""),
                                    size, when, "Windows", cmd, not component)
                        prev = out.get(name.lower())
                        if prev is None or (not prev.size and size):
                            out[name.lower()] = p
                except OSError:
                    continue
    return list(out.values())


# ------------------------------------------------------------------------------------------------ Linux
def _parse_size(s: str) -> int:
    m = re.match(r"\s*([\d.,]+)\s*([KMGT]?i?B)", s)
    if not m:
        return 0
    n = float(m.group(1).replace(",", "."))
    mult = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4,
            "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4}.get(m.group(2), 1)
    return int(n * mult)


_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                       "Dec"), 1)}


def _pacman_date(s: str) -> float:
    """'Thu Oct  1 18:44:13 2026' (LC_ALL=C). Sem strptime: dentro do Qt o locale é o do sistema e %b falharia."""
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(\d{4})", s)
    if not m or m.group(1) not in _MONTHS:
        return 0.0
    mon, day, hh, mm, ss, year = _MONTHS[m.group(1)], *map(int, m.groups()[1:])
    try:
        return time.mktime((year, mon, day, hh, mm, ss, 0, 0, -1))
    except (OverflowError, ValueError):
        return 0.0


def parse_pacman_qi(text: str) -> list[Program]:
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        f = dict(re.findall(r"^([A-Za-z ]+?)\s*:\s*(.*)$", block, re.M))
        name = f.get("Name", "").strip()
        if not name:
            continue
        when = _pacman_date(f.get("Install Date", ""))
        out.append(Program(name, f.get("Version", "").strip(), f.get("Packager", "").split("<")[0].strip(),
                           _parse_size(f.get("Installed Size", "")), when, "pacman", name, False, is_protected(name),
                           f.get("Description", "").strip()))
    return out


def _pacman() -> list[Program]:
    code, out = run(["env", "LC_ALL=C", "pacman", "-Qei"], timeout=60)
    return parse_pacman_qi(out) if code == 0 else []


def _apt() -> list[Program]:
    code, manual = run(["apt-mark", "showmanual"], timeout=60)
    if code != 0:
        return []
    want = {ln.strip() for ln in manual.splitlines() if ln.strip()}
    code, out = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Installed-Size}\t${Maintainer}\t"
                     "${binary:Summary}\n"], timeout=60)
    res = []
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) < 5 or parts[0] not in want:
            continue
        size = int(parts[2]) * 1024 if parts[2].isdigit() else 0
        res.append(Program(parts[0], parts[1], parts[3].split("<")[0].strip(), size, 0.0, "apt", parts[0], False,
                           is_protected(parts[0]), parts[4]))
    return res


def _dnf() -> list[Program]:
    code, out = run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{SIZE}\t%{VENDOR}\t%{INSTALLTIME}\t"
                     "%{SUMMARY}\n"], timeout=60)
    if code != 0:
        return []
    want = None
    if which("dnf"):
        c2, user = run(["dnf", "repoquery", "--userinstalled", "--qf", "%{name}\n", "-q"], timeout=120)
        if c2 == 0 and user.strip():
            want = {ln.strip() for ln in user.splitlines() if ln.strip()}
    res = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) < 6 or (want is not None and p[0] not in want):
            continue
        res.append(Program(p[0], p[1], p[3], int(p[2]) if p[2].isdigit() else 0,
                           float(p[4]) if p[4].isdigit() else 0.0, "dnf", p[0], False, is_protected(p[0]), p[5]))
    return res


def _flatpak() -> list[Program]:
    if not which("flatpak"):
        return []
    code, out = run(["flatpak", "list", "--app", "--columns=application,name,version,size,origin,installation"],
                    timeout=60)
    res = []
    for ln in out.splitlines() if code == 0 else []:
        p = ln.split("\t")
        if len(p) < 4 or "." not in p[0]:
            continue
        res.append(Program(p[1] or p[0], p[2], p[4] if len(p) > 4 else "", _parse_size(p[3]), 0.0, "Flatpak", p[0],
                           True, False, p[0]))
    return res


def _snap() -> list[Program]:
    if not which("snap"):
        return []
    code, out = run(["snap", "list"], timeout=30)
    res = []
    for ln in out.splitlines()[1:] if code == 0 else []:
        p = ln.split()
        if len(p) < 5 or p[0] in ("core", "core18", "core20", "core22", "core24", "snapd", "bare") \
                or p[0].startswith(("gnome-", "gtk-common", "kde-frameworks", "mesa-")):
            continue
        res.append(Program(p[0], p[1], p[4] if len(p) > 4 else "", 0, 0.0, "Snap", p[0], True, False))
    return res


def _desktop_owners(source: str) -> set[str]:
    """Pacotes que têm entrada no menu de aplicações (uma única chamada ao gestor de pacotes)."""
    files = [f for f in glob.glob("/usr/share/applications/*.desktop") if os.path.isfile(f)]
    if not files:
        return set()
    if source == "pacman":
        _, out = run(["env", "LC_ALL=C", "pacman", "-Qoq", *files], timeout=60)
        return {ln.strip() for ln in out.splitlines() if ln.strip() and " " not in ln.strip()}
    if source == "apt":
        _, out = run(["dpkg", "-S", *files], timeout=60)
        return {ln.split(":")[0].strip() for ln in out.splitlines() if ":" in ln}
    if source == "dnf":
        _, out = run(["rpm", "-qf", "--qf", "%{NAME}\n", *files], timeout=60)
        return {ln.strip() for ln in out.splitlines() if ln.strip() and " " not in ln.strip()}
    return set()


def list_programs() -> list[Program]:
    if IS_WIN:
        progs = _win_programs()
    elif IS_LINUX:
        progs = []
        for tool, fn, src in (("pacman", _pacman, "pacman"), ("apt-mark", _apt, "apt"), ("rpm", _dnf, "dnf")):
            if which(tool):
                native = fn()
                owners = _desktop_owners(src)
                for p in native:
                    p.is_app = p.name in owners
                progs += native
                break
        progs += _flatpak() + _snap()
    else:
        progs = []
    progs.sort(key=lambda p: p.name.lower())
    return progs


def uninstall(p: Program) -> tuple[bool, str]:
    if p.protected:
        return False, f"«{p.name}» é um componente essencial do sistema — o Nexo não o remove."
    if p.source == "Windows":
        # abre o desinstalador do próprio programa (o utilizador segue os passos dele)
        code, out = run(p.ident, timeout=3600, shell=True)
        ok = code in (0, 3010, 1641)   # 3010/1641 = MSI pede reinício
        return ok, "Desinstalado." + (" Reinicie o PC para terminar." if code in (3010, 1641) else "") if ok else \
            (out.strip()[-300:] or f"O desinstalador terminou com o código {code}.")
    if p.source == "Flatpak":
        code, out = run(["flatpak", "uninstall", "-y", "--noninteractive", p.ident], timeout=900)
    elif p.source == "Snap":
        code, out = run_root(["snap", "remove", p.ident], timeout=900)
    elif p.source == "pacman":
        code, out = run_root(["pacman", "-Rns", "--noconfirm", p.ident], timeout=900)
    elif p.source == "apt":
        code, out = run_root(["apt-get", "remove", "-y", p.ident], timeout=900)
    elif p.source == "dnf":
        code, out = run_root(["dnf", "remove", "-y", p.ident], timeout=900)
    else:
        return False, "Origem desconhecida."
    if code == 0:
        return True, f"«{p.name}» foi desinstalado."
    tail = "\n".join(ln for ln in out.splitlines() if ln.strip())[-400:]
    if "required by" in out or "breaks dependency" in out:
        return False, f"Outros pacotes precisam de «{p.name}», por isso não foi removido.\n{tail}"
    return False, tail or f"Falhou (código {code})."
