"""Histórico dos sensores guardado em disco (SQLite).

O SensorHub lê 1×/s; aqui junta-se cada minuto numa linha (média e máximo de cada valor) e
guarda-se 7 dias (~10 000 linhas, < 2 MB). Assim dá para ver "a que horas aqueceu" ou se as
temperaturas subiram desde a semana passada (pó)."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from .util import config_dir

KEEP_DAYS = 7
DB_NAME = "historico.db"
log = logging.getLogger("nexo.history")


def db_path() -> Path:
    return config_dir() / DB_NAME


class History:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else db_path()
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self._minute: int | None = None
        self._acc: dict[str, list[float]] = {}      # chave → [soma, n, máximo]
        self._last_prune = 0.0

    # ------------------------------------------------------------------ ligação
    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5)
            self._db.execute("CREATE TABLE IF NOT EXISTS minute (ts INTEGER PRIMARY KEY, data TEXT NOT NULL)")
            self._db.commit()
        return self._db

    def close(self) -> None:
        self.flush()
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # ------------------------------------------------------------------ escrita
    def add(self, snap: dict, now: float | None = None) -> None:
        """Junta uma leitura (valores None são ignorados). Ao mudar de minuto grava o anterior."""
        now = time.time() if now is None else now
        m = int(now // 60)
        if self._minute is not None and m != self._minute:
            self.flush()
        self._minute = m
        for k, v in snap.items():
            if v is None:
                continue
            a = self._acc.get(k)
            if a is None:
                self._acc[k] = [v, 1, v]
            else:
                a[0] += v
                a[1] += 1
                if v > a[2]:
                    a[2] = v

    def flush(self) -> None:
        if self._minute is None or not self._acc:
            return
        row = {k: [round(s / n, 2), round(mx, 2)] for k, (s, n, mx) in self._acc.items()}
        ts = self._minute * 60
        self._acc = {}
        try:
            with self._lock:
                db = self._conn()
                db.execute("INSERT OR REPLACE INTO minute (ts, data) VALUES (?, ?)", (ts, json.dumps(row)))
                if time.time() - self._last_prune > 3600:
                    self._last_prune = time.time()
                    db.execute("DELETE FROM minute WHERE ts < ?", (ts - KEEP_DAYS * 86400,))
                db.commit()
        except sqlite3.Error:
            log.exception("Não foi possível gravar o histórico dos sensores")

    # ------------------------------------------------------------------ leitura
    def query(self, keys: list[str], since: float, until: float | None = None,
              bucket: int = 60) -> dict[str, list[tuple[float, float, float]]]:
        """{chave: [(ts, média, máximo)]} entre since e until, agrupado em blocos de `bucket` s."""
        until = time.time() if until is None else until
        try:
            with self._lock:
                rows = self._conn().execute("SELECT ts, data FROM minute WHERE ts >= ? AND ts <= ? ORDER BY ts",
                                            (int(since), int(until))).fetchall()
        except sqlite3.Error:
            log.exception("Não foi possível ler o histórico dos sensores")
            rows = []
        out: dict[str, list] = {k: [] for k in keys}
        acc: dict[str, list[float]] = {}
        cur = None

        def emit():
            for k, (s, n, mx) in acc.items():
                out[k].append((cur * bucket + bucket / 2, s / n, mx))
        for ts, data in rows:
            b = int(ts // bucket)
            if cur is not None and b != cur:
                emit()
                acc = {}
            cur = b
            try:
                d = json.loads(data)
            except ValueError:
                continue
            for k in keys:
                v = d.get(k)
                if not v:
                    continue
                a = acc.get(k)
                if a is None:
                    acc[k] = [v[0], 1, v[1]]
                else:
                    a[0] += v[0]
                    a[1] += 1
                    a[2] = max(a[2], v[1])
        if cur is not None:
            emit()
        return out

    def first_ts(self) -> float | None:
        try:
            with self._lock:
                r = self._conn().execute("SELECT MIN(ts) FROM minute").fetchone()
            return r[0] if r and r[0] is not None else None
        except sqlite3.Error:
            return None

    def clear(self) -> None:
        self._acc = {}
        with self._lock:
            db = self._conn()
            db.execute("DELETE FROM minute")
            db.commit()
            db.execute("VACUUM")
