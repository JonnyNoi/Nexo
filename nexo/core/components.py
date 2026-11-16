"""Drivers e componentes em falta: o que impede o PC de render o que devia, mesmo com tudo atualizado.

Linux
  • Placa NVIDIA com o driver livre *nouveau* (ou sem driver) — nos jogos rende uma fração do driver da NVIDIA.
  • AMD/Intel sem driver **Vulkan** (vulkan-radeon / vulkan-intel / mesa-vulkan-drivers): sem ele o Proton,
    o DXVK e muitos jogos nativos não abrem.
  • Steam instalada (pacote do sistema) sem o driver Vulkan de **32 bits**: a Steam e muitos jogos Proton
    precisam dele.
  • **Microcode** da CPU em falta (intel-ucode / amd-ucode): correções de estabilidade e segurança do fabricante.
Windows
  • Placa gráfica no «Adaptador de Vídeo Básico da Microsoft» (sem driver nenhum).
  • Dispositivos com problema no Gestor de Dispositivos (sem driver, com erro…) — os desativados de propósito
    não contam.

Tudo é lido sem palavra-passe (consultas ao gestor de pacotes e ao sysfs/WMI). `gather()` recolhe os factos e
`evaluate()` decide — separados para os testes não dependerem da máquina."""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field

from .util import IS_LINUX, IS_WIN, as_list, load_json, ps_json, read_text, run, run_root, save_json, which

CACHE = "componentes.json"
MAX_AGE = 24 * 3600

# Código de erro do Gestor de Dispositivos → explicação curta (22 = desativado pelo utilizador: ignorado)
WIN_ERRORS = {
    1: "não está bem configurado",
    3: "o driver pode estar danificado",
    10: "não consegue arrancar",
    12: "não tem recursos livres",
    18: "o driver precisa de ser reinstalado",
    19: "configuração danificada no registo",
    28: "sem driver instalado",
    31: "o Windows não consegue carregar o driver",
    37: "o driver não arrancou",
    39: "o driver está danificado ou em falta",
    43: "o Windows parou o dispositivo porque reportou problemas",
    52: "a assinatura do driver não foi verificada",
}
WIN_IGNORE = {22, 45}   # desativado de propósito · desligado (dispositivo USB que não está ligado)

# pacotes por gestor: (vulkan AMD, vulkan Intel, lib32 AMD, lib32 Intel, lib32 NVIDIA, microcode Intel, AMD)
PKGS = {
    "pacman": {"vk_amd": ["vulkan-radeon", "amdvlk"], "vk_intel": ["vulkan-intel"],
               "vk32_amd": ["lib32-vulkan-radeon", "lib32-amdvlk"], "vk32_intel": ["lib32-vulkan-intel"],
               "vk32_nvidia": ["lib32-nvidia-utils"],
               "ucode_intel": ["intel-ucode"], "ucode_amd": ["amd-ucode"]},
    "dpkg": {"vk_amd": ["mesa-vulkan-drivers"], "vk_intel": ["mesa-vulkan-drivers"],
             "vk32_amd": ["mesa-vulkan-drivers:i386"], "vk32_intel": ["mesa-vulkan-drivers:i386"],
             "vk32_nvidia": [],
             "ucode_intel": ["intel-microcode"], "ucode_amd": ["amd64-microcode"]},
    "rpm": {"vk_amd": ["mesa-vulkan-drivers"], "vk_intel": ["mesa-vulkan-drivers"],
            "vk32_amd": ["mesa-vulkan-drivers.i686"], "vk32_intel": ["mesa-vulkan-drivers.i686"],
            "vk32_nvidia": [],
            "ucode_intel": [], "ucode_amd": []},   # Fedora/openSUSE já trazem o microcode com o firmware
}
INSTALL_CMD = {"pacman": "pacman -S --needed --noconfirm",
               "dpkg": "DEBIAN_FRONTEND=noninteractive apt-get install -y",
               "rpm": "dnf install -y"}


@dataclass
class Finding:
    id: str
    kind: str                 # warn | bad
    title: str
    detail: str
    packages: list[str] = field(default_factory=list)   # o Nexo pode instalá-los (Linux)
    command: str = ""         # comando sugerido para correr à mão (quando não convém instalar sozinho)
    action: str = ""          # "install" | "devmgmt" | ""


# --------------------------------------------------------------------------- recolha
def _pm() -> str | None:
    for pm, tool in (("pacman", "pacman"), ("dpkg", "dpkg-query"), ("rpm", "rpm")):
        if which(tool):
            return pm
    return None


def _installed(pm: str, names: list[str]) -> set[str]:
    """Quais destes pacotes estão instalados (uma consulta por pacote; são poucos)."""
    out = set()
    for n in dict.fromkeys(names):
        if pm == "pacman":
            code, _o = run(["pacman", "-Q", n], timeout=10)
        elif pm == "dpkg":
            code, o = run(["dpkg-query", "-W", "-f=${Status}", n], timeout=10)
            code = 0 if code == 0 and "install ok installed" in o else 1
        else:
            code, _o = run(["rpm", "-q", n], timeout=10)
        if code == 0:
            out.add(n)
    return out


def _cpu_vendor() -> str:
    for line in read_text("/proc/cpuinfo").splitlines():
        if line.startswith("vendor_id"):
            v = line.split(":", 1)[1].strip()
            return "Intel" if v == "GenuineIntel" else "AMD" if v == "AuthenticAMD" else v
    return ""


def gather() -> dict:
    """Factos do sistema para evaluate()."""
    if IS_WIN:
        gpus = as_list(ps_json("Get-CimInstance Win32_VideoController | Select Name", timeout=30))
        bad = as_list(ps_json("Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } "
                              "| Select Name,ConfigManagerErrorCode,PNPClass", timeout=60))
        return {"os": "windows", "win_gpus": [g.get("Name") or "" for g in gpus], "win_devices": bad}
    if not IS_LINUX:
        return {"os": "other"}
    from .sysinfo import list_gpus
    pm = _pm()
    names = [p for group in (PKGS.get(pm) or {}).values() for p in group]
    return {
        "os": "linux", "pm": pm,
        "gpus": [{"name": g.get("name", ""), "vendor": g.get("vendor", ""), "driver": g.get("driver", "")}
                 for g in list_gpus()],
        "installed": sorted(_installed(pm, names)) if pm else [],
        "steam_native": bool(which("steam")) and not os.path.realpath(which("steam") or "").startswith("/var/lib/flatpak"),
        "cpu_vendor": _cpu_vendor(),
        "chwd": bool(which("chwd")), "ubuntu_drivers": bool(which("ubuntu-drivers")),
        "rpmfusion": os.path.exists("/etc/yum.repos.d/rpmfusion-nonfree.repo"),
    }


# --------------------------------------------------------------------------- decisão
def _nvidia_cmd(facts: dict) -> str:
    if facts.get("chwd"):
        return "sudo chwd -a"
    if facts.get("ubuntu_drivers"):
        return "sudo ubuntu-drivers install"
    if facts.get("pm") == "rpm" and facts.get("rpmfusion"):
        return "sudo dnf install akmod-nvidia"
    if facts.get("pm") == "pacman":
        return "sudo pacman -S nvidia-open-dkms nvidia-utils lib32-nvidia-utils"
    return ""


def evaluate(facts: dict) -> list[Finding]:
    if facts.get("os") == "windows":
        return _evaluate_windows(facts)
    if facts.get("os") != "linux":
        return []
    out: list[Finding] = []
    pm = facts.get("pm")
    pk = PKGS.get(pm) or {}
    have = set(facts.get("installed") or [])
    gpus = facts.get("gpus") or []
    vendors = {g.get("vendor") for g in gpus}

    def missing(key: str) -> bool:
        alts = pk.get(key) or []
        return bool(alts) and not (have & set(alts))

    # NVIDIA sem o driver da NVIDIA
    for g in gpus:
        drv = (g.get("driver") or "").lower()
        if g.get("vendor") == "NVIDIA" and not drv.startswith("nvidia"):
            what = "o driver livre nouveau" if drv == "nouveau" else "nenhum driver"
            cmd = _nvidia_cmd(facts)
            detail = ("Com o nouveau, as placas NVIDIA recentes ficam presas a velocidades baixas e quase não "
                      "correm jogos. Instale o driver da NVIDIA com o comando abaixo e reinicie." if cmd else
                      "Com o nouveau, as placas NVIDIA recentes ficam presas a velocidades baixas e quase não "
                      "correm jogos. Instale o driver da NVIDIA pelo gestor de drivers da sua distribuição e "
                      "reinicie.")
            out.append(Finding("nvidia", "bad", f"A placa {g.get('name') or 'NVIDIA'} está a usar {what}",
                               detail, command=cmd))
            break

    # Vulkan (AMD/Intel)
    for vendor, key in (("AMD", "vk_amd"), ("Intel", "vk_intel")):
        if vendor in vendors and missing(key):
            pkg = pk[key][0]
            out.append(Finding(
                f"vulkan_{vendor.lower()}", "bad", f"Falta o driver Vulkan da placa {vendor}",
                "Sem ele, o Proton/DXVK e muitos jogos e programas recentes não abrem ou usam a CPU para desenhar.",
                packages=[pkg], action="install"))

    # 32 bits para a Steam
    if facts.get("steam_native"):
        for vendor, key in (("AMD", "vk32_amd"), ("Intel", "vk32_intel"), ("NVIDIA", "vk32_nvidia")):
            if vendor not in vendors or not missing(key):
                continue
            if vendor == "NVIDIA" and any(f.id == "nvidia" for f in out):
                continue   # primeiro o driver principal
            detail = ("A Steam e muitos jogos pelo Proton são de 32 bits: sem este pacote podem não abrir ou abrir "
                      "sem aceleração.")
            cmd = ""
            if pm == "dpkg":
                detail = ("A Steam e muitos jogos pelo Proton são de 32 bits: sem este pacote podem não abrir ou "
                          "abrir sem aceleração. Antes, é preciso ativar a arquitetura i386 (comando abaixo).")
                cmd = "sudo dpkg --add-architecture i386 && sudo apt update"
            out.append(Finding(
                f"vulkan32_{vendor.lower()}", "warn", f"Falta o driver Vulkan de 32 bits ({vendor}) para a Steam",
                detail, packages=[pk[key][0]], command=cmd, action="install"))

    # microcode
    cpu = facts.get("cpu_vendor")
    key = {"Intel": "ucode_intel", "AMD": "ucode_amd"}.get(cpu or "")
    if key and missing(key):
        out.append(Finding(
            "microcode", "warn", f"Falta o microcode da CPU {cpu}",
            "São correções do fabricante carregadas a cada arranque (estabilidade e segurança). Depois de instalar, "
            "reinicie; com o GRUB pode ser preciso regenerar a configuração (grub-mkconfig).",
            packages=[pk[key][0]], action="install"))
    return out


def _evaluate_windows(facts: dict) -> list[Finding]:
    out: list[Finding] = []
    basic = [n for n in facts.get("win_gpus") or [] if "basic display" in n.lower() or "vídeo básico" in n.lower()
             or "basic render" in n.lower()]
    if basic:
        out.append(Finding(
            "basic_display", "bad", "A placa gráfica está sem driver",
            "O Windows está a usar o «Adaptador de Vídeo Básico da Microsoft»: sem aceleração, resolução e "
            "frequência limitadas, jogos não abrem. Instale o driver da AMD, NVIDIA ou Intel (página Atualizações → "
            "Drivers) ou procure em Windows Update → Opções avançadas → Atualizações opcionais.",
            action="devmgmt"))
    devs = []
    for d in facts.get("win_devices") or []:
        try:
            code = int(d.get("ConfigManagerErrorCode") or 0)
        except (TypeError, ValueError):
            continue
        if code in WIN_IGNORE or not code:
            continue
        if d.get("PNPClass") == "Display" and basic:
            continue
        from .i18n import tr   # a lista é montada aqui: traduzir já cada parte
        devs.append(f"{d.get('Name') or tr('Dispositivo desconhecido')} "
                    f"({tr(WIN_ERRORS[code]) if code in WIN_ERRORS else tr('erro') + f' {code}'})")
    if devs:
        shown = "; ".join(devs[:5]) + ("; …" if len(devs) > 5 else "")
        out.append(Finding(
            "devices", "warn", f"{len(devs)} dispositivo(s) com problema no Gestor de Dispositivos",
            f"{shown}. Os dispositivos sem driver costumam resolver-se em Windows Update → Atualizações opcionais "
            "ou no site do fabricante da placa-mãe/portátil.", action="devmgmt"))
    return out


# --------------------------------------------------------------------------- API
def check() -> list[Finding]:
    res = evaluate(gather())
    try:
        save_json(CACHE, {"time": time.time(), "items": [asdict(f) for f in res]})
    except OSError:
        pass
    return res


def cached() -> dict:
    data = load_json(CACHE, {}) or {}
    return data if isinstance(data, dict) else {}


def cached_findings() -> list[Finding]:
    out = []
    for d in cached().get("items") or []:
        try:
            out.append(Finding(**d))
        except TypeError:
            continue
    return out


def due(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return now - float(cached().get("time") or 0) > MAX_AGE


def install(findings: list[Finding]) -> tuple[bool, str]:
    """Linux: instala os pacotes em falta de uma vez (um único pedido de palavra-passe)."""
    import shlex

    from . import changes, snapshot
    pm = _pm()
    pkgs = list(dict.fromkeys(p for f in findings if f.action == "install" for p in f.packages))
    if not pkgs:
        return False, "Nada para instalar."
    if pm not in INSTALL_CMD:
        return False, f"Gestor de pacotes não reconhecido — instale à mão: {' '.join(pkgs)}"
    cmd = INSTALL_CMD[pm] + " " + " ".join(shlex.quote(p) for p in pkgs)
    code, out = run_root(snapshot.with_snapshot(cmd, "instalar drivers em falta"), timeout=1800)
    if code != 0:
        lines = [x for x in (out or "").splitlines() if x.strip()]
        return False, " · ".join(lines[-3:]) or "falhou"
    try:
        changes.mark("driver", "Instalou " + ", ".join(pkgs))
    except Exception:  # noqa: BLE001 — o registo de alterações nunca pode estragar a instalação
        pass
    check()
    return True, f"Instalado: {', '.join(pkgs)}. Reinicie o PC para ter a certeza de que é usado."


def open_device_manager() -> None:
    from .systools import open_panel
    open_panel(["devmgmt.msc"])
