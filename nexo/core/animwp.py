"""Fundos animados (vídeo, GIF, WEBP/PNG animados) no ambiente de trabalho — Windows e Linux.

Como cada sistema os põe a mexer:
  * Windows: o próprio Nexo (`Nexo --wallpaper-player`, ver ui/wpplayer.py) desenha o vídeo/GIF numa janela
    colada por trás dos ícones (WorkerW). Fica a correr sozinho, mesmo com a janela do Nexo fechada, e arranca
    com o Windows (chave Run). Como imagem fixa (ecrã de bloqueio, se o leitor parar) fica a 1.ª imagem.
  * KDE Plasma: GIF/WEBP animados com o plugin normal de imagem (o Plasma anima-os); vídeos com o plugin
    "Smart Video Wallpaper Reborn" (luisbocanegra.smart.video.wallpaper.reborn).
  * Hyprland / Sway / outros wlroots: mpvpaper (vídeo e GIF) ou swww (GIF).
  * X11 (XFCE sem ícones, i3, Openbox, GNOME em X11…): o leitor do Nexo como janela do tipo "desktop".
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .util import IS_WIN, config_dir, load_json, save_json

VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi")
MAYBE_ANIM_EXT = (".gif", ".webp", ".png", ".apng")
KDE_VIDEO_PLUGIN = "luisbocanegra.smart.video.wallpaper.reborn"
KDE_VIDEO_PLUGIN_URL = "https://store.kde.org/p/2139746"
STATE = "fundo_animado.json"
RUN_KEY_NAME = "NexoFundoAnimado"

# ajuste -> modo do plugin de vídeo do KDE (0 esticar, 1 ajustar, 2 preencher) e opções do mpv
KDE_FILL = {"fill": 2, "fit": 1, "stretch": 0, "center": 1, "tile": 2, "span": 2}
MPV_FILL = {"fill": ["--panscan=1.0"], "span": ["--panscan=1.0"], "tile": ["--panscan=1.0"],
            "stretch": ["--keepaspect=no"], "fit": [], "center": []}

_anim_cache: dict[tuple[str, float], bool] = {}


# ---------------------------------------------------------------------------------------------- deteção
def is_video(path: str) -> bool:
    return path.lower().endswith(VIDEO_EXT)


def is_animated(path: str) -> bool:
    """True para vídeos e para GIF/WEBP/PNG com mais de uma imagem (um GIF parado não conta)."""
    low = path.lower()
    if low.endswith(VIDEO_EXT):
        return True
    if not low.endswith(MAYBE_ANIM_EXT):
        return False
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return False
    if key not in _anim_cache:
        _anim_cache[key] = _count_frames(path) > 1
    return _anim_cache[key]


def _count_frames(path: str) -> int:
    try:
        from PySide6.QtGui import QImageReader
    except ImportError:  # pragma: no cover
        return 2 if path.lower().endswith(".gif") else 1
    r = QImageReader(path)
    if not r.supportsAnimation():
        return 1
    n = r.imageCount()
    if n > 1:
        return n
    # alguns leitores (WEBP) devolvem 0: conta à mão até à 2.ª imagem
    count = 0
    while count < 2 and not r.read().isNull():
        count += 1
    return count


# ---------------------------------------------------------------------------------------------- 1.ª imagem
def frames_dir() -> Path:
    d = config_dir() / "wallpapers" / ".imagens"
    d.mkdir(parents=True, exist_ok=True)
    return d


def still_path(path: str) -> Path:
    """Onde fica guardada a 1.ª imagem (JPG) de um fundo animado."""
    return frames_dir() / (os.path.basename(path) + ".jpg")


def still_frame(path: str) -> str | None:
    """Devolve (e guarda) uma imagem parada do fundo animado — miniaturas, ecrã de bloqueio, fundo de reserva.

    GIF/WEBP: lida com o Qt. Vídeo: ffmpeg, se existir (no Windows a página usa o leitor de vídeo do Qt
    e grava no mesmo sítio, ver ui/pages/wallpaper.py)."""
    out = still_path(path)
    try:
        if out.exists() and out.stat().st_mtime >= os.path.getmtime(path):
            return str(out)
    except OSError:
        return None
    if is_video(path):
        ff = shutil.which("ffmpeg")
        if not ff:
            return None
        for seek in ("1", "0"):  # 1 s dentro (evita o ecrã preto do início); vídeos curtos: o início
            try:
                subprocess.run([ff, "-y", "-loglevel", "error", "-ss", seek, "-i", path, "-frames:v", "1",
                                "-q:v", "3", str(out)], capture_output=True, timeout=60,
                               creationflags=0x08000000 if IS_WIN else 0)
            except (OSError, subprocess.SubprocessError):
                return None
            if out.exists() and out.stat().st_size:
                return str(out)
        return None
    try:
        from PySide6.QtGui import QImageReader
    except ImportError:  # pragma: no cover
        return None
    img = QImageReader(path).read()
    if img.isNull() or not img.save(str(out), "JPG", 90):
        return None
    return str(out)


# ---------------------------------------------------------------------------------------------- estado
def _state() -> dict:
    s = load_json(STATE, {})
    return s if isinstance(s, dict) else {}


def _player_alive(s: dict) -> bool:
    pid = s.get("pid")
    if not pid:
        return False
    try:
        import psutil
        p = psutil.Process(int(pid))
        return abs(p.create_time() - float(s.get("created", 0))) < 2 and p.is_running()
    except Exception:  # noqa: BLE001 (processo já não existe / sem acesso)
        return False


def active() -> str:
    """Caminho do fundo animado em uso ('' se não houver)."""
    s = _state()
    path = s.get("path") or ""
    if not path or not os.path.exists(path):
        return ""
    method = s.get("method")
    if method in ("player", "mpvpaper") and not _player_alive(s):
        return ""
    if method == "kde-image":
        from .desktopwp import _linux_get
        if os.path.abspath(_linux_get() or "") != os.path.abspath(path):
            return ""
    if method == "kde-video":
        cfg = Path.home() / ".config/plasma-org.kde.plasma.desktop-appletsrc"
        try:
            if f"wallpaperplugin={KDE_VIDEO_PLUGIN}" not in cfg.read_text(errors="replace"):
                return ""
        except OSError:
            return ""
    return path


def _kill_player(s: dict) -> None:
    """Termina o leitor e os filhos (o .exe de ficheiro único corre o Python num processo filho)."""
    if not _player_alive(s):
        return
    import psutil
    try:
        root = psutil.Process(int(s["pid"]))
        procs = [*root.children(recursive=True), root]
    except psutil.Error:
        return
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass


def stop(restore_still: bool = False) -> None:
    """Pára o fundo animado que o Nexo lançou (leitor próprio ou mpvpaper). Os plugins do KDE ficam até
    serem substituídos por outro fundo."""
    s = _state()
    if not s:
        return
    _kill_player(s)
    if IS_WIN:
        _win_autostart(None)
        if restore_still and s.get("still") and os.path.exists(s["still"]):
            from .desktopwp import _win_set
            _win_set(s["still"], s.get("style") or "fill")   # repinta o ambiente de trabalho
    save_json(STATE, {})


# ---------------------------------------------------------------------------------------------- comando do leitor
def player_command(path: str, style: str) -> list[str]:
    args = ["--wallpaper-player", path, "--style", style]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    exe = sys.executable
    if IS_WIN:   # sem janela de consola
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = w if os.path.exists(w) else exe
    root = str(Path(__file__).resolve().parents[2])
    return [exe, "-c", f"import sys; sys.path.insert(0, {root!r}); from nexo.app import main; sys.exit(main())",
            *args]


def _spawn(cmd: list[str]) -> int:
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                "close_fds": True}
    if IS_WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw).pid  # noqa: S603


def _remember(path: str, style: str, method: str, still: str | None, pid: int | None = None) -> None:
    s = {"path": path, "style": style, "method": method, "still": still or ""}
    if pid:
        try:
            import psutil
            s.update(pid=pid, created=psutil.Process(pid).create_time())
        except Exception:  # noqa: BLE001
            s.update(pid=pid, created=0)
    save_json(STATE, s)


def register_self(path: str) -> bool:
    """Chamado pelo leitor ao arrancar (também no início de sessão do Windows). False = não devia estar a
    correr (o fundo entretanto mudou, ou já há outro leitor) e o leitor sai."""
    s = _state()
    if s.get("method") != "player" or os.path.abspath(s.get("path") or "") != os.path.abspath(path):
        return False
    # (no executável de ficheiro único o PID lançado é o do arrancador do PyInstaller, o nosso pai)
    if s.get("pid") not in (None, os.getpid(), os.getppid()) and _player_alive(s):
        return False
    import psutil
    s.update(pid=os.getpid(), created=psutil.Process().create_time())
    save_json(STATE, s)
    return True


def relaunch_player(path: str, style: str) -> None:
    """Lança um leitor novo para o mesmo fundo (o atual vai sair)."""
    s = _state()
    s.pop("pid", None)
    save_json(STATE, s)
    pid = _spawn(player_command(path, style))
    _remember(path, style, "player", s.get("still"), pid)


def _win_autostart(cmd: list[str] | None) -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if cmd:
                winreg.SetValueEx(k, RUN_KEY_NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
            else:
                try:
                    winreg.DeleteValue(k, RUN_KEY_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------- aplicar
def kde_video_plugin_installed() -> bool:
    return any((base / KDE_VIDEO_PLUGIN / "metadata.json").exists()
               for base in (Path.home() / ".local/share/plasma/wallpapers", Path("/usr/share/plasma/wallpapers")))


def _kde_video(path: str, style: str) -> tuple[bool, str]:
    from .desktopwp import _run
    if not kde_video_plugin_installed():
        return False, ("Para vídeos no KDE é preciso o plugin «Smart Video Wallpaper Reborn» "
                       "(Definições do fundo → Obter novos plugins…, ou o pacote "
                       "plasma6-wallpapers-smart-video-wallpaper-reborn do AUR)")
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus") or shutil.which("qdbus-qt6")
    if not qdbus:
        return False, "Não encontrei o qdbus"
    url = Path(path).as_uri()
    videos = json.dumps([{"filename": url, "enabled": True, "duration": 0, "customDuration": 0, "playbackRate": 0,
                          "alternativePlaybackRate": 0, "loop": True, "dayNightPhase": 4}])
    js = ("var all = desktops(); for (var i = 0; i < all.length; i++) { var d = all[i];"
          f"d.wallpaperPlugin = '{KDE_VIDEO_PLUGIN}';"
          f"d.currentConfigGroup = ['Wallpaper', '{KDE_VIDEO_PLUGIN}', 'General'];"
          f"d.writeConfig('VideoUrls', {json.dumps(videos)}); d.writeConfig('LastVideo', {json.dumps(url)});"
          f"d.writeConfig('LastVideoPosition', 0); d.writeConfig('FillMode', {KDE_FILL.get(style, 2)}); }}")
    return _run([qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", js])


def _x11_session() -> bool:
    return bool(os.environ.get("DISPLAY")) and os.environ.get("XDG_SESSION_TYPE", "x11") == "x11"


def set_animated(path: str, style: str, still: str | None = None) -> tuple[bool, str]:
    """Põe um fundo animado. Devolve (ok, mensagem)."""
    from .desktopwp import _kde_set, desktop
    if not os.path.isfile(path):
        return False, "Ficheiro não encontrado"
    still = still or still_frame(path)
    stop()
    if IS_WIN:
        if still:   # imagem de reserva: aparece se o leitor parar (e por baixo, enquanto arranca)
            from .desktopwp import _win_set
            _win_set(still, style)
        cmd = player_command(path, style)
        _remember(path, style, "player", still)   # antes de lançar: o leitor confirma que é o fundo atual
        pid = _spawn(cmd)
        _win_autostart(cmd)
        _remember(path, style, "player", still, pid)
        return True, "Fundo animado a tocar (continua mesmo com o Nexo fechado)"

    de = desktop()
    if de == "kde":
        if is_video(path):
            ok, msg = _kde_video(path, style)
            method = "kde-video"
        else:
            ok, msg = _kde_set(path, style)   # o plugin de imagem do Plasma anima GIF/WEBP sozinho
            method = "kde-image"
        if ok:
            _remember(path, style, method, still)
        return ok, msg

    if de in ("hyprland", "sway") or os.environ.get("WAYLAND_DISPLAY"):
        if not is_video(path) and shutil.which("swww"):
            from .desktopwp import _run
            ok, msg = _run(["swww", "img", path])
            if ok:
                _remember(path, style, "swww-anim", still)
            return ok, msg
        mp = shutil.which("mpvpaper")
        if mp and de not in ("gnome", "kde"):
            opts = " ".join(["no-audio", "--loop-file=inf", "--hwdec=auto", *MPV_FILL.get(style, [])])
            pid = _spawn([mp, "-o", opts, "ALL", path])
            _remember(path, style, "mpvpaper", still, pid)
            return True, "Fundo animado a tocar com o mpvpaper"
        if de == "gnome":
            return False, "O GNOME em Wayland não deixa pôr vídeos no fundo sem a extensão «Hanabi»"
        return False, "Instale o mpvpaper (vídeos e GIF) ou o swww (GIF) para fundos animados neste ambiente"

    if _x11_session():
        _remember(path, style, "player", still)
        pid = _spawn(player_command(path, style))
        _remember(path, style, "player", still, pid)
        return True, "Fundo animado a tocar (enquanto a sessão estiver aberta)"
    return False, f"Fundos animados ainda não são suportados em '{de}'"
