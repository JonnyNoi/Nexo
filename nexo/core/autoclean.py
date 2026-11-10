"""Limpeza automática agendada: só o que é 100 % seguro e não precisa de palavra-passe.

Corre a partir da janela principal (verificação a cada 5 min) quando passou o intervalo escolhido.
Fica de fora tudo o que tem consequências (Lixo/Reciclagem, caches dos navegadores, shaders dos jogos,
caches de programação) e tudo o que precisa de administrador — isso continua a ser manual."""
from __future__ import annotations

import time

from . import cleanup
from .util import get_setting, human_bytes, set_setting

# categorias que se refazem sozinhas sem custo visível
AUTO_IDS = ("lx_thumbs", "lx_aur", "win_temp_user", "win_thumbs", "win_wer")
INTERVALS = {0: "Desligada", 7: "Semanal", 14: "A cada 2 semanas", 30: "Mensal"}


def categories() -> list[cleanup.CleanCategory]:
    return [c for c in cleanup.categories()
            if c.id in AUTO_IDS and not c.needs_admin and not c.caution and not c.command and c.patterns]


def due(now: float | None = None) -> bool:
    days = int(get_setting("auto_clean_days") or 0)
    if days <= 0:
        return False
    now = time.time() if now is None else now
    return now - float(get_setting("auto_clean_last") or 0) >= days * 86400


def run() -> tuple[int, str]:
    """Limpa e devolve (bytes libertados, resumo). Marca a hora mesmo que não haja nada para limpar."""
    freed, done = 0, []
    for c in categories():
        size = cleanup.compute_size(c)
        if size <= 0:
            continue
        ok, _msg = cleanup.clean(c)
        if ok:
            after = cleanup.compute_size(c)
            got = max(0, size - max(after, 0))
            if got:
                freed += got
                done.append(c.name)
    set_setting("auto_clean_last", time.time())
    set_setting("auto_clean_freed", int(get_setting("auto_clean_freed") or 0) + freed)
    if not freed:
        return 0, "Limpeza automática: não havia nada para limpar."
    return freed, f"Limpeza automática: {human_bytes(freed)} libertados ({', '.join(done)})."
