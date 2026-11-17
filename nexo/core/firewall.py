"""Firewall e portas abertas: o PC está a aceitar ligações de outros computadores da rede?

Linux: ufw (/etc/ufw/ufw.conf, legível sem root), firewalld ou nftables (systemctl); portas à escuta com
psutil (sem root não se sabe o programa dos serviços do sistema — usa-se o nome habitual da porta).
Windows: Get-NetFirewallProfile e portas à escuta com psutil.

Uma porta só a escutar em 127.0.0.1/::1 é local (só o próprio PC chega lá); em 0.0.0.0/:: ou num IP da
rede fica exposta — sem firewall, qualquer aparelho da mesma rede (Wi-Fi do café, rede da escola) pode ligar-se."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from dataclasses import asdict, dataclass

import psutil

from .util import IS_LINUX, IS_WIN, as_list, load_json, ps_json, read_text, run, run_root, save_json, which

CACHE = "firewall.json"

SERVICES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP (servidor)", 80: "HTTP", 111: "rpcbind", 135: "RPC do Windows",
    137: "NetBIOS", 138: "NetBIOS", 139: "Partilha de ficheiros (SMB)", 443: "HTTPS",
    445: "Partilha de ficheiros (SMB)", 548: "AFP", 631: "Impressoras (CUPS)", 1716: "KDE Connect",
    1900: "UPnP/SSDP", 2049: "NFS", 2375: "Docker (sem cifra)", 2376: "Docker", 3000: "Servidor de desenvolvimento",
    3306: "MySQL/MariaDB", 3389: "Ambiente de Trabalho Remoto", 5000: "Servidor de desenvolvimento",
    5353: "mDNS (descoberta na rede)", 5355: "LLMNR", 5432: "PostgreSQL", 5900: "VNC", 5901: "VNC",
    6379: "Redis", 8000: "Servidor de desenvolvimento", 8080: "Servidor web", 8384: "Syncthing",
    9090: "Painel web", 11434: "Ollama", 22000: "Syncthing", 27017: "MongoDB", 27036: "Steam (Remote Play)",
    32400: "Plex",
}
# exposto sem firewall = qualquer um na rede pode tentar entrar
RISKY = {21, 23, 135, 139, 445, 2375, 3306, 3389, 5432, 5900, 5901, 6379, 11434, 27017}
# serviços de descoberta/cliente que estão sempre abertos e não são problema
NORMAL_UDP = {67, 68, 137, 138, 546, 1900, 3702, 5353, 5355}


@dataclass
class FwStatus:
    active: bool | None      # None = não se sabe
    name: str = ""           # ufw, firewalld, nftables, Firewall do Windows
    detail: str = ""
    installed: str = ""      # firewall instalada mas desligada (para o botão Ativar)


@dataclass
class Port:
    proto: str               # TCP | UDP
    port: int
    addr: str
    process: str = ""
    exposed: bool = False

    @property
    def service(self) -> str:
        return SERVICES.get(self.port, "")


# --------------------------------------------------------------------------- estado da firewall
def _active(unit: str) -> bool:
    code, out = run(["systemctl", "is-active", unit], timeout=5)
    return out.strip() == "active"


def status() -> FwStatus:
    if IS_WIN:
        fw = ps_json("Get-NetFirewallProfile | Select-Object Name,Enabled", timeout=30)
        profs = [f for f in as_list(fw) if isinstance(f, dict)]
        if not profs:
            return FwStatus(None, "Firewall do Windows")
        off = [str(f.get("Name")) for f in profs if not f.get("Enabled")]
        return FwStatus(not off, "Firewall do Windows",
                        f"Desligada nos perfis: {', '.join(off)}" if off else "Ligada em todos os perfis",
                        "windows" if off else "")
    if not IS_LINUX:
        return FwStatus(None)
    if which("ufw"):
        conf = read_text("/etc/ufw/ufw.conf") or ""
        if re.search(r"^\s*ENABLED\s*=\s*yes", conf, re.M | re.I):
            return FwStatus(True, "ufw", "Bloqueia ligações que chegam de fora, exceto as que autorizou.")
    if which("firewall-cmd") or os.path.exists("/usr/lib/systemd/system/firewalld.service"):
        if _active("firewalld"):
            return FwStatus(True, "firewalld", "Zona ativa com as regras da distribuição.")
    if _active("nftables"):
        return FwStatus(True, "nftables", "Regras próprias (/etc/nftables.conf).")
    if which("ufw"):
        return FwStatus(False, "ufw", "Instalada mas desligada.", "ufw")
    if which("firewall-cmd"):
        return FwStatus(False, "firewalld", "Instalada mas desligada.", "firewalld")
    return FwStatus(False, "", "Nenhuma firewall instalada.")


# --------------------------------------------------------------------------- portas à escuta
_VIRTUAL = ("virbr", "docker", "br-", "veth", "vmnet", "vboxnet", "lxcbr", "podman", "cni", "waydroid")


def _virtual_ips() -> set[str]:
    """IPs das redes virtuais (máquinas virtuais, Docker): só o próprio PC chega lá."""
    out = set()
    try:
        for name, addrs in psutil.net_if_addrs().items():
            if name.lower().startswith(_VIRTUAL) or "vethernet" in name.lower():
                out.update(a.address.split("%")[0] for a in addrs)
    except OSError:
        pass
    return out


def _exposed(addr: str, virtual: set[str] = frozenset()) -> bool:
    addr = addr.split("%")[0]
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    return not ip.is_loopback and addr not in virtual


def listening() -> list[Port]:
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        return []
    virtual = _virtual_ips()
    names: dict[int, str] = {}
    seen: dict[tuple[str, int], Port] = {}
    for c in conns:
        if not c.laddr:
            continue
        tcp = c.type == socket.SOCK_STREAM
        if tcp and c.status != psutil.CONN_LISTEN:
            continue
        if not tcp and (c.raddr or (c.laddr.port >= 1024 and c.laddr.port not in SERVICES)):
            continue   # UDP: só serviços conhecidos (o resto são clientes com portas aleatórias)
        proc = ""
        if c.pid:
            if c.pid not in names:
                try:
                    names[c.pid] = psutil.Process(c.pid).name()
                except (psutil.Error, OSError):
                    names[c.pid] = ""
            proc = names[c.pid]
        key = ("TCP" if tcp else "UDP", c.laddr.port)
        p = seen.get(key)
        exp = _exposed(c.laddr.ip, virtual)
        if p is None:
            seen[key] = Port(key[0], key[1], c.laddr.ip, proc, exp)
        else:   # a mesma porta em IPv4 e IPv6: fica exposta se alguma estiver
            p.exposed = p.exposed or exp
            p.process = p.process or proc
            if exp:
                p.addr = c.laddr.ip
    return sorted(seen.values(), key=lambda p: (not p.exposed, p.proto, p.port))


# --------------------------------------------------------------------------- conclusões
def analyze(st: FwStatus, ports: list[Port]) -> list[tuple[str, str]]:
    """[(ok|info|warn|bad, texto)]"""
    exposed = [p for p in ports if p.exposed and not (p.proto == "UDP" and p.port in NORMAL_UDP)]
    risky = [p for p in exposed if p.port in RISKY and not (IS_WIN and p.port in (135, 139, 445))]
    out: list[tuple[str, str]] = []
    if st.active is False:
        name = f" ({st.name})" if st.name else ""
        if risky:
            what = ", ".join(f"{p.service or p.port} ({p.port})" for p in risky[:4])
            out.append(("bad", f"Firewall desligada{name} e serviços sensíveis abertos para a rede: {what}. "
                               "Ative a firewall ou desligue esses serviços."))
        elif exposed:
            out.append(("warn", f"Firewall desligada{name} — {len(exposed)} porta(s) aceitam ligações de outros "
                                "aparelhos da rede. Numa rede pública (café, escola, hotel) é um risco."))
        else:
            out.append(("warn", f"Firewall desligada{name}. Nenhum serviço está aberto para a rede agora, mas "
                                "convém tê-la ligada."))
    elif st.active:
        out.append(("ok", f"{st.name} ativa." + (f" {len(exposed)} porta(s) abertas no PC, protegidas pela "
                                                 "firewall (só passam as que autorizou)." if exposed else "")))
    if any(p.port == 2375 for p in exposed):
        out.append(("bad", "A API do Docker está aberta na rede sem cifra (porta 2375) — dá controlo total do PC "
                           "a quem lá chegar."))
    if not exposed:
        out.append(("ok", "Nenhum serviço aceita ligações de outros aparelhos — só do próprio PC."))
    return out


def scan() -> dict:
    st = status()
    ports = listening()
    data = {"status": asdict(st), "ports": [asdict(p) for p in ports]}
    try:
        save_json(CACHE, data)
    except OSError:
        pass
    return {"status": st, "ports": ports, "findings": analyze(st, ports)}


def cached() -> tuple[FwStatus | None, list[Port]]:
    data = load_json(CACHE, {}) or {}
    try:
        st = FwStatus(**data["status"])
        ports = [Port(**p) for p in data.get("ports", [])]
    except (KeyError, TypeError):
        return None, []
    return st, ports


# --------------------------------------------------------------------------- ligar
def enable(st: FwStatus) -> tuple[bool, str]:
    """Liga a firewall instalada (ou instala a da distribuição). Pede a palavra-passe / administrador."""
    if IS_WIN:
        from .util import is_admin
        if not is_admin():
            return False, "É preciso abrir o Nexo como administrador (botão Admin no menu)."
        code, out = run(["powershell", "-NoProfile", "-Command",
                         "Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True"], timeout=60)
        return code == 0, "Firewall do Windows ligada." if code == 0 else out.strip()[:300]
    if st.installed == "ufw" or (not st.installed and which("ufw")):
        code, out = run_root(["ufw", "--force", "enable"], timeout=120)
        return code == 0, "ufw ligada: bloqueia as ligações que chegam de fora." if code == 0 else out.strip()[:300]
    if st.installed == "firewalld":
        code, out = run_root(["systemctl", "enable", "--now", "firewalld"], timeout=120)
        return code == 0, "firewalld ligada." if code == 0 else out.strip()[:300]
    from .systools import linux_pkg_manager
    pm = linux_pkg_manager()
    cmds = {"pacman": "pacman -S --needed --noconfirm ufw && systemctl enable --now ufw && ufw --force enable",
            "apt": "apt-get install -y ufw && ufw --force enable",
            "dnf": "dnf install -y firewalld && systemctl enable --now firewalld",
            "zypper": "zypper --non-interactive install firewalld && systemctl enable --now firewalld"}
    if pm not in cmds:
        return False, "Gestor de pacotes não reconhecido — instale o ufw ou o firewalld à mão."
    code, out = run_root(cmds[pm], timeout=600)
    return code == 0, "Firewall instalada e ligada." if code == 0 else out.strip()[-300:]
