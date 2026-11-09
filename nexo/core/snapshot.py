"""Pontos de restauro antes de alterações ao sistema.

Windows: ponto de restauro do sistema (Checkpoint-Computer, precisa de admin).
Linux: snapshot do snapper (configuração "root") ou do Timeshift em modo btrfs.

Para não pedir a palavra-passe duas vezes no Linux, o comando do snapshot é posto à frente do
comando que já corre como root (`with_snapshot`). Só se cria um ponto a cada COOLDOWN segundos:
ligar cinco ajustes seguidos não gera cinco snapshots."""
from __future__ import annotations

import json
import os
import shlex
import time

from .util import IS_LINUX, IS_WIN, get_setting, is_admin, read_text, run, run_root, set_setting, which

COOLDOWN = 30 * 60   # segundos


def backend() -> str | None:
    """'windows' | 'snapper' | 'timeshift' | None"""
    if IS_WIN:
        return "windows"
    if not IS_LINUX:
        return None
    if which("snapper") and os.path.exists("/etc/snapper/configs/root"):
        return "snapper"
    if which("timeshift"):
        try:
            cfg = json.loads(read_text("/etc/timeshift/timeshift.json", "{}") or "{}")
        except ValueError:
            cfg = {}
        # em modo rsync um snapshot copia o sistema inteiro (minutos) — não serve para "antes de cada ajuste"
        if str(cfg.get("btrfs_mode", "")).lower() == "true":
            return "timeshift"
    return None


def backend_label(b: str | None = None) -> str:
    b = backend() if b is None else b
    return {"windows": "Restauro do sistema do Windows", "snapper": "Snapper (btrfs)",
            "timeshift": "Timeshift (btrfs)"}.get(b, "Nenhum disponível")


def how_to_restore(b: str | None = None) -> str:
    b = backend() if b is None else b
    return {
        "windows": "Para voltar atrás: Painel de Controlo → Recuperação → Abrir Restauro do Sistema.",
        "snapper": "Para voltar atrás: escolha o snapshot no menu de arranque (limine/grub-btrfs) "
                   "ou use 'snapper rollback' / Btrfs Assistant.",
        "timeshift": "Para voltar atrás: abra o Timeshift e escolha o snapshot.",
    }.get(b, "")


def enabled() -> bool:
    return bool(get_setting("snapshot_before")) and backend() is not None


def _due() -> bool:
    last = float(get_setting("snapshot_last", 0) or 0)
    return time.time() - last > COOLDOWN


def _mark() -> None:
    set_setting("snapshot_last", time.time())


def _desc(what: str) -> str:
    what = "".join(c for c in what if c.isprintable())[:60]
    return f"Nexo: antes de {what}" if what else "Nexo"


def linux_cmd(what: str, b: str | None = None) -> str | None:
    """Comando de shell (para correr como root) que cria o snapshot, ou None."""
    b = backend() if b is None else b
    d = shlex.quote(_desc(what))
    if b == "snapper":
        return f"snapper -c root create -t single -c number -d {d}"
    if b == "timeshift":
        return f"timeshift --create --scripted --comments {d}"
    return None


def with_snapshot(cmd: str, what: str) -> str:
    """Linux: devolve o comando com o snapshot à frente (se estiver ligado e for altura).
    Uma falha do snapshot nunca impede a ação (`|| true`)."""
    if not IS_LINUX or not enabled() or not _due():
        return cmd
    snap = linux_cmd(what)
    if not snap:
        return cmd
    _mark()
    return f"{{ {snap} >/dev/null 2>&1 || true; }}; {cmd}"


def before(what: str) -> tuple[bool, str] | None:
    """Windows: cria o ponto de restauro antes de uma alteração (se ligado e for altura).
    Devolve None quando não fez nada. No Linux use with_snapshot (evita um 2.º pedido de palavra-passe)."""
    if not IS_WIN or not enabled() or not _due():
        return None
    if not is_admin():
        return None   # a própria ação vai dizer que precisa de admin
    ok, msg = create(what)
    return ok, msg


def create(what: str = "alterações manuais") -> tuple[bool, str]:
    """Cria já um ponto de restauro (ignora o intervalo mínimo)."""
    b = backend()
    if b == "windows":
        if not is_admin():
            return False, "Precisa de executar o Nexo como administrador para criar pontos de restauro."
        from .systools import win_restore_point
        ok, msg = win_restore_point(_desc(what))
    elif b in ("snapper", "timeshift"):
        code, out = run_root(linux_cmd(what, b), timeout=900)
        ok = code == 0
        msg = "Snapshot criado. " + how_to_restore(b) if ok else (out.strip()[-300:] or "Falhou")
    else:
        return False, "Não há sistema de pontos de restauro disponível (instale e configure o snapper ou o Timeshift)."
    if ok:
        _mark()
    return ok, msg


def list_recent(limit: int = 5) -> list[tuple[str, str]]:
    """Últimos pontos criados pelo Nexo: [(data, descrição)]. Só leitura, sem pedir palavra-passe
    (no snapper, a lista é legível por utilizadores com ALLOW_USERS/ALLOW_GROUPS; senão devolve [])."""
    b = backend()
    if b == "snapper":
        code, out = run(["snapper", "-c", "root", "--jsonout", "list"], timeout=15)
        if code != 0:
            return []
        try:
            snaps = json.loads(out).get("root", [])
        except ValueError:
            return []
        mine = [(s.get("date", ""), s.get("description", "")) for s in snaps
                if str(s.get("description", "")).startswith("Nexo")]
        return mine[-limit:][::-1]
    if b == "windows":
        from .util import ps_json, as_list
        data = ps_json("Get-ComputerRestorePoint | Select-Object Description,"
                       "@{n='When';e={$_.ConvertToDateTime($_.CreationTime).ToString('yyyy-MM-dd HH:mm')}} "
                       "| ConvertTo-Json", timeout=30)
        rows = [(d.get("When", ""), d.get("Description", "")) for d in as_list(data)
                if str(d.get("Description", "")).startswith("Nexo")]
        return rows[-limit:][::-1]
    return []
