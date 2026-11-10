"""Que programas estão a usar a internet (e, no Linux, quanto).

Linux: `ss -tinp` dá, para cada ligação TCP dos seus programas, os bytes enviados/recebidos (sem
root). Entre duas leituras a diferença dá a velocidade por programa. O tráfego UDP (alguns jogos,
chamadas de voz, QUIC/HTTP3 dos navegadores) não tem contadores por ligação — esses programas aparecem
com as ligações mas sem velocidade.
Windows: o sistema não dá bytes por programa sem ferramentas extra; mostra-se o número de ligações e
para onde (psutil)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import psutil

from .util import IS_LINUX, run, which

_USER = re.compile(r'\("([^"]+)",pid=(\d+),fd=\d+\)')
_BYTES = re.compile(r"bytes_(sent|received):(\d+)")
_LOCAL_NETS = ("127.", "::1", "10.", "192.168.", "169.254.", "fe80:", "fc", "fd")


@dataclass
class ProcNet:
    pid: int
    name: str
    conns: int = 0
    remotes: set[str] = field(default_factory=set)
    down: float | None = None      # bytes/s (None = desconhecido)
    up: float | None = None
    total_down: int = 0            # desde que a medição começou
    total_up: int = 0


def _is_local(ip: str) -> bool:
    if ip.startswith("172."):
        try:
            return 16 <= int(ip.split(".")[1]) <= 31
        except (IndexError, ValueError):
            return False
    return ip.startswith(_LOCAL_NETS)


def parse_ss(out: str) -> dict[tuple[int, str], tuple[str, int, str, int, int]]:
    """{(pid, ligação): (nome, pid, remoto, enviados, recebidos)} a partir de `ss -tinpH`."""
    res = {}
    cur = None
    for line in out.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            cols = line.split()
            users = _USER.findall(line)
            if len(cols) >= 4 and users:
                local, peer = cols[2], cols[3]
                cur = (users, local, peer)
            else:
                cur = None
            continue
        if cur is None:
            continue
        users, local, peer = cur
        b = dict(_BYTES.findall(line))
        sent, recv = int(b.get("sent", 0)), int(b.get("received", 0))
        name, pid = users[0][0], int(users[0][1])
        host = peer.rsplit(":", 1)[0].strip("[]")
        res[(pid, f"{local}>{peer}")] = (name, pid, host, sent, recv)
        cur = None
    return res


class NetProcMonitor:
    """Chamar sample() periodicamente (ex.: a cada 2 s)."""

    def __init__(self):
        self._prev: dict[tuple[int, str], tuple[int, int]] = {}
        self._prev_t: float | None = None
        self._totals: dict[int, list[int]] = {}
        self.has_rates = IS_LINUX and bool(which("ss"))

    def sample(self) -> list[ProcNet]:
        procs: dict[int, ProcNet] = {}
        now = time.monotonic()
        if self.has_rates:
            code, out = run(["ss", "-tinpH", "state", "established"], timeout=5)
            socks = parse_ss(out) if code == 0 else {}
            dt = (now - self._prev_t) if self._prev_t else None
            cur: dict[tuple[int, str], tuple[int, int]] = {}
            for key, (name, pid, host, sent, recv) in socks.items():
                if _is_local(host):
                    continue
                p = procs.get(pid) or procs.setdefault(pid, ProcNet(pid, name, down=0.0, up=0.0))
                p.conns += 1
                p.remotes.add(host)
                cur[key] = (sent, recv)
                old = self._prev.get(key)
                if old is not None:
                    ds, dr = max(0, sent - old[0]), max(0, recv - old[1])
                    tot = self._totals.setdefault(pid, [0, 0])
                    tot[0] += dr
                    tot[1] += ds
                    if dt:
                        p.down += dr / dt
                        p.up += ds / dt
            self._prev, self._prev_t = cur, now
            if dt is None:
                for p in procs.values():
                    p.down = p.up = None
        # UDP/sem contadores (e tudo no Windows): ligações por processo
        try:
            conns = psutil.net_connections("inet")
        except (psutil.AccessDenied, OSError):
            conns = []
        for c in conns:
            if not c.pid or not c.raddr or _is_local(c.raddr.ip):
                continue
            if self.has_rates and c.type == 1:     # SOCK_STREAM: já contado pelo ss
                continue
            p = procs.get(c.pid)
            if p is None:
                try:
                    name = psutil.Process(c.pid).name()
                except psutil.Error:
                    continue
                p = procs[c.pid] = ProcNet(c.pid, name)
            p.conns += 1
            p.remotes.add(c.raddr.ip)
        for pid, p in procs.items():
            t = self._totals.get(pid)
            if t:
                p.total_down, p.total_up = t
        return sorted(procs.values(), key=lambda p: (-(p.down or 0) - (p.up or 0), -p.conns, p.name.lower()))
