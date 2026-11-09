"""Vigilância em segundo plano: espaço em disco, memória e saúde dos discos (S.M.A.R.T.).

Só lógica (sem Qt) para poder ser testada: a janela principal chama estas funções num
temporizador e mostra as mensagens devolvidas como notificações."""
from __future__ import annotations

from dataclasses import dataclass, field

import psutil

from .util import IS_WIN, human_bytes, load_json, save_json

SMART_SEEN = "smart_seen.json"
_RANK = {"ok": 0, "unknown": 0, "warn": 1, "bad": 2}
_SKIP_FS = {"squashfs", "tmpfs", "overlay", "iso9660", "udf", "devtmpfs", "efivarfs", "ramfs", "vfat"}
MIN_SIZE = 4 * 1024 ** 3   # ignora partições pequenas (EFI, /boot, pens de arranque)


@dataclass
class Usage:
    mount: str
    total: int
    free: int

    @property
    def free_pct(self) -> float:
        return 100.0 * self.free / self.total if self.total else 100.0


def disk_usages() -> list[Usage]:
    out, seen = [], set()
    for p in psutil.disk_partitions(all=False):
        if p.device in seen or p.fstype.lower() in _SKIP_FS or "/snap/" in p.mountpoint:
            continue
        opts = set(p.opts.split(","))
        if "ro" in opts or (IS_WIN and ("cdrom" in opts or "removable" in opts)):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue
        seen.add(p.device)   # btrfs: vários subvolumes do mesmo dispositivo contam uma vez
        out.append(Usage(p.mountpoint, u.total, u.free))
    return out


@dataclass
class DiskAlerts:
    """Avisa uma vez quando um disco desce abaixo de `min_pct` % livre; volta a armar
    quando recupera 3 pontos acima do limite (evita avisos repetidos a oscilar no limite)."""
    alerted: set = field(default_factory=set)

    def check(self, usages: list[Usage], min_pct: float) -> list[tuple[str, str]]:
        msgs = []
        for u in usages:
            if u.total < MIN_SIZE:
                continue
            if u.free_pct < min_pct:
                if u.mount not in self.alerted:
                    self.alerted.add(u.mount)
                    kind = "bad" if u.free_pct < min_pct / 2 else "warn"
                    name = u.mount if not IS_WIN else u.mount.rstrip("\\")
                    msgs.append((f"Pouco espaço no disco {name}: só {human_bytes(u.free)} livres "
                                 f"({u.free_pct:.0f} %). Use a página Disco para libertar espaço.", kind))
            elif u.free_pct >= min_pct + 3:
                self.alerted.discard(u.mount)
        return msgs


def smart_changes(cache: dict | None, seen: dict | None = None) -> tuple[list[tuple[str, str]], dict]:
    """Compara o veredicto de cada disco com o último visto e devolve (mensagens, novo estado).
    Só avisa quando piora (ok → atenção → mau); uma melhoria apenas atualiza o estado."""
    seen = dict(seen or {})
    msgs = []
    for d in (cache or {}).get("disks", []):
        key = d.get("serial") or d.get("dev") or d.get("model")
        if not key:
            continue
        v = d.get("verdict", "unknown")
        if d.get("error"):       # disco que não deu para ler não é "disco a falhar"
            continue
        old = seen.get(key, "ok")
        if _RANK.get(v, 0) > _RANK.get(old, 0):
            name = d.get("model") or d.get("dev")
            why = next((t for k, t in d.get("reasons", []) if k == v), "")
            if v == "bad":
                msgs.append((f"O disco {name} está com problemas de saúde{': ' + why if why else ''}. "
                             "Faça cópia de segurança dos seus ficheiros.", "bad"))
            else:
                msgs.append((f"Atenção à saúde do disco {name}{': ' + why if why else ''}.", "warn"))
        seen[key] = v
    return msgs, seen


def smart_check_cached() -> list[tuple[str, str]]:
    """Usa a cache da página Saúde dos discos (sem pedir palavra-passe) e guarda o estado visto."""
    from . import smart
    msgs, seen = smart_changes(smart.cached(), load_json(SMART_SEEN, {}))
    try:
        save_json(SMART_SEEN, seen)
    except OSError:
        pass
    return msgs
