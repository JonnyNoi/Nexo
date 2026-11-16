"""Saúde da bateria (portáteis): capacidade original vs. atual, ciclos e desgaste.

Linux: /sys/class/power_supply/BAT* (energy_* em µWh ou charge_* em µAh — a razão é a mesma).
Windows: WMI (root\\wmi: BatteryStaticData.DesignedCapacity, BatteryFullChargedCapacity, BatteryCycleCount)
com Win32_Battery para o estado e a carga. Num PC de secretária devolve uma lista vazia."""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from .util import IS_LINUX, IS_WIN, as_list, load_json, ps_json, read_text, save_json

CACHE = "bateria.json"
# desgaste a partir do qual se avisa (capacidade atual em % da original)
WARN_PCT = 80
BAD_PCT = 60


@dataclass
class Battery:
    name: str
    design: float = 0.0          # capacidade original (Wh ou mWh — só a razão interessa)
    full: float = 0.0            # capacidade atual com carga completa
    cycles: int | None = None
    percent: float | None = None  # carga agora
    status: str = ""             # A carregar | A descarregar | Carregada | Ligada à corrente
    model: str = ""
    manufacturer: str = ""
    technology: str = ""
    power_w: float | None = None  # consumo/carregamento agora (W)
    unit: str = "Wh"

    @property
    def health_pct(self) -> float | None:
        if self.design <= 0 or self.full <= 0:
            return None
        return min(100.0, 100.0 * self.full / self.design)

    @property
    def wear_pct(self) -> float | None:
        h = self.health_pct
        return None if h is None else 100.0 - h

    def verdict(self) -> tuple[str, str]:
        """(tipo de cor, explicação)"""
        h = self.health_pct
        if h is None:
            return "ok", "O sistema não indica a capacidade original desta bateria."
        if h < BAD_PCT:
            return "bad", (f"A bateria só guarda {h:.0f} % da carga de quando era nova — dura bem menos do que "
                           "devia. Vale a pena trocá-la.")
        if h < WARN_PCT:
            return "warn", (f"A bateria guarda {h:.0f} % da carga original: já se nota desgaste. Evitar calor e "
                            "deixá-la a 100 % ligada à corrente o tempo todo ajuda a durar mais.")
        return "ok", f"A bateria guarda {h:.0f} % da carga original — está em bom estado."

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


_STATUS = {"Charging": "A carregar", "Discharging": "A descarregar", "Full": "Carregada",
           "Not charging": "Ligada à corrente", "Unknown": ""}


def _num(path: str) -> float:
    try:
        return float(read_text(path) or 0)
    except ValueError:
        return 0.0


def _linux(root: str = "/sys/class/power_supply") -> list[Battery]:
    out = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if read_text(os.path.join(d, "type")) != "Battery":
            continue
        if read_text(os.path.join(d, "scope")) == "Device":   # rato/teclado sem fios, comando
            continue
        if read_text(os.path.join(d, "present"), "1") == "0":
            continue
        f = lambda n, d=d: os.path.join(d, n)  # noqa: E731
        if os.path.exists(f("energy_full")):
            design, full, unit = _num(f("energy_full_design")) / 1e6, _num(f("energy_full")) / 1e6, "Wh"
        else:
            design, full, unit = _num(f("charge_full_design")) / 1e3, _num(f("charge_full")) / 1e3, "mAh"
        cyc = read_text(f("cycle_count"))
        pct = read_text(f("capacity"))
        power = _num(f("power_now")) / 1e6 if os.path.exists(f("power_now")) else None
        if power is None and os.path.exists(f("current_now")) and os.path.exists(f("voltage_now")):
            power = _num(f("current_now")) * _num(f("voltage_now")) / 1e12
        out.append(Battery(
            name=os.path.basename(d), design=design, full=full,
            cycles=int(cyc) if cyc.isdigit() and int(cyc) > 0 else None,
            percent=float(pct) if pct.replace(".", "", 1).isdigit() else None,
            status=_STATUS.get(read_text(f("status")), read_text(f("status"))),
            model=read_text(f("model_name")), manufacturer=read_text(f("manufacturer")),
            technology=read_text(f("technology")), power_w=round(power, 1) if power else None, unit=unit))
    return out


_PS = r"""
$r = @{}
$r.static = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData -EA SilentlyContinue |
  Select DesignedCapacity,DeviceName,ManufactureName)
$r.full = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -EA SilentlyContinue |
  Select FullChargedCapacity)
$r.cyc = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryCycleCount -EA SilentlyContinue | Select CycleCount)
$r.st = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus -EA SilentlyContinue |
  Select Charging,Discharging,PowerOnline,ChargeRate,DischargeRate)
$r.w32 = @(Get-CimInstance Win32_Battery -EA SilentlyContinue | Select Name,EstimatedChargeRemaining,BatteryStatus)
[pscustomobject]$r
"""


def parse_windows(data: dict | None) -> list[Battery]:
    if not data:
        return []
    static, full = as_list(data.get("static")), as_list(data.get("full"))
    cyc, st, w32 = as_list(data.get("cyc")), as_list(data.get("st")), as_list(data.get("w32"))
    n = max(len(static), len(w32))
    out = []
    for i in range(n):
        s = static[i] if i < len(static) else {}
        w = w32[i] if i < len(w32) else {}
        fc = full[i] if i < len(full) else {}
        c = cyc[i] if i < len(cyc) else {}
        b = st[i] if i < len(st) else {}
        status = ""
        if b.get("Charging"):
            status = "A carregar"
        elif b.get("Discharging"):
            status = "A descarregar"
        elif b.get("PowerOnline"):
            status = "Ligada à corrente"
        rate = b.get("DischargeRate") or b.get("ChargeRate") or 0
        cycles = c.get("CycleCount")
        out.append(Battery(
            name=w.get("Name") or s.get("DeviceName") or f"Bateria {i + 1}",
            design=float(s.get("DesignedCapacity") or 0) / 1000, full=float(fc.get("FullChargedCapacity") or 0) / 1000,
            cycles=int(cycles) if isinstance(cycles, int) and cycles > 0 else None,
            percent=w.get("EstimatedChargeRemaining"), status=status,
            model=s.get("DeviceName") or "", manufacturer=s.get("ManufactureName") or "",
            power_w=round(rate / 1000, 1) if rate else None))
    return out


def batteries() -> list[Battery]:
    if IS_LINUX:
        bats = _linux()
    elif IS_WIN:
        bats = parse_windows(ps_json(_PS, timeout=30))
    else:
        bats = []
    try:
        save_json(CACHE, [b.as_dict() for b in bats])
    except OSError:
        pass
    return bats


def has_battery() -> bool:
    """Rápido: no Linux lê o sysfs; no Windows usa a cache (ou a deteção do psutil)."""
    if IS_LINUX:
        return bool(_linux())
    cached = load_json(CACHE, None)
    if isinstance(cached, list):
        return bool(cached)
    try:
        import psutil
        return psutil.sensors_battery() is not None
    except Exception:  # noqa: BLE001
        return False


def cached() -> list[Battery]:
    data = load_json(CACHE, [])
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            out.append(Battery(**{k: v for k, v in d.items() if k in Battery.__dataclass_fields__}))
        except TypeError:
            continue
    return out
