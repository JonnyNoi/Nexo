"""O monitor está a usar a taxa de atualização para que foi comprado?

Um monitor de 144/165/180 Hz ligado a 60 Hz é muito comum (cabo HDMI antigo, Windows que escolhe 60 Hz por
omissão, modo nunca alterado depois de instalar o sistema) — e perde-se toda a fluidez que se pagou.

Linux: modos do compositor (kscreen-doctor, hyprctl, swaymsg ou xrandr numa sessão X11); o nome do monitor
e, quando não há ferramenta (ex.: GNOME em Wayland), o máximo vêm do EDID em /sys/class/drm (sem root).
Windows: EnumDisplaySettings — o modo atual e todos os modos que o controlador aceita.
A interface pode ainda dar o Hz atual visto pelo Qt (set_qt_screens) para quando nada mais funciona."""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import asdict, dataclass

from .util import IS_LINUX, IS_WIN, load_json, run, save_json, which

CACHE = "ecras.json"
# diferenças menores do que isto são arredondamentos (59,94 vs. 60) ou modos que não interessam
_MIN_GAIN = 1.15


@dataclass
class Monitor:
    output: str                  # DP-1, HDMI-A-1, \\.\DISPLAY1…
    name: str = ""               # modelo (EDID)
    width: int = 0               # modo atual
    height: int = 0
    hz: float | None = None      # taxa de atualização atual
    max_hz: float | None = None  # máximo na resolução atual
    native: tuple[int, int] | None = None   # maior resolução que o monitor aceita

    @property
    def label(self) -> str:
        return f"{self.name} ({self.output})" if self.name else self.output


# --------------------------------------------------------------------------- EDID
def parse_edid(data: bytes) -> dict:
    """{'name', 'max_hz', 'native': (w, h)} a partir dos detailed timings do bloco base e das extensões CTA."""
    out: dict = {"name": "", "max_hz": None, "native": None}
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return out
    timings = []

    def descriptor(d: bytes):
        clock = int.from_bytes(d[0:2], "little") * 10_000
        if clock:
            h, hb = d[2] | (d[4] >> 4) << 8, d[3] | (d[4] & 0xF) << 8
            v, vb = d[5] | (d[7] >> 4) << 8, d[6] | (d[7] & 0xF) << 8
            if h and v and (h + hb) and (v + vb):
                timings.append((h, v, clock / ((h + hb) * (v + vb))))
        elif d[3] == 0xFC and not out["name"]:
            out["name"] = d[5:18].split(b"\n")[0].decode("ascii", "replace").strip()

    for i in range(54, 126, 18):
        descriptor(data[i:i + 18])
    for b in range(1, len(data) // 128):
        blk = data[b * 128:(b + 1) * 128]
        if blk[0] == 0x02 and 4 <= blk[2] < 127:          # extensão CTA-861
            for i in range(blk[2], 127 - 17, 18):
                descriptor(blk[i:i + 18])
    if timings:
        out["native"] = max(((w, h) for w, h, _ in timings), key=lambda r: r[0] * r[1])
        out["max_hz"] = round(max(hz for w, h, hz in timings if (w, h) == out["native"]), 2)
    return out


def _edids_linux() -> dict[str, dict]:
    """{'DP-1': {...}} dos monitores ligados."""
    out = {}
    for d in glob.glob("/sys/class/drm/card*-*"):
        try:
            with open(os.path.join(d, "status")) as fh:
                if fh.read().strip() != "connected":
                    continue
            with open(os.path.join(d, "edid"), "rb") as fh:
                info = parse_edid(fh.read())
        except OSError:
            continue
        out[os.path.basename(d).split("-", 1)[1]] = info
    return out


# --------------------------------------------------------------------------- ferramentas do Linux
def _best(modes: list[tuple[int, int, float]], cur: tuple[int, int]) -> tuple[float | None, tuple[int, int] | None]:
    """(máximo na resolução atual, maior resolução)"""
    if not modes:
        return None, None
    same = [hz for w, h, hz in modes if (w, h) == cur]
    native = max(((w, h) for w, h, _ in modes), key=lambda r: r[0] * r[1])
    return (round(max(same), 2) if same else None), native


def parse_kscreen(text: str) -> list[Monitor]:
    out = []
    for o in (json.loads(text) or {}).get("outputs", []):
        if not (o.get("connected") and o.get("enabled")):
            continue
        modes = [(m["size"]["width"], m["size"]["height"], float(m["refreshRate"])) for m in o.get("modes", [])
                 if m.get("size") and m.get("refreshRate")]
        cur = next((m for m in o.get("modes", []) if m.get("id") == o.get("currentModeId")), None)
        if not cur:
            continue
        w, h = cur["size"]["width"], cur["size"]["height"]
        mx, native = _best(modes, (w, h))
        out.append(Monitor(o.get("name", "?"), "", w, h, round(float(cur["refreshRate"]), 2), mx, native))
    return out


def parse_hyprctl(text: str) -> list[Monitor]:
    out = []
    for o in json.loads(text) or []:
        modes = [(int(a), int(b), float(c)) for a, b, c in
                 (re.findall(r"(\d+)x(\d+)@([\d.]+)", " ".join(o.get("availableModes") or [])))]
        w, h = int(o.get("width") or 0), int(o.get("height") or 0)
        mx, native = _best(modes, (w, h))
        out.append(Monitor(o.get("name", "?"), f"{o.get('make', '')} {o.get('model', '')}".strip(), w, h,
                           round(float(o.get("refreshRate") or 0), 2) or None, mx, native))
    return out


def parse_sway(text: str) -> list[Monitor]:
    out = []
    for o in json.loads(text) or []:
        cm = o.get("current_mode") or {}
        if not o.get("active") or not cm:
            continue
        modes = [(m["width"], m["height"], m["refresh"] / 1000) for m in o.get("modes", [])]
        w, h = cm["width"], cm["height"]
        mx, native = _best(modes, (w, h))
        out.append(Monitor(o.get("name", "?"), f"{o.get('make', '')} {o.get('model', '')}".strip(), w, h,
                           round(cm["refresh"] / 1000, 2), mx, native))
    return out


def parse_xrandr(text: str) -> list[Monitor]:
    out: list[Monitor] = []
    modes: list[tuple[int, int, float]] = []
    cur = None

    def flush():
        if out and cur:
            m = out[-1]
            m.width, m.height, m.hz = cur
            m.max_hz, m.native = _best(modes, cur[:2])

    for line in text.splitlines():
        hdr = re.match(r"^(\S+) connected", line)
        if hdr:
            flush()
            out.append(Monitor(hdr.group(1)))
            modes, cur = [], None
            continue
        mm = re.match(r"^\s+(\d+)x(\d+)i?\s+(.*)$", line)
        if mm and out:
            w, h = int(mm.group(1)), int(mm.group(2))
            for hz, star in re.findall(r"([\d.]+)(\*?)\+?", mm.group(3)):
                modes.append((w, h, float(hz)))
                if star:
                    cur = (w, h, round(float(hz), 2))
        elif not line.startswith(" "):   # saída desligada ou outra secção: os modos seguintes não são dela
            flush()
            out.append(Monitor(""))
            modes, cur = [], None
    flush()
    return [m for m in out if m.output and m.hz]


def _linux() -> list[Monitor]:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    tries = [("kscreen-doctor", ["kscreen-doctor", "-j"], parse_kscreen),
             ("hyprctl", ["hyprctl", "monitors", "all", "-j"], parse_hyprctl),
             ("swaymsg", ["swaymsg", "-r", "-t", "get_outputs"], parse_sway)]
    if session != "wayland":   # no Wayland o xrandr só vê o XWayland, com modos falsos
        tries.append(("xrandr", ["xrandr", "--query"], parse_xrandr))
    mons: list[Monitor] = []
    for exe, cmd, parse in tries:
        if not which(exe):
            continue
        code, out = run(cmd, timeout=5)
        if code == 0 and out.strip():
            try:
                mons = parse(out)
            except (ValueError, KeyError, TypeError):
                mons = []
            if mons:
                break
    edids = _edids_linux()
    for m in mons:
        e = edids.get(m.output) or {}
        m.name = m.name or e.get("name", "")
        m.native = m.native or e.get("native")
    if not mons:   # sem ferramenta: monitores do EDID; o Hz atual vem do Qt, se houver
        mons = [Monitor(out, e.get("name", ""), max_hz=e.get("max_hz"), native=e.get("native"))
                for out, e in edids.items()]
    return mons


# --------------------------------------------------------------------------- Windows
def _windows() -> list[Monitor]:
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                    ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                    ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
                    ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                    ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
                    ("dmPanningHeight", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    out = []
    i = 0
    while True:
        dev = DISPLAY_DEVICEW()
        dev.cb = ctypes.sizeof(dev)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
            break
        i += 1
        if not dev.StateFlags & 0x1:          # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
            continue
        mon = DISPLAY_DEVICEW()
        mon.cb = ctypes.sizeof(mon)
        name = mon.DeviceString if user32.EnumDisplayDevicesW(dev.DeviceName, 0, ctypes.byref(mon), 0) else ""
        if name.lower().startswith(("generic pnp", "monitor pnp", "monitor genérico")):
            name = ""
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(dm)
        if not user32.EnumDisplaySettingsW(dev.DeviceName, -1, ctypes.byref(dm)):   # ENUM_CURRENT_SETTINGS
            continue
        w, h, hz = dm.dmPelsWidth, dm.dmPelsHeight, float(dm.dmDisplayFrequency)
        modes = []
        k = 0
        while k < 2000:
            m = DEVMODEW()
            m.dmSize = ctypes.sizeof(m)
            if not user32.EnumDisplaySettingsW(dev.DeviceName, k, ctypes.byref(m)):
                break
            if m.dmDisplayFrequency > 1:
                modes.append((m.dmPelsWidth, m.dmPelsHeight, float(m.dmDisplayFrequency)))
            k += 1
        mx, native = _best(modes, (w, h))
        out.append(Monitor(dev.DeviceName, name, w, h, hz if hz > 1 else None, mx, native))
    return out


# --------------------------------------------------------------------------- Qt (alternativa) e cache
_qt: list[dict] = []


def set_qt_screens(screens: list[dict]) -> None:
    """[{'name', 'model', 'hz', 'width', 'height'}] da QGuiApplication — chamado pela interface."""
    global _qt
    _qt = list(screens)


def _merge_qt(mons: list[Monitor]) -> None:
    if not _qt:
        return
    for m in mons:
        if m.hz:
            continue
        q = next((s for s in _qt if s.get("name") == m.output or (m.name and s.get("model") == m.name)), None)
        if q is None and len(mons) == 1 and len(_qt) == 1:
            q = _qt[0]
        if q and q.get("hz"):
            m.hz = round(float(q["hz"]), 2)
            m.width, m.height = m.width or int(q.get("width") or 0), m.height or int(q.get("height") or 0)


def monitors() -> list[Monitor]:
    mons: list[Monitor] = []
    if IS_LINUX:
        mons = _linux()
    elif IS_WIN:
        try:
            mons = _windows()
        except (OSError, AttributeError):
            mons = []
    _merge_qt(mons)
    try:
        save_json(CACHE, [asdict(m) for m in mons])
    except OSError:
        pass
    return mons


def cached() -> list[Monitor]:
    data = load_json(CACHE, [])
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            d = {k: v for k, v in d.items() if k in Monitor.__dataclass_fields__}
            if d.get("native"):
                d["native"] = tuple(d["native"])
            out.append(Monitor(**d))
        except (TypeError, AttributeError):
            continue
    return out


# --------------------------------------------------------------------------- veredicto
@dataclass
class Verdict:
    kind: str     # ok | warn
    text: str


def check(m: Monitor) -> Verdict | None:
    """None quando não se sabe o Hz atual."""
    if not m.hz:
        return None
    res = f"{m.width}×{m.height}" if m.width else "Monitor"
    if m.max_hz and m.max_hz >= m.hz * _MIN_GAIN:
        return Verdict("warn", f"O monitor está a {m.hz:.0f} Hz mas aceita {m.max_hz:.0f} Hz. Escolha "
                               f"{m.max_hz:.0f} Hz nas definições de ecrã do sistema — se não aparecer, use um cabo "
                               "DisplayPort ou HDMI 2.0/2.1.")
    if m.native and m.width and (m.width, m.height) != m.native and m.native[0] * m.native[1] > m.width * m.height:
        return Verdict("ok", f"{res} a {m.hz:.0f} Hz. A resolução nativa é {m.native[0]}×{m.native[1]} — "
                             "abaixo dela a imagem fica menos nítida.")
    return Verdict("ok", f"{res} a {m.hz:.0f} Hz — o máximo que o monitor aceita." if m.max_hz
                   else f"{res} a {m.hz:.0f} Hz.")
