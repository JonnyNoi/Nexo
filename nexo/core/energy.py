"""Consumo de energia e quanto custa.

O SensorHub lê o consumo da CPU e da GPU 1×/s; aqui soma-se a energia (Wh) de cada dia numa tabela da
base de dados do histórico (fica guardada 400 dias, ~30 KB). O resto do PC (placa-mãe, discos, ventoinhas,
perdas da fonte) não tem sensor: usa-se uma estimativa em watts que o utilizador pode ajustar e que é
somada só na altura de mostrar — mudar a estimativa ou o preço do kWh refaz as contas do passado.

Só conta enquanto o Nexo está aberto (com a janela fechada na bandeja também conta)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .history import db_path
from .util import get_setting

KEEP_DAYS = 400
FLUSH_EVERY = 60          # segundos entre gravações
MAX_W = 2000              # leituras acima disto são erros do sensor
log = logging.getLogger("nexo.energy")


@dataclass
class Day:
    day: str               # AAAA-MM-DD (hora local)
    cpu_wh: float = 0.0
    gpu_wh: float = 0.0
    seconds: int = 0       # tempo com o Nexo aberto
    game_wh: float = 0.0   # CPU+GPU enquanto havia um jogo aberto
    game_seconds: int = 0

    def total_wh(self, rest_w: float) -> float:
        return self.cpu_wh + self.gpu_wh + rest_w * self.seconds / 3600

    def game_total_wh(self, rest_w: float) -> float:
        return self.game_wh + rest_w * self.game_seconds / 3600


def price() -> float:
    """Preço do kWh (na moeda escolhida)."""
    try:
        return max(0.0, float(get_setting("energy_price", 0.20)))
    except (TypeError, ValueError):
        return 0.20


def rest_w() -> float:
    """Estimativa do consumo do resto do PC (W)."""
    try:
        return max(0.0, float(get_setting("energy_rest_w", 50)))
    except (TypeError, ValueError):
        return 50.0


def currency() -> str:
    return str(get_setting("energy_currency", "€") or "€")


def cost(wh: float, kwh_price: float | None = None) -> float:
    return wh / 1000 * (price() if kwh_price is None else kwh_price)


def fmt_money(v: float) -> str:
    c = currency()
    txt = f"{v:.0f}" if v >= 100 else f"{v:.2f}" if v >= 0.1 or v == 0 else f"{v:.3f}" if v >= 0.01 else f"{v:.4f}"
    txt = txt.replace(".", ",")
    return f"{txt} {c}" if c in ("€", "R$", "kr", "zł") else f"{c}{txt}"


def fmt_energy(wh: float) -> str:
    if wh >= 1000:
        return f"{wh / 1000:.1f} kWh".replace(".", ",")
    return f"{wh:.0f} Wh"


def _conn(path: Path | str | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(str(path or db_path()), timeout=5, check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS energy (
        day TEXT PRIMARY KEY, cpu_wh REAL NOT NULL DEFAULT 0, gpu_wh REAL NOT NULL DEFAULT 0,
        seconds INTEGER NOT NULL DEFAULT 0, game_wh REAL NOT NULL DEFAULT 0,
        game_seconds INTEGER NOT NULL DEFAULT 0)""")
    return db


class Meter:
    """Chamar `add` 1×/s (thread da interface); grava a cada minuto e em `close`."""

    def __init__(self, path: Path | str | None = None):
        self.path = path
        self._lock = threading.Lock()
        self._acc: dict[str, list[float]] = {}     # dia → [cpu_wh, gpu_wh, s, game_wh, game_s]
        self._n = 0
        self._last: float | None = None

    def add(self, cpu_w: float | None, gpu_w: float | None, gaming: bool = False, now: float | None = None) -> None:
        now = time.time() if now is None else now
        dt = 1.0 if self._last is None else now - self._last
        self._last = now
        if not 0 < dt <= 5:        # suspensão / relógio mudado: não inventar energia
            return
        cpu = cpu_w if cpu_w is not None and 0 <= cpu_w < MAX_W else 0.0
        gpu = gpu_w if gpu_w is not None and 0 <= gpu_w < MAX_W else 0.0
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        a = self._acc.setdefault(day, [0.0, 0.0, 0.0, 0.0, 0.0])
        a[0] += cpu * dt / 3600
        a[1] += gpu * dt / 3600
        a[2] += dt
        if gaming:
            a[3] += (cpu + gpu) * dt / 3600
            a[4] += dt
        self._n += 1
        if self._n >= FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        acc, self._acc, self._n = self._acc, {}, 0
        if not acc:
            return
        try:
            with self._lock:
                db = _conn(self.path)
                with db:
                    for day, (c, g, s, gw, gs) in acc.items():
                        db.execute("INSERT INTO energy (day, cpu_wh, gpu_wh, seconds, game_wh, game_seconds) "
                                   "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET "
                                   "cpu_wh = cpu_wh + excluded.cpu_wh, gpu_wh = gpu_wh + excluded.gpu_wh, "
                                   "seconds = seconds + excluded.seconds, game_wh = game_wh + excluded.game_wh, "
                                   "game_seconds = game_seconds + excluded.game_seconds",
                                   (day, c, g, int(round(s)), gw, int(round(gs))))
                    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - KEEP_DAYS * 86400))
                    db.execute("DELETE FROM energy WHERE day < ?", (cutoff,))
                db.close()
        except sqlite3.Error:
            log.warning("Não foi possível gravar o consumo de energia", exc_info=True)

    def pending(self) -> dict[str, list[float]]:
        """O que ainda não foi gravado (para mostrar o dia de hoje ao segundo)."""
        return {k: list(v) for k, v in self._acc.items()}

    def close(self) -> None:
        self.flush()


def days(n: int = 30, path: Path | str | None = None, pending: dict | None = None,
         now: float | None = None) -> list[Day]:
    """Últimos n dias (incluindo hoje), do mais antigo para o mais recente; dias sem dados ficam a zero."""
    now = time.time() if now is None else now
    keys = [time.strftime("%Y-%m-%d", time.localtime(now - i * 86400)) for i in range(n - 1, -1, -1)]
    out = {k: Day(k) for k in keys}
    try:
        db = _conn(path)
        rows = db.execute("SELECT day, cpu_wh, gpu_wh, seconds, game_wh, game_seconds FROM energy WHERE day >= ?",
                          (keys[0],)).fetchall()
        db.close()
    except sqlite3.Error:
        log.warning("Não foi possível ler o consumo de energia", exc_info=True)
        rows = []
    for r in rows:
        if r[0] in out:
            out[r[0]] = Day(*r)
    for k, (c, g, s, gw, gs) in (pending or {}).items():
        d = out.get(k)
        if d is not None:
            d.cpu_wh += c
            d.gpu_wh += g
            d.seconds += int(s)
            d.game_wh += gw
            d.game_seconds += int(gs)
    return [out[k] for k in keys]


@dataclass
class Totals:
    wh: float
    cpu_wh: float
    gpu_wh: float
    rest_wh: float
    hours: float
    game_wh: float
    days_with_data: int

    @property
    def avg_w(self) -> float:
        return self.wh / self.hours if self.hours else 0.0


def totals(rows: list[Day], rest: float | None = None) -> Totals:
    rest = rest_w() if rest is None else rest
    secs = sum(d.seconds for d in rows)
    cpu = sum(d.cpu_wh for d in rows)
    gpu = sum(d.gpu_wh for d in rows)
    rest_wh = rest * secs / 3600
    return Totals(cpu + gpu + rest_wh, cpu, gpu, rest_wh, secs / 3600,
                  sum(d.game_total_wh(rest) for d in rows), sum(1 for d in rows if d.seconds))


def month_estimate(rows: list[Day], rest: float | None = None) -> float | None:
    """Estimativa do custo de um mês (30 dias) a partir da média dos dias com dados."""
    t = totals(rows, rest)
    if t.days_with_data < 1:
        return None
    return cost(t.wh / t.days_with_data * 30)


def per_game(days_back: int = 30, rest: float | None = None, path: Path | str | None = None) -> list[tuple]:
    """[(jogo, horas, Wh, custo)] — energia das sessões de jogo (CPU+GPU medidos + resto do PC)."""
    from . import sessions
    rest = rest_w() if rest is None else rest
    acc: dict[str, list[float]] = {}
    for s in sessions.since(time.time() - days_back * 86400, path=path):
        if s.wh is None:
            continue
        a = acc.setdefault(s.game, [0.0, 0.0])
        a[0] += s.minutes / 60
        a[1] += s.wh + rest * s.minutes / 60
    rows = [(g, h, wh, cost(wh)) for g, (h, wh) in acc.items()]
    return sorted(rows, key=lambda r: -r[2])
