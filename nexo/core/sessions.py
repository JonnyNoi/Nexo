"""Histórico das sessões de jogo (na mesma base de dados SQLite do histórico dos sensores).

Cada sessão guarda: jogo, início/fim, temperaturas máximas da CPU/GPU e FPS (média, 1 % low e mínimo).
O «1 % low» é calculado a partir das amostras de FPS de 1 s (o percentil 1) — é uma aproximação do
valor que os programas de benchmark calculam com cada fotograma, mas chega para comparar sessões."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .history import db_path

KEEP = 2000                # sessões guardadas no máximo (as mais antigas saem)
MIN_SECONDS = 60           # sessões mais curtas não contam (arranques falhados, launchers)
log = logging.getLogger("nexo.sessions")
_lock = threading.Lock()


@dataclass
class Session:
    game: str
    start: float
    end: float
    cpu_max: float | None = None
    gpu_max: float | None = None
    fps_avg: float | None = None
    fps_low1: float | None = None
    fps_min: float | None = None
    id: int | None = None

    @property
    def minutes(self) -> float:
        return max(0.0, (self.end - self.start) / 60)


@dataclass
class GameSummary:
    game: str
    sessions: int
    minutes: float
    last: float
    fps_avg: float | None
    cpu_max: float | None
    gpu_max: float | None


def _conn(path: Path | str | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(str(path or db_path()), timeout=5)
    db.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
        cpu_max REAL, gpu_max REAL, fps_avg REAL, fps_low1 REAL, fps_min REAL)""")
    db.execute("CREATE INDEX IF NOT EXISTS sessions_game ON sessions (game)")
    return db


def percentile(values: list[float], pct: float) -> float | None:
    """Percentil com interpolação linear (pct entre 0 e 100)."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def fps_stats(samples: list[float]) -> tuple[float | None, float | None, float | None]:
    """(média, 1 % low, mínimo) das amostras; None com menos de 10 amostras (não é representativo)."""
    s = [x for x in samples if x and x > 0]
    if len(s) < 10:
        return None, None, None
    return sum(s) / len(s), percentile(s, 1), min(s)


def add(sess: Session, path: Path | str | None = None) -> bool:
    if sess.end - sess.start < MIN_SECONDS or not sess.game:
        return False
    try:
        with _lock:
            db = _conn(path)
            with db:
                db.execute("INSERT INTO sessions (game, start, end, cpu_max, gpu_max, fps_avg, fps_low1, fps_min) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (sess.game, sess.start, sess.end, sess.cpu_max, sess.gpu_max, sess.fps_avg,
                            sess.fps_low1, sess.fps_min))
                db.execute("DELETE FROM sessions WHERE id NOT IN (SELECT id FROM sessions ORDER BY start DESC LIMIT ?)",
                           (KEEP,))
            db.close()
        return True
    except sqlite3.Error:
        log.warning("Não foi possível guardar a sessão de %s", sess.game, exc_info=True)
        return False


def recent(limit: int = 200, game: str | None = None, path: Path | str | None = None) -> list[Session]:
    try:
        with _lock:
            db = _conn(path)
            q = "SELECT game, start, end, cpu_max, gpu_max, fps_avg, fps_low1, fps_min, id FROM sessions"
            args: tuple = ()
            if game:
                q += " WHERE game = ?"
                args = (game,)
            rows = db.execute(q + " ORDER BY start DESC LIMIT ?", (*args, limit)).fetchall()
            db.close()
    except sqlite3.Error:
        log.warning("Não foi possível ler as sessões", exc_info=True)
        return []
    return [Session(*r) for r in rows]


def summary(days: float | None = None, path: Path | str | None = None) -> list[GameSummary]:
    """Totais por jogo (mais jogado primeiro). days=None → desde sempre."""
    since = time.time() - days * 86400 if days else 0
    try:
        with _lock:
            db = _conn(path)
            rows = db.execute(
                "SELECT game, COUNT(*), SUM(end - start) / 60.0, MAX(end), "
                "SUM(fps_avg * (end - start)) / NULLIF(SUM(CASE WHEN fps_avg IS NOT NULL THEN end - start END), 0), "
                "MAX(cpu_max), MAX(gpu_max) FROM sessions WHERE start >= ? GROUP BY game "
                "ORDER BY SUM(end - start) DESC", (since,)).fetchall()
            db.close()
    except sqlite3.Error:
        log.warning("Não foi possível ler o resumo das sessões", exc_info=True)
        return []
    return [GameSummary(*r) for r in rows]


def delete(session_id: int, path: Path | str | None = None) -> None:
    with _lock:
        db = _conn(path)
        with db:
            db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        db.close()


def clear(path: Path | str | None = None) -> None:
    with _lock:
        db = _conn(path)
        with db:
            db.execute("DELETE FROM sessions")
        db.close()
