"""Leitura de sensores em tempo real (temperatura, carga, clocks, ventoinhas, consumo...)."""
from __future__ import annotations

import glob
import os
import subprocess
import threading
import time
from dataclasses import dataclass

import psutil

from .util import _NO_WINDOW, IS_LINUX, IS_WIN, as_list, ps_json, read_text, run, which


@dataclass
class Reading:
    group: str      # "CPU", "GPU", "Memória", "Disco", "Rede", "Placa-mãe", ...
    name: str
    value: float
    unit: str
    kind: str       # temp | load | freq | fan | power | volt | mem | rate

    @property
    def key(self) -> str:
        return f"{self.group}/{self.name}"


KIND_LABELS = {
    "temp": "Temperatura", "load": "Carga", "freq": "Clock", "fan": "Ventoinha",
    "power": "Consumo", "volt": "Tensão", "mem": "Memória", "rate": "Transferência",
}

_CPU_HWMON = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
_GPU_HWMON = ("amdgpu", "nouveau", "radeon", "i915", "xe")


def _hwmon_group(name: str) -> str:
    if name in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
        return "CPU"
    if name in _GPU_HWMON:
        return "GPU"
    if name == "nvme" or name.startswith("drivetemp"):
        return "Disco"
    if name.startswith("spd") or name.startswith("jc42"):
        return "Memória"
    if name in ("iwlwifi", "r8169") or name.startswith(("iwlwifi", "r8169", "mt7", "ath")):
        return "Rede"
    if name in ("acpitz",):
        return "ACPI"
    if name.startswith(("nct", "it87", "asus", "dell", "thinkpad", "f71")):
        return "Placa-mãe"
    if name in ("BAT0", "BAT1", "AC", "ADP1"):
        return "Bateria"
    return name


class SensorReader:
    """Chamar read() periodicamente (ex.: 1×/s) a partir de uma thread de trabalho.

    Otimizações: a lista de ficheiros do hwmon e os rótulos são lidos uma vez (e revistos a cada
    minuto); chips lentos (NVMe/SPD/drivetemp fazem uma consulta ao dispositivo em cada leitura) só
    são lidos numa thread à parte a cada SLOW_EVERY segundos; NVIDIA e Windows usam um processo persistente em vez de
    lançar um processo novo a cada leitura."""

    SLOW_EVERY = 5.0        # segundos entre leituras dos chips lentos (numa thread à parte)
    RESCAN_EVERY = 60.0     # segundos entre novas pesquisas de sensores (hotplug)

    def __init__(self) -> None:
        self._last_t = time.monotonic()
        self._last_disk = psutil.disk_io_counters()
        self._last_net = psutil.net_io_counters()
        psutil.cpu_percent(percpu=True)  # inicia o contador
        self._tick = 0
        self._hw_layout: list[tuple] = []
        self._hw_scanned = 0.0
        self._slow_cache: dict[str, Reading] = {}
        self._slow_thread: threading.Thread | None = None
        self._slow_ready = threading.Event()
        self._drm_cards: list[str] | None = None
        self._rapl: tuple[int, float] | None = None
        self._win_cache: list[Reading] = []
        self._win_proc = None
        self._nv_cache: list[Reading] = []
        self._nv_proc = None
        self._stop = threading.Event()
        if IS_WIN:
            threading.Thread(target=self._win_loop, daemon=True).start()
        if which("nvidia-smi"):
            threading.Thread(target=self._nv_loop, daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        for p in (self._win_proc, self._nv_proc):
            if p is not None:
                try:
                    p.kill()
                except OSError:
                    pass

    # ------------------------------------------------------------------ geral
    def read(self) -> list[Reading]:
        out: list[Reading] = []
        now = time.monotonic()
        dt = max(now - self._last_t, 1e-3)
        self._last_t = now
        self._tick += 1

        per = psutil.cpu_percent(percpu=True)
        out.append(Reading("CPU", "Carga total", sum(per) / len(per), "%", "load"))
        out.append(Reading("CPU", "Núcleo mais ocupado", max(per), "%", "load"))
        for i, p in enumerate(per):
            out.append(Reading("CPU", f"Carga thread #{i}", p, "%", "load"))
        try:
            freqs = psutil.cpu_freq(percpu=True)
            if freqs:
                cur = [f.current for f in freqs]
                out.append(Reading("CPU", "Clock médio", sum(cur) / len(cur), "MHz", "freq"))
                out.append(Reading("CPU", "Clock máximo", max(cur), "MHz", "freq"))
        except (OSError, RuntimeError, NotImplementedError, ValueError):
            pass

        vm = psutil.virtual_memory()
        out.append(Reading("Memória", "RAM em uso", vm.percent, "%", "load"))
        out.append(Reading("Memória", "RAM usada", (vm.total - vm.available) / 1024**3, "GB", "mem"))
        try:
            sw = psutil.swap_memory()
        except Exception:  # Windows com contadores de desempenho desativados
            sw = None
        if sw and sw.total:
            out.append(Reading("Memória", "Swap em uso", sw.percent, "%", "load"))

        d = psutil.disk_io_counters()
        if d and self._last_disk:
            out.append(Reading("Disco", "Leitura", (d.read_bytes - self._last_disk.read_bytes) / dt / 1024**2, "MB/s", "rate"))
            out.append(Reading("Disco", "Escrita", (d.write_bytes - self._last_disk.write_bytes) / dt / 1024**2, "MB/s", "rate"))
        self._last_disk = d
        n = psutil.net_io_counters()
        if n and self._last_net:
            out.append(Reading("Rede", "Download", (n.bytes_recv - self._last_net.bytes_recv) / dt / 1024**2, "MB/s", "rate"))
            out.append(Reading("Rede", "Upload", (n.bytes_sent - self._last_net.bytes_sent) / dt / 1024**2, "MB/s", "rate"))
        self._last_net = n

        if self._tick % 5 == 1:
            try:
                bat = psutil.sensors_battery()
            except Exception:
                bat = None
            self._bat = bat
        bat = getattr(self, "_bat", None)
        if bat:
            out.append(Reading("Bateria", "Carga" + (" (a carregar)" if bat.power_plugged else ""), bat.percent, "%", "load"))

        if IS_LINUX:
            out += self._linux_hwmon()
            out += self._linux_gpu()
        if IS_WIN:
            out += list(self._win_cache)
        out += list(self._nv_cache)
        return out

    # ------------------------------------------------------------------ Linux
    _SLOW_CHIPS = ("nvme", "drivetemp", "spd", "jc42")

    def _scan_hwmon(self) -> None:
        layout = []
        for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            chip = read_text(hw + "/name") or os.path.basename(hw)
            group = _hwmon_group(chip)
            slow = chip.startswith(self._SLOW_CHIPS)
            for f in sorted(glob.glob(hw + "/*_input")) + sorted(glob.glob(hw + "/power*_average")):
                base = os.path.basename(f)
                idx = base.split("_")[0]
                kind_raw = "".join(c for c in idx if c.isalpha())
                if kind_raw not in ("temp", "fan", "in", "power", "freq", "curr"):
                    continue
                label = read_text(f"{hw}/{idx}_label") or idx
                layout.append((f, group, kind_raw, idx, label, slow))
        self._hw_layout = layout
        self._hw_scanned = time.monotonic()

    @staticmethod
    def _convert(group, kind_raw, idx, label, v) -> Reading | None:
        if kind_raw == "temp":
            if v <= 0 or v > 150000:
                return None
            return Reading(group, label if group != "ACPI" else f"Zona {label}", v / 1000, "°C", "temp")
        if kind_raw == "fan":
            return Reading(group, f"Ventoinha {label}", v, "RPM", "fan")
        if kind_raw == "in":
            return Reading(group, f"Tensão {label}", v / 1000, "V", "volt")
        if kind_raw == "power":
            return Reading(group, f"Consumo {label if label != idx else ''}".strip(), v / 1e6, "W", "power")
        if kind_raw == "freq":
            return Reading(group, f"Clock {label}", v / 1e6, "MHz", "freq")
        if kind_raw == "curr":
            return Reading(group, f"Corrente {label}", v / 1000, "A", "volt")
        return None

    def _slow_loop(self) -> None:
        """Chips lentos (NVMe/SPD/drivetemp) lidos numa thread própria a cada SLOW_EVERY s:
        cada leitura faz uma consulta ao dispositivo (vários ms) e não deve atrasar o ciclo principal."""
        while not self._stop.is_set():
            cache: dict[str, Reading] = {}
            for f, group, kind_raw, idx, label, slow in list(self._hw_layout):
                if not slow:
                    continue
                try:
                    with open(f, "rb") as fh:
                        v = float(fh.read())
                except (OSError, ValueError):
                    continue
                r = self._convert(group, kind_raw, idx, label, v)
                if r is not None:
                    cache[f] = r
            self._slow_cache = cache
            self._slow_ready.set()
            self._stop.wait(self.SLOW_EVERY)

    def _linux_hwmon(self) -> list[Reading]:
        if not self._hw_layout or time.monotonic() - self._hw_scanned > self.RESCAN_EVERY:
            self._scan_hwmon()
            if self._slow_thread is None and any(e[5] for e in self._hw_layout):
                self._slow_thread = threading.Thread(target=self._slow_loop, daemon=True, name="sensors-slow")
                self._slow_thread.start()
                self._slow_ready.wait(1.0)  # primeira leitura já com os valores lentos
        out: list[Reading] = []
        power_seen: set[tuple[str, str]] = set()
        slow_cache = self._slow_cache
        for f, group, kind_raw, idx, label, slow in self._hw_layout:
            if slow:
                r = slow_cache.get(f)
                if r is not None:
                    out.append(Reading(r.group, r.name, r.value, r.unit, r.kind))
                continue
            try:
                with open(f, "rb") as fh:
                    v = float(fh.read())
            except (OSError, ValueError):
                continue
            r = self._convert(group, kind_raw, idx, label, v)
            if r is None:
                continue
            if r.kind == "power":
                # amdgpu expõe power1_average e power1_input — evita duplicados
                if (group, r.name) in power_seen:
                    continue
                power_seen.add((group, r.name))
            out.append(r)
        # Intel RAPL (consumo do pacote da CPU) — só legível como root na maioria das distros
        rapl = "/sys/class/powercap/intel-rapl:0/energy_uj"
        if os.access(rapl, os.R_OK):
            try:
                e = int(read_text(rapl))
                t = time.monotonic()
                if self._rapl:
                    e0, t0 = self._rapl
                    if e >= e0:
                        out.append(Reading("CPU", "Consumo do pacote", (e - e0) / 1e6 / (t - t0), "W", "power"))
                self._rapl = (e, t)
            except ValueError:
                pass
        # nomes repetidos (ex.: dois módulos de RAM com "temp1") ficam "temp1 #2"
        seen: dict[str, int] = {}
        for r in out:
            k = r.key
            seen[k] = seen.get(k, 0) + 1
            if seen[k] > 1:
                r.name = f"{r.name} #{seen[k]}"
        return out

    def _linux_gpu(self) -> list[Reading]:
        if self._drm_cards is None or self._tick % 60 == 0:
            self._drm_cards = [c for c in sorted(glob.glob("/sys/class/drm/card[0-9]/device"))
                               if os.path.exists(c + "/gpu_busy_percent") or os.path.exists(c + "/mem_info_vram_used")]
        out: list[Reading] = []
        for card in self._drm_cards:
            busy = read_text(card + "/gpu_busy_percent")
            if busy.isdigit():
                out.append(Reading("GPU", "Carga", float(busy), "%", "load"))
            used = read_text(card + "/mem_info_vram_used")
            total = read_text(card + "/mem_info_vram_total")
            if used.isdigit() and total.isdigit() and int(total):
                out.append(Reading("GPU", "VRAM usada", int(used) / 1024**2, "MB", "mem"))
                out.append(Reading("GPU", "VRAM em uso", int(used) * 100 / int(total), "%", "load"))
            mbusy = read_text(card + "/mem_busy_percent")
            if mbusy.isdigit():
                out.append(Reading("GPU", "Carga do controlador de memória", float(mbusy), "%", "load"))
        return out

    # ------------------------------------------------------------------ NVIDIA (ambos)
    _NV_FIELDS = ("temperature.gpu,utilization.gpu,clocks.gr,clocks.mem,power.draw,memory.used,"
                  "memory.total,fan.speed")

    @staticmethod
    def _nv_parse(lines: list[str]) -> list[Reading]:
        def num(s):
            try:
                return float(s)
            except ValueError:
                return None
        res: list[Reading] = []
        for i, line in enumerate(lines):
            vals = [x.strip() for x in line.split(",")]
            g = "GPU" if i == 0 else f"GPU {i + 1}"
            t, u, cg, cm, p, mu, mt, fan = (num(x) for x in (vals + [""] * 8)[:8])
            for v, name, unit, kind in ((t, "Temperatura", "°C", "temp"), (u, "Carga", "%", "load"),
                                        (cg, "Clock do núcleo", "MHz", "freq"), (cm, "Clock da memória", "MHz", "freq"),
                                        (p, "Consumo", "W", "power"), (mu, "VRAM usada", "MB", "mem"),
                                        (fan, "Ventoinha", "%", "fan")):
                if v is not None:
                    res.append(Reading(g, name, v, unit, kind))
            if mu is not None and mt:
                res.append(Reading(g, "VRAM em uso", mu * 100 / mt, "%", "load"))
        return res

    def _nv_loop(self) -> None:
        """Um único nvidia-smi em modo contínuo (-lms) em vez de um processo novo por segundo."""
        code, out = run(["nvidia-smi", "-L"], timeout=5)
        if code != 0:
            return
        n_gpus = max(1, sum(1 for ln in out.splitlines() if ln.startswith("GPU ")))
        while not self._stop.is_set():
            try:
                self._nv_proc = p = subprocess.Popen(
                    ["nvidia-smi", f"--query-gpu={self._NV_FIELDS}", "--format=csv,noheader,nounits", "-lms", "1000"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
                    creationflags=_NO_WINDOW)
            except OSError:
                return
            batch: list[str] = []
            for line in p.stdout:  # type: ignore[union-attr]
                if self._stop.is_set():
                    break
                if line.strip():
                    batch.append(line)
                if len(batch) >= n_gpus:
                    self._nv_cache = self._nv_parse(batch)
                    batch = []
            try:
                p.kill()
            except OSError:
                pass
            self._nv_cache = []
            self._stop.wait(5.0)  # se o processo morrer, tenta de novo daqui a pouco

    # ------------------------------------------------------------------ Windows
    _WIN_SCRIPT = r"""
$o = @{}
foreach ($ns in 'root/LibreHardwareMonitor','root/OpenHardwareMonitor') {
  try { $s = Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop |
        Select Name,SensorType,Value,Parent; if ($s) { $o.lhm = $s; break } } catch {}
}
if (-not $o.lhm) {
  try { $o.acpi = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop |
        Select InstanceName,CurrentTemperature } catch {}
}
try { $o.gpu = ((Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -ErrorAction Stop).CounterSamples |
      Measure-Object CookedValue -Sum).Sum } catch {}
$o
"""

    def _win_parse(self, data) -> list[Reading]:
        kinds = {"Temperature": ("temp", "°C"), "Load": ("load", "%"), "Clock": ("freq", "MHz"),
                 "Fan": ("fan", "RPM"), "Power": ("power", "W"), "Voltage": ("volt", "V")}
        res: list[Reading] = []
        if not isinstance(data, dict):
            return res
        for s in as_list(data.get("lhm")):
            k = kinds.get(s.get("SensorType"))
            if not k or s.get("Value") is None:
                continue
            parent = str(s.get("Parent", ""))
            group = ("CPU" if "cpu" in parent else "GPU" if "gpu" in parent else
                     "Memória" if "ram" in parent else "Disco" if ("nvme" in parent or "hdd" in parent) else "Placa-mãe")
            if k[0] == "load" and group in ("CPU", "Memória") and s["Name"] in ("CPU Total", "Memory"):
                continue  # já temos pelo psutil
            res.append(Reading(group, s["Name"], float(s["Value"]), k[1], k[0]))
        for z in as_list(data.get("acpi")):
            t = (z.get("CurrentTemperature") or 0) / 10 - 273.15
            if 0 < t < 130:
                zone = str(z.get("InstanceName", "")).split("\\")[-1]
                res.append(Reading("ACPI", f"Zona {zone}", t, "°C", "temp"))
        if data.get("gpu") is not None and not any(r.group == "GPU" and r.kind == "load" for r in res):
            res.append(Reading("GPU", "Carga", min(100.0, float(data["gpu"])), "%", "load"))
        return res

    def _win_loop(self) -> None:
        """Um único PowerShell em ciclo (arrancar o PowerShell custa ~0,5 s de CPU cada vez)."""
        import json
        exe = which("pwsh") or which("powershell") or "powershell"
        import base64
        loop = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8\nwhile ($true) {\n$r = & {\n"
                + self._WIN_SCRIPT + "\n}\n[Console]::Out.WriteLine(($r | ConvertTo-Json -Depth 4 -Compress))\n"
                "[Console]::Out.Flush()\nStart-Sleep -Seconds 2\n}")
        enc = base64.b64encode(loop.encode("utf-16-le")).decode("ascii")
        while not self._stop.is_set():
            try:
                self._win_proc = p = subprocess.Popen(
                    [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    encoding="utf-8", errors="replace", bufsize=1, creationflags=_NO_WINDOW)
            except OSError:
                # sem processo persistente: volta ao método antigo
                while not self._stop.is_set():
                    self._win_cache = self._win_parse(ps_json(self._WIN_SCRIPT, timeout=20))
                    self._stop.wait(2.0)
                return
            for line in p.stdout:  # type: ignore[union-attr]
                if self._stop.is_set():
                    break
                i = min([x for x in (line.find("{"), line.find("[")) if x >= 0], default=-1)
                if i < 0:
                    continue
                try:
                    self._win_cache = self._win_parse(json.loads(line[i:]))
                except ValueError:
                    continue
            try:
                p.kill()
            except OSError:
                pass
            self._stop.wait(3.0)


# ---------------------------------------------------------------------- helpers
def pick_cpu_temp(readings: list[Reading]) -> float | None:
    """Escolhe a melhor leitura de temperatura da CPU."""
    pref = ("Package id 0", "Tctl", "Tdie", "CPU Package", "Core (Tctl/Tdie)", "CPU")
    temps = [r for r in readings if r.kind == "temp" and r.group == "CPU"]
    for p in pref:
        for r in temps:
            if r.name.startswith(p):
                return r.value
    if temps:
        return max(r.value for r in temps)
    acpi = [r.value for r in readings if r.kind == "temp" and r.group == "ACPI"]
    return max(acpi) if acpi else None


def pick_gpu_temp(readings: list[Reading]) -> float | None:
    pref = ("edge", "Temperatura", "GPU Core", "junction")
    temps = [r for r in readings if r.kind == "temp" and r.group == "GPU"]
    for p in pref:
        for r in temps:
            if r.name.startswith(p):
                return r.value
    return temps[0].value if temps else None


def pick(readings: list[Reading], group: str, name: str) -> float | None:
    for r in readings:
        if r.group == group and r.name == name:
            return r.value
    return None


def pick_power(readings: list[Reading], group: str) -> float | None:
    for r in readings:
        if r.group == group and r.kind == "power":
            return r.value
    return None
