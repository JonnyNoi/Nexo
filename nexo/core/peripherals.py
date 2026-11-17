"""Periféricos: bateria de ratos, teclados, comandos e auscultadores sem fios, e o estado do Bluetooth.

Linux: upower (vê os dispositivos HID/Bluetooth com bateria — Logitech, comandos da PlayStation/Xbox,
auscultadores…) e /sys/class/power_supply (scope=Device) quando o upower não existe; bluetoothctl para o
adaptador e os aparelhos ligados.
Windows: bateria dos aparelhos Bluetooth (propriedade DEVPKEY_Bluetooth_Battery) e estado do rádio."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

from .util import IS_LINUX, IS_WIN, as_list, ps_json, read_text, run, which

LOW = 15   # % — avisar abaixo disto

KINDS = {"mouse": "Rato", "keyboard": "Teclado", "gaming-input": "Comando", "headset": "Auscultadores",
         "headphones": "Auscultadores", "speakers": "Coluna", "tablet": "Mesa digitalizadora", "pen": "Caneta",
         "touchpad": "Touchpad", "phone": "Telemóvel", "media-player": "Leitor multimédia", "remote-control":
         "Comando à distância", "printer": "Impressora", "other-audio": "Áudio", "ups": "UPS", "computer": "Computador",
         "battery": "Bateria"}
_LEVELS = {"full": 100, "high": 80, "normal": 55, "low": 20, "critical": 5}


@dataclass
class Device:
    name: str
    kind: str = ""                 # Rato, Teclado, Comando…
    percent: int | None = None
    level: str = ""                # quando o aparelho só diz "alta/baixa" (alguns Logitech, comandos)
    charging: bool = False
    source: str = ""               # upower, sysfs, Bluetooth

    @property
    def low(self) -> bool:
        return not self.charging and self.percent is not None and self.percent <= LOW


@dataclass
class Bluetooth:
    present: bool = False
    powered: bool = False
    blocked: bool = False
    name: str = ""
    connected: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- Linux
def parse_upower(text: str) -> list[Device]:
    out = []
    for block in re.split(r"^Device: ", text, flags=re.M)[1:]:
        path = block.splitlines()[0].strip()
        if path.endswith("DisplayDevice"):
            continue
        f = dict(re.findall(r"^\s+([\w -]+):\s+(.+)$", block, re.M))
        if f.get("power supply", "").strip() == "yes":       # bateria do portátil / corrente
            continue
        kind = next((ln.strip() for ln in block.splitlines()[1:]
                     if re.fullmatch(r"\s{2}[a-z-]+\s*", ln)), "")
        if kind in ("line-power", "unknown") and "percentage" not in f:
            continue
        if f.get("present", "yes").strip() == "no":
            continue
        pct = None
        m = re.match(r"(\d+(?:[.,]\d+)?)%", f.get("percentage", ""))
        ignored = "ignored" in f.get("percentage", "")
        if m and not ignored:
            pct = round(float(m.group(1).replace(",", ".")))
        level = f.get("battery-level", "").strip()
        if level in ("none", "unknown"):
            level = ""
        if pct is None and level in _LEVELS:
            pct = _LEVELS[level]
        if pct is None and not level:
            continue
        name = (f.get("model") or f.get("native-path") or path.rsplit("/", 1)[-1]).strip()
        out.append(Device(name, KINDS.get(kind, kind.capitalize()), pct, level,
                          f.get("state", "").strip() in ("charging", "fully-charged"), "upower"))
    return out


def _sysfs() -> list[Device]:
    out = []
    for d in glob.glob("/sys/class/power_supply/*"):
        if read_text(os.path.join(d, "scope")) != "Device":
            continue
        cap = read_text(os.path.join(d, "capacity"))
        lvl = (read_text(os.path.join(d, "capacity_level")) or "").lower()
        pct = int(cap) if cap and cap.isdigit() else _LEVELS.get(lvl)
        if pct is None:
            continue
        name = read_text(os.path.join(d, "model_name")) or os.path.basename(d)
        out.append(Device(name, "", pct, lvl if not cap else "",
                          read_text(os.path.join(d, "status")) in ("Charging", "Full"), "sysfs"))
    return out


def parse_btshow(text: str) -> Bluetooth:
    if "Controller" not in text:
        return Bluetooth()
    f = dict(re.findall(r"^\s+(\w+):\s+(.+)$", text, re.M))
    return Bluetooth(True, f.get("Powered", "").strip() == "yes", "blocked" in f.get("PowerState", ""),
                     f.get("Alias", f.get("Name", "")).strip())


def _bluetooth_linux() -> Bluetooth:
    if not which("bluetoothctl"):
        return Bluetooth(present=bool(glob.glob("/sys/class/bluetooth/hci*")))
    _, out = run(["bluetoothctl", "show"], timeout=5)
    bt = parse_btshow(out)
    if bt.powered:
        code, out = run(["bluetoothctl", "devices", "Connected"], timeout=5)
        if code == 0:
            bt.connected = [m.group(1).strip() for m in re.finditer(r"^Device [0-9A-F:]{17} (.+)$", out, re.M)]
    return bt


# --------------------------------------------------------------------------- Windows
_WIN_PS = r"""
$k = '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2'
Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | ForEach-Object {
  $b = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $k -ErrorAction SilentlyContinue).Data
  if ($b -ne $null) { [pscustomobject]@{ Name = $_.FriendlyName; Battery = [int]$b } }
}
"""


def _windows() -> tuple[list[Device], Bluetooth]:
    devs = [Device(str(d.get("Name") or "?"), "", int(d["Battery"]), source="Bluetooth")
            for d in as_list(ps_json(_WIN_PS, timeout=40)) if isinstance(d, dict) and d.get("Battery") is not None]
    radio = ps_json("Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.FriendlyName -match 'Adapter|Radio|Wireless Bluetooth|Bluetooth' -and "
                    "$_.InstanceId -match '^USB|^PCI' } | Select-Object FriendlyName,Status", timeout=30)
    rows = [r for r in as_list(radio) if isinstance(r, dict)]
    bt = Bluetooth(bool(rows), any(r.get("Status") == "OK" for r in rows), False,
                   str(rows[0].get("FriendlyName") or "") if rows else "")
    return devs, bt


# --------------------------------------------------------------------------- API
def scan() -> tuple[list[Device], Bluetooth]:
    if IS_WIN:
        try:
            return _windows()
        except Exception:  # noqa: BLE001
            return [], Bluetooth()
    if not IS_LINUX:
        return [], Bluetooth()
    devs: list[Device] = []
    if which("upower"):
        _, out = run(["upower", "--dump"], timeout=10)
        devs = parse_upower(out)
    if not devs:
        devs = _sysfs()
    return devs, _bluetooth_linux()


def low_battery(devs: list[Device]) -> list[Device]:
    return [d for d in devs if d.low]
