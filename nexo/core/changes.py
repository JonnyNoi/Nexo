"""Antes/depois: o que mudou no PC entre dois benchmarks e quanto isso valeu.

Os sítios do Nexo que mexem no sistema (ajustes de otimização, atualizações, debloat, arranque, limpeza)
chamam mark(); cada resultado de benchmark é comparado com o anterior do MESMO teste (modo, qualidade e
hardware) e com as mudanças feitas entretanto — assim vê-se se um ajuste ajudou de facto ou se foi só
placebo. Diferenças abaixo de NOISE_PCT são variação normal entre execuções."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .util import _save_lock, load_json, save_json

MARKS = "alteracoes.json"
NOISE_PCT = 3.0


def mark(kind: str, text: str, now: float | None = None) -> None:
    """kind: ajuste | atualizacao | debloat | arranque | limpeza | driver"""
    now = time.time() if now is None else now
    with _save_lock:
        data = load_json(MARKS, [])
        if not isinstance(data, list):
            data = []
        # o mesmo texto várias vezes seguidas (ex.: ligar/desligar) só conta uma vez por minuto
        if data and data[-1].get("text") == text and now - data[-1].get("when", 0) < 60:
            data[-1]["when"] = now
        else:
            data.append({"when": now, "kind": kind, "text": text})
        save_json(MARKS, data[-300:])


def marks_between(t0: float, t1: float, data: list | None = None) -> list[dict]:
    data = load_json(MARKS, []) if data is None else data
    return [m for m in data if isinstance(m, dict) and t0 < m.get("when", 0) <= t1]


def _ts(entry: dict) -> float:
    if entry.get("ts"):
        return float(entry["ts"])
    try:
        return time.mktime(time.strptime(entry.get("date", ""), "%Y-%m-%d %H:%M"))
    except ValueError:
        return 0.0


def same_test(a: dict, b: dict) -> bool:
    return (a.get("mode"), a.get("quality"), a.get("cpu")) == (b.get("mode"), b.get("quality"), b.get("cpu"))


@dataclass
class Comparison:
    prev: dict
    delta_pct: float
    changes: list[dict]

    @property
    def verdict(self) -> str:
        if abs(self.delta_pct) < NOISE_PCT:
            return "igual"
        return "melhor" if self.delta_pct > 0 else "pior"

    def text(self) -> str:
        sign = "+" if self.delta_pct >= 0 else "−"
        base = f"{sign}{abs(self.delta_pct):.1f} % vs {self.prev.get('date', '')}"
        if self.verdict == "igual":
            base += " (variação normal)"
        if self.changes:
            base += " · desde então: " + summarize(self.changes)
        return base


def compare(history: list[dict], entry: dict) -> Comparison | None:
    """Compara `entry` com o resultado anterior do mesmo teste em `history` (que pode já conter entry)."""
    t = _ts(entry)
    prev = None
    for h in history:   # ordem cronológica: fica o último resultado do mesmo teste antes de entry
        if h is entry:
            break
        if same_test(h, entry) and _ts(h) <= t:
            prev = h
    if prev is None or not prev.get("score"):
        return None
    delta = (float(entry["score"]) - float(prev["score"])) / float(prev["score"]) * 100
    return Comparison(prev, delta, marks_between(_ts(prev), t))


_KIND_TXT = {"ajuste": ("ajuste", "ajustes"), "atualizacao": ("atualização", "atualizações"),
             "debloat": ("remoção (debloat)", "remoções (debloat)"), "arranque": ("mudança no arranque",
             "mudanças no arranque"), "limpeza": ("limpeza", "limpezas"), "driver": ("driver", "drivers")}


def summarize(changes: list[dict]) -> str:
    counts: dict[str, int] = {}
    for c in changes:
        counts[c.get("kind", "")] = counts.get(c.get("kind", ""), 0) + 1
    parts = []
    for k, n in counts.items():
        one, many = _KIND_TXT.get(k, (k, k))
        parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts)
