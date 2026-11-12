"""Drivers da placa gráfica: que versão está instalada e se há uma mais recente.

Linux
  • AMD/Intel: o driver do kernel (amdgpu/i915/xe) vem com o kernel; o que conta para os jogos é o
    **Mesa** (OpenGL/Vulkan). Compara-se a versão instalada com a última versão estável publicada
    (GitLab do Mesa) e com as atualizações pendentes da página Atualizações.
  • NVIDIA: versão do driver proprietário (nvidia-smi / /proc/driver/nvidia/version) e se o gestor de
    pacotes tem uma atualização à espera.
Windows
  • Win32_VideoController: versão e data do driver. Sem uma API pública dos fabricantes, o aviso usa a
    idade do driver (mais de 6 meses) e aponta para a página oficial de transferências.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field

from .util import APP_NAME, APP_VERSION, IS_LINUX, IS_WIN, as_list, ps_json, read_text, run, which

MESA_TAGS = "https://gitlab.freedesktop.org/api/v4/projects/176/repository/tags?per_page=40"
OLD_DAYS = 180
VENDOR_PAGES = {
    "AMD": "https://www.amd.com/pt/support/download/drivers.html",
    "NVIDIA": "https://www.nvidia.com/pt-br/drivers/",
    "Intel": "https://www.intel.com/content/www/us/en/support/detect.html",
}


@dataclass
class DriverInfo:
    gpu: str
    vendor: str
    component: str            # "Mesa", "NVIDIA", "Driver"
    version: str
    date: str = ""            # AAAA-MM-DD (Windows)
    latest: str = ""
    status: str = "unknown"   # ok | warn | unknown
    message: str = ""
    link: str = ""
    packages: list[str] = field(default_factory=list)   # nomes de pacotes a procurar nas atualizações


# --------------------------------------------------------------------------- versões instaladas
def _mesa_version() -> tuple[str, list[str]]:
    """(versão, pacotes) a partir do gestor de pacotes; senão do glxinfo."""
    probes = [
        (["pacman", "-Q", "mesa"], r"^mesa\s+(?:\d+:)?([\d.]+)", ["mesa", "lib32-mesa", "vulkan-radeon",
                                                                 "vulkan-intel"]),
        (["dpkg-query", "-W", "-f=${Version}", "libgl1-mesa-dri"], r"^(?:\d+:)?([\d.]+)",
         ["libgl1-mesa-dri", "mesa-vulkan-drivers"]),
        (["rpm", "-q", "--qf", "%{VERSION}", "mesa-dri-drivers"], r"^([\d.]+)", ["mesa-dri-drivers",
                                                                                  "mesa-vulkan-drivers"]),
        (["rpm", "-q", "--qf", "%{VERSION}", "Mesa"], r"^([\d.]+)", ["Mesa", "Mesa-dri"]),
    ]
    for cmd, rx, pkgs in probes:
        if not which(cmd[0]):
            continue
        code, out = run(cmd, timeout=10)
        m = re.search(rx, out.strip(), re.M) if code == 0 else None
        if m:
            return m.group(1).rstrip("."), pkgs
    if which("glxinfo"):
        _c, out = run(["glxinfo", "-B"], timeout=10)
        m = re.search(r"Mesa\s+([\d.]+)", out)
        if m:
            return m.group(1), []
    return "", []


def _nvidia_version() -> str:
    txt = read_text("/proc/driver/nvidia/version")
    m = re.search(r"Kernel Module(?: for x86_64)?\s+([\d.]+)", txt)
    if m:
        return m.group(1)
    if which("nvidia-smi"):
        code, out = run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], timeout=5)
        if code == 0 and out.strip():
            return out.strip().splitlines()[0].strip()
    return ""


def installed() -> list[DriverInfo]:
    out: list[DriverInfo] = []
    if IS_WIN:
        rows = as_list(ps_json("Get-CimInstance Win32_VideoController | Select Name,DriverVersion,"
                               "@{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}},"
                               "AdapterCompatibility", timeout=30))
        for r in rows:
            name = r.get("Name") or "Placa gráfica"
            if "basic display" in name.lower() or "remote" in name.lower():
                vendor = ""
            else:
                comp = f"{r.get('AdapterCompatibility') or ''} {name}"
                vendor = "AMD" if re.search(r"AMD|ATI|Radeon", comp, re.I) else \
                    "NVIDIA" if "nvidia" in comp.lower() else "Intel" if "intel" in comp.lower() else ""
            out.append(DriverInfo(name, vendor, "Driver", r.get("DriverVersion") or "", r.get("DriverDate") or "",
                                  link=VENDOR_PAGES.get(vendor, "")))
        return out
    if not IS_LINUX:
        return out
    from .sysinfo import list_gpus
    gpus = list_gpus()
    mesa_needed = [g for g in gpus if g.get("vendor") in ("AMD", "Intel") or
                   (g.get("driver") or "") in ("amdgpu", "radeon", "i915", "xe", "nouveau")]
    if mesa_needed:
        ver, pkgs = _mesa_version()
        out.append(DriverInfo(", ".join(g["name"] for g in mesa_needed), mesa_needed[0].get("vendor", ""), "Mesa",
                              ver, packages=pkgs, link="https://docs.mesa3d.org/relnotes.html"))
    nv = [g for g in gpus if g.get("vendor") == "NVIDIA" and "nouveau" not in (g.get("driver") or "")]
    if nv:
        out.append(DriverInfo(", ".join(g["name"] for g in nv), "NVIDIA", "NVIDIA", _nvidia_version(),
                              packages=["nvidia", "nvidia-dkms", "nvidia-open", "nvidia-open-dkms", "nvidia-utils",
                                        "nvidia-driver", "akmod-nvidia", "nvidia-580xx-dkms"],
                              link=VENDOR_PAGES["NVIDIA"]))
    return out


# --------------------------------------------------------------------------- comparação
def _vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def latest_mesa(timeout: float = 8) -> str:
    """Última versão estável do Mesa (sem -rc). Precisa de internet."""
    req = urllib.request.Request(MESA_TAGS, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL https fixa)
        tags = json.loads(r.read().decode("utf-8", "replace"))
    vers = [t["name"][5:] for t in tags if re.fullmatch(r"mesa-\d+\.\d+\.\d+", t.get("name", ""))]
    return max(vers, key=_vt) if vers else ""


def evaluate(drivers: list[DriverInfo], pending: list | None = None, online: bool = True,
             today: float | None = None) -> list[DriverInfo]:
    """Preenche status/message. pending = atualizações pendentes (updates.Update) da página Atualizações."""
    today = time.time() if today is None else today
    pend = {u.name: u for u in (pending or [])}
    mesa_latest = None
    for d in drivers:
        if not d.version:
            d.status, d.message = "unknown", "Não foi possível saber a versão instalada."
            continue
        up = next((pend[p] for p in d.packages if p in pend), None)
        if up is not None:
            d.status, d.latest = "warn", up.new
            d.message = (f"Há uma atualização à espera ({up.name} {up.new}) — instale-a na página Atualizações.")
            continue
        if d.component == "Mesa":
            if mesa_latest is None:
                try:
                    mesa_latest = latest_mesa() if online else ""
                except Exception:  # noqa: BLE001 — sem internet ou GitLab em baixo: não é grave
                    mesa_latest = ""
            d.latest = mesa_latest
            if not mesa_latest:
                d.status, d.message = "ok", "Sem atualizações pendentes no sistema."
            elif _vt(d.version)[:2] >= _vt(mesa_latest)[:2]:
                d.status, d.message = "ok", "Versão atual."
            else:
                behind = _vt(mesa_latest)[0] * 4 + _vt(mesa_latest)[1] - (_vt(d.version)[0] * 4 + _vt(d.version)[1])
                d.status = "warn" if behind >= 2 else "ok"
                d.message = (f"Já existe o Mesa {mesa_latest}. " +
                             ("A sua distribuição ainda não o tem ou o sistema não é atualizado há algum tempo — "
                              "versões novas trazem desempenho e correções para jogos recentes."
                              if behind >= 2 else "Chega normalmente à sua distribuição nas próximas semanas."))
            continue
        if d.component == "NVIDIA":
            d.status, d.message = "ok", "Sem atualizações pendentes no sistema."
            continue
        # Windows: idade do driver
        if d.date:
            try:
                age = (today - time.mktime(time.strptime(d.date, "%Y-%m-%d"))) / 86400
            except ValueError:
                age = None
            if age is None:
                d.status, d.message = "unknown", ""
            elif age > OLD_DAYS:
                d.status = "warn"
                d.message = (f"O driver tem {int(age // 30)} meses. "
                             + ("Os fabricantes lançam drivers novos com frequência (melhor desempenho em jogos "
                                "recentes) — procure a versão mais recente na página oficial."
                                if d.link else "Procure uma versão mais recente no Windows Update."))
            else:
                d.status, d.message = "ok", f"Driver recente ({int(age)} dias)."
        else:
            d.status, d.message = "unknown", "Data do driver desconhecida."
    return drivers


CACHE = "drivers.json"


def check(online: bool = True) -> list[DriverInfo]:
    from dataclasses import asdict

    from . import updates
    from .util import save_json
    res = evaluate(installed(), updates.items(updates.cached()), online)
    try:   # o painel (Saúde do PC) lê o último resultado sem voltar a verificar
        save_json(CACHE, {"time": time.time(), "items": [asdict(d) for d in res]})
    except OSError:
        pass
    return res

