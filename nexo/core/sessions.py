"""Histórico das sessões de jogo (na mesma base de dados SQLite do histórico dos sensores).

Cada sessão guarda: jogo, início/fim, temperaturas máximas da CPU/GPU e FPS (média, 1 % low e mínimo).
O «1 % low» é calculado a partir das amostras de FPS de 1 s (o percentil 1) — é uma aproximação do
valor que os programas de benchmark calculam com cada fotograma, mas chega para comparar sessões.

Também guarda, por segundo, o FPS e o fotograma mais lento (gráfico de frametimes e contagem de engasgos),
a carga média da CPU/GPU, a VRAM máxima e a energia gasta pela CPU+GPU (usadas pelo «O que devo atualizar?»
e pela página Energia)."""
from __future__ import annotations

import json
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
    cpu_load: float | None = None      # carga média durante a sessão (%)
    gpu_load: float | None = None
    vram_max: float | None = None      # % máxima da VRAM
    ram_max: float | None = None       # % máxima da RAM
    wh: float | None = None            # energia gasta pela CPU+GPU (Wh)
    stutters: int | None = None        # segundos com um fotograma muito mais lento que o normal
    timeline: list | None = None       # [[fps, fotograma mais lento ms], …] (reduzido; só em get())

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
    have = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
    for col, typ in _EXTRA_COLS:
        if col not in have:     # bases de dados de versões anteriores
            db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ}")
    return db


_EXTRA_COLS = (("cpu_load", "REAL"), ("gpu_load", "REAL"), ("vram_max", "REAL"), ("ram_max", "REAL"),
               ("wh", "REAL"), ("stutters", "INTEGER"), ("timeline", "TEXT"))
_COLS = "game, start, end, cpu_max, gpu_max, fps_avg, fps_low1, fps_min, id, cpu_load, gpu_load, vram_max, " \
        "ram_max, wh, stutters"
TIMELINE_POINTS = 1200     # pontos guardados por sessão (sessões longas são reduzidas)


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


def count_stutters(samples: list) -> int | None:
    """Segundos com um engasgo: o fotograma mais lento demorou ≥ 2,5× o normal (e pelo menos +20 ms).
    `samples` = [[fps, fotograma mais lento ms], …]. None quando não há fotogramas mais lentos medidos."""
    good = [(f, w) for f, w in samples if f and f > 0]
    worst = [w for _f, w in good if w]
    if len(good) < 10 or not worst:
        return None
    normal = 1000.0 / percentile([f for f, _w in good], 50)
    lim = max(2.5 * normal, normal + 20)
    return sum(1 for w in worst if w >= lim)


def compact_timeline(samples: list, points: int = TIMELINE_POINTS) -> list:
    """Reduz a linha do tempo a `points` pontos sem esconder os engasgos: cada ponto guarda o FPS mais
    baixo e o fotograma mais lento do bloco."""
    samples = [[f, w] for f, w in samples if f]
    if len(samples) <= points:
        return [[round(f, 1), round(w, 1) if w else None] for f, w in samples]
    step = len(samples) / points
    out = []
    for i in range(points):
        blk = samples[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]
        ws = [w for _f, w in blk if w]
        out.append([round(min(f for f, _w in blk), 1), round(max(ws), 1) if ws else None])
    return out


def add(sess: Session, path: Path | str | None = None) -> bool:
    if sess.end - sess.start < MIN_SECONDS or not sess.game:
        return False
    try:
        with _lock:
            db = _conn(path)
            with db:
                tl = json.dumps(compact_timeline(sess.timeline), separators=(",", ":")) if sess.timeline else None
                db.execute("INSERT INTO sessions (game, start, end, cpu_max, gpu_max, fps_avg, fps_low1, fps_min, "
                           "cpu_load, gpu_load, vram_max, ram_max, wh, stutters, timeline) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (sess.game, sess.start, sess.end, sess.cpu_max, sess.gpu_max, sess.fps_avg,
                            sess.fps_low1, sess.fps_min, sess.cpu_load, sess.gpu_load, sess.vram_max, sess.ram_max,
                            sess.wh, sess.stutters, tl))
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
            q = f"SELECT {_COLS} FROM sessions"
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


def since(ts: float, path: Path | str | None = None) -> list[Session]:
    """Sessões que começaram depois de `ts` (mais antigas primeiro)."""
    try:
        with _lock:
            db = _conn(path)
            rows = db.execute(f"SELECT {_COLS} FROM sessions WHERE start >= ? ORDER BY start", (ts,)).fetchall()
            db.close()
    except sqlite3.Error:
        log.warning("Não foi possível ler as sessões", exc_info=True)
        return []
    return [Session(*r) for r in rows]


def get(session_id: int, path: Path | str | None = None) -> Session | None:
    """Uma sessão com a linha do tempo (FPS e fotograma mais lento)."""
    try:
        with _lock:
            db = _conn(path)
            r = db.execute(f"SELECT {_COLS}, timeline FROM sessions WHERE id = ?", (session_id,)).fetchone()
            db.close()
    except sqlite3.Error:
        log.warning("Não foi possível ler a sessão %s", session_id, exc_info=True)
        return None
    if not r:
        return None
    sess = Session(*r[:-1])
    try:
        sess.timeline = json.loads(r[-1]) if r[-1] else None
    except ValueError:
        sess.timeline = None
    return sess


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
