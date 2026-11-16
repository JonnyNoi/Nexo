"""Quanto tempo o PC demora a arrancar — e o que o atrasa.

Linux: `systemd-analyze` (firmware/BIOS, carregador, kernel, initrd, serviços) e `critical-chain` (os
serviços que de facto atrasaram o arranque; o `blame` também lista coisas que correm depois, como o fstrim).
Windows: Visualizador de Eventos, Diagnostics-Performance (ID 100 = tempo de arranque; 101–103 = programas,
controladores e serviços que o tornaram mais lento). Precisa de administrador.

Cada arranque é guardado uma vez (arranque.json); a página Arranque mostra a evolução e o que mudou entre
dois arranques (changes.mark — ex.: programas desativados no arranque)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import changes
from .util import IS_LINUX, IS_WIN, _save_lock, as_list, is_admin, load_json, ps_json, read_text, run, save_json, which

HISTORY = "arranque.json"
SLOW_TOTAL = 60.0       # s — acima disto o arranque é lento (num SSD devia ser bem menos)
SLOW_FIRMWARE = 10.0    # s — tempo no BIOS/UEFI antes de chegar ao sistema


def _n(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


@dataclass
class Delay:
    name: str
    seconds: float
    kind: str = "serviço"   # serviço | programa | controlador


@dataclass
class Boot:
    boot_id: str
    when: float                 # hora do arranque (epoch)
    total: float                # s
    phases: dict[str, float] = field(default_factory=dict)   # firmware, loader, kernel, initrd, userspace / main, post
    delays: list[Delay] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"boot_id": self.boot_id, "when": self.when, "total": self.total, "phases": self.phases,
                "delays": [d.__dict__ for d in self.delays]}

    @staticmethod
    def from_dict(d: dict) -> Boot:
        return Boot(str(d.get("boot_id", "")), float(d.get("when", 0)), float(d.get("total", 0)),
                    dict(d.get("phases") or {}),
                    [Delay(**x) for x in d.get("delays") or [] if isinstance(x, dict) and "name" in x])


PHASE_NAMES = {"firmware": "BIOS/UEFI", "loader": "Carregador", "kernel": "Kernel", "initrd": "initrd",
               "userspace": "Serviços", "main": "Até ao ambiente de trabalho", "post": "Depois do início de sessão"}


# --------------------------------------------------------------------------- Linux
def parse_duration(s: str) -> float:
    """'1min 8.649s' → 68.649; '761ms' → 0.761; '61us' → 0.000061"""
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)\s*(h|min|ms|us|µs|s)\b", s):
        total += float(num) * {"h": 3600, "min": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "µs": 1e-6}[unit]
    return total


def parse_analyze(text: str) -> tuple[float, dict[str, float]] | None:
    line = next((ln for ln in text.splitlines() if "Startup finished in" in ln), "")
    if not line:
        return None
    phases = {}
    head, _, tot = line.partition("=")
    for chunk in head.split("in", 1)[1].split("+"):
        m = re.match(r"\s*(.+?)\s*\((\w+)\)", chunk)
        if m:
            phases[m.group(2)] = round(parse_duration(m.group(1)), 3)
    total = parse_duration(tot) if tot else sum(phases.values())
    return round(total, 3), phases


def parse_chain(text: str, min_s: float = 0.1) -> list[Delay]:
    out = []
    for ln in text.splitlines():
        m = re.search(r"([\w@\\.:-]+\.(?:service|mount|device|socket|target|swap))\s+@\S+.*?\+(.+)$", ln)
        if not m:
            continue
        secs = parse_duration(m.group(2))
        if secs >= min_s:
            out.append(Delay(m.group(1), round(secs, 2)))
    out.sort(key=lambda d: -d.seconds)
    return out


def _linux_current() -> Boot | None:
    if not which("systemd-analyze"):
        return None
    code, out = run(["systemd-analyze", "--no-pager"], timeout=15)
    parsed = parse_analyze(out) if code == 0 else None
    if not parsed:
        return None      # "Bootup is not yet finished" logo a seguir ao arranque
    total, phases = parsed
    _, chain = run(["systemd-analyze", "critical-chain", "--no-pager"], timeout=15)
    try:
        import psutil
        when = psutil.boot_time()
    except Exception:  # noqa: BLE001
        when = time.time()
    return Boot(read_text("/proc/sys/kernel/random/boot_id") or str(int(when)), when, total, phases,
                parse_chain(chain)[:12])


# --------------------------------------------------------------------------- Windows
_PS = r"""
$log='Microsoft-Windows-Diagnostics-Performance/Operational'
$r=@{}
$ev = Get-WinEvent -FilterHashtable @{LogName=$log; Id=100} -MaxEvents 1 -EA SilentlyContinue
if ($ev) { $x=[xml]$ev.ToXml(); $d=@{}; foreach($n in $x.Event.EventData.Data){ $d[$n.Name]=$n.'#text' }
  $r.boot=@{When=$ev.TimeCreated.ToUniversalTime().ToString('o'); BootTime=$d.BootTime; Main=$d.MainPathBootTime;
            Post=$d.BootPostBootTime; Start=$d.BootStartTime} }
$r.slow=@(Get-WinEvent -FilterHashtable @{LogName=$log; Id=101,102,103; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 60 -EA SilentlyContinue |
  ForEach-Object { $x=[xml]$_.ToXml(); $d=@{}; foreach($n in $x.Event.EventData.Data){ $d[$n.Name]=$n.'#text' }
    @{Id=$_.Id; Name=$d.FriendlyName; File=$d.Name; Ms=$d.DegradationTime} })
[pscustomobject]$r
"""


def parse_windows(data: dict | None) -> Boot | None:
    if not data or not isinstance(data.get("boot"), dict):
        return None
    b = data["boot"]
    try:
        total = float(b.get("BootTime") or 0) / 1000
    except ValueError:
        return None
    if total <= 0:
        return None
    from datetime import datetime
    try:
        when = datetime.fromisoformat(str(b.get("When")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        when = time.time()
    phases = {}
    for k, name in (("Main", "main"), ("Post", "post")):
        try:
            phases[name] = round(float(b.get(k) or 0) / 1000, 3)
        except ValueError:
            pass
    kinds = {101: "programa", 102: "controlador", 103: "serviço"}
    worst: dict[str, Delay] = {}
    for s in as_list(data.get("slow")):
        if not isinstance(s, dict):
            continue
        name = (s.get("Name") or s.get("File") or "").strip()
        try:
            secs = float(s.get("Ms") or 0) / 1000
        except ValueError:
            continue
        if name and secs > 0 and (name not in worst or worst[name].seconds < secs):
            worst[name] = Delay(name, round(secs, 2), kinds.get(s.get("Id"), "serviço"))
    delays = sorted(worst.values(), key=lambda d: -d.seconds)[:12]
    return Boot(str(b.get("Start") or b.get("When")), when, round(total, 3), phases, delays)


def _windows_current() -> Boot | None:
    if not is_admin():
        return None
    return parse_windows(ps_json(_PS, timeout=60))


# --------------------------------------------------------------------------- histórico
def current() -> Boot | None:
    if IS_LINUX:
        return _linux_current()
    if IS_WIN:
        return _windows_current()
    return None


def history() -> list[Boot]:
    data = load_json(HISTORY, [])
    out = []
    for d in data if isinstance(data, list) else []:
        if isinstance(d, dict):
            try:
                out.append(Boot.from_dict(d))
            except (TypeError, ValueError):
                continue
    out.sort(key=lambda b: b.when)
    return out


def record(boot: Boot | None = None) -> Boot | None:
    """Guarda o arranque atual (uma vez por arranque). Devolve-o (ou None se ainda não houver dados)."""
    boot = boot or current()
    if boot is None:
        return None
    with _save_lock:
        data = load_json(HISTORY, [])
        if not isinstance(data, list):
            data = []
        data = [d for d in data if isinstance(d, dict) and d.get("boot_id") != boot.boot_id]
        data.append(boot.as_dict())
        data.sort(key=lambda d: d.get("when", 0))
        save_json(HISTORY, data[-200:])
    return boot


@dataclass
class Trend:
    latest: Boot
    baseline: float | None      # média dos arranques anteriores (até 5)
    delta: float | None         # s (negativo = mais rápido)
    changes: list[dict]         # o que mudou desde o arranque anterior

    def text(self) -> str:
        t = f"{_n(self.latest.total)} s"
        if self.baseline is None or self.delta is None:
            return t
        if abs(self.delta) < max(1.0, self.baseline * 0.05):
            out = f"{t} (igual à média dos anteriores)"
        else:
            word = "mais rápido" if self.delta < 0 else "mais lento"
            out = f"{t} — {_n(abs(self.delta))} s {word} do que a média dos anteriores"
        if self.changes:
            out += " · desde o arranque anterior: " + changes.summarize(self.changes)
        return out


def trend(hist: list[Boot] | None = None) -> Trend | None:
    hist = history() if hist is None else hist
    if not hist:
        return None
    latest = hist[-1]
    prev = hist[-6:-1]
    if not prev:
        return Trend(latest, None, None, [])
    base = sum(b.total for b in prev) / len(prev)
    return Trend(latest, round(base, 2), round(latest.total - base, 2),
                 changes.marks_between(prev[-1].when, latest.when))


def advice(boot: Boot) -> list[tuple[str, str]]:
    """(tipo de cor, conselho) — o que se pode fazer para arrancar mais depressa."""
    out = []
    fw = boot.phases.get("firmware", 0)
    if fw >= SLOW_FIRMWARE:
        out.append(("warn", f"O BIOS/UEFI demora {fw:.0f} s antes de o sistema começar. Ligue o «Fast Boot» no BIOS "
                            "e desligue o arranque pela rede (PXE) e controladores que não usa."))
    if boot.total >= SLOW_TOTAL:
        out.append(("warn", f"O arranque demora {boot.total:.0f} s. Desative programas que abrem sozinhos (abaixo) "
                            "e confirme que o sistema está num SSD."))
    big = [d for d in boot.delays if d.seconds >= 5]
    if big:
        out.append(("warn", f"«{big[0].name}» atrasou o arranque {big[0].seconds:.0f} s."))
    if not out:
        out.append(("ok", "O arranque está rápido."))
    return out
