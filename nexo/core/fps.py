"""Contador de FPS do jogo a correr — sem injetar código pelo Nexo.

Fontes, por ordem:
  • Linux: MangoHud. O jogo é lançado com `mangohud` e uma opção que faz o MangoHud gravar um registo CSV
    (uma linha a cada 250 ms, escrita na hora) numa pasta do Nexo; lemos a última linha.
  • Windows: RivaTuner Statistics Server (RTSS/MSI Afterburner), se estiver aberto — lemos a memória
    partilhada que ele publica para outros programas.
  • Windows: PresentMon (Intel, código aberto). Usa os eventos do próprio Windows (ETW), não toca no jogo,
    por isso é seguro com anti-batota. Precisa de administrador ou do grupo "Performance Log Users"."""
from __future__ import annotations

import collections
import hashlib
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .util import IS_WIN, config_dir

# ============================================================================================ Linux: MangoHud
def mangohud_dir() -> Path:
    d = config_dir() / "fps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mangohud_env() -> str:
    """Valor de MANGOHUD_CONFIG: grava o registo para o Nexo e esconde a caixa do MangoHud (o overlay do Nexo
    já mostra tudo). `read_cfg` mantém o resto da configuração do utilizador."""
    return f"read_cfg,no_display,autostart_log=1,log_interval=250,output_folder={mangohud_dir()}"


def steam_launch_option() -> str:
    return f"MANGOHUD_CONFIG={mangohud_env()} mangohud %command%"


def _user_mangohud_dirs() -> list[Path]:
    """Pasta de registos definida pelo utilizador no MangoHud.conf (se já grava registos por conta própria)."""
    out = []
    conf = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "MangoHud" / "MangoHud.conf"
    try:
        for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*output_folder\s*=\s*(.+?)\s*$", line)
            if m:
                out.append(Path(os.path.expanduser(m.group(1))))
    except OSError:
        pass
    return out


def _tail_line(path: Path) -> str:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 2048))
        chunk = f.read().decode("utf-8", "replace")
    lines = [ln for ln in chunk.split("\n") if ln.strip()]
    if not chunk.endswith("\n") and lines:
        lines.pop()          # última linha ainda a meio de ser escrita
    return lines[-1] if lines else ""


def _read_mangohud() -> tuple[float, float] | None:
    now = time.time()
    best: tuple[float, Path] | None = None
    for d in [mangohud_dir(), *_user_mangohud_dirs()]:
        try:
            for e in os.scandir(d):
                if e.name.endswith(".csv") and "_summary" not in e.name:
                    mt = e.stat().st_mtime
                    if now - mt < 3 and (best is None or mt > best[0]):
                        best = (mt, Path(e.path))
        except OSError:
            continue
    if best is None:
        return None
    try:
        cols = _tail_line(best[1]).split(",")
        if len(cols) < 10:
            return None
        fps, ft = float(cols[0]), float(cols[1])
    except (OSError, ValueError):
        return None
    if not 0 < fps < 5000:
        return None
    return fps, (ft if ft > 0 else 1000.0 / fps)


def prune_mangohud_logs(keep: int = 8) -> None:
    """Os registos são só nossos (pasta do Nexo): guarda os mais recentes, apaga os restantes."""
    try:
        files = sorted(mangohud_dir().glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for p in files[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


# ============================================================================================ Windows: RTSS
def _read_rtss(pid: int) -> tuple[float, float] | None:
    if not IS_WIN:
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenFileMappingW.restype = wintypes.HANDLE
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    h = k32.OpenFileMappingW(0x0004, False, "RTSSSharedMemoryV2")   # FILE_MAP_READ
    if not h:
        return None
    try:
        view = k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
        if not view:
            return None
        try:
            import struct
            sig, _ver, entry_size, arr_off, arr_size = struct.unpack("<5I", ctypes.string_at(view, 20))
            if sig != 0x52545353 or not entry_size or arr_size > 1024:   # 'RTSS'
                return None
            tick = k32.GetTickCount()
            cands = []
            for i in range(arr_size):
                raw = ctypes.string_at(view + arr_off + i * entry_size, 284)
                e_pid = struct.unpack_from("<I", raw, 0)[0]
                t0, t1, frames, ftime = struct.unpack_from("<4I", raw, 268)
                if not e_pid or t1 <= t0 or (tick - t1) & 0xFFFFFFFF > 2000:
                    continue
                fps = 1000.0 * frames / (t1 - t0)
                cands.append((e_pid == pid, fps, ftime / 1000.0 if ftime else 1000.0 / max(fps, 0.1)))
            if not cands:
                return None
            _mine, fps, ft = max(cands)
            return fps, ft
        finally:
            k32.UnmapViewOfFile(view)
    except Exception:
        return None
    finally:
        k32.CloseHandle(h)


# ============================================================================================ Windows: PresentMon
PRESENTMON_URL = "https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/PresentMon-2.6.0-x64.exe"
# SHA-256 publicado pelo GitHub para este ficheiro da release v2.6.0 — o Nexo corre como administrador no
# Windows e executa este programa, por isso só aceita exatamente este binário.
PRESENTMON_SHA256 = "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af"
_IGNORE_APPS = {"dwm.exe", "explorer.exe", "nexo.exe", "python.exe", "pythonw.exe", "presentmon.exe",
                "steamwebhelper.exe", "msedgewebview2.exe", "chrome.exe", "firefox.exe", "msedge.exe"}


def presentmon_path() -> Path:
    return config_dir() / "ferramentas" / "PresentMon.exe"


_pm_ok_cache: dict = {}


def presentmon_installed() -> bool:
    """Só conta o binário oficial (mesmo SHA-256). Resultado guardado por (tamanho, mtime) — é chamado em ciclo."""
    p = presentmon_path()
    try:
        st = p.stat()
    except OSError:
        return False
    key = (st.st_size, st.st_mtime_ns)
    if key not in _pm_ok_cache:
        _pm_ok_cache.clear()
        _pm_ok_cache[key] = file_sha256(p) == PRESENTMON_SHA256
    return _pm_ok_cache[key]


def file_sha256(path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def install_presentmon() -> str:
    """Transfere o PresentMon oficial (GitHub da Intel/GameTechDev). Só corre a pedido do utilizador."""
    import urllib.request
    dest = presentmon_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(PRESENTMON_URL, headers={"User-Agent": "Nexo"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310 (URL https fixa)
        while chunk := r.read(65536):
            f.write(chunk)
            h.update(chunk)
    if h.hexdigest() != PRESENTMON_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("O ficheiro transferido não corresponde ao PresentMon oficial (verificação SHA-256 "
                           "falhou). Não foi instalado.")
    os.replace(tmp, dest)
    return str(dest)


def grant_perf_log_permission() -> bool:
    """Junta o utilizador ao grupo "Performance Log Users" (SID S-1-5-32-559, igual em qualquer idioma),
    o que deixa o PresentMon ler os eventos sem correr o Nexo como administrador. Pede UAC.
    Só tem efeito depois de terminar sessão e voltar a entrar."""
    if not IS_WIN:
        return False
    import ctypes
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\").replace("'", "''")
    ps = f"Add-LocalGroupMember -SID 'S-1-5-32-559' -Member '{user}' -ErrorAction SilentlyContinue"
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                             f'-NoProfile -WindowStyle Hidden -Command "{ps}"', None, 0)
    return rc > 32


class _PresentMon:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.frames: dict[int, collections.deque] = {}
        self.names: dict[int, str] = {}
        self.last: dict[int, float] = {}
        self.lock = threading.Lock()
        self.error = ""
        self.started = 0.0

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running() or not presentmon_installed():
            return
        self.error = ""
        cmd = [str(presentmon_path()), "--output_stdout", "--no_console_stats", "--stop_existing_session",
               "--session_name", "NexoFPS", "--no_track_gpu", "--no_track_input"]
        for ex in ("dwm.exe", "explorer.exe"):
            cmd += ["--exclude", ex]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                         text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
        except OSError as e:
            self.proc, self.error = None, str(e)
            return
        self.started = time.monotonic()
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_err, args=(self.proc,), daemon=True).start()

    def _read_err(self, proc):
        txt = proc.stderr.read() if proc.stderr else ""
        if proc is self.proc and txt.strip():
            low = txt.lower()
            if "access" in low or "elevat" in low or "administrator" in low or "performance log" in low:
                self.error = "sem-permissao"
            else:
                self.error = txt.strip().splitlines()[-1][:200]

    def _read(self, proc):
        idx = None
        for line in proc.stdout:
            cols = line.rstrip("\r\n").split(",")
            if idx is None:
                if "Application" in cols and "ProcessID" in cols:
                    ms = next((c for c in ("MsBetweenPresents", "FrameTime", "MsBetweenAppStart") if c in cols), None)
                    if ms:
                        idx = (cols.index("Application"), cols.index("ProcessID"), cols.index(ms))
                continue
            try:
                app, pid, ms = cols[idx[0]], int(cols[idx[1]]), float(cols[idx[2]])
            except (ValueError, IndexError):
                continue
            if ms <= 0 or app.lower() in _IGNORE_APPS:
                continue
            with self.lock:
                dq = self.frames.get(pid)
                if dq is None:
                    dq = self.frames[pid] = collections.deque(maxlen=600)
                dq.append(ms)
                self.names[pid] = app
                self.last[pid] = time.monotonic()

    def read(self, pids: set[int]) -> tuple[float, float] | None:
        now = time.monotonic()
        with self.lock:
            live = [p for p, t in self.last.items() if now - t < 2]
            for p in [p for p in self.last if now - self.last[p] > 30]:   # limpa processos que já fecharam
                self.frames.pop(p, None), self.names.pop(p, None), self.last.pop(p, None)
            if not live:
                return None
            mine = [p for p in live if p in pids]
            pid = mine[0] if mine else max(live, key=lambda p: len(self.frames[p]))
            total, n = 0.0, 0
            for ms in reversed(self.frames[pid]):     # último ~1 s de fotogramas
                total += ms
                n += 1
                if total >= 1000:
                    break
        if not n or total <= 0:
            return None
        return 1000.0 * n / total, total / n

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None
        with self.lock:
            self.frames.clear()
            self.last.clear()


# ============================================================================================ medidor
class FpsMeter:
    """Chamar `set_game` quando o jogo muda e `read()` 1×/s. `read` devolve {"fps", "ft", "src"} ou None."""

    def __init__(self):
        self.pid = 0
        self.pids: set[int] = set()
        self.pm = _PresentMon() if IS_WIN else None
        self.src = ""          # de onde vieram os últimos FPS
        self._pids_at = 0.0

    def set_game(self, game) -> None:
        pid = getattr(game, "pid", 0) or 0
        if pid == self.pid:
            return
        self.pid, self.pids, self._pids_at = pid, {pid} if pid else set(), 0.0
        if self.pm is not None:
            if pid and presentmon_installed():
                self.pm.start()
            elif not pid:
                self.pm.stop()
        if not pid and not IS_WIN:
            prune_mangohud_logs()

    def _refresh_pids(self):
        """O jogo pode desenhar num processo-filho (lançadores): inclui os descendentes do processo detetado."""
        if not self.pid or time.monotonic() - self._pids_at < 5:
            return
        self._pids_at = time.monotonic()
        try:
            import psutil
            p = psutil.Process(self.pid)
            self.pids = {self.pid, *(c.pid for c in p.children(recursive=True))}
        except Exception:
            self.pids = {self.pid}

    def read(self) -> dict | None:
        r, src = None, ""
        if IS_WIN:
            self._refresh_pids()
            r, src = _read_rtss(self.pid), "RTSS"
            if r is None and self.pm is not None:
                if self.pid and presentmon_installed() and not self.pm.running() and not self.pm.error:
                    self.pm.start()
                r, src = self.pm.read(self.pids), "PresentMon"
        else:
            r, src = _read_mangohud(), "MangoHud"
        self.src = src if r else ""
        if r is None:
            return None
        return {"fps": round(r[0], 1), "ft": round(r[1], 2), "src": src}

    def error(self) -> str:
        return self.pm.error if self.pm is not None else ""

    def stop(self) -> None:
        if self.pm is not None:
            self.pm.stop()
        self.pid = 0
