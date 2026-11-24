"""Deteção da ligação à internet (Windows e Linux), sem dependências além do psutil.

O teste é feito por etapas, para dizer ao utilizador *onde* está o problema e não só "sem internet":
1. placa de rede ligada com endereço (Wi-Fi/cabo/VPN, ignorando adaptadores virtuais);
2. ligação TCP a vários servidores públicos por IP (não depende do DNS);
3. resolução de nomes (DNS);
4. pedido HTTP a uma página de verificação, que deteta redes com página de login (hotéis, aeroportos…).

Todas as etapas têm tempo limite curto e correm em paralelo onde possível: o teste completo demora
normalmente menos de 1 s com internet e no máximo ~4 s sem ela. Deve correr fora da thread da interface.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import psutil

# Estados possíveis (do melhor para o pior)
ONLINE = "online"        # internet a funcionar
PORTAL = "portal"        # rede com página de login (captive portal)
NO_DNS = "sem_dns"       # há internet, mas o DNS não responde
LIMITED = "limitada"     # ligado à rede local/router, mas sem acesso à internet
OFFLINE = "sem_rede"     # nenhuma placa de rede ligada

LABELS = {
    ONLINE: "Ligado",
    PORTAL: "Requer início de sessão",
    NO_DNS: "DNS sem resposta",
    LIMITED: "Sem acesso à internet",
    OFFLINE: "Sem rede",
}

# servidores contactados por IP (porta 443 raramente é bloqueada; 53 como alternativa)
_TCP_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443), ("208.67.222.222", 443),
                ("1.0.0.1", 53), ("8.8.4.4", 53)]
_TCP_TARGETS_V6 = [("2606:4700:4700::1111", 443), ("2001:4860:4860::8888", 443)]
_DNS_NAMES = ["connectivitycheck.gstatic.com", "www.msftconnecttest.com", "cloudflare.com"]
# (url, código esperado, conteúdo esperado) — páginas oficiais usadas pelo Android e pelo Windows
_PORTAL_CHECKS = [("http://connectivitycheck.gstatic.com/generate_204", 204, None),
                  ("http://www.msftconnecttest.com/connecttest.txt", 200, b"Microsoft Connect Test"),
                  ("http://cp.cloudflare.com/generate_204", 204, None)]

_VIRTUAL = ("lo", "docker", "br-", "virbr", "veth", "vmnet", "vboxnet", "vethernet", "loopback",
            "isatap", "teredo", "bluetooth", "zt", "lxc", "lxd", "podman", "cni", "flannel", "kube")
# (prefixos do nome no Linux, palavras no nome no Windows)
_KINDS = [("VPN", ("tun", "tap", "wg", "ppp"), ("vpn", "nordlynx", "tailscale", "proton", "mullvad", "wireguard")),
          ("Wi-Fi", ("wl",), ("wi-fi", "wifi", "wlan", "wireless", "sem fios")),
          ("Cabo", ("en", "eth"), ("ethernet", "local area connection", "ligação de área local"))]


@dataclass
class NetStatus:
    state: str
    latency_ms: float | None = None
    iface: str = ""            # nome da placa usada
    kind: str = ""             # "Wi-Fi", "Cabo", "VPN" ou ""
    detail: str = ""           # explicação para o utilizador
    steps: list[tuple[str, bool | None, str]] = field(default_factory=list)  # (etapa, ok?, detalhe)
    checked_at: float = field(default_factory=time.time)

    @property
    def online(self) -> bool:
        """True quando é possível descarregar (internet direta). Portal e DNS em falha contam como não."""
        return self.state == ONLINE

    @property
    def label(self) -> str:
        return LABELS.get(self.state, self.state)

    @property
    def level(self) -> str:
        """Cor do tema: ok / warn / bad."""
        return "ok" if self.state == ONLINE else "bad" if self.state == OFFLINE else "warn"

    def short(self) -> str:
        if self.state == ONLINE:
            parts = [self.kind or "Ligado"]
            if self.latency_ms is not None:
                parts.append(f"{self.latency_ms:.0f} ms")
            return " · ".join(parts)
        return self.label


# --------------------------------------------------------------------------- etapa 1: placas
def _kind(name: str) -> str:
    n = name.lower()
    for kind, prefixes, words in _KINDS:
        if n.startswith(prefixes) or any(w in n for w in words):
            return kind
    return ""


def interfaces() -> list[tuple[str, str]]:
    """[(nome, tipo)] das placas de rede ligadas com um endereço utilizável, físicas primeiro."""
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for name, st in stats.items():
        low = name.lower()
        if not st.isup or low.startswith(_VIRTUAL) or any(v in low for v in ("virtual", "vmware", "hyper-v",
                                                                               "pseudo", "loopback")):
            continue
        good = False
        for a in addrs.get(name, []):
            if a.family == socket.AF_INET and a.address and not a.address.startswith(("127.", "169.254.")):
                good = True
            elif a.family == socket.AF_INET6 and a.address and not a.address.lower().startswith(("fe80", "::1")):
                good = True
        if good:
            out.append((name, _kind(name)))
    order = {"Cabo": 0, "Wi-Fi": 1, "": 2, "VPN": 3}
    return sorted(out, key=lambda x: order.get(x[1], 2))


# --------------------------------------------------------------------------- etapa 2: TCP por IP
def _tcp(host: str, port: int, timeout: float) -> float:
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        t = time.perf_counter()
        s.connect((host, port))
        return (time.perf_counter() - t) * 1000
    finally:
        s.close()


def _first_success(fn, items, timeout: float):
    """Corre fn(item) em paralelo e devolve (item, resultado) do primeiro que der certo, ou (None, None)."""
    ex = ThreadPoolExecutor(max(1, len(items)))
    try:
        futs = {ex.submit(fn, it): it for it in items}
        pending = set(futs)
        end = time.monotonic() + timeout
        while pending:
            left = end - time.monotonic()
            if left <= 0:
                break
            done, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
            for f in done:
                if f.exception() is None:
                    return futs[f], f.result()
        return None, None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def reach_internet(timeout: float = 2.5) -> float | None:
    """Latência (ms) do servidor público mais rápido, ou None se nenhum responder."""
    targets = list(_TCP_TARGETS)
    if socket.has_ipv6:
        targets += _TCP_TARGETS_V6
    _t, ms = _first_success(lambda hp: _tcp(hp[0], hp[1], timeout), targets, timeout + 0.3)
    return ms


# --------------------------------------------------------------------------- etapa 3: DNS
def resolves(timeout: float = 2.5) -> bool:
    name, _r = _first_success(lambda n: socket.getaddrinfo(n, 80, proto=socket.IPPROTO_TCP), _DNS_NAMES, timeout)
    return name is not None


# --------------------------------------------------------------------------- etapa 4: portal
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):  # um redirecionamento aqui = página de login
        return None


def _portal_one(check, timeout: float) -> str:
    url, code, body = check
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "Nexo", "Cache-Control": "no-cache"})
    try:
        with opener.open(req, timeout=timeout) as r:  # noqa: S310 (URL http fixa, só verificação)
            data = r.read(256)
            ok = r.status == code and (body is None or data.strip().startswith(body))
            return "ok" if ok else "portal"
    except urllib.error.HTTPError as e:
        return "portal" if 300 <= e.code < 400 or e.code in (401, 403, 407, 511) else "erro"


def portal_check(timeout: float = 3.0) -> str:
    """'ok', 'portal' (rede pede login) ou 'erro' (não foi possível verificar — p. ex. proxy/firewall)."""
    res = []
    ex = ThreadPoolExecutor(len(_PORTAL_CHECKS))
    try:
        futs = [ex.submit(_portal_one, c, timeout) for c in _PORTAL_CHECKS]
        for f in futs:
            try:
                r = f.result(timeout=timeout + 0.5)
            except Exception:  # noqa: BLE001
                r = "erro"
            if r == "ok":
                return "ok"
            res.append(r)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return "portal" if "portal" in res else "erro"


# --------------------------------------------------------------------------- teste completo
def check(full: bool = True) -> NetStatus:
    """Testa a ligação. full=False salta a verificação de portal (usado no teste periódico com internet)."""
    steps: list[tuple[str, bool | None, str]] = []
    ifs = interfaces()
    iface, kind = (ifs[0] if ifs else ("", ""))
    if not ifs:
        steps.append(("Placa de rede", False, "Nenhuma ligação Wi-Fi ou por cabo ativa"))
        return NetStatus(OFFLINE, detail="O computador não está ligado a nenhuma rede. Verifique o Wi-Fi, o "
                         "cabo de rede ou o modo de avião.", steps=steps)
    steps.append(("Placa de rede", True, ", ".join(f"{n} ({k})" if k else n for n, k in ifs[:3])))

    with ThreadPoolExecutor(2) as ex:   # TCP e DNS ao mesmo tempo
        f_tcp = ex.submit(reach_internet)
        f_dns = ex.submit(resolves)
        ms, dns_ok = f_tcp.result(), f_dns.result()

    steps.append(("Acesso à internet", ms is not None,
                  f"Servidor público respondeu em {ms:.0f} ms" if ms is not None else "Nenhum servidor respondeu"))
    steps.append(("DNS (nomes de sites)", dns_ok, "A funcionar" if dns_ok else "Sem resposta"))

    if ms is None:
        # o DNS pode responder da cache local/do router mesmo sem internet, por isso não chega para dizer
        # "ligado"; pode também ser só uma firewall a bloquear ligações diretas — o HTTP (com o proxy do
        # sistema) decide
        p = portal_check()
        if p == "ok":
            steps.append(("Página de verificação", True, "Acessível (através de proxy)"))
            return NetStatus(ONLINE, None, iface, kind, "Internet através de proxy ou firewall.", steps)
        if p == "portal":
            steps.append(("Página de verificação", False, "A rede pede início de sessão"))
            return NetStatus(PORTAL, None, iface, kind, "Esta rede (hotel, aeroporto, escola…) pede para iniciar "
                             "sessão numa página web antes de dar acesso à internet. Abra o navegador.", steps)
        steps.append(("Página de verificação", False, "Inacessível"))
        return NetStatus(LIMITED, None, iface, kind, "Está ligado à rede, mas o router não tem acesso à internet. "
                         "Experimente reiniciar o router ou contacte o fornecedor de internet.", steps)

    if ms is not None and not dns_ok:
        return NetStatus(NO_DNS, ms, iface, kind, "Há internet, mas o servidor DNS não responde, por isso os "
                         "sites não abrem. Mude o DNS em Utilitários → DNS (p. ex. Cloudflare).", steps)

    if full:
        p = portal_check()
        if p == "portal":
            steps.append(("Página de verificação", False, "A rede pede início de sessão"))
            return NetStatus(PORTAL, ms, iface, kind, "Esta rede pede para iniciar sessão numa página web antes "
                             "de dar acesso à internet. Abra o navegador.", steps)
        steps.append(("Página de verificação", p == "ok" or None,
                      "Acessível" if p == "ok" else "Não foi possível verificar (proxy ou firewall)"))
    return NetStatus(ONLINE, ms, iface, kind, "A ligação à internet está a funcionar.", steps)


def is_online(timeout: float = 2.0) -> bool:
    """Teste rápido (sem portal), para usar antes de uma descarga."""
    return bool(interfaces()) and (reach_internet(timeout) is not None or portal_check(timeout) == "ok")


def friendly_error(exc: BaseException | str) -> str:
    """Traduz erros de rede comuns para uma mensagem compreensível."""
    msg = str(exc)
    low = msg.lower()
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror) or "getaddrinfo" in low or "name or service not known" in low \
            or "nodename nor servname" in low or "temporary failure in name resolution" in low or "11001" in low:
        return "Sem ligação à internet (não foi possível encontrar o servidor)."
    if isinstance(reason, TimeoutError) or "timed out" in low or "timeout" in low:
        return "A ligação demorou demasiado — a internet pode estar lenta ou instável."
    if "connection refused" in low or "10061" in low:
        return "O servidor recusou a ligação. Tente mais tarde."
    if "network is unreachable" in low or "10051" in low or "no route to host" in low:
        return "Sem ligação à internet (rede inacessível)."
    if "has expired" in low or "not yet valid" in low:
        return "Erro de segurança na ligação (certificado fora de prazo). Verifique a data e hora do sistema."
    if "local issuer" in low or "unable to get" in low or "self-signed" in low or "self signed" in low:
        return ("Erro de segurança na ligação: não foram encontrados os certificados do sistema. Instale/atualize "
                "o pacote ca-certificates ou use a versão mais recente do Nexo.")
    if "certificate" in low or "ssl" in low:
        return "Erro de segurança na ligação (certificado). Verifique a data e hora do sistema."
    if "http error 429" in low:
        return "Demasiados pedidos ao servidor — aguarde um pouco e tente de novo."
    if "http error 5" in low:
        return "O servidor está com problemas. Tente mais tarde."
    return msg
