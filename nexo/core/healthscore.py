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
    out += _protection()
    return out


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


def _protection() -> list[Check]:
    from . import snapshot
    if snapshot.backend() and not get_setting("snapshot_before"):
        return [Check("warn", "Pontos de restauro desligados — ative-os para poder voltar atrás.", "Definições",
                      "Ativar")]
    return []
