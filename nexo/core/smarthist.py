"""Histórico dos dados S.M.A.R.T. e previsão do fim de vida dos discos.

Cada leitura da página «Saúde dos discos» (ou da tarefa agendada) guarda, uma vez por dia e por disco, os
valores que contam para a fiabilidade: vida restante dos SSD, setores realocados/pendentes, erros de
integridade, dados escritos e horas ligado. Com isso:
  • setores realocados/pendentes ou erros a SUBIR — o sinal mais conhecido de um disco a começar a falhar
    (um valor alto e parado é muito menos preocupante do que um valor pequeno a crescer);
  • quando o SSD chega aos 0 % de vida, ao ritmo de desgaste atual (regressão linear, precisa de pelo menos
    30 dias e de 1 ponto de desgaste);
  • quanto escreve por dia (o que mais gasta um SSD)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .util import load_json, save_json

FILE = "smart_historico.json"
KEEP_DAYS = 3 * 365
MIN_SPAN_DAYS = 30
FIELDS = ("life", "realloc", "pending", "media_errors", "written", "hours")


def disk_key(d: dict) -> str:
    return (d.get("serial") or "").strip() or f"{d.get('model', '')}|{d.get('dev', '')}"


def _load() -> dict:
    data = load_json(FILE, {})
    return data if isinstance(data, dict) else {}


def record(disks: list[dict], now: float | None = None, data: dict | None = None, save: bool = True) -> dict:
    """Junta a leitura de hoje (substitui a de hoje, se já houver). Devolve o histórico."""
    now = time.time() if now is None else now
    data = _load() if data is None else data
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    cutoff = time.strftime("%Y-%m-%d", time.localtime(now - KEEP_DAYS * 86400))
    for d in disks:
        if d.get("error") and not d.get("attrs"):
            continue
        row = {"day": day, **{f: d.get(f) for f in FIELDS}}
        if all(row[f] is None for f in FIELDS):
            continue
        rows = [r for r in data.get(disk_key(d), []) if r.get("day") != day and r.get("day", "") >= cutoff]
        rows.append(row)
        rows.sort(key=lambda r: r["day"])
        data[disk_key(d)] = rows
    if save:
        save_json(FILE, data)
    return data


def _ts(day: str) -> float:
    return time.mktime(time.strptime(day, "%Y-%m-%d"))


@dataclass
class Trend:
    days: int = 0                          # dias de histórico deste disco
    notes: list[tuple[str, str]] = field(default_factory=list)   # (ok|warn|bad, texto)
    life_eta_days: float | None = None     # dias até 0 % de vida, ao ritmo atual
    life_per_year: float | None = None     # pontos de vida gastos por ano
    written_per_day: float | None = None   # bytes por dia
    series: dict[str, list[tuple[float, float]]] = field(default_factory=dict)  # campo → [(ts, valor)]


def _slope(pts: list[tuple[float, float]]) -> float | None:
    """Declive (unidades por segundo) pela regressão linear."""
    n = len(pts)
    if n < 2:
        return None
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    den = sum((x - mx) ** 2 for x, _ in pts)
    if not den:
        return None
    return sum((x - mx) * (y - my) for x, y in pts) / den


def trend(rows: list[dict]) -> Trend:
    t = Trend()
    if not rows:
        return t
    first, last = rows[0], rows[-1]
    t.days = int(round((_ts(last["day"]) - _ts(first["day"])) / 86400))
    for f in FIELDS:
        pts = [(_ts(r["day"]), float(r[f])) for r in rows if r.get(f) is not None]
        if pts:
            t.series[f] = pts

    # setores e erros a subir
    names = {"realloc": "setores realocados", "pending": "setores pendentes",
             "media_errors": "erros de integridade dos dados"}
    for f, what in names.items():
        pts = t.series.get(f)
        if not pts or len(pts) < 2:
            continue
        start, end = pts[0][1], pts[-1][1]
        if end > start:
            span = max(1, round((pts[-1][0] - pts[0][0]) / 86400))
            recent = [v for ts, v in pts if ts >= pts[-1][0] - 30 * 86400]
            growing = len(recent) >= 2 and recent[-1] > recent[0]
            kind = "bad" if growing and (end - start >= 10 or f == "pending") else "warn"
            if growing:
                t.notes.append((kind, f"Os {what} subiram de {start:.0f} para {end:.0f} em {span} dias — e "
                                      "continuam a subir. Faça já uma cópia dos dados importantes."))
            else:
                t.notes.append((kind, f"Os {what} subiram de {start:.0f} para {end:.0f} em {span} dias. Vigie: se "
                                      "voltarem a subir, o disco está a degradar-se."))

    # vida dos SSD
    life = t.series.get("life")
    if life and len(life) >= 2 and (life[-1][0] - life[0][0]) >= MIN_SPAN_DAYS * 86400 \
            and life[0][1] - life[-1][1] >= 1:
        sl = _slope(life)
        if sl is not None and sl < 0:
            per_day = -sl * 86400
            t.life_per_year = per_day * 365
            t.life_eta_days = life[-1][1] / per_day if per_day else None
            if t.life_eta_days is not None:
                years = t.life_eta_days / 365
                if years < 1:
                    t.notes.append(("bad", f"Ao ritmo atual, o SSD chega ao fim da vida útil daqui a ~"
                                           f"{max(1, round(t.life_eta_days / 30))} meses. Planeie a substituição."))
                elif years < 3:
                    t.notes.append(("warn", f"Ao ritmo atual, o SSD dura mais ~{years:.1f} anos "
                                            f"(gasta {t.life_per_year:.1f} % de vida por ano)."))
                else:
                    t.notes.append(("ok", f"Desgaste lento: ao ritmo atual dura mais de {min(years, 30):.0f} anos "
                                          f"({t.life_per_year:.1f} % por ano)."))

    # escrita por dia
    wr = t.series.get("written")
    if wr and len(wr) >= 2 and wr[-1][0] - wr[0][0] >= 7 * 86400 and wr[-1][1] >= wr[0][1]:
        t.written_per_day = (wr[-1][1] - wr[0][1]) / ((wr[-1][0] - wr[0][0]) / 86400)
    return t


def for_disk(d: dict, data: dict | None = None) -> Trend:
    data = _load() if data is None else data
    return trend(data.get(disk_key(d), []))
