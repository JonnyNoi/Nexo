"""Deteção de jogos: instalados (Steam, Heroic, Lutris, Epic, GOG) e a correr (Steam/Proton, Wine, lojas).

Nada aqui injeta código nos jogos: só se leem a lista de processos e os ficheiros das lojas."""
from __future__ import annotations

import glob
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from . import disksafety as ds
from .util import IS_WIN, get_setting

# ---------------------------------------------------------------------------------------------- instalados
_STEAM_TOOLS = re.compile(r"proton|steam linux runtime|steamworks common|steamvr|redistributable", re.I)


@dataclass
class Game:
    name: str
    store: str            # Steam, Epic, GOG, Heroic, Lutris…
    path: str = ""
    size: int = 0
    appid: str = ""
    launch: str = ""      # URI que a loja entende (steam://rungameid/…)
    extra: dict = field(default_factory=dict)


def steam_roots() -> list[str]:
    roots = []
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                roots.append(winreg.QueryValueEx(k, "SteamPath")[0].replace("/", "\\"))
        except OSError:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        h = Path.home()
        roots += [str(h / ".local/share/Steam"), str(h / ".steam/steam"), str(h / ".steam/root"),
                  str(h / ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
    out, seen = [], set()
    for r in roots:
        try:
            real = os.path.realpath(r)
        except OSError:
            continue
        if os.path.isdir(os.path.join(real, "steamapps")) and real not in seen:
            seen.add(real)
            out.append(real)
    return out


def steam_libraries() -> list[str]:
    """Pastas 'steamapps' de todas as bibliotecas (incluindo outros discos)."""
    libs, seen = [], set()
    for root in steam_roots():
        cands = [root]
        try:
            txt = Path(root, "steamapps", "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
            cands += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', txt)]
        except OSError:
            pass
        for c in cands:
            sa = os.path.join(c, "steamapps")
            try:
                real = os.path.realpath(sa)
            except OSError:
                continue
            if os.path.isdir(real) and real not in seen:
                seen.add(real)
                libs.append(real)
    return libs


def _acf(path: str) -> dict:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {k.lower(): v for k, v in re.findall(r'^\s*"(\w+)"\s+"([^"]*)"', txt, re.M)}


def _steam_games() -> list[Game]:
    out = []
    for lib in steam_libraries():
        for f in glob.glob(os.path.join(lib, "appmanifest_*.acf")):
            kv = _acf(f)
            name = kv.get("name", "")
            if not name or _STEAM_TOOLS.search(name):
                continue
            appid = kv.get("appid", "")
            out.append(Game(name, "Steam", os.path.join(lib, "common", kv.get("installdir", "")),
                            int(kv.get("sizeondisk", "0") or 0), appid, f"steam://rungameid/{appid}"))
    return out


def _heroic_games() -> list[Game]:
    out = []
    bases = [Path.home() / ".config/heroic", Path.home() / ".var/app/com.heroicgameslauncher.hgl/config/heroic"]
    if IS_WIN:
        bases = [Path(os.environ.get("APPDATA", "")) / "heroic"]
    for b in bases:
        try:
            data = json.loads((b / "legendaryConfig/legendary/installed.json").read_text(encoding="utf-8"))
            for app, d in (data or {}).items():
                out.append(Game(d.get("title") or app, "Epic (Heroic)", d.get("install_path", ""),
                                int(d.get("install_size") or 0), app, f"heroic://launch/legendary/{app}"))
        except (OSError, ValueError, AttributeError):
            pass
        try:
            data = json.loads((b / "gog_store/installed.json").read_text(encoding="utf-8"))
            for d in (data or {}).get("installed", []):
                p = d.get("install_path", "")
                out.append(Game(os.path.basename(p.rstrip("/\\")) or d.get("appName", "?"), "GOG (Heroic)", p,
                                int(d.get("install_size") or 0) if str(d.get("install_size", "")).isdigit() else 0,
                                d.get("appName", ""), f"heroic://launch/gog/{d.get('appName', '')}"))
        except (OSError, ValueError, AttributeError):
            pass
    return out


def _lutris_games() -> list[Game]:
    db = Path.home() / ".local/share/lutris/pga.db"
    if IS_WIN or not db.is_file():
        return []
    import sqlite3
    out = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        for name, slug, directory, runner in con.execute(
                "select name, slug, directory, runner from games where installed = 1"):
            out.append(Game(name, f"Lutris ({runner})" if runner else "Lutris", directory or "", 0, slug,
                            f"lutris:rungame/{slug}"))
        con.close()
    except sqlite3.Error:
        pass
    return out


def _epic_games() -> list[Game]:
    if not IS_WIN:
        return []
    out = []
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    for f in glob.glob(os.path.join(pd, r"Epic\EpicGamesLauncher\Data\Manifests\*.item")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "games" not in [c.lower() for c in d.get("AppCategories", ["games"])]:
            continue
        app = d.get("AppName", "")
        out.append(Game(d.get("DisplayName") or app, "Epic", d.get("InstallLocation", ""),
                        int(d.get("InstallSize") or 0), app,
                        f"com.epicgames.launcher://apps/{app}?action=launch&silent=true"))
    return out


def _gog_games() -> list[Game]:
    if not IS_WIN:
        return []
    out = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games") as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = winreg.QueryValueEx(k, "gameName")[0]
                        path = winreg.QueryValueEx(k, "path")[0]
                    out.append(Game(name, "GOG", path, 0, sub, f"goggalaxy://openGameView/{sub}"))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def installed_games() -> list[Game]:
    games: list[Game] = []
    for fn in (_steam_games, _epic_games, _gog_games, _heroic_games, _lutris_games):
        try:
            games += fn()
        except Exception:  # noqa: BLE001
            pass
    # tamanho em falta: soma rápida só para pastas que existem (limitada)
    for g in games:
        if not g.size and g.path and os.path.isdir(g.path):
            g.size = _du(g.path, limit_s=1.5)
    seen, out = set(), []
    for g in sorted(games, key=lambda g: g.name.lower()):
        k = (g.name.lower(), g.store)
        if k not in seen:
            seen.add(k)
            out.append(g)
    return out


def _du(path: str, limit_s: float) -> int:
    total, t0 = 0, time.monotonic()
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
        if time.monotonic() - t0 > limit_s:
            break
    return total


# ---------------------------------------------------------------------------------------------- a correr
# processos que nunca são "o jogo" (lojas, ajudantes, Wine, anti-batota, crash reporters…)
_NOT_GAME = {
    "steam", "steam.exe", "steamwebhelper", "steamwebhelper.exe", "steamservice.exe", "gameoverlayui",
    "gameoverlayui.exe", "steamerrorreporter", "steamerrorreporter.exe", "steamerrorreporter64.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "epiconlineservices.exe", "epiconlineserviceshost.exe",
    "galaxyclient.exe", "galaxyclient helper.exe", "gogalaxy.exe", "eadesktop.exe", "eabackgroundservice.exe",
    "upc.exe", "ubisoftconnect.exe", "uplaywebcore.exe", "battle.net.exe", "agent.exe", "riotclientservices.exe",
    "riotclientux.exe", "riotclientuxrender.exe", "riotclientcrashhandler.exe", "vgtray.exe", "vgc.exe",
    "easyanticheat.exe", "easyanticheat_eos.exe", "beservice.exe", "beservice_x64.exe", "start_protected_game.exe",
    "crashreportclient.exe", "unrealcefsubprocess.exe", "crashpad_handler.exe", "uninstall.exe",
    "explorer.exe", "services.exe", "winedevice.exe", "plugplay.exe", "rpcss.exe", "svchost.exe", "conhost.exe",
    "start.exe", "rundll32.exe", "tabtip.exe", "winemenubuilder.exe", "wineboot.exe", "mscorsvw.exe",
    "cmd.exe", "rpcss", "wineserver", "wine", "wine64", "wine-preloader", "wine64-preloader", "pressure-vessel-wrap",
    "pv-bwrap", "srt-bwrap", "reaper", "steam-runtime-launcher-service", "python3", "python", "bash", "sh",
    "heroic", "lutris", "legendary", "gogdl", "umu-run", "mangohud", "gamescope", "gamemoded", "xdg-dbus-proxy",
    "iexplore.exe", "msedgewebview2.exe", "cefsharp.browsersubprocess.exe", "qtwebengineprocess.exe",
    "nexo", "nexo.exe",
}
_WINE_LOADERS = {"wine-preloader", "wine64-preloader", "wine", "wine64"}
MIN_WINE_RSS = 150 * 1024**2
_steam_name_cache: dict[str, str] = {}


def steam_name(appid: str) -> str:
    if appid in _steam_name_cache:
        return _steam_name_cache[appid]
    name = ""
    for lib in steam_libraries():
        kv = _acf(os.path.join(lib, f"appmanifest_{appid}.acf"))
        if kv.get("name"):
            name = kv["name"]
            break
    _steam_name_cache[appid] = name
    return name


def _win_path(s: str) -> str:
    """Caminho tal como o Wine o mostra: 'Z:\\home\\x\\jogo.exe' → '/home/x/jogo.exe'."""
    if len(s) > 2 and s[1] == ":" and s[0].lower() == "z" and not IS_WIN:
        return s[2:].replace("\\", "/")
    return s


_root_cache: dict[str, tuple[str, ds.Verdict] | None] = {}


def _game_root(path: str) -> tuple[str, ds.Verdict] | None:
    """Sobe na árvore até encontrar a pasta do jogo (regras do disksafety: steamapps/common/X, Epic Games/X…).
    O resultado fica em cache: os caminhos dos executáveis não mudam e classify() custa várias expressões regulares."""
    if path in _root_cache:
        return _root_cache[path]
    if len(_root_cache) > 4096:
        _root_cache.clear()
    res = _root_cache[path] = _game_root_uncached(path)
    return res


def _game_root_uncached(path: str) -> tuple[str, ds.Verdict] | None:
    p = path.rstrip("/\\")
    for _ in range(10):
        parent = os.path.dirname(p) if "/" in p or "\\" in p else ""
        if not parent or parent == p:
            break
        v = ds.classify(p)
        if v.is_game:
            return p, v
        p = parent
    return None


@dataclass
class RunningGame:
    name: str
    pid: int
    source: str          # "Steam", "Wine/Proton", "Pasta de jogos", "Definido por si"
    exe: str = ""
    appid: str = ""
    started: float = 0.0


# dados que não mudam durante a vida de um processo (nome, exe, cmdline, pai), por (pid, create_time):
# ler /proc/<pid>/cmdline e exe de TODOS os processos a cada 4 s era o maior custo do Nexo em repouso
_static: dict[int, dict] = {}


def _process_table() -> dict[int, dict]:
    procs: dict[int, dict] = {}
    for p in psutil.process_iter():
        try:
            ct = p.create_time()   # o psutil guarda-o no objeto Process (que também reaproveita entre chamadas)
        except (psutil.Error, OSError):
            continue
        info = _static.get(p.pid)
        if info is None or info["create_time"] != ct:
            try:
                info = p.as_dict(["pid", "ppid", "name", "exe", "cmdline"])
            except (psutil.Error, OSError):
                continue
            info["create_time"] = ct
            info["_proc"] = p
            _static[p.pid] = info
        procs[p.pid] = info
    for pid in [k for k in _static if k not in procs]:
        del _static[pid]
    return procs


def _rss(info: dict) -> int:
    """Memória residente (só pedida para os candidatos a jogo)."""
    try:
        return info["_proc"].memory_info().rss
    except (psutil.Error, OSError, KeyError):
        return 0


def detect_running() -> RunningGame | None:
    """O jogo que está a correr agora (o processo mais pesado que pareça um jogo), ou None."""
    extra = {x.lower() for x in (get_setting("game_processes") or [])}
    procs = _process_table()
    reapers: dict[int, str] = {}
    for pid, i in procs.items():
        if (i.get("name") or "") == "reaper":
            m = re.search(r"AppId=(\d+)", " ".join(i.get("cmdline") or []))
            if m:
                reapers[pid] = m.group(1)

    def steam_appid_of(pid: int) -> str:
        seen = 0
        while pid and seen < 25:
            if pid in reapers:
                return reapers[pid]
            pid = (procs.get(pid) or {}).get("ppid") or 0
            seen += 1
        return ""

    best: tuple[int, int, RunningGame] | None = None   # (prioridade, rss, jogo)
    me = os.getpid()
    for pid, i in procs.items():
        if pid == me:
            continue
        name = (i.get("name") or "").lower()
        cmd = i.get("cmdline") or []
        exe = i.get("exe") or ""
        argv0 = _win_path(cmd[0]) if cmd else ""
        base = os.path.basename(argv0.replace("\\", "/")).lower() if argv0 else name
        if name in _NOT_GAME or base in _NOT_GAME:
            if not (name in _WINE_LOADERS and base not in _NOT_GAME):
                continue
        game: RunningGame | None = None
        prio = 0
        if name in extra or base in extra or os.path.splitext(base)[0] in extra:
            game, prio = RunningGame(os.path.splitext(base)[0], pid, "Definido por si", exe or argv0), 4
        else:
            for path in (argv0, exe):
                if not path:
                    continue
                hit = _game_root(path)
                if hit:
                    root, v = hit
                    nm = v.name or os.path.basename(root)
                    game, prio = RunningGame(nm, pid, "Pasta de jogos", path, v.steam_appid), 3
                    break
            if game is None and base.endswith(".exe") and _rss(i) >= MIN_WINE_RSS:
                folder = os.path.basename(os.path.dirname(argv0.replace("\\", "/")))
                stem = os.path.splitext(os.path.basename(argv0.replace("\\", "/")))[0]
                nm = folder if folder.lower() not in ("bin", "binaries", "win64", "x64", "game", "") else stem
                game, prio = RunningGame(nm or stem, pid, "Wine/Proton", argv0), 2
        if game is None:
            continue
        appid = game.appid or steam_appid_of(pid)
        if appid:
            game.appid = appid
            game.name = steam_name(appid) or game.name
            game.source = "Steam"
            prio += 1
        game.started = i.get("create_time") or time.time()
        rss = _rss(i)
        if best is None or (prio, rss) > best[:2]:
            best = (prio, rss, game)
    return best[2] if best else None
