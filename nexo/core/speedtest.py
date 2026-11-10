"""Teste de velocidade da internet (latência, variação, download e upload).

Usa os servidores públicos do speed.cloudflare.com (os mesmos do teste da Cloudflare, sem conta nem
publicidade): é escolhido automaticamente o centro de dados mais próximo. Download e upload usam várias
ligações em paralelo durante um tempo fixo, como os testes conhecidos, para encher a ligação mesmo em
fibra. Os primeiros instantes (arranque do TCP) não contam para o resultado.
"""
from __future__ import annotations

import http.client
import os
import ssl
import statistics
import threading
import time
from dataclasses import asdict, dataclass, field

from .util import APP_NAME, APP_VERSION, get_setting, set_setting, TaskCancelled

HOST = "speed.cloudflare.com"
UA = f"{APP_NAME}/{APP_VERSION}"
DL_CHUNK = 50_000_000      # bytes por pedido de download
UL_CHUNK = 20_000_000      # bytes por pedido de upload
WARMUP = 1.5               # segundos ignorados no início de cada fase

# Centros de dados da Cloudflare mais comuns para quem está em Portugal/Europa (código IATA → cidade)
_COLOS = {"LIS": "Lisboa", "OPO": "Porto", "MAD": "Madrid", "BCN": "Barcelona", "CDG": "Paris", "MRS": "Marselha",
          "LHR": "Londres", "MAN": "Manchester", "FRA": "Frankfurt", "AMS": "Amesterdão", "DUS": "Düsseldorf",
          "MXP": "Milão", "FCO": "Roma", "ZRH": "Zurique", "BRU": "Bruxelas", "DUB": "Dublin", "VIE": "Viena",
          "GRU": "São Paulo", "GIG": "Rio de Janeiro", "LAD": "Luanda", "MPM": "Maputo", "EWR": "Newark",
          "IAD": "Ashburn", "MIA": "Miami", "LAX": "Los Angeles"}


class Cancelled(TaskCancelled):
    pass


@dataclass
class SpeedResult:
    ping_ms: float | None = None
    jitter_ms: float | None = None
    download_mbps: float | None = None
    upload_mbps: float | None = None
    loaded_ping_ms: float | None = None   # latência com a ligação cheia (deteta "bufferbloat")
    server: str = ""
    ip: str = ""
    when: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def _conn(timeout: float = 10) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(HOST, 443, timeout=timeout, context=ssl.create_default_context())


def _server_ms(resp: http.client.HTTPResponse) -> float:
    """Tempo de processamento do servidor (cabeçalho Server-Timing), para não o contar como latência."""
    total = 0.0
    for part in (resp.getheader("Server-Timing") or "").split(","):
        if "dur=" in part:
            try:
                total = max(total, float(part.split("dur=")[1].split(";")[0]))
            except ValueError:
                pass
    return total


# --------------------------------------------------------------------------- latência
def _pings(n: int, stop: threading.Event, conn=None, budget: float | None = None) -> tuple[list[float], dict]:
    """n pedidos vazios; pára antes se passar o tempo `budget` (ligações muito lentas), com pelo menos 4."""
    c = conn or _conn()
    times, meta = [], {}
    t0 = time.perf_counter()
    try:
        for _ in range(n):
            if stop.is_set():
                raise Cancelled
            if budget and len(times) >= 4 and time.perf_counter() - t0 > budget:
                break
            t = time.perf_counter()
            c.request("GET", "/__down?bytes=0", headers={"User-Agent": UA})
            r = c.getresponse()
            r.read()
            dt = (time.perf_counter() - t) * 1000 - _server_ms(r)
            times.append(max(0.5, dt))
            if not meta:
                meta = {"colo": r.getheader("cf-meta-colo") or "", "city": r.getheader("cf-meta-city") or "",
                        "ip": r.getheader("cf-meta-ip") or ""}
    finally:
        if conn is None:
            c.close()
    return times, meta


def measure_latency(stop: threading.Event, n: int = 12, budget: float = 4.0) -> tuple[float, float, dict]:
    """(ping mediano, jitter, meta). O 1.º pedido abre a ligação TLS e não conta."""
    c = _conn()
    try:
        _pings(1, stop, c)
        times, meta = _pings(n, stop, c, budget)
        try:  # centro de dados e país (o cabeçalho cf-meta-colo nem sempre vem)
            c.request("GET", "/cdn-cgi/trace", headers={"User-Agent": UA})
            for ln in c.getresponse().read().decode(errors="replace").splitlines():
                k, _s, v = ln.partition("=")
                if k in ("colo", "ip", "loc") and v:
                    meta[k] = meta.get(k) or v
        except (OSError, http.client.HTTPException):
            pass
    finally:
        c.close()
    ping = statistics.median(times)
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return ping, jitter, meta


# --------------------------------------------------------------------------- débito
class _Meter:
    """Conta bytes de várias threads e calcula a velocidade instantânea e a final."""

    def __init__(self):
        self.lock = threading.Lock()
        self.total = 0
        self.start = time.perf_counter()
        self.samples: list[tuple[float, int]] = [(0.0, 0)]

    def add(self, n: int):
        with self.lock:
            self.total += n

    def sample(self) -> float:
        """Mb/s na última ~1 s."""
        t = time.perf_counter() - self.start
        with self.lock:
            self.samples.append((t, self.total))
        ref = next(((ts, b) for ts, b in reversed(self.samples) if t - ts >= 1.0), self.samples[0])
        dt = t - ref[0]
        return (self.total - ref[1]) * 8 / dt / 1e6 if dt > 0 else 0.0

    def result(self) -> float:
        t = time.perf_counter() - self.start
        base = next(((ts, b) for ts, b in self.samples if ts >= WARMUP), None)
        if base is None or t - base[0] < 0.5:
            return self.total * 8 / max(t, 0.001) / 1e6
        return (self.total - base[1]) * 8 / (t - base[0]) / 1e6


def _download_worker(meter: _Meter, end: float, stop: threading.Event):
    while time.perf_counter() < end and not stop.is_set():
        c = _conn()
        try:
            c.request("GET", f"/__down?bytes={DL_CHUNK}", headers={"User-Agent": UA})
            r = c.getresponse()
            while time.perf_counter() < end and not stop.is_set():
                data = r.read(65536)
                if not data:
                    break
                meter.add(len(data))
        except (OSError, http.client.HTTPException):
            time.sleep(0.2)
        finally:
            c.close()


_PAYLOAD = os.urandom(1 << 20)  # 1 MB aleatório (não comprimível), enviado repetidamente


def _upload_worker(meter: _Meter, end: float, stop: threading.Event):
    block = memoryview(_PAYLOAD)[:65536]
    while time.perf_counter() < end and not stop.is_set():
        c = _conn()
        try:
            c.putrequest("POST", "/__up")
            c.putheader("User-Agent", UA)
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(UL_CHUNK))
            c.endheaders()
            sent = 0
            while sent < UL_CHUNK and time.perf_counter() < end and not stop.is_set():
                n = min(len(block), UL_CHUNK - sent)
                c.send(block[:n])
                sent += n
                meter.add(n)
            if sent >= UL_CHUNK:
                c.getresponse().read()
        except (OSError, http.client.HTTPException):
            time.sleep(0.2)
        finally:
            c.close()


def _run_phase(worker, streams: int, seconds: float, stop: threading.Event, on_sample, phase: str,
               loaded: list | None = None) -> float:
    meter = _Meter()
    end = time.perf_counter() + seconds
    threads = [threading.Thread(target=worker, args=(meter, end, stop), daemon=True) for _ in range(streams)]
    for t in threads:
        t.start()
    if loaded is not None:  # mede a latência com a ligação cheia, numa thread à parte
        def lp():
            try:
                time.sleep(WARMUP)
                if time.perf_counter() < end - 1:
                    times, _m = _pings(5, stop)
                    loaded.extend(times)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=lp, daemon=True).start()
    while time.perf_counter() < end:
        if stop.is_set():
            raise Cancelled
        time.sleep(0.2)
        on_sample(phase, meter.sample(), min(1.0, 1 - (end - time.perf_counter()) / seconds))
    for t in threads:
        t.join(timeout=3)
    if meter.total == 0:
        raise ConnectionError("Não foi possível transferir dados do servidor de teste.")
    return meter.result()


def run(on_progress=None, stop: threading.Event | None = None, seconds: float = 10.0) -> SpeedResult:
    """Corre o teste completo. on_progress(fase, valor, fração) com fase em
    'ping' (ms), 'download'/'upload' (Mb/s) ou 'info' (dict). Levanta Cancelled se stop for ativado."""
    stop = stop or threading.Event()
    emit = on_progress or (lambda *_a: None)
    res = SpeedResult()

    emit("phase", "ping", 0)
    ping, jitter, meta = measure_latency(stop)
    res.ping_ms, res.jitter_ms = ping, jitter
    colo = meta.get("colo", "")
    city = _COLOS.get(colo, "") or meta.get("city", "") or colo
    res.server = f"Cloudflare · {city}" if city else "Cloudflare"
    res.ip = meta.get("ip", "")
    emit("info", {"server": res.server, "ip": res.ip, "ping": ping, "jitter": jitter}, 1)

    loaded: list[float] = []
    emit("phase", "download", 0)
    res.download_mbps = _run_phase(_download_worker, 6, seconds, stop, emit, "download", loaded)
    if loaded:
        res.loaded_ping_ms = statistics.median(loaded)
    emit("done_phase", "download", res.download_mbps)

    emit("phase", "upload", 0)
    res.upload_mbps = _run_phase(_upload_worker, 4, seconds * 0.8, stop, emit, "upload")
    emit("done_phase", "upload", res.upload_mbps)
    return res


# --------------------------------------------------------------------------- interpretação e histórico
def quality(r: SpeedResult) -> list[tuple[str, str, str]]:
    """[(atividade, nível ok/warn/bad, explicação)] — o que a ligação permite fazer."""
    d, u, p, j = r.download_mbps or 0, r.upload_mbps or 0, r.ping_ms or 999, r.jitter_ms or 0

    def lvl(good: bool, fair: bool) -> str:
        return "ok" if good else "warn" if fair else "bad"
    return [
        ("Navegar e redes sociais", lvl(d >= 10, d >= 3), f"{d:.0f} Mb/s"),
        ("Vídeo em 4K", lvl(d >= 25, d >= 15), "precisa de ~25 Mb/s"),
        ("Jogos online", lvl(p <= 40 and j <= 10, p <= 80 and j <= 30), f"latência {p:.0f} ms · variação {j:.0f} ms"),
        ("Videochamadas", lvl(u >= 5 and p <= 100, u >= 1.5 and p <= 200), f"envio {u:.0f} Mb/s"),
        ("Transmitir (streaming)", lvl(u >= 10, u >= 5), "1080p60 precisa de ~6–10 Mb/s de envio"),
        ("Descarregar um jogo de 50 GB", lvl(d >= 100, d >= 30), duration_for(50e9, d)),
    ]


def duration_for(nbytes: float, mbps: float) -> str:
    if not mbps:
        return "—"
    s = nbytes * 8 / (mbps * 1e6)
    if s < 90:
        return f"~{s:.0f} s"
    if s < 5400:
        return f"~{s / 60:.0f} min"
    return f"~{s / 3600:.1f} h"


def bufferbloat(r: SpeedResult) -> tuple[str, str] | None:
    """(nível, texto) sobre a subida da latência com a ligação cheia."""
    if r.loaded_ping_ms is None or r.ping_ms is None:
        return None
    extra = r.loaded_ping_ms - r.ping_ms
    if extra < 30:
        return "ok", f"A latência quase não sobe com a ligação cheia (+{max(0, extra):.0f} ms) — ótimo para jogar."
    if extra < 100:
        return "warn", f"A latência sobe {extra:.0f} ms com a ligação cheia — pode notar atrasos ao jogar enquanto " \
                       "alguém descarrega."
    return "bad", f"A latência sobe {extra:.0f} ms com a ligação cheia (bufferbloat). Ative o SQM/QoS no router, " \
                  "se existir."


def history() -> list[dict]:
    h = get_setting("speed_history") or []
    return h if isinstance(h, list) else []


def save(r: SpeedResult) -> None:
    set_setting("speed_history", ([r.to_dict()] + history())[:30])


def clear_history() -> None:
    set_setting("speed_history", [])
