"""Relatório da semana: como esteve o PC nos últimos 7 dias, comparado com a semana anterior.

Não recolhe nada de novo — junta o que o Nexo já guarda: pontuação da Saúde do PC (uma por dia), fiabilidade,
throttling, tempo de arranque, sessões de jogo, alertas e o que foi alterado (changes.mark). Gerado uma vez
por semana (Definições → Alertas) e guardado em relatorio_semanal.json; também `nexo --relatorio-semanal`."""
from __future__ import annotations

import html
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .util import APP_NAME, _save_lock, get_setting, load_json, save_json, set_setting

SCORES = "saude_historico.json"
REPORT = "relatorio_semanal.json"
WEEK = 7 * 86400


def _n(x: float) -> str:
    """1 casa decimal com vírgula (12,5)."""
    return f"{x:.1f}".replace(".", ",")


@dataclass
class Line:
    kind: str        # ok | info | warn | bad
    text: str
    page: str = ""


@dataclass
class Report:
    start: float
    end: float
    score: int | None = None
    score_prev: int | None = None
    lines: list[Line] = field(default_factory=list)

    @property
    def headline(self) -> str:
        if self.score is None:
            return "Relatório da semana"
        s = f"Saúde do PC: {self.score}/100"
        if self.score_prev is not None and self.score != self.score_prev:
            d = self.score - self.score_prev
            s += f" ({'+' if d > 0 else '−'}{abs(d)} vs semana anterior)"
        return s

    def summary(self) -> str:
        """Uma linha para a notificação."""
        worst = [ln.text for ln in self.lines if ln.kind in ("bad", "warn")][:2]
        return self.headline + (" · " + " · ".join(worst) if worst else " · semana sem problemas.")

    def as_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Report:
        return Report(float(d.get("start", 0)), float(d.get("end", 0)), d.get("score"), d.get("score_prev"),
                      [Line(**x) for x in d.get("lines") or [] if isinstance(x, dict) and "text" in x])


# --------------------------------------------------------------------------- pontuação diária
def record_score(score: int, now: float | None = None) -> None:
    """Guarda a pontuação do dia (a pior do dia — é a que mostra os problemas). Barato: só escreve quando muda."""
    now = time.time() if now is None else now
    day = date.fromtimestamp(now).isoformat()
    data = load_json(SCORES, {})
    if not isinstance(data, dict):
        data = {}
    old = data.get(day)
    if isinstance(old, int) and old <= score:
        return
    with _save_lock:
        data[day] = int(score)
        keep = sorted(data)[-120:]
        save_json(SCORES, {k: data[k] for k in keep})


def _avg_score(t0: float, t1: float, data: dict | None = None) -> int | None:
    data = load_json(SCORES, {}) if data is None else data
    d0, d1 = date.fromtimestamp(t0), date.fromtimestamp(t1)
    vals = [v for k, v in (data or {}).items() if isinstance(v, (int, float)) and d0 < date.fromisoformat(k) <= d1]
    return round(sum(vals) / len(vals)) if vals else None


# --------------------------------------------------------------------------- relatório
def build(now: float | None = None) -> Report:
    now = time.time() if now is None else now
    t0, tp = now - WEEK, now - 2 * WEEK
    rep = Report(t0, now, _avg_score(t0, now), _avg_score(tp, t0))
    L = rep.lines
    for part in (_stability, _throttle, _boot, _games, _alerts, _changes, _updates):
        try:
            L.extend(part(now, t0, tp))
        except Exception:  # noqa: BLE001 — uma fonte estragada não pode impedir o relatório
            import logging
            logging.getLogger("nexo.weekly").warning("Parte do relatório falhou: %s", part.__name__, exc_info=True)
    if not any(ln.kind in ("bad", "warn") for ln in L):
        L.insert(0, Line("ok", "Semana tranquila: sem falhas, sobreaquecimento nem avisos importantes."))
    return rep


def _stability(now, t0, tp) -> list[Line]:
    from . import reliability as rel
    evs = rel.events()
    if not evs and not rel.cached():
        return []
    cur = rel.summary(evs, now=now, days=7)
    prev = {k: v - cur.get(k, 0) for k, v in rel.summary(evs, now=now, days=14).items()}
    bad = {c: n for c, n in cur.items() if rel.CATEGORIES[c][1] == "bad"}
    out = []
    if bad:
        what = ", ".join(f"{rel.CATEGORIES[c][0].lower()} ({n}×)" for c, n in bad.items())
        out.append(Line("bad", f"Problemas de estabilidade: {what}.", "Fiabilidade"))
    apps = cur.get("app", 0)
    if apps:
        was = prev.get("app", 0)
        cmp = f" (eram {was})" if was and was != apps else ""
        out.append(Line("info" if apps < 5 else "warn", f"{apps} programa(s) fecharam com erro{cmp}.", "Fiabilidade"))
    if not bad and not apps:
        out.append(Line("ok", "Sem falhas do sistema nem desligares sem aviso."))
    return out


def _throttle(now, t0, tp) -> list[Line]:
    from . import throttle
    eps = throttle.recent(7, now)
    if not eps:
        return []
    mins = sum(e.seconds for e in eps) / 60
    comps = sorted({throttle.NAMES[e.comp].lower() for e in eps})
    return [Line("warn", f"Limitação por temperatura {len(eps)}× ({', '.join(comps)}), {mins:.0f} min no total.",
                 "Fiabilidade")]


def _boot(now, t0, tp) -> list[Line]:
    from . import boottime
    hist = boottime.history()
    week = [b.total for b in hist if t0 < b.when <= now]
    before = [b.total for b in hist if tp < b.when <= t0]
    if not week:
        return []
    avg = sum(week) / len(week)
    txt = f"Arranque médio: {_n(avg)} s ({len(week)} arranque(s))"
    kind = "warn" if avg >= boottime.SLOW_TOTAL else "info"
    if before:
        pavg = sum(before) / len(before)
        if abs(avg - pavg) >= max(1.0, pavg * 0.05):
            txt += f" — {'mais rápido' if avg < pavg else 'mais lento'} do que na semana anterior ({_n(pavg)} s)"
    return [Line(kind, txt + ".", "Arranque")]


def _games(now, t0, tp) -> list[Line]:
    from . import sessions
    week = sessions.summary(days=7)
    if not week:
        return []
    mins = sum(g.minutes for g in week)
    top = week[0]
    fps = f", {top.fps_avg:.0f} FPS de média" if top.fps_avg else ""
    h = f"{_n(mins / 60)} h" if mins >= 60 else f"{mins:.0f} min"
    return [Line("info", f"Jogou {h} — mais jogado: {top.game} ({_n(top.minutes / 60)} h{fps}).", "Modo jogo")]


def _alerts(now, t0, tp) -> list[Line]:
    from . import alertlog
    al = [a for a in alertlog.all_alerts() if t0 < a.when <= now and a.kind in ("warn", "bad")]
    if not al:
        return []
    n = sum(a.count for a in al)
    return [Line("info", f"{n} aviso(s) no centro de alertas — o mais recente: «{al[0].msg[:90]}».", al[0].page)]


def _changes(now, t0, tp) -> list[Line]:
    from . import changes
    ch = changes.marks_between(t0, now)
    if not ch:
        return []
    return [Line("info", f"Alterações feitas com o Nexo: {changes.summarize(ch)}.", "Benchmark")]


def _updates(now, t0, tp) -> list[Line]:
    from . import updates
    data = updates.cached() or {}
    n = len(data.get("items") or [])
    if n >= 20:
        return [Line("warn", f"{n} atualizações por instalar.", "Atualizações")]
    return []


# --------------------------------------------------------------------------- quando gerar
def due(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if not get_setting("weekly_report", True):
        return False
    last = float(get_setting("weekly_last") or 0)
    if not last:
        # primeira vez: espera uma semana de dados (marca o início)
        set_setting("weekly_last", now)
        return False
    return now - last >= WEEK


def generate(now: float | None = None) -> Report:
    now = time.time() if now is None else now
    rep = build(now)
    save_json(REPORT, rep.as_dict())
    set_setting("weekly_last", now)
    return rep


def last() -> Report | None:
    d = load_json(REPORT, None)
    return Report.from_dict(d) if isinstance(d, dict) and d.get("end") else None


# --------------------------------------------------------------------------- exportar
def to_text(rep: Report) -> str:
    d0 = date.fromtimestamp(rep.start) + timedelta(days=1)
    d1 = date.fromtimestamp(rep.end)
    sym = {"ok": "✓", "info": "•", "warn": "!", "bad": "✗"}
    out = [f"{APP_NAME} — relatório de {d0.strftime('%d/%m')} a {d1.strftime('%d/%m/%Y')}", rep.headline, ""]
    out += [f" {sym.get(ln.kind, '•')} {ln.text}" for ln in rep.lines]
    return "\n".join(out)


def to_html(rep: Report) -> str:
    colors = {"ok": "#1f9d55", "info": "#4a6fa5", "warn": "#b7791f", "bad": "#c53030"}
    d0 = date.fromtimestamp(rep.start) + timedelta(days=1)
    d1 = date.fromtimestamp(rep.end)
    rows = "\n".join(f'<li style="border-left:4px solid {colors.get(ln.kind, "#888")}">{html.escape(ln.text)}</li>'
                     for ln in rep.lines)
    return f"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{APP_NAME} — relatório semanal</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 16px;color:#222;background:#fff}}
h1{{font-size:1.4rem}} ul{{list-style:none;padding:0}} li{{padding:.6rem .8rem;margin:.4rem 0;background:#f6f7f9}}
@media (prefers-color-scheme:dark){{body{{background:#16181d;color:#e6e6e6}} li{{background:#22252c}}}}</style>
</head><body><h1>{APP_NAME} — semana de {d0.strftime('%d/%m')} a {d1.strftime('%d/%m/%Y')}</h1>
<p><b>{html.escape(rep.headline)}</b></p><ul>{rows}</ul></body></html>"""
