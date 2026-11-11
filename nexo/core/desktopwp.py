"""Muda o fundo (wallpaper) do ambiente de trabalho do sistema — Windows e Linux.

Linux: KDE Plasma, GNOME/Ubuntu/Budgie, Cinnamon, MATE, XFCE, LXQt, Sway, Hyprland e,
como último recurso, swww / swaybg / feh / nitrogen.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .util import IS_WIN, config_dir, get_setting, set_setting

# modos de ajuste: chave -> (texto, Windows (WallpaperStyle, TileWallpaper), GNOME, KDE FillMode, feh)
STYLES = {
    "fill": ("Preencher", ("10", "0"), "zoom", 2, "--bg-fill"),
    "fit": ("Ajustar", ("6", "0"), "scaled", 1, "--bg-max"),
    "stretch": ("Esticar", ("2", "0"), "stretched", 0, "--bg-scale"),
    "center": ("Centrar", ("0", "0"), "centered", 6, "--bg-center"),
    "tile": ("Mosaico", ("0", "1"), "wallpaper", 3, "--bg-tile"),
    "span": ("Expandir (vários ecrãs)", ("22", "0"), "spanned", 2, "--bg-fill"),
}


def _run(cmd: list[str], timeout: float = 15) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def desktop() -> str:
    if IS_WIN:
        return "windows"
    d = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if os.environ.get("SWAYSOCK"):
        return "sway"
    for key in ("kde", "cinnamon", "mate", "xfce", "lxqt", "budgie", "gnome", "unity", "pantheon", "deepin"):
        if key in d:
            return {"unity": "gnome", "pantheon": "gnome", "budgie": "gnome"}.get(key, key)
    return d or "desconhecido"


def desktop_name() -> str:
    return {"windows": "Windows", "kde": "KDE Plasma", "gnome": "GNOME", "cinnamon": "Cinnamon", "mate": "MATE",
            "xfce": "XFCE", "lxqt": "LXQt", "sway": "Sway", "hyprland": "Hyprland",
            "deepin": "Deepin"}.get(desktop(), desktop())


# ---------------------------------------------------------------------------------------------- Windows
def _win_set(path: str, style: str) -> tuple[bool, str]:
    import ctypes
    import winreg
    ws, tile = STYLES.get(style, STYLES["fill"])[1]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, ws)
            winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, tile)
    except OSError:
        pass
    SPI_SETDESKWALLPAPER, SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 20, 1, 2
    ok = ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path,
                                                     SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    return bool(ok), "" if ok else "O Windows recusou a imagem (formato não suportado?)"


def _win_get() -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(520)
    ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0)  # SPI_GETDESKWALLPAPER
    return buf.value


def _win_lock(path: str) -> tuple[bool, str]:
    ps = ("$ErrorActionPreference='Stop';"
          "[Windows.System.UserProfile.LockScreen,Windows.System.UserProfile,ContentType=WindowsRuntime]|Out-Null;"
          "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
          "$f=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime];"
          "$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods()|?{$_.Name -eq 'AsTask' -and "
          "$_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0];"
          "function Await($op,$t){$x=$asTask.MakeGenericMethod($t).Invoke($null,@($op));$x.Wait(-1)|Out-Null;$x.Result};"
          "$file=Await ($f::GetFileFromPathAsync($env:NEXO_WP)) ($f);"
          "$a=([System.WindowsRuntimeSystemExtensions].GetMethods()|?{$_.Name -eq 'AsTask' -and "
          "$_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'})[0];"
          "$a.Invoke($null,@([Windows.System.UserProfile.LockScreen]::SetImageFileAsync($file))).Wait(-1)|Out-Null")
    env = dict(os.environ, NEXO_WP=path)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                           text=True, timeout=30, env=env, creationflags=0x08000000)
        return r.returncode == 0, r.stderr.strip()[-300:]
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


# ---------------------------------------------------------------------------------------------- Linux
def _kde_set(path: str, style: str) -> tuple[bool, str]:
    mode = STYLES.get(style, STYLES["fill"])[3]
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus") or shutil.which("qdbus-qt6") or shutil.which("qdbus-qt5")
    if qdbus:
        js = ("var all = desktops(); for (var i = 0; i < all.length; i++) { var d = all[i];"
              "d.wallpaperPlugin = 'org.kde.image'; d.currentConfigGroup = ['Wallpaper','org.kde.image','General'];"
              f"d.writeConfig('Image', {json.dumps('file://' + path)}); d.writeConfig('FillMode', {mode}); }}")
        ok, msg = _run([qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", js])
        if ok:
            return ok, msg
    if shutil.which("plasma-apply-wallpaperimage"):
        return _run(["plasma-apply-wallpaperimage", path])
    return False, "Não encontrei o qdbus nem o plasma-apply-wallpaperimage"


def _kde_lock(path: str) -> tuple[bool, str]:
    tool = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if not tool:
        return False, "kwriteconfig não encontrado"
    return _run([tool, "--file", "kscreenlockerrc", "--group", "Greeter", "--group", "Wallpaper", "--group",
                 "org.kde.image", "--group", "General", "--key", "Image", f"file://{path}"])


def _gsettings(schema: str, key: str, value: str) -> tuple[bool, str]:
    return _run(["gsettings", "set", schema, key, value])


def _gnome_set(path: str, style: str) -> tuple[bool, str]:
    uri = Path(path).as_uri()
    ok, msg = _gsettings("org.gnome.desktop.background", "picture-uri", uri)
    _gsettings("org.gnome.desktop.background", "picture-uri-dark", uri)
    _gsettings("org.gnome.desktop.background", "picture-options", STYLES.get(style, STYLES["fill"])[2])
    return ok, msg


def _xfce_set(path: str, style: str) -> tuple[bool, str]:
    ok, out = _run(["xfconf-query", "-c", "xfce4-desktop", "-l"])
    if not ok:
        return False, out
    style_n = {"center": "1", "tile": "2", "stretch": "3", "fit": "4", "fill": "5", "span": "5"}.get(style, "5")
    done = False
    for prop in out.splitlines():
        if prop.endswith("/last-image"):
            _run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", path])
            _run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop[:-len("last-image")] + "image-style", "-s", style_n])
            done = True
    return done, "" if done else "Não encontrei os ecrãs do XFCE (abra as definições do ambiente de trabalho 1 vez)"


def _linux_set(path: str, style: str) -> tuple[bool, str]:
    de = desktop()
    if de == "kde":
        return _kde_set(path, style)
    if de == "gnome" or de == "deepin":
        return _gnome_set(path, style)
    if de == "cinnamon":
        ok, msg = _gsettings("org.cinnamon.desktop.background", "picture-uri", Path(path).as_uri())
        _gsettings("org.cinnamon.desktop.background", "picture-options", STYLES.get(style, STYLES["fill"])[2])
        return ok, msg
    if de == "mate":
        ok, msg = _gsettings("org.mate.background", "picture-filename", path)
        _gsettings("org.mate.background", "picture-options", STYLES.get(style, STYLES["fill"])[2])
        return ok, msg
    if de == "xfce":
        return _xfce_set(path, style)
    if de == "lxqt" and shutil.which("pcmanfm-qt"):
        mode = {"fit": "fit", "stretch": "stretch", "center": "center", "tile": "tile"}.get(style, "zoom")
        return _run(["pcmanfm-qt", f"--set-wallpaper={path}", f"--wallpaper-mode={mode}"])
    if de == "hyprland":
        if shutil.which("swww"):
            return _run(["swww", "img", path, "--transition-type", "fade"])
        if shutil.which("hyprctl"):
            _run(["hyprctl", "hyprpaper", "preload", path])
            return _run(["hyprctl", "hyprpaper", "wallpaper", f",{path}"])
    if de == "sway" and shutil.which("swaymsg"):
        mode = {"fit": "fit", "stretch": "stretch", "center": "center", "tile": "tile"}.get(style, "fill")
        return _run(["swaymsg", "output", "*", "bg", path, mode])
    if shutil.which("swww"):
        return _run(["swww", "img", path])
    if shutil.which("feh"):
        return _run(["feh", STYLES.get(style, STYLES["fill"])[4], path])
    if shutil.which("nitrogen"):
        return _run(["nitrogen", "--set-zoom-fill", "--save", path])
    return False, f"Ambiente '{desktop()}' não suportado — instale o feh ou o swww"


def _linux_get() -> str:
    de = desktop()
    if de == "kde":
        cfg = Path.home() / ".config/plasma-org.kde.plasma.desktop-appletsrc"
        try:
            for line in cfg.read_text(errors="replace").splitlines():
                if line.startswith("Image="):
                    v = line[6:].strip()
                    return v[7:] if v.startswith("file://") else v
        except OSError:
            pass
        return ""
    schema, key = {"cinnamon": ("org.cinnamon.desktop.background", "picture-uri"),
                   "mate": ("org.mate.background", "picture-filename")}.get(
        de, ("org.gnome.desktop.background", "picture-uri"))
    if shutil.which("gsettings"):
        ok, out = _run(["gsettings", "get", schema, key])
        if ok:
            v = out.strip().strip("'")
            return v[7:] if v.startswith("file://") else v
    return ""


# ---------------------------------------------------------------------------------------------- API
def _stable_copy(path: str) -> str:
    """Copia a imagem para a pasta do Nexo: o fundo não desaparece se o original for apagado."""
    d = config_dir() / "wallpapers"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / os.path.basename(path)
    try:
        if os.path.abspath(path) != os.path.abspath(dest):
            shutil.copy2(path, dest)
        return str(dest)
    except OSError:
        return path


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def images() -> list[str]:
    """Imagens paradas guardadas na pasta de fundos do Nexo (usadas na troca automática)."""
    from . import animwp
    return [f for f in media() if f.lower().endswith(IMAGE_EXT) and not animwp.is_animated(f)]


def media() -> list[str]:
    """Todos os fundos guardados: imagens, GIF/WEBP animados e vídeos."""
    from .wallhaven import list_local
    return list_local()


def set_wallpaper(path: str, style: str | None = None, lock_screen: bool = False,
                  still: str | None = None) -> tuple[bool, str]:
    """Põe o fundo. Vídeos e GIF/WEBP animados ficam animados (ver core/animwp.py); `still` é a 1.ª imagem
    já extraída (opcional — serve para o ecrã de bloqueio e como reserva)."""
    from . import animwp
    if not os.path.isfile(path):
        return False, "Ficheiro não encontrado"
    animated = animwp.is_animated(path)
    if not animated and not path.lower().endswith(IMAGE_EXT):
        return False, "Use uma imagem (PNG, JPG, WEBP, BMP), um GIF animado ou um vídeo (MP4, WEBM, MKV…)"
    path = os.path.abspath(_stable_copy(path))
    style = style or get_setting("desktop_wp_style", "fill")
    if animated:
        still = still or animwp.still_frame(path)
        ok, msg = animwp.set_animated(path, style, still)
        lock_img = still
    else:
        animwp.stop()
        ok, msg = _win_set(path, style) if IS_WIN else _linux_set(path, style)
        lock_img = path
    if ok:
        set_setting("desktop_wp", path)
        if lock_screen and lock_img:
            lok, lmsg = _win_lock(lock_img) if IS_WIN else (
                _kde_lock(lock_img) if desktop() == "kde" else
                _gsettings("org.gnome.desktop.screensaver", "picture-uri", Path(lock_img).as_uri()))
            if not lok:
                msg = f"Ecrã de bloqueio não alterado: {lmsg}"
    return ok, msg or ("Fundo alterado" if ok else "Não foi possível mudar o fundo")


def current_wallpaper() -> str:
    from . import animwp
    anim = animwp.active()
    if anim:
        return anim
    try:
        p = _win_get() if IS_WIN else _linux_get()
    except Exception:  # noqa: BLE001
        p = ""
    if IS_WIN and p and os.path.dirname(os.path.abspath(p)) == str(animwp.frames_dir()):
        p = ""   # imagem de reserva de um fundo animado que já não está a tocar
    return p if p and os.path.exists(p) else (get_setting("desktop_wp") or "")
