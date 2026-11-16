"""Wi-Fi: sinal, banda, canal e redes vizinhas no mesmo canal — causas comuns de "a internet está lenta".

Linux: nmcli (NetworkManager). Windows: `netsh wlan show interfaces` e `show networks mode=bssid`; a saída
do netsh vem no idioma do Windows, por isso as chaves são reconhecidas em inglês e português."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .util import IS_LINUX, IS_WIN, run, which


@dataclass
class Net:
    ssid: str
    signal: int            # 0–100 %
    channel: int = 0
    band: str = ""         # "2.4 GHz" | "5 GHz" | "6 GHz"
    rate: str = ""         # velocidade da ligação (só na rede atual)
    security: str = ""
    radio: str = ""        # 802.11ax…
    in_use: bool = False


@dataclass
class WifiState:
    current: Net | None
    nearby: list[Net] = field(default_factory=list)
    available: bool = True     # há uma placa Wi-Fi (e ferramenta para a ler)
    message: str = ""


def band_of(channel: int, freq_mhz: int = 0) -> str:
    if freq_mhz:
        return "2.4 GHz" if freq_mhz < 3000 else ("5 GHz" if freq_mhz < 5925 else "6 GHz")
    if 1 <= channel <= 14:
        return "2.4 GHz"
    return "5 GHz" if channel else ""


# ------------------------------------------------------------------------------------------------ Linux
def _split_nmcli(line: str) -> list[str]:
    """nmcli -t separa por ':' e escapa os ':' dos valores como '\\:'."""
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in re.split(r"(?<!\\):", line)]


def parse_nmcli(text: str) -> list[Net]:
    out = []
    for ln in text.splitlines():
        p = _split_nmcli(ln)
        if len(p) < 8:
            continue
        in_use, ssid, _bssid, chan, freq, rate, sig, sec = p[:8]
        ch = int(chan) if chan.isdigit() else 0
        f = int(re.sub(r"\D", "", freq) or 0)
        out.append(Net(ssid or "(rede oculta)", int(sig) if sig.isdigit() else 0, ch, band_of(ch, f), rate, sec,
                       in_use=in_use.strip() == "*"))
    return out


def _linux() -> WifiState:
    if not which("nmcli"):
        return WifiState(None, [], False, "O NetworkManager (nmcli) não está disponível.")
    _, devs = run(["nmcli", "-t", "-f", "TYPE", "dev"], timeout=10)
    if "wifi" not in devs.split():
        return WifiState(None, [], False, "Este PC não tem placa Wi-Fi ativa (está ligado por cabo ou sem rede).")
    code, out = run(["nmcli", "-t", "-f", "IN-USE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL,SECURITY", "dev", "wifi", "list"],
                    timeout=20)
    nets = parse_nmcli(out) if code == 0 else []
    cur = next((n for n in nets if n.in_use), None)
    return WifiState(cur, nets, True, "" if cur else "A placa Wi-Fi não está ligada a nenhuma rede.")


# ------------------------------------------------------------------------------------------------ Windows
def _kv(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    k, _, v = line.partition(":")
    return k.strip().lower(), v.strip()


def _apply(net: dict, k: str, v: str) -> None:
    if v.endswith("%") and v[:-1].strip().isdigit():
        net["signal"] = int(v[:-1])
    elif k.startswith(("channel", "canal")) and v.isdigit():
        net["channel"] = int(v)
    elif k in ("band", "banda"):
        net["band"] = v.replace(",", ".")
    elif "radio" in k or "rádio" in k:
        net["radio"] = v
    elif k.startswith(("receive rate", "taxa de rece")):
        net["rate"] = f"{v} Mbit/s"
    elif k.startswith(("authentication", "autentica")):
        net["security"] = v


def _mk(d: dict, in_use: bool = False) -> Net:
    ch = d.get("channel", 0)
    return Net(d.get("ssid") or "(rede oculta)", d.get("signal", 0), ch, d.get("band") or band_of(ch),
               d.get("rate", ""), d.get("security", ""), d.get("radio", ""), in_use)


def parse_netsh_interface(text: str) -> Net | None:
    d: dict = {}
    for ln in text.splitlines():
        kv = _kv(ln)
        if not kv:
            continue
        k, v = kv
        if k == "ssid":
            d["ssid"] = v
        else:
            _apply(d, k, v)
    return _mk(d, True) if d.get("ssid") else None


def parse_netsh_networks(text: str) -> list[Net]:
    out: list[Net] = []
    ssid, sec = "", ""
    cur: dict | None = None
    for ln in text.splitlines():
        kv = _kv(ln)
        if not kv:
            continue
        k, v = kv
        if re.match(r"^ssid \d+", k):
            if cur:
                out.append(_mk(cur))
                cur = None
            ssid, sec = v, ""
        elif re.match(r"^bssid \d+", k):
            if cur:
                out.append(_mk(cur))
            cur = {"ssid": ssid, "security": sec}
        elif cur is not None:
            _apply(cur, k, v)
        elif k.startswith(("authentication", "autentica")):
            sec = v
    if cur:
        out.append(_mk(cur))
    return out


def _windows() -> WifiState:
    code, iface = run(["netsh", "wlan", "show", "interfaces"], timeout=15)
    if code != 0 or not re.search(r"(?im)^\s*(ssid|bssid|name|nome)\s*:", iface):
        return WifiState(None, [], False, "Este PC não tem placa Wi-Fi ativa (está ligado por cabo ou sem rede).")
    cur = parse_netsh_interface(iface)
    _, nets = run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=20)
    return WifiState(cur, parse_netsh_networks(nets), True, "" if cur else "A placa Wi-Fi não está ligada a nenhuma rede.")


def state() -> WifiState:
    if IS_LINUX:
        return _linux()
    if IS_WIN:
        return _windows()
    return WifiState(None, [], False, "Sistema não suportado.")


# ------------------------------------------------------------------------------------------------ análise
def _overlaps(a: int, b: int, band: str) -> bool:
    if band.startswith("2"):
        return abs(a - b) < 5          # canais de 20 MHz a 2,4 GHz sobrepõem-se até 4 de distância
    return a == b


def crowding(cur: Net, nearby: list[Net]) -> int:
    """Quantas outras redes (com sinal apreciável) partilham ou sobrepõem o canal da rede atual."""
    return sum(1 for n in nearby
               if not n.in_use and n.ssid != cur.ssid and n.signal >= 30 and n.band == cur.band
               and _overlaps(n.channel, cur.channel, cur.band))


def best_24_channel(nearby: list[Net], ssid: str = "") -> int:
    load = {c: 0 for c in (1, 6, 11)}
    for n in nearby:
        if n.band.startswith("2") and n.ssid != ssid:
            for c in load:
                if _overlaps(n.channel, c, "2.4"):
                    load[c] += max(1, n.signal // 25)
    return min(load, key=lambda c: (load[c], c))


def analyze(st: WifiState) -> list[tuple[str, str]]:
    """(tipo de cor, conclusão) para a rede atual."""
    cur = st.current
    if not cur:
        return []
    out = []
    if cur.signal < 30:
        out.append(("bad", f"Sinal muito fraco ({cur.signal} %). Aproxime-se do router, tire obstáculos (paredes, "
                           "armários metálicos) ou use um repetidor/mesh — ou um cabo."))
    elif cur.signal < 55:
        out.append(("warn", f"Sinal fraco ({cur.signal} %): a velocidade e a latência sofrem. Um sítio mais perto "
                            "do router ou um repetidor ajuda."))
    else:
        out.append(("ok", f"Sinal bom ({cur.signal} %)."))
    if cur.band.startswith("2"):
        has5 = any(n.ssid == cur.ssid and not n.band.startswith("2") and n.signal >= 40 for n in st.nearby)
        if has5:
            out.append(("warn", "Está ligado na banda de 2,4 GHz, mas o seu router também emite a 5 GHz com bom "
                                "sinal — a 5 GHz é bem mais rápida e com menos interferências."))
        n = crowding(cur, st.nearby)
        if n >= 4:
            best = best_24_channel(st.nearby, cur.ssid)
            tip = f" O canal {best} está mais livre — mude-o nas definições do router." if best != cur.channel else ""
            out.append(("warn", f"{n} redes vizinhas usam o mesmo canal ({cur.channel}) ou canais sobrepostos.{tip}"))
    else:
        n = crowding(cur, st.nearby)
        if n >= 3:
            out.append(("warn", f"{n} redes vizinhas usam o mesmo canal ({cur.channel}). Escolher outro canal no "
                                "router reduz as interferências."))
    return out
