"""Perfis por jogo: o que muda quando um jogo arranca e volta ao normal quando fecha.

Para cada jogo (pelo nome que o Modo jogo deteta):
  • ventoinhas  — guardado à parte (hwcontrol.set_game_profile / fan_game_profiles);
  • energia     — perfil de energia durante o jogo ("" = não mudar); o anterior é reposto no fim;
  • overlay     — "" = como nas definições gerais, "on" = sempre, "off" = nunca;
  • fechar      — programas a fechar quando o jogo arranca (pedido normal de fecho, nunca à força);
  • gamemode    — Linux: pede ao Feral GameMode (gamemoded) otimizações para o processo do jogo.

As definições ficam em `game_profiles` = {jogo: {...}}."""
from __future__ import annotations

import os

import psutil

from .util import IS_LINUX, IS_WIN, get_setting, run, set_setting, which

KEY = "game_profiles"
POWER_CHOICES = {"": "Não mudar", "performance": "Desempenho", "balanced": "Equilibrado",
                 "power-saver": "Poupança de energia"}
OVERLAY_CHOICES = {"": "Como nas definições gerais", "on": "Mostrar sempre", "off": "Nunca mostrar"}
DEFAULT = {"power": "", "overlay": "", "close": [], "gamemode": False}


def _all() -> dict:
    d = get_setting(KEY) or {}
    return d if isinstance(d, dict) else {}


def get(game: str | None) -> dict:
    if not game:
        return dict(DEFAULT)
    p = _all().get(game) or {}
    return {**DEFAULT, **(p if isinstance(p, dict) else {})}


def set_value(game: str, key: str, value) -> None:
    if key not in DEFAULT:
        raise KeyError(key)
    allp = dict(_all())
    p = {**DEFAULT, **(allp.get(game) or {})}
    p[key] = value
    if p == DEFAULT:
        allp.pop(game, None)     # perfil vazio não ocupa espaço
    else:
        allp[game] = p
    set_setting(KEY, allp)


def has_profile(game: str) -> bool:
    return game in _all() or game in (get_setting("fan_game_profiles") or {})


def power_for(game: str | None) -> str:
    v = get(game)["power"]
    return v if v in POWER_CHOICES else ""


def overlay_for(game: str | None, general: bool) -> bool:
    v = get(game)["overlay"]
    return True if v == "on" else False if v == "off" else bool(general)


def known_games() -> list[str]:
    """Jogos para escolher no editor: os que já têm perfil + os das sessões guardadas."""
    names = set(_all()) | set(get_setting("fan_game_profiles") or {})
    try:
        from . import sessions
        names |= {s.name for s in sessions.recent(300)}
    except Exception:  # noqa: BLE001 — base de dados ainda não existe ou ilegível
        pass
    return sorted(n for n in names if n)


# --------------------------------------------------------------------------- fechar programas
# nunca fechar (sessão gráfica, sistema, o próprio Nexo, lançadores de que o jogo depende)
_NEVER = {"systemd", "init", "xorg", "xwayland", "gnome-shell", "kwin_wayland", "kwin_x11", "plasmashell",
          "pipewire", "wireplumber", "pulseaudio", "dbus-daemon", "dbus-broker", "sddm", "gdm", "explorer",
          "csrss", "winlogon", "wininit", "services", "lsass", "svchost", "dwm", "smss", "system", "steam",
          "steamwebhelper", "nexo", "python", "python3", "pythonw", "gamemoded", "mangohud", "wine", "wine64",
          "wineserver", "lutris", "heroic", "epicgameslauncher", "galaxyclient"}


def _norm(name: str) -> str:
    n = os.path.basename(name or "").strip().lower()
    return n[:-4] if n.endswith(".exe") else n


def can_close(name: str) -> bool:
    n = _norm(name)
    return bool(n) and n not in _NEVER


def close_programs(names: list[str], game_pid: int = 0) -> list[str]:
    """Pede para fechar os programas do utilizador com estes nomes. Devolve os nomes fechados."""
    want = {_norm(n) for n in names if can_close(n)}
    if not want:
        return []
    me = os.getpid()
    try:
        user = psutil.Process(me).username()
    except psutil.Error:
        user = None
    protect = {me, game_pid}
    try:   # o jogo e os pais dele (lançador) ficam
        p = psutil.Process(game_pid) if game_pid else None
        while p is not None:
            protect.add(p.pid)
            p = p.parent()
    except psutil.Error:
        pass
    closed, procs = set(), []
    for p in psutil.process_iter(["pid", "name", "username"]):
        info = p.info
        n = _norm(info.get("name") or "")
        if n in want and info["pid"] not in protect and (user is None or info.get("username") == user):
            try:
                p.terminate()
                procs.append(p)
                closed.add(info.get("name") or n)
            except psutil.Error:
                pass
    psutil.wait_procs(procs, timeout=3)
    return sorted(closed)


# --------------------------------------------------------------------------- Feral GameMode (Linux)
_GM = ["--session", "--dest", "com.feralinteractive.GameMode", "--object-path", "/com/feralinteractive/GameMode",
       "--method"]


def gamemode_available() -> bool:
    return IS_LINUX and bool(which("gdbus")) and bool(which("gamemoded"))


def gamemode_register(pid: int, on: bool) -> tuple[bool, str]:
    """RegisterGame/UnregisterGame no gamemoded (pela sessão D-Bus do utilizador, sem palavra-passe)."""
    if not gamemode_available():
        return False, "O GameMode (gamemoded) não está instalado."
    method = "com.feralinteractive.GameMode." + ("RegisterGame" if on else "UnregisterGame")
    code, out = run(["gdbus", "call", *_GM, method, str(int(pid))], timeout=10)
    # resposta "(0,)" = sucesso; "(-1,)" = recusado
    ok = code == 0 and "(0," in out.replace(" ", "")
    return ok, "" if ok else (out.strip()[-200:] or "o gamemoded recusou o pedido")


def power_available() -> bool:
    return IS_WIN or (IS_LINUX and bool(which("powerprofilesctl")))
