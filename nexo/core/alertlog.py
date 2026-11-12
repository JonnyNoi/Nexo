"""Centro de alertas: guarda os avisos (temperatura, RAM, discos, jogos, atualizações…) para os ver depois.

Os alertas aparecem como notificação e desaparecem; aqui ficam registados (no máximo MAX, os mais
recentes primeiro) com a hora, o tipo, a página que resolve e se já foram lidos."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from .util import _save_lock, load_json, save_json

FILE = "alertas.json"
MAX = 200
# o mesmo aviso repetido dentro deste intervalo não cria uma entrada nova (só atualiza a hora)
DEDUP_S = 600


@dataclass
class Alert:
    id: int
    when: float
    msg: str
    kind: str = "info"      # ok | info | warn | bad
    page: str = ""          # página do Nexo que resolve ("" = nenhuma)
    read: bool = False
    count: int = 1          # quantas vezes se repetiu


# página a abrir para cada tipo de aviso (por palavras-chave da mensagem)
_PAGES = (
    (("jogo", "sessão de"), "Modo jogo"),
    (("temperatura", "°c"), "Sensores"),
    (("memória ram", "ram quase"), "Processos"),
    (("s.m.a.r.t", "saúde do disco", "problemas de saúde", "setores"), "Saúde dos discos"),
    (("espaço", "disco", "livre"), "Espaço em disco"),
    (("limpeza",), "Tarefas agendadas"),
    (("antivírus", "ameaça", "suspeito"), "Antivírus"),
    (("nexo ", "⬆"), "Definições"),
    (("atualiza",), "Atualizações"),
)


def guess_page(msg: str) -> str:
    low = msg.lower()
    for words, page in _PAGES:
        if any(w in low for w in words):
            return page
    return ""


def _load() -> list[dict]:
    data = load_json(FILE, [])
    return [x for x in data if isinstance(x, dict) and "id" in x] if isinstance(data, list) else []


def all_alerts() -> list[Alert]:
    out = []
    for x in _load():
        try:
            out.append(Alert(**{k: x[k] for k in Alert.__dataclass_fields__ if k in x}))
        except TypeError:
            continue
    return out


def add(msg: str, kind: str = "info", page: str | None = None, now: float | None = None) -> Alert:
    now = time.time() if now is None else now
    page = guess_page(msg) if page is None else page
    with _save_lock:
        lst = _load()
        for x in lst[:20]:
            if x.get("msg") == msg and now - float(x.get("when", 0)) < DEDUP_S:
                x["when"], x["read"] = now, False
                x["count"] = int(x.get("count", 1)) + 1
                lst.remove(x)
                lst.insert(0, x)
                save_json(FILE, lst)
                return Alert(**{k: x[k] for k in Alert.__dataclass_fields__ if k in x})
        new_id = max((int(x.get("id", 0)) for x in lst), default=0) + 1
        a = Alert(new_id, now, msg, kind, page or "")
        lst.insert(0, asdict(a))
        save_json(FILE, lst[:MAX])
    return a


def unread() -> int:
    return sum(1 for x in _load() if not x.get("read"))


def mark_read(alert_id: int | None = None) -> None:
    """Marca um alerta (ou todos, com None) como lido."""
    with _save_lock:
        lst = _load()
        changed = False
        for x in lst:
            if (alert_id is None or x.get("id") == alert_id) and not x.get("read"):
                x["read"] = changed = True
        if changed:
            save_json(FILE, lst)


def clear() -> None:
    with _save_lock:
        save_json(FILE, [])


def when_text(ts: float, now: float | None = None) -> str:
    """"agora", "há 5 min", "há 3 h", "ontem 14:02", "12/11 09:30"."""
    now = time.time() if now is None else now
    d = max(0, now - ts)
    if d < 60:
        return "agora"
    if d < 3600:
        return f"há {int(d // 60)} min"
    lt, ln = time.localtime(ts), time.localtime(now)
    if d < 12 * 3600 or lt.tm_yday == ln.tm_yday and lt.tm_year == ln.tm_year:
        return f"há {int(d // 3600)} h" if d < 12 * 3600 else time.strftime("hoje %H:%M", lt)
    if d < 48 * 3600 and (ln.tm_yday - lt.tm_yday) % 366 == 1:
        return time.strftime("ontem %H:%M", lt)
    return time.strftime("%d/%m %H:%M", lt)
