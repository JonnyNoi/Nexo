"""Recolha de informações do sistema (hardware e SO) para Linux e Windows."""
from __future__ import annotations

import glob
import json
import os
import platform
import re
import socket
import time

import psutil

from .util import (IS_LINUX, IS_WIN, as_list, human_bytes, human_duration, os_label,
                   ps_json, read_text, run, which)

Section = list[tuple[str, str]]


# =========================================================================== CPU
def cpu_model() -> str:
    if IS_LINUX:
        for line in read_text("/proc/cpuinfo").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    if IS_WIN:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or "Desconhecido"


def _cpu_section_linux() -> Section:
    rows: Section = [("Modelo", cpu_model())]
    rows.append(("Núcleos / threads", f"{psutil.cpu_count(False)} / {psutil.cpu_count(True)}"))
    f = psutil.cpu_freq()
    if f:
        rows.append(("Frequência (atual / máx.)", f"{f.current:.0f} MHz / {f.max:.0f} MHz"))
    code, out = run(["lscpu", "-J"], timeout=5) if which("lscpu") else (1, "")
    if code == 0:
        try:
            data = {d["field"].rstrip(":"): d["data"] for d in json.loads(out)["lscpu"]}
            for key, label in (("Vendor ID", "Fabricante"), ("Architecture", "Arquitetura"),
                               ("L1d cache", "Cache L1d"), ("L1i cache", "Cache L1i"),
                               ("L2 cache", "Cache L2"), ("L3 cache", "Cache L3"),
                               ("Virtualization", "Virtualização"),
                               ("Socket(s)", "Sockets")):
                if data.get(key):
                    rows.append((label, data[key]))
        except (ValueError, KeyError, TypeError):
            pass
    gov = read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if gov:
        rows.append(("Governor", gov))
    drv = read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_driver")
    if drv:
        rows.append(("Driver de frequência", drv))
    flags = ""
    for line in read_text("/proc/cpuinfo").splitlines():
        if line.startswith("flags"):
            flags = line.split(":", 1)[1]
            break
    ext = [x.upper() for x in ("sse4_2", "avx", "avx2", "avx512f", "aes", "sha_ni") if f" {x}" in flags]
    if ext:
        rows.append(("Instruções", ", ".join(ext).replace("_", ".")))
    return rows


def _cpu_section_win(wmi: dict) -> Section:
    rows: Section = []
    for p in as_list(wmi.get("cpu")):
        rows += [
            ("Modelo", (p.get("Name") or cpu_model()).strip()),
            ("Fabricante", p.get("Manufacturer") or ""),
            ("Núcleos / threads", f"{p.get('NumberOfCores')} / {p.get('NumberOfLogicalProcessors')}"),
            ("Frequência máx.", f"{p.get('MaxClockSpeed')} MHz"),
            ("Cache L2", human_bytes((p.get("L2CacheSize") or 0) * 1024)),
            ("Cache L3", human_bytes((p.get("L3CacheSize") or 0) * 1024)),
            ("Socket", p.get("SocketDesignation") or ""),
            ("Virtualização", "Ativa" if p.get("VirtualizationFirmwareEnabled") else "Desativada"),
        ]
    if not rows:
        rows.append(("Modelo", cpu_model()))
        rows.append(("Núcleos / threads", f"{psutil.cpu_count(False)} / {psutil.cpu_count(True)}"))
    return rows


# =========================================================================== GPU
_VENDORS = {"0x1002": "AMD", "0x10de": "NVIDIA", "0x8086": "Intel"}


def _pretty_gpu(vendor: str, device: str) -> str:
    """'Advanced Micro Devices, Inc. [AMD/ATI]' + 'Navi 24 [Radeon RX 6400/6500 XT/6500M]'
    -> 'AMD Radeon RX 6400/6500 XT/6500M (Navi 24)'"""
    v = "AMD" if "AMD" in vendor or "ATI" in vendor else "NVIDIA" if "NVIDIA" in vendor else \
        "Intel" if "Intel" in vendor else vendor
    m = re.match(r"(.*?)\s*\[(.+)\]\s*$", device)
    if m:
        chip, market = m.group(1).strip(), m.group(2).strip()
        return f"{v} {market}" + (f" ({chip})" if chip else "")
    return f"{v} {device}"


def list_gpus() -> list[dict]:
    """Lista de GPUs com nome, fabricante, VRAM e caminho sysfs (Linux)."""
    gpus: list[dict] = []
    if IS_LINUX:
        names = {}
        if which("lspci"):
            _, out = run(["lspci", "-mm", "-D"], timeout=5)
            for line in out.splitlines():
                parts = re.findall(r'"([^"]*)"', line)
                if len(parts) >= 3 and re.search(r"VGA|3D|Display", parts[0]):
                    addr = line.split()[0]
                    names[addr] = _pretty_gpu(parts[1], parts[2])
        for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
            dev = os.path.realpath(card + "/device")
            vendor = read_text(card + "/device/vendor")
            if not vendor:
                continue
            addr = os.path.basename(dev)
            g = {"name": names.get(addr, f"GPU {addr}"), "vendor": _VENDORS.get(vendor, vendor),
                 "sysfs": card + "/device", "pci": addr}
            vram = read_text(card + "/device/mem_info_vram_total")
            if vram.isdigit():
                g["vram"] = int(vram)
            g["driver"] = os.path.basename(os.path.realpath(card + "/device/driver"))
            gpus.append(g)
        if which("nvidia-smi"):
            code, out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,pci.bus_id",
                             "--format=csv,noheader,nounits"], timeout=5)
            if code == 0:
                gpus = [g for g in gpus if g["vendor"] != "NVIDIA"]
                for line in out.splitlines():
                    n, mem, drv, bus = [x.strip() for x in line.split(",")]
                    gpus.append({"name": n, "vendor": "NVIDIA", "vram": int(float(mem)) * 1024**2,
                                 "driver": f"nvidia {drv}", "pci": bus})
    return gpus


def _gpu_section_linux() -> Section:
    rows: Section = []
    for i, g in enumerate(list_gpus()):
        pre = f"GPU {i + 1} · " if i else ""
        rows.append((pre + "Modelo", g["name"]))
        rows.append((pre + "Fabricante", g["vendor"]))
        if g.get("vram"):
            rows.append((pre + "VRAM", human_bytes(g["vram"])))
        if g.get("driver"):
            rows.append((pre + "Driver", g["driver"]))
        if g.get("sysfs"):
            s = g["sysfs"]
            w = read_text(s + "/current_link_width")
            sp = read_text(s + "/current_link_speed")
            mw = read_text(s + "/max_link_width")
            if w:
                rows.append((pre + "PCIe (em uso / máx.)", f"x{w} {sp} / x{mw}"))
            vb = read_text(s + "/vbios_version")
            if vb:
                rows.append((pre + "VBIOS", vb))
    if which("glxinfo"):
        _, out = run(["glxinfo", "-B"], timeout=5)
        m = re.search(r"OpenGL core profile version string:\s*(.+)", out)
        if m:
            rows.append(("OpenGL", m.group(1)))
    if which("vulkaninfo"):
        _, out = run(["vulkaninfo", "--summary"], timeout=8)
        m = re.search(r"apiVersion\s*=\s*(\S+)", out)
        if m:
            rows.append(("Vulkan", m.group(1)))
    return rows or [("GPU", "Não detetada")]


def _gpu_section_win(wmi: dict) -> Section:
    rows: Section = []
    for i, g in enumerate(as_list(wmi.get("gpu"))):
        pre = f"GPU {i + 1} · " if i else ""
        rows += [
            (pre + "Modelo", g.get("Name") or ""),
            (pre + "Driver", f"{g.get('DriverVersion', '')}  ({str(g.get('DriverDate', ''))[:10]})"),
            (pre + "Resolução", f"{g.get('CurrentHorizontalResolution')}×{g.get('CurrentVerticalResolution')} "
                                f"@ {g.get('CurrentRefreshRate')} Hz"),
        ]
        ram = g.get("AdapterRAM")
        if ram:
            rows.append((pre + "VRAM (WMI, máx. 4 GB)", human_bytes(ram)))
    if which("nvidia-smi"):
        code, out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,pcie.link.gen.max,"
                         "pcie.link.width.max,power.limit", "--format=csv,noheader"], timeout=5)
        if code == 0:
            rows.append(("NVIDIA (nvidia-smi)", out.splitlines()[0]))
    return rows or [("GPU", "Não detetada")]


# =========================================================================== RAM
def _ram_section(wmi: dict | None = None) -> Section:
    vm = psutil.virtual_memory()
    try:
        sw = psutil.swap_memory()
        swap = f"{human_bytes(sw.used)} de {human_bytes(sw.total)}"
    except Exception:  # Windows com contadores de desempenho desativados
        swap = "indisponível"
    rows: Section = [
        ("Total", human_bytes(vm.total)),
        ("Em uso", f"{human_bytes(vm.total - vm.available)} ({vm.percent:.0f}%)"),
        ("Disponível", human_bytes(vm.available)),
        ("Swap / ficheiro de paginação", swap),
    ]
    if IS_LINUX:
        zram = glob.glob("/sys/block/zram*/disksize")
        if zram:
            rows.append(("zram", ", ".join(human_bytes(int(read_text(z) or 0)) for z in zram)))
        # dmidecode precisa de root; só tenta se já formos root
        if os.geteuid() == 0 and which("dmidecode"):
            _, out = run(["dmidecode", "-t", "17"], timeout=5)
            for block in out.split("Memory Device")[1:]:
                f = dict(re.findall(r"^\s*([^:\n]+):\s*(.+)$", block, re.M))
                if f.get("Size", "").startswith("No"):
                    continue
                rows.append((f"Módulo {f.get('Locator', '?')}",
                             f"{f.get('Size')} {f.get('Type', '')} {f.get('Configured Memory Speed', f.get('Speed', ''))} "
                             f"· {f.get('Manufacturer', '')} {f.get('Part Number', '').strip()}"))
    if wmi:
        types = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}
        for m in as_list(wmi.get("ram")):
            t = types.get(m.get("SMBIOSMemoryType"), "")
            rows.append((f"Módulo {m.get('DeviceLocator', '?')}",
                         f"{human_bytes(m.get('Capacity') or 0)} {t} {m.get('ConfiguredClockSpeed') or m.get('Speed')} MT/s"
                         f" · {(m.get('Manufacturer') or '').strip()} {(m.get('PartNumber') or '').strip()}"))
    rows.extend(_ram_speed_rows(wmi))
    return rows


def _ram_speed_rows(wmi: dict | None) -> Section:
    """Velocidade atual vs. a anunciada pelo módulo (XMP/EXPO desligado é muito comum)."""
    from . import ramspeed
    try:
        mods = ramspeed.parse_windows(wmi.get("ram")) if wmi else ramspeed.modules()
        if wmi:
            from .util import save_json
            save_json(ramspeed.CACHE, [m.__dict__ for m in mods])
        v = ramspeed.check(mods)
    except Exception:  # noqa: BLE001
        return []
    if not v:
        return []
    rows: Section = []
    if IS_LINUX and not (os.geteuid() == 0 and which("dmidecode")):   # com root o dmidecode já os listou
        for m in mods:
            rows.append((f"Módulo {m.slot}", f"{human_bytes(m.size)} {m.kind} {m.configured or '?'} MT/s · "
                                             f"{m.manufacturer} {m.part}".strip()))
    rows.append(("Velocidade", ("⚠ " if v.kind == "warn" else "") + v.text))
    return rows


def _display_section() -> Section:
    """Monitores: modo atual e se está abaixo da taxa de atualização máxima (144 Hz a correr a 60 Hz)."""
    from . import display
    try:
        mons = display.monitors()
    except Exception:  # noqa: BLE001
        return []
    rows: Section = []
    for m in mons:
        v = display.check(m)
        if v:
            rows.append((m.label, ("⚠ " if v.kind == "warn" else "") + v.text))
        elif m.max_hz:
            rows.append((m.label, f"Até {m.max_hz:.0f} Hz"))
    return rows


# =========================================================================== Placa-mãe
def _board_section_linux() -> Section:
    d = "/sys/class/dmi/id/"
    rows: Section = []
    for f, label in (("sys_vendor", "Fabricante do sistema"), ("product_name", "Modelo do sistema"),
                     ("board_vendor", "Fabricante da placa-mãe"), ("board_name", "Placa-mãe"),
                     ("board_version", "Revisão"), ("bios_vendor", "BIOS / UEFI"),
                     ("bios_version", "Versão do BIOS"), ("bios_date", "Data do BIOS")):
        v = read_text(d + f)
        if v and "O.E.M" not in v and "Default string" not in v:
            rows.append((label, v))
    rows.append(("Modo de arranque", "UEFI" if os.path.isdir("/sys/firmware/efi") else "Legacy/BIOS"))
    sb = glob.glob("/sys/firmware/efi/efivars/SecureBoot-*")
    if sb:
        try:
            with open(sb[0], "rb") as fh:
                rows.append(("Secure Boot", "Ativo" if fh.read()[-1] == 1 else "Inativo"))
        except OSError:
            pass
    return rows


def _board_section_win(wmi: dict) -> Section:
    rows: Section = []
    for b in as_list(wmi.get("board")):
        rows += [("Fabricante da placa-mãe", b.get("Manufacturer") or ""), ("Placa-mãe", b.get("Product") or ""),
                 ("Revisão", b.get("Version") or "")]
    for b in as_list(wmi.get("bios")):
        rows += [("BIOS / UEFI", b.get("Manufacturer") or ""),
                 ("Versão do BIOS", b.get("SMBIOSBIOSVersion") or ""),
                 ("Data do BIOS", str(b.get("ReleaseDate") or "")[:10])]
    for c in as_list(wmi.get("cs")):
        rows.insert(0, ("Modelo do sistema", f"{c.get('Manufacturer', '')} {c.get('Model', '')}"))
    return rows


# =========================================================================== SO
def _os_section(wmi: dict | None = None) -> Section:
    boot = psutil.boot_time()
    rows: Section = [
        ("Sistema operativo", os_label()),
        ("Kernel / build", platform.release() if IS_LINUX else platform.version()),
        ("Arquitetura", platform.machine()),
        ("Nome do computador", socket.gethostname()),
        ("Utilizador", os.environ.get("USER") or os.environ.get("USERNAME") or ""),
        ("Ligado há", human_duration(time.time() - boot)),
        ("Python", platform.python_version()),
    ]
    if IS_LINUX:
        de = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION")
        if de:
            rows.append(("Ambiente gráfico", f"{de} ({os.environ.get('XDG_SESSION_TYPE', '?')})"))
        for pm, cmd in (("pacman", ["pacman", "-Qq"]), ("dpkg", ["dpkg-query", "-f", ".\n", "-W"]),
                        ("rpm", ["rpm", "-qa"])):
            if which(cmd[0]):
                code, out = run(cmd, timeout=10)
                if code == 0:
                    rows.append((f"Pacotes ({pm})", str(len(out.splitlines()))))
                break
        if which("flatpak"):
            code, out = run(["flatpak", "list", "--app", "--columns=application"], timeout=10)
            if code == 0:
                rows.append(("Pacotes (flatpak)", str(len([x for x in out.splitlines() if x.strip()]))))
    if wmi:
        for o in as_list(wmi.get("os")):
            rows[0] = ("Sistema operativo", f"{o.get('Caption', '')} ({o.get('OSArchitecture', '')})")
            rows[1] = ("Versão / build", f"{o.get('Version', '')} build {o.get('BuildNumber', '')}")
            rows.append(("Instalado em", str(o.get("InstallDate") or "")[:10]))
    return rows


# =========================================================================== Discos
def physical_disks() -> list[dict]:
    disks = []
    if IS_LINUX and which("lsblk"):
        code, out = run(["lsblk", "-J", "-b", "-d", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE"], timeout=5)
        if code == 0:
            for d in json.loads(out).get("blockdevices", []):
                if d.get("type") != "disk" or d["name"].startswith(("zram", "loop")):
                    continue
                kind = "HDD" if d.get("rota") in (True, "1", 1) else ("NVMe SSD" if d["name"].startswith("nvme") else "SSD")
                if d.get("tran") == "usb":
                    kind += " (USB)"
                disks.append({"name": "/dev/" + d["name"], "model": (d.get("model") or "").strip(),
                              "size": int(d.get("size") or 0), "kind": kind})
    return disks


def _disk_section(wmi: dict | None = None) -> Section:
    rows: Section = []
    if wmi:
        for d in as_list(wmi.get("disk")):
            rows.append((f"Disco {d.get('Index', '')}",
                         f"{(d.get('Model') or '').strip()} · {human_bytes(d.get('Size') or 0)} · {d.get('InterfaceType', '')}"))
        for d in as_list(wmi.get("pdisk")):
            kinds = {3: "HDD", 4: "SSD"}
            bus = {17: "NVMe", 11: "SATA", 7: "USB"}
            rows.append((f"Físico · {d.get('FriendlyName', '')}",
                         f"{kinds.get(d.get('MediaType'), '?')} {bus.get(d.get('BusType'), '')} · saúde: {d.get('HealthStatus', '?')}"))
    else:
        for d in physical_disks():
            rows.append((d["name"], f"{d['model']} · {human_bytes(d['size'])} · {d['kind']}"))
    seen = set()
    for p in psutil.disk_partitions(all=False):
        # btrfs monta vários subvolumes do mesmo dispositivo: mostra só o primeiro
        if p.device in seen or p.fstype in ("squashfs", "tmpfs", "overlay") or "/snap/" in p.mountpoint:
            continue
        seen.add(p.device)
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue
        rows.append((f"Partição {p.mountpoint}",
                     f"{human_bytes(u.used)} / {human_bytes(u.total)} ({u.percent:.0f}%) · {p.fstype} · {p.device}"))
    return rows


# =========================================================================== Rede
def _net_section() -> Section:
    rows: Section = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if not st or not st.isup or name.startswith(("lo", "Loopback", "docker", "veth", "virbr")):
            continue
        ips = [a.address for a in addrs if a.family == socket.AF_INET]
        mac = [a.address for a in addrs if a.family == psutil.AF_LINK]
        speed = f"{st.speed} Mb/s" if st.speed else ""
        rows.append((name, " · ".join(x for x in (", ".join(ips), mac[0] if mac else "", speed) if x)))
    return rows


# =========================================================================== Windows WMI
_WMI_SCRIPT = r"""
$r = @{}
$r.os    = Get-CimInstance Win32_OperatingSystem | Select Caption,Version,BuildNumber,OSArchitecture,@{n='InstallDate';e={$_.InstallDate.ToString('yyyy-MM-dd')}}
$r.cs    = Get-CimInstance Win32_ComputerSystem | Select Manufacturer,Model
$r.cpu   = Get-CimInstance Win32_Processor | Select Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation,VirtualizationFirmwareEnabled
$r.ram   = Get-CimInstance Win32_PhysicalMemory | Select DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,Manufacturer,PartNumber,SMBIOSMemoryType
$r.gpu   = Get-CimInstance Win32_VideoController | Select Name,DriverVersion,@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}},AdapterRAM,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate
$r.board = Get-CimInstance Win32_BaseBoard | Select Manufacturer,Product,Version
$r.bios  = Get-CimInstance Win32_BIOS | Select Manufacturer,SMBIOSBIOSVersion,@{n='ReleaseDate';e={$_.ReleaseDate.ToString('yyyy-MM-dd')}}
$r.disk  = Get-CimInstance Win32_DiskDrive | Select Index,Model,Size,InterfaceType
try { $r.pdisk = Get-PhysicalDisk | Select FriendlyName,MediaType,BusType,HealthStatus } catch {}
$r
"""


def _wmi() -> dict:
    data = ps_json(_WMI_SCRIPT, timeout=60)
    return data if isinstance(data, dict) else {}


# =========================================================================== API pública
def collect() -> dict[str, Section]:
    """Devolve um dicionário ordenado {categoria: [(campo, valor), ...]}. Pode demorar alguns segundos."""
    data = _collect()
    if not data.get("Ecrã"):   # VM, sessão remota ou sem forma de ler os monitores
        data.pop("Ecrã", None)
    return data


def _collect() -> dict[str, Section]:
    if IS_WIN:
        w = _wmi()
        return {
            "Sistema": _os_section(w),
            "Processador": _cpu_section_win(w),
            "Memória": _ram_section(w),
            "Placa gráfica": _gpu_section_win(w),
            "Ecrã": _display_section(),
            "Placa-mãe / BIOS": _board_section_win(w),
            "Armazenamento": _disk_section(w),
            "Rede": _net_section(),
        }
    return {
        "Sistema": _os_section(),
        "Processador": _cpu_section_linux(),
        "Memória": _ram_section(),
        "Placa gráfica": _gpu_section_linux(),
        "Ecrã": _display_section(),
        "Placa-mãe / BIOS": _board_section_linux(),
        "Armazenamento": _disk_section(),
        "Rede": _net_section(),
    }


def summary() -> dict[str, str]:
    """Resumo rápido (sem chamadas lentas) para o painel."""
    gpus = list_gpus() if IS_LINUX else []
    gpu = gpus[0]["name"] if gpus else ""
    if IS_WIN:
        data = ps_json("Get-CimInstance Win32_VideoController | Select -First 1 Name", timeout=20)
        if isinstance(data, dict):
            gpu = data.get("Name", "")
    return {
        "os": os_label(),
        "cpu": cpu_model(),
        "threads": f"{psutil.cpu_count(False)}C / {psutil.cpu_count(True)}T",
        "ram": human_bytes(psutil.virtual_memory().total, 0),
        "gpu": gpu or "—",
    }


# =========================================================================== relatório (Informação → Exportar, nexo --relatorio)
def report_json(data: dict[str, Section]) -> str:
    import json
    return json.dumps({k: dict(v) for k, v in data.items()}, indent=2, ensure_ascii=False)


def report_html(data: dict[str, Section]) -> str:
    import html
    import time

    from .util import APP_NAME, APP_VERSION
    parts = [f"<!doctype html><meta charset='utf-8'><title>Relatório {APP_NAME}</title>"
             "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 16px;"
             "background:#0e1014;color:#e7e9ee}h1{color:#ff6b3d}h2{border-bottom:1px solid #2a2f3b;padding-bottom:6px}"
             "table{width:100%;border-collapse:collapse}td{padding:6px 8px;border-bottom:1px solid #1e222b;vertical-align:top}"
             "td:first-child{color:#8a92a6;width:35%}</style>",
             f"<h1>{APP_NAME} — relatório do sistema</h1><p>Gerado em {time.strftime('%d/%m/%Y %H:%M')} "
             f"pelo {APP_NAME} {APP_VERSION}</p>"]
    for cat, rows in data.items():
        parts.append(f"<h2>{html.escape(cat)}</h2><table>")
        parts += [f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in rows]
        parts.append("</table>")
    return "".join(parts)
