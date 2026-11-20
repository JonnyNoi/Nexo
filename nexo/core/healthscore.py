"""Saúde do PC: uma pontuação de 0 a 100 e as ações mais úteis do momento.

Junta as verificações do painel (temperaturas, RAM, disco, S.M.A.R.T., tempo ligado…) com outras que
não mudam a cada segundo (atualizações pendentes, drivers antigos, última análise antivírus, pontos de
restauro) — todas lidas de caches, sem pedir nada ao sistema."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .util import get_setting

# quanto cada problema tira à pontuação
PENALTY = {"bad": 25, "warn": 8}
# limite do que cada tipo de problema pode tirar (muitos avisos pequenos não levam a pontuação a 0)
MAX_WARN_TOTAL = 40


@dataclass
class Check:
    kind: str          # ok | warn | bad
    text: str
    page: str | None = None
    action: str = "Resolver"   # texto do botão


def score(checks: list[Check]) -> int:
    bad = sum(PENALTY["bad"] for c in checks if c.kind == "bad")
    warn = min(MAX_WARN_TOTAL, sum(PENALTY["warn"] for c in checks if c.kind == "warn"))
    return max(0, min(100, 100 - bad - warn))


def grade(s: int) -> tuple[str, str]:
    """(texto, tipo de cor)"""
    if s >= 90:
        return "Excelente", "ok"
    if s >= 75:
        return "Boa", "ok"
    if s >= 50:
        return "Precisa de atenção", "warn"
    return "Má", "bad"


def top_actions(checks: list[Check], n: int = 3) -> list[Check]:
    """Os problemas mais graves que têm uma página para os resolver."""
    todo = [c for c in checks if c.kind != "ok" and c.page]
    todo.sort(key=lambda c: 0 if c.kind == "bad" else 1)
    return todo[:n]


# --------------------------------------------------------------------------- verificações lentas
def slow_checks(now: float | None = None) -> list[Check]:
    """Verificações que só dependem de caches (podem correr na thread da interface a cada minuto)."""
    now = time.time() if now is None else now
    out: list[Check] = []
    out += _updates(now)
    out += _antivirus(now)
    out += _drivers()
    out += _components()
    out += _protection()
    out += _reliability(now)
    out += _throttling(now)
    out += _battery()
    out += _memory_speed()
    out += _display()
    out += _firewall()
    out += _boot()
    out += _smart_trend()
    out += _bios()
    return out


def _smart_trend() -> list[Check]:
    """Setores estragados a subir ou SSD perto do fim da vida (histórico S.M.A.R.T.)."""
    from . import smart, smarthist
    data = smart.cached() or {}
    hist = smarthist._load()
    for d in data.get("disks") or []:
        tr = smarthist.for_disk(d, hist)
        bad = [t for k, t in tr.notes if k == "bad"]
        if bad:
            return [Check("bad", f"{d.get('model') or 'Disco'}: {bad[0]}", "Saúde dos discos", "Ver")]
    return []


def _bios() -> list[Check]:
    from . import bios
    c = bios.cached()
    if c and c.get("fwupd_update"):
        return [Check("warn", f"Há uma atualização do BIOS/UEFI: {c['fwupd_update']}.", "Atualizações", "Ver")]
    return []


def _battery() -> list[Check]:
    from . import battery
    out = []
    for b in battery.cached():
        kind, _why = b.verdict()
        h = b.health_pct
        if h is not None and kind != "ok":
            out.append(Check(kind, f"Bateria gasta: guarda só {h:.0f} % da carga original.", "Bateria", "Ver"))
    return out


def _memory_speed() -> list[Check]:
    from . import ramspeed
    v = ramspeed.check(ramspeed.cached())
    if v and v.kind == "warn":
        what = f"{v.current} MT/s em vez de {v.rated}" if v.rated else f"{v.current} MT/s"
        return [Check("warn", f"Memória RAM abaixo da velocidade ({what}) — ligue o XMP/EXPO no BIOS.",
                      "Informação", "Ver")]
    return []


def _display() -> list[Check]:
    from . import display
    for m in display.cached():
        v = display.check(m)
        if v and v.kind == "warn":
            return [Check("warn", f"Monitor a {m.hz:.0f} Hz em vez de {m.max_hz:.0f} Hz — mude nas definições de ecrã.",
                          "Informação", "Ver")]
    return []


def _firewall() -> list[Check]:
    from . import firewall
    st, ports = firewall.cached()
    if st is None or st.active is not False:
        return []
    worst = next((f for f in firewall.analyze(st, ports) if f[0] in ("bad", "warn")), None)
    if worst is None:
        return []
    return [Check(worst[0], "Firewall desligada — o PC aceita ligações de outros aparelhos da rede."
                  if worst[0] == "bad" or any(p.exposed for p in ports) else "Firewall desligada.",
                  "Internet", "Ver")]


def _boot() -> list[Check]:
    from . import boottime
    hist = boottime.history()
    if hist and hist[-1].total >= boottime.SLOW_TOTAL:
        return [Check("warn", f"O PC demora {hist[-1].total:.0f} s a arrancar.", "Arranque", "Ver")]
    return []


def _updates(now: float) -> list[Check]:
    from . import updates
    data = updates.cached() or {}
    items = data.get("items") or []
    if not data.get("time"):
        return []
    n = len(items)
    if n >= 50:
        return [Check("warn", f"{n} atualizações por instalar.", "Atualizações", "Atualizar")]
    if n:
        return [Check("warn" if now - float(data["time"]) > 7 * 86400 else "ok",
                      f"{n} atualizações disponíveis.", "Atualizações", "Atualizar")]
    return [Check("ok", "Sistema atualizado.")]


def _antivirus(now: float) -> list[Check]:
    last = get_setting("av_last_scan") or {}
    when = float(last.get("when") or 0) if isinstance(last, dict) else 0
    if isinstance(last, dict) and last.get("bad"):
        return [Check("bad", f"A última análise encontrou {last['bad']} ameaça(s).", "Antivírus", "Ver")]
    if not when:
        return [Check("warn", "Ainda não fez nenhuma análise antivírus.", "Antivírus", "Analisar")]
    days = (now - when) / 86400
    if days > 30:
        return [Check("warn", f"Última análise antivírus há {int(days)} dias.", "Antivírus", "Analisar")]
    return [Check("ok", "Análise antivírus recente.")]


def _drivers() -> list[Check]:
    from .util import load_json
    data = load_json("drivers.json", {}) or {}
    old = [d for d in (data.get("items") or []) if isinstance(d, dict) and d.get("status") == "warn"]
    if old:
        name = f"{old[0].get('component') or 'driver'} {old[0].get('version') or ''}".strip()
        more = f" (+{len(old) - 1})" if len(old) > 1 else ""
        return [Check("warn", f"Driver desatualizado: {name}{more}.", "Atualizações", "Ver")]
    return []


def _components() -> list[Check]:
    from . import components
    found = components.cached_findings()
    if not found:
        return []
    worst = next((f for f in found if f.kind == "bad"), found[0])
    more = f" (+{len(found) - 1})" if len(found) > 1 else ""
    from .i18n import tr   # traduzir o título antes de lhe juntar o "(+n)" (senão o modelo não o reconhece)
    return [Check(worst.kind, f"{tr(worst.title)}{more}.", "Atualizações", "Resolver")]


def _reliability(now: float) -> list[Check]:
    """Um único desligar sem aviso pode ter sido o botão de reset — só é grave a partir do segundo."""
    from . import reliability as rel
    s = rel.summary(rel.events(), now=now, days=7)
    serious = {c: n for c, n in s.items() if rel.CATEGORIES[c][1] == "bad" and (c != "shutdown" or n >= 2)}
    if serious:
        what = ", ".join(f"{rel.CATEGORIES[c][0].lower()} ({n}×)" for c, n in serious.items())
        return [Check("bad", f"Problemas de estabilidade esta semana: {what}.", "Fiabilidade", "Ver")]
    if s.get("shutdown"):
        return [Check("warn", "O PC desligou-se sem aviso uma vez esta semana.", "Fiabilidade", "Ver")]
    if s.get("gpu", 0) >= 2 or s.get("memory", 0) >= 2:
        return [Check("warn", "O controlador gráfico ou a memória falharam várias vezes esta semana.", "Fiabilidade",
                      "Ver")]
    return []


def _throttling(now: float) -> list[Check]:
    from . import throttle
    eps = throttle.recent(7, now)
    if not eps:
        return []
    comps = sorted({throttle.NAMES[e.comp].lower() for e in eps})
    return [Check("warn", f"Limitação por temperatura esta semana: {len(eps)}× ({', '.join(comps)}).", "Fiabilidade",
                  "Ver")]


def _protection() -> list[Check]:
    from . import snapshot
    if snapshot.backend() and not get_setting("snapshot_before"):
        return [Check("warn", "Pontos de restauro desligados — ative-os para poder voltar atrás.", "Definições",
                      "Ativar")]
    return []
