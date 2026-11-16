"""Ferramentas do sistema (inspiradas nas secções "Config", "Updates" e "Tweaks" do WinUtil do Chris Titus).

Windows: ponto de restauro, reparações (SFC, DISM, rede, Windows Update), funcionalidades opcionais,
política de atualizações e atalhos para os painéis clássicos.
Linux: atualizar o sistema, manutenção (órfãos, TRIM, cache de DNS, firmware) e diagnóstico.
Ambos: DNS (escolher servidor + teste de velocidade).
"""
from __future__ import annotations

import os
import random
import re
import socket
import struct
import subprocess
import time
from dataclasses import dataclass, field

from . import snapshot
from .util import _NO_WINDOW, IS_LINUX, IS_WIN, is_admin, ps_json, run, run_ps, run_root, which


@dataclass
class Action:
    id: str
    name: str
    desc: str
    admin: bool = False
    long: bool = False          # demora vários minutos
    danger: bool = False        # pede confirmação
    run: object = field(default=None, repr=False)   # () -> (ok, mensagem)


def _need_admin() -> tuple[bool, str] | None:
    if IS_WIN and not is_admin():
        return False, "Precisa de executar o Nexo como administrador (botão Admin no menu)."
    return None


def _wrap(fn, admin=True):
    def go():
        if admin and (r := _need_admin()):
            return r
        return fn()
    return go


def _out_ok(code: int, out: str, ok_msg: str = "Concluído") -> tuple[bool, str]:
    lines = [ln.strip() for ln in out.replace("\r", "\n").splitlines() if ln.strip()]
    tail = "\n".join(lines[-4:])
    return code == 0, (tail or ok_msg) if code != 0 else (ok_msg + (f"\n{tail}" if tail else ""))


# =========================================================================== Windows
def win_restore_point(desc: str = "Nexo") -> tuple[bool, str]:
    # o Windows só deixa criar 1 ponto a cada 24 h — esta chave remove o limite
    run(["reg", "add", r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore", "/v",
         "SystemRestorePointCreationFrequency", "/t", "REG_DWORD", "/d", "0", "/f"], timeout=15)
    code, out = run_ps("Enable-ComputerRestore -Drive \"$env:SystemDrive\\\" -ErrorAction SilentlyContinue; "
                       f"Checkpoint-Computer -Description '{desc.replace(chr(39), '')}' "
                       "-RestorePointType MODIFY_SETTINGS -ErrorAction Stop; "
                       "'ok'", timeout=600)
    return (True, "Ponto de restauro criado (Painel de Controlo → Recuperação para voltar atrás).") \
        if code == 0 and "ok" in out else (False, out[-300:] or "Falhou")


def win_sfc() -> tuple[bool, str]:
    code, out = run(["sfc", "/scannow"], timeout=3600)
    out = out.replace("\x00", "")
    return _out_ok(code, out, "Verificação de ficheiros do sistema concluída")


def win_dism() -> tuple[bool, str]:
    code, out = run(["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"], timeout=3600)
    return _out_ok(code, out, "Imagem do Windows reparada")


def win_chkdsk() -> tuple[bool, str]:
    drive = os.environ.get("SystemDrive", "C:")
    code, out = run(["chkdsk", drive, "/scan"], timeout=3600)
    return _out_ok(code, out, "Verificação do disco concluída")


def win_reset_network() -> tuple[bool, str]:
    msgs = []
    for cmd in (["netsh", "winsock", "reset"], ["netsh", "int", "ip", "reset"], ["ipconfig", "/flushdns"],
                ["ipconfig", "/release"], ["ipconfig", "/renew"]):
        code, out = run(cmd, timeout=120)
        msgs.append(f"{' '.join(cmd)}: {'ok' if code == 0 else 'erro'}")
    return True, "Rede reposta. Reinicie o PC para terminar.\n" + " · ".join(msgs)


def win_reset_update() -> tuple[bool, str]:
    services = ["wuauserv", "bits", "cryptsvc", "msiserver"]
    for s in services:
        run(["net", "stop", s, "/y"], timeout=60)
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    stamp = time.strftime("%Y%m%d%H%M%S")
    moved = []
    for p in (os.path.join(windir, "SoftwareDistribution"), os.path.join(windir, "System32", "catroot2")):
        if os.path.exists(p):
            try:
                os.rename(p, f"{p}.nexo-{stamp}")
                moved.append(os.path.basename(p))
            except OSError as e:
                moved.append(f"{os.path.basename(p)} (não foi possível: {e.strerror})")
    for s in services:
        run(["net", "start", s], timeout=60)
    return True, ("Componentes do Windows Update repostos (" + ", ".join(moved) + "). "
                  "Volte a procurar atualizações nas Definições do Windows.")


def win_flush_dns() -> tuple[bool, str]:
    code, out = run(["ipconfig", "/flushdns"], timeout=30)
    return code == 0, "Cache de DNS limpa" if code == 0 else out


def win_actions() -> list[Action]:
    return [
        Action("restore", "Criar ponto de restauro", "Recomendado antes de mexer em ajustes ou remover apps.",
               True, run=_wrap(win_restore_point)),
        Action("sfc", "Verificar ficheiros do sistema (SFC)", "Procura e repara ficheiros do Windows danificados.",
               True, True, run=_wrap(win_sfc)),
        Action("dism", "Reparar imagem do Windows (DISM)",
               "Descarrega cópias boas dos componentes danificados. Faça antes do SFC se este não conseguir reparar.",
               True, True, run=_wrap(win_dism)),
        Action("chkdsk", "Verificar o disco do sistema", "Procura erros no sistema de ficheiros (sem reiniciar).",
               True, True, run=_wrap(win_chkdsk)),
        Action("dns", "Limpar cache de DNS", "Resolve sites que não abrem depois de mudarem de servidor.",
               False, run=_wrap(win_flush_dns, admin=False)),
        Action("net", "Repor a rede", "Winsock, TCP/IP e renovação do IP. Resolve muitos problemas de ligação.",
               True, danger=True, run=_wrap(win_reset_network)),
        Action("wu", "Repor o Windows Update",
               "Para quando as atualizações falham ou ficam presas. Renomeia a cache (não apaga nada).",
               True, True, True, run=_wrap(win_reset_update)),
    ]


# ------------------------------------------------------------------ funcionalidades opcionais
@dataclass
class Feature:
    name: str
    desc: str
    features: list[str]


WIN_FEATURES = [
    Feature("WSL (Subsistema Linux)", "Corre Linux (Ubuntu, Debian…) dentro do Windows.",
            ["Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform"]),
    Feature("Hyper-V", "Máquinas virtuais da Microsoft (Windows Pro/Enterprise).", ["Microsoft-Hyper-V-All"]),
    Feature("Windows Sandbox", "Ambiente descartável para testar programas suspeitos (Pro/Enterprise).",
            ["Containers-DisposableClientVM"]),
    Feature(".NET Framework 3.5", "Necessário para programas e jogos mais antigos.", ["NetFx3"]),
    Feature("Componentes legados (DirectPlay)", "Necessário para alguns jogos antigos.", ["DirectPlay", "LegacyComponents"]),
]


def win_feature_states() -> dict[str, bool]:
    names = [f for feat in WIN_FEATURES for f in feat.features]
    data = ps_json("Get-WindowsOptionalFeature -Online | Where-Object { @(" + ",".join(f"'{n}'" for n in names)
                   + ") -contains $_.FeatureName } | Select-Object FeatureName, State", timeout=120)
    out = {}
    for d in (data if isinstance(data, list) else [data] if data else []):
        out[d.get("FeatureName")] = str(d.get("State")) in ("Enabled", "2")
    return out


def win_set_feature(feat: Feature, on: bool) -> tuple[bool, str]:
    if r := _need_admin():
        return r
    msgs = []
    ok = True
    for f in feat.features:
        cmd = ["dism", "/online", "/enable-feature" if on else "/disable-feature", f"/featurename:{f}", "/norestart"]
        if on:
            cmd.append("/all")
        code, out = run(cmd, timeout=1800)
        if code not in (0, 3010):  # 3010 = feito, falta reiniciar
            ok = False
            msgs.append(f"{f}: {out.strip().splitlines()[-1] if out.strip() else code}")
    return ok, ("Feito — reinicie o PC para concluir." if ok else "; ".join(msgs))


# ------------------------------------------------------------------ política de atualizações
_WU = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
_AU = _WU + r"\AU"


def win_update_mode() -> str:
    """'default' | 'security'"""
    code, out = run(["reg", "query", _WU, "/v", "DeferFeatureUpdatesPeriodInDays"], timeout=15)
    return "security" if code == 0 and "0x16d" in out.lower() else "default"


def win_set_update_mode(mode: str) -> tuple[bool, str]:
    if r := _need_admin():
        return r
    if mode == "security":
        vals = [("DeferFeatureUpdates", 1), ("DeferFeatureUpdatesPeriodInDays", 365),
                ("DeferQualityUpdates", 1), ("DeferQualityUpdatesPeriodInDays", 4)]
        for name, v in vals:
            code, out = run(["reg", "add", _WU, "/v", name, "/t", "REG_DWORD", "/d", str(v), "/f"], timeout=15)
            if code != 0:
                return False, out
        return True, ("Modo \"só segurança\": atualizações de segurança chegam 4 dias depois e as grandes "
                      "atualizações de funcionalidades esperam 1 ano.")
    for name in ("DeferFeatureUpdates", "DeferFeatureUpdatesPeriodInDays", "DeferQualityUpdates",
                 "DeferQualityUpdatesPeriodInDays"):
        run(["reg", "delete", _WU, "/v", name, "/f"], timeout=15)
    return True, "Windows Update com a configuração predefinida."


def win_drivers_via_update() -> bool:
    code, out = run(["reg", "query", _WU, "/v", "ExcludeWUDriversInQualityUpdate"], timeout=15)
    return not (code == 0 and "0x1" in out.lower())


def win_set_drivers_via_update(on: bool) -> tuple[bool, str]:
    if r := _need_admin():
        return r
    if on:
        run(["reg", "delete", _WU, "/v", "ExcludeWUDriversInQualityUpdate", "/f"], timeout=15)
        return True, "O Windows Update volta a instalar drivers."
    code, out = run(["reg", "add", _WU, "/v", "ExcludeWUDriversInQualityUpdate", "/t", "REG_DWORD", "/d", "1", "/f"],
                    timeout=15)
    return code == 0, ("O Windows Update deixa de substituir os drivers (útil para manter o driver da GPU "
                       "que instalou).") if code == 0 else out


# ------------------------------------------------------------------ painéis clássicos
WIN_PANELS = [
    ("Painel de Controlo", ["control"]), ("Ligações de rede", ["ncpa.cpl"]), ("Opções de energia", ["powercfg.cpl"]),
    ("Som", ["mmsys.cpl"]), ("Propriedades do sistema", ["sysdm.cpl"]), ("Programas e funcionalidades", ["appwiz.cpl"]),
    ("Gestor de dispositivos", ["devmgmt.msc"]), ("Gestão de discos", ["diskmgmt.msc"]),
    ("Serviços", ["services.msc"]), ("Agendador de tarefas", ["taskschd.msc"]),
    ("Visualizador de eventos", ["eventvwr.msc"]), ("Contas de utilizador", ["netplwiz"]),
    ("Configuração do sistema", ["msconfig"]), ("Editor de registo", ["regedit"]),
]


def open_panel(cmd: list[str]) -> None:
    if IS_WIN:
        subprocess.Popen(["cmd", "/c", "start", "", *cmd], creationflags=_NO_WINDOW)


# =========================================================================== Linux
def linux_pkg_manager() -> str | None:
    for pm in ("pacman", "apt", "dnf", "zypper"):
        if which(pm):
            return pm
    return None


def linux_update_system() -> tuple[bool, str]:
    pm = linux_pkg_manager()
    cmds = {
        "pacman": "pacman -Syu --noconfirm",
        "apt": "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade",
        "dnf": "dnf -y upgrade --refresh",
        "zypper": "zypper --non-interactive update",
    }
    if pm not in cmds:
        return False, "Gestor de pacotes não reconhecido."
    code, out = run_root(cmds[pm], timeout=3600)
    ok, msg = _out_ok(code, out, "Sistema atualizado")
    return ok, msg


def linux_orphans() -> tuple[bool, str]:
    pm = linux_pkg_manager()
    if pm == "pacman":
        code, out = run(["pacman", "-Qtdq"], timeout=60)
        pk = out.split() if code == 0 else []
        if not pk:
            return True, "Não há pacotes órfãos."
        code, out = run_root(snapshot.with_snapshot("pacman -Rns --noconfirm " + " ".join(pk),
                                                    "remover pacotes órfãos"), timeout=900)
        return _out_ok(code, out, f"{len(pk)} pacotes órfãos removidos")
    if pm == "apt":
        return _out_ok(*run_root(snapshot.with_snapshot("apt-get -y autoremove --purge", "remover pacotes órfãos"), timeout=900),
                       "Pacotes sem uso removidos")
    if pm == "dnf":
        return _out_ok(*run_root(snapshot.with_snapshot("dnf -y autoremove", "remover pacotes órfãos"), timeout=900),
                       "Pacotes sem uso removidos")
    if pm == "zypper":
        return _out_ok(*run_root("zypper --non-interactive rm -u $(zypper -q pa --unneeded | awk -F'|' 'NR>2{print $3}')",
                                 timeout=900), "Pacotes sem uso removidos")
    return False, "Gestor de pacotes não reconhecido."


def linux_trim() -> tuple[bool, str]:
    return _out_ok(*run_root(["fstrim", "-av"], timeout=1800), "TRIM concluído")


def linux_flush_dns() -> tuple[bool, str]:
    if which("resolvectl"):
        code, out = run(["resolvectl", "flush-caches"], timeout=20)
        if code != 0:
            code, out = run_root(["resolvectl", "flush-caches"], timeout=60)
        return code == 0, "Cache de DNS limpa" if code == 0 else out
    return False, "O systemd-resolved não está em uso (não há cache de DNS a limpar)."


def linux_firmware() -> tuple[bool, str]:
    if not which("fwupdmgr"):
        return False, "Instale o fwupd para atualizar firmware (BIOS, SSD, periféricos)."
    run(["fwupdmgr", "refresh", "--force"], timeout=300)
    code, out = run(["fwupdmgr", "get-updates", "--no-unreported-check", "--no-metadata-check"], timeout=300)
    if "no updates" in out.lower() or "no upgrades" in out.lower() or code == 2:
        return True, "O firmware está atualizado."
    code, out = run(["fwupdmgr", "update", "-y", "--no-reboot-check"], timeout=1800)
    return _out_ok(code, out, "Firmware atualizado (pode ser preciso reiniciar)")


def linux_failed_services() -> tuple[bool, str]:
    code, out = run(["systemctl", "--failed", "--no-legend", "--plain"], timeout=20)
    code2, out2 = run(["systemctl", "--user", "--failed", "--no-legend", "--plain"], timeout=20)
    lines = [ln.split()[0] for ln in (out + "\n" + out2).splitlines() if ln.strip() and not ln.startswith("comando")]
    return True, ("Serviços com falha: " + ", ".join(lines)) if lines else "Nenhum serviço com falha."


def linux_journal_errors() -> tuple[bool, str]:
    code, out = run(["journalctl", "-b", "-p", "3", "--no-pager", "-q", "-o", "cat", "-n", "300"], timeout=30)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return True, "Sem erros registados neste arranque."
    common: dict[str, int] = {}
    for ln in lines:
        k = re.sub(r"\d+", "#", ln)[:120]
        common[k] = common.get(k, 0) + 1
    top = sorted(common.items(), key=lambda kv: -kv[1])[:6]
    return True, f"{len(lines)} erros neste arranque. Mais frequentes:\n" + "\n".join(f"{n}× {k}" for k, n in top)


def linux_actions() -> list[Action]:
    pm = linux_pkg_manager()
    acts = []
    if pm:
        acts.append(Action("upd", f"Atualizar o sistema ({pm})", "Instala todas as atualizações dos pacotes.",
                           True, True, run=linux_update_system))
        acts.append(Action("orph", "Remover pacotes órfãos", "Dependências que já nenhum programa usa.",
                           True, danger=True, run=linux_orphans))
    acts += [
        Action("trim", "TRIM dos SSDs", "Avisa os SSDs dos blocos livres (mantém o desempenho de escrita).",
               True, True, run=linux_trim),
        Action("dns", "Limpar cache de DNS", "Resolve sites que não abrem depois de mudarem de servidor.",
               run=linux_flush_dns),
        Action("fw", "Atualizar firmware (fwupd)", "BIOS/UEFI, SSDs, ratos, teclados e docks compatíveis.",
               True, True, run=linux_firmware),
        Action("svc", "Serviços com falha", "Lista os serviços do systemd que falharam.", run=linux_failed_services),
        Action("log", "Erros do arranque atual", "Resume os erros do registo (journal) desde o arranque.",
               run=linux_journal_errors),
    ]
    return acts


def actions() -> list[Action]:
    return win_actions() if IS_WIN else linux_actions() if IS_LINUX else []


# =========================================================================== DNS (ambos)
DNS_PROVIDERS = [
    ("Automático (do router)", []),
    ("Cloudflare", ["1.1.1.1", "1.0.0.1"]),
    ("Cloudflare (bloqueia malware)", ["1.1.1.2", "1.0.0.2"]),
    ("Cloudflare Família (malware + adultos)", ["1.1.1.3", "1.0.0.3"]),
    ("Google", ["8.8.8.8", "8.8.4.4"]),
    ("Quad9 (bloqueia malware)", ["9.9.9.9", "149.112.112.112"]),
    ("AdGuard (bloqueia anúncios)", ["94.140.14.14", "94.140.15.15"]),
    ("OpenDNS", ["208.67.222.222", "208.67.220.220"]),
]


def _dns_query_time(server: str, timeout: float = 1.5) -> float | None:
    """Tempo (ms) de uma pergunta DNS por UDP — média de 3 domínios, ignora o 1.º (aquecimento)."""
    times = []
    for host in ("example.com", "wikipedia.org", "github.com", "microsoft.com"):
        qid = random.randint(0, 65535)
        q = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
        q += b"".join(bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\x00" + struct.pack(">HH", 1, 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            t = time.perf_counter()
            s.sendto(q, (server, 53))
            data, _ = s.recvfrom(512)
            if data[:2] == q[:2]:
                times.append((time.perf_counter() - t) * 1000)
        except OSError:
            pass
        finally:
            s.close()
    if not times:
        return None
    times = times[1:] or times
    return sum(times) / len(times)


def dns_benchmark() -> list[tuple[str, float | None]]:
    from concurrent.futures import ThreadPoolExecutor
    provs = [(n, ips) for n, ips in DNS_PROVIDERS if ips]
    with ThreadPoolExecutor(len(provs)) as ex:
        res = list(ex.map(lambda p: _dns_query_time(p[1][0]), provs))
    return sorted(((n, t) for (n, _), t in zip(provs, res)), key=lambda x: (x[1] is None, x[1] or 0))


def current_dns() -> list[str]:
    if IS_WIN:
        data = ps_json("Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses } | "
                       "Select-Object -ExpandProperty ServerAddresses", timeout=30)
        return [str(x) for x in (data if isinstance(data, list) else [data] if data else [])][:4]
    if which("resolvectl"):
        code, out = run(["resolvectl", "dns"], timeout=10)
        ips = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", out)
        if ips:
            return list(dict.fromkeys(ips))[:4]
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as f:
            return [ln.split()[1] for ln in f if ln.startswith("nameserver")][:4]
    except OSError:
        return []


def set_dns(servers: list[str]) -> tuple[bool, str]:
    if IS_WIN:
        if r := _need_admin():
            return r
        adapters = "Get-NetAdapter -Physical | Where-Object Status -eq 'Up'"
        if servers:
            sv = ",".join(f"'{s}'" for s in servers)
            code, out = run_ps(f"{adapters} | Set-DnsClientServerAddress -ServerAddresses @({sv}); ipconfig /flushdns",
                               timeout=60)
        else:
            code, out = run_ps(f"{adapters} | Set-DnsClientServerAddress -ResetServerAddresses; ipconfig /flushdns",
                               timeout=60)
        return code == 0, ("DNS alterado" if code == 0 else out[-300:])
    if not which("nmcli"):
        return False, "Precisa do NetworkManager (nmcli) para mudar o DNS."
    code, out = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"], timeout=15)
    conns = [ln.rsplit(":", 1)[0].replace("\\:", ":") for ln in out.splitlines()
             if ln and not ln.endswith((":loopback", ":bridge", ":tun", ":wireguard")) and "docker" not in ln
             and "virbr" not in ln]
    if not conns:
        return False, "Nenhuma ligação de rede ativa encontrada."
    msgs = []
    ok_all = True
    for c in conns:
        args = (["ipv4.dns", " ".join(servers), "ipv4.ignore-auto-dns", "yes"] if servers
                else ["ipv4.dns", "", "ipv4.ignore-auto-dns", "no"])
        code, out = run(["nmcli", "connection", "modify", c, *args], timeout=30)
        if code == 0:
            run(["nmcli", "connection", "up", c], timeout=60)  # reaplica (a ligação cai 1–2 s)
            msgs.append(c)
        else:
            ok_all = False
            msgs.append(f"{c}: {out}")
    return ok_all, "DNS alterado em: " + ", ".join(msgs)
