"""Programas que arrancam com o sistema (ativar / desativar, reversível)."""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from .util import IS_LINUX, IS_WIN, is_admin, run


@dataclass
class StartupItem:
    name: str
    command: str
    source: str        # descrição da origem (ex.: "HKCU Run", "~/.config/autostart")
    enabled: bool
    kind: str          # win_reg | win_folder | xdg | systemd
    ref: dict          # dados para alterar o estado
    essential: bool = False  # necessário para o ambiente gráfico (não deixar desativar)


# =========================================================================== Linux
# componentes da sessão gráfica: desativá-los parte o ambiente de trabalho
_ESSENTIAL = ("plasmashell", "plasma-", "polkit", "pam_kwallet", "ksmserver", "kwin", "xembedsniproxy",
              "gmenudbusmenuproxy", "powerdevil", "gnome-shell", "gsd-", "gnome-keyring", "xdg-user-dirs",
              "at-spi", "kaccess", "pipewire", "wireplumber", "xdg-desktop-portal", "lxpolkit", "xfce4-",
              "xfsettingsd", "cinnamon-", "mate-settings", "nm-applet", "spice-vdagent", "geoclue",
              "ctfmon", "securityhealth", "rtkaudio", "igfx")


def _is_essential(cmd: str) -> bool:
    low = cmd.lower()
    return any(k in low for k in _ESSENTIAL)


def _xdg_dirs():
    user = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    system = [Path(p) / "autostart" for p in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")]
    return user, system


def _read_desktop(path: Path) -> dict:
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
        return dict(cp["Desktop Entry"]) if cp.has_section("Desktop Entry") else {}
    except Exception:
        return {}


_CORE_UNITS = ("pipewire", "wireplumber", "xdg-", "dbus", "plasma-", "gnome-", "org.gnome", "systemd-",
               "p11-kit", "gcr-", "obex", "at-spi", "pulseaudio", "filter-chain", "gvfs", "evolution",
               "kde-", "mpris-proxy", "app-", "ssh-agent", "gpg-agent", "dirmngr")


def _linux_items() -> list[StartupItem]:
    user_dir, sys_dirs = _xdg_dirs()
    found: dict[str, StartupItem] = {}
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":")
    for d, is_user in [(p, False) for p in sys_dirs] + [(user_dir, True)]:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            e = _read_desktop(f)
            if not e:
                continue
            only = [x for x in e.get("OnlyShowIn", "").split(";") if x]
            notin = [x for x in e.get("NotShowIn", "").split(";") if x]
            if (only and not set(only) & set(desktop)) or (notin and set(notin) & set(desktop)):
                found.pop(f.name, None)
                continue
            enabled = (e.get("Hidden", "false").lower() != "true"
                       and e.get("X-GNOME-Autostart-enabled", "true").lower() != "false")
            found[f.name] = StartupItem(
                e.get("Name", f.stem), e.get("Exec", ""),
                "~/.config/autostart" if is_user else str(d), enabled, "xdg",
                {"file": f.name, "path": str(f)},
                essential=not is_user and _is_essential(e.get("Exec", "") + " " + f.name))
    items = list(found.values())
    code, out = run(["systemctl", "--user", "list-unit-files", "--type=service", "--state=enabled,disabled",
                     "--no-legend", "--no-pager"], timeout=10)
    if code == 0:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 2 or "@" in parts[0]:
                continue
            unit, state = parts[0], parts[1]
            user_made = any((Path.home() / d / unit).exists()
                            for d in (".config/systemd/user", ".local/share/systemd/user"))
            # os serviços base da sessão (som, portais, dbus...) ficam de fora para não partir nada
            if not user_made and (state != "enabled" or unit.startswith(_CORE_UNITS)):
                continue
            items.append(StartupItem(unit.removesuffix(".service"), unit, "systemd --user",
                                     state == "enabled", "systemd", {"unit": unit}))
    return items


def _linux_set(item: StartupItem, enabled: bool) -> tuple[bool, str]:
    if item.kind == "systemd":
        code, out = run(["systemctl", "--user", "enable" if enabled else "disable", item.ref["unit"]], timeout=15)
        return code == 0, out or "Feito"
    user_dir, _ = _xdg_dirs()
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / item.ref["file"]
    src = Path(item.ref["path"])
    lines = (target if target.exists() else src).read_text(encoding="utf-8", errors="replace").splitlines()
    out, in_entry, done = [], False, False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if in_entry and not done:
                out.append(f"Hidden={'false' if enabled else 'true'}")
                done = True
            in_entry = s == "[Desktop Entry]"
        if in_entry and (s.startswith("Hidden=") or s.startswith("X-GNOME-Autostart-enabled=")):
            continue
        out.append(line)
    if not done:
        out.append(f"Hidden={'false' if enabled else 'true'}")
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True, "Feito (aplica no próximo início de sessão)"


# =========================================================================== Windows
_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


def _win_items() -> list[StartupItem]:
    import winreg
    items: list[StartupItem] = []
    hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}

    def approved(hive, sub, name) -> bool:
        try:
            with winreg.OpenKey(hives[hive], f"{_APPROVED}\\{sub}") as k:
                data = winreg.QueryValueEx(k, name)[0]
                return not (isinstance(data, bytes) and data and data[0] % 2 == 1)  # 03 = desativado
        except OSError:
            return True

    for hive in ("HKCU", "HKLM"):
        for path, sub in ((_RUN, "Run"), (_RUN32, "Run32")):
            try:
                k = winreg.OpenKey(hives[hive], path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                items.append(StartupItem(name, str(value), f"{hive} {sub}", approved(hive, sub, name),
                                         "win_reg", {"hive": hive, "sub": sub, "name": name}))
            winreg.CloseKey(k)
    folders = [(Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup", "HKCU"),
               (Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup", "HKLM")]
    for folder, hive in folders:
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if f.name.lower() == "desktop.ini":
                continue
            items.append(StartupItem(f.stem, str(f), "Pasta Arranque" + (" (todos)" if hive == "HKLM" else ""),
                                     approved(hive, "StartupFolder", f.name), "win_folder",
                                     {"hive": hive, "sub": "StartupFolder", "name": f.name}))
    return items


def _win_set(item: StartupItem, enabled: bool) -> tuple[bool, str]:
    import winreg
    hive = item.ref["hive"]
    if hive == "HKLM" and not is_admin():
        return False, "Precisa de executar como administrador para itens de todos os utilizadores."
    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    # mesmo formato do Gestor de Tarefas: 12 bytes, 1.º byte 02 = ativo, 03 = desativado
    data = bytes([2 if enabled else 3]) + bytes(11)
    try:
        with winreg.CreateKeyEx(root, f"{_APPROVED}\\{item.ref['sub']}", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, item.ref["name"], 0, winreg.REG_BINARY, data)
        return True, "Feito"
    except OSError as e:
        return False, str(e)


# =========================================================================== API
def list_items() -> list[StartupItem]:
    items = _win_items() if IS_WIN else _linux_items() if IS_LINUX else []
    # apps do utilizador primeiro, componentes essenciais no fim
    return sorted(items, key=lambda i: (i.essential, i.kind == "systemd", i.name.lower()))


def set_enabled(item: StartupItem, enabled: bool) -> tuple[bool, str]:
    if IS_WIN:
        return _win_set(item, enabled)
    return _linux_set(item, enabled)




# ---------------------------------------------------------------- arranque do próprio Nexo
_SELF_NAME = "Nexo"


def _self_command() -> str:
    import sys
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    root = Path(__file__).resolve().parents[2]
    return f'"{sys.executable}" "{root / "run_nexo.py"}" --minimized'


def self_autostart_enabled() -> bool:
    if IS_WIN:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, _SELF_NAME)
            return True
        except OSError:
            return False
    return (_xdg_dirs()[0] / "nexo.desktop").exists()


def _remove_legacy_autostart() -> None:
    """Remove a entrada de arranque do nome antigo (PCForge)."""
    try:
        if IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "PCForge")
        else:
            (_xdg_dirs()[0] / "pcforge.desktop").unlink()
    except OSError:
        pass


def set_self_autostart(on: bool) -> tuple[bool, str]:
    _remove_legacy_autostart()
    try:
        if IS_WIN:
            import winreg
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                                    0, winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, _SELF_NAME, 0, winreg.REG_SZ, _self_command())
                else:
                    try:
                        winreg.DeleteValue(k, _SELF_NAME)
                    except FileNotFoundError:
                        pass
        else:
            f = _xdg_dirs()[0] / "nexo.desktop"
            if on:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("[Desktop Entry]\nType=Application\nName=Nexo\n"
                             f"Exec={_self_command()}\nIcon=nexo\nTerminal=false\n"
                             "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
            elif f.exists():
                f.unlink()
        return True, "O Nexo abre com o sistema (minimizado)" if on else "O Nexo já não abre com o sistema"
    except OSError as e:
        return False, str(e)
