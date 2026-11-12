"""Tarefas agendadas: limpeza automática, análise antivírus rápida e verificação da saúde dos discos.

A janela principal chama `due_tasks()` a cada 5 minutos e corre o que estiver em atraso (uma de cada vez,
em segundo plano). Cada tarefa guarda o intervalo (dias; 0 = desligada), a hora da última execução e o
resultado nas definições.

Nada aqui pede palavra-passe sem o utilizador estar a ver: no Linux a leitura S.M.A.R.T. precisa de root,
por isso a tarefa "Saúde dos discos" só LEMBRA (alerta com botão para a página); no Windows corre mesmo."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .util import IS_WIN, get_setting, set_setting

INTERVALS = {0: "Desligada", 1: "Diária", 7: "Semanal", 14: "A cada 2 semanas", 30: "Mensal"}


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    desc: str
    icon: str
    page: str                 # página relacionada
    days_key: str
    last_key: str
    default_days: int = 0
    reminder: bool = False    # só avisa (não corre sozinha)


def tasks() -> list[Task]:
    return [
        Task("clean", "Limpeza automática", "Miniaturas, caches de pacotes e temporários que se refazem sozinhos. "
             "Sem palavra-passe; o Lixo e as caches dos navegadores ficam de fora.", "broom", "Espaço em disco",
             "auto_clean_days", "auto_clean_last"),
        Task("antivirus", "Análise antivírus rápida", "Processos, arranque, pastas pessoais e temporárias "
             "(com o " + ("Microsoft Defender" if IS_WIN else "ClamAV, se estiver instalado") + "). "
             "Só avisa: nada vai para a quarentena sem a sua confirmação.", "virus", "Antivírus",
             "sched_av_days", "sched_av_last", 7),
        Task("smart", "Saúde dos discos (S.M.A.R.T.)",
             "Lê o estado dos discos e avisa se algum piorou." if IS_WIN else
             "Lembra-o de ler o estado dos discos (no Linux é preciso a palavra-passe, por isso não corre "
             "sozinha).", "hdd", "Saúde dos discos", "sched_smart_days", "sched_smart_last", 30, reminder=not IS_WIN),
    ]


def get(task_id: str) -> Task:
    return next(t for t in tasks() if t.id == task_id)


def interval(t: Task) -> int:
    v = get_setting(t.days_key)
    return int(t.default_days if v is None else v or 0)


def last_run(t: Task) -> float:
    return float(get_setting(t.last_key) or 0)


def set_interval(t: Task, days: int, now: float | None = None) -> None:
    now = time.time() if now is None else now
    set_setting(t.days_key, int(days))
    if days and not last_run(t):
        # primeira vez: não corre já no arranque — conta a partir de agora
        set_setting(t.last_key, now)


def next_run(t: Task, now: float | None = None) -> float | None:
    """Hora da próxima execução (None = desligada)."""
    days = interval(t)
    if days <= 0:
        return None
    now = time.time() if now is None else now
    return (last_run(t) or now) + days * 86400   # nunca corrida: conta a partir de agora


def start_counting(now: float | None = None) -> None:
    """Tarefas ligadas por omissão e nunca corridas começam a contar agora (nada pesado no 1.º arranque)."""
    now = time.time() if now is None else now
    for t in tasks():
        if interval(t) > 0 and not last_run(t):
            set_setting(t.last_key, now)


def due_tasks(now: float | None = None) -> list[Task]:
    now = time.time() if now is None else now
    start_counting(now)
    out = []
    for t in tasks():
        n = next_run(t, now)
        if n is not None and n <= now:
            out.append(t)
    return out


def result(t: Task) -> dict:
    r = (get_setting("sched_results") or {}).get(t.id)
    return r if isinstance(r, dict) else {}


def record(t: Task, ok: bool, msg: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    set_setting(t.last_key, now)
    res = dict(get_setting("sched_results") or {})
    res[t.id] = {"when": now, "ok": bool(ok), "msg": msg}
    set_setting("sched_results", res)


# --------------------------------------------------------------------------- execução
def run_task(t: Task) -> tuple[str, str]:
    """Corre a tarefa (numa thread de trabalho). Devolve (mensagem, tipo de alerta; "" = sem alerta)."""
    if t.id == "clean":
        from . import autoclean
        freed, msg = autoclean.run()
        record(t, True, msg)
        return (msg, "ok") if freed else ("", "")
    if t.id == "antivirus":
        from . import antivirus as av
        rep = av.scan("quick", use_engine=True)
        bad, warn = rep.count(av.BAD), rep.count(av.WARN)
        try:
            save_report(rep)
        except OSError:
            pass
        if bad:
            msg = f"Análise antivírus agendada: {bad} ameaça(s) encontrada(s) — reveja na página Antivírus."
            record(t, False, msg)
            return msg, "bad"
        if warn:
            msg = f"Análise antivírus agendada: {warn} item(ns) suspeito(s) para rever."
            record(t, True, msg)
            return msg, "warn"
        record(t, True, f"Análise antivírus agendada: nada encontrado ({rep.files_scanned} ficheiros).")
        return "", ""
    if t.id == "smart":
        if t.reminder:
            msg = "Está na altura de verificar a saúde dos discos (S.M.A.R.T.)."
            record(t, True, "Lembrete mostrado.")
            return msg, "info"
        from . import smart, watch
        smart.read_all()
        msgs = watch.smart_check_cached()
        record(t, not msgs, msgs[0][0] if msgs else "Discos lidos: sem alterações.")
        return msgs[0] if msgs else ("", "")
    raise ValueError(t.id)


REPORT = "av_relatorio.json"


def save_report(rep) -> None:
    """Guarda o resultado da análise agendada para a página Antivírus o mostrar."""
    from dataclasses import asdict

    from .util import save_json
    save_json(REPORT, {**{k: v for k, v in asdict(rep).items() if k != "findings"},
                       "findings": [asdict(f) for f in rep.findings]})


def load_report():
    from . import antivirus as av
    from .util import load_json
    d = load_json(REPORT, None)
    if not isinstance(d, dict):
        return None
    try:
        rep = av.Report(**{k: v for k, v in d.items() if k != "findings" and k in av.Report.__dataclass_fields__})
        rep.findings = [av.Finding(**f) for f in d.get("findings", [])]
        return rep
    except TypeError:
        return None
