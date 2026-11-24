"""«O que devo atualizar?» — qual a peça que mais limita o PC e o que melhorar primeiro.

Junta o que o Nexo já sabe:
  • as sessões de jogo (carga média da CPU e da GPU, FPS, VRAM e RAM máximas) — a forma mais fiável de ver o
    gargalo: com a placa gráfica perto dos 100 % é ela que limita; com ela folgada e o FPS baixo, é a CPU
    (ou o próprio jogo);
  • os resultados do benchmark (CPU multi/single-core e placa gráfica);
  • o hardware: quantidade e velocidade da RAM (XMP desligado), VRAM, disco do sistema (HDD/SSD), monitor,
    limitação por temperatura.
Primeiro aparecem as correções GRÁTIS (XMP, Hz do monitor, temperatura), depois as compras por ordem do que
mais melhora. `advise()` é uma função pura (testável); `gather()` recolhe os dados."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# Referências do benchmark do Nexo (ver FUNCIONALIDADES.md): i5-12400F ≈ 1290 multi / 196 single; RX 6500 XT ≈ 1500 (1080p)
CPU_MULTI_LOW, CPU_MULTI_OK = 700, 1100
CPU_SINGLE_LOW, CPU_SINGLE_OK = 120, 170
GPU_LOW, GPU_OK = 900, 2500           # pontuação da placa gráfica em 1080p (FPS × 10)
GPU_BOUND = 88                        # % de carga média da GPU a partir da qual é ela que limita
GPU_IDLE = 70                         # abaixo disto, com FPS baixo, o limite está na CPU/jogo
MIN_MINUTES = 20                      # tempo de jogo mínimo para tirar conclusões


@dataclass
class GameLoad:
    game: str
    minutes: float
    cpu_load: float | None
    gpu_load: float | None
    fps_avg: float | None
    fps_low1: float | None
    vram_max: float | None
    ram_max: float | None


@dataclass
class Facts:
    cpu: str = ""
    cores: int = 0
    threads: int = 0
    ram_gb: float = 0.0
    ram_kind: str = ""
    ram_xmp_off: bool = False
    ram_current: int | None = None
    ram_rated: int | None = None
    gpu: str = ""
    vram_gb: float | None = None
    sys_disk: str = ""                 # HDD | SSD | NVMe | ""
    cpu_multi: float | None = None
    cpu_single: float | None = None
    gpu_score: float | None = None     # 1080p
    monitor_hz: float | None = None
    monitor_max_hz: float | None = None
    throttle_cpu: int = 0              # episódios nos últimos 30 dias
    throttle_gpu: int = 0
    games: list[GameLoad] = field(default_factory=list)


@dataclass
class Advice:
    part: str            # CPU | Placa gráfica | Memória | Disco | Monitor | Refrigeração | Equilíbrio
    kind: str            # free | upgrade | ok
    title: str
    why: str
    priority: int        # menor = primeiro
    page: str | None = None


@dataclass
class Bottleneck:
    who: str             # gpu | cpu | none | unknown
    gpu_share: float     # fração do tempo de jogo limitado pela GPU
    cpu_share: float
    minutes: float
    text: str


def fps_target(f: Facts) -> float:
    """FPS que o monitor consegue mostrar (o máximo dele, não o modo atual) — acima disto não há gargalo."""
    return max(60.0, (f.monitor_max_hz or f.monitor_hz or 60) * 0.95)


def bottleneck(f: Facts) -> Bottleneck:
    games = [g for g in f.games if g.gpu_load is not None and g.minutes > 0]
    total = sum(g.minutes for g in games)
    if total < MIN_MINUTES:
        return Bottleneck("unknown", 0, 0, total, "Ainda há pouco tempo de jogo registado para saber o que limita "
                                                  f"o PC nos jogos (precisa de {MIN_MINUTES} min com o Nexo aberto).")
    target = fps_target(f)
    gpu_t = cpu_t = 0.0
    for g in games:
        if g.gpu_load >= GPU_BOUND:
            gpu_t += g.minutes
        elif g.gpu_load < GPU_IDLE and (g.fps_avg is None or g.fps_avg < target):
            cpu_t += g.minutes
    gs, cs = gpu_t / total, cpu_t / total
    if gs >= 0.5 and gs >= cs:
        return Bottleneck("gpu", gs, cs, total, f"Nos jogos, a placa gráfica esteve no limite em {gs * 100:.0f} % "
                                                f"do tempo — é ela que decide o FPS.")
    if cs >= 0.5:
        return Bottleneck("cpu", gs, cs, total, f"Nos jogos, a placa gráfica ficou folgada (abaixo de {GPU_IDLE} %) "
                                                f"com FPS abaixo de {target:.0f} em {cs * 100:.0f} % do tempo — "
                                                "o processador (ou o próprio jogo) não a consegue alimentar.")
    return Bottleneck("none", gs, cs, total, "Nos jogos, nem a CPU nem a placa gráfica limitam de forma clara "
                                             "(o FPS está perto do monitor ou limitado pelo jogo).")


def _join(parts: list[str]) -> str:
    """Frases juntas — cada uma traduzida à parte (a junção não existe no catálogo)."""
    from .i18n import tr
    return " ".join(tr(p) for p in parts)


def advise(f: Facts) -> tuple[Bottleneck, list[Advice]]:
    out: list[Advice] = []
    b = bottleneck(f)
    played = [g for g in f.games if g.minutes > 0]

    # ------------------------------------------------------------ grátis
    if f.ram_xmp_off:
        what = f"{f.ram_current} MT/s em vez de {f.ram_rated}" if f.ram_current and f.ram_rated else "abaixo da velocidade"
        out.append(Advice("Memória", "free", "Ligar o XMP/EXPO no BIOS",
                          f"A memória está a {what}. Ligar o perfil XMP (Intel) ou EXPO/DOCP (AMD) dá mais "
                          "desempenho sem gastar nada — sobretudo nos jogos limitados pela CPU.", 0, "Informação"))
    if f.monitor_hz and f.monitor_max_hz and f.monitor_hz < f.monitor_max_hz * 0.95:
        out.append(Advice("Monitor", "free", f"Pôr o monitor a {f.monitor_max_hz:.0f} Hz",
                          f"Está a {f.monitor_hz:.0f} Hz. Mude nas definições de ecrã (e use um cabo DisplayPort ou "
                          "HDMI 2.0+).", 1, "Informação"))
    if f.throttle_cpu or f.throttle_gpu:
        who = ("O processador e a placa gráfica baixaram" if f.throttle_cpu and f.throttle_gpu else
               "O processador baixou" if f.throttle_cpu else "A placa gráfica baixou")
        out.append(Advice("Refrigeração", "free", "Baixar as temperaturas", _join([
            f"{who} o clock por temperatura este mês.",
            "Limpe o pó, confirme as ventoinhas e a pasta térmica — perde-se desempenho sem dar por isso."]),
            2, "Fiabilidade"))

    # ------------------------------------------------------------ disco
    if f.sys_disk == "HDD":
        out.append(Advice("Disco", "upgrade", "Trocar o disco do sistema por um SSD",
                          "O sistema está num disco rígido (HDD). Um SSD (de preferência NVMe) é a melhoria que "
                          "mais se nota: arranque, programas e carregamentos dos jogos várias vezes mais rápidos.",
                          10))

    # ------------------------------------------------------------ memória
    ram_full = [g for g in played if g.ram_max is not None and g.ram_max >= 90 and g.minutes >= 5]
    if f.ram_gb and f.ram_gb < 7.5:
        out.append(Advice("Memória", "upgrade", "Mais memória RAM (16 GB)",
                          f"Tem {f.ram_gb:.0f} GB — pouco para o Windows/Linux atual com navegador e jogos abertos. "
                          "16 GB (2 módulos iguais, dual channel) é o mínimo recomendado hoje.", 11))
    elif ram_full or (f.ram_gb and f.ram_gb < 15 and played):
        why = (f"A RAM chegou aos {max(g.ram_max for g in ram_full):.0f} % em {ram_full[0].game}."
               if ram_full else f"Tem {f.ram_gb:.0f} GB.")
        out.append(Advice("Memória", "upgrade", "Mais memória RAM", _join([
            why, f"Quando a RAM enche, o sistema usa o disco e o jogo engasga. Passar para "
                 f"{32 if f.ram_gb >= 15 else 16} GB resolve."]), 14 if ram_full else 22))

    # ------------------------------------------------------------ placa gráfica
    vram_full = [g for g in played if g.vram_max is not None and g.vram_max >= 95 and g.minutes >= 5]
    gpu_weak = f.gpu_score is not None and f.gpu_score < GPU_LOW
    if b.who == "gpu" or gpu_weak:
        slow = [g for g in played if g.fps_avg is not None and g.fps_avg < 60]
        why = [b.text] if b.who == "gpu" else []
        if gpu_weak:
            why.append(f"No benchmark fez {f.gpu_score:.0f} pontos em 1080p (uma RX 6500 XT faz ~1500).")
        if slow:
            why.append(f"FPS médio abaixo de 60 em: {', '.join(g.game for g in slow[:3])}.")
        elif b.who == "gpu" and not gpu_weak:
            fps = [g.fps_avg for g in played if g.fps_avg is not None]
            if fps:
                why.append(f"Os jogos já correm a ~{sum(fps) / len(fps):.0f} FPS em média: só vale a pena se quiser "
                           "mais FPS ou mais qualidade gráfica.")
        if vram_full:
            why.append("Escolha uma placa com pelo menos 8 GB de VRAM (a memória da atual encheu nos jogos).")
        elif f.vram_gb and f.vram_gb < 6:
            why.append(f"Escolha uma placa com pelo menos 8 GB de VRAM (a atual tem {f.vram_gb:.0f} GB).")
        out.append(Advice("Placa gráfica", "upgrade", "Placa gráfica mais potente", _join(why),
                          12 if (b.who == "gpu" and slow) or gpu_weak else 20))
    elif vram_full:
        out.append(Advice("Placa gráfica", "upgrade", "Placa gráfica com mais VRAM",
                          f"A memória da placa gráfica encheu em {vram_full[0].game}: baixe a qualidade das texturas "
                          "ou, numa próxima placa, escolha uma com mais VRAM.", 24))

    # ------------------------------------------------------------ processador
    cpu_weak = ((f.cpu_multi is not None and f.cpu_multi < CPU_MULTI_LOW)
                or (f.cpu_single is not None and f.cpu_single < CPU_SINGLE_LOW))
    few_threads = 0 < f.threads < 8
    if b.who == "cpu" or cpu_weak or few_threads:
        why = [b.text] if b.who == "cpu" else []
        if cpu_weak:
            parts = []
            if f.cpu_multi is not None:
                parts.append(f"{f.cpu_multi:.0f} multi-core")
            if f.cpu_single is not None:
                parts.append(f"{f.cpu_single:.0f} single-core")
            why.append(f"No benchmark fez {' / '.join(parts)} (um i5-12400F faz ~1290 / 196).")
        if few_threads:
            why.append(f"Tem {f.threads} threads — muitos jogos atuais querem 8 ou mais.")
        if f.ram_xmp_off:
            why.append("Antes de trocar, ligue o XMP: a CPU depende muito da velocidade da memória.")
        out.append(Advice("CPU", "upgrade", "Processador mais rápido", _join(why),
                          13 if b.who == "cpu" else 21))

    upgrades = [a for a in out if a.kind == "upgrade"]
    if not upgrades:
        if b.who == "unknown" and (f.cpu_multi is None or f.gpu_score is None):
            txt = ("Não há nada que precise claramente de ser trocado. Jogue um pouco com o Nexo aberto e faça os "
                   "benchmarks (CPU e placa gráfica) para uma recomendação mais precisa.")
        elif b.who == "unknown":
            txt = ("Não há nada que precise claramente de ser trocado. Jogue um pouco com o Nexo aberto para saber "
                   "o que limita o PC nos jogos.")
        else:
            txt = ("O PC está equilibrado: nenhuma peça limita claramente as outras. Para mais FPS, a melhoria "
                   "com mais efeito costuma ser a placa gráfica.")
        out.append(Advice("Equilíbrio", "ok", "Nada urgente para trocar", txt, 50))
    out.sort(key=lambda a: a.priority)
    return b, out


# =========================================================================== recolha
def _sys_disk_kind() -> str:
    from .util import IS_LINUX, IS_WIN, ps_json, run, which
    if IS_LINUX and which("findmnt") and which("lsblk"):
        code, src = run(["findmnt", "-no", "SOURCE", "/"], timeout=5)
        dev = src.strip().split("[")[0]
        if code != 0 or not dev.startswith("/dev/"):
            return ""
        code, out = run(["lsblk", "-sno", "NAME,ROTA,TYPE", dev], timeout=5)   # sobe até ao disco (LUKS/LVM)
        for ln in out.splitlines()[::-1]:
            parts = ln.replace("└─", "").replace("├─", "").split()
            if len(parts) >= 3 and parts[2] == "disk":
                if parts[1] == "1":
                    return "HDD"
                return "NVMe" if parts[0].startswith("nvme") else "SSD"
        return ""
    if IS_WIN:
        d = ps_json("$n = (Get-Partition -DriveLetter C).DiskNumber; Get-PhysicalDisk | Where-Object "
                    "{ $_.DeviceId -eq \"$n\" } | Select-Object MediaType,BusType | ConvertTo-Json", timeout=20)
        if isinstance(d, dict):
            mt, bus = str(d.get("MediaType", "")), str(d.get("BusType", ""))
            if mt in ("3", "HDD"):
                return "HDD"
            if bus in ("17", "NVMe"):
                return "NVMe"
            if mt in ("4", "SSD"):
                return "SSD"
    return ""


def _bench() -> tuple[float | None, float | None, float | None]:
    """Melhor resultado recente de cada teste (o mais recente com a mesma qualidade conta igual)."""
    from .util import load_json
    hist = load_json("bench_history.json", []) or []
    multi = single = gpu = None
    for h in hist if isinstance(hist, list) else []:
        try:
            s = float(h.get("score") or 0)
        except (TypeError, ValueError):
            continue
        mode = h.get("mode", "")
        if mode == "Multi-core":
            multi = s
        elif mode == "Single-core":
            single = s
        elif mode == "Placa gráfica" and str(h.get("quality", "")).startswith("1080"):
            gpu = s
    return multi, single, gpu


def gather(days: int = 90) -> Facts:
    import psutil

    from . import ramspeed, sessions, sysinfo, throttle
    f = Facts()
    f.cpu = sysinfo.cpu_model()
    f.cores = psutil.cpu_count(False) or 0
    f.threads = psutil.cpu_count(True) or 0
    f.ram_gb = psutil.virtual_memory().total / 1024**3
    mods = ramspeed.cached()
    f.ram_kind = "/".join(sorted({m.kind for m in mods if m.kind}))
    v = ramspeed.check(mods)
    if v and v.kind == "warn":
        f.ram_xmp_off, f.ram_current, f.ram_rated = True, v.current, v.rated
    try:
        gpus = sysinfo.list_gpus() if not sysinfo.IS_WIN else []
    except Exception:  # noqa: BLE001
        gpus = []
    dedicated = [g for g in gpus if g.get("vram")]
    if dedicated:
        g = max(dedicated, key=lambda x: x["vram"])
        f.gpu, f.vram_gb = g["name"], g["vram"] / 1024**3
    else:
        f.gpu = sysinfo.summary().get("gpu", "") if sysinfo.IS_WIN else (gpus[0]["name"] if gpus else "")
        from .gpustress import vram_total_mb
        mb = vram_total_mb()
        f.vram_gb = mb / 1024 if mb else None
    f.sys_disk = _sys_disk_kind()
    f.cpu_multi, f.cpu_single, f.gpu_score = _bench()
    try:
        from . import display
        mons = display.cached()
        if mons:
            m = max(mons, key=lambda x: x.hz or 0)
            f.monitor_hz, f.monitor_max_hz = m.hz, m.max_hz
    except Exception:  # noqa: BLE001
        pass
    for ep in throttle.recent(30):
        if ep.comp == "cpu":
            f.throttle_cpu += 1
        elif ep.comp == "gpu":
            f.throttle_gpu += 1
    acc: dict[str, dict] = {}
    for s in sessions.since(time.time() - days * 86400):
        a = acc.setdefault(s.game, {"m": 0.0, "cpu": [0.0, 0.0], "gpu": [0.0, 0.0], "fps": [0.0, 0.0],
                                    "low": [0.0, 0.0], "vram": None, "ram": None})
        m = s.minutes
        a["m"] += m
        for k, val in (("cpu", s.cpu_load), ("gpu", s.gpu_load), ("fps", s.fps_avg), ("low", s.fps_low1)):
            if val is not None:
                a[k][0] += val * m
                a[k][1] += m
        for k, val in (("vram", s.vram_max), ("ram", s.ram_max)):
            if val is not None:
                a[k] = max(a[k] or 0, val)
    wavg = lambda p: p[0] / p[1] if p[1] else None  # noqa: E731
    f.games = sorted((GameLoad(g, a["m"], wavg(a["cpu"]), wavg(a["gpu"]), wavg(a["fps"]), wavg(a["low"]),
                               a["vram"], a["ram"]) for g, a in acc.items()), key=lambda x: -x.minutes)
    return f
