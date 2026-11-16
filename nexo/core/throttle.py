"""Deteção de throttling: o processador ou a placa gráfica a baixar o clock por temperatura.

Como o hardware não o diz da mesma maneira em todo o lado, há duas fontes:
  • sinal direto — Linux com Intel: contadores do kernel em
    /sys/devices/system/cpu/cpu*/thermal_throttle/{core,package}_throttle_count (sobem a cada limitação);
  • heurística — para tudo o resto (AMD, NVIDIA, Windows): temperatura perto do limite do componente,
    carga alta e clock claramente abaixo do máximo que o próprio componente atingiu nesta sessão, durante
    vários segundos seguidos. Picos curtos não contam.

O detetor é puro (recebe amostras, devolve início/fim de episódios) para poder ser testado; os episódios
ficam em config_dir()/throttling.json (os últimos 100)."""
from __future__ import annotations

import glob
import time
from dataclasses import asdict, dataclass, field

from .util import IS_LINUX, _save_lock, load_json, read_text, save_json, which

LOG = "throttling.json"
CPU_DEFAULT_LIMIT = 95.0
GPU_DEFAULT_LIMIT = 90.0
NVIDIA_LIMIT = 83.0      # temperatura a que as GeForce começam a baixar o clock (alvo por omissão)
NAMES = {"cpu": "Processador", "gpu": "Placa gráfica"}
WHO = {"cpu": "O processador", "gpu": "A placa gráfica"}


@dataclass
class Episode:
    comp: str                  # cpu | gpu
    start: float
    end: float | None = None
    reason: str = "temperatura"
    peak_temp: float | None = None
    clock_drop: float | None = None    # % abaixo do máximo
    game: str | None = None

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end or time.time()) - self.start)


@dataclass
class _State:
    peak_clock: float = 0.0
    hits: int = 0
    calm: int = 0
    episode: Episode | None = None
    lowest_ratio: float = 1.0
    temps: list = field(default_factory=list)


class Detector:
    SUSTAIN = 8        # amostras seguidas (≈ s) a cumprir a condição antes de contar
    RELEASE = 6        # amostras seguidas sem a condição para dar o episódio por terminado
    MARGIN = 4.0       # °C abaixo do limite em que já conta como "perto"
    MIN_LOAD = 60.0
    CLOCK_RATIO = 0.9

    def __init__(self, cpu_limit: float = CPU_DEFAULT_LIMIT, gpu_limit: float = GPU_DEFAULT_LIMIT):
        self.limits = {"cpu": cpu_limit, "gpu": gpu_limit}
        self.st = {"cpu": _State(), "gpu": _State()}
        self._counter: int | None = None

    def active(self) -> dict[str, Episode]:
        return {k: s.episode for k, s in self.st.items() if s.episode is not None}

    def feed(self, sample: dict, now: float | None = None, counter: int | None = None,
             game: str | None = None) -> list[tuple[str, Episode]]:
        """sample: cpu_temp, cpu_load, cpu_clock, gpu_temp, gpu_load, gpu_clock (None = sem leitura).
        counter: soma dos contadores de throttling do kernel (Intel) ou None.
        Devolve [("start"|"end", episódio)]."""
        now = time.time() if now is None else now
        out: list[tuple[str, Episode]] = []
        hard = False
        if counter is not None:
            if self._counter is not None and counter > self._counter:
                hard = True
            self._counter = counter
        for comp in ("cpu", "gpu"):
            t, load, clk = sample.get(f"{comp}_temp"), sample.get(f"{comp}_load"), sample.get(f"{comp}_clock")
            s = self.st[comp]
            if clk and load is not None and load >= 50:
                # máximo atingido sob carga; desce muito devagar (o boost depende da temperatura ambiente)
                s.peak_clock = max(clk, s.peak_clock * 0.9995)
            ratio = (clk / s.peak_clock) if clk and s.peak_clock else 1.0
            lim = self.limits[comp]
            cond = (t is not None and load is not None and t >= lim - self.MARGIN and load >= self.MIN_LOAD
                    and ratio <= self.CLOCK_RATIO)
            direct = comp == "cpu" and hard
            if cond or direct:
                s.hits = self.SUSTAIN if direct else s.hits + 1
                s.calm = 0
                s.lowest_ratio = min(s.lowest_ratio, ratio)
                if t is not None:
                    s.temps.append(t)
                if s.episode is None and s.hits >= self.SUSTAIN:
                    s.episode = Episode(comp, now - (0 if direct else self.SUSTAIN - 1), None,
                                        "temperatura (sinal do processador)" if direct else "temperatura",
                                        max(s.temps) if s.temps else t, None, game)
                    out.append(("start", s.episode))
            else:
                s.hits = 0
                if s.episode is not None:
                    s.calm += 1
                    if s.calm >= self.RELEASE:
                        ep = s.episode
                        ep.end = now - self.RELEASE + 1
                        ep.peak_temp = max(s.temps) if s.temps else ep.peak_temp
                        ep.clock_drop = round((1 - s.lowest_ratio) * 100) if s.lowest_ratio < 1 else None
                        out.append(("end", ep))
                        s.episode, s.calm, s.lowest_ratio, s.temps = None, 0, 1.0, []
                else:
                    s.temps = []
                    s.lowest_ratio = 1.0
        return out


# ----------------------------------------------------------------------------------- sistema
def intel_counter() -> int | None:
    """Soma dos contadores de throttling térmico (Linux, Intel). None se não existirem."""
    if not IS_LINUX:
        return None
    files = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/thermal_throttle/*_throttle_count")
    if not files:
        return None
    total = 0
    for f in files:
        v = read_text(f).strip()
        if v.isdigit():
            total += int(v)
    return total


def _hwmon_crit(names: tuple[str, ...], label_pref: tuple[str, ...] = ()) -> float | None:
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if read_text(h + "/name").strip() not in names:
            continue
        cands = []
        for crit in glob.glob(h + "/temp*_crit"):
            base = crit[:-5]
            lab = read_text(base + "_label").strip().lower()
            v = read_text(crit).strip()
            if v.lstrip("-").isdigit() and 50_000 <= int(v) <= 130_000:
                cands.append((0 if any(lab.startswith(p) for p in label_pref) else 1, int(v) / 1000))
        if cands:
            return sorted(cands)[0][1]
    return None


def limits() -> tuple[float, float]:
    """(limite da CPU, limite da GPU) em °C — lido do hardware quando possível."""
    cpu = gpu = None
    if IS_LINUX:
        cpu = _hwmon_crit(("coretemp",), ("package",))
        if cpu is None and _hwmon_crit(("k10temp", "zenpower")) is not None:
            cpu = 95.0
        gpu = _hwmon_crit(("amdgpu",), ("junction",))
    if gpu is None and which("nvidia-smi"):
        gpu = NVIDIA_LIMIT
    return cpu or CPU_DEFAULT_LIMIT, gpu or GPU_DEFAULT_LIMIT


def sample_from(readings) -> dict:
    """Constrói a amostra a partir das leituras dos sensores (sensors.Reading)."""
    from .sensors import pick, pick_cpu_temp, pick_gpu_temp
    gpu_temp = None
    for r in readings:   # AMD: a temperatura que limita é a junction (ponto mais quente)
        if r.group == "GPU" and r.kind == "temp" and r.name.startswith("junction"):
            gpu_temp = r.value
    if gpu_temp is None:
        gpu_temp = pick_gpu_temp(readings)
    gpu_clock = None
    for name in ("Clock sclk", "Clock do núcleo", "GPU Core"):
        gpu_clock = pick(readings, "GPU", name)
        if gpu_clock is not None:
            break
    return {"cpu_temp": pick_cpu_temp(readings), "cpu_load": pick(readings, "CPU", "Carga total"),
            "cpu_clock": pick(readings, "CPU", "Clock médio"),
            "gpu_temp": gpu_temp, "gpu_load": pick(readings, "GPU", "Carga"), "gpu_clock": gpu_clock}


# ----------------------------------------------------------------------------------- registo
def log_episode(ep: Episode) -> None:
    with _save_lock:
        data = load_json(LOG, [])
        if not isinstance(data, list):
            data = []
        data.append(asdict(ep))
        save_json(LOG, data[-100:])


def recent(days: float = 30, now: float | None = None) -> list[Episode]:
    now = time.time() if now is None else now
    out = []
    for d in load_json(LOG, []) or []:
        try:
            ep = Episode(**d)
        except TypeError:
            continue
        if now - ep.start <= days * 86400:
            out.append(ep)
    return sorted(out, key=lambda e: e.start, reverse=True)


def describe(ep: Episode) -> str:
    who = WHO.get(ep.comp, ep.comp)
    bits = [f"{who} baixou o clock por {ep.reason}"]
    if ep.peak_temp is not None:
        bits.append(f"{ep.peak_temp:.0f} °C")
    if ep.clock_drop:
        bits.append(f"clock −{ep.clock_drop} %")
    if ep.end:
        mins = ep.seconds / 60
        bits.append(f"{mins:.0f} min" if mins >= 1 else f"{ep.seconds:.0f} s")
    if ep.game:
        bits.append(f"durante {ep.game}")
    return " · ".join(bits)


ADVICE = {"cpu": "Verifique o cooler do processador (pó, pasta térmica, se está bem apertado) e a ventilação da caixa.",
          "gpu": "Limpe o pó da placa gráfica, melhore a entrada de ar da caixa ou limite os FPS no jogo."}
