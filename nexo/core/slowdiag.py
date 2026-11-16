"""«Porque está lento?» — um diagnóstico de um clique que explica, em frases simples, o que está a pesar.

collect() mede durante ~2 s (CPU por aplicação, memória e paginação, atividade dos discos, processos
conhecidos que costumam pesar) e junta o que o Nexo já sabe (temperaturas, throttling, espaço livre,
S.M.A.R.T., perfil de energia, tempo ligado). analyze() é pura: recebe esse dicionário e devolve as
conclusões ordenadas da mais grave para a menos grave."""
from __future__ import annotations

import time
from dataclasses import dataclass

import psutil

from .util import IS_LINUX, human_bytes


@dataclass
class Finding:
    kind: str            # bad | warn | info | ok
    title: str
    detail: str = ""
    page: str | None = None
    action: str = "Abrir"


# processos que, quando ocupados, explicam a lentidão (nome em minúsculas sem .exe → explicação)
KNOWN = {
    # atualizações
    "pacman": ("updates", "Está a decorrer uma atualização de pacotes (pacman)."),
    "paru": ("updates", "Está a decorrer uma atualização (paru)."),
    "yay": ("updates", "Está a decorrer uma atualização (yay)."),
    "makepkg": ("updates", "Está a ser compilado um pacote do AUR."),
    "apt": ("updates", "Está a decorrer uma atualização (apt)."),
    "dpkg": ("updates", "Estão a ser instalados pacotes (dpkg)."),
    "dnf": ("updates", "Está a decorrer uma atualização (dnf)."),
    "packagekitd": ("updates", "O PackageKit está a procurar ou instalar atualizações."),
    "flatpak": ("updates", "O Flatpak está a atualizar aplicações."),
    "tiworker": ("updates", "O Windows Update está a instalar atualizações (TiWorker)."),
    "trustedinstaller": ("updates", "O Windows está a instalar atualizações ou componentes."),
    "mousocoreworker": ("updates", "O Windows Update está a trabalhar."),
    "wuauclt": ("updates", "O Windows Update está a trabalhar."),
    "msiexec": ("updates", "Está a decorrer uma instalação."),
    # antivírus
    "msmpeng": ("av", "O Microsoft Defender está a analisar ficheiros."),
    "mpdefendercoreservice": ("av", "O Microsoft Defender está a analisar ficheiros."),
    "clamscan": ("av", "O ClamAV está a analisar ficheiros."),
    "clamd": ("av", "O ClamAV está a analisar ficheiros."),
    "freshclam": ("av", "O ClamAV está a atualizar as definições."),
    # indexação
    "baloo_file": ("index", "O KDE está a indexar ficheiros para a pesquisa (Baloo)."),
    "baloo_file_extractor": ("index", "O KDE está a indexar ficheiros para a pesquisa (Baloo)."),
    "tracker-miner-fs-3": ("index", "O GNOME está a indexar ficheiros (Tracker)."),
    "localsearch-3": ("index", "O GNOME está a indexar ficheiros (LocalSearch)."),
    "searchindexer": ("index", "O Windows está a indexar ficheiros para a pesquisa."),
    "searchprotocolhost": ("index", "O Windows está a indexar ficheiros para a pesquisa."),
    # outros
    "snapperd": ("snap", "O Snapper está a criar ou limpar pontos de restauro."),
    "btrfs": ("snap", "Manutenção do sistema de ficheiros btrfs (balance/scrub)."),
    "compattelrunner": ("tele", "Telemetria do Windows (Compatibility Appraiser) a correr."),
}


def _norm(name: str) -> str:
    n = (name or "").lower()
    return n[:-4] if n.endswith(".exe") else n


# ------------------------------------------------------------------------------------- recolha
def collect(hub_snapshot: dict | None = None, throttling: dict | None = None, seconds: float = 2.0) -> dict:
    from . import processes
    hub_snapshot = hub_snapshot or {}
    procs = {}
    for p in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
        try:
            p.cpu_percent(None)
            procs[p.pid] = p
        except (psutil.Error, OSError):
            continue
    io0 = _disk_io()
    sw0 = psutil.swap_memory()
    cpu_total = psutil.cpu_percent(None)
    time.sleep(seconds)
    cpu_total = psutil.cpu_percent(None)
    io1 = _disk_io()
    sw1 = psutil.swap_memory()
    ncpu = psutil.cpu_count() or 1
    rows = []
    for pid, p in procs.items():
        try:
            cpu = p.cpu_percent(None) / ncpu
            info = p.info
            mem = info.get("memory_info")
            rows.append({"pid": pid, "name": info.get("name") or "?", "exe": info.get("exe") or "", "cpu": cpu,
                         "rss": mem.rss if mem else 0, "self": pid == _self_pid()})
        except (psutil.Error, OSError):
            continue
    apps, _hidden = processes.group_apps(rows)
    vm = psutil.virtual_memory()
    busy = {}
    for dev, (b0, b1) in _pair(io0, io1).items():
        if b0 is not None and b1 is not None:
            busy[dev] = min(100.0, max(0.0, (b1 - b0) / (seconds * 1000) * 100))
    known = []
    for r in rows:
        k = _norm(r["name"])
        if k in KNOWN and (r["cpu"] >= 3 or KNOWN[k][0] == "updates"):
            known.append({"key": k, "cpu": r["cpu"]})
    data = {
        "cpu_total": cpu_total,
        "apps": [{"name": a["name"], "cpu": a["cpu"], "rss": a["rss"], "n": len(a["pids"])} for a in apps],
        "ram_pct": vm.percent, "ram_total": vm.total, "ram_avail": vm.available,
        "swap_pct": sw1.percent if sw1.total else 0.0,
        "swap_rate": max(0, (sw1.sin + sw1.sout) - (sw0.sin + sw0.sout)) / seconds,
        "disk_busy": busy,
        "known": known,
        "cpu_temp": hub_snapshot.get("cpu_temp"), "gpu_temp": hub_snapshot.get("gpu_temp"),
        "throttling": throttling or {},
        "uptime_days": (time.time() - psutil.boot_time()) / 86400,
    }
    try:
        from .watch import disk_usages
        data["disks"] = [{"mount": u.mount, "free_pct": u.free_pct, "free": u.free} for u in disk_usages()]
    except Exception:  # noqa: BLE001
        data["disks"] = []
    try:
        from . import smart
        c = smart.cached() or {}
        data["smart_bad"] = [{"name": d.get("model") or d.get("dev"), "verdict": d.get("verdict"),
                              "reason": (d.get("reasons") or [["", ""]])[0][1]}
                             for d in c.get("disks", []) if d.get("verdict") in ("bad", "warn")]
    except Exception:  # noqa: BLE001
        data["smart_bad"] = []
    try:
        from . import power
        data["power"] = power.get_power_profile() if power.available() else ""
    except Exception:  # noqa: BLE001
        data["power"] = ""
    try:
        from . import reliability
        data["oom_recent"] = reliability.summary(reliability.events(), days=1).get("memory", 0)
    except Exception:  # noqa: BLE001
        data["oom_recent"] = 0
    return data


def _self_pid() -> int:
    import os
    return os.getpid()


def _disk_io() -> dict:
    try:
        c = psutil.disk_io_counters(perdisk=True) or {}
    except (RuntimeError, OSError):
        return {}
    out = {}
    for dev, v in c.items():
        if IS_LINUX:
            # só discos inteiros (sda, nvme0n1): partições e dispositivos virtuais ficam de fora
            import os
            if not os.path.exists(f"/sys/block/{dev}") or dev.startswith(("loop", "ram", "zram", "dm-", "sr")):
                continue
        out[dev] = getattr(v, "busy_time", None)
    return out


def _pair(a: dict, b: dict) -> dict:
    return {k: (a.get(k), b.get(k)) for k in set(a) | set(b)}


# ------------------------------------------------------------------------------------- análise
def analyze(d: dict) -> list[Finding]:
    out: list[Finding] = []
    apps = sorted(d.get("apps") or [], key=lambda a: -a["cpu"])
    cpu = d.get("cpu_total") or 0.0
    # --- processador
    if cpu >= 85:
        top = [a for a in apps[:3] if a["cpu"] >= 10]
        who = ", ".join(f"{a['name']} ({a['cpu']:.0f} %)" for a in top) or "vários processos do sistema"
        out.append(Finding("bad", f"Processador quase no máximo ({cpu:.0f} %)",
                           f"Quem está a usar: {who}. Feche o que não precisa ou espere que termine.",
                           "Processos", "Ver processos"))
    elif apps and apps[0]["cpu"] >= 25:
        a = apps[0]
        out.append(Finding("warn", f"{a['name']} está a usar {a['cpu']:.0f} % do processador",
                           "Se não estiver a fazer nada de pesado com ele, pode estar preso — feche-o e volte a abrir.",
                           "Processos", "Ver processos"))
    # --- processos conhecidos (atualizações, antivírus, indexação…)
    seen = set()
    for k in d.get("known") or []:
        cat, text = KNOWN.get(k["key"], ("", ""))
        if not cat or cat in seen:
            continue
        seen.add(cat)
        page = {"updates": "Atualizações", "av": "Antivírus"}.get(cat)
        out.append(Finding("warn" if k["cpu"] >= 10 else "info", text,
                           "É temporário — o PC volta ao normal quando terminar.", page))
    # --- memória
    ram = d.get("ram_pct") or 0.0
    swap_rate = d.get("swap_rate") or 0.0
    big = sorted(d.get("apps") or [], key=lambda a: -a["rss"])[:3]
    big_txt = ", ".join(f"{a['name']} ({human_bytes(a['rss'])})" for a in big if a["rss"] >= 300 * 2**20)
    if ram >= 90 or swap_rate >= 5 * 2**20:
        detail = "O sistema está a usar o disco como memória (muito mais lento)." if swap_rate >= 5 * 2**20 else \
            "Quase não há memória livre."
        if big_txt:
            detail += f" Quem gasta mais: {big_txt}."
        out.append(Finding("bad", f"Memória RAM quase cheia ({ram:.0f} %)", detail, "Otimização",
                           "Fechar programas"))
    elif ram >= 80:
        out.append(Finding("warn", f"Memória RAM a {ram:.0f} %", f"Quem gasta mais: {big_txt}." if big_txt else "",
                           "Otimização", "Fechar programas"))
    if d.get("oom_recent"):
        out.append(Finding("warn", "Hoje o sistema já teve de fechar programas por falta de memória",
                           "Veja quais em Fiabilidade.", "Fiabilidade"))
    # --- disco
    for dev, b in sorted((d.get("disk_busy") or {}).items(), key=lambda kv: -kv[1]):
        if b >= 90:
            out.append(Finding("bad", f"O disco {dev} está ocupado a {b:.0f} %",
                               "Tudo o que precisa do disco (abrir programas, ficheiros) fica à espera. "
                               "Costuma ser uma cópia, atualização, antivírus ou indexação.", "Processos",
                               "Ver processos"))
            break
        if b >= 60:
            out.append(Finding("warn", f"O disco {dev} está muito ativo ({b:.0f} %)", "", "Processos", "Ver processos"))
            break
    for u in d.get("disks") or []:
        if u["free_pct"] < 5 or (u["mount"] in ("/", "C:\\") and u["free_pct"] < 10):
            out.append(Finding("bad" if u["free_pct"] < 5 else "warn",
                               f"Pouco espaço em {u['mount']} ({human_bytes(u['free'])} livres)",
                               "Com o disco do sistema quase cheio tudo fica mais lento (atualizações, cache, "
                               "ficheiro de paginação).", "Espaço em disco", "Libertar espaço"))
    for disk in d.get("smart_bad") or []:
        if disk.get("verdict") == "bad":
            out.append(Finding("bad", f"O disco {disk['name']} tem problemas de saúde",
                               "Um disco a falhar pode ficar muito lento antes de avariar. Faça cópia de segurança.",
                               "Saúde dos discos", "Ver disco"))
        else:   # aviso: informativo (não é por si só a causa da lentidão)
            out.append(Finding("info", f"O disco {disk['name']} tem um aviso de saúde", disk.get("reason") or "",
                               "Saúde dos discos", "Ver disco"))
    # --- temperatura / throttling
    for comp, ep in (d.get("throttling") or {}).items():
        who = "O processador" if comp == "cpu" else "A placa gráfica"
        out.append(Finding("bad", f"{who} está a baixar o clock por temperatura",
                           ("Está a trabalhar mais devagar para não sobreaquecer. "
                            + ("Verifique o cooler e a pasta térmica." if comp == "cpu"
                               else "Limpe o pó e melhore a ventilação.")), "Sensores", "Ver sensores"))
    if not d.get("throttling"):
        for key, name, lim in (("cpu_temp", "processador", 90), ("gpu_temp", "placa gráfica", 88)):
            t = d.get(key)
            if t is not None and t >= lim:
                out.append(Finding("warn", f"Temperatura alta no {name} ({t:.0f} °C)" if name == "processador"
                                   else f"Temperatura alta na {name} ({t:.0f} °C)",
                                   "Perto do limite em que o hardware se protege baixando o desempenho.",
                                   "Sensores", "Ver sensores"))
    # --- energia / tempo ligado
    if d.get("power") == "power-saver":
        out.append(Finding("warn", "Perfil de energia em «Poupança de energia»",
                           "O processador fica limitado de propósito. Mude para Equilibrado ou Desempenho.",
                           None))
    if (d.get("uptime_days") or 0) >= 7:
        out.append(Finding("info", f"O PC está ligado há {d['uptime_days']:.0f} dias",
                           "Reiniciar de vez em quando liberta memória presa e aplica atualizações pendentes.", None))
    order = {"bad": 0, "warn": 1, "info": 2}
    out.sort(key=lambda f: order.get(f.kind, 3))
    if not any(f.kind in ("bad", "warn") for f in out):
        out.insert(0, Finding("ok", "Não encontrei nada a pesar agora",
                              "Processador, memória e discos estão folgados. Se a lentidão for só num programa ou "
                              "jogo, o problema está nele (ou na internet — veja a página Internet).", "Internet",
                              "Testar internet"))
    return out
