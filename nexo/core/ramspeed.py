"""A memória RAM está a correr à velocidade para que foi comprada?

Muitos kits (ex.: DDR5-6000, DDR4-3600) só atingem essa velocidade com o perfil XMP/EXPO ligado no BIOS;
sem ele ficam na velocidade base JEDEC (DDR5-4800, DDR4-2133…) — perde-se desempenho, sobretudo em jogos.

O SPD/DMI só indica a velocidade JEDEC ("Speed"), por isso a velocidade anunciada sai do código do módulo
(part number): a maioria inclui-a por extenso (UD5-6000, F5-6000J3038F16G, CMK32GX4M2D3600C18) ou abreviada
(Kingston KF436C17 → 3600, Crucial BL8G32C16 → 3200).

Linux: propriedades do udev (MEMORY_DEVICE_*), legíveis sem root (systemd ≥ 248).
Windows: Win32_PhysicalMemory (Speed, ConfiguredClockSpeed, PartNumber)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .util import IS_LINUX, IS_WIN, as_list, load_json, ps_json, run, save_json, which

CACHE = "memoria.json"
SPEEDS = {1600, 1866, 2133, 2400, 2666, 2800, 2933, 3000, 3200, 3333, 3466, 3600, 3733, 3800, 3866, 4000, 4133,
          4266, 4400, 4600, 4800, 5000, 5200, 5400, 5600, 5800, 6000, 6200, 6400, 6600, 6800, 7000, 7200, 7400,
          7600, 7800, 8000, 8200, 8400, 8800}
_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}
# abaixo disto (com o kit anunciado acima) quase de certeza que é só JEDEC
_TOLERANCE = 0.97


@dataclass
class Module:
    slot: str
    size: int = 0                 # bytes
    kind: str = ""                # DDR4, DDR5…
    jedec: int | None = None      # "Speed" do SPD (MT/s)
    configured: int | None = None  # velocidade atual (MT/s)
    part: str = ""
    manufacturer: str = ""

    @property
    def rated(self) -> int | None:
        return rated_from_part(self.part)


def rated_from_part(part: str) -> int | None:
    p = (part or "").strip().upper()
    if not p or p in ("NOT SPECIFIED", "UNKNOWN"):
        return None
    m = re.match(r"^KF\d(\d{2})C\d", p)              # Kingston FURY: KF436C17 → 3600, KF560C40 → 6000
    if m:
        v = int(m.group(1)) * 100
        return v if v in SPEEDS else None
    m = re.match(r"^BL\w*?(\d{2})C\d{2}", p)          # Crucial Ballistix: BL2K8G32C16U4B → 3200
    if m and int(m.group(1)) * 100 in SPEEDS:
        return int(m.group(1)) * 100
    found = [int(x) for x in re.findall(r"(?<!\d)(\d{4})(?!\d)", p) if int(x) in SPEEDS]
    return max(found) if found else None


def parse_udev(text: str) -> list[Module]:
    props = dict(re.findall(r"^(MEMORY_DEVICE_\d+_[A-Z_]+)=(.*)$", text, re.M))
    idx = sorted({int(m) for m in re.findall(r"^MEMORY_DEVICE_(\d+)_", "\n".join(props), re.M)})
    out = []
    for i in idx:
        g = lambda k, i=i: props.get(f"MEMORY_DEVICE_{i}_{k}", "")  # noqa: E731
        if g("PRESENT") == "0" or not g("SIZE"):
            continue
        out.append(Module(slot=g("LOCATOR") or f"#{i}", size=int(g("SIZE") or 0), kind=g("TYPE"),
                          jedec=int(g("SPEED_MTS")) if g("SPEED_MTS").isdigit() else None,
                          configured=int(g("CONFIGURED_SPEED_MTS")) if g("CONFIGURED_SPEED_MTS").isdigit() else None,
                          part=g("PART_NUMBER").strip(), manufacturer=g("MANUFACTURER").strip()))
    return out


def parse_windows(rows) -> list[Module]:
    out = []
    for m in as_list(rows):
        if not isinstance(m, dict):
            continue
        out.append(Module(slot=m.get("DeviceLocator") or "?", size=int(m.get("Capacity") or 0),
                          kind=_TYPES.get(m.get("SMBIOSMemoryType"), ""),
                          jedec=m.get("Speed") or None, configured=m.get("ConfiguredClockSpeed") or None,
                          part=(m.get("PartNumber") or "").strip(), manufacturer=(m.get("Manufacturer") or "").strip()))
    return out


def modules() -> list[Module]:
    mods: list[Module] = []
    if IS_LINUX and which("udevadm"):
        _, out = run(["udevadm", "info", "-q", "property", "-p", "/sys/devices/virtual/dmi/id"], timeout=5)
        mods = parse_udev(out)
    elif IS_WIN:
        mods = parse_windows(ps_json("Get-CimInstance Win32_PhysicalMemory | Select DeviceLocator,Capacity,Speed,"
                                     "ConfiguredClockSpeed,PartNumber,Manufacturer,SMBIOSMemoryType", timeout=30))
    try:
        save_json(CACHE, [m.__dict__ for m in mods])
    except OSError:
        pass
    return mods


def cached() -> list[Module]:
    data = load_json(CACHE, [])
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            out.append(Module(**{k: v for k, v in d.items() if k in Module.__dataclass_fields__}))
        except TypeError:
            continue
    return out


@dataclass
class Verdict:
    kind: str           # ok | warn
    text: str
    current: int | None = None
    rated: int | None = None


def check(mods: list[Module]) -> Verdict | None:
    """None quando não há dados suficientes (VM, Linux sem udev, módulos sem código)."""
    cur = [m.configured for m in mods if m.configured]
    if not cur:
        return None
    current = min(cur)
    rated = [m.rated for m in mods if m.rated]
    top = max(rated) if rated else None
    if top and current < top * _TOLERANCE:
        lost = 100 * (1 - current / top)
        return Verdict("warn", f"A memória está a {current} MT/s mas foi feita para {top} MT/s (−{lost:.0f} %). "
                               "Ligue o perfil XMP (Intel) ou EXPO/DOCP (AMD) no BIOS para ter a velocidade toda.",
                       current, top)
    jedec = [m.jedec for m in mods if m.jedec]
    if jedec and current < max(jedec) * _TOLERANCE:
        return Verdict("warn", f"A memória está a {current} MT/s, abaixo dos {max(jedec)} MT/s que os módulos "
                               "suportam. Confirme as definições de memória no BIOS.", current, max(jedec))
    kinds = {m.kind for m in mods if m.kind}
    if len({m.part for m in mods if m.part}) > 1:
        return Verdict("ok", f"Memória a {current} MT/s. Atenção: os módulos não são todos iguais — kits "
                             "misturados às vezes obrigam a baixar a velocidade.", current, top)
    return Verdict("ok", f"Memória {'/'.join(sorted(kinds))} a {current} MT/s"
                         + (f" — a velocidade anunciada ({top} MT/s)." if top else "."), current, top)
